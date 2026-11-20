"""Coding's private, settings-locked pre-B Source configuration projection."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_local_migration import (
    _LegacySourceProjection,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _hold_windows_private_cutover_directory,
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


_source_projection = _LegacySourceProjection(
    product_id="coding",
    label="Coding",
    source_keys=_SOURCE_KEYS,
    key_markers=_SOURCE_KEY_MARKERS,
    projection_name=_PROJECTION_NAME,
    prefix="coding-pre-b-sources-",
    maximum_bytes=_MAX_SETTINGS_BYTES,
)


@contextmanager
def hold_coding_pre_b_source_configuration(
    settings_manager: SettingsManager,
    *,
    global_settings_path: Path,
    project_settings_path: Path,
    projection_parent: Path,
) -> Iterator[Path]:
    """Hold the frozen Source projection through the complete cutover scope."""
    with _source_projection.hold(
        settings_manager,
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
        projection_parent=projection_parent,
    ) as root:
        yield root


def read_coding_settings_patch_without_writes(
    path: Path,
) -> tuple[bool, str | None, dict[str, object]]:
    """Read a settings patch before a Product owner creates its first lock."""
    return _source_projection.read_patch(path)


def require_coding_fresh_settings_without_writes(*paths: Path) -> None:
    """Refuse legacy Plugin settings before SettingsManager writes lock files."""

    if coding_settings_have_pre_b_inputs_without_writes(*paths):
        raise RuntimeError(
            "Coding pre-B workspace is unsupported; use a fresh workspace"
        )


def coding_settings_have_pre_b_inputs_without_writes(*paths: Path) -> bool:
    """Recognize settings needing the compatible Session storage route."""

    return _source_projection.has_pre_fence_inputs(*paths)


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
