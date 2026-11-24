"""Coding's scoped, inert Product binding for Plugin operation explanation."""

from __future__ import annotations

import os as os
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as replace
from pathlib import Path

from loushang.coding.composition.plan import CODING_PRODUCT_ID as CODING_PRODUCT_ID
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
    observe_partial_handoff_desired_commit,
)
from loushang.harness.workspace.paths import (
    WorkspaceOperationGuard,
    require_workspace_directory,
)


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
        with WorkspaceOperationGuard(self.workspace_guard):
            if not isinstance(request, PluginOperationExplanationRequestV1):
                raise TypeError('Plugin operation explanation requires a typed request')
            if (
                request.product_id != CODING_PRODUCT_ID
                or request.scope_id != self.layout.scope_id
            ):
                raise CodingPluginOperationExplanationError(
                    code='plugin_explanation_scope_mismatch'
                )
            if os.name != "posix":
                raise CodingPluginOperationExplanationError(
                    code='plugin_explanation_platform_unsupported'
                )
            if not coding_fenced_product_exists(self.layout):
                raise CodingPluginOperationExplanationError(
                    code='plugin_explanation_product_not_fenced'
                )
            explanation = explain_coding_fenced_plugin_operation(
                self.layout,
                request.operation_id,
                correlation_id=request.correlation_id,
                workspace_guard=self.workspace_guard,
            )
            explanation = observe_partial_handoff_desired_commit(
                explanation,
                operation_id=request.operation_id,
                read_handoff=lambda operation_id: read_coding_fenced_package_handoff(
                    self.layout, operation_id
                ),
                read_commit=lambda handoff: read_coding_fenced_handoff_desired_commit(
                    self.layout, handoff
                ),
            )
        guidance = project_coding_plugin_operation_guidance(explanation.to_dict())
        repair = guidance["repairCommand"]
        assert repair is None or isinstance(repair, str)
        return replace(explanation, repair_command=repair)


def bind_coding_plugin_operation_explanation_query(
    cwd: str | Path,
    *,
    workspace_guard: Callable[[], None] | None = None,
) -> CodingPluginOperationExplanationQuery:
    with WorkspaceOperationGuard(workspace_guard):
        workspace = require_workspace_directory(
            cwd, unavailable="Plugin operation explanation workspace is unavailable"
        )
        return CodingPluginOperationExplanationQuery(
            layout=resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace_guard=workspace_guard,
        )


__all__ = [
    "CodingPluginOperationExplanationError",
    "CodingPluginOperationExplanationQuery",
    "bind_coding_plugin_operation_explanation_query",
]
