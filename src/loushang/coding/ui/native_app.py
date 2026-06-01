from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from loushang.coding.tools.output_preview import (
    DEFAULT_TOOL_OUTPUT_PREVIEW_LINES,
    collapse_tool_output_preview,
    drop_tool_timing_tail_line,
    prefers_tail_tool_output,
)
from loushang.coding.ui.native_state import NativeCodingTuiState, NativeTranscriptWindow
from loushang.coding.ui.transcript_style import apply_coding_transcript_style
from loushang.tui import (
    BottomFrame,
    Composer,
    LoushangWelcomePanel,
    PendingQueueView,
    PendingSection,
    RenderConstraints,
    RenderLine,
    RenderRequestKind,
    RenderResult,
    ScreenLayout,
    StatusBar,
    StatusField,
    SurfaceHost,
    TerminalRuntimeCapabilities,
    WorkingLine,
    loushang_welcome_theme,
    theme_capabilities_from_runtime,
)
from loushang.tui.markdown.renderer import MarkdownRenderCache
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    ContextCompactionRecord,
    DisplayRecord,
    ErrorRecord,
    StreamingTextBuffer,
    ThinkingRecord,
    ToolExecutionRecord,
    TranscriptView,
    UserPromptRecord,
    WorkedDividerRecord,
)

ACTIVE_RENDER_INTERVAL_MS = 80
DEFAULT_ACTIVE_TRANSCRIPT_LINE_BUDGET = 320
DEFAULT_STABLE_RENDER_CACHE_ENTRY_LIMIT = 128


def _terminal_transcript_theme() -> ThemeResolver:
    return ThemeResolver(
        defaults={
            "markdown.heading": {"color": "yellow"},
            "markdown.link": {"color": "blue"},
            "markdown.link.url": {"color": "bright_black"},
            "markdown.code.inline": {"color": "cyan"},
            "markdown.code.block": {"color": "green"},
            "markdown.code.block.border": {"color": "bright_black"},
            "markdown.code.indent": {"text": ""},
            "markdown.quote.text": {"color": "bright_black"},
            "markdown.quote.border": {"color": "bright_black"},
            "markdown.hr": {"color": "bright_black"},
            "markdown.list.bullet": {"color": "green"},
            "transcript.divider": {"color": "bright_black", "dim": True},
            "transcript.error": {"color": "red"},
            "transcript.tool.action": {"color": "bright_cyan"},
            "transcript.tool.connector": {"color": "bright_black", "dim": True},
            "transcript.tool.error_marker": {"color": "red", "bold": True},
            "transcript.tool.flag": {"color": "bright_cyan"},
            "transcript.tool.marker": {"color": "bright_cyan", "bold": True},
            "transcript.tool.meta": {"color": "bright_black", "dim": True},
            "transcript.tool.verb": {"bold": True},
        }
    )


