from __future__ import annotations

import asyncio

from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.harness.session import AgentEventRouter
from loushang.harness.transcript import ApplicationMessage, AutoRetryOutcome


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost={},
    )


def _assistant_message(
    *, stop_reason: str = "stop", error_message: str | None = None
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text="reply")],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(),
        stop_reason=stop_reason,
        error_message=error_message,
        timestamp=0.0,
    )


class _RetryRecorder:
    def __init__(
        self, order: list[str], *, retryable: bool = False, did_retry: bool = False
    ) -> None:
        self.order = order
        self.retryable = retryable
        self.did_retry = did_retry

    async def finish_success_if_needed(
        self, assistant_message: AssistantMessage
    ) -> None:
        del assistant_message
        self.order.append("retry_finish_success")

    def should_prepare_retry(self, assistant_message: AssistantMessage) -> bool:
        del assistant_message
        self.order.append("retry_should_prepare")
        return self.retryable

    def ensure_future(self) -> None:
        self.order.append("retry_ensure_future")

    def is_retryable_error(self, assistant_message: AssistantMessage) -> bool:
        del assistant_message
        self.order.append("retry_is_retryable")
        return self.retryable

    async def handle_retryable_error(
        self, assistant_message: AssistantMessage
    ) -> AutoRetryOutcome:
        del assistant_message
        self.order.append("retry_handle")
        return AutoRetryOutcome(should_continue=self.did_retry)

    def continue_retry(self, continue_run: object) -> None:
        assert callable(continue_run)
        self.order.append("retry_continue")


class _CompactionRecorder:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def clear_overflow_recovery_attempted(self) -> None:
        self.order.append("compaction_clear_overflow")


def test_agent_event_router_preserves_assistant_message_end_ordering() -> None:
    order: list[str] = []
    assistant = _assistant_message()

    async def scenario() -> None:
        async def append_message(message: object) -> str:
            order.append(f"append:{message.role}")
            return "record-1"

        async def dispatch_event(event: object, **kwargs: object) -> None:
            assert kwargs["source_record_id"] == "record-1"
            await _record_async(order, f"dispatch:{event['type']}")

        router = AgentEventRouter(
            append_message=append_message,
            dispatch_event=dispatch_event,
            emit_extension_agent_event=lambda event: _record_async(
                order, f"extension:{event['type']}"
            ),
            record_tool_execution_error=lambda event: order.append(
                f"tool_error:{event['type']}"
            ),
            retry_controller=_RetryRecorder(order),
            compaction_controller=_CompactionRecorder(order),
            sync_extension_diagnostics=lambda **kwargs: order.append(
                f"sync:{kwargs['phase']}"
            ),
            record_assistant_response_error=lambda message: order.append(
                f"assistant_error:{message.role}"
            ),
            check_auto_compaction=lambda message: _record_async(
                order, f"auto_compact:{message.role}"
            ),
            schedule_continue_run=lambda: _record_async(order, "continue"),
        )

        await router.handle({"type": "message_end", "message": assistant}, object())
        assert router._committed_messages == {}

    asyncio.run(scenario())

    assert order == [
        "append:assistant",
        "dispatch:message_end",
        "extension:message_end",
        "retry_finish_success",
        "compaction_clear_overflow",
    ]


def test_agent_event_router_consumes_queued_application_message_on_start() -> None:
    consumed: list[object] = []
    message = ApplicationMessage(
        application_message_id="completion-1",
        custom_type="multiagent.completion",
        content="/root/reviewer completed (round 1).",
        timestamp=0.0,
        display=False,
        delivery_mode="steering",
    )

    async def scenario() -> None:
        router = AgentEventRouter(
            append_message=lambda value: _append_async([], value),
            dispatch_event=lambda event, **kwargs: _record_async([], "dispatch"),
            emit_extension_agent_event=lambda event: _record_async([], "extension"),
            record_tool_execution_error=lambda event: None,
            retry_controller=_RetryRecorder([]),
            compaction_controller=_CompactionRecorder([]),
            sync_extension_diagnostics=lambda **kwargs: None,
            record_assistant_response_error=lambda value: None,
            check_auto_compaction=lambda value: _record_async([], "compact"),
            schedule_continue_run=lambda: _record_async([], "continue"),
            consume_queued_message=lambda value: consumed.append(value) or True,
        )

        await router.handle(
            {"type": "message_start", "message": message},
            object(),
        )

    asyncio.run(scenario())

    assert consumed == [message]


def test_agent_event_router_does_not_dispatch_after_append_failure() -> None:
    order: list[str] = []

    async def scenario() -> None:
        async def fail_append(message: object) -> str:
            del message
            order.append("append")
            raise OSError("store unavailable")

        router = AgentEventRouter(
            append_message=fail_append,
            dispatch_event=lambda event, **kwargs: _record_async(order, "dispatch"),
            emit_extension_agent_event=lambda event: _record_async(order, "extension"),
            record_tool_execution_error=lambda event: None,
            retry_controller=_RetryRecorder(order),
            compaction_controller=_CompactionRecorder(order),
            sync_extension_diagnostics=lambda **kwargs: None,
            record_assistant_response_error=lambda message: None,
            check_auto_compaction=lambda message: _record_async(order, "compact"),
            schedule_continue_run=lambda: _record_async(order, "continue"),
        )

        try:
            await router.handle(
                {"type": "message_end", "message": _assistant_message()}, object()
            )
        except OSError as exc:
            assert str(exc) == "store unavailable"
        else:
            raise AssertionError("append failure must propagate")

    asyncio.run(scenario())

    assert order == ["append"]


