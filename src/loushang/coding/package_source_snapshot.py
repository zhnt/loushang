"""Coding's private, settings-locked pre-B Source configuration projection."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.config.agent import SettingsManager
from loushang.harness.config.store import _read_stable_json_patch
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _hold_windows_private_cutover_directory,
    _PinnedWindowsAuthority,
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
    return _read_stable_json_patch(
        path,
        maximum_bytes=lambda: _MAX_SETTINGS_BYTES,
        label="Coding Source settings",
    )


def require_coding_fresh_settings_without_writes(*paths: Path) -> None:
    """Refuse legacy Plugin settings before SettingsManager writes lock files."""

    if coding_settings_have_pre_b_inputs_without_writes(*paths):
        raise RuntimeError(
            "Coding pre-B workspace is unsupported; use a fresh workspace"
        )


def coding_settings_have_pre_b_inputs_without_writes(*paths: Path) -> bool:
    """Recognize settings needing the compatible Session storage route."""

    for path in paths:
        _, _, patch = read_coding_settings_patch_without_writes(path)
        for key in _PRE_B_SETTINGS_KEYS:
            if key not in patch:
                continue
            value = patch[key]
            if not isinstance(value, list) or value:
                return True
    return False


def _looks_like_source_key(key: str) -> bool:
    return key in _SOURCE_KEYS or any(marker in key for marker in _SOURCE_KEY_MARKERS)


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
    with _hold_windows_private_cutover_directory(
        parent_path,
        prefix=prefix,
        projection_name=_PROJECTION_NAME,
        projection_label="Coding Source projection",
        projection_contents=projection_contents,
    ) as directory:
        yield directory


__all__ = [
    "hold_coding_pre_b_source_configuration",
    "hold_coding_windows_private_cutover_directory",
]
