"""Coding's scoped, inert Product binding for Plugin operation explanation."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_product_management_cli import (
    coding_fenced_product_exists,
    explain_coding_fenced_plugin_operation,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationRequestV1,
    PluginOperationExplanationV1,
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
        if self.workspace_guard is not None:
            self.workspace_guard()
        if not isinstance(request, PluginOperationExplanationRequestV1):
            raise TypeError("Plugin operation explanation requires a typed request")
        if (
            request.product_id != CODING_PRODUCT_ID
            or request.scope_id != self.layout.scope_id
        ):
            raise CodingPluginOperationExplanationError(
                code="plugin_explanation_scope_mismatch"
            )
        if os.name != "posix":
            raise CodingPluginOperationExplanationError(
                code="plugin_explanation_platform_unsupported"
            )
        if not coding_fenced_product_exists(self.layout):
            raise CodingPluginOperationExplanationError(
                code="plugin_explanation_product_not_fenced"
            )
        return explain_coding_fenced_plugin_operation(
            self.layout,
            request.operation_id,
            correlation_id=request.correlation_id,
            workspace_guard=self.workspace_guard,
        )


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
