"""Best-effort SDK preparation for the currently selected Coding model."""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable

from loushang.ai.sdk_import import load_sdk_symbols, sdk_package_for_api
from loushang.foundation.observability import get_log
from loushang.harnesstui.conversation.application_host import _ScreenSdkPreparation
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


class CodingSdkWarmup(_ScreenSdkPreparation):
    """Own one visible preparation task for a live Coding screen."""

    _sdk_preparation_task_name = "coding-sdk-warmup"
    _selection_failure_event = "sdk_warmup.selection_failed"
    _load_failure_event = "sdk_warmup.failed"

    def __init__(
        self,
        *,
        app: ScreenConversationApp,
        session_provider: Callable[[], object],
    ) -> None:
        super().__init__(app=app)
        self.session_provider = session_provider

    @classmethod
    def attach(
        cls, *, app: ScreenConversationApp, session_provider: Callable[[], object]
    ) -> CodingSdkWarmup:
        warmup = cls(app=app, session_provider=session_provider)
        app.on_session_ready = warmup.after_ready
        return warmup

    def _select_sdk_preparation(self) -> tuple[str, str] | None:
        return _current_builtin_sdk(self.session_provider())

    def _sdk_preparation_loaded(self, package: str) -> bool:
        return _sdk_loaded(package)

    def _load_sdk_preparation(self, api: str) -> Awaitable[object]:
        return load_sdk_symbols(api)

    def _record_sdk_preparation_failure(self, event: str, error: Exception) -> None:
        _log.debug_event("tui", event, exceptionType=type(error).__name__)


__all__ = ["CodingSdkWarmup"]
