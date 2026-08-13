from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field, replace
from types import ModuleType, SimpleNamespace

import pytest

from loushang.ai import CallOptions, ReasoningOptions
from loushang.ai.auth import ApiKeyAuth, OAuthBearerAuth
from loushang.ai.context import NormalizedContext, normalize_context
from loushang.ai.errors import UnsupportedCapabilityError
from loushang.ai.model import (
    Auth,
    Capabilities,
    Model,
    OpenAIResponsesConfig,
    Pricing,
)
from loushang.ai.options import get_reasoning_effort, is_reasoning_requested
from loushang.ai.protocols._openai_responses import process_responses_stream
from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter
from loushang.ai.provider import ProviderRequest, resolve_request_for_model
from loushang.ai.structured import StructuredOutputOptions
from loushang.ai.types import (
    AssistantMessage,
    Context,
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


def _normalized_context(model, context, options=None):
    if not isinstance(model, Model) or not model.api:
        model = bound_test_model(
            model,
            api="openai-responses",
            options=options,
        )
    pairing_mode = (
        "strict" if getattr(options, "pairing_mode", "strict") == "strict" else "repair"
    )
    return normalize_context(context, model=model, pairing_mode=pairing_mode)


class _AsyncEventStream:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self._events:
            yield event


async def _collect_raw_parts(events: list[SimpleNamespace]) -> list[dict[str, object]]:
    return [part async for part in process_responses_stream(_AsyncEventStream(events))]


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


def _assert_no_session_hint_fields() -> None:
    assert "prompt_cache_key" not in _FakeAsyncOpenAI.last_create_kwargs
    assert "prompt_cache_retention" not in _FakeAsyncOpenAI.last_create_kwargs
    headers = _FakeAsyncOpenAI.last_create_kwargs.get("extra_headers") or {}
    assert "session_id" not in headers
    assert "x-client-request-id" not in headers
    assert "x-session-affinity" not in headers


def test_openai_responses_payload_maps_formal_context_and_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                Context(
                    system_prompt="You are helpful.",
                    messages=[UserMessage(role="user", content="hello", timestamp=0.0)],
                    tools=[
                        Tool(
                            name="calc",
                            description="Calculate values",
                            parameters={"type": "object"},
                        )
                    ],
                ),
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["input"] == [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
    ]
    assert _FakeAsyncOpenAI.last_create_kwargs["tools"] == [
        {
            "type": "function",
            "name": "calc",
            "description": "Calculate values",
            "parameters": {"type": "object"},
        }
    ]


def test_openai_responses_complete_mode_maps_non_stream_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        response=SimpleNamespace(
            id="resp_complete",
            status="failed",
            service_tier="priority",
            output=[
                SimpleNamespace(
                    type="reasoning",
                    id="rs_1",
                    summary=[SimpleNamespace(type="summary_text", text="plan")],
                ),
                SimpleNamespace(
                    type="message",
                    id="msg_1",
                    content=[SimpleNamespace(type="output_text", text="hello")],
                ),
                SimpleNamespace(
                    type="function_call",
                    id="fc_1",
                    call_id="call_1",
                    name="calc",
                    arguments={"x": 1},
                ),
            ],
            usage=SimpleNamespace(
                input_tokens=3,
                output_tokens=2,
                total_tokens=5,
                input_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
            error=SimpleNamespace(code="bad_request", message="boom"),
        ),
    )
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()

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
                CallOptions(
                    auth=ApiKeyAuth("test-key"),
                    reasoning=ReasoningOptions(effort="high"),
                ),
                mode="complete",
            )
        )
    )

    assert "stream" not in _FakeAsyncOpenAI.last_create_kwargs
    assert [part["type"] for part in parts] == [
        "response_start",
        "thinking_delta",
        "thinking_signature_delta",
        "text_delta",
        "text_signature_delta",
        "tool_call_start",
        "tool_call_args_delta",
        "tool_call_done",
        "usage_cost_multiplier",
        "usage_delta",
        "stop_reason",
        "response_error",
    ]
    assert parts[1] == {"type": "thinking_delta", "text": "plan"}
    assert parts[4]["signature"] == '{"v": 1, "id": "msg_1"}'
    assert parts[5]["id"] == "call_1|fc_1"
    assert parts[6]["delta"] == '{"x":1}'
    assert parts[8] == {"type": "usage_cost_multiplier", "multiplier": 2.0}
    assert parts[10] == {"type": "stop_reason", "stop_reason": "error"}


