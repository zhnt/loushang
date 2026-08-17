from __future__ import annotations

import inspect
from typing import NamedTuple

from loushang.ai.api_registry import APIRegistry
from loushang.ai.bootstrap import register_builtin_api_adapters
from loushang.ai.prepared_request import PreparedRequestAdapter
from loushang.ai.protocols.anthropic_messages import AnthropicMessagesAdapter
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter
from loushang.ai.provider.protocol import APIAdapter


class CoreAdapterCase(NamedTuple):
    api: str
    provider_type: type[object]


CORE_ADAPTERS = (
    CoreAdapterCase("anthropic-messages", AnthropicMessagesAdapter),
    CoreAdapterCase("openai-completions", OpenAIChatCompletionsAdapter),
    CoreAdapterCase("openai-responses", OpenAIResponsesAdapter),
)


def test_core_adapters_implement_invoke_raw_contract() -> None:
    for case in CORE_ADAPTERS:
        provider = case.provider_type()

        assert isinstance(provider, APIAdapter)
        assert provider.api == case.api
        assert callable(provider.invoke_raw)
        assert list(inspect.signature(provider.invoke_raw).parameters) == ["request"]
        assert isinstance(provider, PreparedRequestAdapter)
        assert list(inspect.signature(provider.prepare_request).parameters) == [
            "request"
        ]
        assert list(
            inspect.signature(provider.invoke_prepared_raw).parameters
        ) == ["request", "prepared"]
        assert not hasattr(provider, "stream_simple")


def test_builtin_registration_matches_core_contracts() -> None:
    registry = APIRegistry()

    register_builtin_api_adapters(registry)

    assert sorted(provider.api for provider in registry.list_api_adapters()) == [
        case.api for case in CORE_ADAPTERS
    ]
