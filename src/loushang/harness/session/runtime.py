"""One optional Agent/AI session runtime composed from Harness primitives.

Products provide input, transcript, and after-turn policy through narrow ports.
This module owns only the ordering and lifetime of one running Agent session.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from loushang.agent import AbortSignal
from loushang.agent.types import AgentEvent, AgentMessage
from loushang.ai.types import AssistantMessage, ImagePart
from loushang.harness.events import (
    OrderedEventBus,
    QueueChanged,
    RuntimeEvent,
    RuntimeEventPublisher,
    SessionRuntimeEventPayload,
    ToolPolicyAuditEvent,
    ToolPolicyAuditEventType,
    TranscriptRecordCommitted,
    session_runtime_event_kind,
)
from loushang.harness.runtime.execution import HostRuntime
from loushang.harness.session.agent_event_router import (
    AgentEventRouter,
    CompactionRouterPort,
    ExtensionDiagnosticsSync,
    ExtensionEventEmitter,
    RetryRouterPort,
)
from loushang.harness.session.application_input import ApplicationInputRuntime
from loushang.harness.session.prompt_controller import AgentPort, PromptController
from loushang.harness.session.queue_controller import AgentQueuePort, QueueController
from loushang.harness.transcript import (
    ApplicationMessage,
    AutoCompactionOutcome,
    CommitResult,
    CompactionResult,
)

AppendMessage = Callable[[object], Awaitable[str]]
CommitApplicationMessage = Callable[[ApplicationMessage], Awaitable[CommitResult]]
RefreshTranscriptContext = Callable[[], None]
SetCommitObserver = Callable[[Callable[[CommitResult], None] | None], None]
CommandExtractor = Callable[[str], tuple[str, str] | None]
CommandExecutor = Callable[[str, str], Awaitable[object | None]]
PreflightUserInput = Callable[..., Awaitable[object]]
SynchronousPreflightUserInput = Callable[[str], object]
RejectQueuedExtensionCommand = Callable[[str], None]
BeforeAgentStartOptions = Callable[[], dict[str, object]]
PrePromptCompaction = Callable[[], Awaitable[AutoCompactionOutcome]]
ToolExecutionErrorRecorder = Callable[[AgentEvent], None]
AssistantResponseErrorRecorder = Callable[[AssistantMessage], None]
AutoCompactionChecker = Callable[
    [AssistantMessage], Awaitable[AutoCompactionOutcome]
]
RuntimeEventListener = Callable[[RuntimeEvent[object]], Awaitable[None] | None]
AgentEventListener = Callable[[AgentEvent, AbortSignal], Awaitable[None] | None]


class SessionAgentPort(Protocol):
    """Agent-loop capabilities required by the shared session runtime."""

    @property
    def is_streaming(self) -> bool: ...

    def subscribe(self, listener: AgentEventListener) -> Callable[[], None]: ...

    def abort(self) -> None: ...

    async def wait_for_idle(self) -> None: ...

    async def prompt(
        self,
        input: str | AgentMessage | list[AgentMessage],
        images: list[ImagePart] | None = None,
    ) -> None: ...

    async def continue_run(
        self,
        *,
        model_call_purpose: str = "continuation",
    ) -> None: ...


@dataclass(frozen=True)
class TranscriptRuntimePort:
    """Durable transcript operations sealed for one session lifetime."""

    session_id: str
    append_message: AppendMessage
    commit_application_message: CommitApplicationMessage
    refresh_context: RefreshTranscriptContext
    set_commit_observer: SetCommitObserver


@dataclass(frozen=True)
class TurnPolicyPort:
    """Product input and before-start decisions for one Agent turn."""

    get_extension_runner: Callable[[], object | None]
    get_cwd: Callable[[], str]
    extract_extension_command_invocation: CommandExtractor
    execute_command_async: CommandExecutor
    preflight_user_input: SynchronousPreflightUserInput
    reject_queued_extension_command: RejectQueuedExtensionCommand
    preflight_user_input_async: PreflightUserInput
    before_agent_start_system_prompt_options: BeforeAgentStartOptions
    sync_extension_diagnostics: ExtensionDiagnosticsSync
    compact_before_prompt_async: PrePromptCompaction | None = None


@dataclass(frozen=True)
class AfterTurnPolicyPort:
    """Product effects invoked after common Agent-event ordering is complete."""

    emit_extension_agent_event: ExtensionEventEmitter
    record_tool_execution_error: ToolExecutionErrorRecorder
    retry_controller: RetryRouterPort
    compaction_controller: CompactionRouterPort
    sync_extension_diagnostics: ExtensionDiagnosticsSync
    record_assistant_response_error: AssistantResponseErrorRecorder
    check_auto_compaction: AutoCompactionChecker


@dataclass
class SessionRuntime:
    """Compose one Agent session's shared lifecycle, input, and event ordering.

    This is an optional Agent/AI Harness profile.  It does not choose Product
    commands, prompt content, retry classification, compaction semantics, or
    transcript storage.  Those choices are supplied through the ports above.
    """

    agent: SessionAgentPort
    transcript: TranscriptRuntimePort
    turn_policy: TurnPolicyPort
    after_turn_policy: AfterTurnPolicyPort

    def __post_init__(self) -> None:
        self._closed = False
        self._event_bus: OrderedEventBus[RuntimeEvent[object]] = OrderedEventBus(
            async_listener_error=(
                "Async runtime event listeners require a running event loop."
            )
        )
        self._event_publisher = RuntimeEventPublisher[object](
            stream_id=f"session:{self.transcript.session_id}",
            bus=self._event_bus,
        )
        self._host_runtime: HostRuntime[None] = HostRuntime(
            abort_driver=self.agent.abort,
            wait_for_idle_driver=self.agent.wait_for_idle,
            is_running_driver=lambda: self.agent.is_streaming,
        )
        self._queue_controller = QueueController(
            agent=cast(AgentQueuePort, self.agent),
            preflight_user_input=self.turn_policy.preflight_user_input,
            reject_extension_command=self.turn_policy.reject_queued_extension_command,
            emit_queue_update=self._emit_queue_update,
        )
        self._prompt_controller = PromptController(
            agent=cast(AgentPort, self.agent),
            queue_controller=self._queue_controller,
            get_extension_runner=self.turn_policy.get_extension_runner,
            get_cwd=self.turn_policy.get_cwd,
            extract_extension_command_invocation=(
                self.turn_policy.extract_extension_command_invocation
            ),
            execute_command_async=self.turn_policy.execute_command_async,
            preflight_user_input_async=self.turn_policy.preflight_user_input_async,
            before_agent_start_system_prompt_options=(
                self.turn_policy.before_agent_start_system_prompt_options
            ),
            sync_extension_diagnostics=self.turn_policy.sync_extension_diagnostics,
            compact_before_prompt_async=(
                self._compact_before_prompt
                if self.turn_policy.compact_before_prompt_async is not None
                else None
            ),
            run_prompt=self.run_agent_prompt,
        )
        self._application_inputs = ApplicationInputRuntime(
            commit_application_message=self.transcript.commit_application_message,
            queue=self._queue_controller,
            project_direct=self._project_direct_application_message,
            run_trigger_turn=lambda message: self.run_agent_prompt(message),
        )
        self._agent_event_router = AgentEventRouter(
            append_message=self.transcript.append_message,
            dispatch_event=self.dispatch_event,
            emit_extension_agent_event=self.after_turn_policy.emit_extension_agent_event,
            record_tool_execution_error=(
                self.after_turn_policy.record_tool_execution_error
            ),
            retry_controller=self.after_turn_policy.retry_controller,
            compaction_controller=self.after_turn_policy.compaction_controller,
            sync_extension_diagnostics=self.after_turn_policy.sync_extension_diagnostics,
            record_assistant_response_error=(
                self.after_turn_policy.record_assistant_response_error
            ),
            check_auto_compaction=self.check_auto_compaction,
            schedule_continue_run=lambda: self.schedule_continue_run(
                model_call_purpose="retry"
            ),
            consume_queued_message=self._queue_controller.mark_message_consumed,
        )
        self.transcript.set_commit_observer(self._schedule_transcript_commit)
        self._unsubscribe_agent = self.agent.subscribe(self.handle_agent_event)

    @property
    def is_active(self) -> bool:
        return self._host_runtime.is_active

    @property
    def queue(self) -> QueueController:
        return self._queue_controller

    @property
    def host_runtime(self) -> HostRuntime[None]:
        return self._host_runtime

    @property
    def prompt_controller(self) -> PromptController:
        return self._prompt_controller

    @property
    def agent_event_router(self) -> AgentEventRouter:
        return self._agent_event_router

    @property
    def application_inputs(self) -> ApplicationInputRuntime:
        return self._application_inputs

    def subscribe(self, listener: RuntimeEventListener) -> Callable[[], None]:
        return self._event_bus.subscribe(listener)

    async def prompt(
        self,
        user_input: str,
        images: list[ImagePart] | None = None,
        *,
        streaming_behavior: str | None = None,
        source: str | None = None,
        preflight_result: Callable[[bool], None] | None = None,
    ) -> None:
        await self._prompt_controller.prompt(
            user_input,
            images=images,
            streaming_behavior=streaming_behavior,
            source=source,
            preflight_result=preflight_result,
        )

    def steer(self, user_input: str, images: list[ImagePart] | None = None) -> None:
        self._queue_controller.steer(user_input, images=images)

    def follow_up(
        self, user_input: str, images: list[ImagePart] | None = None
    ) -> None:
        self._queue_controller.follow_up(user_input, images=images)

    async def continue_run(self) -> None:
        await self._host_runtime.run_after_idle(self.agent.continue_run)

    def schedule_continue_run(
        self,
        *,
        model_call_purpose: str = "continuation",
    ) -> asyncio.Task[None]:
        return self._host_runtime.defer_run(
            lambda: self.agent.continue_run(
                model_call_purpose=model_call_purpose
            ),
            key="agent-continue",
        )

    async def check_auto_compaction(
        self,
        assistant_message: AssistantMessage,
    ) -> CompactionResult | None:
        outcome = await self.after_turn_policy.check_auto_compaction(
            assistant_message
        )
        return self._accept_auto_compaction_outcome(outcome)

    async def _compact_before_prompt(self) -> CompactionResult | None:
        compact = self.turn_policy.compact_before_prompt_async
        if compact is None:
            return None
        return self._accept_auto_compaction_outcome(await compact())

    def _accept_auto_compaction_outcome(
        self,
        outcome: AutoCompactionOutcome,
    ) -> CompactionResult | None:
        if outcome.should_continue:
            self.schedule_continue_run()
        return outcome.result

    def abort(self) -> bool:
        return self._host_runtime.abort()

    async def wait_for_idle(self) -> None:
        await self._host_runtime.wait_for_idle()

    async def run_agent_prompt(
        self,
        prompt: object,
        images: list[ImagePart] | None = None,
    ) -> None:
        normalized_prompt = cast(str | AgentMessage | list[AgentMessage], prompt)

        async def operation() -> None:
            if images is None:
                await self.agent.prompt(normalized_prompt)
            else:
                await self.agent.prompt(normalized_prompt, images=images)

        await self._host_runtime.run(operation)

    async def handle_agent_event(
        self, event: AgentEvent, signal: AbortSignal
    ) -> None:
        await self._agent_event_router.handle(event, signal)

    async def dispatch_event(
        self,
        event: AgentEvent | SessionRuntimeEventPayload | Mapping[str, object],
        *,
        source_record_id: str | None = None,
    ) -> None:
        kind, payload = _normalize_runtime_event(event)
        await self._event_publisher.publish(
            kind,
            payload,
            session_id=self.transcript.session_id,
            source_record_id=source_record_id,
        )

    def schedule_event_dispatch(
        self, event: SessionRuntimeEventPayload
    ) -> asyncio.Task[None]:
        return self._event_publisher.schedule(
            session_runtime_event_kind(event),
            event,
            session_id=self.transcript.session_id,
        )

    def dispatch_event_without_loop(self, event: SessionRuntimeEventPayload) -> None:
        self._event_publisher.publish_without_loop(
            session_runtime_event_kind(event),
            event,
            session_id=self.transcript.session_id,
        )

    async def dispose(self) -> None:
        try:
            await self._host_runtime.dispose()
        finally:
            self.close()

    def close(self) -> None:
        """Detach sealed session bindings after the Product has shut down."""

        if self._closed:
            return
        self._closed = True
        self._unsubscribe_agent()
        self.transcript.set_commit_observer(None)
        self._event_bus.clear()

    async def _project_direct_application_message(
        self,
        message: ApplicationMessage,
        record_id: str,
    ) -> None:
        self.transcript.refresh_context()
        await self.dispatch_event({"type": "message_start", "message": message})
        await self.dispatch_event(
            {"type": "message_end", "message": message},
            source_record_id=record_id,
        )

    def _emit_queue_update(self) -> None:
        event = QueueChanged(snapshot=self._queue_controller.get_queue_snapshot())
        try:
            self.schedule_event_dispatch(event)
        except RuntimeError:
            self.dispatch_event_without_loop(event)

    def _schedule_transcript_commit(self, result: CommitResult) -> None:
        receipt = result.receipt
        if result.disposition != "committed" or receipt is None:
            return
        self._event_publisher.schedule(
            "transcript.record_committed",
            TranscriptRecordCommitted(
                conversation_id=self.transcript.session_id,
                record_id=result.record_id,
                revision=receipt.revision,
                committed_at=receipt.committed_at,
            ),
            session_id=self.transcript.session_id,
            source_record_id=result.record_id,
        )


def _normalize_runtime_event(
    event: AgentEvent | SessionRuntimeEventPayload | Mapping[str, object],
) -> tuple[str, object]:
    if isinstance(event, Mapping):
        event_type = event.get("type")
        if isinstance(event_type, str) and event_type in _AGENT_EVENT_TYPES:
            return f"agent.{event_type}", event
        if isinstance(event_type, str) and event_type in _TOOL_POLICY_AUDIT_EVENT_TYPES:
            payload = ToolPolicyAuditEvent(
                event_type=cast(ToolPolicyAuditEventType, event_type),
                details={key: value for key, value in event.items() if key != "type"},
            )
            return session_runtime_event_kind(payload), payload
        raise TypeError("Runtime event mapping has an unsupported type")
    return session_runtime_event_kind(event), event


_AGENT_EVENT_TYPES = {
    "agent_start",
    "agent_end",
    "turn_start",
    "turn_end",
    "message_start",
    "message_update",
    "message_end",
    "tool_execution_start",
    "tool_execution_update",
    "tool_execution_end",
}
_TOOL_POLICY_AUDIT_EVENT_TYPES = {
    "tool_action_frozen",
    "tool_policy_evaluated",
    "tool_approval_requested",
    "tool_approval_resolved",
    "tool_execution_started",
    "tool_execution_completed",
    "tool_execution_failed",
}


__all__ = [
    "AfterTurnPolicyPort",
    "SessionRuntime",
    "SessionAgentPort",
    "TranscriptRuntimePort",
    "TurnPolicyPort",
]