def test_openai_responses_payload_uses_resolved_capabilities_for_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        base_url="https://api.openai.test/v1",
        capabilities=Capabilities(input=("text", "image")),
    )
    provider = OpenAIResponsesAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(input=("text",)),
                Context(
                    system_prompt=None,
                    messages=[
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
                        ToolResultMessage(
                            role="toolResult",
                            tool_call_id="call_1",
                            tool_name="read",
                            content=[
                                ImagePart(
                                    type="image",
                                    data="dG9vbA==",
                                    mime_type="image/png",
                                )
                            ],
                            is_error=False,
                            timestamp=0.0,
                        ),
                    ],
                ),
                CallOptions(auth=ApiKeyAuth("test-key"), pairing_mode="repair"),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "look"},
                {
                    "type": "input_image",
                    "detail": "auto",
                    "image_url": "data:image/png;base64,dXNlcg==",
                },
            ],
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": [
                {
                    "type": "input_image",
                    "detail": "auto",
                    "image_url": "data:image/png;base64,dG9vbA==",
                }
            ],
        },
    ]


def test_openai_responses_payload_maps_structured_output_text_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        base_url="https://api.openai.test/v1",
        capabilities=Capabilities(input=("text",), structured_output=True),
    )
    provider = OpenAIResponsesAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                Context(
                    messages=[UserMessage(role="user", content="hello", timestamp=0.0)]
                ),
                CallOptions(
                    auth=ApiKeyAuth("test-key"),
                    output=StructuredOutputOptions(mode="json_object"),
                ),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["text"] == {
        "format": {"type": "json_object"}
    }


def test_openai_responses_direct_stream_rejects_mismatched_request_api() -> None:
    provider = OpenAIResponsesAdapter()
    request = make_provider_request(
        _Model(),
        api="openai-completions",
        provider_id="openai",
        endpoint_id="openai-responses",
        base_url=None,
        capabilities=Capabilities(input=("text",)),
    )

    with pytest.raises(ValueError, match="Mismatched api"):
        asyncio.run(
            _stream(
                provider,
                _Model(),
                {"messages": [UserMessage(role="user", content="hello", timestamp=0)]},
                CallOptions(),
                request,
            )
        )


def test_openai_responses_supplied_empty_request_uses_typed_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    provider = OpenAIResponsesAdapter()
    request = make_provider_request(
        _Model(reasoning=True),
        api="openai-responses",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        capabilities=Capabilities(input=("text",), reasoning=True),
        max_tokens=128,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(reasoning=True),
                Context(
                    system_prompt="Use terse answers.",
                    messages=[UserMessage(role="user", content="hello", timestamp=0.0)],
                ),
                CallOptions(
                    cache_retention="long",
                    cache_key="session-default",
                ),
                request,
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["input"][0] == {
        "role": "developer",
        "content": "Use terse answers.",
    }
    assert _FakeAsyncOpenAI.last_create_kwargs["prompt_cache_key"] == "session-default"
    assert _FakeAsyncOpenAI.last_create_kwargs["prompt_cache_retention"] == "24h"
    headers = _FakeAsyncOpenAI.last_create_kwargs.get("extra_headers") or {}
    assert "session_id" not in headers


def test_openai_responses_supplied_request_adapter_config_projects_to_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    provider = OpenAIResponsesAdapter()
    request = make_provider_request(
        _Model(reasoning=True),
        api="openai-responses",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAIResponsesConfig(
            developer_role=False,
            long_cache_retention=False,
        ),
        capabilities=Capabilities(input=("text",), reasoning=True),
        max_tokens=128,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(reasoning=True),
                _tool_result_followed_by_user_context(system_prompt="Use system."),
                CallOptions(
                    cache_retention="short",
                    cache_key="session-options",
                ),
                request,
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["input"] == [
        {"role": "system", "content": "Use system."},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "calc",
            "arguments": '{"x": 1}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "42",
        },
        {"role": "user", "content": [{"type": "input_text", "text": "next"}]},
    ]
    assert _FakeAsyncOpenAI.last_create_kwargs["prompt_cache_key"] == "session-options"
    assert "prompt_cache_retention" not in _FakeAsyncOpenAI.last_create_kwargs
    headers = _FakeAsyncOpenAI.last_create_kwargs.get("extra_headers") or {}
    assert "session_id" not in headers
    assert "x-client-request-id" not in headers


def test_openai_responses_ignores_unsupported_cache_key_without_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    provider = OpenAIResponsesAdapter()
    request = make_provider_request(
        _Model(reasoning=True),
        api="openai-responses",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAIResponsesConfig(prompt_cache_key=False),
        capabilities=Capabilities(input=("text",), reasoning=True),
        max_tokens=128,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(reasoning=True),
                Context(
                    system_prompt=None,
                    messages=[UserMessage(role="user", content="hello", timestamp=0)],
                ),
                CallOptions(
                    cache_retention="short",
                    cache_key="session-direct",
                ),
                request,
            )
        )
    )

    _assert_no_session_hint_fields()


