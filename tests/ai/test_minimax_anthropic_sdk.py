"""Exercise the real Anthropic SDK, replacing only HTTP transport (no inference)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import anthropic
import httpx
import pytest

from loushang.ai import ApiKeyAuth, CallOptions, ReasoningOptions, complete, stream
from loushang.ai.errors import AIProviderError
from loushang.ai.model import load_builtin_model_registry
from loushang.ai.model.domain import (
    AnthropicMessagesConfig,
    Capabilities,
    Defaults,
    Model,
)
from loushang.ai.types import UserMessage

FLASH = "MiniMax-M3.1-Flash"
ENDPOINTS = ("anthropic-messages", "anthropic-messages-cn")


@pytest.fixture
def sdk_http(monkeypatch):
    captured = []
    real_client = anthropic.AsyncAnthropic

    def handle(request):
        payload = json.loads(request.content)
        captured.append((str(request.url), payload))
        message = {
            "id": "msg_offline",
            "type": "message",
            "role": "assistant",
            "model": payload["model"],
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        if not payload.get("stream"):
            return httpx.Response(200, json=message)
        events = [
            {
                "type": "message_start",
                "message": {**message, "content": [], "stop_reason": None},
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "ok"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
            {"type": "message_stop"},
        ]
        body = "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body
        )

    def client_factory(**kwargs):
        # Keep SDK timeout calculation, validation, JSON serialization and SSE
        # parsing intact; injecting only the offline HTTP client is intentional.
        kwargs["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        kwargs["max_retries"] = 0
        return real_client(**kwargs)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", client_factory)
    return captured


def invoke(model, mode="complete", **options):
    async def run():
        context = {"messages": [UserMessage("user", "hello", 0.0)]}
        call_options = CallOptions(auth=ApiKeyAuth("offline-fixture"), **options)
        if mode == "complete":
            return await complete(model, context, call_options)
        events = await stream(model, context, call_options)
        return await events.result()

    return asyncio.run(run())


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("mode", ["complete", "stream"])
@pytest.mark.parametrize("budget", [None, 4096, 8192])
def test_flash_default_and_explicit_budget_reach_real_sdk_http(
    sdk_http, endpoint, mode, budget
):
    model = load_builtin_model_registry().get_model("minimax", endpoint, FLASH)
    result = invoke(model, mode, max_output_tokens=budget)
    assert result.stop_reason == "stop", result.error_message
    url, payload = sdk_http.pop()
    host = "api.minimaxi.com" if endpoint.endswith("-cn") else "api.minimax.io"
    assert url == f"https://{host}/anthropic/v1/messages"
    assert payload["model"] == FLASH
    assert payload["max_tokens"] == (8192 if budget is None else budget)
    assert model.max_tokens == 524288  # Capability is not the request default.
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"] == {"effort": "max"}
    assert "temperature" not in payload
    assert payload.get("stream", False) == (mode == "stream")


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_flash_explicit_large_stream_budget_is_not_clamped(sdk_http, endpoint):
    model = load_builtin_model_registry().get_model("minimax", endpoint, FLASH)
    result = invoke(
        model,
        "stream",
        max_output_tokens=32000,
        reasoning=ReasoningOptions(effort="high"),
    )
    assert result.stop_reason == "stop", result.error_message
    payload = sdk_http.pop()[1]
    assert payload["max_tokens"] == 32000
    assert payload["output_config"] == {"effort": "high"}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_flash_explicit_large_nonstream_budget_keeps_sdk_guard(sdk_http, endpoint):
    model = load_builtin_model_registry().get_model("minimax", endpoint, FLASH)
    with pytest.raises(AIProviderError):
        invoke(model, max_output_tokens=32000)

    async def sdk_guard():
        async with anthropic.AsyncAnthropic(
            api_key="offline-fixture", base_url=model.base_url
        ) as client:
            await client.messages.create(
                model=FLASH,
                max_tokens=32000,
                messages=[{"role": "user", "content": "hello"}],
            )

    with pytest.raises(ValueError, match="Streaming is required"):
        asyncio.run(sdk_guard())
    assert sdk_http == []  # Do not silently cap an explicit user request.


@pytest.mark.parametrize("mode", ["complete", "stream"])
@pytest.mark.parametrize("enabled", [None, False, True])
def test_custom_adaptive_model_preserves_temperature_when_thinking_off(
    sdk_http, mode, enabled
):
    model = Model(
        id="saved-custom",
        upstream_id="custom-deployment",
        provider="custom",
        endpoint="messages",
        api="anthropic-messages",
        base_url="https://custom.example/anthropic",
        capabilities=Capabilities(
            context_window=100000,
            max_tokens=40000,
            reasoning=True,
            temperature=True,
            stream=True,
        ),
        adapter=AnthropicMessagesConfig(
            thinking_mode="adaptive", reasoning_effort_map={"high": "high"}
        ),
        defaults=Defaults.from_raw({"maxTokens": 6144}),
    )
    reasoning = (
        None
        if enabled is None
        else ReasoningOptions(enabled=enabled, effort="high" if enabled else None)
    )
    result = invoke(model, mode, reasoning=reasoning, temperature=0.4)
    assert result.stop_reason == "stop", result.error_message
    url, payload = sdk_http.pop()
    assert url == "https://custom.example/anthropic/v1/messages"
    assert payload["model"] == "custom-deployment"
    assert payload["max_tokens"] == 6144
    if enabled is True:
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["output_config"] == {"effort": "high"}
        assert "temperature" not in payload
    else:
        assert payload["temperature"] == 0.4
        assert "output_config" not in payload
        assert payload.get("thinking") == (
            {"type": "disabled"} if enabled is False else None
        )


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_custom_flash_defaults_and_explicit_legacy_are_preserved(sdk_http, endpoint):
    registry = load_builtin_model_registry()
    flash = registry.get_model("minimax", endpoint, FLASH)
    custom = replace(
        flash,
        id="my-flash",
        upstream_id="saved-flash",
        defaults=Defaults.from_raw({"maxTokens": 6144, "reasoningEffort": "low"}),
    )
    legacy = registry.get_model("minimax", endpoint, "MiniMax-M2.7")
    for model in (custom, legacy):
        result = invoke(model, max_output_tokens=4096)
        assert result.stop_reason == "stop", result.error_message
        payload = sdk_http.pop()[1]
        assert payload["model"] == (model.upstream_id or model.id)
        assert payload["max_tokens"] == 4096
    result = invoke(custom)
    assert result.stop_reason == "stop", result.error_message
    payload = sdk_http.pop()[1]
    assert payload["max_tokens"] == 6144
    assert payload["output_config"] == {"effort": "low"}
