"""Session-bound Coding Product clients for optional Plugin JSONL RPC routes."""

from __future__ import annotations

from pathlib import Path

from .package_product_repair_rpc import (
    CodingPackageRepairRpcClientV1,
    bind_coding_package_repair_rpc_client,
)
from .package_product_runtime import CodingProductWorkspaceWitnessV1
from .plugin_management_command_rpc import (
    CodingPluginDesiredRpcClientV1,
    bind_coding_plugin_desired_rpc_client,
)
from .plugin_management_explanation import (
    CodingPluginOperationExplanationQuery,
    bind_coding_plugin_operation_explanation_query,
)
from .plugin_management_preview import (
    CodingCurrentPreviewQuery,
    bind_coding_current_preview_query,
)
from .plugin_management_read_sdk import (
    CodingPluginManagementReadClientV1,
    CodingPluginManagementReadSdkError,
    open_coding_plugin_management_read_client,
)


class CodingPluginRpcSessionScope:
    """Pin the current RPC Session's workspace before a Product command runs."""

    def __init__(self) -> None:
        self._client: CodingPluginManagementReadClientV1 | None = None
        self._witness: CodingProductWorkspaceWitnessV1 | None = None

    def bind_session(self, session: object) -> None:
        """Replace the pin on each Host Session bind; invalid input stays dark."""

        self._client = None
        self._witness = None
        witness = getattr(session, "coding_product_workspace_witness", None)
        if not isinstance(witness, CodingProductWorkspaceWitnessV1):
            return
        manager = getattr(session, "session_manager", None)
        get_cwd = getattr(manager, "get_cwd", None)
        if not callable(get_cwd):
            return
        try:
            witness.assert_current()
            workspace = get_cwd()
            if not isinstance(workspace, str | Path):
                return
            if Path(workspace).expanduser().resolve(strict=True) != witness.workspace:
                return
            client = open_coding_plugin_management_read_client(witness.workspace)
            witness.assert_current()
            self._witness = witness
            self._client = client
        except (OSError, RuntimeError, TypeError, ValueError):
            return

    def bind_management(self, cwd: str) -> CodingPluginManagementReadClientV1:
        return self._client_for(cwd)

    def bind_desired(self, cwd: str) -> CodingPluginDesiredRpcClientV1:
        client = self._client_for(cwd)
        bound = bind_coding_plugin_desired_rpc_client(client.workspace)
        client._assert_workspace_identity()
        if (
            bound.local.workspace != client.workspace
            or bound.local.workspace_identity != client.workspace_identity
        ):
            raise _unavailable()
        return bound

    def bind_package_repair(self, cwd: str) -> CodingPackageRepairRpcClientV1:
        client = self._client_for(cwd)
        bound = bind_coding_package_repair_rpc_client(client.workspace)
        client._assert_workspace_identity()
        if (
            bound.local.workspace != client.workspace
            or bound.local.workspace_identity != client.workspace_identity
        ):
            raise _unavailable()
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
        client = self._client
        witness = self._witness
        if client is None or witness is None or not isinstance(cwd, str) or not cwd:
            raise _unavailable()
        try:
            witness.assert_current()
        except (OSError, RuntimeError, ValueError) as exc:
            raise _unavailable() from exc
        client._assert_workspace_identity()
        try:
            current = Path(cwd).expanduser().resolve(strict=True)
        except OSError as exc:
            raise _unavailable() from exc
        if current != client.workspace:
            raise _unavailable()
        client._assert_workspace_identity()
        try:
            witness.assert_current()
        except (OSError, RuntimeError, ValueError) as exc:
            raise _unavailable() from exc
        return client


def _unavailable() -> CodingPluginManagementReadSdkError:
    return CodingPluginManagementReadSdkError(
        "Coding RPC Session workspace changed",
        code="coding_management_workspace_changed",
    )


__all__ = ["CodingPluginRpcSessionScope"]
