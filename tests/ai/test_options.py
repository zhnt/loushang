from __future__ import annotations

import importlib.util
from dataclasses import fields
from types import SimpleNamespace

import pytest

import loushang.ai as ai
import loushang.ai.options as options_module
from loushang.ai import ApiKeyAuth, OAuthBearerAuth
from loushang.ai import CallOptions as PublicCallOptions
from loushang.ai.advanced.registry import APIRegistry
from loushang.ai.options import (
    CallOptions,
    ReasoningOptions,
    RetryOptions,
    get_idle_timeout_seconds,
    get_max_output_tokens,
    get_reasoning_budget_tokens,
    get_reasoning_effort,
    get_reasoning_summary,
    get_retry_attempts,
    get_retry_max_delay_ms,
    get_timeout_seconds,
    is_reasoning_requested,
)

REMOVED_OPTION_NAMES = {
    "ModelCallOptions",
    "ProviderStreamOptions",
    "SimpleCallOptions",
    "SimpleStreamOptions",
    "StreamOptions",
    "ThinkingBudgets",
    "Timeout" + "Options",
    "Transport",
    "simple_options_to_call_options",
}

REMOVED_PROVIDER_OPTIONS = {
    "AnthropicOptions",
    "OpenAICompletionsOptions",
    "OpenAIResponsesOptions",
}


def test_call_options_is_the_single_public_call_contract() -> None:
    assert PublicCallOptions is CallOptions
    assert "CallOptions" in ai.__all__

    for name in REMOVED_OPTION_NAMES:
        assert name not in ai.__all__
        assert not hasattr(ai, name)
        assert name not in options_module.__all__
        assert not hasattr(options_module, name)

    options = CallOptions(auth=ApiKeyAuth("key"))

    assert isinstance(options, CallOptions)
    assert options.auth == ApiKeyAuth("key")


def test_call_options_fields_are_canonical_and_consumed() -> None:
    field_order = tuple(field.name for field in fields(CallOptions))
    field_names = set(field_order)

    assert field_order == (
        "cancellation",
        "auth",
        "credential",
        "credential_file",
        "headers",
        "cache_retention",
        "cache_key",
        "max_output_tokens",
        "temperature",
        "timeout_seconds",
        "idle_timeout_seconds",
        "retry",
        "trace",
        "pairing_mode",
        "reasoning",
        "tool_choice",
        "output",
        "request_limits",
        "prepared_request_committer",
    )

    assert field_names == {
        "cancellation",
        "auth",
        "credential",
        "credential_file",
        "headers",
        "cache_retention",
        "cache_key",
        "max_output_tokens",
        "temperature",
        "timeout_seconds",
        "idle_timeout_seconds",
        "retry",
        "trace",
        "prepared_request_committer",
        "pairing_mode",
        "reasoning",
        "tool_choice",
        "output",
        "request_limits",
    }
    assert {
        "signal",
        "max_tokens",
        "retries",
        "max_retry_delay_ms",
        "metadata",
        "hooks",
        "reasoning_summary",
        "on_payload",
        "on_response",
        "service_tier",
        "text_verbosity",
    }.isdisjoint(field_names)

    options = CallOptions(auth=OAuthBearerAuth("oauth-token"))

    assert options.auth == OAuthBearerAuth("oauth-token")
    assert "api_key" not in field_names
    assert "oauth_credentials" not in field_names


def test_call_options_rejects_invalid_non_auth_fields() -> None:
    with pytest.raises(TypeError, match="cache_key"):
        CallOptions(cache_key=123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cache_key"):
        CallOptions(cache_key="   ")
    with pytest.raises(ValueError, match="control characters"):
        CallOptions(cache_key="cache\nkey")
    with pytest.raises(TypeError, match="request_limits"):
        CallOptions(request_limits=object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("max_output_tokens", True, "positive integer"),
        ("max_output_tokens", 0, "positive integer"),
        ("temperature", True, "finite number"),
        ("temperature", float("nan"), "finite number"),
        ("timeout_seconds", 0, "finite positive number"),
        ("timeout_seconds", float("inf"), "finite positive number"),
        ("idle_timeout_seconds", True, "finite positive number"),
        ("cache_retention", "forever", "cache_retention"),
        ("pairing_mode", "loose", "pairing_mode"),
        ("tool_choice", "sometimes", "tool_choice"),
        ("tool_choice", {"type": "tool", "name": ""}, "tool_choice"),
    ],
)
def test_call_options_rejects_invalid_values(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        CallOptions(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "tool_choice",
    [
        "auto",
        "none",
        "required",
        "any",
        {"type": "tool", "name": "lookup"},
        {"type": "function", "name": "lookup"},
        {"type": "function", "function": {"name": "lookup"}},
    ],
)
def test_call_options_accepts_supported_tool_choices(tool_choice: object) -> None:
    assert CallOptions(tool_choice=tool_choice).tool_choice == tool_choice  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"enabled": "false"},
        {"effort": "extreme"},
        {"budget_tokens": True},
        {"budget_tokens": 0},
        {"expose_summary": 1},
    ],
)
def test_reasoning_options_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        ReasoningOptions(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": True},
        {"max_attempts": 0},
        {"max_delay_seconds": True},
        {"max_delay_seconds": -1},
        {"max_delay_seconds": float("nan")},
    ],
)
def test_retry_options_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RetryOptions(**kwargs)  # type: ignore[arg-type]


