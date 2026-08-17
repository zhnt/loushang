from __future__ import annotations

import asyncio

import pytest

import loushang.ai.provider.runtime as runtime_module
from loushang.ai.context import NormalizedContext
from loushang.ai.errors import AIProviderProtocolError, AITimeoutError
from loushang.ai.model import Auth, Model
from loushang.ai.options import CallOptions, RetryOptions
from loushang.ai.protocols.anthropic_messages import AnthropicMessagesAdapter
from loushang.ai.protocols.openai_chat_completions import OpenAIChatCompletionsAdapter
from loushang.ai.protocols.openai_responses import OpenAIResponsesAdapter
from loushang.ai.provider import ProviderRequest
from loushang.ai.provider.errors import provider_error_part
from loushang.ai.provider.runtime import start_provider_runtime


class _HTTPError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int,
        *,
        headers: dict[str, str] | None = None,
        body: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers = headers or {}
        self.body = body


class _BlockingRawSource:
    def __init__(self) -> None:
        self.next_started = asyncio.Event()
        self.closed = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.next_started.set()
        await asyncio.Future()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed.set()


@pytest.mark.parametrize(
    "provider_cls",
    (OpenAIChatCompletionsAdapter, OpenAIResponsesAdapter, AnthropicMessagesAdapter),
)
def test_builtin_adapters_expose_invoke_raw_contract(provider_cls) -> None:
    provider = provider_cls()

    assert callable(getattr(provider, "invoke_raw", None))
    assert "stream" not in provider_cls.__dict__


def test_provider_runtime_assembles_raw_parts() -> None:
    async def _parts():
        yield {"type": "response_start", "response_id": "resp_1"}
        yield {"type": "text_delta", "text": "hello"}
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=None,
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == [
        "start",
        "text_start",
        "text_delta",
        "text_end",
        "done",
    ]
    assert events[-1]["message"].content[0].text == "hello"


