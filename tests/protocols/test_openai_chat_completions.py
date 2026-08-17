from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field, replace
from types import ModuleType, SimpleNamespace

import pytest

from loushang.ai import (
    CallOptions,
    get_model,
)
from loushang.ai.auth import ApiKeyAuth, OAuthBearerAuth
from loushang.ai.context import NormalizedContext, normalize_context
from loushang.ai.model import (
    Auth,
    Capabilities,
    Model,
    ModelRegistry,
    OpenAICompletionsConfig,
    Pricing,
    Provider,
)
from loushang.ai.model.domain import Endpoint
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.provider import ProviderRequest
from loushang.ai.structured import StructuredOutputOptions
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
from tests.protocols._runtime import (
    bound_test_model,
    make_provider_request,
    provider_request_for_test,
    start_test_provider_stream,
)

MAX_TOKENS_FIELD = "maxTokensField"
REQUIRES_REASONING_CONTENT_ON_ASSISTANT_MESSAGES = (
    "requiresReasoningContentOnAssistantMessages"
)
SUPPORTS_DEVELOPER_ROLE = "supportsDeveloperRole"
SUPPORTS_REASONING_EFFORT = "supportsReasoningEffort"
SUPPORTS_STORE = "supportsStore"
SUPPORTS_STRICT_MODE = "supportsStrictMode"
THINKING_FORMAT = "thinkingFormat"


def _registry_with_endpoint(provider_id: str, endpoint: Endpoint) -> ModelRegistry:
    return ModelRegistry.from_providers(
        {
            provider_id: Provider(
                id=provider_id,
                endpoints={endpoint.id: endpoint},
            )
        }
    )


def _normalized_context(model, context, options=None):
    if not isinstance(model, Model) or not model.api:
        model = bound_test_model(
            model,
            api="openai-completions",
            options=options,
        )
    pairing_mode = (
        "strict" if getattr(options, "pairing_mode", "strict") == "strict" else "repair"
    )
    return normalize_context(context, model=model, pairing_mode=pairing_mode)


def _invoke_raw_parts(
    provider,
    model,
    context,
    options=None,
    request=None,
    *,
    mode: str = "stream",
):
    normalized_context = _normalized_context(
        request.model if request is not None else model,
        context,
        options,
    )
    provider_request = provider_request_for_test(
        provider,
        model,
        normalized_context,
        options=options,
        request=request,
    )
    if mode != "stream":
        provider_request = replace(provider_request, mode=mode)
    return provider.invoke_raw(provider_request)


async def _stream(provider, model, context, options=None, request=None):
    return start_test_provider_stream(
        provider,
        model,
        _normalized_context(
            request.model if request is not None else model,
            context,
            options,
        ),
        options,
        request=request,
    )


def _adapter_config_from_compat(
    compat: dict[str, object] | None,
) -> OpenAICompletionsConfig:
    raw: dict[str, object] = {}
    compat = compat or {}
    mappings = {
        SUPPORTS_STORE: "store",
        SUPPORTS_DEVELOPER_ROLE: "developerRole",
        SUPPORTS_REASONING_EFFORT: "reasoningEffort",
        "supportsUsageInStreaming": "streamingUsage",
        SUPPORTS_STRICT_MODE: "strictSchema",
        REQUIRES_REASONING_CONTENT_ON_ASSISTANT_MESSAGES: ("assistantReasoningContent"),
    }
    for old_key, new_key in mappings.items():
        if old_key in compat:
            raw[new_key] = compat[old_key]
    if MAX_TOKENS_FIELD in compat:
        raw["maxOutputTokensField"] = compat[MAX_TOKENS_FIELD]
    if THINKING_FORMAT in compat and compat[THINKING_FORMAT] is not None:
        raw["reasoningFormat"] = compat[THINKING_FORMAT]
    return OpenAICompletionsConfig.from_raw(raw)