def test_call_options_retains_typed_auth() -> None:
    auth = ApiKeyAuth("typed-secret")

    options = CallOptions(auth=auth)

    assert options.auth is auth


def test_call_options_repr_does_not_expose_secrets_or_headers() -> None:
    options = CallOptions(
        auth=ApiKeyAuth("api-secret"),
        headers={"x-provider-token": "header-secret"},
    )

    rendered = repr(options)

    assert "api-secret" not in rendered
    assert "header-secret" not in rendered


@pytest.mark.parametrize(
    "headers",
    [
        {"": "value"},
        {"x-header": ""},
        {"x-header": "line\nfeed"},
        {"x-header": "one", "X-Header": "two"},
    ],
)
def test_call_options_rejects_invalid_headers(headers: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="headers"):
        CallOptions(headers=headers)


def test_call_options_preserves_opaque_cache_key() -> None:
    options = CallOptions(cache_key="  cache key / opaque  ")

    assert options.cache_key == "  cache key / opaque  "
    assert not hasattr(options, "session_id")
    assert not hasattr(options, "region")


def test_call_option_helpers_support_canonical_shapes_only() -> None:
    options = CallOptions(
        max_output_tokens=123,
        reasoning=ReasoningOptions(
            enabled=True,
            effort="high",
            budget_tokens=2048,
            expose_summary=True,
        ),
        retry=RetryOptions(max_attempts=4, max_delay_seconds=2.5),
        timeout_seconds=30,
        idle_timeout_seconds=5,
    )

    assert get_max_output_tokens(options) == 123
    assert is_reasoning_requested(options) is True
    assert get_reasoning_effort(options) == "high"
    assert get_reasoning_summary(options) == "auto"
    assert get_reasoning_budget_tokens(options) == 2048
    assert get_retry_attempts(options) == 4
    assert get_retry_max_delay_ms(options) == 2500
    assert get_timeout_seconds(options) == 30
    assert get_idle_timeout_seconds(options) == 5

    legacy = SimpleNamespace(
        max_tokens=64,
        reasoning="medium",
        reasoning_summary="detailed",
        retries=2,
        max_retry_delay_ms=500,
        timeout=10,
        thinking_budget_tokens=4096,
    )
    assert get_max_output_tokens(legacy) is None
    assert get_reasoning_effort(legacy) is None
    assert get_reasoning_summary(legacy) is None
    assert get_reasoning_budget_tokens(legacy) is None
    assert get_retry_attempts(legacy) is None
    assert get_retry_max_delay_ms(legacy) is None
    assert get_timeout_seconds(legacy) is None


def test_call_options_reject_non_canonical_reasoning() -> None:
    with pytest.raises(TypeError, match="reasoning must be ReasoningOptions"):
        CallOptions(reasoning="medium")  # type: ignore[arg-type]


def test_provider_specific_options_are_removed_from_core() -> None:
    assert importlib.util.find_spec("loushang.ai.advanced.options") is None
    assert APIRegistry.__module__ == "loushang.ai.api_registry"

    for module in (ai, options_module):
        for name in REMOVED_PROVIDER_OPTIONS:
            assert name not in getattr(module, "__all__", ())
            assert not hasattr(module, name), (module.__name__, name)
    import loushang.ai.advanced as advanced_module

    for name in REMOVED_PROVIDER_OPTIONS:
        assert name not in advanced_module.__all__
        assert not hasattr(advanced_module, name)