def test_provider_runtime_rejects_source_without_terminal_part() -> None:
    async def _parts():
        yield {"type": "response_start", "response_id": "resp_missing_done"}
        yield {"type": "text_delta", "text": "hello"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=None,
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == [
        "start",
        "text_start",
        "text_delta",
        "error",
    ]
    assert events[-1]["error_info"]["code"] == "provider_protocol"
    assert events[-1]["error_info"]["message"] == (
        "provider stream ended before a terminal response event"
    )


def test_provider_runtime_result_raises_protocol_error_for_unexpected_eof() -> None:
    async def _parts():
        yield {"type": "response_start", "response_id": "resp_missing_done"}

    async def _run():
        stream = start_provider_runtime(_parts, options=None, request=_request())
        with pytest.raises(AIProviderProtocolError) as exc_info:
            await stream.result()
        return exc_info.value

    error = asyncio.run(_run())

    assert str(error) == "provider stream ended before a terminal response event"


@pytest.mark.parametrize("terminal", ["response_done", "response_error", "aborted"])
def test_provider_runtime_stops_after_first_terminal_part(terminal: str) -> None:
    consumed_after_terminal = False

    async def _parts():
        nonlocal consumed_after_terminal
        if terminal == "response_error":
            yield {"type": terminal, "message": "failed"}
        else:
            yield {"type": terminal}
        consumed_after_terminal = True
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(_parts, options=None, request=_request())
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert len(events) == 1
    assert events[0]["type"] == ("done" if terminal == "response_done" else "error")
    assert consumed_after_terminal is False


def test_provider_runtime_converts_adapter_exceptions_to_error_events() -> None:
    async def _parts():
        raise RuntimeError("Authorization: Bearer secret-token")
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=None,
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == ["error"]
    assert events[0]["error"].error_message == "Provider request failed."
    assert events[0]["error_info"]["message"] == "Provider request failed."
    assert events[0]["error_info"]["provider"] == "provider-a"
    assert events[0]["error_info"]["endpoint"] == "openai-responses"
    assert events[0]["error_info"]["model"] == "model-a"
    assert "secret-token" not in repr(events)


def test_provider_runtime_retries_retryable_exception_before_visible_output() -> None:
    attempts = 0
    trace_events: list[dict[str, object]] = []

    async def _parts():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _HTTPError(
                "temporarily unavailable",
                503,
                headers={"x-request-id": "req_503"},
            )
        yield {"type": "response_start", "response_id": "resp_2"}
        yield {"type": "text_delta", "text": "recovered"}
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(
                retry=RetryOptions(max_attempts=2, max_delay_seconds=0),
                trace=trace_events.append,
            ),
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert attempts == 2
    assert [event["type"] for event in events] == [
        "start",
        "text_start",
        "text_delta",
        "text_end",
        "done",
    ]
    assert events[-1]["message"].content[0].text == "recovered"
    assert [event["type"] for event in trace_events] == [
        "runtime:request",
        "runtime:retry",
        "runtime:request",
    ]
    call_id = _assert_runtime_trace_identity(trace_events[0]["data"])
    assert trace_events[0]["data"] == {
        "callId": call_id,
        "api": "openai-responses",
        "provider": "provider-a",
        "endpoint": "openai-responses",
        "model": "model-a",
        "upstreamModel": "model-a",
        "attempt": 1,
        "maxAttempts": 2,
    }
    retry_trace = trace_events[1]
    assert retry_trace["schema"] == "loushang.ai.trace.v1"
    assert retry_trace["source"] == "runtime"
    assert retry_trace["name"] == "retry"
    assert retry_trace["data"] == {
        "callId": call_id,
        "api": "openai-responses",
        "provider": "provider-a",
        "endpoint": "openai-responses",
        "model": "model-a",
        "attempt": 2,
        "maxAttempts": 2,
        "delayMs": 0,
        "reason": "service_unavailable",
        "statusCode": 503,
        "requestId": "req_503",
    }
    assert trace_events[2]["data"]["callId"] == call_id
    assert trace_events[2]["data"]["attempt"] == 2


def test_provider_runtime_retries_response_error_before_visible_output() -> None:
    attempts = 0
    trace_events: list[dict[str, object]] = []

    async def _parts():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            yield provider_error_part(
                _HTTPError(
                    "rate limited",
                    429,
                    headers={"x-request-id": "req_raw_429"},
                ),
                source="openai",
            )
            return
        yield {"type": "response_start", "response_id": "resp_3"}
        yield {"type": "text_delta", "text": "ok"}
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(
                retry=RetryOptions(max_attempts=2, max_delay_seconds=0),
                trace=trace_events.append,
            ),
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert attempts == 2
    assert [event["type"] for event in events] == [
        "start",
        "text_start",
        "text_delta",
        "text_end",
        "done",
    ]
    assert events[-1]["message"].content[0].text == "ok"
    assert [event["type"] for event in trace_events] == [
        "runtime:request",
        "runtime:retry",
        "runtime:request",
    ]
    call_id = _assert_runtime_trace_identity(trace_events[0]["data"])
    assert trace_events[1]["data"] == {
        "callId": call_id,
        "api": "openai-responses",
        "provider": "provider-a",
        "endpoint": "openai-responses",
        "model": "model-a",
        "attempt": 2,
        "maxAttempts": 2,
        "delayMs": 0,
        "reason": "rate_limit",
        "statusCode": 429,
        "requestId": "req_raw_429",
    }


def test_provider_runtime_never_retries_raw_authentication_errors() -> None:
    attempts = 0

    async def _parts():
        nonlocal attempts
        attempts += 1
        yield {
            "type": "response_error",
            "code": 401,
            "message": "Authorization: Bearer secret-token",
            "error_info": {
                "code": "service_unavailable",
                "message": "Authorization: Bearer secret-token",
                "source": "custom-provider",
                "retryable": True,
                "statusCode": 401,
            },
        }

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(
                retry=RetryOptions(max_attempts=2, max_delay_seconds=0),
            ),
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert attempts == 1
    assert events[0]["error_info"]["code"] == "authentication"
    assert events[0]["error_info"]["retryable"] is False
    assert events[0]["error_info"]["message"] == "Provider authentication failed."
    assert "secret-token" not in repr(events)


def test_provider_runtime_emits_error_trace_for_terminal_error() -> None:
    trace_events: list[dict[str, object]] = []

    async def _parts():
        raise _HTTPError(
            "unauthorized",
            401,
            headers={"x-request-id": "req_401"},
            body={
                "error": {
                    "type": "authentication_error",
                    "message": "bad token=secret-token",
                },
                "request": {"prompt": "private prompt"},
            },
        )
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(trace=trace_events.append),
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == ["error"]
    assert [event["type"] for event in trace_events] == [
        "runtime:request",
        "runtime:error",
    ]
    call_id = _assert_runtime_trace_identity(trace_events[0]["data"])
    assert trace_events[1]["data"] == {
        "callId": call_id,
        "api": "openai-responses",
        "provider": "provider-a",
        "endpoint": "openai-responses",
        "model": "model-a",
        "reason": "authentication",
        "retryable": False,
        "statusCode": 401,
        "requestId": "req_401",
        "exceptionType": "_HTTPError",
        "providerResponseSummary": (
            '{"error":{"type":"authentication_error",'
            '"message":"bad token=[REDACTED]"}}'
        ),
    }
    assert "provider_response_summary" not in events[0]
    assert "private prompt" not in repr(trace_events)


def test_provider_runtime_does_not_retry_nonretryable_error_before_output() -> None:
    attempts = 0

    async def _parts():
        nonlocal attempts
        attempts += 1
        raise _HTTPError("unauthorized", 401)
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(
                retry=RetryOptions(max_attempts=2, max_delay_seconds=0)
            ),
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert attempts == 1
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["error_info"]["code"] == "authentication"
    assert events[0]["error_info"]["statusCode"] == 401


def test_provider_runtime_does_not_retry_after_visible_output() -> None:
    attempts = 0

    async def _parts():
        nonlocal attempts
        attempts += 1
        yield {"type": "response_start", "response_id": "resp_4"}
        yield {"type": "text_delta", "text": "partial"}
        raise _HTTPError("rate limited", 429)

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(
                retry=RetryOptions(max_attempts=2, max_delay_seconds=0)
            ),
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert attempts == 1
    assert [event["type"] for event in events] == [
        "start",
        "text_start",
        "text_delta",
        "error",
    ]
    assert events[-1]["error"].content[0].text == "partial"
    assert events[-1]["error_info"]["statusCode"] == 429


def test_provider_runtime_uses_retry_after_delay() -> None:
    attempts = 0
    delays: list[float] = []

    async def _sleep(delay: float) -> None:
        delays.append(delay)

    async def _parts():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _HTTPError(
                "slow down",
                429,
                headers={"Retry-After": "1"},
            )
        yield {"type": "text_delta", "text": "done"}
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(retry=RetryOptions(max_attempts=2)),
            request=_request(),
            _sleep=_sleep,
            _jitter=lambda: 0.0,
        )
        return await stream.result()

    message = asyncio.run(_run())

    assert attempts == 2
    assert delays == [1.0]
    assert message.content[0].text == "done"


