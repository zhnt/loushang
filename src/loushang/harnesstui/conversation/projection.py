from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Protocol, TypeVar

from loushang.harness.events.recording_policy import is_cancelled_error_message
from loushang.harnesstui.conversation.history import structural_message_text
from loushang.harnesstui.conversation.runtime_view import StringQueueReader
from loushang.harnesstui.conversation.tool_transcript import (
    ToolCallSnapshot,
    ToolCallView,
    ToolResultView,
    ToolTranscriptBlock,
    ToolTranscriptProjectionBinding,
    ToolTranscriptProjector,
)

ErrorId = int | str
ToolFinishCleanup = Literal["before_projection", "after_target"]
ProjectionEventT = TypeVar("ProjectionEventT")
CancellationErrorPredicate = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class ToolFinishContext:
    """Snapshot the state needed to finish one tool without mutating it yet."""

    tool_call_id: str
    snapshot: ToolCallSnapshot | None
    started_at: float


class ConversationProjectionTarget(Protocol):
    """Receive product-neutral conversation facts for one UI surface."""

    def run_started(self, *, start_time: Callable[[], float]) -> None: ...

    def queues_updated(
        self,
        *,
        steers: tuple[str, ...],
        followups: tuple[str, ...],
    ) -> None: ...

    def user_message(self, text: str) -> None: ...

    def assistant_started(self) -> None: ...

    def assistant_delta(self, delta: str) -> None: ...

    def assistant_finished(
        self,
        final_text: str,
        *,
        error_message: str | None,
        show_error: bool,
    ) -> None: ...

    def assistant_error(self, error_message: str) -> None: ...

    def tool_started(
        self,
        tool_call_id: str,
        snapshot: ToolCallSnapshot,
    ) -> None: ...

    def tool_finished(
        self,
        block: ToolTranscriptBlock,
        *,
        elapsed_seconds: float,
    ) -> None: ...

    def tool_result_message(self, block: ToolTranscriptBlock) -> None: ...

    def retry_started(
        self,
        *,
        attempt: int | None,
        max_attempts: int | None,
        delay_ms: int | float | None,
        error_message: str | None,
    ) -> None: ...

    def compaction_started(self, *, reason: str | None) -> None: ...

    def compaction_finished(
        self,
        *,
        error_message: str | None,
        summary: str,
        tokens_before: int | None,
    ) -> None: ...


