from __future__ import annotations

import asyncio

import pytest

from loushang.agent import Agent
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.ai.utils import is_context_overflow
from loushang.coding.control import RetrySettings
from loushang.harness.events import RetryCompleted, RetryStarted
from loushang.harness.events.session import RetryAttempt, RetryOutcome
from loushang.harness.runtime.retry import RetryPolicy
from loushang.harness.transcript import AgentTranscriptRetryRuntime


def _usage(*, input_tokens: int = 0, total_tokens: int = 0) -> Usage:
    return Usage(
        input=input_tokens,
        output=max(total_tokens - input_tokens, 0),
        cache_read=0,
        cache_write=0,
        total_tokens=total_tokens,
        cost={},
    )


def _model(*, context_window: int = 128000) -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=context_window,
            max_tokens=4096,
        ),
    )


def _assistant_error_message(
    error_message: str, *, usage: Usage | None = None
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="error")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=usage or _usage(),
        stop_reason="error",
        error_message=error_message,
        timestamp=0.0,
    )


def _assistant_success_message() -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="ok")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(total_tokens=8),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _retry_runtime(
    *,
    agent: Agent,
    get_settings,
    dispatch_event,
    record_runtime_exception,
    sleep_for_retry,
) -> AgentTranscriptRetryRuntime:
    return AgentTranscriptRetryRuntime(
        get_policy=lambda: RetryPolicy(
            enabled=get_settings().enabled,
            max_attempts=get_settings().max_retries,
            base_delay_ms=get_settings().base_delay_ms,
        ),
        get_messages=lambda: list(agent.state.messages),
        set_messages=agent.state.set_messages,
        get_context_window=lambda: agent.model.context_window,
        dispatch_event=dispatch_event,
        record_runtime_exception=record_runtime_exception,
        sleep_for_retry=sleep_for_retry,
        is_context_overflow_fn=is_context_overflow,
    )


def test_retry_controller_starts_retry_removes_error_and_continues() -> None:
    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "off"}
    )
    error_message = _assistant_error_message("503 service unavailable")
    agent.state.messages.append(error_message)
    events: list[object] = []
    continued: list[str] = []

    controller = _retry_runtime(
        agent=agent,
        get_settings=lambda: RetrySettings(
            enabled=True, max_retries=2, base_delay_ms=1
        ),
        dispatch_event=lambda event: _append_async(events, event),
        record_runtime_exception=lambda **kwargs: None,
        sleep_for_retry=lambda delay_ms, signal: _noop_async(),
    )

    async def scenario() -> None:
        assert controller.should_prepare_retry(error_message) is True
        outcome = await controller.handle_retryable_error(error_message)
        controller.continue_retry(lambda: _append_async(continued, "continued"))
        await asyncio.sleep(0)
        assert outcome.should_continue is True

    asyncio.run(scenario())

    assert controller.is_retrying is True
    assert controller.attempt == 1
    assert agent.state.messages == []
    assert continued == ["continued"]
    assert events == [
        RetryStarted(
            RetryAttempt(
                attempt=1,
                max_attempts=2,
                delay_ms=1,
                error="503 service unavailable",
            )
        )
    ]


def test_retry_controller_finishes_success_and_resolves_waiter() -> None:
    events: list[object] = []
    controller = _retry_runtime(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        get_settings=lambda: RetrySettings(
            enabled=True, max_retries=2, base_delay_ms=1
        ),
        dispatch_event=lambda event: _append_async(events, event),
        record_runtime_exception=lambda **kwargs: None,
        sleep_for_retry=lambda delay_ms, signal: _noop_async(),
    )

    async def scenario() -> None:
        controller.ensure_future()
        controller.attempt = 1
        await controller.finish(success=True, attempt=1)
        await controller.wait()

    asyncio.run(scenario())

    assert controller.is_retrying is False
    assert controller.attempt == 0
    assert events == [RetryCompleted(RetryOutcome(success=True, attempt=1))]


