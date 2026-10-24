from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from loushang.ai import sdk_import


def test_selected_sdk_import_does_not_block_event_loop(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    sdk = SimpleNamespace(AsyncAnthropic=object(), Omit=object())

    def import_module(name: str) -> object:
        calls.append(name)
        entered.set()
        assert release.wait(2)
        return sdk

    monkeypatch.setattr(sdk_import, "import_module", import_module)

    async def run() -> None:
        first = asyncio.create_task(sdk_import.load_sdk_symbols("anthropic-messages"))
        assert await asyncio.to_thread(entered.wait, 2)
        second = asyncio.create_task(sdk_import.load_sdk_symbols("anthropic-messages"))
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
        release.set()
        assert await first == (sdk.AsyncAnthropic, sdk.Omit)
        assert await second == (sdk.AsyncAnthropic, sdk.Omit)

    try:
        asyncio.run(run())
    finally:
        release.set()
    assert calls == ["anthropic"]


def test_sdk_import_maps_both_openai_apis_and_skips_unknown(monkeypatch) -> None:
    calls: list[str] = []
    sdk = SimpleNamespace(AsyncOpenAI=object(), Omit=object())

    def import_module(name: str) -> object:
        calls.append(name)
        return sdk

    monkeypatch.setattr(sdk_import, "import_module", import_module)

    async def run() -> None:
        assert await sdk_import.load_sdk_symbols("openai-completions") == (
            sdk.AsyncOpenAI,
            sdk.Omit,
        )
        assert await sdk_import.load_sdk_symbols("openai-responses") == (
            sdk.AsyncOpenAI,
            sdk.Omit,
        )
        assert await sdk_import.load_sdk_symbols("plugin-api") is None

    asyncio.run(run())
    assert calls == ["openai", "openai"]