@dataclass(slots=True)
class NativeCodingTuiApp:
    model_label: str | None
    cwd: str
    branch: str | None
    session_label: str | None
    now: Callable[[], float] = time.monotonic
    composer: Composer = field(default_factory=lambda: Composer(prompt="› ", continuation_prompt="  "))
    state: NativeCodingTuiState = field(init=False)
    active_surface: Any | None = None
    surface_host: SurfaceHost | None = None
    transcript_theme: ThemeResolver = field(default_factory=_terminal_transcript_theme)
    welcome_theme: ThemeResolver | None = field(default_factory=loushang_welcome_theme)
    active_transcript_line_budget: int = DEFAULT_ACTIVE_TRANSCRIPT_LINE_BUDGET
    stable_render_cache_entry_limit: int = DEFAULT_STABLE_RENDER_CACHE_ENTRY_LIMIT
    render_requester: Callable[[RenderRequestKind], object] | None = None
    terminal_diagnostics_provider: Callable[[], str] | None = None
    terminal_capabilities: TerminalRuntimeCapabilities | None = None
    _transcript_region: _NativeTranscriptRegion = field(init=False, repr=False)
    _bottom_frame_component: BottomFrame = field(init=False, repr=False)
    _render_baseline_reset_reason: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.state = NativeCodingTuiState(
            model_label=self.model_label,
            cwd=self.cwd,
            branch=self.branch,
            session_label=self.session_label,
        )
        self._transcript_region = _NativeTranscriptRegion(theme=self.transcript_theme)
        self._bottom_frame_component = BottomFrame(composer=self.composer)

    def start_prompt(self, text: str, *, started_at: float | None = None) -> None:
        self.state.start_prompt(text, started_at=self.now() if started_at is None else started_at)
        self.composer.add_history(text)
        self.composer.clear()

    def start_pending_prompt(self, text: str, *, started_at: float | None = None) -> None:
        self.state.start_prompt(text, started_at=self.now() if started_at is None else started_at)
        self.composer.add_history(text)

    def begin_run(self, *, started_at: float | None = None) -> None:
        self.state.begin_run(started_at=self.now() if started_at is None else started_at)

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
        if isinstance(committed, AssistantMessageRecord) and committed.text == draft_text:
            self._transcript_region.promote_transient_cache(committed, source_buffer=draft_buffer)
        self._transcript_region.clear_transient_cache()

    def complete_run(self, *, elapsed_seconds: float | None = None) -> None:
        elapsed = self.elapsed_seconds() if elapsed_seconds is None else elapsed_seconds
        self.state.complete_run(elapsed_seconds=elapsed)
        self._transcript_region.clear_transient_cache()

    def queue_followup(self, text: str) -> None:
        self.state.queue_followup(text)

    def queue_steer(self, text: str) -> None:
        self.state.queue_steer(text)

    def sync_queues(self, *, steers: tuple[str, ...] | list[str], followups: tuple[str, ...] | list[str]) -> None:
        self.state.sync_queues(steers=steers, followups=followups)

    def set_status(self, message: str | None) -> None:
        self.state.set_status(message)
        self._request_render("product")

    def set_statusline_visible(self, visible: bool) -> None:
        self.state.statusline_visible = visible
        self._request_render("product")

    def add_error(self, summary: str, diagnostics: str = "") -> None:
        self.state.add_error(summary, diagnostics)
        self._request_render("product")

    def add_status(self, message: str) -> None:
        self.state.add_status(message)
        self._request_render("product")

    def replace_transcript_window(
        self,
        records: Iterable[DisplayRecord] | NativeTranscriptWindow,
        *,
        evicted_prefix_record_count: int = 0,
        reason: str = "replace",
    ) -> None:
        self.state.replace_transcript_window(
            records,
            evicted_prefix_record_count=evicted_prefix_record_count,
        )
        self._render_baseline_reset_reason = f"transcript_window_replaced:{reason}" if reason else "transcript_window_replaced"

    def compact_transcript_window(self, *, summary: str, max_records: int = 80) -> None:
        summary_record = AssistantMessageRecord(f"Compacted summary:\n\n{summary.strip()}")
        active_records = tuple(self.state.records)
        keep_count = max(0, max_records - 1)
        kept_records = active_records[-keep_count:] if keep_count else ()
        evicted_count = max(0, len(active_records) - len(kept_records))
        self.replace_transcript_window(
            (summary_record, *kept_records),
            evicted_prefix_record_count=self.state.evicted_prefix_record_count + evicted_count,
            reason="compaction",
        )

    def append_context_compaction_record(
        self,
        *,
        summary: str = "",
        tokens_before: int | None = None,
        max_records: int = 80,
    ) -> None:
        self.state.records.append(ContextCompactionRecord(summary=summary, tokens_before=tokens_before))
        evicted = self.state.trim_transcript_prefix(max_records=max_records)
        if evicted:
            self._render_baseline_reset_reason = "transcript_window_trimmed:context_compaction"

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
        editor_height = 16 if self._expanded_bottom_frame() else 12
        editor_height = max(1, min(editor_height, visible_height))
        self._transcript_region.records = self.state.records
        self._transcript_region.draft = None
        self._transcript_region.draft_buffer = self.state.assistant_draft_buffer
        self._transcript_region.cwd = self.state.cwd
        self._transcript_region.theme = self.transcript_theme
        self._transcript_region.capabilities = (
            theme_capabilities_from_runtime(self.terminal_capabilities) if self.terminal_capabilities is not None else None
        )
        self._transcript_region.window_generation = self.state.transcript_window_generation
        self._transcript_region.stable_cache_entry_limit = self.stable_render_cache_entry_limit
        layout = ScreenLayout(
            transcript=self._transcript_region,
            editor=_CappedRenderable(self._bottom_frame(), max_height=editor_height),
            editor_min_height=editor_height,
        )
        return layout.render(constraints)

    def startup_welcome_panel(self) -> LoushangWelcomePanel:
        return LoushangWelcomePanel(
            directory=self.state.cwd,
            session=self.state.session_label or "",
            model=self.state.model_label or "",
            theme=self.welcome_theme,
        )

    def trim_active_transcript_window(self) -> None:
        records, evicted_count, changed = _trim_records_to_line_budget(
            tuple(self.state.records),
            line_budget=self.active_transcript_line_budget,
        )
        if not changed:
            return
        self.state.replace_transcript_window(
            NativeTranscriptWindow(
                records=records,
                evicted_prefix_record_count=self.state.evicted_prefix_record_count + evicted_count,
            )
        )
        self._render_baseline_reset_reason = "transcript_window_trimmed:active_line_budget"

    def _expanded_bottom_frame(self) -> bool:
        return (
            self.active_surface is not None
            or self.state.running
            or bool(self.state.pending_steers)
            or bool(self.state.pending_followups)
            or bool(self.state.interruption_message)
        )

    def _request_render(self, kind: RenderRequestKind) -> None:
        if self.render_requester is not None:
            self.render_requester(kind)

    def _bottom_frame(self) -> BottomFrame:
        self._bottom_frame_component.composer = self.composer
        self._bottom_frame_component.surface = self.active_surface
        self._bottom_frame_component.working_line = self._working_line()
        self._bottom_frame_component.pending_queue = self._pending_queue()
        self._bottom_frame_component.status_bar = self._status_bar() if self.state.statusline_visible else None
        return self._bottom_frame_component

    def _working_line(self) -> WorkingLine | None:
        if not self.state.running:
            return None
        return WorkingLine(label="Working", elapsed_seconds=self.elapsed_seconds())

    def _pending_queue(self) -> PendingQueueView | None:
        sections: list[PendingSection] = []
        if self.state.interruption_message:
            sections.append(
                PendingSection(
                    label=self.state.interruption_message,
                    marker="■",
                    show_when_empty=True,
                )
            )
        if self.state.pending_steers:
            sections.append(
                PendingSection(
                    label="Messages to be submitted after next tool call",
                    items=tuple(self.state.pending_steers),
                    hint="press esc to interrupt and send immediately",
                    hint_placement="header",
                )
            )
        if self.state.pending_followups:
            sections.append(
                PendingSection(
                    label="Queued follow-up inputs",
                    items=tuple(self.state.pending_followups),
                    hint="alt + ↑ edit last queued message",
                )
            )
        if not sections:
            return None
        return PendingQueueView(sections=tuple(sections))

    def _status_bar(self) -> StatusBar:
        status = "running" if self.state.running else "idle"
        fields = [
            StatusField(self.state.model_label or "model", priority=100),
            StatusField(_cwd_label(self.state.cwd), priority=90),
            StatusField(self.state.branch or "no-branch", priority=80),
            StatusField(self.state.session_label or "no-session", priority=70),
            StatusField(status, priority=60),
        ]
        if self.state.pending_followups or self.state.pending_steers:
            fields.append(
                StatusField(
                    f"queued={len(self.state.pending_followups)} steer={len(self.state.pending_steers)}",
                    priority=50,
                )
            )
        if self.state.status_message:
            fields.append(StatusField(self.state.status_message, priority=40))
        return StatusBar(fields)


