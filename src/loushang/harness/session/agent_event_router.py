from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from loushang.agent import AbortSignal, AgentEvent
from loushang.ai.types import AssistantMessage
from loushang.harness.transcript import AutoRetryOutcome, CompactionResult

AppendMessage = Callable[[object], Awaitable[str]]
EventDispatcher = Callable[..., Awaitable[None]]
ExtensionEventEmitter = Callable[[AgentEvent], Awaitable[None]]
ToolExecutionErrorRecorder = Callable[[AgentEvent], None]
ExtensionDiagnosticsSync = Callable[..., None]
AssistantResponseErrorRecorder = Callable[[AssistantMessage], None]
AutoCompactionChecker = Callable[
    [AssistantMessage], Awaitable[CompactionResult | None]
]
QueuedMessageConsumer = Callable[[object], bool]
ContinueRun = Callable[[], Awaitable[None]]


class RetryRouterPort(Protocol):
    async def finish_success_if_needed(
        self, assistant_message: AssistantMessage
    ) -> None: ...

    def should_prepare_retry(self, assistant_message: AssistantMessage) -> bool: ...

    def ensure_future(self) -> object: ...

    def is_retryable_error(self, assistant_message: AssistantMessage) -> bool: ...

    async def handle_retryable_error(
        self, assistant_message: AssistantMessage
    ) -> AutoRetryOutcome: ...

    def continue_retry(self, continue_run: ContinueRun) -> None: ...


class CompactionRouterPort(Protocol):
    def clear_overflow_recovery_attempted(self) -> None: ...


@dataclass
class AgentEventRouter:
    append_message: AppendMessage
    dispatch_event: EventDispatcher
    emit_extension_agent_event: ExtensionEventEmitter
    record_tool_execution_error: ToolExecutionErrorRecorder
    retry_controller: RetryRouterPort
    compaction_controller: CompactionRouterPort
    sync_extension_diagnostics: ExtensionDiagnosticsSync
    record_assistant_response_error: AssistantResponseErrorRecorder
    check_auto_compaction: AutoCompactionChecker
    schedule_continue_run: ContinueRun
    consume_queued_message: QueuedMessageConsumer | None = None
    _committed_messages: dict[int, tuple[object, str]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    async def handle(self, event: AgentEvent, signal: AbortSignal) -> None:
        del signal
        if (
            event["type"] == "message_start"
            and getattr(event["message"], "role", None) in {"user", "application"}
            and self.consume_queued_message is not None
        ):
            self.consume_queued_message(event["message"])
        source_record_id: str | None = None
        committed_message: object | None = None
        if event["type"] == "message_end":
            committed_message = event["message"]
            source_record_id = await self._append_message_once(committed_message)
        if event["type"] == "tool_execution_end" and event.get("is_error"):
            self.record_tool_execution_error(event)
        await self.dispatch_event(event, source_record_id=source_record_id)
        await self.emit_extension_agent_event(event)
        if event["type"] == "message_end" and isinstance(
            event["message"], AssistantMessage
        ):
            assistant_message = event["message"]
            await self.retry_controller.finish_success_if_needed(assistant_message)
            if assistant_message.stop_reason != "error":
                self.compaction_controller.clear_overflow_recovery_attempted()
        if event["type"] == "agent_end":
            self.sync_extension_diagnostics(phase="runtime")
            last_assistant_message = _last_assistant_message(event["messages"])
            if last_assistant_message is None:
                return
            self.record_assistant_response_error(last_assistant_message)
            if self.retry_controller.should_prepare_retry(last_assistant_message):
                self.retry_controller.ensure_future()
            if self.retry_controller.is_retryable_error(last_assistant_message):
                outcome = await self.retry_controller.handle_retryable_error(
                    last_assistant_message
                )
                if outcome.should_continue:
                    self.retry_controller.continue_retry(self.schedule_continue_run)
                    return
            await self.check_auto_compaction(last_assistant_message)
        if committed_message is not None:
            self._forget_committed_message(committed_message)

    async def _append_message_once(self, message: object) -> str:
        identity = id(message)
        existing = self._committed_messages.get(identity)
        if existing is not None and existing[0] is message:
            return existing[1]
        record_id = await self.append_message(message)
        self._committed_messages[identity] = (message, record_id)
        return record_id

    def _forget_committed_message(self, message: object) -> None:
        identity = id(message)
        existing = self._committed_messages.get(identity)
        if existing is not None and existing[0] is message:
            self._committed_messages.pop(identity, None)


def _last_assistant_message(messages: Sequence[object]) -> AssistantMessage | None:
    for message in reversed(messages):
        if isinstance(message, AssistantMessage):
            return message
    return None