def test_openai_responses_rejects_unsupported_long_cache_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    provider = OpenAIResponsesAdapter()
    request = make_provider_request(
        _Model(reasoning=True),
        api="openai-responses",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAIResponsesConfig(long_cache_retention=False),
        capabilities=Capabilities(input=("text",), reasoning=True),
        max_tokens=128,
    )

    with pytest.raises(UnsupportedCapabilityError, match="long cache retention"):
        asyncio.run(
            _collect_parts(
                _invoke_raw_parts(
                    provider,
                    _Model(reasoning=True),
                    Context(
                        system_prompt=None,
                        messages=[
                            UserMessage(role="user", content="hello", timestamp=0.0)
                        ],
                    ),
                    CallOptions(cache_retention="long"),
                    request,
                )
            )
        )

    assert _FakeAsyncOpenAI.last_create_kwargs == {}


def test_openai_responses_supplied_request_typed_adapter_overrides_stale_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    provider = OpenAIResponsesAdapter()
    request = make_provider_request(
        _Model(reasoning=True),
        api="openai-responses",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAIResponsesConfig(
            developer_role=False,
            long_cache_retention=False,
        ),
        capabilities=Capabilities(input=("text",), reasoning=True),
        max_tokens=128,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(reasoning=True),
                _tool_result_followed_by_user_context(system_prompt="Use system."),
                CallOptions(
                    cache_retention="short",
                    cache_key="session-typed",
                ),
                request,
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["input"] == [
        {"role": "system", "content": "Use system."},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "calc",
            "arguments": '{"x": 1}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "42",
        },
        {"role": "user", "content": [{"type": "input_text", "text": "next"}]},
    ]
    assert _FakeAsyncOpenAI.last_create_kwargs["prompt_cache_key"] == "session-typed"
    assert "prompt_cache_retention" not in _FakeAsyncOpenAI.last_create_kwargs
    headers = _FakeAsyncOpenAI.last_create_kwargs.get("extra_headers") or {}
    assert "session_id" not in headers
    assert "x-client-request-id" not in headers


def test_openai_responses_cache_retention_none_suppresses_cache_key_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    provider = OpenAIResponsesAdapter()
    request = make_provider_request(
        _Model(),
        api="openai-responses",
        base_url="https://api.openai.test/v1",
        headers={"Authorization": "Bearer test-key"},
        adapter_config=OpenAIResponsesConfig(prompt_cache_key=True),
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                Context(
                    messages=[UserMessage(role="user", content="hello", timestamp=0.0)]
                ),
                CallOptions(cache_retention="none", cache_key="opaque-cache-key"),
                request=request,
            )
        )
    )

    _assert_no_session_hint_fields()


def test_openai_responses_uses_upstream_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        base_url="https://api.openai.test/v1",
        upstream_model_id="openai/gpt-oss-120b:free",
    )
    provider = OpenAIResponsesAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(id="openai/gpt-oss-120b_free"),
                Context(
                    system_prompt=None,
                    messages=[UserMessage(role="user", content="hello", timestamp=0.0)],
                ),
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["model"] == "openai/gpt-oss-120b:free"


def test_openai_responses_caps_model_max_tokens_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        base_url="https://api.openai.test/v1",
        max_tokens=None,
    )
    provider = OpenAIResponsesAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(max_tokens=32768),
                Context(
                    system_prompt=None,
                    messages=[UserMessage(role="user", content="hello", timestamp=0.0)],
                    tools=[],
                ),
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["max_output_tokens"] == 32000


def test_openai_responses_uses_resolved_capability_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        base_url="https://api.openai.test/v1",
        max_tokens=None,
        capabilities=Capabilities(max_tokens=2048),
    )
    provider = OpenAIResponsesAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(max_tokens=1024),
                Context(
                    system_prompt=None,
                    messages=[UserMessage(role="user", content="hello", timestamp=0.0)],
                    tools=[],
                ),
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["max_output_tokens"] == 2048


def test_openai_responses_can_omit_model_default_max_output_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        base_url="https://api.openai.test/v1",
        adapter_config=OpenAIResponsesConfig(max_output_tokens=False),
    )
    provider = OpenAIResponsesAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                Context(
                    system_prompt=None,
                    messages=[UserMessage(role="user", content="hello", timestamp=0.0)],
                ),
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert "max_output_tokens" not in _FakeAsyncOpenAI.last_create_kwargs


