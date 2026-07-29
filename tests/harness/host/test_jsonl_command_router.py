from __future__ import annotations

import asyncio

import pytest

from loushang.harness.host.jsonl_command_host import JsonlCommand
from loushang.harness.host.jsonl_command_router import (
    JsonlCommandRoute,
    JsonlCommandRouter,
)


def test_jsonl_command_router_dispatches_sync_and_async_routes() -> None:
    received: list[tuple[str, str | None]] = []

    def handle_sync(command: JsonlCommand) -> None:
        received.append((command.command_type, command.command_id))

    async def handle_async(command: JsonlCommand) -> None:
        received.append((command.command_type, command.command_id))

    router = JsonlCommandRouter(
        routes=(
            JsonlCommandRoute(command_type="sync", handler=handle_sync),
            JsonlCommandRoute(command_type="async", handler=handle_async),
        ),
        on_unsupported=lambda command: received.append(
            (f"unsupported:{command.command_type}", command.command_id)
        ),
    )

    async def scenario() -> None:
        await router.handle_jsonl_command(
            JsonlCommand(command_id="one", command_type="sync", payload={})
        )
        await router.handle_jsonl_command(
            JsonlCommand(command_id="two", command_type="async", payload={})
        )
        await router.handle_jsonl_command(
            JsonlCommand(command_id="three", command_type="unknown", payload={})
        )

    asyncio.run(scenario())

    assert received == [
        ("sync", "one"),
        ("async", "two"),
        ("unsupported:unknown", "three"),
    ]
    assert router.command_types == frozenset({"sync", "async"})


def test_jsonl_command_router_rejects_invalid_or_duplicate_routes() -> None:
    def handler(command: JsonlCommand) -> None:
        del command

    with pytest.raises(ValueError, match="non-empty"):
        JsonlCommandRouter(
            routes=(JsonlCommandRoute(command_type="", handler=handler),),
            on_unsupported=handler,
        )

    with pytest.raises(ValueError, match="duplicate"):
        JsonlCommandRouter(
            routes=(
                JsonlCommandRoute(command_type="prompt", handler=handler),
                JsonlCommandRoute(command_type="prompt", handler=handler),
            ),
            on_unsupported=handler,
        )
