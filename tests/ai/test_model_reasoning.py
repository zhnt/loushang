from __future__ import annotations

import pytest

from loushang.ai import CallOptions, ReasoningOptions
from loushang.ai.auth import ApiKeyAuth
from loushang.ai.model import (
    available_thinking_levels,
    load_builtin_model_registry,
    preferred_thinking_level,
    validate_reasoning_request,
)
from loushang.ai.protocols.anthropic_messages import AnthropicMessagesAdapter
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.provider import resolve_request_for_model


@pytest.mark.parametrize(
    ("provider", "endpoint", "model_id", "default"),
    [
        ("moonshot", "openai-completions", "kimi-k3.1-pro", "max"),
        ("moonshot", "openai-completions", "kimi-k3.1-pro-highspeed", "max"),
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

    assert available_thinking_levels(model) == ("low", "high", "max")
    assert preferred_thinking_level(model) == default
    assert "medium" not in available_thinking_levels(model)

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
            reasoning=ReasoningOptions(enabled=True, effort="max"),
        ),
    )
    assert request.reasoning_enabled is True
    assert request.reasoning_effort == "max"
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


@pytest.mark.parametrize(
    ("provider", "endpoint", "model_id", "level", "native_effort"),
    [
        ("deepseek", "openai-completions", "deepseek-flash", "low", "low"),
        (
            "volcano-ark",
            "openai-completions-cn-beijing",
            "doubao-seed-evolving",
            "off",
            "none",
        ),
        ("zai", "openai-completions", "glm-5.3-flash", "max", "max"),
    ],
)
def test_current_chat_models_send_the_documented_effort(
    provider: str, endpoint: str, model_id: str, level: str, native_effort: str
) -> None:
    model = load_builtin_model_registry().get_model(provider, endpoint, model_id)
    assert level in available_thinking_levels(model)

    request = resolve_request_for_model(
        model,
        options=CallOptions(
            auth=ApiKeyAuth("secret"),
            reasoning=ReasoningOptions(
                enabled=level != "off", effort=None if level == "off" else level
            ),
        ),
    )
    payload = OpenAIChatCompletionsAdapter().prepare_request(request).payload
    assert payload["reasoning_effort"] == native_effort
    if provider == "zai":
        assert "thinking" not in payload


def test_minimax_flash_sends_selected_effort_through_messages_adapter() -> None:
    model = load_builtin_model_registry().get_model(
        "minimax", "anthropic-messages", "MiniMax-M3.1-Flash"
    )
    request = resolve_request_for_model(
        model,
        options=CallOptions(
            auth=ApiKeyAuth("secret"),
            reasoning=ReasoningOptions(enabled=True, effort="low"),
        ),
    )

    payload = AnthropicMessagesAdapter().prepare_request(request).payload
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": "low"}


def test_openai_responses_sends_two_distinct_top_efforts() -> None:
    from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter

    model = load_builtin_model_registry().get_model(
        "openai", "openai-responses", "gpt-6.2-sol"
    )
    assert available_thinking_levels(model) == ("low", "medium", "high", "xhigh", "max")
    for effort in ("xhigh", "max"):
        request = resolve_request_for_model(
            model,
            options=CallOptions(
                auth=ApiKeyAuth("secret"), reasoning=ReasoningOptions(effort=effort)
            ),
        )
        payload = OpenAIResponsesAdapter().prepare_request(request).payload
        assert payload["reasoning"]["effort"] == effort


def test_custom_responses_mapping_chooses_one_level_per_native_value() -> None:
    from dataclasses import replace

    from loushang.ai.model import OpenAIResponsesConfig
    from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter

    builtin = load_builtin_model_registry().get_model(
        "openai", "openai-responses", "gpt-6-luna"
    )
    model = replace(
        builtin,
        capabilities=replace(
            builtin.capabilities, reasoning_efforts=("none", "fast", "max")
        ),
        defaults={},
        adapter=OpenAIResponsesConfig(
            reasoning_effort_map={"low": "fast", "xhigh": "max"}
        ),
    )
    assert available_thinking_levels(model) == ("off", "low", "max")
    auth = ApiKeyAuth("secret")
    adapter = OpenAIResponsesAdapter()
    for request_options, expected in (
        (CallOptions(auth=auth), None),
        (
            CallOptions(auth=auth, reasoning=ReasoningOptions(enabled=False)),
            {"effort": "none"},
        ),
        (
            CallOptions(auth=auth, reasoning=ReasoningOptions(effort="low")),
            {"effort": "fast"},
        ),
    ):
        request = resolve_request_for_model(model, options=request_options)
        assert adapter.prepare_request(request).payload.get("reasoning") == expected

    with pytest.raises(ValueError, match="Available levels: off, low, max"):
        resolve_request_for_model(
            model,
            options=CallOptions(auth=auth, reasoning=ReasoningOptions(effort="xhigh")),
        )
    unknown = replace(
        model, capabilities=replace(model.capabilities, reasoning_efforts=None)
    )
    assert available_thinking_levels(unknown) == ()