@dataclass(slots=True)
class _NativeTranscriptRegion:
    records: list[DisplayRecord] = field(default_factory=list)
    draft: AssistantMessageRecord | None = None
    draft_buffer: StreamingTextBuffer | None = None
    cwd: str = ""
    theme: ThemeResolver | None = None
    capabilities: Any | None = None
    window_generation: int = 0
    stable_cache_entry_limit: int = DEFAULT_STABLE_RENDER_CACHE_ENTRY_LIMIT
    _stable_line_cache: dict[tuple[DisplayRecord, int, tuple[object, ...]], tuple[str, ...]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _transient_line_cache_key: tuple[DisplayRecord, int, tuple[object, ...]] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _transient_line_cache_lines: tuple[str, ...] | None = field(default=None, init=False, repr=False)
    _transient_source_text: str = field(default="", init=False, repr=False)
    _transient_source_width: int = field(default=0, init=False, repr=False)
    _transient_source_style_signature: tuple[object, ...] | None = field(default=None, init=False, repr=False)
    _transient_source_buffer_id: int | None = field(default=None, init=False, repr=False)
    _transient_source_buffer_version: int = field(default=-1, init=False, repr=False)
    _markdown_render_cache: MarkdownRenderCache = field(default_factory=MarkdownRenderCache, init=False, repr=False)
    _cache_generation: int = field(default=-1, init=False, repr=False)

    @property
    def has_content(self) -> bool:
        return bool(self.records or self.draft is not None or self.draft_buffer is not None)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        self._reset_cache_if_window_changed()
        style_signature = (*_native_transcript_style_signature(self.theme, self.capabilities), self.cwd)
        rows = self._render_tail_rows(
            max_height=constraints.max_height,
            width=constraints.width,
            style_signature=style_signature,
        )
        return RenderResult(lines=tuple(RenderLine(line) for line in rows))

    def _render_record_lines(
        self,
        record: DisplayRecord | StreamingTextBuffer,
        *,
        width: int,
        style_signature: tuple[object, ...],
    ) -> tuple[str, ...]:
        if isinstance(record, StreamingTextBuffer):
            return self._render_streaming_buffer_lines(record, width=width, style_signature=style_signature)
        if isinstance(record, AssistantMessageRecord) and not record.stable:
            return self._render_transient_record_lines(record, width=width, style_signature=style_signature)

        key = (record, width, style_signature)
        cached = self._stable_line_cache.get(key)
        if cached is not None:
            return cached
        rendered = self._render_record_uncached(record, width=width)
        self._stable_line_cache[key] = rendered
        self._enforce_stable_cache_entry_limit()
        return rendered

    def _render_streaming_buffer_lines(
        self,
        buffer: StreamingTextBuffer,
        *,
        width: int,
        style_signature: tuple[object, ...],
    ) -> tuple[str, ...]:
        if (
            self._transient_line_cache_lines is not None
            and self._transient_source_width == width
            and self._transient_source_style_signature == style_signature
            and self._transient_source_buffer_id == id(buffer)
            and self._transient_source_buffer_version == buffer.version
        ):
            return self._transient_line_cache_lines

        rendered = self._render_record_uncached(
            AssistantMessageRecord(_streaming_buffer_render_text(buffer), stable=False),
            width=width,
        )
        self._remember_streaming_buffer_cache(
            buffer,
            width=width,
            style_signature=style_signature,
            lines=rendered,
        )
        return rendered

    def _render_transient_record_lines(
        self,
        record: AssistantMessageRecord,
        *,
        width: int,
        style_signature: tuple[object, ...],
    ) -> tuple[str, ...]:
        key = (record, width, style_signature)
        if key == self._transient_line_cache_key and self._transient_line_cache_lines is not None:
            return self._transient_line_cache_lines

        rendered = self._render_record_uncached(record, width=width)
        self._transient_line_cache_key = key
        self._transient_line_cache_lines = rendered
        self._transient_source_text = record.text
        self._transient_source_width = width
        self._transient_source_style_signature = style_signature
        self._transient_source_buffer_id = None
        self._transient_source_buffer_version = -1
        return rendered

    def _render_record_uncached(self, record: DisplayRecord, *, width: int) -> tuple[str, ...]:
        display_record = _native_coding_display_record(record, cwd=self.cwd)
        render_width = _native_transcript_record_render_width(display_record, width=width)
        view = TranscriptView(
            [display_record],
            theme=self.theme,
            capabilities=self.capabilities,
            markdown_cache=self._markdown_render_cache,
        )
        rendered = view.render(RenderConstraints(width=render_width, max_height=1_000_000))
        return _coding_lines(
            tuple(line.text for line in rendered.lines),
            display_record,
            theme=self.theme,
            capabilities=self.capabilities,
        )

    def _remember_streaming_buffer_cache(
        self,
        buffer: StreamingTextBuffer,
        *,
        width: int,
        style_signature: tuple[object, ...],
        lines: tuple[str, ...],
    ) -> None:
        self._transient_line_cache_key = None
        self._transient_line_cache_lines = lines
        self._transient_source_text = ""
        self._transient_source_width = width
        self._transient_source_style_signature = style_signature
        self._transient_source_buffer_id = id(buffer)
        self._transient_source_buffer_version = buffer.version

    def _render_tail_rows(
        self,
        *,
        max_height: int,
        width: int,
        style_signature: tuple[object, ...],
    ) -> list[str]:
        if max_height <= 0:
            return []
        newest_first_blocks: list[tuple[str, ...]] = []
        used_rows = 0
        for record in reversed(tuple(self._iter_records())):
            block = self._render_record_lines(record, width=width, style_signature=style_signature)
            if not block:
                continue
            separator_rows = 1 if newest_first_blocks else 0
            available = max_height - used_rows - separator_rows
            if available <= 0:
                break
            if len(block) > available:
                block = block[-available:]
            newest_first_blocks.append(block)
            used_rows += separator_rows + len(block)
            if used_rows >= max_height:
                break

        rows: list[str] = []
        for block in reversed(newest_first_blocks):
            if rows:
                rows.append("")
            rows.extend(block)
        return rows[-max_height:]

    def _iter_records(self) -> Iterable[DisplayRecord | StreamingTextBuffer]:
        yield from self.records
        if self.draft_buffer is not None:
            yield self.draft_buffer
        elif self.draft is not None:
            yield self.draft

    def _reset_cache_if_window_changed(self) -> None:
        if self._cache_generation == self.window_generation:
            return
        self._stable_line_cache.clear()
        self._transient_line_cache_key = None
        self._transient_line_cache_lines = None
        self._markdown_render_cache.clear()
        self._cache_generation = self.window_generation

    def clear_transient_cache(self) -> None:
        self._transient_line_cache_key = None
        self._transient_line_cache_lines = None
        self._transient_source_text = ""
        self._transient_source_width = 0
        self._transient_source_style_signature = None
        self._transient_source_buffer_id = None
        self._transient_source_buffer_version = -1

    def promote_transient_cache(
        self,
        record: AssistantMessageRecord,
        *,
        source_buffer: StreamingTextBuffer | None = None,
    ) -> None:
        if self._transient_line_cache_lines is None:
            return
        if source_buffer is None and record.text != self._transient_source_text:
            return
        if source_buffer is not None and self._transient_source_buffer_id != id(source_buffer):
            return
        if source_buffer is not None and self._transient_source_buffer_version != source_buffer.version:
            return
        if self._transient_source_width <= 0 or self._transient_source_style_signature is None:
            return
        self._stable_line_cache[
            (record, self._transient_source_width, self._transient_source_style_signature)
        ] = self._transient_line_cache_lines
        self._enforce_stable_cache_entry_limit()

    def _enforce_stable_cache_entry_limit(self) -> None:
        limit = max(0, self.stable_cache_entry_limit)
        if limit == 0:
            self._stable_line_cache.clear()
            return
        while len(self._stable_line_cache) > limit:
            self._stable_line_cache.pop(next(iter(self._stable_line_cache)))


@dataclass(frozen=True, slots=True)
class _CappedRenderable:
    renderable: Any
    max_height: int

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return self.renderable.render(
            RenderConstraints(
                width=constraints.width,
                max_height=max(1, min(self.max_height, constraints.max_height)),
                visible_height=constraints.visible_height,
            )
        )


def _coding_line(
    line: str,
    record: DisplayRecord,
    *,
    theme: ThemeResolver | None,
    capabilities: Any | None,
) -> str:
    if isinstance(record, UserPromptRecord) and line.startswith("> "):
        line = "› " + line[2:]
        return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)
    if isinstance(record, AssistantMessageRecord) and line.startswith("* "):
        line = "• " + line[2:]
        return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)
    if isinstance(record, ErrorRecord) and line.startswith("! Error: "):
        line = "■ Error: " + line[len("! Error: ") :]
        return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)
    if isinstance(record, ContextCompactionRecord) and line.startswith("* "):
        line = "• " + line[2:]
        return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)
    if isinstance(record, ToolExecutionRecord):
        if line.startswith("- Ran "):
            line = "• Ran " + line[len("- Ran ") :]
            return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)
        if line.startswith("! Ran "):
            line = "■ Ran " + line[len("! Ran ") :]
            return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)
        return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)
    if isinstance(record, WorkedDividerRecord) and line.startswith("- Worked for "):
        line = line.replace("-", "─", 1).replace("-", "─")
        return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)
    return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)


