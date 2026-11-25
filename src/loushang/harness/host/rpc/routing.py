"""Explicit adaptation from legacy RPC handlers to JSONL command routes."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

from loushang.harness.host.jsonl_command_host import JsonlCommand
from loushang.harness.host.jsonl_command_router import JsonlCommandRoute
from loushang.harness.workspace.paths import WorkspaceOperationGuard

LegacyRpcHandler = Callable[[str | None, dict[str, Any]], object]


def legacy_rpc_routes(
    bindings: Iterable[tuple[str, LegacyRpcHandler]],
) -> tuple[JsonlCommandRoute, ...]:
    """Bind an explicit command/handler table without name-based lookup."""

    return tuple(
        _legacy_rpc_route(command_type, handler)
        for command_type, handler in bindings
    )


def _legacy_rpc_route(
    command_type: str,
    handler: LegacyRpcHandler,
) -> JsonlCommandRoute:
    async def route(command: JsonlCommand) -> None:
        result = handler(command.command_id, dict(command.payload))
        if inspect.isawaitable(result):
            await result

    return JsonlCommandRoute(command_type=command_type, handler=route)


class _WorkspaceClient(Protocol):
    @property
    def workspace(self) -> Path: ...

    def assert_workspace_current(self) -> None: ...


_WorkspaceClientT = TypeVar("_WorkspaceClientT", bound=_WorkspaceClient)


class RpcWorkspaceScope(Generic[_WorkspaceClientT]):
    """Pin a client to the workspace admitted by the current Session."""

    def __init__(self, *, unavailable: Callable[[], Exception]) -> None:
        self._unavailable = unavailable
        self._binding: tuple[_WorkspaceClientT, Callable[[], None]] | None = None

    def clear(self) -> None:
        self._binding = None

    def bind(
        self,
        workspace: Path,
        *,
        get_cwd: Callable[[], object],
        require_current: Callable[[], None],
        open_client: Callable[[Path], _WorkspaceClientT],
    ) -> None:
        self.clear()
        try:
            require_current()
            current = get_cwd()
            if not isinstance(current, str | Path):
                return
            if Path(current).expanduser().resolve(strict=True) != workspace:
                return
            client = open_client(workspace)
            require_current()
            self._binding = client, require_current
        except (OSError, RuntimeError, TypeError, ValueError):
            return

    def client_for(self, cwd: str) -> _WorkspaceClientT:
        binding = self._binding
        if binding is None or not isinstance(cwd, str) or not cwd:
            raise self._unavailable()
        client, require_current = binding
        self._require_current(require_current)
        with WorkspaceOperationGuard(client.assert_workspace_current):
            try:
                current = Path(cwd).expanduser().resolve(strict=True)
            except OSError as exc:
                raise self._unavailable() from exc
            if current != client.workspace:
                raise self._unavailable()
        self._require_current(require_current)
        return client

    def _require_current(self, check: Callable[[], None]) -> None:
        try:
            check()
        except (OSError, RuntimeError, ValueError) as exc:
            raise self._unavailable() from exc


__all__ = ["LegacyRpcHandler", "RpcWorkspaceScope", "legacy_rpc_routes"]
