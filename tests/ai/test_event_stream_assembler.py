from __future__ import annotations

import asyncio

import pytest

from loushang.ai.errors import AICancelledError, AIRateLimitError, AIStreamError
from loushang.ai.event_stream import AssistantMessageEventStream, RawAssembler
from loushang.ai.model import Pricing
from loushang.ai.types import AssistantMessage, Usage


def test_raw_assembler_uses_real_content_index_for_thinking_only_stream() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
    )

    assembler.feed({"type": "response_start", "response_id": "resp_1"})
    assembler.feed({"type": "thinking_delta", "text": "plan"})
    assembler.feed(
        {
            "type": "thinking_signature_delta",
            "signature": '{"type":"reasoning","id":"rs_1","summary":[]}',
        }
    )
    assembler.feed({"type": "response_done"})

    events = asyncio.run(_collect_events(stream))

    assert [event["type"] for event in events] == [
        "start",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "done",
    ]
    assert events[1]["content_index"] == 0
    assert events[0]["partial"].endpoint == "test-endpoint"
    assert events[-1]["message"].endpoint == "test-endpoint"
    assert events[-1]["message"].content[0].type == "thinking"
    assert events[-1]["message"].content[0].thinking == "plan"


def test_raw_assembler_uses_real_content_index_for_toolcall_only_stream() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-completions",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
    )

    assembler.feed({"type": "response_start", "response_id": "resp_1"})
    assembler.feed({"type": "tool_call_start", "id": "call_1", "name": "calc"})
    assembler.feed({"type": "tool_call_args_delta", "delta": '{"x":1}'})
    assembler.feed({"type": "tool_call_done"})
    assembler.feed({"type": "response_done"})

    events = asyncio.run(_collect_events(stream))

    assert [event["type"] for event in events] == [
        "start",
        "toolcall_start",
        "toolcall_delta",
        "toolcall_end",
        "done",
    ]
    assert events[1]["content_index"] == 0
    assert events[2]["content_index"] == 0
    assert events[3]["content_index"] == 0
    assert events[-1]["message"].content[0].type == "toolCall"
    assert events[-1]["message"].content[0].arguments == {"x": 1}


def test_raw_assembler_groups_interleaved_tool_calls_by_id_and_index() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-completions",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
    )

    assembler.feed({"type": "response_start", "response_id": "resp_1"})
    assembler.feed(
        {"type": "tool_call_start", "id": "call_a", "name": "add", "index": 0}
    )
    assembler.feed(
        {"type": "tool_call_start", "id": "call_b", "name": "mul", "index": 1}
    )
    assembler.feed(
        {
            "type": "tool_call_args_delta",
            "tool_call_id": "call_a",
            "index": 1,
            "delta": '{"a":',
        }
    )
    assembler.feed({"type": "tool_call_args_delta", "index": 1, "delta": '{"x":'})
    assembler.feed({"type": "tool_call_args_delta", "index": 0, "delta": "1}"})
    assembler.feed(
        {"type": "tool_call_args_delta", "tool_call_id": "call_b", "delta": "2}"}
    )
    assembler.feed({"type": "tool_call_done", "index": 1})
    assembler.feed({"type": "tool_call_done", "tool_call_id": "call_a"})
    assembler.feed({"type": "response_done"})

    events = asyncio.run(_collect_events(stream))

    assert [event["type"] for event in events] == [
        "start",
        "toolcall_start",
        "toolcall_start",
        "toolcall_delta",
        "toolcall_delta",
        "toolcall_delta",
        "toolcall_delta",
        "toolcall_end",
        "toolcall_end",
        "done",
    ]
    assert [events[index]["content_index"] for index in range(1, 9)] == [
        0,
        1,
        0,
        1,
        0,
        1,
        1,
        0,
    ]
    done = events[-1]["message"]
    assert [part.id for part in done.content] == ["call_a", "call_b"]
    assert done.content[0].arguments == {"a": 1}
    assert done.content[1].arguments == {"x": 2}