def _native_coding_display_record(record: DisplayRecord, *, cwd: str = "") -> DisplayRecord:
    if not isinstance(record, ToolExecutionRecord):
        return record
    name = _compact_display_paths(record.name, cwd=cwd)
    command = "" if _tool_command_duplicates_heading(record) else record.command
    output = drop_tool_timing_tail_line(record.output)
    if record.output_kind == "text":
        output = collapse_tool_output_preview(
            output,
            max_lines=DEFAULT_TOOL_OUTPUT_PREVIEW_LINES,
            tail=prefers_tail_tool_output(name),
        )
    if name == record.name and command == record.command and output == record.output:
        return record
    return replace(record, name=name, command=command, output=output)


def _tool_command_duplicates_heading(record: ToolExecutionRecord) -> bool:
    if not record.command:
        return False
    return _normalize_tool_text(record.command) == _normalize_tool_text(record.name)


def _normalize_tool_text(text: str) -> str:
    return " ".join(text.strip().split())


_ABSOLUTE_PATH_RE = re.compile(r"(?P<prefix>^|[\s\"'=])(?P<path>/[^\s\"']+)")


def _compact_display_paths(text: str, *, cwd: str) -> str:
    home = _normalized_path(os.path.expanduser("~"))
    normalized_cwd = _normalized_path(cwd)

    def replace_path(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        path = match.group("path")
        return prefix + _compact_absolute_path(path, cwd=normalized_cwd, home=home)

    return _ABSOLUTE_PATH_RE.sub(replace_path, text)


def _compact_absolute_path(path: str, *, cwd: str, home: str) -> str:
    if cwd and cwd != "/" and (path == cwd or path.startswith(f"{cwd}/")):
        relative = path[len(cwd) :].lstrip("/")
        return relative or "."
    if home and home != "/" and (path == home or path.startswith(f"{home}/")):
        return "~" + path[len(home) :]
    return path


def _normalized_path(path: str) -> str:
    normalized = path.rstrip("/")
    return normalized or path


def _coding_lines(
    lines: tuple[str, ...],
    record: DisplayRecord,
    *,
    theme: ThemeResolver | None,
    capabilities: Any | None,
) -> tuple[str, ...]:
    if not isinstance(record, ToolExecutionRecord):
        return tuple(_coding_line(line, record, theme=theme, capabilities=capabilities) for line in lines)

    rendered: list[str] = []
    output_started = False
    for line in lines:
        if line.startswith("- Ran ") or line.startswith("! Ran "):
            rendered.append(_coding_line(line, record, theme=theme, capabilities=capabilities))
            continue
        if line.startswith("  $ "):
            rendered.append(_style_tool_body_line(f"  │ {line[2:]}", record, theme=theme, capabilities=capabilities))
            continue
        if line.startswith("  "):
            content = line[2:]
            prefix = "  └ " if not output_started else "    "
            output_started = True
            rendered.append(_style_tool_body_line(f"{prefix}{content}", record, theme=theme, capabilities=capabilities))
            continue
        rendered.append(_coding_line(line, record, theme=theme, capabilities=capabilities))
    return tuple(rendered)


def _style_tool_body_line(
    line: str,
    record: ToolExecutionRecord,
    *,
    theme: ThemeResolver | None,
    capabilities: Any | None,
) -> str:
    return apply_coding_transcript_style(line, record, theme=theme, capabilities=capabilities)


def _native_transcript_record_render_width(record: DisplayRecord, *, width: int) -> int:
    if isinstance(record, ToolExecutionRecord):
        return max(1, width - 2)
    return width


def _streaming_buffer_render_text(buffer: StreamingTextBuffer) -> str:
    return "\n".join(buffer.logical_lines())


def _native_transcript_style_signature(theme: ThemeResolver | None, capabilities: Any | None) -> tuple[object, ...]:
    capabilities_signature: tuple[bool, bool] | None = None
    if capabilities is not None:
        capabilities_signature = (bool(capabilities.truecolor), bool(capabilities.hyperlinks))
    if theme is None:
        return (None, capabilities_signature)
    return (id(theme), theme.version, capabilities_signature)


def _trim_records_to_line_budget(
    records: tuple[DisplayRecord, ...],
    *,
    line_budget: int,
) -> tuple[tuple[DisplayRecord, ...], int, bool]:
    line_budget = max(0, line_budget)
    if not records or line_budget <= 0:
        return (), len(records), bool(records)

    kept_newest_first: list[DisplayRecord] = []
    used_lines = 0
    fully_evicted_count = 0
    changed = False

    for index in range(len(records) - 1, -1, -1):
        record = records[index]
        separator_lines = 1 if kept_newest_first else 0
        available = line_budget - used_lines - separator_lines
        if available <= 0:
            fully_evicted_count = index + 1
            changed = True
            break

        record_lines = _record_logical_line_count(record)
        if record_lines <= available:
            kept_newest_first.append(record)
            used_lines += separator_lines + record_lines
            continue

        trimmed = _tail_trim_record(record, max_lines=available)
        if trimmed is not None:
            kept_newest_first.append(trimmed)
            used_lines += separator_lines + _record_logical_line_count(trimmed)
            fully_evicted_count = index
        else:
            fully_evicted_count = index + 1
        changed = True
        break

    kept_records = tuple(reversed(kept_newest_first))
    if not changed and len(kept_records) == len(records):
        return records, 0, False
    return kept_records, fully_evicted_count, True


def _record_logical_line_count(record: DisplayRecord) -> int:
    if isinstance(record, UserPromptRecord | AssistantMessageRecord | ThinkingRecord):
        return _text_line_count(record.text)
    if isinstance(record, ToolExecutionRecord):
        count = 1
        if record.command:
            count += _text_line_count(record.command)
        if record.output:
            count += _text_line_count(record.output)
        if record.stderr:
            count += _text_line_count(record.stderr)
        if record.exit_code is not None:
            count += 1
        return count
    if isinstance(record, ErrorRecord):
        return 1 + (_text_line_count(record.diagnostics) if record.diagnostics else 0)
    return 1


def _text_line_count(text: str) -> int:
    if not text:
        return 1
    return max(1, text.count("\n") + (0 if text.endswith("\n") else 1))


def _tail_trim_record(record: DisplayRecord, *, max_lines: int) -> DisplayRecord | None:
    if max_lines <= 0:
        return None
    if isinstance(record, UserPromptRecord):
        return UserPromptRecord(
            _tail_trim_text(
                record.text,
                max_lines=max_lines,
                marker="[older prompt content omitted from active UI window]",
            )
        )
    if isinstance(record, AssistantMessageRecord):
        return AssistantMessageRecord(
            _tail_trim_text(
                record.text,
                max_lines=max_lines,
                marker="[older assistant output omitted from active UI window]",
            ),
            stable=record.stable,
        )
    if isinstance(record, ThinkingRecord):
        return replace(
            record,
            text=_tail_trim_text(
                record.text,
                max_lines=max_lines,
                marker="[older thinking content omitted from active UI window]",
            ),
        )
    if isinstance(record, ErrorRecord):
        if max_lines <= 1 or not record.diagnostics:
            return ErrorRecord("[older error details omitted from active UI window]")
        return replace(
            record,
            diagnostics=_tail_trim_text(
                record.diagnostics,
                max_lines=max_lines - 1,
                marker="[older error diagnostics omitted from active UI window]",
            ),
        )
    if isinstance(record, ToolExecutionRecord):
        return _tail_trim_tool_record(record, max_lines=max_lines)
    return None


def _tail_trim_tool_record(record: ToolExecutionRecord, *, max_lines: int) -> ToolExecutionRecord | None:
    output_budget = max_lines - 1
    if record.command:
        output_budget -= _text_line_count(record.command)
    if record.stderr:
        output_budget -= _text_line_count(record.stderr)
    if record.exit_code is not None:
        output_budget -= 1
    if output_budget <= 0:
        if max_lines <= 1:
            return None
        return replace(record, output="[older tool output omitted from active UI window]", stderr="", command="")
    return replace(
        record,
        output=_tail_trim_text(
            record.output,
            max_lines=output_budget,
            marker="[older tool output omitted from active UI window]",
        ),
    )


def _tail_trim_text(text: str, *, max_lines: int, marker: str) -> str:
    if max_lines <= 1:
        return marker
    if _text_line_count(text) <= max_lines:
        return text
    lines = text.rstrip("\n").rsplit("\n", max_lines - 1)
    return "\n".join([marker, *lines[-(max_lines - 1) :]])


def _cwd_label(cwd: str) -> str:
    if not cwd:
        return "cwd"
    return cwd.rstrip("/").rsplit("/", 1)[-1] or cwd


__all__ = ["NativeCodingTuiApp"]