@dataclass(slots=True)
class ConversationProjector:
    """Coordinate reusable conversation projection state for a UI target."""

    target: ConversationProjectionTarget
    tool_projector: ToolTranscriptProjector = field(
        default_factory=ToolTranscriptProjector
    )
    now: Callable[[], float] = time.monotonic
    track_rendered_tool_results: bool = True
    measure_tool_elapsed: bool = True
    tool_finish_cleanup: ToolFinishCleanup = "after_target"
    tool_calls: dict[str, ToolCallSnapshot] = field(
        default_factory=dict,
        repr=False,
    )
    rendered_tool_results: set[str] = field(default_factory=set, repr=False)
    rendered_assistant_errors: set[ErrorId] = field(
        default_factory=set,
        repr=False,
    )
    last_error_message: str | None = None
    _tool_started_at: dict[str, float] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def run_started(self) -> None:
        self.tool_calls.clear()
        self._tool_started_at.clear()
        self.target.run_started(start_time=self.now)

    def queues_updated(
        self,
        *,
        steers: tuple[str, ...],
        followups: tuple[str, ...],
    ) -> None:
        self.target.queues_updated(steers=steers, followups=followups)

    def user_message(self, text: str) -> None:
        self.target.user_message(text)

    def assistant_started(self) -> None:
        self.target.assistant_started()

    def assistant_delta(self, delta: str) -> None:
        self.target.assistant_delta(delta)

    def assistant_finished(
        self,
        final_text: str,
        *,
        error_message: str | None = None,
        show_error: bool = False,
        error_id: ErrorId | None = None,
    ) -> None:
        show_error = self._remember_assistant_error(
            error_message,
            show_error=show_error,
            error_id=error_id,
        )
        self.target.assistant_finished(
            final_text,
            error_message=error_message,
            show_error=show_error,
        )

    def assistant_error(
        self,
        error_message: str,
        *,
        show_error: bool,
        error_id: ErrorId | None = None,
    ) -> None:
        if self._remember_assistant_error(
            error_message,
            show_error=show_error,
            error_id=error_id,
        ):
            self.target.assistant_error(error_message)

    def tool_started(self, view: ToolCallView) -> None:
        snapshot = self.tool_projector.remember_call(view)
        self.tool_calls[view.tool_call_id] = snapshot
        if self.measure_tool_elapsed:
            self._tool_started_at[view.tool_call_id] = self.now()
        self.target.tool_started(view.tool_call_id, snapshot)

    def tool_updated(self, view: ToolCallView) -> None:
        if view.tool_call_id not in self.tool_calls:
            self.tool_started(view)

    def has_active_tool_call(self, tool_call_id: str) -> bool:
        return tool_call_id in self.tool_calls

    def tool_call_snapshot(self, tool_call_id: str) -> ToolCallSnapshot | None:
        return self.tool_calls.get(tool_call_id)

    def has_rendered_tool_result(self, tool_call_id: str) -> bool:
        return (
            self.track_rendered_tool_results
            and tool_call_id in self.rendered_tool_results
        )

    def begin_tool_finish(self, tool_call_id: str) -> ToolFinishContext:
        fallback_started_at = self.now() if self.measure_tool_elapsed else 0.0
        context = ToolFinishContext(
            tool_call_id=tool_call_id,
            snapshot=self.tool_calls.get(tool_call_id),
            started_at=self._tool_started_at.get(
                tool_call_id,
                fallback_started_at,
            ),
        )
        if self.tool_finish_cleanup == "before_projection":
            self._complete_tool_finish(context)
        return context

    def tool_finished(
        self,
        view: ToolResultView,
        *,
        context: ToolFinishContext | None = None,
    ) -> None:
        context = context or self.begin_tool_finish(view.tool_call_id)
        block = self.tool_projector.project_result(view, context.snapshot)
        finished_at = self.now() if self.measure_tool_elapsed else context.started_at
        self.target.tool_finished(
            block,
            elapsed_seconds=max(0.0, finished_at - context.started_at),
        )
        if self.tool_finish_cleanup == "after_target":
            self._complete_tool_finish(context)

    def tool_result_message(
        self,
        view: ToolResultView,
        *,
        deduplicate: bool = True,
    ) -> None:
        if deduplicate and self.has_rendered_tool_result(view.tool_call_id):
            return
        if deduplicate and self.track_rendered_tool_results:
            self.rendered_tool_results.add(view.tool_call_id)
        self.target.tool_result_message(self.tool_projector.project_result(view))

    def _complete_tool_finish(self, context: ToolFinishContext) -> None:
        self.tool_calls.pop(context.tool_call_id, None)
        self._tool_started_at.pop(context.tool_call_id, None)
        if self.track_rendered_tool_results:
            self.rendered_tool_results.add(context.tool_call_id)

    def retry_started(
        self,
        *,
        attempt: int | None,
        max_attempts: int | None,
        delay_ms: int | float | None,
        error_message: str | None,
    ) -> None:
        self.target.retry_started(
            attempt=attempt,
            max_attempts=max_attempts,
            delay_ms=delay_ms,
            error_message=error_message,
        )

    def compaction_started(self, *, reason: str | None) -> None:
        self.target.compaction_started(reason=reason)

    def compaction_finished(
        self,
        *,
        error_message: str | None,
        summary: str,
        tokens_before: int | None,
    ) -> None:
        self.target.compaction_finished(
            error_message=error_message,
            summary=summary,
            tokens_before=tokens_before,
        )

    def _remember_assistant_error(
        self,
        error_message: str | None,
        *,
        show_error: bool,
        error_id: ErrorId | None,
    ) -> bool:
        if not error_message:
            return False
        self.last_error_message = error_message
        if not show_error:
            return False
        if error_id is None:
            return True
        if error_id in self.rendered_assistant_errors:
            return False
        self.rendered_assistant_errors.add(error_id)
        return True