def test_openai_completions_payload_maps_user_image_assistant_toolcall_and_tool_result_mixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, compat={}, reasoning_effort=None)
    provider = OpenAIChatCompletionsAdapter()

    assistant = AssistantMessage(
        role="assistant",
        content=[
            TextPart(type="text", text="working"),
            ThinkingPart(
                type="thinking", thinking="plan", thinking_signature="reasoning_content"
            ),
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1}),
        ],
        api="openai-completions",
        provider="openai",
        endpoint="openai-completions",
        model="gpt-test",
        response_id="resp_1",
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="calc",
        content=[
            TextPart(type="text", text="before"),
            ImagePart(type="image", data="aGVsbG8=", mime_type="image/png"),
            TextPart(type="text", text="after"),
        ],
        is_error=False,
        timestamp=0.0,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                {
                    "system_prompt": "You are helpful.",
                    "messages": [
                        UserMessage(
                            role="user",
                            content=[
                                TextPart(type="text", text="look"),
                                ImagePart(
                                    type="image", data="dXNlcg==", mime_type="image/png"
                                ),
                            ],
                            timestamp=0.0,
                        ),
                        assistant,
                        tool_result,
                    ],
                    "tools": [
                        Tool(
                            name="calc",
                            description="Calculate values",
                            parameters={"type": "object"},
                        ),
                    ],
                },
                CallOptions(auth=ApiKeyAuth("test-key"), tool_choice="required"),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["messages"] == [
        {"role": "system", "content": "You are helpful."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,dXNlcg=="},
                },
            ],
        },
        {
            "role": "assistant",
            "content": "working",
            "reasoning_content": "plan",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "calc", "arguments": '{"x": 1}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "before\nafter",
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Attached image(s) from tool result:"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,aGVsbG8="},
                },
            ],
        },
    ]
    assert _FakeAsyncOpenAI.last_create_kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "calc",
                "description": "Calculate values",
                "parameters": {"type": "object"},
                "strict": False,
            },
        }
    ]
    assert _FakeAsyncOpenAI.last_create_kwargs["tool_choice"] == "required"


def test_openai_completions_complete_mode_maps_non_stream_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        response=SimpleNamespace(
            id="chatcmpl_complete",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        reasoning_content="plan",
                        reasoning_details=[
                            {
                                "type": "reasoning.encrypted",
                                "id": "call_1",
                                "data": "secret",
                            }
                        ],
                        content="hello",
                        tool_calls=[
                            SimpleNamespace(
                                id=None,
                                function=SimpleNamespace(
                                    name="calc",
                                    arguments='{"x":1}',
                                ),
                            )
                        ],
                    ),
                    finish_reason="content_filter",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=3,
                completion_tokens=2,
                prompt_tokens_details=SimpleNamespace(cached_tokens=1),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=4),
            ),
        ),
    )
    _patch_resolved_request(
        monkeypatch,
        compat={"supportsUsageInStreaming": True},
        reasoning_effort=None,
    )
    provider = OpenAIChatCompletionsAdapter()
    request = make_provider_request(
        _Model(),
        api="openai-completions",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAICompletionsConfig(),
        capabilities=Capabilities(input=("text",), tool_use=True),
    )

    parts = asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ],
                    "tools": [
                        Tool(
                            name="calc",
                            description="Calculate values",
                            parameters={"type": "object"},
                        ),
                    ],
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
                request=request,
                mode="complete",
            )
        )
    )

    assert "stream" not in _FakeAsyncOpenAI.last_create_kwargs
    assert "stream_options" not in _FakeAsyncOpenAI.last_create_kwargs
    assert "tool_stream" not in _FakeAsyncOpenAI.last_create_kwargs
    assert [part["type"] for part in parts] == [
        "response_start",
        "usage_delta",
        "thinking_delta",
        "tool_call_thought_signature",
        "text_delta",
        "tool_call_start",
        "tool_call_args_delta",
        "tool_call_done",
        "stop_reason",
        "response_error",
    ]
    assert parts[1]["input"] == 2
    assert parts[1]["output"] == 2
    assert parts[1]["total_tokens"] == 5
    assert parts[2] == {"type": "thinking_delta", "text": "plan"}
    assert parts[3]["tool_call_id"] == "call_1"
    assert parts[5]["id"] == "tool_call_0"
    assert parts[6]["delta"] == '{"x":1}'
    assert parts[8] == {"type": "stop_reason", "stop_reason": "error"}


def test_openai_completions_stream_usage_only_chunk_updates_message_and_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        chunks=[
            SimpleNamespace(
                id="chatcmpl_usage",
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="hello"),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                id="chatcmpl_usage",
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=3,
                    completion_tokens=2,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=1),
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=4),
                ),
            ),
        ],
    )
    _patch_resolved_request(
        monkeypatch,
        compat={"supportsUsageInStreaming": True},
        reasoning_effort=None,
    )
    provider = OpenAIChatCompletionsAdapter()
    model = _Model(pricing=Pricing(input=1, output=2, cache_read=0.5, cache_write=0.25))

    async def _scenario():
        stream = await _stream(
            provider,
            model,
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(auth=ApiKeyAuth("test-key")),
        )
        return await stream.result()

    message = asyncio.run(_scenario())

    assert message.response_id == "chatcmpl_usage"
    assert message.usage == Usage(
        input=2,
        output=2,
        cache_read=1,
        cache_write=0,
        total_tokens=5,
        cost={
            "input": 0.000002,
            "output": 0.000004,
            "cacheRead": 0.0000005,
            "cacheWrite": 0.0,
            "total": 0.0000065,
        },
    )


