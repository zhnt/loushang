from __future__ import annotations

import asyncio

import pytest

import loushang.harness.transcript.summarization as summary_module
from loushang.ai import CallOptions, Context
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.harness.transcript.summarization import default_summary_completer


def _model(*, supports_stream: bool) -> Model:
    return Model(
        id="summary-model",
        name="Summary",
        provider="test-provider",
        endpoint="anthropic-messages",
        api="anthropic-messages",
        capabilities=Capabilities(
            stream=supports_stream,
            context_window=1_024,
            max_tokens=128,
        ),
    )


def _message(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="anthropic-messages",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="anthropic-messages",
        provider="test-provider",
        model="summary-model",
        response_id="response-1",
        usage=Usage(
            input=1,
            output=1,
            cache_read=0,
            cache_write=0,
            total_tokens=2,
            cost=None,
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0,
    )


@pytest.mark.parametrize("supports_stream", [True, False])
def test_default_summary_completer_traces_selected_invocation_mode(
    monkeypatch: pytest.MonkeyPatch,
    supports_stream: bool,
) -> None:
    trace_events: list[dict[str, object]] = []
    calls: list[str] = []

    class _Stream:
        async def result(self) -> AssistantMessage:
            return _message("stream summary")

    async def fake_stream(*args, **kwargs):
        del args, kwargs
        calls.append("stream")
        return _Stream()

    async def fake_complete(*args, **kwargs):
        del args, kwargs
        calls.append("complete")
        return _message("complete summary")

    monkeypatch.setattr(summary_module, "stream", fake_stream)
    monkeypatch.setattr(summary_module, "complete", fake_complete)
    mode = "stream" if supports_stream else "complete"

    result = asyncio.run(
        default_summary_completer(
            _model(supports_stream=supports_stream),
            Context(),
            CallOptions(trace=trace_events.append),
        )
    )

    assert calls == [mode]
    assert result == f"{mode} summary"
    assert trace_events == [
        {
            "schema": "loushang.ai.trace.v1",
            "type": "summary:request",
            "source": "summary",
            "name": "request",
            "data": {
                "mode": mode,
                "api": "anthropic-messages",
                "provider": "test-provider",
                "endpoint": "anthropic-messages",
                "model": "summary-model",
            },
        }
    ]
