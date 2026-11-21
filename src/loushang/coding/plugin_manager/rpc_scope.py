"""Session-bound Coding Product clients for optional Plugin JSONL RPC routes."""

from __future__ import annotations

from loushang.coding.harness.plugin_management import session_scope as _programs
from loushang.coding.package.product_repair_rpc import (
    CodingPackageRepairRpcClientV1,
    bind_coding_package_repair_rpc_client,
)
from loushang.coding.package.product_runtime import CodingProductWorkspaceWitnessV1
from loushang.coding.plugin_manager.command_rpc import (
    CodingPluginDesiredRpcClientV1,
    bind_coding_plugin_desired_rpc_client,
)
from loushang.coding.plugin_manager.explanation import (
    CodingPluginOperationExplanationQuery,
    bind_coding_plugin_operation_explanation_query,
)
from loushang.coding.plugin_manager.preview import (
    CodingCurrentPreviewQuery,
    bind_coding_current_preview_query,
)
from loushang.coding.plugin_manager.read_sdk import (
    CodingPluginManagementReadClientV1,
    CodingPluginManagementReadSdkError,
)
from loushang.coding.plugin_manager.read_sdk import (
    open_coding_plugin_management_read_client as open_coding_plugin_management_read_client,
)


class CodingPluginRpcSessionScope:
    """Pin the current RPC Session's workspace before a Product command runs."""

    def __init__(self) -> None:
        self._client: CodingPluginManagementReadClientV1 | None = None
        self._witness: CodingProductWorkspaceWitnessV1 | None = None

    def bind_session(self, session: object) -> None:
        """Replace the pin on each Host Session bind; invalid input stays dark."""

        _programs.bind_session(self, session)

    def bind_management(self, cwd: str) -> CodingPluginManagementReadClientV1:
        return self._client_for(cwd)

    def bind_desired(self, cwd: str) -> CodingPluginDesiredRpcClientV1:
        client = self._client_for(cwd)
        bound = bind_coding_plugin_desired_rpc_client(client.workspace)
        _programs.require_matching_workspace(client, bound)
        return bound

    def bind_package_repair(self, cwd: str) -> CodingPackageRepairRpcClientV1:
        client = self._client_for(cwd)
        bound = bind_coding_package_repair_rpc_client(client.workspace)
        _programs.require_matching_workspace(client, bound)
        return bound

    def bind_preview(self, cwd: str) -> CodingCurrentPreviewQuery:
        client = self._client_for(cwd)
        return bind_coding_current_preview_query(
            client.workspace, workspace_guard=client._assert_workspace_identity
        )

    def bind_explanation(self, cwd: str) -> CodingPluginOperationExplanationQuery:
        client = self._client_for(cwd)
        return bind_coding_plugin_operation_explanation_query(
            client.workspace, workspace_guard=client._assert_workspace_identity
        )

    def _client_for(self, cwd: str) -> CodingPluginManagementReadClientV1:
        return _programs.require_scoped_client(self, cwd)


def _unavailable() -> CodingPluginManagementReadSdkError:
    return CodingPluginManagementReadSdkError(
        "Coding RPC Session workspace changed",
        code="coding_management_workspace_changed",
    )


__all__ = ["CodingPluginRpcSessionScope"]