def test_openai_completions_payload_uses_resolved_capabilities_for_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={},
        reasoning_effort=None,
        capabilities=Capabilities(input=("text", "image")),
    )
    provider = OpenAIChatCompletionsAdapter()
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="read",
        content=[ImagePart(type="image", data="dG9vbA==", mime_type="image/png")],
        is_error=False,
        timestamp=0.0,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(input=("text",)),
                {
                    "messages": [
                        UserMessage(
                            role="user",
                            content=[
                                TextPart(type="text", text="look"),
                                ImagePart(
                                    type="image",
                                    data="dXNlcg==",
                                    mime_type="image/png",
                                ),
                            ],
                            timestamp=0.0,
                        ),
                        tool_result,
                    ],
                },
                CallOptions(auth=ApiKeyAuth("test-key"), pairing_mode="repair"),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,dXNlcg=="},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "(see attached image)",
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Attached image(s) from tool result:"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,dG9vbA=="},
                },
            ],
        },
    ]


def test_openai_completions_payload_maps_structured_output_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={},
        reasoning_effort=None,
        capabilities=Capabilities(input=("text",), structured_output=True),
    )
    provider = OpenAIChatCompletionsAdapter()
    schema = {
        "title": "Answer",
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(
                    auth=ApiKeyAuth("test-key"),
                    output=StructuredOutputOptions(
                        mode="json_schema",
                        schema=schema,
                        strict=True,
                    ),
                ),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "Answer",
            "schema": schema,
            "strict": True,
        },
    }


def test_openai_completions_uses_upstream_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={},
        upstream_model_id="openai/gpt-oss-120b:free",
        reasoning_effort=None,
    )
    provider = OpenAIChatCompletionsAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(id="openai/gpt-oss-120b_free"),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["model"] == "openai/gpt-oss-120b:free"


def test_openai_completions_caps_model_max_tokens_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={"maxTokensField": "max_tokens"},
        reasoning_effort=None,
        max_tokens=None,
    )
    provider = OpenAIChatCompletionsAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(max_tokens=32768),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["max_tokens"] == 32000


def test_openai_completions_uses_resolved_capability_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={"maxTokensField": "max_tokens"},
        reasoning_effort=None,
        max_tokens=None,
        capabilities=Capabilities(max_tokens=2048),
    )
    provider = OpenAIChatCompletionsAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(max_tokens=1024),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["max_tokens"] == 2048


def test_openai_completions_payload_uses_resolved_capabilities_for_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={
            "supportsDeveloperRole": True,
            "supportsReasoningEffort": True,
            "maxTokensField": "max_tokens",
        },
        reasoning_effort="high",
        capabilities=Capabilities(reasoning=True),
    )
    provider = OpenAIChatCompletionsAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(reasoning=False),
                {
                    "system_prompt": "You reason carefully.",
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ],
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["messages"][0] == {
        "role": "developer",
        "content": "You reason carefully.",
    }
    assert _FakeAsyncOpenAI.last_create_kwargs["reasoning_effort"] == "high"


def test_openai_completions_explicit_zai_thinking_object_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={
            THINKING_FORMAT: "zai-thinking",
            SUPPORTS_DEVELOPER_ROLE: False,
            SUPPORTS_REASONING_EFFORT: False,
            SUPPORTS_STORE: False,
        },
        reasoning_effort="high",
        base_url="https://api.z.ai/api/paas/v4/",
    )
    provider = OpenAIChatCompletionsAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(provider_id="zai", reasoning=True),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["thinking"] == {"type": "enabled"}
    assert "enable_thinking" not in _FakeAsyncOpenAI.last_create_kwargs
    assert "reasoning_effort" not in _FakeAsyncOpenAI.last_create_kwargs
    assert "store" not in _FakeAsyncOpenAI.last_create_kwargs