def test_provider_runtime_caps_retry_after_by_max_delay() -> None:
    attempts = 0
    delays: list[float] = []

    async def _sleep(delay: float) -> None:
        delays.append(delay)

    async def _parts():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _HTTPError(
                "slow down",
                429,
                headers={"Retry-After": "2"},
            )
        yield {"type": "text_delta", "text": "done"}
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(
                retry=RetryOptions(max_attempts=2, max_delay_seconds=0.5)
            ),
            request=_request(),
            _sleep=_sleep,
            _jitter=lambda: 0.0,
        )
        return await stream.result()

    message = asyncio.run(_run())

    assert attempts == 2
    assert delays == [0.5]
    assert message.content[0].text == "done"


@pytest.mark.parametrize("retry_after", ["NaN", "Infinity"])
def test_provider_runtime_ignores_non_finite_retry_after(retry_after: str) -> None:
    attempts = 0
    delays: list[float] = []

    async def _sleep(delay: float) -> None:
        delays.append(delay)

    async def _parts():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _HTTPError(
                "slow down",
                429,
                headers={"Retry-After": retry_after},
            )
        yield {"type": "text_delta", "text": "done"}
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(
                retry=RetryOptions(max_attempts=2, max_delay_seconds=1)
            ),
            request=_request(),
            _sleep=_sleep,
            _jitter=lambda: 0.0,
        )
        return await stream.result()

    message = asyncio.run(_run())

    assert attempts == 2
    assert delays == [0.25]
    assert message.content[0].text == "done"