def test_raw_assembler_preserves_content_order_across_block_types() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
    )

    assembler.feed({"type": "response_start", "response_id": "resp_1"})
    assembler.feed({"type": "thinking_delta", "text": "plan"})
    assembler.feed({"type": "text_delta", "text": "answer"})
    assembler.feed({"type": "tool_call_start", "id": "call_1", "name": "calc"})
    assembler.feed({"type": "tool_call_args_delta", "delta": '{"x":1}'})
    assembler.feed({"type": "tool_call_done"})
    assembler.feed({"type": "response_done"})

    events = asyncio.run(_collect_events(stream))

    assert events[1]["type"] == "thinking_start"
    assert events[1]["content_index"] == 0
    assert events[3]["type"] == "text_start"
    assert events[3]["content_index"] == 1
    assert events[5]["type"] == "toolcall_start"
    assert events[5]["content_index"] == 2
    assert events[8]["type"] == "thinking_end"
    assert events[8]["content_index"] == 0
    assert events[9]["type"] == "text_end"
    assert events[9]["content_index"] == 1
    assert [part.type for part in events[-1]["message"].content] == [
        "thinking",
        "text",
        "toolCall",
    ]


async def _collect_events(stream: AssistantMessageEventStream) -> list[dict]:
    return [event async for event in stream]