def test_openai_completions_deepseek_thinking_uses_extra_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={
            THINKING_FORMAT: "deepseek",
            REQUIRES_REASONING_CONTENT_ON_ASSISTANT_MESSAGES: True,
            SUPPORTS_DEVELOPER_ROLE: False,
            SUPPORTS_REASONING_EFFORT: False,
            SUPPORTS_STORE: False,
        },
        reasoning_effort="high",
        base_url="https://api.deepseek.com",
    )
    provider = OpenAIChatCompletionsAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(provider_id="deepseek", reasoning=True),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    assert "thinking" not in _FakeAsyncOpenAI.last_create_kwargs
    assert "reasoning_effort" not in _FakeAsyncOpenAI.last_create_kwargs
    assert "store" not in _FakeAsyncOpenAI.last_create_kwargs


def test_openai_completions_explicit_moonshot_thinking_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={
            THINKING_FORMAT: "moonshot",
            MAX_TOKENS_FIELD: "max_tokens",
            SUPPORTS_DEVELOPER_ROLE: False,
            SUPPORTS_REASONING_EFFORT: False,
            SUPPORTS_STORE: False,
            SUPPORTS_STRICT_MODE: False,
        },
        reasoning_effort=None,
        base_url="https://api.moonshot.cn/v1",
    )
    provider = OpenAIChatCompletionsAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(provider_id="moonshot", reasoning=True),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["extra_body"] == {
        "thinking": {"type": "disabled"}
    }


def test_openai_completions_uses_resolved_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    provider = OpenAIChatCompletionsAdapter()
    request = make_provider_request(
        _Model(),
        api="openai-completions",
        options=CallOptions(auth=ApiKeyAuth("test-key")),
        temperature=0.4,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                request.model,
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                request.options,
                request,
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["temperature"] == 0.4
    assert "reasoning_effort" not in _FakeAsyncOpenAI.last_create_kwargs


def test_openai_completions_explicit_moonshot_thinking_for_model_definition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        compat={
            THINKING_FORMAT: "moonshot",
            MAX_TOKENS_FIELD: "max_tokens",
            SUPPORTS_DEVELOPER_ROLE: False,
            SUPPORTS_REASONING_EFFORT: False,
            SUPPORTS_STORE: False,
            SUPPORTS_STRICT_MODE: False,
        },
        reasoning_effort=None,
        base_url="https://api.moonshot.cn/v1",
    )
    provider = OpenAIChatCompletionsAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                Model(
                    id="kimi-k2.6",
                    provider="moonshot",
                    endpoint="openai-completions",
                    capabilities=Capabilities(reasoning=True),
                ),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["extra_body"] == {
        "thinking": {"type": "disabled"}
    }


def test_openai_completions_builtin_moonshot_uses_system_role_not_developer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    provider = OpenAIChatCompletionsAdapter()
    model = get_model("moonshot", "openai-completions", "kimi-k2.6")

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                model,
                {
                    "system_prompt": "You are helpful.",
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ],
                },
                CallOptions(),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["messages"][0] == {
        "role": "system",
        "content": "You are helpful.",
    }


def test_openai_completions_payload_synthesizes_missing_tool_result_for_assistant_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, compat={}, reasoning_effort=None)
    provider = OpenAIChatCompletionsAdapter()
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-completions",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id="resp_1",
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                {"messages": [assistant]},
                CallOptions(auth=ApiKeyAuth("test-key"), pairing_mode="repair"),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["messages"] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "calc", "arguments": '{"x": 1}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "No result provided",
        },
    ]


def test_openai_completions_stream_maps_thinking_tool_calls_and_reasoning_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        chunks=[
            SimpleNamespace(
                id="chatcmpl_1",
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            reasoning_content="plan",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name="calc", arguments='{"x":'
                                    ),
                                )
                            ],
                        ),
                        finish_reason=None,
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                id="chatcmpl_1",
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(arguments="1}"),
                                )
                            ],
                            reasoning_details=[
                                SimpleNamespace(
                                    type="reasoning.encrypted",
                                    id="call_1",
                                    data="secret",
                                )
                            ],
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=None,
            ),
        ],
    )
    _patch_resolved_request(monkeypatch, compat={}, reasoning_effort=None)
    provider = OpenAIChatCompletionsAdapter()

    async def _scenario() -> list[dict]:
        stream = await _stream(
            provider,
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(auth=ApiKeyAuth("test-key")),
        )
        return await _collect_stream_events(stream)

    events = asyncio.run(_scenario())

    assert [event["type"] for event in events] == [
        "start",
        "thinking_start",
        "thinking_delta",
        "toolcall_start",
        "toolcall_delta",
        "toolcall_delta",
        "toolcall_end",
        "thinking_end",
        "done",
    ]
    done = events[-1]["message"]
    assert done.stop_reason == "toolUse"
    assert done.content[0].thinking == "plan"
    assert done.content[1].name == "calc"
    assert done.content[1].arguments == {"x": 1}
    assert (
        done.content[1].thought_signature
        == '{"type": "reasoning.encrypted", "id": "call_1", "data": "secret"}'
    )


