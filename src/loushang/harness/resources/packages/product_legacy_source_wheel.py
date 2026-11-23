"""Recapture admitted legacy Product Source bytes outside the lifecycle kernel.

The original RevisionStore capture and cleanup retain their exact ordering;
only the later Product policy may authorize the resulting Wheel candidate.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import TypeVar

from loushang.harness.resources.packages.plugin_lifecycle._exact_product_source import (
    _pack_product_wheel_members,
)
from loushang.harness.resources.plugins.dependencies import PluginDependencyClosureLock

_LEGACY_SOURCE_MAX_ENTRIES = 128
_LEGACY_SOURCE_MAX_FILES = 64
_LEGACY_SOURCE_MAX_FILE_BYTES = 256 * 1024
_LEGACY_SOURCE_MAX_CONTENT_BYTES = 1024 * 1024
_LEGACY_SOURCE_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LegacyWheelT = TypeVar("_LegacyWheelT")
_LegacyWheelValues = tuple[str, str, str, str, str, str, str, str, bytes]


def legacy_source_wheel_prefix(plugin_id: str, content_digest: str) -> str:
    digest = sha256(f"{plugin_id}\0{content_digest}".encode()).hexdigest()
    return f"loushang_legacy_{digest[:24]}"


def _reacquire_legacy_local_plugin_wheel(
    source_root: Path,
    *,
    legacy_package_root: Path,
    staging_parent: Path,
    plugin_id: str,
    expected_source_identity: str,
    expected_content_digest: str,
    expected_manifest_digest: str,
    expected_dependency_lock: PluginDependencyClosureLock,
    result_factory: Callable[[_LegacyWheelValues], _LegacyWheelT],
) -> _LegacyWheelT:
    """Recapture admitted original Source bytes; this grants no Product authority."""
    if os.name != "posix":
        raise RuntimeError("POSIX local Plugin Source reacquisition is required")
    if not isinstance(plugin_id, str) or _SAFE_ID.fullmatch(plugin_id) is None:
        raise ValueError("Legacy Plugin identity is invalid")
    if any(
        not isinstance(value, str) or _SHA256.fullmatch(value) is None
        for value in (expected_content_digest, expected_manifest_digest)
    ):
        raise ValueError("Legacy Plugin revision evidence is invalid")
    if (
        not isinstance(expected_dependency_lock, PluginDependencyClosureLock)
        or expected_dependency_lock.package_content_digest != expected_content_digest
        or expected_dependency_lock.python_distributions
    ):
        raise ValueError("Legacy Plugin dependency closure is unsupported")

    from loushang.harness.resources.plugins.locators import (
        canonical_plugin_relative_path,
    )
    from loushang.harness.resources.plugins.manifest import PluginManifestParser
    from loushang.harness.resources.plugins.revisions import PluginRevisionStore

    source = _canonical_legacy_source_directory(
        source_root, name="original Plugin Source"
    )
    original_source_identity = f"local:{source}"
    if expected_source_identity != original_source_identity:
        raise ValueError("Legacy Plugin Source identity changed")
    legacy = _canonical_legacy_source_directory(
        legacy_package_root, name="legacy Package root"
    )
    if source == legacy or source.is_relative_to(legacy):
        raise ValueError("Legacy Package Store bytes cannot be reacquired as Source")
    parent = _private_legacy_staging_parent(staging_parent)
    if (
        parent == legacy
        or parent.is_relative_to(legacy)
        or parent == source
        or parent.is_relative_to(source)
    ):
        raise ValueError("Legacy Source staging overlaps protected inputs")
    stage = Path(tempfile.mkdtemp(prefix="legacy-local-source-", dir=parent))
    try:
        _require_bounded_legacy_source_tree(source)
        package = PluginManifestParser().parse(source)
        if package.manifest_path is None or package.manifest.name != plugin_id:
            raise ValueError("Legacy Plugin Source manifest identity changed")
        published = PluginRevisionStore(stage / "revisions").publish(package)
        handle = published.revision_handle
        try:
            if (
                published.content_digest != expected_content_digest
                or published.manifest_digest != expected_manifest_digest
            ):
                raise ValueError("Legacy Plugin Source revision changed")
            handle.verify()
            prefix = legacy_source_wheel_prefix(plugin_id, expected_content_digest)
            files: dict[str, bytes] = {}
            total_bytes = 0
            paths = sorted(published.root.rglob("*"))
            if len(paths) > _LEGACY_SOURCE_MAX_ENTRIES:
                raise ValueError("Legacy Plugin Source exceeds entry budget")
            regular_paths = tuple(path for path in paths if not path.is_dir())
            if any(
                not any(file.is_relative_to(directory) for file in regular_paths)
                for directory in paths
                if directory.is_dir()
            ):
                raise ValueError("Legacy Plugin Source contains an empty directory")
            for path in regular_paths:
                relative = path.relative_to(published.root).as_posix()
                canonical_plugin_relative_path(relative)
                if any(part.endswith(".dist-info") for part in Path(relative).parts):
                    raise ValueError("Legacy Plugin Source contains Wheel metadata")
                if len(files) >= _LEGACY_SOURCE_MAX_FILES:
                    raise ValueError("Legacy Plugin Source exceeds file budget")
                with handle.open_file(relative) as stream:
                    body = stream.read(_LEGACY_SOURCE_MAX_FILE_BYTES + 1)
                total_bytes += len(body)
                if (
                    len(body) > _LEGACY_SOURCE_MAX_FILE_BYTES
                    or total_bytes > _LEGACY_SOURCE_MAX_CONTENT_BYTES
                ):
                    raise ValueError("Legacy Plugin Source exceeds byte budget")
                files[f"{prefix}/{relative}"] = body
            handle.verify()
            manifest_path = f"{prefix}/plugin.json"
            if manifest_path not in files:
                raise ValueError("Legacy Plugin Source manifest is missing")
            parsed = PluginManifestParser().parse_file_set(
                files, manifest_logical_path=manifest_path
            )
            if parsed.name != plugin_id:
                raise ValueError("Legacy Plugin Source manifest identity changed")
            distribution = prefix.replace("_", "-")
            wheel = _build_legacy_source_wheel(
                prefix, distribution, files, published.root
            )
            if len(wheel) > _LEGACY_SOURCE_MAX_WHEEL_BYTES:
                raise ValueError("Legacy Plugin Wheel exceeds byte budget")
            handle.verify()
            return result_factory(
                (
                    plugin_id,
                    original_source_identity,
                    expected_content_digest,
                    expected_manifest_digest,
                    f"{distribution}==1",
                    manifest_path,
                    f"{prefix}-1-py3-none-any.whl",
                    sha256(wheel).hexdigest(),
                    wheel,
                ),
            )
        finally:
            handle.close()
    finally:
        _remove_private_legacy_stage(stage)


def _canonical_legacy_source_directory(path: Path, *, name: str) -> Path:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or ".." in path.parts
        or path != path.resolve(strict=True)
        or not path.is_dir()
    ):
        raise ValueError(f"{name} is not a canonical directory")
    return path


def _private_legacy_staging_parent(path: Path) -> Path:
    parent = _canonical_legacy_source_directory(
        path, name="legacy Source staging parent"
    )
    metadata = parent.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_uid != os.geteuid()
    ):
        raise ValueError("Legacy Source staging parent is not private")
    return parent


def _require_bounded_legacy_source_tree(source: Path) -> None:
    entry_count = 0
    byte_count = 0
    for directory, dirs, files in os.walk(
        source, followlinks=False, onerror=_raise_legacy_source_os_error
    ):
        if Path(directory) == source:
            dirs[:] = [name for name in dirs if name != ".git"]
            files = [name for name in files if name != ".git"]
        for name in (*dirs, *files):
            path = Path(directory) / name
            metadata = path.lstat()
            entry_count += 1
            if entry_count > _LEGACY_SOURCE_MAX_ENTRIES:
                raise ValueError("Legacy Plugin Source exceeds entry budget")
            if stat.S_ISREG(metadata.st_mode):
                if metadata.st_size > _LEGACY_SOURCE_MAX_FILE_BYTES:
                    raise ValueError("Legacy Plugin Source exceeds file budget")
                byte_count += metadata.st_size
                if byte_count > _LEGACY_SOURCE_MAX_CONTENT_BYTES:
                    raise ValueError("Legacy Plugin Source exceeds byte budget")
            elif not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("Legacy Plugin Source contains an unsafe entry")


def _raise_legacy_source_os_error(error: OSError) -> None:
    raise error


def _build_legacy_source_wheel(
    prefix: str, distribution: str, files: dict[str, bytes], root: Path
) -> bytes:
    dist_info = f"{prefix}-1.dist-info"
    files[f"{dist_info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1\n\n"
    ).encode()
    files[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\n"
        b"Generator: loushang-legacy-local-source\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n\n"
    )
    record_name = f"{dist_info}/RECORD"
    return _pack_product_wheel_members(
        files,
        get_record_name=lambda: record_name,
        executable_source=(prefix, root),
    )


def _remove_private_legacy_stage(stage: Path) -> None:
    for directory, _children, _files in os.walk(stage, topdown=False):
        Path(directory).chmod(0o700)
    shutil.rmtree(stage)


class _LegacyLocalWheelFields:
    """Inert recapture facts and inspection shared with nominal Product adapters."""

    __slots__ = ()

    plugin_id: str
    original_source_identity: str
    source_content_digest: str
    manifest_digest: str
    requested_package: str
    plugin_manifest_path: str
    filename: str
    artifact_digest: str
    wheel_bytes: bytes
