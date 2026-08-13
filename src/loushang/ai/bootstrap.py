from __future__ import annotations

from loushang.ai.api_registry import APIRegistry
from loushang.ai.protocols.anthropic_messages import AnthropicMessagesAdapter
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter


def register_builtin_api_adapters(
    registry: APIRegistry,
) -> None:
    registry.register_api_adapter(AnthropicMessagesAdapter())
    registry.register_api_adapter(OpenAIChatCompletionsAdapter())
    registry.register_api_adapter(OpenAIResponsesAdapter())