def test_openai_completions_stream_groups_interleaved_parallel_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        chunks=[
            SimpleNamespace(
                id="chatcmpl_1",
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_a",
                                    index=0,
                                    function=SimpleNamespace(
                                        name="add", arguments='{"a":'
                                    ),
                                ),
                                SimpleNamespace(
                                    id="call_b",
                                    index=1,
                                    function=SimpleNamespace(
                                        name="mul", arguments='{"x":'
                                    ),
                                ),
                            ]
                        ),
                        finish_reason=None,
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                id="chatcmpl_1",
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            tool_calls=[
                                SimpleNamespace(
                                    index=1,
                                    function=SimpleNamespace(arguments="2}"),
                                ),
                                SimpleNamespace(
                                    index=0,
                                    function=SimpleNamespace(arguments="1}"),
                                ),
                            ]
                        ),
                        finish_reason="tool_calls",
                    )
                ],
                usage=None,
            ),
        ],
    )
    _patch_resolved_request(monkeypatch, compat={}, reasoning_effort=None)
    provider = OpenAIChatCompletionsAdapter()

    async def _scenario() -> list[dict]:
        stream = await _stream(
            provider,
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(auth=ApiKeyAuth("test-key")),
        )
        return await _collect_stream_events(stream)

    events = asyncio.run(_scenario())

    assert [event["type"] for event in events] == [
        "start",
        "toolcall_start",
        "toolcall_delta",
        "toolcall_start",
        "toolcall_delta",
        "toolcall_delta",
        "toolcall_delta",
        "toolcall_end",
        "toolcall_end",
        "done",
    ]
    done = events[-1]["message"]
    assert [part.id for part in done.content] == ["call_a", "call_b"]
    assert [part.name for part in done.content] == ["add", "mul"]
    assert done.content[0].arguments == {"a": 1}
    assert done.content[1].arguments == {"x": 2}


def test_openai_completions_omits_response_start_when_chunk_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        chunks=[
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="hello"),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )
        ],
    )
    _patch_resolved_request(monkeypatch, compat={}, reasoning_effort=None)
    provider = OpenAIChatCompletionsAdapter()

    parts = asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert "response_start" not in {part["type"] for part in parts}
    assert {"type": "text_delta", "text": "hello"} in parts
    assert parts[-1] == {"type": "response_done"}


async def _collect_parts(source) -> list[dict]:
    return [part async for part in source]


@pytest.mark.parametrize(
    ("auth", "expected_headers"),
    [
        (ApiKeyAuth("opaque"), {"Authorization": "Bearer opaque"}),
        (
            OAuthBearerAuth(
                "oauth-token",
                extra_headers={"X-Account-Id": "account-1"},
            ),
            {
                "Authorization": "Bearer oauth-token",
                "X-Account-Id": "account-1",
            },
        ),
        (None, {}),
    ],
)
def test_openai_completions_forwards_authoritative_auth_headers(
    monkeypatch: pytest.MonkeyPatch,
    auth,
    expected_headers: dict[str, str],
) -> None:
    _fake_openai_module(monkeypatch)

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                OpenAIChatCompletionsAdapter(),
                _Model(),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=auth),
            )
        )
    )

    headers = _FakeAsyncOpenAI.last_create_kwargs["extra_headers"]
    sdk_api_key = _FakeAsyncOpenAI.last_init_kwargs["api_key"]
    assert isinstance(sdk_api_key, str) and sdk_api_key
    assert sdk_api_key not in headers.values()
    if not expected_headers:
        assert isinstance(headers["Authorization"], _FakeOmit)
        assert isinstance(headers["X-Api-Key"], _FakeOmit)
    else:
        assert all(headers[name] == value for name, value in expected_headers.items())
        assert sdk_api_key not in expected_headers.values()


