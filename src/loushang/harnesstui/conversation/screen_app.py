"""Reusable full-screen conversation application shell."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from loushang.harnesstui.conversation.input_policy import ConversationCapabilities
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
    RenderBaselineReset,
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
from loushang.tui.cell_width import (
    slice_by_column,
    strip_control_sequences,
    visible_width,
)
from loushang.tui.core import RenderLine
from loushang.tui.keybindings import KeybindingManager
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    DisplayRecord,
    ToolExecutionRecord,
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
    capability_provider: Callable[[], ConversationCapabilities] | None = field(
        default=None, kw_only=True
    )
    active_surface: Any | None = None
    surface_host: SurfaceHost | None = None
    transcript_theme: ThemeResolver | None = None
    welcome_theme: ThemeResolver | None = None
    active_transcript_line_budget: int = 0
    compaction_summary_formatter: Callable[[str], str] = _normalized_compaction_summary
    stable_render_cache_entry_limit: int = DEFAULT_STABLE_TRANSCRIPT_CACHE_ENTRY_LIMIT
    render_requester: Callable[[RenderRequestKind], object] | None = None
    terminal_diagnostics_provider: Callable[[], str] | None = None
    terminal_capabilities: TerminalRuntimeCapabilities | None = None
    keybindings: KeybindingManager | None = None
    transcript_source_factory: Callable[[], TranscriptSource] | None = None
    context_usage_provider: Callable[[], object | None] | None = None
    _transcript_presentation: TranscriptPresentation = field(
        init=False,
        repr=False,
    )
    _transcript_region: TranscriptRegion = field(init=False, repr=False)
    _bottom_frame_component: BottomFrame = field(init=False, repr=False)
    _frame_presentation: ScreenFramePresentation = field(init=False, repr=False)
    _render_baseline_reset_reason: str | RenderBaselineReset | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _context_usage_refresh_key: tuple[int, int] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _expanded_tool_keys: set[str | int] = field(
        default_factory=set, init=False, repr=False
    )
    _focused_tool_index: int | None = field(default=None, init=False, repr=False)
    _focused_tool_key: str | int | None = field(default=None, init=False, repr=False)
    _screen_rows: tuple[str, ...] = field(default=(), init=False, repr=False)
    _selection_anchor: tuple[int, int] | None = field(
        default=None, init=False, repr=False
    )
    _selection_tip: tuple[int, int] | None = field(default=None, init=False, repr=False)
    _selection_revision: int | None = field(default=None, init=False, repr=False)
    _selection_screen_snapshot: tuple[str, ...] = field(
        default=(), init=False, repr=False
    )
    _mouse_press_control: int | None = field(default=None, init=False, repr=False)
    _mouse_press_revision: int | None = field(default=None, init=False, repr=False)
    _mouse_press_key: str | int | None = field(default=None, init=False, repr=False)
    _detail_anchor_revision: int | None = field(default=None, init=False, repr=False)
    _reader_surface: TranscriptReaderSurface | None = field(
        default=None, init=False, repr=False
    )
    _tool_key_to_index: dict[str | int, int] = field(
        default_factory=dict, init=False, repr=False
    )
    _tool_index_cache_revision: tuple[int, int] | None = field(
        default=None, init=False, repr=False
    )
    _mouse_press_position: tuple[int, int] | None = field(
        default=None, init=False, repr=False
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
        self._context_usage_refresh_key = None
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

    def present_copy_status(self, message: str) -> None:
        self.set_status(message)
        if self._reader_surface is not None and self._reader_surface.focused:
            self._reader_surface.copy_status = message
            self._request_render("input")

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

    def set_keybindings(self, keybindings: KeybindingManager) -> None:
        self.keybindings = keybindings

    def statusline_preview_snapshot(self) -> StatusLinePreviewSnapshot:
        self._refresh_context_usage()
        return self._frame_presentation.statusline_preview_snapshot(self.state)

    def open_transcript_reader(self) -> bool:
        if self.surface_host is None:
            return False
        self.clear_transcript_selection()
        self._mouse_press_control = None
        source = (
            self.transcript_source_factory()
            if self.transcript_source_factory is not None
            else ActiveWindowTranscriptSource(self.state)
        )
        reader = TranscriptReaderSurface(
            source, keybindings=self.keybindings or KeybindingManager()
        )
        self._reader_surface = reader
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
        self._reset_transcript_interaction()
        self._render_baseline_reset_reason = (
            f"transcript_window_replaced:{reason}"
            if reason
            else "transcript_window_replaced"
        )

    def install_resumed_history(
        self,
        records: Iterable[DisplayRecord],
    ) -> None:
        """Atomically install and bound history restored into this screen."""

        source_records = tuple(records)
        active_records, evicted_count, _changed = trim_records_to_line_budget(
            source_records,
            line_budget=self.active_transcript_line_budget,
        )
        self.state.replace_transcript_window(
            ActiveTranscriptWindow(
                records=active_records,
                evicted_prefix_record_count=evicted_count,
            )
        )
        self._reset_transcript_interaction()
        self._render_baseline_reset_reason = RenderBaselineReset(
            reason="transcript_window_replaced:resume",
            replay_hidden_prefix=True,
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
        self._reset_transcript_interaction()
        self._render_baseline_reset_reason = (
            "transcript_window_trimmed:active_line_budget"
        )

    def consume_render_baseline_reset_reason(
        self,
    ) -> str | RenderBaselineReset | None:
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
        if (
            self._selection_revision is not None
            and self._selection_revision != self.state.records_revision
        ):
            self._selection_anchor = self._selection_tip = None
            self._selection_revision = None
        if self.capability_provider is not None:
            current = self.capability_provider()
            if type(current) is not ConversationCapabilities:
                raise ValueError("invalid conversation capability projection")
            self.state.capabilities = current
        self._refresh_context_usage()
        self._refresh_tool_index_cache()
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
        self._transcript_region.expanded_tool_indices = frozenset(
            self._tool_key_to_index[key]
            for key in self._expanded_tool_keys
            if key in self._tool_key_to_index
        )
        if self._focused_tool_key is not None:
            self._focused_tool_index = self._tool_key_to_index.get(
                self._focused_tool_key
            )
        self._transcript_region.focused_tool_index = self._focused_tool_index
        self._transcript_region.anchor_tool_index = (
            self._focused_tool_index
            if self._focused_tool_index is not None
            and self._detail_anchor_revision == self.state.records_revision
            else None
        )
        self._transcript_region.visible_controls = {}
        self._transcript_region.visible_height = 0
        layout = ScreenLayout(
            transcript=self._transcript_region,
            editor=CappedRenderable(
                self._bottom_frame(),
                max_height=editor_height,
            ),
            editor_min_height=editor_height,
        )
        result = layout.render(constraints)
        if (
            self._focused_tool_index is not None
            and self._focused_tool_index
            not in self._transcript_region.visible_controls.values()
        ):
            self._focused_tool_index = None
            self._focused_tool_key = None
            self._detail_anchor_revision = None
        self._screen_rows = tuple(line.text for line in result.lines)
        if (
            self._selection_anchor is not None
            and self._selection_tip is not None
            and self._screen_rows[: self._transcript_region.visible_height]
            != self._selection_screen_snapshot
        ):
            self._selection_anchor = self._selection_tip = None
            self._selection_revision = None
        if self._selection_anchor is None or self._selection_tip is None:
            return result
        highlighted = tuple(
            RenderLine(self._highlight_selected_row(row, line.text))
            for row, line in enumerate(result.lines)
        )
        return RenderResult(lines=highlighted, cursor=result.cursor)

    def focus_detail_controls(self) -> bool:
        controls = tuple(self._transcript_region.visible_controls.values())
        if not controls:
            return False
        self._focused_tool_index = controls[0]
        self._focused_tool_key = self._tool_key(
            self.state.records[self._focused_tool_index]
        )  # type: ignore[arg-type]
        self._request_render("input")
        return True

    def move_detail_focus(self, direction: int) -> bool:
        controls = tuple(self._transcript_region.visible_controls.values())
        if self._focused_tool_index is None or not controls:
            return False
        position = (
            controls.index(self._focused_tool_index)
            if self._focused_tool_index in controls
            else len(controls) - 1
        )
        self._focused_tool_index = controls[(position + direction) % len(controls)]
        self._focused_tool_key = self._tool_key(
            self.state.records[self._focused_tool_index]
        )  # type: ignore[arg-type]
        self._request_render("input")
        return True

    def toggle_focused_detail(self) -> bool:
        if self._focused_tool_index is None:
            return False
        self._toggle_tool_detail(self._focused_tool_index)
        return True

    def clear_detail_focus(self) -> bool:
        if self._focused_tool_index is None:
            return False
        self._focused_tool_index = None
        self._focused_tool_key = None
        self._request_render("input")
        return True

    def clear_transcript_selection(self) -> bool:
        self._mouse_press_control = None
        self._mouse_press_key = None
        self._mouse_press_position = None
        if self._selection_anchor is None:
            return False
        self._selection_anchor = self._selection_tip = None
        self._selection_revision = None
        self._selection_screen_snapshot = ()
        self._request_render("input")
        return True

    def selected_transcript_text(self) -> str:
        bounds = self._selection_bounds()
        if bounds is None:
            return ""
        start, end = bounds
        chunks: list[str] = []
        for row in range(start[0], min(end[0] + 1, len(self._screen_rows))):
            if row in self._transcript_region.visible_controls:
                continue
            plain = strip_control_sequences(self._screen_rows[row])
            left = start[1] if row == start[0] else 0
            right = end[1] if row == end[0] else visible_width(plain)
            chunks.append(
                slice_by_column(
                    plain, start=left, length=max(0, right - left), strict=False
                ).text
            )
        return "\n".join(chunks)

    def handle_transcript_mouse(self, event: object) -> tuple[bool, str | None]:
        action = getattr(event, "mouse_action", "")
        if (
            action not in {"press", "drag", "release"}
            or getattr(event, "mouse_button", None) != 0
        ):
            return False, None
        row = max(0, getattr(event, "mouse_row", 0) or 0)
        column = max(0, getattr(event, "mouse_column", 0) or 0)
        control = self._transcript_region.visible_controls.get(row)
        if control is not None and row < len(self._screen_rows):
            line = strip_control_sequences(self._screen_rows[row])
            label = "Show Less" if "Show Less" in line else "Show Detail"
            start = line.find(label)
            if not start <= column < start + len(label):
                control = None
        if action == "press":
            self._mouse_press_control = control
            self._mouse_press_revision = self.state.records_revision
            self._mouse_press_position = (row, column)
            self._mouse_press_key = (
                self._tool_key(self.state.records[control])
                if control is not None
                else None  # type: ignore[arg-type]
            )
            if control is not None:
                self._selection_anchor = self._selection_tip = None
                self._selection_revision = None
                return True, None
            if row >= self._transcript_region.visible_height:
                return False, None
            self._selection_anchor = self._selection_tip = (row, column)
            self._selection_revision = self.state.records_revision
            self._selection_screen_snapshot = self._screen_rows[
                : self._transcript_region.visible_height
            ]
            return True, None
        if (
            action == "drag"
            and self._mouse_press_control is not None
            and self._mouse_press_position is not None
        ):
            self._selection_anchor = self._mouse_press_position
            self._selection_revision = self.state.records_revision
            self._selection_screen_snapshot = self._screen_rows[
                : self._transcript_region.visible_height
            ]
            self._mouse_press_control = None
            self._mouse_press_key = None
        if action == "drag" and self._selection_anchor is not None:
            self._mouse_press_control = None
            self._mouse_press_key = None
            self._mouse_press_position = None
            self._selection_tip = (
                min(row, self._transcript_region.visible_height - 1),
                column,
            )
            return True, None
        if action == "release":
            if (
                control is not None
                and control == self._mouse_press_control
                and self._mouse_press_revision == self.state.records_revision
                and self._mouse_press_key == self._tool_key(self.state.records[control])
            ):  # type: ignore[arg-type]
                self._toggle_tool_detail(control)
                self._mouse_press_control = None
                self._mouse_press_key = None
                return True, None
            self._mouse_press_control = None
            self._mouse_press_key = None
            if self._selection_anchor is not None:
                self._selection_tip = (
                    min(row, self._transcript_region.visible_height - 1),
                    column,
                )
                return True, self.selected_transcript_text() or None
        return False, None

    def _toggle_tool_detail(self, index: int) -> None:
        if index >= len(self.state.records) or not isinstance(
            self.state.records[index], ToolExecutionRecord
        ):
            return
        key = self._tool_key(self.state.records[index])
        if key in self._expanded_tool_keys:
            self._expanded_tool_keys.remove(key)
        else:
            self._expanded_tool_keys.add(key)
        self._focused_tool_index = index
        self._focused_tool_key = key
        self._detail_anchor_revision = self.state.records_revision
        self._request_render("input")

    def _selection_bounds(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        if self._selection_anchor is None or self._selection_tip is None:
            return None
        return tuple(sorted((self._selection_anchor, self._selection_tip)))  # type: ignore[return-value]

    def _highlight_selected_row(self, row: int, text: str) -> str:
        bounds = self._selection_bounds()
        if bounds is None or not bounds[0][0] <= row <= bounds[1][0]:
            return text
        plain = strip_control_sequences(text)
        left = bounds[0][1] if row == bounds[0][0] else 0
        right = bounds[1][1] if row == bounds[1][0] else visible_width(plain)
        before = slice_by_column(plain, start=0, length=left, strict=False).text
        selected = slice_by_column(
            plain, start=left, length=max(0, right - left), strict=False
        ).text
        after = slice_by_column(
            plain,
            start=right,
            length=max(0, visible_width(plain) - right),
            strict=False,
        ).text
        return before + (f"\x1b[7m{selected}\x1b[27m" if selected else "") + after

    def _reset_transcript_interaction(self) -> None:
        self._expanded_tool_keys.clear()
        self._focused_tool_index = None
        self._focused_tool_key = None
        self._selection_anchor = self._selection_tip = None
        self._selection_revision = None
        self._mouse_press_control = None
        self._mouse_press_key = None
        self._mouse_press_position = None
        self._detail_anchor_revision = None

    @staticmethod
    def _tool_key(record: DisplayRecord) -> str | int:
        return (
            record.activity_id
            if isinstance(record, ToolExecutionRecord)
            and record.activity_id is not None
            else id(record)
        )

    def _refresh_tool_index_cache(self) -> None:
        revision = (
            self.state.records_revision,
            self.state.transcript_window_generation,
        )
        if revision == self._tool_index_cache_revision:
            return
        self._tool_key_to_index = {
            self._tool_key(record): index
            for index, record in enumerate(self.state.records)
            if isinstance(record, ToolExecutionRecord)
        }
        self._tool_index_cache_revision = revision

    def _refresh_context_usage(self) -> None:
        # Rebuilding a long session's context is synchronous and can stall
        # animation and input while a tool is running. Refresh after the run.
        if self.context_usage_provider is None or self.state.running:
            return
        refresh_key = (
            self.state.records_revision,
            self.state.transcript_window_generation,
        )
        if refresh_key == self._context_usage_refresh_key:
            return
        try:
            self.state.context_usage = self.context_usage_provider()
        except Exception:
            self.state.context_usage = None
        self._context_usage_refresh_key = refresh_key

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
