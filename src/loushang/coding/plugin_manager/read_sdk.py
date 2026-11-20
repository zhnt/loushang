"""Local read-only Coding Plugin management SDK over scoped Harness queries.

This module is separate from the public Plugin *author* SDK. Opening a client
does not activate Product state, create a Session, or grant command authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.harness.plugin_management import support_read as _programs
from loushang.coding.package.management_binding import (
    build_coding_fenced_product_management_cli_ports as build_coding_fenced_product_management_cli_ports,
)
from loushang.coding.plugin_manager.binding import (
    build_coding_plugin_management_cli_read_binding,
)
from loushang.coding.plugin_manager.explanation import (
    bind_coding_plugin_operation_explanation_query,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.plugin_manager.preview import (
    bind_coding_current_preview_query,
)
from loushang.harness.plugin_management.application import (
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
)
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentPreviewRequestV1,
    project_plugin_current_preview,
)
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationRequestV1,
    project_plugin_operation_explanation,
)
from loushang.harness.workspace.paths import assert_workspace_directory_identity

_RUNTIME_PROGRAM_VALUES = {
    "value_001": "Plugin support Desired State revision is invalid",
    "value_002": "Plugin support Product evidence gaps are invalid",
}


class CodingPluginManagementReadSdkError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingPluginManagementReadClientV1:
    workspace: Path
    layout: CodingPluginLifecycleStateLayout
    workspace_identity: tuple[int, int]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workspace, Path)
            or not self.workspace.is_absolute()
            or self.workspace != self.workspace.resolve(strict=True)
            or not isinstance(self.layout, CodingPluginLifecycleStateLayout)
            or self.layout
            != resolve_coding_plugin_lifecycle_state_layout(self.workspace)
            or type(self.workspace_identity) is not tuple
            or len(self.workspace_identity) != 2
            or any(
                type(item) is not int or item < 0 for item in self.workspace_identity
            )
        ):
            raise ValueError("Coding management read workspace is invalid")

    @property
    def product_id(self) -> str:
        return CODING_PRODUCT_ID

    @property
    def installation_scope(self) -> Literal["workspace"]:
        return "workspace"

    @property
    def scope_id(self) -> str:
        return self.layout.scope_id

    def snapshot(self, query: PluginManagementQueryV1) -> PluginManagementProjectionV1:
        return _programs.read_fenced_snapshot(self, query)

    def management_snapshot(
        self,
        *,
        correlation_id: str,
        settings_manager: object | None = None,
        plugin_ids: tuple[str, ...] = (),
    ) -> dict[str, object]:
        """Read the management owner projection without startup or repair."""

        self._assert_workspace_identity()
        binding = build_coding_plugin_management_cli_read_binding(
            self.workspace,
            settings_manager,
            workspace_identity=self.workspace_identity,
        )
        if binding.scope_id != self.layout.scope_id:
            raise ValueError("Plugin management read changed workspace scope")
        projection = binding.query(
            correlation_id=correlation_id,
            plugin_ids=plugin_ids,
        ).to_dict()
        self._assert_workspace_identity()
        return projection

    def preview_current(
        self,
        *,
        correlation_id: str,
        composition_set_id: str = "coding-standard",
    ) -> dict[str, object]:
        self._assert_workspace_identity()
        preview = project_plugin_current_preview(
            bind_coding_current_preview_query(
                self.workspace, workspace_guard=self._assert_workspace_identity
            ),
            PluginCurrentPreviewRequestV1(
                correlation_id=correlation_id,
                product_id=CODING_PRODUCT_ID,
                scope_id=self.layout.scope_id,
                composition_set_id=composition_set_id,
            ),
        )
        self._assert_workspace_identity()
        return preview

    def support_status(
        self,
        *,
        correlation_id: str,
        composition_set_id: str = "coding-standard",
    ) -> dict[str, object]:
        """Join management and Product preview without asserting Session use."""

        return _programs.support_status(
            self, correlation_id=correlation_id, composition_set_id=composition_set_id
        )

    def explain_operation(
        self,
        operation_id: str,
        *,
        correlation_id: str,
    ) -> dict[str, object]:
        self._assert_workspace_identity()
        explanation = project_plugin_operation_explanation(
            bind_coding_plugin_operation_explanation_query(
                self.workspace, workspace_guard=self._assert_workspace_identity
            ),
            PluginOperationExplanationRequestV1(
                correlation_id=correlation_id,
                product_id=CODING_PRODUCT_ID,
                scope_id=self.layout.scope_id,
                operation_id=operation_id,
            ),
        )
        self._assert_workspace_identity()
        return explanation

    def _assert_workspace_identity(self) -> None:
        assert_workspace_directory_identity(
            self.workspace,
            self.workspace_identity,
            changed=lambda: CodingPluginManagementReadSdkError(
                "Coding management workspace changed",
                code="coding_management_workspace_changed",
            ),
        )

    def assert_workspace_current(self) -> None:
        """Keep the original workspace identity across a CLI or RPC operation."""

        self._assert_workspace_identity()


def open_coding_plugin_management_read_client(
    workspace: str | Path,
    *,
    expected_workspace_identity: tuple[int, int] | None = None,
) -> CodingPluginManagementReadClientV1:
    return _programs.open_read_client(
        workspace, expected_workspace_identity=expected_workspace_identity
    )


def bind_coding_plugin_management_rpc_query(
    workspace: str | Path,
) -> CodingPluginManagementReadClientV1:
    return open_coding_plugin_management_read_client(workspace)


__all__ = [
    "CodingPluginManagementReadClientV1",
    "CodingPluginManagementReadSdkError",
    "bind_coding_plugin_management_rpc_query",
    "open_coding_plugin_management_read_client",
]