def test_openai_completions_uses_catalog_auth_header_and_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    model = bound_test_model(
        _Model(),
        api="openai-completions",
        auth=Auth(kind="apiKey", header="X-Custom-Auth", prefix="Token "),
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                OpenAIChatCompletionsAdapter(),
                model,
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(auth=ApiKeyAuth("opaque")),
            )
        )
    )

    headers = _FakeAsyncOpenAI.last_create_kwargs["extra_headers"]
    assert headers["X-Custom-Auth"] == "Token opaque"


async def _collect_stream_events(stream) -> list[dict]:
    return [event async for event in stream]


def _fake_openai_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    chunks: list[object] | None = None,
    response: object | None = None,
) -> None:
    _FakeAsyncOpenAI.last_init_kwargs = {}
    _FakeAsyncOpenAI.last_create_kwargs = {}
    _FakeAsyncOpenAI.chunks = chunks or []
    _FakeAsyncOpenAI.response = response
    module = ModuleType("openai")
    module.AsyncOpenAI = _FakeAsyncOpenAI
    module.Omit = _FakeOmit
    monkeypatch.setitem(sys.modules, "openai", module)


class _FakeOmit:
    pass


def _patch_resolved_request(
    monkeypatch: pytest.MonkeyPatch,
    *,
    compat: dict[str, object],
    reasoning_effort: str | None,
    base_url: str = "https://api.openai.test/v1",
    extra_headers: dict[str, str] | None = None,
    max_tokens: int | None = 1024,
    capabilities: Capabilities | None = None,
    upstream_model_id: str | None = None,
) -> None:
    def _resolve(_model, *, context=None, options=None, request=None):
        del context, request
        headers = {}
        option_auth = getattr(options, "auth", None) if options is not None else None
        if isinstance(option_auth, ApiKeyAuth):
            headers["Authorization"] = f"Bearer {option_auth.value}"
        if extra_headers:
            headers.update(extra_headers)
        option_max_tokens = (
            getattr(options, "max_output_tokens", None) if options is not None else None
        )
        resolved_max_tokens = (
            option_max_tokens if isinstance(option_max_tokens, int) else max_tokens
        )
        adapter_config = _adapter_config_from_compat(compat)
        resolved_capabilities = capabilities or Capabilities(
            input=tuple(getattr(_model, "input", ("text",))),
            reasoning=bool(getattr(_model, "reasoning", False)),
            max_tokens=getattr(_model, "max_tokens", None),
        )
        request_model = bound_test_model(
            _model,
            api="openai-completions",
            options=options,
            base_url=base_url,
            adapter_config=adapter_config,
            capabilities=resolved_capabilities,
            upstream_model_id=upstream_model_id,
        )
        return ProviderRequest(
            model=request_model,
            context=NormalizedContext(system_prompt=None),
            options=options,
            base_url=base_url,
            headers=headers,
            max_output_tokens=resolved_max_tokens,
            reasoning_effort=reasoning_effort,
            reasoning_enabled=reasoning_effort is not None,
            temperature=(
                getattr(options, "temperature", None) if options is not None else None
            ),
        )

    monkeypatch.setattr(
        "tests.protocols._runtime.resolve_request_for_model",
        _resolve,
    )


class _FakeAsyncOpenAI:
    last_init_kwargs: dict[str, object] = {}
    last_create_kwargs: dict[str, object] = {}
    chunks: list[object] = []
    response: object | None = None

    def __init__(self, **kwargs) -> None:
        type(self).last_init_kwargs = kwargs
        self.chat = SimpleNamespace(completions=_FakeCompletions(type(self)))


class _FakeCompletions:
    def __init__(self, owner: type[_FakeAsyncOpenAI]) -> None:
        self._owner = owner

    async def create(self, **kwargs):
        self._owner.last_create_kwargs = kwargs
        if kwargs.get("stream") is not True:
            return self._owner.response
        return _FakeStream(self._owner.chunks)


class _FakeStream:
    def __init__(self, chunks: list[object]) -> None:
        self._iterator = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


@dataclass(frozen=True)
class _Model:
    id: str = "gpt-test"
    base_url: str | None = None
    reasoning: bool = False
    input: tuple[str, ...] = ("text", "image")
    max_tokens: int | None = 4096
    headers: dict[str, str] = field(default_factory=dict)
    compat: dict[str, object] = field(default_factory=dict)
    defaults: dict[str, object] = field(default_factory=dict)
    pricing: Pricing | None = None
    provider_id: str = "openai"
    endpoint_id: str = "openai-completions"
