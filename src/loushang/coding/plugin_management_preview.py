"""Coding's read-only Product binding for current Plugin composition preview."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.config.agent._settings_codec import CONTROL_CONFIG_CODEC
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentPreviewRequestV1,
)

from ._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from .composition_sets import resolve_coding_composition_set
from .control.settings_store import (
    default_global_settings_path,
    default_project_settings_path,
)
from .package_product_management_cli import coding_fenced_product_exists
from .package_product_preview import (
    CodingCurrentDataResourcePreviewV1,
    CodingFencedProductReadOnlyPreviewOwner,
)
from .product_plan import CODING_PRODUCT_ID

_MAX_SETTINGS_BYTES = 1024 * 1024


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

    def preview_current(
        self, request: PluginCurrentPreviewRequestV1
    ) -> CodingCurrentDataResourcePreviewV1:
        if self.workspace_guard is not None:
            self.workspace_guard()
        if not isinstance(request, PluginCurrentPreviewRequestV1):
            raise TypeError("Plugin current preview requires a typed request")
        if (
            request.product_id != CODING_PRODUCT_ID
            or request.scope_id != self.layout.scope_id
        ):
            raise CodingCurrentPreviewError(code="plugin_preview_scope_mismatch")
        if not coding_fenced_product_exists(self.layout):
            raise CodingCurrentPreviewError(code="plugin_preview_product_not_fenced")
        if os.name != "posix":
            raise CodingCurrentPreviewError(code="plugin_preview_platform_unsupported")
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
        if self.workspace_guard is not None:
            self.workspace_guard()
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
            _after_skills, after_revision = _capture_disabled_skills(self.workspace)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise CodingCurrentPreviewError(
                code="plugin_preview_settings_unavailable"
            ) from exc
        if self.workspace_guard is not None:
            self.workspace_guard()
        gaps = set(preview.evidence_gaps)
        if settings_revision != after_revision:
            gaps.add("stale_snapshot")
        return replace(
            preview,
            disabled_skill_settings_revision=settings_revision,
            evidence_gaps=tuple(sorted(gaps)),
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
    digest = sha256(b"loushang.coding.preview.disabled-skills/v1\0")
    digest.update(json.dumps(
        settings.disabled_skills,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8"))
    return settings.disabled_skills, f"sha256:{digest.hexdigest()}"


def _read_settings_bytes(path: Path) -> bytes | None:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
        )
    except FileNotFoundError:
        return None
    try:
        opened = os.fstat(descriptor)
        visible = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
            or opened.st_size > _MAX_SETTINGS_BYTES
        ):
            raise ValueError("Plugin preview settings file is unsafe")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(_MAX_SETTINGS_BYTES + 1)
        if len(body) > _MAX_SETTINGS_BYTES:
            raise ValueError("Plugin preview settings file is too large")
        return body
    finally:
        os.close(descriptor)


__all__ = [
    "CodingCurrentPreviewError",
    "CodingCurrentPreviewQuery",
    "bind_coding_current_preview_query",
]
