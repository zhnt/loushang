"""Coding's read-only Product binding for current Plugin composition preview."""

from __future__ import annotations

import json as json
import os as os
import stat as stat
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as replace
from hashlib import sha256 as sha256
from pathlib import Path

from loushang.coding.composition.plan import CODING_PRODUCT_ID as CODING_PRODUCT_ID
from loushang.coding.composition.sets import (
    resolve_coding_composition_set as resolve_coding_composition_set,
)
from loushang.coding.control.settings_store import (
    default_global_settings_path as default_global_settings_path,
)
from loushang.coding.control.settings_store import (
    default_project_settings_path as default_project_settings_path,
)
from loushang.coding.harness.plugin_management import preview_snapshot as _programs
from loushang.coding.package.epoch_layout import (
    coding_fenced_product_exists as coding_fenced_product_exists,
)
from loushang.coding.package.product_preview import (
    CodingCurrentDataResourcePreviewV1,
)
from loushang.coding.package.product_preview import (
    CodingFencedProductReadOnlyPreviewOwner as CodingFencedProductReadOnlyPreviewOwner,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.config.agent._settings_codec import (
    CONTROL_CONFIG_CODEC as CONTROL_CONFIG_CODEC,
)
from loushang.harness.config.agent.types import ControlConfig
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentPreviewRequestV1,
)

_MAX_SETTINGS_BYTES = 1024 * 1024


_RUNTIME_PROGRAM_VALUES = {
    "value_001": "plugin_preview_product_not_fenced",
    "value_002": "plugin_preview_settings_unavailable",
    "value_003": "plugin_preview_settings_stale",
    "value_004": "plugin_preview_owner_unavailable",
    "value_005": "Plugin current preview requires a typed request",
    "value_006": "plugin_preview_scope_mismatch",
    "value_007": "plugin_preview_platform_unsupported",
    "value_008": "plugin_preview_composition_invalid",
    "value_009": "Plugin preview settings must be a JSON object",
    "value_010": "Plugin preview settings have invalid fields",
    "value_011": "Plugin preview settings file is unsafe",
    "value_012": "Plugin preview settings file is too large",
}

_RUNTIME_PROGRAM_BYTES = {
    "value_001": b"loushang.coding.preview.disabled-skills/v1\x00"
}


class CodingCurrentPreviewError(RuntimeError):
    """Finite, path-free Product failure for the read-only preview adapter."""

    def __init__(self, *, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingCurrentPreviewQuery:
    workspace: Path
    layout: CodingPluginLifecycleStateLayout
    workspace_guard: Callable[[], None] | None = None

    def configured_capabilities(self) -> dict[str, str]:
        """Read the CLI inference input under the same bounded settings policy."""

        return _programs.configured_capabilities(self)

    def owner_revisions(self) -> tuple[str, str, str]:
        """Read Product policy, authority, and Skill settings without composing."""

        return _programs.owner_revisions(self)

    def preview_current(
        self, request: PluginCurrentPreviewRequestV1
    ) -> CodingCurrentDataResourcePreviewV1:
        return _programs.preview_current(self, request)


def bind_coding_current_preview_query(
    cwd: str | Path, *, workspace_guard: Callable[[], None] | None = None
) -> CodingCurrentPreviewQuery:
    if workspace_guard is not None:
        workspace_guard()
    workspace = Path(cwd).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("Plugin current preview workspace is unavailable")
    query = CodingCurrentPreviewQuery(
        workspace=workspace,
        layout=resolve_coding_plugin_lifecycle_state_layout(workspace),
        workspace_guard=workspace_guard,
    )
    if workspace_guard is not None:
        workspace_guard()
    return query


def _capture_disabled_skills(workspace: Path) -> tuple[tuple[str, ...], str]:
    """Apply the Product codec without a lock; hash only the relevant projection."""

    return _programs.capture_disabled_resource_settings(workspace)


def _capture_preview_settings(workspace: Path) -> ControlConfig:
    """Read only declared settings bytes for preview and CLI choice inference."""

    return _programs.capture_preview_settings(workspace)


def _read_settings_bytes(path: Path) -> bytes | None:
    return _programs.read_settings_bytes(path)


__all__ = [
    "CodingCurrentPreviewError",
    "CodingCurrentPreviewQuery",
    "bind_coding_current_preview_query",
]