def test_openai_responses_rejects_explicit_unsupported_max_output_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        base_url="https://api.openai.test/v1",
        adapter_config=OpenAIResponsesConfig(max_output_tokens=False),
    )
    provider = OpenAIResponsesAdapter()

    with pytest.raises(UnsupportedCapabilityError, match="max_output_tokens"):
        asyncio.run(
            _collect_parts(
                _invoke_raw_parts(
                    provider,
                    _Model(),
                    Context(
                        system_prompt=None,
                        messages=[
                            UserMessage(role="user", content="hello", timestamp=0.0)
                        ],
                    ),
                    CallOptions(auth=ApiKeyAuth("test-key"), max_output_tokens=16),
                )
            )
        )

    assert _FakeAsyncOpenAI.last_create_kwargs == {}


def test_openai_responses_payload_maps_assistant_tool_call_and_synthesizes_missing_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
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

    assert _FakeAsyncOpenAI.last_create_kwargs["input"] == [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "calc",
            "arguments": '{"x": 1}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "No result provided",
        },
    ]


def test_openai_responses_payload_normalizes_cross_provider_tool_call_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall", id="call:1|orig:item", name="calc", arguments={"x": 1}
            )
        ],
        api="anthropic-messages",
        provider="anthropic",
        endpoint="test-endpoint",
        model="claude-test",
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
        tool_call_id="call:1|orig:item",
        tool_name="calc",
        content=[TextPart(type="text", text="42")],
        is_error=False,
        timestamp=0.0,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                {"messages": [assistant, tool_result]},
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    function_call = _FakeAsyncOpenAI.last_create_kwargs["input"][0]
    function_output = _FakeAsyncOpenAI.last_create_kwargs["input"][1]
    assert function_call["type"] == "function_call"
    assert function_call["call_id"] == "call_1"
    assert function_call["id"].startswith("fc_")
    assert function_output == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "42",
    }


def _responses_tool_call_history(*, endpoint: str) -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="call_1|fc_source",
                name="calc",
                arguments={"x": 1},
            )
        ],
        api="openai-responses",
        provider="openai",
        endpoint=endpoint,
        model="gpt-test",
        response_id="resp_1",
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost={},
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


def test_openai_responses_reuses_item_id_for_same_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                OpenAIResponsesAdapter(),
                _Model(),
                {
                    "messages": [
                        _responses_tool_call_history(endpoint="openai-responses")
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key"), pairing_mode="repair"),
            )
        )
    )

    function_call = _FakeAsyncOpenAI.last_create_kwargs["input"][0]
    assert function_call["id"] == "fc_source"


def test_openai_responses_does_not_reuse_item_id_across_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                OpenAIResponsesAdapter(),
                _Model(),
                {
                    "messages": [
                        _responses_tool_call_history(endpoint="alternate-responses")
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key"), pairing_mode="repair"),
            )
        )
    )

    function_call = _FakeAsyncOpenAI.last_create_kwargs["input"][0]
    assert function_call["id"].startswith("fc_")
    assert function_call["id"] != "fc_source"


def test_openai_responses_payload_replays_assistant_thinking_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ThinkingPart(
                type="thinking",
                thinking="plan",
                thinking_signature='{"type":"reasoning","id":"rs_1","summary":[{"type":"summary_text","text":"plan"}]}',
            ),
            TextPart(type="text", text="done"),
        ],
        api="openai-responses",
        provider="openai",
        endpoint="openai-responses",
        model="gpt-test",
        response_id="resp_1",
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                {"messages": [assistant]},
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["input"] == [
        {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [{"type": "summary_text", "text": "plan"}],
        },
        {"role": "assistant", "content": "done"},
    ]