def test_provider_runtime_bounds_pre_visible_buffer_by_part_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module, "_PENDING_RETRY_BUFFER_MAX_PARTS", 2)

    async def _parts():
        yield {"type": "response_start", "response_id": "resp_buffer_parts"}
        yield {"type": "usage_delta", "input": 1}
        yield {"type": "usage_delta", "output": 1}
        yield {"type": "text_delta", "text": "unreachable"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=None,
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == ["start", "error"]
    error_info = events[-1]["error_info"]
    assert error_info["code"] == "provider_protocol"
    assert error_info["provider"] == "provider-a"
    assert error_info["endpoint"] == "openai-responses"
    assert error_info["model"] == "model-a"
    assert error_info["details"]["maxParts"] == 2
    assert error_info["details"]["partCount"] == 3


def test_provider_runtime_bounds_pre_visible_buffer_by_estimated_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module, "_PENDING_RETRY_BUFFER_MAX_BYTES", 8)

    async def _parts():
        yield {"type": "response_start", "response_id": "resp_buffer_bytes"}
        yield {"type": "text_delta", "text": "unreachable"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=None,
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == ["error"]
    error_info = events[-1]["error_info"]
    assert error_info["code"] == "provider_protocol"
    assert error_info["details"]["maxBytes"] == 8
    assert error_info["details"]["estimatedBytes"] > 8


def test_provider_runtime_applies_backpressure_to_raw_source() -> None:
    produced = 0

    async def _parts():
        nonlocal produced
        yield {"type": "response_start", "response_id": "resp_backpressure"}
        for index in range(1000):
            produced += 1
            yield {"type": "text_delta", "text": str(index)}
        yield {"type": "response_done"}

    async def _run() -> int:
        stream = start_provider_runtime(
            _parts,
            options=None,
            request=_request(),
        )
        assert stream._queue.maxsize > 0
        await asyncio.sleep(0.05)
        produced_before_consume = produced
        await stream.aclose()
        return produced_before_consume

    produced_before_consume = asyncio.run(_run())

    assert 0 < produced_before_consume < 1000


def test_provider_runtime_cancellation_signal_aborts_and_closes_source() -> None:
    source = _BlockingRawSource()
    trace_events: list[dict[str, object]] = []

    async def _run():
        signal = asyncio.Event()
        stream = start_provider_runtime(
            lambda: source,
            options=CallOptions(cancellation=signal, trace=trace_events.append),
            request=_request(),
        )
        await asyncio.wait_for(source.next_started.wait(), timeout=1)
        signal.set()
        events = [event async for event in stream]
        await asyncio.wait_for(source.closed.wait(), timeout=1)
        return events

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == ["error"]
    assert events[0]["reason"] == "aborted"
    assert events[0]["error"].stop_reason == "aborted"
    assert [event["type"] for event in trace_events] == [
        "runtime:request",
        "runtime:cancel",
    ]
    call_id = _assert_runtime_trace_identity(trace_events[0]["data"])
    assert trace_events[1]["data"] == {
        "callId": call_id,
        "api": "openai-responses",
        "provider": "provider-a",
        "endpoint": "openai-responses",
        "model": "model-a",
        "reason": "cancelled",
    }


def test_provider_runtime_consumer_close_closes_source_without_leaking_task() -> None:
    source = _BlockingRawSource()

    async def _run() -> bool:
        stream = start_provider_runtime(
            lambda: source,
            options=None,
            request=_request(),
        )
        await asyncio.wait_for(source.next_started.wait(), timeout=1)
        await stream.aclose()
        assert source.closed.is_set()
        task = stream._producer_task
        if task is not None:
            with pytest.raises(asyncio.CancelledError):
                await task
        return task is not None and task.cancelled()

    assert asyncio.run(_run()) is True


def test_provider_runtime_total_deadline_times_out_and_closes_source() -> None:
    source = _BlockingRawSource()

    async def _run():
        stream = start_provider_runtime(
            lambda: source,
            options=CallOptions(timeout_seconds=0.02),
            request=_request(),
        )
        events = [event async for event in stream]
        await asyncio.wait_for(source.closed.wait(), timeout=1)
        return events

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == ["error"]
    assert events[0]["error_info"]["code"] == "timeout"


def test_provider_runtime_idle_timeout_applies_between_raw_parts() -> None:
    closed = asyncio.Event()

    async def _parts():
        try:
            yield {"type": "response_start", "response_id": "resp_idle"}
            await asyncio.sleep(10)
            yield {"type": "response_done"}
        finally:
            closed.set()

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(idle_timeout_seconds=0.02),
            request=_request(),
        )
        events = [event async for event in stream]
        await asyncio.wait_for(closed.wait(), timeout=1)
        return events

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == ["start", "error"]
    assert events[-1]["error_info"]["code"] == "timeout"


