"""Real OpenAI SDK response -> history -> next HTTP request, without inference."""

from __future__ import annotations

import asyncio
import json

import httpx
import openai
import pytest

from loushang.ai import ApiKeyAuth, CallOptions, complete, stream
from loushang.ai.model import load_builtin_model_registry
from loushang.ai.model.domain import Capabilities, Model, OpenAICompletionsConfig
from loushang.ai.types import (
    TextPart,
    ThinkingPart,
    Tool,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

REASONING = "distinct-original-reasoning"
FIELDS = ("reasoning_content", "reasoning", "reasoning_text")


@pytest.fixture(params=["contiguous", "text-between", "tool-between"])
def sdk_http(monkeypatch, request):
    captured = []
    clients = []
    real_client = openai.AsyncOpenAI
    response_field = {"name": "reasoning_content"}
    sequence = request.param

    def handle(request):
        payload = json.loads(request.content)
        captured.append((str(request.url), payload))
        first = len(captured) == 1
        field = response_field["name"]
        function = {"name": "lookup", "arguments": '{"q":"cat"}'}
        tool = {"id": "call_offline", "type": "function", "function": function}
        message = {"role": "assistant", "content": "working" if first else "done"}
        if first:
            message["tool_calls"] = [tool]
            if field is not None:
                message[field] = REASONING
        finish = "tool_calls" if first else "stop"
        envelope = {"id": "chatcmpl_offline", "created": 0, "model": payload["model"]}
        if not payload.get("stream"):
            return httpx.Response(
                200,
                json={
                    **envelope,
                    "object": "chat.completion",
                    "choices": [
                        {"index": 0, "message": message, "finish_reason": finish}
                    ],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    },
                },
            )
        deltas = []
        if first and field is not None:
            # Two chunks catch accidental concatenation of the field-name marker.
            deltas.extend([{field: "distinct-original-"}, {field: "reasoning"}])
        deltas.append({"role": "assistant", "content": message["content"]})
        if first:
            deltas.extend(
                [
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                **tool,
                                "function": {"name": "lookup", "arguments": '{"q":'},
                            }
                        ]
                    },
                    {"tool_calls": [{"index": 0, "function": {"arguments": '"cat"}'}}]},
                ]
            )
        if first and field is not None and sequence != "contiguous":
            # Synthetic compatible sequences, not a claim about live MiniMax.
            deltas[0] = {field: "distinct-"}
            deltas.pop(1)
            insert_at = 2 if sequence == "text-between" else len(deltas)
            deltas.insert(insert_at, {field: "original-reasoning"})
        chunks = [
            {
                **envelope,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
            for delta in deltas
        ]
        chunks.append(
            {
                **envelope,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            }
        )
        body = (
            "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body
        )

    def factory(**kwargs):
        client = real_client(
            **kwargs,
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        )
        clients.append(client)
        return client

    monkeypatch.setattr(openai, "AsyncOpenAI", factory)
    return captured, clients, response_field


def roundtrip(model, mode, clients):
    async def run():
        tools = [
            Tool(
                "lookup",
                "Find a term",
                {"type": "object", "properties": {"q": {"type": "string"}}},
            )
        ]
        user = UserMessage("user", "look up cat", 0.0)
        options = CallOptions(auth=ApiKeyAuth("offline-fixture"))

        async def call(messages):
            context = {"messages": messages, "tools": tools}
            if mode == "complete":
                return await complete(model, context, options)
            events = await stream(model, context, options)
            return await events.result()

        try:
            assistant = await call([user])
            tool_call = next(
                part for part in assistant.content if isinstance(part, ToolCall)
            )
            assert tool_call.name == "lookup"
            assert tool_call.arguments == {"q": "cat"}
            result = ToolResultMessage(
                "toolResult",
                tool_call.id,
                tool_call.name,
                [TextPart("text", "found cat")],
                False,
                0.0,
            )
            followup = await call([user, assistant, result])
            assert followup.stop_reason == "stop"
            assert assistant.stop_reason == "toolUse"
            return assistant
        finally:
            for client in clients:
                await client.close()

    return asyncio.run(run())


@pytest.mark.parametrize("endpoint", ["openai-completions", "openai-completions-cn"])
@pytest.mark.parametrize("mode", ["complete", "stream"])
def test_minimax_real_sdk_preserves_reasoning_through_tool_roundtrip(
    sdk_http, endpoint, mode
):
    captured, clients, _ = sdk_http
    model = load_builtin_model_registry().get_model(
        "minimax", endpoint, "MiniMax-M3.1-Flash"
    )
    assistant = roundtrip(model, mode, clients)
    thinking = next(
        part for part in assistant.content if isinstance(part, ThinkingPart)
    )
    assert thinking.thinking == REASONING
    assert len(captured) == 2
    expected_host = "api.minimaxi.com" if endpoint.endswith("-cn") else "api.minimax.io"
    assert [url for url, _ in captured] == [
        f"https://{expected_host}/v1/chat/completions"
    ] * 2
    history = captured[1][1]["messages"]
    replay = next(message for message in history if message["role"] == "assistant")
    assert set(replay) == {"role", "content", "tool_calls", "reasoning_content"}
    assert replay["reasoning_content"] == REASONING
    assert thinking.thinking_signature == "reasoning_content"
    assert replay["content"] == "working"
    assert replay["tool_calls"][0]["id"] == "call_offline"
    assert json.loads(replay["tool_calls"][0]["function"]["arguments"]) == {"q": "cat"}
    assert history[-1] == {
        "role": "tool",
        "tool_call_id": "call_offline",
        "content": "found cat",
    }
    for _, payload in captured:
        assert payload["model"] == "MiniMax-M3.1-Flash"
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["reasoning_effort"] == "max"
        assert payload.get("stream", False) == (mode == "stream")
        assert "reasoning" not in replay and "reasoning_text" not in replay


@pytest.mark.parametrize("field", [*FIELDS, None])
@pytest.mark.parametrize("mode", ["complete", "stream"])
def test_non_minimax_real_sdk_retains_original_field_semantics(sdk_http, field, mode):
    captured, clients, response_field = sdk_http
    response_field["name"] = field
    model = Model(
        id="custom-model",
        provider="custom",
        endpoint="chat",
        api="openai-completions",
        base_url="https://custom.example/v1",
        capabilities=Capabilities(reasoning=True, tool_use=True, stream=True),
        adapter=OpenAICompletionsConfig(),
    )
    assistant = roundtrip(model, mode, clients)
    replay = next(
        message
        for message in captured[1][1]["messages"]
        if message["role"] == "assistant"
    )
    if field is not None:
        assert replay[field] == REASONING
        thinking = next(
            part for part in assistant.content if isinstance(part, ThinkingPart)
        )
        assert thinking.thinking == REASONING
        assert thinking.thinking_signature == field
    else:
        assert not any(isinstance(part, ThinkingPart) for part in assistant.content)
    assert set(replay) == {"role", "content", "tool_calls"} | (
        {field} if field else set()
    )
    assert replay["content"] == "working"
    assert replay["tool_calls"][0]["id"] == "call_offline"
    assert all(
        url == "https://custom.example/v1/chat/completions" for url, _ in captured
    )
    assert all(payload["model"] == "custom-model" for _, payload in captured)