def test_agent_event_router_retries_projection_without_appending_again() -> None:
    order: list[str] = []
    assistant = _assistant_message()

    async def scenario() -> None:
        attempts = 0

        async def append_message(message: object) -> str:
            order.append(f"append:{message.role}")
            return "record-1"

        async def dispatch_event(event: object, **kwargs: object) -> None:
            nonlocal attempts
            attempts += 1
            order.append(f"dispatch:{attempts}")
            if attempts == 1:
                raise RuntimeError("projection failed")

        router = AgentEventRouter(
            append_message=append_message,
            dispatch_event=dispatch_event,
            emit_extension_agent_event=lambda event: _record_async(
                order, f"extension:{event['type']}"
            ),
            record_tool_execution_error=lambda event: None,
            retry_controller=_RetryRecorder(order),
            compaction_controller=_CompactionRecorder(order),
            sync_extension_diagnostics=lambda **kwargs: None,
            record_assistant_response_error=lambda message: None,
            check_auto_compaction=lambda message: _record_async(order, "compact"),
            schedule_continue_run=lambda: _record_async(order, "continue"),
        )
        event = {"type": "message_end", "message": assistant}

        try:
            await router.handle(event, object())
        except RuntimeError as exc:
            assert str(exc) == "projection failed"
        else:
            raise AssertionError("projection failure must propagate")
        await router.handle(event, object())
        assert router._committed_messages == {}

    asyncio.run(scenario())

    assert order.count("append:assistant") == 1
    assert order[:3] == ["append:assistant", "dispatch:1", "dispatch:2"]


def test_agent_event_router_records_tool_errors_before_dispatch_and_extension_mirror() -> (
    None
):
    order: list[str] = []

    async def scenario() -> None:
        async def dispatch_event(event: object, **kwargs: object) -> None:
            assert kwargs["source_record_id"] is None
            await _record_async(order, f"dispatch:{event['type']}")

        router = AgentEventRouter(
            append_message=lambda message: _append_async(order, message),
            dispatch_event=dispatch_event,
            emit_extension_agent_event=lambda event: _record_async(
                order, f"extension:{event['type']}"
            ),
            record_tool_execution_error=lambda event: order.append(
                f"tool_error:{event['type']}"
            ),
            retry_controller=_RetryRecorder(order),
            compaction_controller=_CompactionRecorder(order),
            sync_extension_diagnostics=lambda **kwargs: order.append(
                f"sync:{kwargs['phase']}"
            ),
            record_assistant_response_error=lambda message: order.append(
                f"assistant_error:{message.role}"
            ),
            check_auto_compaction=lambda message: _record_async(
                order, f"auto_compact:{message.role}"
            ),
            schedule_continue_run=lambda: _record_async(order, "continue"),
        )

        await router.handle({"type": "tool_execution_end", "is_error": True}, object())

    asyncio.run(scenario())

    assert order == [
        "tool_error:tool_execution_end",
        "dispatch:tool_execution_end",
        "extension:tool_execution_end",
    ]


def test_agent_event_router_retries_before_auto_compaction_and_short_circuits() -> None:
    order: list[str] = []
    assistant = _assistant_message(
        stop_reason="error", error_message="503 service unavailable"
    )

    async def scenario() -> None:
        async def dispatch_event(event: object, **kwargs: object) -> None:
            assert kwargs["source_record_id"] is None
            await _record_async(order, f"dispatch:{event['type']}")

        router = AgentEventRouter(
            append_message=lambda message: _append_async(order, message),
            dispatch_event=dispatch_event,
            emit_extension_agent_event=lambda event: _record_async(
                order, f"extension:{event['type']}"
            ),
            record_tool_execution_error=lambda event: order.append(
                f"tool_error:{event['type']}"
            ),
            retry_controller=_RetryRecorder(order, retryable=True, did_retry=True),
            compaction_controller=_CompactionRecorder(order),
            sync_extension_diagnostics=lambda **kwargs: order.append(
                f"sync:{kwargs['phase']}"
            ),
            record_assistant_response_error=lambda message: order.append(
                f"assistant_error:{message.role}"
            ),
            check_auto_compaction=lambda message: _record_async(
                order, f"auto_compact:{message.role}"
            ),
            schedule_continue_run=lambda: _record_async(order, "continue"),
        )

        await router.handle({"type": "agent_end", "messages": [assistant]}, object())

    asyncio.run(scenario())

    assert order == [
        "dispatch:agent_end",
        "extension:agent_end",
        "sync:runtime",
        "assistant_error:assistant",
        "retry_should_prepare",
        "retry_ensure_future",
        "retry_is_retryable",
        "retry_handle",
        "retry_continue",
    ]


async def _record_async(order: list[str], value: str) -> None:
    order.append(value)


async def _append_async(order: list[str], message: object) -> str:
    order.append(f"append:{getattr(message, 'role', 'unknown')}")
    return "record-1"
