"""Coding's private, settings-locked pre-B Source configuration projection."""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.config.agent import SettingsManager
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_flush_directory,
    windows_flush_file,
    windows_rmdir_at,
    windows_stat_at,
    windows_unlink_at,
)

_SOURCE_KEYS = frozenset(
    {
        "disabled_plugins",
        "package_roots",
        "package_sources",
        "packages",
        "plugin_sources",
        "resource_roots",
    }
)
_PROJECTION_NAME = "coding-source-configuration.json"
_MAX_SETTINGS_BYTES = 4 * 1024 * 1024
_SOURCE_KEY_MARKERS = ("plugin", "package", "resource", "source")
_PRE_B_SETTINGS_KEYS = _SOURCE_KEYS | {"packages"}


@contextmanager
def hold_coding_pre_b_source_configuration(
    settings_manager: SettingsManager,
    *,
    global_settings_path: Path,
    project_settings_path: Path,
    projection_parent: Path,
) -> Iterator[Path]:
    """Keep real persistent Source patches stable through a native cutover.

    The yielded private directory is the snapshot owner's Source domain. Its
    content is a scope-preserving projection of the two actual settings files;
    settings transaction locks stay held until the caller exits this scope.
    """

    if os.name not in {"posix", "nt"} or (
        os.name == "posix"
        and not all(
            hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
        )
    ):
        raise RuntimeError("Rooted Source projection is unavailable")
    if not isinstance(settings_manager, SettingsManager):
        raise TypeError("Coding settings manager is required")
    expected_paths = (
        _require_path(global_settings_path, name="global settings"),
        _require_path(project_settings_path, name="project settings"),
    )
    if expected_paths[0] == expected_paths[1]:
        raise ValueError("Coding Source settings scopes overlap")
    parent = _require_private_parent(projection_parent)
    with settings_manager.transaction():
        observed_paths = (
            settings_manager.global_settings_path,
            settings_manager.project_settings_path,
        )
        if observed_paths != expected_paths:
            raise ValueError("Coding Source settings paths changed")
        session = settings_manager.get_session_settings()
        if any(_looks_like_source_key(key) for key in session):
            raise ValueError("Coding session Source overrides cannot be backed up")
        layers = {}
        for scope, path, patch in (
            ("global", expected_paths[0], settings_manager.get_global_settings()),
            ("project", expected_paths[1], settings_manager.get_project_settings()),
        ):
            present, raw_digest = _verify_loaded_settings(path, patch)
            if any(
                _looks_like_source_key(key) and key not in _SOURCE_KEYS for key in patch
            ):
                raise ValueError("Coding Source settings include an unmapped key")
            layers[scope] = {
                "present": present,
                "rawSha256": raw_digest,
                "settingsPath": str(path),
                "sourcePatch": {
                    key: patch[key] for key in sorted(_SOURCE_KEYS & patch.keys())
                },
            }
        contents = _canonical_bytes(
            {"productId": "coding", "projectionVersion": 1, "scopes": layers}
        )
        if os.name == "nt":
            with hold_coding_windows_private_cutover_directory(
                parent,
                prefix="coding-pre-b-sources-",
                projection_contents=contents,
            ) as source_root:
                yield source_root
        else:
            with TemporaryDirectory(prefix="coding-pre-b-sources-", dir=parent) as raw:
                source_root = Path(raw)
                _write_private_projection(source_root, contents)
                yield source_root


def _require_path(path: Path, *, name: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Coding {name} path is invalid")
    return path


def _require_private_parent(path: Path) -> Path:
    parent = _require_path(path, name="Source projection parent")
    if os.name == "nt":
        with WindowsPrivateDirectoryAcl() as acl:
            root = _PinnedWindowsAuthority.open(parent, read_control=True)
            try:
                acl.validate(root.descriptor)
                root.assert_visible()
            finally:
                root.close()
        return parent
    metadata = parent.lstat()
    getuid = getattr(os, "getuid", None)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or (callable(getuid) and metadata.st_uid != getuid())
    ):
        raise ValueError("Coding Source projection parent is not private")
    return parent


def _verify_loaded_settings(
    path: Path, loaded_patch: Mapping[str, object]
) -> tuple[bool, str | None]:
    present, digest, decoded = read_coding_settings_patch_without_writes(path)
    if decoded != loaded_patch:
        raise ValueError("Coding Source settings changed after reload")
    return present, digest