def _empty_message() -> AssistantMessage:
    return AssistantMessage(
        role="assistant",
        content=[],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def test_event_stream_cancels_producer_when_consumer_stops() -> None:
    async def scenario() -> bool:
        stream = AssistantMessageEventStream()
        cancelled = asyncio.Event()
        message = AssistantMessage(
            role="assistant",
            content=[],
            api="openai-responses",
            provider="openai",
            endpoint="test-endpoint",
            model="gpt-test",
            response_id=None,
            usage=Usage(
                input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=0.0,
        )

        async def producer() -> None:
            try:
                stream.push({"type": "start", "partial": message})
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(producer())
        stream.attach_task(task)
        async for _event in stream:
            break
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        return task.cancelled()

    assert asyncio.run(scenario())


def test_event_stream_push_preserves_terminal_event_when_queue_is_full() -> None:
    stream = AssistantMessageEventStream(max_queue_size=1)
    message = _empty_message()

    stream.push({"type": "start", "partial": message})
    stream.push({"type": "done", "reason": "stop", "message": message})

    events = asyncio.run(_collect_events(stream))

    assert [event["type"] for event in events] == ["done"]
    assert asyncio.run(stream.result()) is message


def test_event_stream_end_preserves_terminal_event_when_queue_is_full() -> None:
    stream = AssistantMessageEventStream(max_queue_size=1)
    message = _empty_message()

    stream.push({"type": "start", "partial": message})
    stream.end(message)

    events = asyncio.run(_collect_events(stream))

    assert [event["type"] for event in events] == ["done"]
    assert asyncio.run(stream.result()) is message


def test_event_stream_emit_waits_when_queue_is_full() -> None:
    async def scenario() -> bool:
        stream = AssistantMessageEventStream(max_queue_size=1)
        message = AssistantMessage(
            role="assistant",
            content=[],
            api="openai-responses",
            provider="openai",
            endpoint="test-endpoint",
            model="gpt-test",
            response_id=None,
            usage=Usage(
                input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
            ),
            stop_reason="stop",
            error_message=None,
            timestamp=0.0,
        )
        await stream.emit({"type": "start", "partial": message})
        second_emit = asyncio.create_task(
            stream.emit({"type": "text_start", "content_index": 0, "partial": message})
        )
        await asyncio.sleep(0)
        blocked = not second_emit.done()
        iterator = stream.__aiter__()
        assert (await iterator.__anext__())["type"] == "start"
        await asyncio.wait_for(second_emit, timeout=1)
        await stream.aclose()
        return blocked

    assert asyncio.run(scenario()) is True


def test_event_stream_result_preserves_producer_exception() -> None:
    async def scenario() -> None:
        stream = AssistantMessageEventStream()

        async def producer() -> None:
            raise ValueError("boom")

        stream.attach_task(asyncio.create_task(producer()))
        await stream.result()

    try:
        asyncio.run(scenario())
    except RuntimeError as exc:
        assert "producer failed" in str(exc)
        assert isinstance(exc.__cause__, ValueError)
    else:  # pragma: no cover
        raise AssertionError("expected producer exception")


def test_event_stream_result_waits_for_producer_cleanup_after_terminal() -> None:
    async def scenario() -> None:
        stream = AssistantMessageEventStream()
        message = _empty_message()
        cleanup_started = asyncio.Event()
        cleanup_can_finish = asyncio.Event()
        cleanup_done = asyncio.Event()

        async def producer() -> None:
            await stream.emit({"type": "done", "reason": "stop", "message": message})
            cleanup_started.set()
            await cleanup_can_finish.wait()
            cleanup_done.set()

        stream.attach_task(asyncio.create_task(producer()))
        result_task = asyncio.create_task(stream.result())

        await asyncio.wait_for(cleanup_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert not result_task.done()

        cleanup_can_finish.set()
        assert await asyncio.wait_for(result_task, timeout=1) is message
        assert cleanup_done.is_set()

    asyncio.run(scenario())


def test_raw_assembler_preserves_http_error_code() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
    )

    assembler.feed(
        {
            "type": "response_error",
            "message": "rate limited",
            "code": 429,
        }
    )

    events = asyncio.run(_collect_events(stream))

    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == 429
    assert events[-1]["error_info"]["code"] == "rate_limit"
    assert events[-1]["error_info"]["source"] == "openai-responses"
    assert events[-1]["error_info"]["retryable"] is True
    assert events[-1]["error_info"]["provider"] == "openai"
    assert events[-1]["error_info"]["endpoint"] == "test-endpoint"
    assert events[-1]["error_info"]["model"] == "gpt-test"
    assert events[-1]["error"].endpoint == "test-endpoint"


def test_event_stream_result_raises_typed_error_for_error_terminal() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
    )

    assembler.feed(
        {
            "type": "response_error",
            "message": "rate limited",
            "code": 429,
            "error_info": {
                "code": "rate_limit",
                "message": "rate limited",
                "source": "openai-responses",
                "retryable": True,
                "provider": "openai",
                "endpoint": "wrong-endpoint",
                "model": "gpt-test",
                "statusCode": 429,
                "requestId": "req_123",
                "details": {},
            },
        }
    )

    with pytest.raises(AIRateLimitError) as exc_info:
        asyncio.run(stream.result())

    error = exc_info.value
    assert error.info.status_code == 429
    assert error.info.request_id == "req_123"
    assert error.info.retryable is True
    assert error.info.endpoint == "test-endpoint"

    message = asyncio.run(stream.final_message())
    assert message.stop_reason == "error"
    assert message.error_message == "Provider rate limit exceeded."
    assert message.error_info is not None
    assert message.error_info["code"] == "rate_limit"
    assert message.error_info["requestId"] == "req_123"
    assert message.endpoint == "test-endpoint"


def test_event_stream_fallback_error_uses_message_endpoint() -> None:
    stream = AssistantMessageEventStream()
    message = AssistantMessage(
        role="assistant",
        content=[],
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost=None,
        ),
        stop_reason="error",
        error_message="stream failed",
        timestamp=0.0,
    )
    stream.push({"type": "error", "reason": "error", "error": message})

    with pytest.raises(AIStreamError) as exc_info:
        asyncio.run(stream.result())

    assert exc_info.value.info.endpoint == "test-endpoint"
    assert asyncio.run(stream.final_message()).endpoint == "test-endpoint"


def test_event_stream_result_raises_cancelled_for_aborted_terminal() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
    )

    assembler.feed({"type": "aborted"})

    with pytest.raises(AICancelledError) as exc_info:
        asyncio.run(stream.result())

    assert exc_info.value.info.provider == "openai"
    assert exc_info.value.info.endpoint == "test-endpoint"
    assert exc_info.value.info.model == "gpt-test"
    message = asyncio.run(stream.final_message())
    assert message.stop_reason == "aborted"
    assert message.endpoint == "test-endpoint"


def test_raw_assembler_keeps_first_terminal_event() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
    )

    assembler.feed({"type": "response_done"})
    assembler.feed({"type": "response_error", "message": "late error", "code": 500})

    events = asyncio.run(_collect_events(stream))

    assert [event["type"] for event in events] == ["done"]
    assert events[0]["message"].stop_reason == "stop"
    assert asyncio.run(stream.result()).stop_reason == "stop"


