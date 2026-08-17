"""Reusable full-screen conversation application shell."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from loushang.harnesstui.conversation.reader import TranscriptReaderSurface
from loushang.harnesstui.conversation.screen_frame import ScreenFramePresentation
from loushang.harnesstui.conversation.screen_state import (
    ActiveTranscriptWindow,
    ScreenConversationState,
)
from loushang.harnesstui.conversation.source import (
    ActiveWindowTranscriptSource,
    TranscriptSource,
)
from loushang.harnesstui.conversation.window_budget import (
    trim_records_to_line_budget,
)
from loushang.harnesstui.status.line import (
    StatusLinePreviewSnapshot,
    StatusLineSettings,
)
from loushang.tui import (
    BottomFrame,
    Composer,
    PendingQueueView,
    RenderConstraints,
    RenderRequestKind,
    RenderResult,
    ScreenLayout,
    StatusBar,
    Surface,
    SurfaceHost,
    TerminalRuntimeCapabilities,
    WorkingLine,
    theme_capabilities_from_runtime,
)
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    DisplayRecord,
)
from loushang.tui.ui_parts.layout import CappedRenderable
from loushang.tui.ui_parts.transcript import (
    DEFAULT_STABLE_TRANSCRIPT_CACHE_ENTRY_LIMIT,
    NeutralTranscriptPresentation,
    TranscriptPresentation,
    TranscriptRegion,
)

ACTIVE_RENDER_INTERVAL_MS = 80


def _normalized_compaction_summary(summary: str) -> str:
    return summary.strip()


@dataclass(slots=True)
class ScreenConversationApp:
    """Coordinate product-neutral conversation state with a TUI screen."""

    model_label: str | None
    cwd: str
    branch: str | None
    session_label: str | None
    now: Callable[[], float] = time.monotonic
    composer: Composer = field(default_factory=Composer)
    state: ScreenConversationState = field(init=False)
    active_surface: Any | None = None
    surface_host: SurfaceHost | None = None
    transcript_theme: ThemeResolver | None = None
    welcome_theme: ThemeResolver | None = None
    active_transcript_line_budget: int = 0
    compaction_summary_formatter: Callable[[str], str] = (
        _normalized_compaction_summary
    )
    stable_render_cache_entry_limit: int = DEFAULT_STABLE_TRANSCRIPT_CACHE_ENTRY_LIMIT
    render_requester: Callable[[RenderRequestKind], object] | None = None
    terminal_diagnostics_provider: Callable[[], str] | None = None
    terminal_capabilities: TerminalRuntimeCapabilities | None = None
    transcript_source_factory: Callable[[], TranscriptSource] | None = None
    _transcript_presentation: TranscriptPresentation = field(
        init=False,
        repr=False,
    )
    _transcript_region: TranscriptRegion = field(init=False, repr=False)
    _bottom_frame_component: BottomFrame = field(init=False, repr=False)
    _frame_presentation: ScreenFramePresentation = field(init=False, repr=False)
    _render_baseline_reset_reason: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.state = ScreenConversationState(
            model_label=self.model_label,
            cwd=self.cwd,
            branch=self.branch,
            session_label=self.session_label,
        )
        self._transcript_presentation = self._create_transcript_presentation()
        self._transcript_region = TranscriptRegion(
            theme=self.transcript_theme,
            presentation=self._transcript_presentation,
        )
        self._bottom_frame_component = BottomFrame(composer=self.composer)
        self._frame_presentation = self._create_frame_presentation()

    def _create_transcript_presentation(self) -> TranscriptPresentation:
        return NeutralTranscriptPresentation()

    def _create_frame_presentation(self) -> ScreenFramePresentation:
        raise NotImplementedError("a product screen binding must supply frame copy")

    def _prepare_transcript_presentation(self) -> None:
        """Synchronize product context before a frame without allocating a profile."""

    def start_prompt(self, text: str, *, started_at: float | None = None) -> None:
        self.state.start_prompt(
            text,
            started_at=self.now() if started_at is None else started_at,
        )
        self.composer.add_history(text)
        self.composer.clear()

    def start_pending_prompt(
        self,
        text: str,
        *,
        started_at: float | None = None,
    ) -> None:
        self.state.start_prompt(
            text,
            started_at=self.now() if started_at is None else started_at,
        )
        self.composer.add_history(text)

    def begin_run(self, *, started_at: float | None = None) -> None:
        self.state.begin_run(
            started_at=self.now() if started_at is None else started_at,
        )

    def begin_assistant(self) -> None:
        self.state.begin_assistant()
        self._transcript_region.clear_transient_cache()
        self._request_render("product")

    def append_assistant_chunk(self, chunk: str) -> None:
        self.state.append_assistant_chunk(chunk)
        self._request_render("stream")

    def end_assistant(self, final_text: str | None = None) -> None:
        draft_buffer = self.state.assistant_draft_buffer
        draft_text = final_text
        if draft_text is None and draft_buffer is not None:
            draft_text = draft_buffer.text
        self.state.end_assistant(draft_text)
        committed = self.state.records[-1] if self.state.records else None
        if (
            isinstance(committed, AssistantMessageRecord)
            and committed.text == draft_text
        ):
            self._transcript_region.promote_transient_cache(
                committed,
                source_buffer=draft_buffer,
            )
        self._transcript_region.clear_transient_cache()

    def complete_run(self, *, elapsed_seconds: float | None = None) -> None:
        elapsed = self.elapsed_seconds() if elapsed_seconds is None else elapsed_seconds
        self.state.complete_run(elapsed_seconds=elapsed)
        self._transcript_region.clear_transient_cache()

    def queue_followup(self, text: str) -> None:
        self.state.queue_followup(text)

    def queue_steer(self, text: str) -> None:
        self.state.queue_steer(text)

    def sync_queues(
        self,
        *,
        steers: tuple[str, ...] | list[str],
        followups: tuple[str, ...] | list[str],
    ) -> None:
        self.state.sync_queues(steers=steers, followups=followups)

    def set_status(self, message: str | None) -> None:
        self.state.set_status(message)
        self._request_render("product")

    def set_statusline_visible(self, visible: bool) -> None:
        self.set_statusline_settings(
            replace(self.state.statusline_settings, enabled=visible)
        )

    def set_statusline_settings(self, settings: StatusLineSettings) -> None:
        self.state.statusline_settings = settings
        self.state.statusline_visible = settings.enabled
        self._request_render("product")

    def request_render(self, kind: RenderRequestKind = "product") -> None:
        self._request_render(kind)

    def statusline_preview_snapshot(self) -> StatusLinePreviewSnapshot:
        return self._frame_presentation.statusline_preview_snapshot(self.state)

    def open_transcript_reader(self) -> bool:
        if self.surface_host is None:
            return False
        source = (
            self.transcript_source_factory()
            if self.transcript_source_factory is not None
            else ActiveWindowTranscriptSource(self.state)
        )
        reader = TranscriptReaderSurface(source)
        self.surface_host.open_surface(
            Surface(
                renderable=reader,
                focus_target=reader,
                presentation="modal",
                max_height="100%",
            )
        )
        self._request_render("input")
        return True

    def add_error(self, summary: str, diagnostics: str = "") -> None:
        self.state.add_error(summary, diagnostics)
        self._request_render("product")

    def add_status(self, message: str) -> None:
        self.state.add_status(message)
        self._request_render("product")

    def replace_transcript_window(
        self,
        records: Iterable[DisplayRecord] | ActiveTranscriptWindow,
        *,
        evicted_prefix_record_count: int = 0,
        reason: str = "replace",
    ) -> None:
        self.state.replace_transcript_window(
            records,
            evicted_prefix_record_count=evicted_prefix_record_count,
        )
        self._render_baseline_reset_reason = (
            f"transcript_window_replaced:{reason}"
            if reason
            else "transcript_window_replaced"
        )

    def compact_transcript_window(
        self,
        *,
        summary: str,
        max_records: int = 80,
    ) -> None:
        """Replace the oldest active records with one reusable summary record."""

        summary_record = AssistantMessageRecord(
            self.compaction_summary_formatter(summary)
        )
        active_records = tuple(self.state.records)
        keep_count = max(0, max_records - 1)
        kept_records = active_records[-keep_count:] if keep_count else ()
        evicted_count = max(0, len(active_records) - len(kept_records))
        self.replace_transcript_window(
            (summary_record, *kept_records),
            evicted_prefix_record_count=(
                self.state.evicted_prefix_record_count + evicted_count
            ),
            reason="compaction",
        )

    def append_context_compaction_record(
        self,
        *,
        summary: str = "",
        tokens_before: int | None = None,
    ) -> None:
        """Append a compaction fact without changing the active transcript window."""

        self.state.records.append(
            ContextCompactionRecord(
                summary=summary,
                tokens_before=tokens_before,
            )
        )
        self.state.mark_records_changed()

    def trim_active_transcript_window(self) -> None:
        """Apply the configured logical-line budget to the active window."""

        records, evicted_count, changed = trim_records_to_line_budget(
            tuple(self.state.records),
            line_budget=self.active_transcript_line_budget,
        )
        if not changed:
            return
        self.state.replace_transcript_window(
            ActiveTranscriptWindow(
                records=records,
                evicted_prefix_record_count=(
                    self.state.evicted_prefix_record_count + evicted_count
                ),
            )
        )
        self._render_baseline_reset_reason = (
            "transcript_window_trimmed:active_line_budget"
        )

    def consume_render_baseline_reset_reason(self) -> str | None:
        reason = self._render_baseline_reset_reason
        self._render_baseline_reset_reason = None
        return reason

    def elapsed_seconds(self) -> float:
        if self.state.active_started_at is None:
            return 0.0
        return max(0.0, self.now() - self.state.active_started_at)

    def next_frame_due_ms(self, *, after_ms: int) -> int | None:
        completion_due_ms = self.composer.next_frame_due_ms(after_ms=after_ms)
        if not self.state.running:
            return completion_due_ms
        active_due_ms = after_ms + ACTIVE_RENDER_INTERVAL_MS
        if completion_due_ms is None:
            return active_due_ms
        return min(active_due_ms, completion_due_ms)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        visible_height = constraints.visible_height or constraints.max_height
        editor_height = self._bottom_frame_height(visible_height)
        self._transcript_region.records = self.state.records
        self._transcript_region.records_revision = self.state.records_revision
        self._transcript_region.draft = None
        self._transcript_region.draft_buffer = self.state.assistant_draft_buffer
        self._prepare_transcript_presentation()
        self._transcript_region.theme = self.transcript_theme
        self._transcript_region.capabilities = (
            theme_capabilities_from_runtime(self.terminal_capabilities)
            if self.terminal_capabilities is not None
            else None
        )
        self._transcript_region.window_generation = (
            self.state.transcript_window_generation
        )
        self._transcript_region.stable_cache_entry_limit = (
            self.stable_render_cache_entry_limit
        )
        layout = ScreenLayout(
            transcript=self._transcript_region,
            editor=CappedRenderable(
                self._bottom_frame(),
                max_height=editor_height,
            ),
            editor_min_height=editor_height,
        )
        return layout.render(constraints)

    def startup_welcome_panel(self) -> Any:
        raise NotImplementedError(
            "a product screen binding must supply a welcome panel"
        )

    def _expanded_bottom_frame(self) -> bool:
        return self._frame_presentation.expanded_bottom_frame(
            self.state,
            active_surface=self.active_surface,
        )

    def _bottom_frame_height(self, visible_height: int) -> int:
        return self._frame_presentation.bottom_frame_height(
            self.state,
            active_surface=self.active_surface,
            visible_height=visible_height,
        )

    def _request_render(self, kind: RenderRequestKind) -> None:
        if self.render_requester is not None:
            self.render_requester(kind)

    def _bottom_frame(self) -> BottomFrame:
        return self._frame_presentation.populate_bottom_frame(
            self._bottom_frame_component,
            composer=self.composer,
            state=self.state,
            active_surface=self.active_surface,
            elapsed_seconds=self.elapsed_seconds(),
        )

    def _working_line(self) -> WorkingLine | None:
        return self._frame_presentation.working_line(
            self.state,
            elapsed_seconds=self.elapsed_seconds(),
        )

    def _pending_queue(self) -> PendingQueueView | None:
        return self._frame_presentation.pending_queue(self.state)

    def _status_bar(self) -> StatusBar:
        return self._frame_presentation.status_bar(self.state)


__all__ = ["ACTIVE_RENDER_INTERVAL_MS", "ScreenConversationApp"]
