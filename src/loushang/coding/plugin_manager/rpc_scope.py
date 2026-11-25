"""Session-bound Coding Product clients for optional Plugin JSONL RPC routes."""

from __future__ import annotations

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
from loushang.harness.host.rpc.routing import RpcWorkspaceScope


class CodingPluginRpcSessionScope:
    """Pin the current RPC Session's workspace before a Product command runs."""

    def __init__(self) -> None:
        self._scope = RpcWorkspaceScope[CodingPluginManagementReadClientV1](unavailable=_unavailable)

    def bind_session(self, session: object) -> None:
        """Replace the pin on each Host Session bind; invalid input stays dark."""

        self._scope.clear()
        witness = getattr(session, "coding_product_workspace_witness", None)
        if not isinstance(witness, CodingProductWorkspaceWitnessV1):
            return
        manager = getattr(session, "session_manager", None)
        get_cwd = getattr(manager, "get_cwd", None)
        if not callable(get_cwd):
            return
        self._scope.bind(
            witness.workspace,
            get_cwd=get_cwd,
            require_current=witness.assert_current,
            open_client=open_coding_plugin_management_read_client,
        )

    def bind_management(self, cwd: str) -> CodingPluginManagementReadClientV1:
        return self._scope.client_for(cwd)

    def bind_desired(self, cwd: str) -> CodingPluginDesiredRpcClientV1:
        client = self._scope.client_for(cwd)
        bound = bind_coding_plugin_desired_rpc_client(client.workspace)
        _require_matching_workspace(client, bound)
        return bound

    def bind_package_repair(self, cwd: str) -> CodingPackageRepairRpcClientV1:
        client = self._scope.client_for(cwd)
        bound = bind_coding_package_repair_rpc_client(client.workspace)
        _require_matching_workspace(client, bound)
        return bound

    def bind_preview(self, cwd: str) -> CodingCurrentPreviewQuery:
        client = self._scope.client_for(cwd)
        return bind_coding_current_preview_query(
            client.workspace, workspace_guard=client.assert_workspace_current
        )

    def bind_explanation(self, cwd: str) -> CodingPluginOperationExplanationQuery:
        client = self._scope.client_for(cwd)
        return bind_coding_plugin_operation_explanation_query(
            client.workspace, workspace_guard=client.assert_workspace_current
        )


def _require_matching_workspace(
    client: CodingPluginManagementReadClientV1,
    bound: CodingPluginDesiredRpcClientV1
    | CodingPackageRepairRpcClientV1,
) -> None:
    client.assert_workspace_current()
    if (
        bound.local.workspace != client.workspace
        or bound.local.workspace_identity != client.workspace_identity
    ):
        raise _unavailable()


def _unavailable() -> CodingPluginManagementReadSdkError:
    return CodingPluginManagementReadSdkError(
        "Coding RPC Session workspace changed",
        code="coding_management_workspace_changed",
    )


__all__ = ["CodingPluginRpcSessionScope"]
