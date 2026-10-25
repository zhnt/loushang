from __future__ import annotations

import pytest

from loushang.ai import CallOptions, ReasoningOptions
from loushang.ai.auth import ApiKeyAuth
from loushang.ai.model import (
    available_thinking_levels,
    load_builtin_model_registry,
    native_reasoning_effort,
    preferred_thinking_level,
    validate_reasoning_request,
)
from loushang.ai.protocols.anthropic_messages import AnthropicMessagesAdapter
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.provider import resolve_request_for_model


@pytest.mark.parametrize(
    ("provider", "endpoint", "model_id", "default"),
    [
        ("moonshot", "openai-completions", "kimi-k3.1-pro", "xhigh"),
        ("moonshot", "openai-completions", "kimi-k3.1-pro-highspeed", "xhigh"),
        ("kimi-code", "kimi-code-openai", "k3.1-pro", "high"),
        ("kimi-code", "kimi-code-openai", "k3.1-pro-highspeed", "high"),
        ("kimi-code", "kimi-code-anthropic", "k3.1-pro", "high"),
        ("kimi-code", "kimi-code-anthropic", "k3.1-pro-highspeed", "high"),
    ],
)
def test_k31_exposes_only_distinct_supported_levels_and_rejects_off(
    provider: str, endpoint: str, model_id: str, default: str
) -> None:
    model = load_builtin_model_registry().get_model(provider, endpoint, model_id)

    assert available_thinking_levels(model) == ("low", "high", "xhigh")
    assert preferred_thinking_level(model) == default
    assert native_reasoning_effort(model, "xhigh") == "max"
    assert native_reasoning_effort(model, "medium") == "high"

    with pytest.raises(ValueError, match="requires reasoning"):
        resolve_request_for_model(
            model,
            options=CallOptions(
                auth=ApiKeyAuth("secret"),
                reasoning=ReasoningOptions(enabled=False),
            ),
        )

    request = resolve_request_for_model(
        model,
        options=CallOptions(
            auth=ApiKeyAuth("secret"),
            reasoning=ReasoningOptions(enabled=True, effort="xhigh"),
        ),
    )
    assert request.reasoning_enabled is True
    assert request.reasoning_effort == "xhigh"
    adapter = (
        AnthropicMessagesAdapter()
        if endpoint == "kimi-code-anthropic"
        else OpenAIChatCompletionsAdapter()
    )
    payload = adapter.prepare_request(request).payload
    if endpoint == "kimi-code-anthropic":
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["output_config"] == {"effort": "max"}
    else:
        assert payload["reasoning_effort"] == "max"
        assert "thinking" not in payload


def test_known_effort_list_rejects_unsupported_generic_level() -> None:
    model = load_builtin_model_registry().get_model(
        "kimi-code", "kimi-code-openai", "k3.1-pro"
    )
    with pytest.raises(ValueError, match="does not support reasoning effort"):
        validate_reasoning_request(model, enabled=True, effort="ultra")