def test_provider_runtime_idle_timeout_does_not_apply_before_first_raw_part() -> None:
    async def _parts():
        await asyncio.sleep(0.02)
        yield {"type": "response_start", "response_id": "resp_first"}
        yield {"type": "response_done"}

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(
                timeout_seconds=0.2,
                idle_timeout_seconds=0.005,
            ),
            request=_request(),
        )
        return [event async for event in stream]

    events = asyncio.run(_run())

    assert [event["type"] for event in events] == ["start", "done"]


def test_provider_runtime_total_deadline_wins_while_tokens_keep_arriving() -> None:
    closed = asyncio.Event()

    async def _parts():
        try:
            yield {"type": "response_start", "response_id": "resp_total"}
            while True:
                await asyncio.sleep(0.005)
                yield {"type": "text_delta", "text": "."}
        finally:
            closed.set()

    async def _run():
        stream = start_provider_runtime(
            _parts,
            options=CallOptions(
                timeout_seconds=0.04,
                idle_timeout_seconds=0.02,
            ),
            request=_request(),
        )
        events = [event async for event in stream]
        await asyncio.wait_for(closed.wait(), timeout=1)
        return events

    events = asyncio.run(_run())

    assert any(event["type"] == "text_delta" for event in events)
    assert events[-1]["type"] == "error"
    assert events[-1]["error_info"]["code"] == "timeout"


def test_provider_runtime_complete_mode_timeout_raises_typed_error() -> None:
    source = _BlockingRawSource()

    async def _run() -> AITimeoutError:
        stream = start_provider_runtime(
            lambda: source,
            options=CallOptions(timeout_seconds=0.02),
            request=_request(mode="complete"),
        )
        with pytest.raises(AITimeoutError) as exc_info:
            await stream.result()
        await asyncio.wait_for(source.closed.wait(), timeout=1)
        return exc_info.value

    error = asyncio.run(_run())

    assert error.info.code.value == "timeout"
    assert error.info.provider == "provider-a"


def _model() -> Model:
    return Model(
        id="model-a",
        provider="provider-a",
        endpoint="openai-responses",
        api="openai-responses",
        base_url="https://provider.test/v1",
        auth=Auth(kind="none"),
    )


def _request(*, mode: str = "stream") -> ProviderRequest:
    return ProviderRequest(
        model=_model(),
        context=NormalizedContext(system_prompt=None),
        options=None,
        base_url="https://provider.test/v1",
        mode=mode,  # type: ignore[arg-type]
    )


def _assert_runtime_trace_identity(
    data: object,
    call_id: object | None = None,
) -> str:
    assert isinstance(data, dict)
    if call_id is None:
        call_id = data["callId"]
    assert isinstance(call_id, str)
    assert call_id
    assert data["callId"] == call_id
    assert data["api"] == "openai-responses"
    assert data["provider"] == "provider-a"
    assert data["endpoint"] == "openai-responses"
    assert data["model"] == "model-a"
    return call_id