def test_retry_controller_abort_cancels_pending_retry() -> None:
    agent = Agent(
        initial_state={"system_prompt": "", "model": _model(), "thinking_level": "off"}
    )
    error_message = _assistant_error_message("socket hang up")
    events: list[object] = []
    started = asyncio.Event()

    async def _blocking_sleep(delay_ms, signal):
        del delay_ms
        started.set()
        while not signal.aborted:
            await asyncio.sleep(0)
        raise asyncio.CancelledError

    controller = _retry_runtime(
        agent=agent,
        get_settings=lambda: RetrySettings(
            enabled=True, max_retries=2, base_delay_ms=1
        ),
        dispatch_event=lambda event: _append_async(events, event),
        record_runtime_exception=lambda **kwargs: None,
        sleep_for_retry=_blocking_sleep,
    )

    async def scenario() -> None:
        task = asyncio.create_task(controller.handle_retryable_error(error_message))
        await started.wait()
        controller.abort()
        assert (await task).should_continue is False
        await controller.wait()

    asyncio.run(scenario())

    assert controller.is_retrying is False
    assert events[-1] == RetryCompleted(
        RetryOutcome(
            success=False,
            attempt=1,
            error="Retry cancelled",
            cancelled=True,
        )
    )


def test_retry_controller_does_not_retry_context_overflow() -> None:
    controller = _retry_runtime(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(context_window=32),
                "thinking_level": "off",
            }
        ),
        get_settings=lambda: RetrySettings(
            enabled=True, max_retries=2, base_delay_ms=1
        ),
        dispatch_event=lambda event: _append_async([], event),
        record_runtime_exception=lambda **kwargs: None,
        sleep_for_retry=lambda delay_ms, signal: _noop_async(),
    )
    overflow_message = _assistant_error_message(
        "token limit exceeded",
        usage=_usage(input_tokens=64, total_tokens=64),
    )

    assert controller.should_prepare_retry(overflow_message) is False
    assert controller.is_retryable_error(overflow_message) is False


@pytest.mark.parametrize(
    "message",
    [
        "OpenAI SDK provider requires an API key (Authorization: Bearer or x-api-key)",
        "Error code: 401 - {'error': {'message': 'Unauthorized'}}",
        "Error code: 403 - {'error': {'message': 'Forbidden'}}",
        "Provider returned error 401: Unauthorized",
        "Provider returned error 403: Forbidden",
        (
            "Error code: 403 - {'error': {'message': 'Kimi For Coding is currently only available "
            "for Coding Agents such as Kimi CLI', 'type': 'access_terminated_error'}}"
        ),
    ],
)
def test_retry_controller_treats_auth_and_access_errors_as_non_retryable(
    message: str,
) -> None:
    controller = _retry_runtime(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        get_settings=lambda: RetrySettings(
            enabled=True, max_retries=2, base_delay_ms=1
        ),
        dispatch_event=lambda event: _append_async([], event),
        record_runtime_exception=lambda **kwargs: None,
        sleep_for_retry=lambda delay_ms, signal: _noop_async(),
    )
    error_message = _assistant_error_message(message)

    assert controller.should_prepare_retry(error_message) is False
    assert controller.is_retryable_error(error_message) is False


def test_retry_controller_treats_network_connection_lost_as_retryable() -> None:
    controller = _retry_runtime(
        agent=Agent(
            initial_state={
                "system_prompt": "",
                "model": _model(),
                "thinking_level": "off",
            }
        ),
        get_settings=lambda: RetrySettings(
            enabled=True, max_retries=2, base_delay_ms=1
        ),
        dispatch_event=lambda event: _append_async([], event),
        record_runtime_exception=lambda **kwargs: None,
        sleep_for_retry=lambda delay_ms, signal: _noop_async(),
    )
    error_message = _assistant_error_message("Network connection lost.")

    assert controller.should_prepare_retry(error_message) is True
    assert controller.is_retryable_error(error_message) is True


async def _append_async(values: list[object], value: object) -> None:
    values.append(value)


async def _noop_async(*args, **kwargs) -> None:
    del args, kwargs
