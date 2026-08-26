from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from loushang.harnesstui.conversation.projection import (
    ConversationProjectionBinding,
    ConversationProjector,
)
from loushang.harnesstui.conversation.screen_state import ScreenConversationState
from loushang.harnesstui.conversation.tool_transcript import (
    ToolCallSnapshot,
    ToolTranscriptBlock,
    ToolTranscriptProjector,
)
from loushang.tui.transcript import ToolExecutionRecord, UserPromptRecord

ProjectionEventT = TypeVar("ProjectionEventT")


class ScreenConversationProjectionPort(Protocol):
    """Screen operations required by the reusable projection target."""

    state: ScreenConversationState

    def begin_run(self, *, started_at: float | None = None) -> None: ...

    def sync_queues(
        self,
        *,
        steers: tuple[str, ...],
        followups: tuple[str, ...],
    ) -> None: ...

    def begin_assistant(self) -> None: ...

    def append_assistant_chunk(self, chunk: str) -> None: ...

    def end_assistant(self, final_text: str | None = None) -> None: ...

    def add_error(self, summary: str, diagnostics: str = "") -> None: ...

    def set_status(self, message: str | None) -> None: ...

    def append_context_compaction_record(
        self,
        *,
        summary: str = "",
        tokens_before: int | None = None,
    ) -> None: ...


class ToolRecordProjector(Protocol):
    """Convert a neutral tool block into a screen transcript record."""

    def __call__(
        self,
        block: ToolTranscriptBlock,
        *,
        elapsed_seconds: float = 0.0,
    ) -> ToolExecutionRecord: ...


class ToolTitleResolver(Protocol):
    """Resolve product-owned running-tool labels from a neutral snapshot."""

    def __call__(self, snapshot: ToolCallSnapshot) -> str: ...


class ScreenProjectionStatusCopy(Protocol):
    """Supply product-owned status text for screen projection events."""

    def retry_status(
        self,
        *,
        attempt: int | None,
        max_attempts: int | None,
        delay_ms: int | float | None,
        error_message: str | None,
    ) -> str: ...

    def compaction_started_status(self, *, reason: str | None) -> str: ...

    def compaction_finished_status(
        self,
        *,
        error_message: str | None,
        tokens_before: int | None,
        tokens_after: int | None,
        duration_ms: int | float | None,
        aborted: bool,
        will_retry: bool,
        stage: str | None,
    ) -> str: ...


class StandardScreenProjectionStatusCopy:
    """Default status copy shared by Agent Product screens."""

    def retry_status(
        self,
        *,
        attempt: int | None,
        max_attempts: int | None,
        delay_ms: int | float | None,
        error_message: str | None,
    ) -> str:
        return f"retry {attempt}/{max_attempts} in {delay_ms}ms: {error_message}"

    def compaction_started_status(self, *, reason: str | None) -> str:
        return f"compact start: {reason}"

    def compaction_finished_status(
        self,
        *,
        error_message: str | None,
        tokens_before: int | None,
        tokens_after: int | None,
        duration_ms: int | float | None,
        aborted: bool,
        will_retry: bool,
        stage: str | None,
    ) -> str:
        return format_compaction_finished_status(
            error_message=error_message,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            duration_ms=duration_ms,
            aborted=aborted,
            will_retry=will_retry,
            stage=stage,
        )


