"""Pin management operations to the current Session's original workspace."""

from __future__ import annotations

from pathlib import Path

from loushang.coding.plugin_manager import rpc_scope as _binding


def bind_session(self: _binding.CodingPluginRpcSessionScope, session: object) -> None:
    """Replace the pin on each Host Session bind; invalid input stays dark."""

    self._client = None
    self._witness = None
    witness = getattr(session, "coding_product_workspace_witness", None)
    if not isinstance(witness, _binding.CodingProductWorkspaceWitnessV1):
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
        client = _binding.open_coding_plugin_management_read_client(witness.workspace)
        witness.assert_current()
        self._witness = witness
        self._client = client
    except (OSError, RuntimeError, TypeError, ValueError):
        return


def require_scoped_client(
    self: _binding.CodingPluginRpcSessionScope, cwd: str
) -> _binding.CodingPluginManagementReadClientV1:
    client = self._client
    witness = self._witness
    if client is None or witness is None or not isinstance(cwd, str) or not cwd:
        raise _binding._unavailable()
    try:
        witness.assert_current()
    except (OSError, RuntimeError, ValueError) as exc:
        raise _binding._unavailable() from exc
    client._assert_workspace_identity()
    try:
        current = Path(cwd).expanduser().resolve(strict=True)
    except OSError as exc:
        raise _binding._unavailable() from exc
    if current != client.workspace:
        raise _binding._unavailable()
    client._assert_workspace_identity()
    try:
        witness.assert_current()
    except (OSError, RuntimeError, ValueError) as exc:
        raise _binding._unavailable() from exc
    return client


def require_matching_workspace(
    client: _binding.CodingPluginManagementReadClientV1,
    bound: _binding.CodingPluginDesiredRpcClientV1
    | _binding.CodingPackageRepairRpcClientV1,
) -> None:
    client._assert_workspace_identity()
    if (
        bound.local.workspace != client.workspace
        or bound.local.workspace_identity != client.workspace_identity
    ):
        raise _binding._unavailable()