def test_openai_responses_payload_replays_assistant_text_signature_and_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()
    assistant = AssistantMessage(
        role="assistant",
        content=[
            TextPart(
                type="text",
                text="done",
                text_signature='{"v":1,"id":"msg_1","phase":"commentary"}',
            ),
        ],
        api="openai-responses",
        provider="openai",
        endpoint="openai-responses",
        model="gpt-test",
        response_id="resp_1",
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(),
                {"messages": [assistant]},
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["input"] == [
        {"role": "assistant", "content": "done", "id": "msg_1", "phase": "commentary"},
    ]


def test_openai_responses_payload_maps_reasoning_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(reasoning=True),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(
                    auth=ApiKeyAuth("test-key"),
                    reasoning=ReasoningOptions(effort="high", expose_summary=True),
                ),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["reasoning"] == {
        "effort": "high",
        "summary": "auto",
    }
    assert _FakeAsyncOpenAI.last_create_kwargs["include"] == [
        "reasoning.encrypted_content"
    ]


def test_openai_responses_explicit_reasoning_disable_overrides_effort() -> None:
    model = bound_test_model(
        _Model(reasoning=True),
        api="openai-responses",
        options=CallOptions(auth=ApiKeyAuth("test-key")),
        defaults={"reasoningEffort": "medium"},
    )
    request = resolve_request_for_model(
        model,
        options=CallOptions(
            auth=ApiKeyAuth("test-key"),
            reasoning=ReasoningOptions(enabled=False),
        ),
    )

    assert request.reasoning_enabled is False
    assert request.reasoning_effort is None


def test_openai_responses_uses_resolved_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    provider = OpenAIResponsesAdapter()
    request = make_provider_request(
        _Model(),
        api="openai-responses",
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


def test_openai_responses_payload_uses_resolved_capabilities_for_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        base_url="https://api.openai.test/v1",
        capabilities=Capabilities(reasoning=True),
    )
    provider = OpenAIResponsesAdapter()

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(reasoning=False),
                {
                    "messages": [
                        UserMessage(role="user", content="hello", timestamp=0.0)
                    ]
                },
                CallOptions(
                    auth=ApiKeyAuth("test-key"),
                    reasoning=ReasoningOptions(effort="high", expose_summary=True),
                ),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["reasoning"] == {
        "effort": "high",
        "summary": "auto",
    }
    assert _FakeAsyncOpenAI.last_create_kwargs["include"] == [
        "reasoning.encrypted_content"
    ]


def test_openai_responses_payload_maps_tool_result_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    _patch_resolved_request(
        monkeypatch,
        base_url="https://bridge.example/v1",
    )
    provider = OpenAIResponsesAdapter()
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
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
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="calc",
        content=[
            TextPart(type="text", text="before"),
            ImagePart(type="image", data="aGVsbG8=", mime_type="image/png"),
        ],
        is_error=False,
        timestamp=0.0,
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                provider,
                _Model(reasoning=True),
                {
                    "messages": [
                        assistant,
                        tool_result,
                        UserMessage(role="user", content="next", timestamp=0.0),
                    ]
                },
                CallOptions(auth=ApiKeyAuth("test-key")),
            )
        )
    )

    assert _FakeAsyncOpenAI.last_create_kwargs["input"] == [
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "calc",
            "arguments": '{"x": 1}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": [
                {"type": "input_text", "text": "before"},
                {
                    "type": "input_image",
                    "detail": "auto",
                    "image_url": "data:image/png;base64,aGVsbG8=",
                },
            ],
        },
        {"role": "user", "content": [{"type": "input_text", "text": "next"}]},
    ]


def test_openai_responses_stream_applies_priority_service_tier_cost_multiplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        events=[
            SimpleNamespace(
                type="response.created", response=SimpleNamespace(id="resp_1")
            ),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    status="completed",
                    service_tier="priority",
                    usage=SimpleNamespace(
                        input_tokens=2000,
                        output_tokens=500,
                        total_tokens=2500,
                        input_tokens_details=SimpleNamespace(cached_tokens=100),
                    ),
                ),
            ),
        ],
    )
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()

    stream = asyncio.run(
        _stream(
            provider,
            Model(
                id="gpt-test",
                provider="openai",
                endpoint="responses",
                pricing=Pricing(input=1.5, output=6.0, cache_read=0.3, cache_write=3.0),
            ),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(auth=ApiKeyAuth("test-key")),
        )
    )
    events = asyncio.run(_collect_stream_events(stream))

    message = events[-1]["message"]
    cost = message.usage.cost
    assert abs(cost["input"] - 0.0057) < 1e-9
    assert abs(cost["output"] - 0.006) < 1e-9
    assert abs(cost["cacheRead"] - 0.00006) < 1e-12
    assert (
        abs(cost["total"] - (cost["input"] + cost["output"] + cost["cacheRead"]))
        < 1e-12
    )