def read_coding_settings_patch_without_writes(
    path: Path,
) -> tuple[bool, str | None, dict[str, object]]:
    """Read a settings patch before a Product owner creates its first lock."""

    _require_path(path, name="settings")
    try:
        before = path.lstat()
    except FileNotFoundError:
        return False, None, {}
    getuid = getattr(os, "getuid", None)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or (callable(getuid) and before.st_uid != getuid())
        or before.st_size > _MAX_SETTINGS_BYTES
    ):
        raise ValueError("Coding Source settings file is unsafe")
    if os.name == "nt":
        parent = _PinnedWindowsAuthority.open(path.parent)
        try:
            descriptor = open_windows_regular_file_at(
                parent.descriptor,
                path.name,
                create_new=False,
                write=False,
            )
        except BaseException:
            parent.close()
            raise
    else:
        parent = None
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if _stable_file_identity(opened) != _stable_file_identity(before):
            raise ValueError("Coding Source settings changed during read")
        raw = bytearray()
        while chunk := os.read(descriptor, 64 * 1024):
            raw.extend(chunk)
            if len(raw) > _MAX_SETTINGS_BYTES:
                raise ValueError("Coding Source settings file exceeds budget")
        after = os.fstat(descriptor)
        visible = path.lstat()
        if _stable_file_identity(after) != _stable_file_identity(
            before
        ) or _stable_file_identity(visible) != _stable_file_identity(before):
            raise ValueError("Coding Source settings changed during read")
    finally:
        try:
            os.close(descriptor)
        finally:
            if parent is not None:
                try:
                    parent.assert_visible()
                finally:
                    parent.close()
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
        )
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Coding Source settings are not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("Coding Source settings must be an object")
    return True, sha256(raw).hexdigest(), decoded


def require_coding_fresh_settings_without_writes(*paths: Path) -> None:
    """Refuse legacy Plugin settings before SettingsManager writes lock files."""

    for path in paths:
        _, _, patch = read_coding_settings_patch_without_writes(path)
        for key in _PRE_B_SETTINGS_KEYS:
            if key not in patch:
                continue
            value = patch[key]
            if not isinstance(value, list) or value:
                raise RuntimeError(
                    "Coding pre-B workspace is unsupported; use a fresh workspace"
                )


def _stable_file_identity(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _looks_like_source_key(key: str) -> bool:
    return key in _SOURCE_KEYS or any(marker in key for marker in _SOURCE_KEY_MARKERS)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate settings key")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_private_projection(root: Path, contents: bytes) -> None:
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        descriptor = os.open(
            _PROJECTION_NAME,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=root_fd,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(contents)
                handle.flush()
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)


@contextmanager
def hold_coding_windows_private_cutover_directory(
    parent_path: Path,
    *,
    prefix: str,
    projection_contents: bytes | None = None,
) -> Iterator[Path]:
    """Hold one exact-ACL Windows temporary cutover directory until empty."""

    if os.name != "nt" or not prefix.startswith("coding-pre-b-"):
        raise ValueError("Coding Windows cutover directory is unavailable")
    name = prefix + secrets.token_hex(16)
    with WindowsPrivateDirectoryAcl() as acl:
        parent = _PinnedWindowsAuthority.open(parent_path, read_control=True)
        child: int | None = None
        child_identity: tuple[int, int] | None = None
        file_identity: tuple[int, int] | None = None
        try:
            acl.validate(parent.descriptor)
            child = open_windows_directory(
                name,
                dir_fd=parent.descriptor,
                create_new=True,
                share_delete=False,
                security_descriptor=acl.security_descriptor,
                read_control=True,
            )
            child_metadata = os.fstat(child)
            child_identity = child_metadata.st_dev, child_metadata.st_ino
            acl.validate(child)
            if projection_contents is not None:
                descriptor = open_windows_regular_file_at(
                    child,
                    _PROJECTION_NAME,
                    create_new=True,
                    write=True,
                    security_descriptor=acl.security_descriptor,
                    read_control=True,
                )
                try:
                    file_metadata = os.fstat(descriptor)
                    file_identity = file_metadata.st_dev, file_metadata.st_ino
                    acl.validate(descriptor)
                    remaining = memoryview(projection_contents)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if written < 1:
                            raise OSError(
                                "Coding Source projection write made no progress"
                            )
                        remaining = remaining[written:]
                    windows_flush_file(descriptor)
                finally:
                    os.close(descriptor)
            windows_flush_directory(child)
            windows_flush_directory(parent.descriptor)
            parent.assert_visible()
            yield parent_path / name
        finally:
            try:
                if child is not None:
                    try:
                        if file_identity is not None:
                            visible_file = windows_stat_at(child, _PROJECTION_NAME)
                            if (
                                visible_file.st_dev,
                                visible_file.st_ino,
                            ) != file_identity:
                                raise OSError("Coding Source projection file changed")
                            windows_unlink_at(child, _PROJECTION_NAME)
                            windows_flush_directory(child)
                    finally:
                        os.close(child)
                if child_identity is not None:
                    visible_child = windows_stat_at(parent.descriptor, name)
                    if (
                        visible_child.st_dev,
                        visible_child.st_ino,
                    ) != child_identity:
                        raise OSError("Coding Source projection directory changed")
                    windows_rmdir_at(parent.descriptor, name)
                    windows_flush_directory(parent.descriptor)
            finally:
                parent.close()


__all__ = [
    "hold_coding_pre_b_source_configuration",
    "hold_coding_windows_private_cutover_directory",
]
