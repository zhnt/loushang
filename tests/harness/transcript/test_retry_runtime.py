from __future__ import annotations

import asyncio

from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.harness.events import RetryCompleted
from loushang.harness.runtime.retry import RetryPolicy
from loushang.harness.transcript import AgentTranscriptRetryRuntime


def test_retry_runtime_owns_identity_free_retry_lifecycle() -> None:
    async def scenario() -> None:
        messages = [
            _assistant_error("503 service unavailable"),
        ]
        events: list[object] = []
        continued: list[bool] = []
        runtime = AgentTranscriptRetryRuntime(
            get_policy=lambda: RetryPolicy(
                enabled=True,
                max_attempts=2,
                base_delay_ms=0,
            ),
            get_messages=lambda: list(messages),
            set_messages=lambda updated: _replace(messages, updated),
            get_context_window=lambda: 100,
            dispatch_event=lambda event: _append(events, event),
            record_runtime_exception=lambda **kwargs: None,
            sleep_for_retry=lambda delay_ms, signal: _sleep(delay_ms, signal),
            is_context_overflow_fn=lambda message, context_window: False,
        )

        outcome = await runtime.handle_retryable_error(messages[0])
        assert outcome.should_continue is True
        runtime.continue_retry(lambda: _append(continued, True))
        await asyncio.sleep(0)
        assert messages == []
        assert continued == [True]
        await runtime.finish(success=True, attempt=1)
        assert isinstance(events[-1], RetryCompleted)
        assert runtime.is_retrying is False

    asyncio.run(scenario())


def test_retry_runtime_prefers_typed_retryability_over_public_message() -> None:
    retryable = _assistant_error("opaque public error")
    object.__setattr__(
        retryable,
        "error_info",
        {"code": "provider", "retryable": True},
    )
    non_retryable = _assistant_error("503 service unavailable")
    object.__setattr__(
        non_retryable,
        "error_info",
        {"code": "authentication", "retryable": False},
    )
    runtime = AgentTranscriptRetryRuntime(
        get_policy=lambda: RetryPolicy(enabled=True),
        get_messages=list,
        set_messages=lambda messages: None,
        get_context_window=lambda: 100,
        dispatch_event=lambda event: _append([], event),
        record_runtime_exception=lambda **kwargs: None,
        sleep_for_retry=lambda delay_ms, signal: _sleep(delay_ms, signal),
        is_context_overflow_fn=lambda message, context_window: False,
    )

    assert runtime.is_retryable_error(retryable) is True
    assert runtime.is_retryable_error(non_retryable) is False


def _assistant_error(error_message: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="error")],
        api="responses",
        provider="test",
        model="test-model",
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
        error_message=error_message,
        timestamp=0.0,
    )


async def _append(values: list[object], value: object) -> None:
    values.append(value)


def _replace(target: list[object], replacement: list[object]) -> None:
    target[:] = replacement


async def _sleep(delay_ms: int, signal: object) -> None:
    del delay_ms, signal
