"""Coding's scoped, inert Product binding for Plugin operation explanation."""

from __future__ import annotations

import os as os
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as replace
from pathlib import Path

from loushang.coding.composition.plan import CODING_PRODUCT_ID as CODING_PRODUCT_ID
from loushang.coding.harness.plugin_management import (
    operation_explanation as _evidence_programs,
)
from loushang.coding.package.epoch_layout import (
    coding_fenced_product_exists as coding_fenced_product_exists,
)
from loushang.coding.package.management_binding import (
    explain_coding_fenced_plugin_operation as explain_coding_fenced_plugin_operation,
)
from loushang.coding.package.management_binding import (
    read_coding_fenced_handoff_desired_commit as read_coding_fenced_handoff_desired_commit,
)
from loushang.coding.package.management_binding import (
    read_coding_fenced_package_handoff as read_coding_fenced_package_handoff,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.plugin_manager.operation_guidance import (
    project_coding_plugin_operation_guidance as project_coding_plugin_operation_guidance,
)
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationRequestV1,
    PluginOperationExplanationV1,
)

_OWNER_EVIDENCE_PROGRAM_VALUES = {
    "value_001": "Plugin operation explanation requires a typed request",
    "value_002": "plugin_explanation_scope_mismatch",
    "value_003": "plugin_explanation_platform_unsupported",
    "value_004": "plugin_explanation_product_not_fenced",
}


class CodingPluginOperationExplanationError(RuntimeError):
    def __init__(self, *, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingPluginOperationExplanationQuery:
    layout: CodingPluginLifecycleStateLayout
    workspace_guard: Callable[[], None] | None = None

    def explain_plugin_operation(
        self, request: PluginOperationExplanationRequestV1
    ) -> PluginOperationExplanationV1:
        return _evidence_programs.explain_operation(self, request)


def bind_coding_plugin_operation_explanation_query(
    cwd: str | Path,
    *,
    workspace_guard: Callable[[], None] | None = None,
) -> CodingPluginOperationExplanationQuery:
    if workspace_guard is not None:
        workspace_guard()
    workspace = Path(cwd).expanduser().resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("Plugin operation explanation workspace is unavailable")
    query = CodingPluginOperationExplanationQuery(
        layout=resolve_coding_plugin_lifecycle_state_layout(workspace),
        workspace_guard=workspace_guard,
    )
    if workspace_guard is not None:
        workspace_guard()
    return query


__all__ = [
    "CodingPluginOperationExplanationError",
    "CodingPluginOperationExplanationQuery",
    "bind_coding_plugin_operation_explanation_query",
]