def test_openai_responses_stream_retains_thinking_signature_on_final_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        events=[
            SimpleNamespace(
                type="response.created", response=SimpleNamespace(id="resp_1")
            ),
            SimpleNamespace(
                type="response.output_item.added",
                item=SimpleNamespace(type="reasoning", id="rs_1", summary=[]),
            ),
            SimpleNamespace(
                type="response.reasoning_summary_part.added",
                part=SimpleNamespace(type="summary_text", text=""),
            ),
            SimpleNamespace(type="response.reasoning_summary_text.delta", delta="plan"),
            SimpleNamespace(
                type="response.output_item.done",
                item=SimpleNamespace(
                    type="reasoning",
                    id="rs_1",
                    summary=[SimpleNamespace(type="summary_text", text="plan")],
                ),
            ),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    status="completed",
                    usage=SimpleNamespace(
                        input_tokens=1,
                        output_tokens=1,
                        total_tokens=2,
                        input_tokens_details=SimpleNamespace(cached_tokens=0),
                    ),
                ),
            ),
        ],
    )
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()

    stream = asyncio.run(
        _stream(
            provider,
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(
                auth=ApiKeyAuth("test-key"),
                reasoning=ReasoningOptions(effort="high"),
            ),
        )
    )
    events = asyncio.run(_collect_stream_events(stream))

    assert [event["type"] for event in events] == [
        "start",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "done",
    ]
    assert events[-1]["message"].content[0].thinking == "plan"
    assert (
        events[-1]["message"].content[0].thinking_signature
        == '{"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "plan"}]}'
    )


def test_openai_responses_function_call_delta_uses_composite_call_id() -> None:
    parts = asyncio.run(
        _collect_raw_parts(
            [
                SimpleNamespace(
                    type="response.output_item.added",
                    output_index=1,
                    item=SimpleNamespace(
                        type="function_call",
                        id="fc_1",
                        call_id="call_1",
                        name="read",
                    ),
                ),
                SimpleNamespace(
                    type="response.function_call_arguments.delta",
                    item_id="fc_1",
                    output_index=1,
                    delta='{"path":',
                ),
                SimpleNamespace(
                    type="response.output_item.done",
                    output_index=1,
                    item=SimpleNamespace(
                        type="function_call",
                        id="fc_1",
                        call_id="call_1",
                    ),
                ),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(status="completed"),
                ),
            ]
        )
    )

    assert parts == [
        {
            "type": "tool_call_start",
            "id": "call_1|fc_1",
            "name": "read",
            "index": 1,
        },
        {
            "type": "tool_call_args_delta",
            "delta": '{"path":',
            "tool_call_id": "call_1|fc_1",
            "index": 1,
        },
        {
            "type": "tool_call_done",
            "tool_call_id": "call_1|fc_1",
            "index": 1,
        },
        {"type": "stop_reason", "stop_reason": "stop"},
        {"type": "response_done"},
    ]


def test_openai_responses_accepts_response_done_completion_alias() -> None:
    parts = asyncio.run(
        _collect_raw_parts(
            [
                SimpleNamespace(
                    type="response.done",
                    response=SimpleNamespace(
                        status="completed",
                        usage=SimpleNamespace(
                            input_tokens=3,
                            output_tokens=2,
                            total_tokens=5,
                            input_tokens_details=SimpleNamespace(cached_tokens=1),
                        ),
                    ),
                )
            ]
        )
    )

    assert parts == [
        {
            "type": "usage_delta",
            "input": 2,
            "output": 2,
            "cache_read": 1,
            "cache_write": 0,
            "total_tokens": 5,
        },
        {"type": "stop_reason", "stop_reason": "stop"},
        {"type": "response_done"},
    ]


@pytest.mark.parametrize("reason", ["max_output_tokens", "max_tokens", "length"])
def test_openai_responses_incomplete_length_is_successful_truncation(
    reason: str,
) -> None:
    parts = asyncio.run(
        _collect_raw_parts(
            [
                SimpleNamespace(
                    type="response.incomplete",
                    response=SimpleNamespace(
                        id="resp_incomplete",
                        status="incomplete",
                        incomplete_details=SimpleNamespace(reason=reason),
                        usage=SimpleNamespace(
                            input_tokens=3,
                            output_tokens=2,
                            total_tokens=5,
                            input_tokens_details=SimpleNamespace(cached_tokens=1),
                        ),
                    ),
                )
            ]
        )
    )

    assert parts[-2:] == [
        {"type": "stop_reason", "stop_reason": "length"},
        {"type": "response_done"},
    ]
    assert parts[0] == {"type": "response_start", "response_id": "resp_incomplete"}
    assert parts[1]["type"] == "usage_delta"


def test_openai_responses_unclassified_incomplete_is_error() -> None:
    parts = asyncio.run(
        _collect_raw_parts(
            [
                SimpleNamespace(
                    type="response.incomplete",
                    response=SimpleNamespace(
                        id="resp_incomplete",
                        status="incomplete",
                        incomplete_details=SimpleNamespace(reason="content_filter"),
                        usage=None,
                    ),
                ),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(status="completed"),
                ),
            ]
        )
    )

    assert [part["type"] for part in parts] == [
        "response_start",
        "stop_reason",
        "response_error",
    ]


