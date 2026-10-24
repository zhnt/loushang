from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from loushang.ai import ApiKeyAuth, CallOptions, ReasoningOptions, complete
from loushang.ai.model import ModelSelection, load_builtin_model_registry
from loushang.ai.model.loader import load_model_registry_from_file
from loushang.ai.options import ThinkingLevel
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    TextPart,
    ThinkingPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)

FLASH = "MiniMax-M3.1-Flash"
ROUTES = {
    "anthropic-messages": "https://api.minimax.io/anthropic",
    "anthropic-messages-cn": "https://api.minimaxi.com/anthropic",
    "openai-completions": "https://api.minimax.io/v1",
    "openai-completions-cn": "https://api.minimaxi.com/v1",
}


@pytest.fixture
def captured_calls(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.base_url = kwargs["base_url"]
            self.messages = SimpleNamespace(create=self.create)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        async def create(self, **kwargs):
            # The real public call pipeline has resolved, normalized, prepared,
            # and reconstructed its payload before reaching this SDK boundary.
            calls.append((self.base_url, kwargs))
            if "/anthropic" in self.base_url:
                return SimpleNamespace(
                    id="mock-response",
                    content=[SimpleNamespace(type="text", text="ok")],
                    stop_reason="end_turn",
                    usage=None,
                )
            return SimpleNamespace(
                id="mock-response",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

        async def close(self):
            pass

    for name, client_name in (
        ("anthropic", "AsyncAnthropic"),
        ("openai", "AsyncOpenAI"),
    ):
        module = ModuleType(name)
        setattr(module, client_name, FakeClient)
        module.Omit = type("Omit", (), {})
        monkeypatch.setitem(sys.modules, name, module)
    return calls


def _complete(model, reasoning=None, context=None):
    return asyncio.run(
        complete(
            model,
            context or {"messages": [UserMessage("user", "hello", 0.0)]},
            CallOptions(auth=ApiKeyAuth("offline-fixture"), reasoning=reasoning),
        )
    )


@pytest.mark.parametrize("endpoint", ROUTES)
def test_active_choices_and_explicit_legacy_resolution(endpoint):
    registry = load_builtin_model_registry()
    models = registry.list_models(provider="minimax", endpoint=endpoint)
    assert [m.id for m in models] == [FLASH, "MiniMax-M3"]
    assert [m.id for m in registry.get_endpoint("minimax", endpoint).list_models()] == [
        FLASH,
        "MiniMax-M3",
    ]
    flash = models[0]
    assert flash.alias == "default-chat"
    assert flash.context_window == 1_000_000
    assert flash.max_tokens == 524_288
    assert flash.capabilities.input == ("text", "image")
    assert flash.supports_temperature is False
    saved = ModelSelection("minimax", endpoint, "MiniMax-M2.7")
    legacy = registry.resolve_model_selection(saved)
    assert legacy.id == "MiniMax-M2.7"
    assert legacy in registry.list_models(model_id="MiniMax-M2.7")
    assert legacy.to_raw()["listed"] is False


@pytest.mark.parametrize("endpoint", ROUTES)
@pytest.mark.parametrize(
    "effort", [None, "minimal", "low", "medium", "high", "xhigh", "max"]
)
def test_flash_public_call_serializes_effort(captured_calls, endpoint, effort):
    model = load_builtin_model_registry().get_model("minimax", endpoint, FLASH)
    reasoning = (
        None if effort is None else ReasoningOptions(effort=cast(ThinkingLevel, effort))
    )
    result = _complete(model, reasoning)
    assert result.stop_reason == "stop", result.error_message
    base_url, payload = captured_calls.pop()
    assert base_url == ROUTES[endpoint]
    assert payload["model"] == FLASH
    expected = "max" if effort is None else "low" if effort == "minimal" else effort
    if endpoint.startswith("anthropic"):
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["output_config"] == {"effort": expected}
        assert payload["max_tokens"] <= 524_288
    else:
        assert payload["extra_body"]["thinking"] == {"type": "adaptive"}
        assert payload["reasoning_effort"] == expected
        assert payload["max_completion_tokens"] <= 524_288
    assert "service_tier" not in payload
    assert "reasoning_split" not in payload.get("extra_body", {})
    assert "temperature" not in payload


@pytest.mark.parametrize("endpoint", ROUTES)
def test_flash_disabled_fails_before_sdk(captured_calls, endpoint):
    model = load_builtin_model_registry().get_model("minimax", endpoint, FLASH)
    with pytest.raises(ValueError, match="requires reasoning"):
        _complete(model, ReasoningOptions(enabled=False))
    with pytest.raises(ValueError, match="Unsupported reasoning effort"):
        ReasoningOptions(effort="none")
    assert captured_calls == []


@pytest.mark.parametrize("endpoint", ROUTES)
@pytest.mark.parametrize("enabled", [None, False, True])
def test_m3_keeps_optional_thinking_without_depth(captured_calls, endpoint, enabled):
    model = load_builtin_model_registry().get_model("minimax", endpoint, "MiniMax-M3")
    reasoning = (
        None
        if enabled is None
        else ReasoningOptions(enabled=enabled, effort="high" if enabled else None)
    )
    result = _complete(model, reasoning)
    assert result.stop_reason == "stop", result.error_message
    _, payload = captured_calls.pop()
    assert payload["model"] == "MiniMax-M3"
    assert "reasoning_effort" not in payload
    assert "output_config" not in payload
    thinking = payload.get("thinking") or payload.get("extra_body", {}).get("thinking")
    if enabled:
        assert thinking == {"type": "adaptive"}
    elif enabled is False:
        assert thinking == {"type": "disabled"}
    else:
        assert thinking is None


@pytest.mark.parametrize("endpoint", ROUTES)
def test_saved_legacy_and_custom_upstream_ids_are_not_rewritten(
    captured_calls, endpoint
):
    registry = load_builtin_model_registry()
    legacy = registry.get_model("minimax", endpoint, "MiniMax-M2.7")
    for model in (
        legacy,
        replace(legacy, id="my-model", upstream_id="custom-deployment"),
    ):
        result = _complete(model)
        assert result.stop_reason == "stop", result.error_message
        assert captured_calls.pop()[1]["model"] == (model.upstream_id or model.id)


@pytest.mark.parametrize("endpoint", ROUTES)
def test_flash_preserves_image_and_tool_thinking_history(captured_calls, endpoint):
    model = load_builtin_model_registry().get_model("minimax", endpoint, FLASH)
    history = AssistantMessage(
        role="assistant",
        content=[
            ThinkingPart("thinking", "keep this reasoning", "signature"),
            ToolCall("toolCall", "call_1", "lookup", {"q": "cat"}),
        ],
        api=model.api,
        provider="minimax",
        endpoint=endpoint,
        model=FLASH,
        response_id=None,
        usage=Usage(0, 0, 0, 0, 0, None),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )
    context = {
        "messages": [
            UserMessage(
                "user",
                [
                    TextPart("text", "describe"),
                    ImagePart("image", "aGVsbG8=", "image/png"),
                ],
                0.0,
            ),
            history,
            ToolResultMessage(
                "toolResult",
                "call_1",
                "lookup",
                [TextPart("text", "found")],
                False,
                0.0,
            ),
        ],
        "tools": [
            Tool(
                "lookup",
                "look up a term",
                {"type": "object", "properties": {"q": {"type": "string"}}},
            )
        ],
    }
    result = _complete(model, context=context)
    assert result.stop_reason == "stop", result.error_message
    payload = captured_calls.pop()[1]
    serialized = json.dumps(payload["messages"])
    assert "keep this reasoning" in serialized
    assert "aGVsbG8=" in serialized
    assert "call_1" in serialized and "found" in serialized
    assert payload["tools"]


def test_custom_catalog_visibility_metadata_roundtrips(tmp_path):
    registry = load_builtin_model_registry()
    provider = registry.get_provider("minimax")
    raw = {"providers": {"minimax": provider.to_raw()}}
    for endpoint in raw["providers"]["minimax"]["endpoints"].values():
        # Keep this fixture focused on the new metadata; M3 has unknown limits.
        endpoint["models"].pop("MiniMax-M3")
    # A caller owns their explicit custom model definition, including visibility.
    raw["providers"]["minimax"]["endpoints"]["anthropic-messages"]["models"][
        "MiniMax-M2.7"
    ]["listed"] = True
    path = tmp_path / "models.json"
    path.write_text(json.dumps(raw))
    custom = load_model_registry_from_file(path)
    assert custom.get_model("minimax", "anthropic-messages", "MiniMax-M2.7").listed
    assert custom.get_model("minimax", "anthropic-messages", FLASH).reasoning_required
    assert custom.get_model("minimax", "anthropic-messages", FLASH).list_order == -1
