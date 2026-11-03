"""Best-effort SDK preparation for the currently selected Coding model."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import Any, TextIO

from loushang.ai.sdk_import import load_sdk_symbols, sdk_package_for_api
from loushang.foundation.observability import get_log
from loushang.harnesstui.conversation.application_host import ActionHostScreenRunner
from loushang.harnesstui.conversation.screen_app import ScreenConversationApp

_log = get_log(__name__).bind(component="CodingSdkWarmup")
_BUILTIN_ADAPTERS = {
    "anthropic-messages": (
        "loushang.ai.protocols.anthropic_messages",
        "AnthropicMessagesAdapter",
    ),
    "openai-completions": (
        "loushang.ai.protocols.openai_chat_completions",
        "OpenAIChatCompletionsAdapter",
    ),
    "openai-responses": (
        "loushang.ai.protocols.openai_responses",
        "OpenAIResponsesAdapter",
    ),
}


def _sdk_loaded(package: str) -> bool:
    module = sys.modules.get(package)
    if module is None or getattr(getattr(module, "__spec__", None), "_initializing", False):
        return False
    constructor = "AsyncAnthropic" if package == "anthropic" else "AsyncOpenAI"
    return hasattr(module, constructor) and hasattr(module, "Omit")


def _current_builtin_sdk(session: object) -> tuple[str, str] | None:
    model = getattr(getattr(session, "agent", None), "model", None)
    api = getattr(model, "api", None)
    provider = getattr(model, "provider_id", None)
    if not isinstance(api, str) or not isinstance(provider, str):
        return None
    package = sdk_package_for_api(api)
    expected = _BUILTIN_ADAPTERS.get(api)
    if package is None or expected is None:
        return None
    from loushang.ai.provider_registry import get_default_provider_registry

    registry = get_default_provider_registry()
    if registry.get_provider_adapter(provider, api) is not None:
        return None
    try:
        adapter = registry.api_registry.get_api_adapter(api)
    except KeyError:
        # The first request installs the built-ins when the registry is empty.
        return (api, package) if not registry.api_registry.list_api_adapters() else None
    adapter_type = type(adapter)
    if (adapter_type.__module__, adapter_type.__name__) != expected:
        return None
    return api, package


class CodingSdkWarmup:
    """Own one visible preparation task for a live Coding screen."""

    def __init__(
        self,
        *,
        app: ScreenConversationApp,
        session_provider: Callable[[], object],
    ) -> None:
        self.app = app
        self.session_provider = session_provider
        self._task: asyncio.Task[None] | None = None
        self._timer: asyncio.TimerHandle | None = None
        self._active_package: str | None = None
        self._desired: tuple[str, str] | None = None
        self._completed: set[str] = set()
        self._failed: set[str] = set()
        self._closed = False

    @classmethod
    def attach(
        cls, *, app: ScreenConversationApp, session_provider: Callable[[], object]
    ) -> CodingSdkWarmup:
        warmup = cls(app=app, session_provider=session_provider)
        app.on_session_ready = warmup.after_ready
        return warmup

    async def run_prepared(
        self,
        prepared: Any,
        *,
        run: Callable[..., Awaitable[int]],
        stdin: TextIO,
        stdout: TextIO,
        screen_runner: ActionHostScreenRunner,
    ) -> int:
        self.app.notify_session_ready()
        try:
            return await run(
                prepared, stdin=stdin, stdout=stdout, screen_runner=screen_runner
            )
        finally:
            self.close()
            self.app.on_session_ready = None

    def after_ready(self) -> None:
        if self._closed or self._timer is not None:
            return
        # Let the admitted idle frame flush before cold imports contend for CPU.
        self._timer = asyncio.get_running_loop().call_later(0.05, self.observe_current)

    def observe_current(self) -> None:
        self._timer = None
        if self._closed or self.app.state.startup_pending:
            return
        try:
            selected = _current_builtin_sdk(self.session_provider())
        except Exception as error:
            _log.debug_event("tui", "sdk_warmup.selection_failed", exceptionType=type(error).__name__)
            selected = None
        self._desired = selected
        self._start_desired()

    def _start_desired(self) -> None:
        selected = self._desired
        if self._closed or selected is None:
            self._show_preparing(False)
            return
        api, package = selected
        if self._task is not None and not self._task.done():
            # A running Python import cannot be stopped. Finish it before
            # starting another SDK; only the current model earns a hint.
            self._show_preparing(self._active_package == package)
            return
        if package in self._completed or _sdk_loaded(package):
            self._completed.add(package)
            self._show_preparing(False)
            return
        if package in self._failed:
            self._show_preparing(False)
            return
        self._active_package = package
        self._show_preparing(True)

        async def warm() -> None:
            try:
                await load_sdk_symbols(api)
                self._completed.add(package)
            except Exception as error:
                self._failed.add(package)
                _log.debug_event(
                    "tui", "sdk_warmup.failed", exceptionType=type(error).__name__
                )
            finally:
                self._task = None
                self._active_package = None
                if not self._closed:
                    self._start_desired()

        self._task = asyncio.create_task(warm(), name="coding-sdk-warmup")

    def _show_preparing(self, preparing: bool) -> None:
        if self.app.state.sdk_preparing != preparing:
            self.app.state.sdk_preparing = preparing
            self.app.request_render("product")

    def close(self) -> None:
        self._closed = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._desired = None
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._active_package = None
        self.app.state.sdk_preparing = False


__all__ = ["CodingSdkWarmup"]