def test_openai_responses_failed_is_error_without_success_terminal() -> None:
    parts = asyncio.run(
        _collect_raw_parts(
            [
                SimpleNamespace(
                    type="response.failed",
                    response=SimpleNamespace(
                        id="resp_failed",
                        status="failed",
                        error=SimpleNamespace(code="server_error", message="failed"),
                        usage=None,
                    ),
                ),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(status="completed"),
                ),
            ]
        )
    )

    assert [part["type"] for part in parts] == [
        "response_start",
        "stop_reason",
        "response_error",
    ]


def test_openai_responses_stream_joins_multiple_reasoning_summary_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        events=[
            SimpleNamespace(
                type="response.created", response=SimpleNamespace(id="resp_1")
            ),
            SimpleNamespace(
                type="response.output_item.added",
                item=SimpleNamespace(type="reasoning", id="rs_1", summary=[]),
            ),
            SimpleNamespace(
                type="response.reasoning_summary_part.added",
                part=SimpleNamespace(type="summary_text", text=""),
            ),
            SimpleNamespace(
                type="response.reasoning_summary_text.delta", delta="first"
            ),
            SimpleNamespace(type="response.reasoning_summary_part.done"),
            SimpleNamespace(
                type="response.reasoning_summary_part.added",
                part=SimpleNamespace(type="summary_text", text=""),
            ),
            SimpleNamespace(
                type="response.reasoning_summary_text.delta", delta="second"
            ),
            SimpleNamespace(
                type="response.output_item.done",
                item=SimpleNamespace(
                    type="reasoning",
                    id="rs_1",
                    summary=[
                        SimpleNamespace(type="summary_text", text="first"),
                        SimpleNamespace(type="summary_text", text="second"),
                    ],
                ),
            ),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    status="completed",
                    usage=SimpleNamespace(
                        input_tokens=1,
                        output_tokens=1,
                        total_tokens=2,
                        input_tokens_details=SimpleNamespace(cached_tokens=0),
                    ),
                ),
            ),
        ],
    )
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()

    stream = asyncio.run(
        _stream(
            provider,
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(
                auth=ApiKeyAuth("test-key"),
                reasoning=ReasoningOptions(effort="high"),
            ),
        )
    )
    events = asyncio.run(_collect_stream_events(stream))

    assert [event["type"] for event in events] == [
        "start",
        "thinking_start",
        "thinking_delta",
        "thinking_delta",
        "thinking_delta",
        "thinking_end",
        "done",
    ]
    assert events[-1]["message"].content[0].thinking == "first\n\nsecond"


def test_openai_responses_stream_retains_text_signature_on_final_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(
        monkeypatch,
        events=[
            SimpleNamespace(
                type="response.created", response=SimpleNamespace(id="resp_1")
            ),
            SimpleNamespace(
                type="response.output_item.added",
                item=SimpleNamespace(
                    type="message", id="msg_1", content=[], phase="final_answer"
                ),
            ),
            SimpleNamespace(type="response.output_text.delta", delta="Hello"),
            SimpleNamespace(
                type="response.output_item.done",
                item=SimpleNamespace(
                    type="message",
                    id="msg_1",
                    phase="final_answer",
                    content=[SimpleNamespace(type="output_text", text="Hello")],
                ),
            ),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    status="completed",
                    usage=SimpleNamespace(
                        input_tokens=1,
                        output_tokens=1,
                        total_tokens=2,
                        input_tokens_details=SimpleNamespace(cached_tokens=0),
                    ),
                ),
            ),
        ],
    )
    _patch_resolved_request(monkeypatch, base_url="https://api.openai.test/v1")
    provider = OpenAIResponsesAdapter()

    stream = asyncio.run(
        _stream(
            provider,
            _Model(),
            {"messages": [UserMessage(role="user", content="hello", timestamp=0.0)]},
            CallOptions(auth=ApiKeyAuth("test-key")),
        )
    )
    events = asyncio.run(_collect_stream_events(stream))

    assert [event["type"] for event in events] == [
        "start",
        "text_start",
        "text_delta",
        "text_end",
        "done",
    ]
    assert events[-1]["message"].content[0].text == "Hello"
    assert (
        events[-1]["message"].content[0].text_signature
        == '{"v": 1, "id": "msg_1", "phase": "final_answer"}'
    )


async def _collect_parts(source) -> list[dict]:
    return [part async for part in source]


async def _collect_stream_events(stream) -> list[dict]:
    return [event async for event in stream]


