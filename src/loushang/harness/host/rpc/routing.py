"""Explicit adaptation from legacy RPC handlers to JSONL command routes."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any

from loushang.harness.host.jsonl_command_host import JsonlCommand
from loushang.harness.host.jsonl_command_router import JsonlCommandRoute

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


__all__ = ["LegacyRpcHandler", "legacy_rpc_routes"]
