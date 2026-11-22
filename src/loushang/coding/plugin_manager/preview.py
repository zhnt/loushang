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
from loushang.harness.config.agent.types import ControlConfig as ControlConfig
from loushang.harness.config.store import read_optional_settings_leaf
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentPreviewRequestV1,
)

_MAX_SETTINGS_BYTES = 1024 * 1024


_DISABLED_SKILLS_REVISION_DOMAIN = b"loushang.coding.preview.disabled-skills/v1\x00"


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

        _check_workspace(self)
        _require_fence(self)
        try:
            settings = _capture_preview_settings(self.workspace)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise CodingCurrentPreviewError(
                code="plugin_preview_settings_unavailable"
            ) from exc
        _check_workspace(self)
        return dict(settings.capabilities)

    def owner_revisions(self) -> tuple[str, str, str]:
        """Read Product policy, authority, and Skill settings without composing."""

        _check_workspace(self)
        _require_fence(self)
        try:
            _disabled, settings_revision = _capture_disabled_skills(
                self.workspace
            )
            with CodingFencedProductReadOnlyPreviewOwner.open(
                self.layout, workspace_guard=self.workspace_guard
            ) as owner:
                policy_revision = owner.policy.policy_revision
                authority_revision = owner.policy.authority_revision
                owner.epoch_runtime.assert_current()
            _after, after_settings_revision = _capture_disabled_skills(
                self.workspace
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise CodingCurrentPreviewError(
                code="plugin_preview_owner_unavailable"
            ) from exc
        _check_workspace(self)
        if settings_revision != after_settings_revision:
            raise CodingCurrentPreviewError(code="plugin_preview_settings_stale")
        return policy_revision, authority_revision, settings_revision

    def preview_current(
        self, request: PluginCurrentPreviewRequestV1
    ) -> CodingCurrentDataResourcePreviewV1:
        _check_workspace(self)
        if not isinstance(request, PluginCurrentPreviewRequestV1):
            raise TypeError("Plugin current preview requires a typed request")
        if (
            request.product_id != CODING_PRODUCT_ID
            or request.scope_id != self.layout.scope_id
        ):
            raise CodingCurrentPreviewError(code="plugin_preview_scope_mismatch")
        _require_fence(self)
        if os.name != "posix":
            raise CodingCurrentPreviewError(
                code="plugin_preview_platform_unsupported"
            )
        try:
            resolve_coding_composition_set(request.composition_set_id)
        except (TypeError, ValueError) as exc:
            raise CodingCurrentPreviewError(
                code="plugin_preview_composition_invalid"
            ) from exc
        try:
            disabled_skills, settings_revision = _capture_disabled_skills(
                self.workspace
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise CodingCurrentPreviewError(
                code="plugin_preview_settings_unavailable"
            ) from exc
        _check_workspace(self)
        try:
            with CodingFencedProductReadOnlyPreviewOwner.open(
                self.layout, workspace_guard=self.workspace_guard
            ) as owner:
                preview = owner.preview_current_data_resources(
                    workspace=self.workspace,
                    composition_set_id=request.composition_set_id,
                    disabled_skills=disabled_skills,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise CodingCurrentPreviewError(
                code="plugin_preview_owner_unavailable"
            ) from exc
        try:
            _after_skills, after_revision = _capture_disabled_skills(
                self.workspace
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise CodingCurrentPreviewError(
                code="plugin_preview_settings_unavailable"
            ) from exc
        _check_workspace(self)
        gaps = set(preview.evidence_gaps)
        if settings_revision != after_revision:
            gaps.add("stale_snapshot")
        return replace(
            preview,
            disabled_skill_settings_revision=settings_revision,
            evidence_gaps=tuple(sorted(gaps)),
        )


def _check_workspace(query: CodingCurrentPreviewQuery) -> None:
    if query.workspace_guard is not None:
        query.workspace_guard()


def _require_fence(query: CodingCurrentPreviewQuery) -> None:
    if not coding_fenced_product_exists(query.layout):
        raise CodingCurrentPreviewError(
            code="plugin_preview_product_not_fenced"
        )


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

    settings = _capture_preview_settings(workspace)
    digest = sha256(_DISABLED_SKILLS_REVISION_DOMAIN)
    digest.update(
        json.dumps(
            settings.disabled_skills,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return settings.disabled_skills, f"sha256:{digest.hexdigest()}"


def _capture_preview_settings(workspace: Path) -> ControlConfig:
    """Read only declared settings bytes for preview and CLI choice inference."""

    settings = CONTROL_CONFIG_CODEC.default()
    for label, path in (
        ("global", default_global_settings_path()),
        ("project", default_project_settings_path(workspace)),
    ):
        body = _read_settings_bytes(path)
        if body is None:
            continue
        document = json.loads(body.decode("utf-8"))
        if not isinstance(document, dict):
            raise ValueError("Plugin preview settings must be a JSON object")
        result = CONTROL_CONFIG_CODEC.apply(settings, document, layer=label)
        if result.issues:
            raise ValueError("Plugin preview settings have invalid fields")
        settings = result.value
    return settings


def _read_settings_bytes(path: Path) -> bytes | None:
    return read_optional_settings_leaf(
        path,
        maximum_bytes=_MAX_SETTINGS_BYTES,
        unsafe_message="Plugin preview settings file is unsafe",
        oversized_message="Plugin preview settings file is too large",
    )


__all__ = [
    "CodingCurrentPreviewError",
    "CodingCurrentPreviewQuery",
    "bind_coding_current_preview_query",
]