def _tool_result_followed_by_user_context(*, system_prompt: str) -> Context:
    assistant = AssistantMessage(
        role="assistant",
        content=[
            ToolCall(type="toolCall", id="call_1", name="calc", arguments={"x": 1})
        ],
        api="openai-responses",
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
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="call_1",
        tool_name="calc",
        content=[TextPart(type="text", text="42")],
        is_error=False,
        timestamp=0.0,
    )
    return Context(
        system_prompt=system_prompt,
        messages=[
            assistant,
            tool_result,
            UserMessage(role="user", content="next", timestamp=0.0),
        ],
    )


def _fake_openai_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[object] | None = None,
    response: object | None = None,
) -> None:
    _FakeAsyncOpenAI.last_init_kwargs = {}
    _FakeAsyncOpenAI.last_create_kwargs = {}
    _FakeAsyncOpenAI.response = response
    _FakeAsyncOpenAI.events = events or [
        SimpleNamespace(type="response.created", response=SimpleNamespace(id="resp_1")),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                status="completed",
                usage=SimpleNamespace(
                    input_tokens=1,
                    output_tokens=1,
                    total_tokens=2,
                    input_tokens_details=SimpleNamespace(cached_tokens=0),
                ),
            ),
        ),
    ]
    module = ModuleType("openai")
    module.AsyncOpenAI = _FakeAsyncOpenAI
    module.Omit = _FakeOmit
    monkeypatch.setitem(sys.modules, "openai", module)


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
def test_openai_responses_forwards_authoritative_auth_headers(
    monkeypatch: pytest.MonkeyPatch,
    auth,
    expected_headers: dict[str, str],
) -> None:
    _fake_openai_module(monkeypatch)

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                OpenAIResponsesAdapter(),
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


def test_openai_responses_uses_catalog_auth_header_and_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_openai_module(monkeypatch)
    model = bound_test_model(
        _Model(),
        api="openai-responses",
        auth=Auth(kind="apiKey", header="X-Custom-Auth", prefix="Token "),
    )

    asyncio.run(
        _collect_parts(
            _invoke_raw_parts(
                OpenAIResponsesAdapter(),
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


class _FakeOmit:
    pass


def _patch_resolved_request(
    monkeypatch: pytest.MonkeyPatch,
    *,
    base_url: str,
    compat: dict[str, object] | None = None,
    adapter_config: OpenAIResponsesConfig | None = None,
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
        resolved_adapter = adapter_config or _responses_adapter_config_from_compat(
            compat or {}
        )
        resolved_capabilities = capabilities or Capabilities(
            input=tuple(getattr(_model, "input", ("text",))),
            reasoning=bool(getattr(_model, "reasoning", False)),
            max_tokens=getattr(_model, "max_tokens", None),
        )
        request_model = bound_test_model(
            _model,
            api="openai-responses",
            options=options,
            base_url=base_url,
            adapter_config=resolved_adapter,
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
            reasoning_enabled=(
                is_reasoning_requested(options)
                if getattr(options, "reasoning", None) is not None
                else None
            ),
            reasoning_effort=get_reasoning_effort(options),
            temperature=(
                getattr(options, "temperature", None) if options is not None else None
            ),
        )

    monkeypatch.setattr(
        "tests.protocols._runtime.resolve_request_for_model",
        _resolve,
    )


def _responses_adapter_config_from_compat(
    compat: dict[str, object],
) -> OpenAIResponsesConfig:
    return OpenAIResponsesConfig(
        developer_role=bool(compat.get("supportsDeveloperRole", True)),
        long_cache_retention=bool(compat.get("supportsLongCacheRetention", True)),
        prompt_cache_key=bool(compat.get("supportsPromptCacheKey", True)),
    )


class _FakeAsyncOpenAI:
    last_init_kwargs: dict[str, object] = {}
    last_create_kwargs: dict[str, object] = {}
    events: list[object] = []
    response: object | None = None

    def __init__(self, **kwargs) -> None:
        type(self).last_init_kwargs = kwargs
        self.responses = _FakeResponses(type(self))


class _FakeResponses:
    def __init__(self, owner: type[_FakeAsyncOpenAI]) -> None:
        self._owner = owner

    async def create(self, **kwargs):
        self._owner.last_create_kwargs = kwargs
        if kwargs.get("stream") is not True:
            return self._owner.response
        return _FakeStream(self._owner.events)


class _FakeStream:
    def __init__(self, events: list[object]) -> None:
        self._iterator = iter(events)

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
    reasoning: bool = False
    input: tuple[str, ...] = ("text", "image")
    max_tokens: int | None = 4096
    headers: dict[str, str] = field(default_factory=dict)
    compat: dict[str, object] = field(default_factory=dict)
    defaults: dict[str, object] = field(default_factory=dict)
    provider_id: str = "openai"
    endpoint_id: str = "openai-responses"