@dataclass(slots=True)
class ScreenConversationProjectionTarget:
    """Map neutral conversation facts onto a reusable screen conversation port."""

    app: ScreenConversationProjectionPort
    tool_title_resolver: ToolTitleResolver
    tool_record_projector: ToolRecordProjector
    status_copy: ScreenProjectionStatusCopy

    def run_started(self, *, start_time: Callable[[], float]) -> None:
        if not self.app.state.running:
            self.app.begin_run(started_at=start_time())

    def queues_updated(
        self,
        *,
        steers: tuple[str, ...],
        followups: tuple[str, ...],
    ) -> None:
        self.app.sync_queues(steers=steers, followups=followups)

    def user_message(self, text: str) -> None:
        text = text.strip()
        if text and not self.app.state.consume_pending_user_echo(text):
            self.app.state.records.append(UserPromptRecord(text))
            self.app.state.mark_records_changed()

    def assistant_started(self) -> None:
        self.app.begin_assistant()

    def assistant_delta(self, delta: str) -> None:
        self.app.append_assistant_chunk(delta)

    def assistant_finished(
        self,
        final_text: str,
        *,
        error_message: str | None,
        show_error: bool,
    ) -> None:
        # Screen commits the final assistant text even when the message reports an
        # error, then adds only errors that product policy says should be visible.
        self.app.end_assistant(final_text)
        if error_message is not None and show_error:
            self.app.add_error(error_message)

    def assistant_error(self, error_message: str) -> None:
        self.app.add_error(error_message)

    def tool_started(
        self,
        tool_call_id: str,
        snapshot: ToolCallSnapshot,
    ) -> None:
        self.app.state.upsert_tool_record(
            tool_call_id,
            ToolExecutionRecord(
                name=self.tool_title_resolver(snapshot),
                state="running",
                elapsed_seconds=0.0,
            ),
        )

    def tool_finished(
        self,
        block: ToolTranscriptBlock,
        *,
        elapsed_seconds: float,
    ) -> None:
        self.app.state.upsert_tool_record(
            block.tool_call_id,
            self.tool_record_projector(
                block,
                elapsed_seconds=elapsed_seconds,
            ),
        )

    def tool_result_message(self, block: ToolTranscriptBlock) -> None:
        # Full-screen mode already projects tool execution lifecycle records.
        del block

    def retry_started(
        self,
        *,
        attempt: int | None,
        max_attempts: int | None,
        delay_ms: int | float | None,
        error_message: str | None,
    ) -> None:
        self.app.set_status(
            self.status_copy.retry_status(
                attempt=attempt,
                max_attempts=max_attempts,
                delay_ms=delay_ms,
                error_message=error_message,
            )
        )

    def compaction_started(self, *, reason: str | None) -> None:
        self.app.set_status(self.status_copy.compaction_started_status(reason=reason))

    def compaction_finished(
        self,
        *,
        error_message: str | None,
        summary: str,
        tokens_before: int | None,
        tokens_after: int | None = None,
        duration_ms: int | float | None = None,
        aborted: bool = False,
        will_retry: bool = False,
        stage: str | None = None,
    ) -> None:
        self.app.set_status(
            self.status_copy.compaction_finished_status(
                error_message=error_message,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                duration_ms=duration_ms,
                aborted=aborted,
                will_retry=will_retry,
                stage=stage,
            )
        )
        if error_message or aborted or stage in {"aborted", "failed"}:
            return
        if summary:
            self.app.append_context_compaction_record(
                summary=summary,
                tokens_before=tokens_before,
            )


def format_compaction_finished_status(
    *,
    error_message: str | None,
    tokens_before: int | None,
    tokens_after: int | None,
    duration_ms: int | float | None,
    aborted: bool,
    will_retry: bool,
    stage: str | None,
) -> str:
    """Format one completed compaction lifecycle observation."""

    duration = _format_duration(duration_ms)
    if aborted or stage == "aborted":
        return _join_status_parts("compact cancelled", duration)
    if error_message or stage == "failed":
        detail = f"compact error: {error_message}" if error_message else "compact failed"
        retry = "retrying" if will_retry else None
        return _join_status_parts(detail, retry, duration)

    if tokens_before is not None and tokens_after is not None:
        result = (
            f"context compacted · {_format_tokens(tokens_before)} -> "
            f"≈{_format_tokens(tokens_after)}"
        )
    elif tokens_before is not None:
        result = (
            f"context compacted · {_format_tokens(tokens_before)} before · "
            "new size pending"
        )
    else:
        result = "compact done"
    retry = "retrying" if will_retry else None
    return _join_status_parts(result, retry, duration)


def _format_tokens(tokens: int) -> str:
    if tokens < 1_000:
        return str(tokens)
    return f"{tokens / 1_000:.0f}k"


def _format_duration(duration_ms: int | float | None) -> str | None:
    if duration_ms is None:
        return None
    if duration_ms < 1_000:
        return f"{max(0, round(duration_ms))}ms"
    seconds = max(0, round(duration_ms / 1_000))
    if seconds < 60:
        return f"{seconds}s"
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes}m{remaining_seconds:02d}s"


def _join_status_parts(*parts: str | None) -> str:
    return " · ".join(part for part in parts if part)


def build_screen_conversation_projection(
    app: ScreenConversationProjectionPort,
    *,
    tool_projector: ToolTranscriptProjector,
    tool_title_resolver: ToolTitleResolver,
    tool_record_projector: ToolRecordProjector,
    status_copy: ScreenProjectionStatusCopy,
    event_handler_factory: Callable[
        [ConversationProjector], Callable[[ProjectionEventT], None]
    ],
    now: Callable[[], float] = time.monotonic,
) -> ConversationProjectionBinding[ProjectionEventT]:
    """Build a screen target, neutral projector, and product event binding."""

    projector = ConversationProjector(
        target=ScreenConversationProjectionTarget(
            app,
            tool_title_resolver=tool_title_resolver,
            tool_record_projector=tool_record_projector,
            status_copy=status_copy,
        ),
        tool_projector=tool_projector,
        now=now,
        track_rendered_tool_results=False,
    )
    return ConversationProjectionBinding(
        projector=projector,
        event_handler=event_handler_factory(projector),
    )


__all__ = [
    "ScreenConversationProjectionPort",
    "ScreenConversationProjectionTarget",
    "ScreenProjectionStatusCopy",
    "StandardScreenProjectionStatusCopy",
    "ToolRecordProjector",
    "ToolTitleResolver",
    "build_screen_conversation_projection",
]