class ConversationProjectionBinding(Generic[ProjectionEventT]):
    """Bind a product event adapter to reusable conversation projection state."""

    __slots__ = ("event_handler", "projector")

    def __init__(
        self,
        projector: ConversationProjector,
        event_handler: Callable[[ProjectionEventT], None],
    ) -> None:
        self.projector = projector
        self.event_handler = event_handler

    def handle(self, event: ProjectionEventT) -> None:
        self.event_handler(event)

    @property
    def tool_calls(self) -> dict[str, ToolCallSnapshot]:
        return self.projector.tool_calls

    @tool_calls.setter
    def tool_calls(self, value: dict[str, ToolCallSnapshot]) -> None:
        self.projector.tool_calls = value

    @property
    def rendered_tool_results(self) -> set[str]:
        return self.projector.rendered_tool_results

    @rendered_tool_results.setter
    def rendered_tool_results(self, value: set[str]) -> None:
        self.projector.rendered_tool_results = value

    @property
    def rendered_assistant_errors(self) -> set[ErrorId]:
        return self.projector.rendered_assistant_errors

    @rendered_assistant_errors.setter
    def rendered_assistant_errors(self, value: set[ErrorId]) -> None:
        self.projector.rendered_assistant_errors = value

    @property
    def last_error_message(self) -> str | None:
        return self.projector.last_error_message

    @last_error_message.setter
    def last_error_message(self, value: str | None) -> None:
        self.projector.last_error_message = value


