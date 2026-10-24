from __future__ import annotations

import asyncio
from types import ModuleType, SimpleNamespace

from loushang.coding.interaction import sdk_warmup
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.tui import RenderConstraints


def _app() -> ScreenCodingTuiApp:
    return ScreenCodingTuiApp(
        model_label="kimi-for-coding", cwd="/repo", branch="main", session_label="abcd"
    )


def test_preparation_hint_never_replaces_running_and_clears_on_completion(monkeypatch) -> None:
    release = asyncio.Event()
    calls: list[str] = []

    async def load(api: str) -> None:
        calls.append(api)
        await release.wait()

    monkeypatch.setattr(sdk_warmup, "_current_builtin_sdk", lambda _session: ("anthropic-messages", "anthropic"))
    monkeypatch.setattr(sdk_warmup, "load_sdk_symbols", load)
    app = _app()
    renders: list[str] = []
    app.render_requester = lambda kind: renders.append(kind)
    warmer = sdk_warmup.CodingSdkWarmup(app=app, session_provider=object)

    async def run() -> None:
        warmer.observe_current()
        assert app.state.sdk_preparing
        await asyncio.sleep(0)
        warmer.observe_current()
        assert calls == ["anthropic-messages"]
        app.start_prompt("hello")
        assert "preparing model" not in app._status_bar().render(
            RenderConstraints(width=80, max_height=1)
        ).lines[0].text
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not app.state.sdk_preparing
        assert renders == ["product", "product"]
        warmer.close()

    asyncio.run(run())


def test_old_model_completion_cannot_clear_new_model_hint(monkeypatch) -> None:
    selected = ["anthropic-messages", "anthropic"]
    releases = {"anthropic-messages": asyncio.Event(), "openai-responses": asyncio.Event()}
    calls: list[str] = []

    async def load(api: str) -> None:
        calls.append(api)
        await releases[api].wait()

    monkeypatch.setattr(sdk_warmup, "_current_builtin_sdk", lambda _session: tuple(selected))
    monkeypatch.setattr(sdk_warmup, "load_sdk_symbols", load)
    app = _app()
    warmer = sdk_warmup.CodingSdkWarmup(app=app, session_provider=object)

    async def run() -> None:
        try:
            warmer.observe_current()
            await asyncio.sleep(0)
            selected[:] = ["openai-responses", "openai"]
            warmer.observe_current()
            await asyncio.sleep(0)
            assert calls == ["anthropic-messages"]
            assert not app.state.sdk_preparing
            releases["anthropic-messages"].set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert app.state.sdk_preparing
            assert calls == ["anthropic-messages", "openai-responses"]
            releases["openai-responses"].set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not app.state.sdk_preparing
        finally:
            releases["anthropic-messages"].set()
            releases["openai-responses"].set()
            warmer.close()
            await asyncio.sleep(0)

    asyncio.run(run())


def test_only_builtin_adapter_for_current_model_is_prepared(monkeypatch) -> None:
    from loushang.ai.api_registry import APIRegistry
    from loushang.ai.provider_registry import ProviderRegistry

    registry = ProviderRegistry(APIRegistry())
    monkeypatch.setattr(
        "loushang.ai.provider_registry.get_default_provider_registry", lambda: registry
    )
    model = SimpleNamespace(api="anthropic-messages", provider_id="kimi-code")
    session = SimpleNamespace(agent=SimpleNamespace(model=model))
    assert sdk_warmup._current_builtin_sdk(session) == ("anthropic-messages", "anthropic")

    custom = SimpleNamespace(api="anthropic-messages", invoke_raw=lambda request: None)
    registry.register_provider_adapter("kimi-code", "anthropic-messages", custom)
    assert sdk_warmup._current_builtin_sdk(session) is None


def test_partially_imported_sdk_still_needs_preparation(monkeypatch) -> None:
    module = ModuleType("anthropic")
    module.__spec__ = SimpleNamespace(_initializing=True)
    module.AsyncAnthropic = object()
    module.Omit = object()
    monkeypatch.setitem(sdk_warmup.sys.modules, "anthropic", module)
    assert not sdk_warmup._sdk_loaded("anthropic")
    module.__spec__._initializing = False
    assert sdk_warmup._sdk_loaded("anthropic")
