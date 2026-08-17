from __future__ import annotations

import asyncio

from loushang.harnesstui.commands.source import materialize_command_items


def test_materialize_command_items_accepts_sync_and_async_sources() -> None:
    async def async_source() -> list[str]:
        await asyncio.sleep(0)
        return ["async"]

    assert asyncio.run(materialize_command_items(lambda: ["sync"])) == ("sync",)
    assert asyncio.run(materialize_command_items(async_source)) == ("async",)


def test_materialize_command_items_normalizes_missing_and_invalid_sources() -> None:
    assert asyncio.run(materialize_command_items(None)) == ()
    assert asyncio.run(materialize_command_items(lambda: object())) == ()