@dataclass(slots=True)
class SessionConversationEventAdapter:
    """Route normalized Agent-session events into a conversation projector."""

    projector: ConversationProjector
    tool_projection: ToolTranscriptProjectionBinding[Mapping[str, Any], object]
    read_pending_steers: StringQueueReader = tuple
    read_pending_followups: StringQueueReader = tuple
    on_session_info_changed: Callable[[], None] | None = None
    is_cancelled_error: CancellationErrorPredicate = is_cancelled_error_message
    recover_tool_updates: bool = True
    project_tool_result_messages: bool = True
    require_assistant_message_for_delta: bool = True
    project_run_starts: bool = True
    project_queue_updates: bool = True
    project_user_messages: bool = True
    project_assistant_error_text: bool = True
    project_compaction_details: bool = True

    def handle(self, event: Mapping[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "agent_start":
            if self.project_run_starts:
                self.projector.run_started()
            return
        if event_type == "queue_update":
            if self.project_queue_updates:
                self.projector.queues_updated(
                    steers=tuple(self.read_pending_steers()),
                    followups=tuple(self.read_pending_followups()),
                )
            return
        if event_type == "session_info_changed":
            if self.on_session_info_changed is not None:
                self.on_session_info_changed()
            return
        if event_type == "message_start":
            self._handle_message_start(event)
            return
        if event_type == "message_update":
            self._handle_message_update(event)
            return
        if event_type == "message_end":
            self._handle_message_end(event)
            return
        if event_type == "agent_end":
            self._handle_agent_end(event)
            return
        if event_type == "tool_execution_start":
            self.projector.tool_started(self.tool_projection.call_view(event))
            return
        if event_type == "tool_execution_update":
            self._handle_tool_update(event)
            return
        if event_type == "tool_execution_end":
            tool_call_id = self.tool_projection.call_id(event)
            context = self.projector.begin_tool_finish(tool_call_id)
            self.projector.tool_finished(
                self.tool_projection.result_view(
                    event,
                    snapshot=context.snapshot,
                ),
                context=context,
            )
            return
        if event_type == "auto_retry_start":
            self.projector.retry_started(
                attempt=event.get("attempt"),
                max_attempts=event.get("max_attempts"),
                delay_ms=event.get("delay_ms"),
                error_message=event.get("error_message"),
            )
            return
        if event_type == "compaction_start":
            self.projector.compaction_started(reason=event.get("reason"))
            return
        if event_type == "compaction_end":
            self._handle_compaction_end(event)

    def _handle_message_start(self, event: Mapping[str, Any]) -> None:
        message = event.get("message")
        role = getattr(message, "role", None)
        if role == "user":
            if self.project_user_messages:
                self.projector.user_message(
                    structural_message_text(getattr(message, "content", message))
                )
        elif role == "assistant":
            self.projector.assistant_started()

    def _handle_message_update(self, event: Mapping[str, Any]) -> None:
        message = event.get("message")
        if (
            self.require_assistant_message_for_delta
            and getattr(message, "role", None) != "assistant"
        ):
            return
        assistant_event = event.get("assistant_message_event")
        if not isinstance(assistant_event, Mapping):
            return
        if assistant_event.get("type") != "text_delta":
            return
        delta = assistant_event.get("delta")
        if isinstance(delta, str):
            self.projector.assistant_delta(delta)

    def _handle_message_end(self, event: Mapping[str, Any]) -> None:
        message = event.get("message")
        role = getattr(message, "role", None)
        if role == "assistant":
            error_message, show_error = _assistant_error(
                message,
                is_cancelled_error=self.is_cancelled_error,
            )
            final_text = (
                ""
                if error_message is not None
                and not self.project_assistant_error_text
                else structural_message_text(getattr(message, "content", message))
            )
            self.projector.assistant_finished(
                final_text,
                error_message=error_message,
                show_error=show_error,
                error_id=id(message),
            )
            return
        if role == "toolResult" and self.project_tool_result_messages:
            tool_call_id = self.tool_projection.message_id(message)
            if tool_call_id and self.projector.has_rendered_tool_result(tool_call_id):
                return
            self.projector.tool_result_message(
                self.tool_projection.tool_result_message_view(message),
                deduplicate=bool(tool_call_id),
            )

    def _handle_tool_update(self, event: Mapping[str, Any]) -> None:
        if not self.recover_tool_updates:
            return
        tool_call_id = self.tool_projection.call_id(event)
        if self.projector.has_active_tool_call(tool_call_id):
            return
        self.projector.tool_updated(self.tool_projection.call_view(event))

    def _handle_compaction_end(self, event: Mapping[str, Any]) -> None:
        raw_error = event.get("error_message")
        if raw_error:
            self.projector.compaction_finished(
                error_message=(
                    raw_error if isinstance(raw_error, str) else str(raw_error)
                ),
                summary="",
                tokens_before=None,
            )
            return
        if not self.project_compaction_details:
            self.projector.compaction_finished(
                error_message=None,
                summary="",
                tokens_before=None,
            )
            return
        self.projector.compaction_finished(
            error_message=None,
            summary=_compaction_summary(event),
            tokens_before=_compaction_tokens_before(event),
        )

    def _handle_agent_end(self, event: Mapping[str, Any]) -> None:
        messages = event.get("messages")
        if not isinstance(messages, list):
            return
        for message in reversed(messages):
            if getattr(message, "role", None) != "assistant":
                continue
            error_message, show_error = _assistant_error(
                message,
                is_cancelled_error=self.is_cancelled_error,
            )
            if error_message is not None:
                self.projector.assistant_error(
                    error_message,
                    show_error=show_error,
                    error_id=id(message),
                )
            return


def _assistant_error(
    message: object,
    *,
    is_cancelled_error: CancellationErrorPredicate,
) -> tuple[str | None, bool]:
    error_message = getattr(message, "error_message", None)
    stop_reason = getattr(message, "stop_reason", None)
    if not isinstance(error_message, str) or not error_message:
        return None, False
    if stop_reason not in {"error", "aborted"}:
        return None, False
    return error_message, not (
        stop_reason == "aborted" and is_cancelled_error(error_message)
    )


def _compaction_summary(event: Mapping[str, Any]) -> str:
    result = event.get("result")
    if not isinstance(result, Mapping):
        return ""
    summary = result.get("summary")
    return summary.strip() if isinstance(summary, str) else ""


def _compaction_tokens_before(event: Mapping[str, Any]) -> int | None:
    result = event.get("result")
    if not isinstance(result, Mapping):
        return None
    tokens_before = result.get("tokens_before")
    return tokens_before if isinstance(tokens_before, int) else None


__all__ = [
    "CancellationErrorPredicate",
    "ConversationProjectionBinding",
    "ConversationProjectionTarget",
    "ConversationProjector",
    "SessionConversationEventAdapter",
    "ToolFinishContext",
]
