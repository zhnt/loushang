from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from loushang.harnesstui.conversation.input_policy import (
    ConversationInputCapabilities,
)
from loushang.harnesstui.status.line import StatusLineSettings
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    ErrorRecord,
    StatusRecord,
    StreamingTextBuffer,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)


@dataclass(frozen=True, slots=True)
class ActiveTranscriptWindow:
    """Bounded transcript records currently retained by a screen UI."""

    records: tuple[DisplayRecord, ...] = ()
    evicted_prefix_record_count: int = 0


@dataclass(slots=True)
class ScreenConversationState:
    """Product-neutral mutable state for a screen conversation."""

    records: list[DisplayRecord] = field(default_factory=list)
    records_revision: int = field(default=0, init=False)
    transcript_window_generation: int = 0
    evicted_prefix_record_count: int = 0
    active_started_at: float | None = None
    pending_followups: list[str] = field(default_factory=list)
    pending_steers: list[str] = field(default_factory=list)
    input_capabilities: ConversationInputCapabilities = field(
        default_factory=ConversationInputCapabilities
    )
    interruption_message: str | None = None
    status_message: str | None = None
    model_label: str | None = None
    cwd: str = ""
    branch: str | None = None
    session_label: str | None = None
    permission_profile: str | None = "standard"
    statusline_visible: bool = True
    statusline_settings: StatusLineSettings = field(default_factory=StatusLineSettings)
    _assistant_draft_buffer: StreamingTextBuffer | None = field(
        default=None, init=False, repr=False
    )
    _tool_record_indices: dict[str, int] = field(default_factory=dict, repr=False)
    _pending_user_echo: str | None = field(default=None, init=False, repr=False)

    @property
    def running(self) -> bool:
        return self.active_started_at is not None

    @property
    def assistant_draft(self) -> AssistantMessageRecord | None:
        if self._assistant_draft_buffer is None:
            return None
        return AssistantMessageRecord(self._assistant_draft_buffer.text, stable=False)

    @property
    def assistant_draft_buffer(self) -> StreamingTextBuffer | None:
        return self._assistant_draft_buffer

    def mark_records_changed(self) -> None:
        self.records_revision += 1

    def replace_transcript_window(
        self,
        records: Iterable[DisplayRecord] | ActiveTranscriptWindow,
        *,
        evicted_prefix_record_count: int = 0,
    ) -> None:
        if isinstance(records, ActiveTranscriptWindow):
            window = records
        else:
            window = ActiveTranscriptWindow(
                records=tuple(records),
                evicted_prefix_record_count=evicted_prefix_record_count,
            )
        replacement = list(window.records)
        records_changed = replacement != self.records
        self.records = replacement
        self.evicted_prefix_record_count = max(0, window.evicted_prefix_record_count)
        self.transcript_window_generation += 1
        self._tool_record_indices.clear()
        self._pending_user_echo = None
        if records_changed:
            self.mark_records_changed()

    def trim_transcript_prefix(self, *, max_records: int) -> int:
        max_records = max(0, max_records)
        if len(self.records) <= max_records:
            return 0
        evicted_count = len(self.records) - max_records
        del self.records[:evicted_count]
        self.mark_records_changed()
        self.evicted_prefix_record_count += evicted_count
        self.transcript_window_generation += 1
        self._tool_record_indices.clear()
        self._pending_user_echo = None
        return evicted_count

    def start_prompt(self, text: str, *, started_at: float) -> None:
        stripped = text.strip()
        if stripped:
            self.records.append(UserPromptRecord(stripped))
            self.mark_records_changed()
            self._pending_user_echo = stripped
        self.active_started_at = started_at
        self._assistant_draft_buffer = None
        self.interruption_message = None
        self.status_message = None
        self._tool_record_indices.clear()

    def begin_run(self, *, started_at: float) -> None:
        self.active_started_at = started_at
        self.interruption_message = None
        self.status_message = None
        self._tool_record_indices.clear()
        self._pending_user_echo = None

    def begin_assistant(self) -> None:
        self._assistant_draft_buffer = None
        self._pending_user_echo = None

    def append_assistant_chunk(self, chunk: str) -> None:
        if not chunk:
            return
        if self._assistant_draft_buffer is None:
            self._assistant_draft_buffer = StreamingTextBuffer()
        self._assistant_draft_buffer.append(chunk)

    def end_assistant(self, final_text: str | None = None) -> None:
        text = final_text
        if text is None and self._assistant_draft_buffer is not None:
            text = self._assistant_draft_buffer.text
        self._assistant_draft_buffer = None
        if text:
            self.records.append(AssistantMessageRecord(text, stable=True))
            self.mark_records_changed()

    def complete_run(self, *, elapsed_seconds: float) -> None:
        if self.assistant_draft is not None:
            self.end_assistant()
        if not self.records or not isinstance(self.records[-1], WorkedDividerRecord):
            self.records.append(WorkedDividerRecord(elapsed_seconds))
            self.mark_records_changed()
        self.active_started_at = None
        self.status_message = None
        self._tool_record_indices.clear()
        self._pending_user_echo = None

    def queue_followup(self, text: str) -> None:
        stripped = text.strip()
        if stripped:
            self.pending_followups.append(stripped)

    def queue_steer(self, text: str) -> None:
        stripped = text.strip()
        if stripped:
            self.pending_steers.append(stripped)

    def sync_queues(
        self,
        *,
        steers: tuple[str, ...] | list[str],
        followups: tuple[str, ...] | list[str],
    ) -> None:
        self.pending_steers = [item for item in steers if item.strip()]
        self.pending_followups = [item for item in followups if item.strip()]

    def clear_queues(self) -> tuple[list[str], list[str]]:
        steers = [*self.pending_steers]
        followups = [*self.pending_followups]
        self.pending_steers.clear()
        self.pending_followups.clear()
        return steers, followups

    def restore_queued_to_text(self) -> str:
        steers, followups = self.clear_queues()
        return "\n".join([*steers, *followups])

    def abort(self, *, message: str, elapsed_seconds: float) -> None:
        if self.assistant_draft is not None:
            self.end_assistant()
        self.records.append(WorkedDividerRecord(elapsed_seconds))
        self.mark_records_changed()
        self.interruption_message = message
        self.active_started_at = None
        self.status_message = None
        self._tool_record_indices.clear()
        self._pending_user_echo = None

    def add_error(self, summary: str, diagnostics: str = "") -> None:
        if summary:
            self.records.append(ErrorRecord(summary, diagnostics))
            self.mark_records_changed()
        self._pending_user_echo = None

    def add_status(self, message: str) -> None:
        stripped = message.strip()
        if stripped:
            self.records.append(StatusRecord(stripped))
            self.mark_records_changed()
        self._pending_user_echo = None

    def consume_pending_user_echo(self, text: str) -> bool:
        if self._pending_user_echo is None:
            return False
        if self._pending_user_echo == text:
            self._pending_user_echo = None
            return True
        self._pending_user_echo = None
        return False

    def set_status(self, message: str | None) -> None:
        self.status_message = (
            message.strip()
            if isinstance(message, str) and message.strip()
            else None
        )

    def upsert_tool_record(
        self, tool_call_id: str, record: ToolExecutionRecord
    ) -> None:
        existing = self._tool_record_indices.get(tool_call_id)
        if existing is not None and 0 <= existing < len(self.records):
            if self.records[existing] == record:
                return
            self.records[existing] = record
            self.mark_records_changed()
            return
        self._tool_record_indices[tool_call_id] = len(self.records)
        self.records.append(record)
        self.mark_records_changed()


__all__ = ["ActiveTranscriptWindow", "ScreenConversationState"]