def test_raw_assembler_uses_clock_timestamp_for_final_message() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
        clock=lambda: 123.5,
    )

    assembler.feed({"type": "response_done"})

    message = asyncio.run(stream.result())

    assert message.timestamp == 123.5


def test_raw_assembler_omits_non_http_top_level_code_but_normalizes_known_code() -> (
    None
):
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="openai-responses",
        provider="openai",
        endpoint="test-endpoint",
        model="gpt-test",
    )

    assembler.feed(
        {
            "type": "response_error",
            "message": "rate limited",
            "code": "rate_limit",  # type: ignore[typeddict-item]
        }
    )

    events = asyncio.run(_collect_events(stream))

    assert events[-1]["type"] == "error"
    assert "code" not in events[-1]
    assert events[-1]["error_info"]["code"] == "rate_limit"
    assert events[-1]["error_info"]["retryable"] is True


def test_raw_assembler_derives_total_tokens_when_provider_omits_total() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="test",
        provider="test",
        endpoint="test-endpoint",
        model="test-model",
    )

    assembler.feed({"type": "response_start", "response_id": "resp-1"})
    assembler.feed(
        {
            "type": "usage_delta",
            "input": 10,
            "output": 4,
            "cache_read": 3,
            "cache_write": 2,
        }
    )
    assembler.feed({"type": "response_done"})

    message = asyncio.run(stream.result())

    assert message.usage.input == 10
    assert message.usage.output == 4
    assert message.usage.cache_read == 3
    assert message.usage.cache_write == 2
    assert message.usage.total_tokens == 19
    assert message.usage.cost is None


def test_raw_assembler_leaves_cost_unknown_without_pricing() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="test",
        provider="test",
        endpoint="test-endpoint",
        model="test-model",
    )

    assembler.feed({"type": "usage_delta", "input": 10, "output": 4})
    assembler.feed({"type": "response_done"})

    message = asyncio.run(stream.result())

    assert message.usage.cost is None


def test_raw_assembler_leaves_cost_unknown_for_used_unknown_price_component() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="test",
        provider="test",
        endpoint="test-endpoint",
        model="test-model",
        pricing=Pricing(input=1.0, output=None),
    )

    assembler.feed({"type": "usage_delta", "input": 10, "output": 4})
    assembler.feed({"type": "response_done"})

    message = asyncio.run(stream.result())

    assert message.usage.cost is None


def test_raw_assembler_recomputes_total_tokens_for_incremental_usage_without_total() -> (
    None
):
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="test",
        provider="test",
        endpoint="test-endpoint",
        model="test-model",
    )

    assembler.feed({"type": "response_start", "response_id": "resp-1"})
    assembler.feed(
        {"type": "usage_delta", "input": 10, "output": 1, "total_tokens": 11}
    )
    assembler.feed({"type": "usage_delta", "output": 4})
    assembler.feed({"type": "response_done"})

    message = asyncio.run(stream.result())

    assert message.usage.input == 10
    assert message.usage.output == 4
    assert message.usage.total_tokens == 14


def test_raw_assembler_preserves_provider_total_tokens_when_present() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="test",
        provider="test",
        endpoint="test-endpoint",
        model="test-model",
    )

    assembler.feed({"type": "response_start", "response_id": "resp-1"})
    assembler.feed(
        {"type": "usage_delta", "input": 10, "output": 4, "total_tokens": 42}
    )
    assembler.feed({"type": "response_done"})

    message = asyncio.run(stream.result())

    assert message.usage.total_tokens == 42


def test_raw_assembler_never_reports_total_below_usage_components() -> None:
    stream = AssistantMessageEventStream()
    assembler = RawAssembler(
        stream=stream,
        api="test",
        provider="test",
        endpoint="test-endpoint",
        model="test-model",
    )

    assembler.feed({"type": "response_start", "response_id": "resp-1"})
    assembler.feed(
        {
            "type": "usage_delta",
            "input": 0,
            "output": 7,
            "cache_read": 36,
            "total_tokens": 7,
        }
    )
    assembler.feed({"type": "response_done"})

    message = asyncio.run(stream.result())

    assert message.usage.cache_read == 36
    assert message.usage.output == 7
    assert message.usage.total_tokens == 43
