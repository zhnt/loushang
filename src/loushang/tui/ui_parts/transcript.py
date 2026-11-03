"""Generic incremental transcript region for full-screen terminal layouts."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from loushang.tui.core import (
    RenderConstraints,
    RenderLine,
    RenderLineSegment,
    RenderResult,
    SegmentedRenderLines,
)
from loushang.tui.markdown.renderer import MarkdownRenderCache
from loushang.tui.markdown.types import _MarkdownBlock
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    StreamingTextBuffer,
    ToolExecutionRecord,
    TranscriptView,
    WorkedDividerRecord,
    _prefix_streaming_assistant_segment,
    _render_streaming_assistant_markdown_segments,
)

DEFAULT_STABLE_TRANSCRIPT_CACHE_ENTRY_LIMIT = 128
_RECORD_SEPARATOR = RenderLine("")


class TranscriptPresentation(Protocol):
    """Project and decorate transcript records without owning render mechanics.

    ``cache_token`` is read on every frame and must be cheap, hashable, and
    stable until presentation output changes. The remaining hooks are cached
    across unchanged records and streaming segments. Assistant ``stable`` is
    render-cache lifecycle metadata and is normalized before these hooks; it is
    not a presentation semantic.
    """

    @property
    def cache_token(self) -> Hashable: ...

    def project_record(self, record: DisplayRecord, *, width: int) -> DisplayRecord: ...

    def record_render_width(
        self,
        record: DisplayRecord,
        *,
        width: int,
    ) -> int: ...

    def present_lines(
        self,
        lines: tuple[str, ...],
        record: DisplayRecord,
        *,
        width: int,
        theme: ThemeResolver | None,
        capabilities: Any | None,
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class NeutralTranscriptPresentation:
    """Preserve the generic TranscriptView result without product decoration."""

    @property
    def cache_token(self) -> None:
        return None

    def project_record(self, record: DisplayRecord, *, width: int) -> DisplayRecord:
        del width
        return record

    def record_render_width(
        self,
        record: DisplayRecord,
        *,
        width: int,
    ) -> int:
        del record
        return width

    def present_lines(
        self,
        lines: tuple[str, ...],
        record: DisplayRecord,
        *,
        width: int,
        theme: ThemeResolver | None,
        capabilities: Any | None,
    ) -> tuple[str, ...]:
        del record, width, theme, capabilities
        return lines


@dataclass(slots=True)
class TranscriptRegion:
    records: list[DisplayRecord] = field(default_factory=list)
    records_revision: int = 0
    draft: AssistantMessageRecord | None = None
    draft_buffer: StreamingTextBuffer | None = None
    theme: ThemeResolver | None = None
    capabilities: Any | None = None
    presentation: TranscriptPresentation = field(
        default_factory=NeutralTranscriptPresentation
    )
    window_generation: int = 0
    stable_cache_entry_limit: int = DEFAULT_STABLE_TRANSCRIPT_CACHE_ENTRY_LIMIT
    expanded_tool_indices: frozenset[int] = frozenset()
    focused_tool_index: int | None = None
    anchor_tool_index: int | None = None
    visible_controls: dict[int, int] = field(default_factory=dict, init=False)
    visible_height: int = field(default=0, init=False)
    _committed_control_rows: dict[int, int] = field(default_factory=dict, init=False)
    _committed_control_positions: tuple[int, ...] = field(default=(), init=False)
    _committed_control_by_index: dict[int, int] = field(
        default_factory=dict, init=False
    )
    _tail_start: int = field(default=0, init=False)
    _stable_line_cache: dict[
        tuple[DisplayRecord, int, tuple[object, ...]], tuple[str, ...]
    ] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _transient_line_cache_key: tuple[DisplayRecord, int, tuple[object, ...]] | None = (
        field(
            default=None,
            init=False,
            repr=False,
        )
    )
    _transient_line_cache_lines: tuple[str, ...] | None = field(
        default=None, init=False, repr=False
    )
    _transient_source_text: str = field(default="", init=False, repr=False)
    _transient_source_width: int = field(default=0, init=False, repr=False)
    _transient_source_style_signature: tuple[object, ...] | None = field(
        default=None, init=False, repr=False
    )
    _transient_source_buffer_id: int | None = field(
        default=None, init=False, repr=False
    )
    _transient_source_buffer_version: int = field(default=-1, init=False, repr=False)
    _markdown_render_cache: MarkdownRenderCache = field(
        default_factory=MarkdownRenderCache, init=False, repr=False
    )
    _cache_generation: int = field(default=-1, init=False, repr=False)
    _committed_segment_key: tuple[object, ...] | None = field(
        default=None, init=False, repr=False
    )
    _committed_segment: RenderLineSegment | None = field(
        default=None, init=False, repr=False
    )
    _committed_render_segments: tuple[RenderLineSegment, ...] = field(
        default=(), init=False, repr=False
    )
    _committed_render_lines: SegmentedRenderLines = field(
        default_factory=SegmentedRenderLines, init=False, repr=False
    )
    _committed_render_lines_segments: tuple[RenderLineSegment, ...] | None = field(
        default=None, init=False, repr=False
    )
    _committed_block_context: tuple[object, ...] | None = field(
        default=None, init=False, repr=False
    )
    _committed_record_blocks: tuple[
        tuple[DisplayRecord, bool, tuple[str, ...]], ...
    ] = field(default=(), init=False, repr=False)
    _committed_record_lines: tuple[tuple[RenderLine, ...], ...] = field(
        default=(), init=False, repr=False
    )
    _committed_record_segments: tuple[RenderLineSegment | None, ...] = field(
        default=(), init=False, repr=False
    )
    _committed_separator_rows: frozenset[int] = field(
        default_factory=frozenset,
        init=False,
        repr=False,
    )
    _draft_segments_key: tuple[object, ...] | None = field(
        default=None, init=False, repr=False
    )
    _draft_segments: tuple[RenderLineSegment, ...] = field(
        default=(), init=False, repr=False
    )
    _draft_stream_context: tuple[object, ...] | None = field(
        default=None, init=False, repr=False
    )
    _draft_stable_segment_cache: dict[tuple[object, ...], RenderLineSegment] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _draft_separator_identity: object = field(
        default_factory=object, init=False, repr=False
    )
    _draft_separator_segment: RenderLineSegment | None = field(
        default=None, init=False, repr=False
    )
    _draft_has_leading_separator: bool = field(default=False, init=False, repr=False)
    _segmented_transient_content_segments: tuple[RenderLineSegment, ...] = field(
        default=(),
        init=False,
        repr=False,
    )
    _segmented_transient_buffer_id: int | None = field(
        default=None, init=False, repr=False
    )
    _segmented_transient_buffer_version: int = field(default=-1, init=False, repr=False)
    _segmented_transient_width: int = field(default=0, init=False, repr=False)
    _segmented_transient_style_signature: tuple[object, ...] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @property
    def has_content(self) -> bool:
        return bool(
            self.records or self.draft is not None or self.draft_buffer is not None
        )

    def prepare_assistant_markdown(
        self, markdown: str, blocks: tuple[_MarkdownBlock, ...]
    ) -> None:
        self._markdown_render_cache.prepare_blocks(markdown, blocks)

    def prepare_assistant_markdown_render(
        self, key: tuple[object, ...], result: RenderResult
    ) -> None:
        self._markdown_render_cache.prepare_result(key, result)

    def clear_prepared_assistant_markdown_render(self) -> None:
        self._markdown_render_cache.clear_prepared_result()

    @property
    def has_prepared_assistant_markdown_render(self) -> bool:
        return self._markdown_render_cache.has_prepared_result

    def has_complete_streaming_draft(
        self,
        buffer: StreamingTextBuffer,
        *,
        width: int,
        theme: ThemeResolver,
        capabilities: Any | None,
    ) -> bool:
        style_signature = (
            *_transcript_style_signature(theme, capabilities),
            self.presentation.cache_token,
        )
        return (
            bool(self._segmented_transient_content_segments)
            and self._segmented_transient_buffer_id == id(buffer)
            and self._segmented_transient_buffer_version == buffer.version
            and self._segmented_transient_width == width
            and self._segmented_transient_style_signature == style_signature
        )

    def render(self, constraints: RenderConstraints) -> RenderResult:
        self._reset_cache_if_window_changed()
        style_signature = (
            *_transcript_style_signature(self.theme, self.capabilities),
            self.presentation.cache_token,
        )
        lines = self._render_tail_segments(
            max_height=constraints.max_height,
            width=constraints.width,
            style_signature=style_signature,
        )
        positions = self._committed_control_positions
        first = bisect_left(positions, self._tail_start)
        last = bisect_left(positions, self._tail_start + len(lines))
        self.visible_controls = {
            row - self._tail_start: self._committed_control_rows[row]
            for row in positions[first:last]
        }
        self.visible_height = len(lines)
        return RenderResult(lines=lines)

    def _render_record_lines(
        self,
        record: DisplayRecord | StreamingTextBuffer,
        *,
        width: int,
        style_signature: tuple[object, ...],
    ) -> tuple[str, ...]:
        if isinstance(record, StreamingTextBuffer):
            return self._render_streaming_buffer_lines(
                record, width=width, style_signature=style_signature
            )
        if isinstance(record, AssistantMessageRecord) and not record.stable:
            return self._render_transient_record_lines(
                record, width=width, style_signature=style_signature
            )

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
            markdown_streaming_key=buffer,
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
        if (
            key == self._transient_line_cache_key
            and self._transient_line_cache_lines is not None
        ):
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

    def _render_record_uncached(
        self,
        record: DisplayRecord,
        *,
        width: int,
        markdown_streaming_key: object | None = None,
    ) -> tuple[str, ...]:
        if isinstance(record, ToolExecutionRecord) and record.detail_expanded:
            record = replace(
                record,
                command=record.expanded_command
                if record.expanded_command is not None
                else record.command,
                output=record.expanded_output
                if record.expanded_output is not None
                else record.output,
            )
        display_record = _presentation_record(
            self.presentation.project_record(
                _presentation_record(record),
                width=width,
            )
        )
        render_width = self.presentation.record_render_width(
            display_record, width=width
        )
        render_record = display_record
        if (
            isinstance(record, AssistantMessageRecord)
            and not record.stable
            and isinstance(display_record, AssistantMessageRecord)
        ):
            render_record = replace(display_record, stable=False)
        view = TranscriptView(
            [render_record],
            theme=self.theme,
            capabilities=self.capabilities,
            markdown_cache=self._markdown_render_cache,
            markdown_streaming_key=markdown_streaming_key,
        )
        rendered = view.render(
            RenderConstraints(width=render_width, max_height=1_000_000)
        )
        return self.presentation.present_lines(
            tuple(line.text for line in rendered.lines),
            display_record,
            width=render_width,
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
        return [
            line.text
            for line in self._render_tail_segments(
                max_height=max_height,
                width=width,
                style_signature=style_signature,
            )
        ]

    def _render_tail_segments(
        self,
        *,
        max_height: int,
        width: int,
        style_signature: tuple[object, ...],
    ) -> SegmentedRenderLines:
        if max_height <= 0:
            self._tail_start = 0
            return SegmentedRenderLines()

        committed = self._render_committed_segment(
            width=width, style_signature=style_signature
        )
        draft_segments = self._render_draft_segments(
            width=width,
            style_signature=style_signature,
            has_committed=committed is not None,
        )
        if self._committed_render_lines_segments is not self._committed_render_segments:
            self._committed_render_lines = SegmentedRenderLines.from_segments(
                self._committed_render_segments
            )
            self._committed_render_lines_segments = self._committed_render_segments
        committed_lines = self._committed_render_lines
        draft_lines = SegmentedRenderLines.from_segments(draft_segments)
        committed_count = len(committed_lines)
        total_count = committed_count + len(draft_lines)
        if total_count <= max_height:
            self._tail_start = 0
            return SegmentedRenderLines.concat(committed_lines, draft_lines)

        start = total_count - max_height
        if self.anchor_tool_index is not None:
            anchor_row = self._committed_control_by_index.get(self.anchor_tool_index)
            if anchor_row is not None and not start <= anchor_row < start + max_height:
                start = max(
                    0, min(anchor_row - max_height + 1, total_count - max_height)
                )
        committed_rows = committed.line_count if committed is not None else 0
        starts_at_draft_separator = (
            committed is not None
            and bool(draft_segments)
            and self._draft_has_leading_separator
            and start == committed_rows
        )
        if start in self._committed_separator_rows or starts_at_draft_separator:
            start += 1
        self._tail_start = start
        stop = start + max_height
        visible_committed = committed_lines[start : min(stop, committed_count)]
        visible_draft = draft_lines[
            max(0, start - committed_count) : max(0, stop - committed_count)
        ]
        return SegmentedRenderLines.concat(visible_committed, visible_draft)

    def _render_committed_segment(
        self,
        *,
        width: int,
        style_signature: tuple[object, ...],
    ) -> RenderLineSegment | None:
        first_record_id = id(self.records[0]) if self.records else 0
        last_record_id = id(self.records[-1]) if self.records else 0
        key = (
            id(self.records),
            self.records_revision,
            len(self.records),
            first_record_id,
            last_record_id,
            self.window_generation,
            width,
            style_signature,
            self.expanded_tool_indices,
            self.focused_tool_index,
        )
        if key == self._committed_segment_key:
            return self._committed_segment

        # The small stable cache may evict old records in a long transcript.
        # Keep the blocks already used by the current committed segment so an
        # appended Worked divider does not render the entire history again.
        block_context = (
            id(self.records),
            self.window_generation,
            width,
            style_signature,
        )
        previous_blocks = (
            self._committed_record_blocks
            if block_context == self._committed_block_context
            else ()
        )
        # The final assistant and Worked divider normally arrive together
        # after the last streaming frame. Preserve the already rendered history
        # instead of rebuilding every line just to append that short suffix.
        appended_start = len(previous_blocks)
        appended = self.records[appended_start:]
        if (
            previous_blocks
            and self._committed_segment is not None
            and self._committed_segment_key is not None
            and self.expanded_tool_indices == self._committed_segment_key[-2]
            and self.focused_tool_index == self._committed_segment_key[-1]
            and appended
            and all(
                previous[0] is self.records[index]
                for index, previous in enumerate(previous_blocks)
            )
            and all(
                isinstance(record, (AssistantMessageRecord, WorkedDividerRecord))
                for record in appended
            )
        ):
            previous_render_segments = self._committed_render_segments
            lines = list(self._committed_segment.lines)
            append_separator_rows = set(self._committed_separator_rows)
            appended_blocks = []
            appended_line_blocks = []
            appended_segment_blocks: list[RenderLineSegment | None] = []
            for record in appended:
                block = self._render_record_lines(
                    record, width=width, style_signature=style_signature
                )
                appended_blocks.append((record, False, block))
                rendered_lines = tuple(RenderLine(row) for row in block)
                appended_line_blocks.append(rendered_lines)
                if block:
                    segment_lines = rendered_lines
                    if lines:
                        append_separator_rows.add(len(lines))
                        segment_lines = (_RECORD_SEPARATOR, *rendered_lines)
                    record_segment = RenderLineSegment(segment_lines)
                    appended_segment_blocks.append(record_segment)
                    lines.extend(segment_lines)
                else:
                    appended_segment_blocks.append(None)
            append_segment = RenderLineSegment(lines=tuple(lines), revision=key)
            self._committed_segment_key = key
            self._committed_segment = append_segment
            self._committed_render_segments = (
                *previous_render_segments,
                *(
                    segment
                    for segment in appended_segment_blocks
                    if segment is not None
                ),
            )
            self._committed_record_blocks = (*previous_blocks, *appended_blocks)
            self._committed_record_lines = (
                *self._committed_record_lines,
                *appended_line_blocks,
            )
            self._committed_record_segments = (
                *self._committed_record_segments,
                *appended_segment_blocks,
            )
            self._committed_separator_rows = frozenset(append_separator_rows)
            return append_segment

        current_blocks: list[tuple[DisplayRecord, bool, tuple[str, ...]]] = []
        current_line_blocks: list[tuple[RenderLine, ...]] = []
        current_segment_blocks: list[RenderLineSegment | None] = []
        rows: list[RenderLine] = []
        separator_rows: set[int] = set()
        controls: dict[int, int] = {}
        for index, record in enumerate(self.records):
            detail_available = isinstance(record, ToolExecutionRecord) and (
                record.expanded_command is not None
                or record.expanded_output is not None
            )
            expanded = detail_available and index in self.expanded_tool_indices
            display_record = (
                replace(record, detail_expanded=True)
                if expanded and isinstance(record, ToolExecutionRecord)
                else record
            )
            previous_record_reused = (
                0 <= index < len(previous_blocks)
                and previous_blocks[index][0] is record
                and previous_blocks[index][1] == expanded
            )
            if previous_record_reused:
                block = previous_blocks[index][2]
                rendered_lines = self._committed_record_lines[index]
            else:
                block = self._render_record_lines(
                    display_record, width=width, style_signature=style_signature
                )
                rendered_lines = tuple(RenderLine(row) for row in block)
            # Reallocating one tracked tuple per old record on each tool
            # chunk also causes full-history garbage-collection pauses.
            current_blocks.append(
                previous_blocks[index]
                if previous_record_reused
                else (record, expanded, block)
            )
            current_line_blocks.append(rendered_lines)
            if not block:
                current_segment_blocks.append(None)
                continue
            has_separator = bool(rows)
            control_text: str | None = None
            if detail_available:
                label = "Show Less" if expanded else "Show Detail"
                if index == self.focused_tool_index:
                    label = f"> {label} <"
                controls[len(rows) + int(has_separator) + len(rendered_lines)] = index
                control_text = f"  [{label}]"
            previous_segment = (
                self._committed_record_segments[index]
                if previous_record_reused
                else None
            )
            if (
                previous_segment is not None
                and (previous_segment.lines[0] is _RECORD_SEPARATOR) == has_separator
                and (
                    control_text is None
                    or previous_segment.lines[-1].text == control_text
                )
            ):
                record_segment = previous_segment
            else:
                segment_lines = (
                    (_RECORD_SEPARATOR, *rendered_lines)
                    if has_separator
                    else rendered_lines
                )
                if control_text is not None:
                    segment_lines = (*segment_lines, RenderLine(control_text))
                record_segment = RenderLineSegment(segment_lines)
            if has_separator:
                separator_rows.add(len(rows))
            rows.extend(record_segment.lines)
            current_segment_blocks.append(record_segment)
        segment = (
            RenderLineSegment(
                lines=tuple(rows),
                revision=key,
            )
            if rows
            else None
        )
        self._committed_segment_key = key
        self._committed_segment = segment
        self._committed_render_segments = tuple(
            segment for segment in current_segment_blocks if segment is not None
        )
        self._committed_block_context = block_context
        self._committed_record_blocks = tuple(current_blocks)
        self._committed_record_lines = tuple(current_line_blocks)
        self._committed_record_segments = tuple(current_segment_blocks)
        self._committed_separator_rows = frozenset(separator_rows)
        self._committed_control_rows = controls
        self._committed_control_positions = tuple(controls)
        self._committed_control_by_index = {
            index: row for row, index in controls.items()
        }
        return segment

    def _render_draft_segments(
        self,
        *,
        width: int,
        style_signature: tuple[object, ...],
        has_committed: bool,
    ) -> tuple[RenderLineSegment, ...]:
        draft: DisplayRecord | StreamingTextBuffer | None = (
            self.draft_buffer or self.draft
        )
        if draft is None:
            self._clear_draft_segment_cache()
            return ()
        source_revision: object
        if isinstance(draft, StreamingTextBuffer):
            source_revision = (id(draft), draft.version)
        else:
            source_revision = draft
        key = (
            source_revision,
            has_committed,
            self.window_generation,
            width,
            style_signature,
        )
        if key == self._draft_segments_key:
            return self._draft_segments

        if isinstance(draft, StreamingTextBuffer):
            segmented = self._render_streaming_draft_segments(
                draft,
                width=width,
                style_signature=style_signature,
                has_committed=has_committed,
            )
            if segmented is not None:
                self._draft_segments_key = key
                self._draft_segments = segmented
                return segmented

        block = self._render_record_lines(
            draft, width=width, style_signature=style_signature
        )
        rows = ("", *block) if has_committed and block else block
        segment = (
            RenderLineSegment(
                lines=tuple(RenderLine(row) for row in rows),
                revision=key,
            )
            if rows
            else None
        )
        segments = (segment,) if segment is not None else ()
        self._draft_segments_key = key
        self._draft_segments = segments
        self._draft_has_leading_separator = bool(has_committed and block)
        self._segmented_transient_content_segments = ()
        self._segmented_transient_buffer_id = None
        self._segmented_transient_buffer_version = -1
        return segments

    def _render_streaming_draft_segments(
        self,
        buffer: StreamingTextBuffer,
        *,
        width: int,
        style_signature: tuple[object, ...],
        has_committed: bool,
    ) -> tuple[RenderLineSegment, ...] | None:
        source_record = _presentation_record(
            AssistantMessageRecord(
                _streaming_buffer_render_text(buffer),
                stable=False,
            )
        )
        display_record = _presentation_record(
            self.presentation.project_record(source_record, width=width)
        )
        if not isinstance(display_record, AssistantMessageRecord):
            return None
        render_width = self.presentation.record_render_width(
            display_record,
            width=width,
        )
        stream_context = (
            id(buffer),
            self.window_generation,
            render_width,
            style_signature,
        )
        if stream_context != self._draft_stream_context:
            self._draft_stream_context = stream_context
            self._draft_stable_segment_cache.clear()
            self._draft_separator_segment = None

        rendered = _render_streaming_assistant_markdown_segments(
            display_record.text,
            width=render_width,
            theme=self.theme,
            capabilities=self.capabilities,
            code_highlighter=None,
            markdown_cache=self._markdown_render_cache,
            markdown_streaming_key=buffer,
        )
        if rendered is None:
            self._draft_stable_segment_cache.clear()
            self._draft_separator_segment = None
            self._segmented_transient_content_segments = ()
            self._segmented_transient_buffer_id = None
            self._segmented_transient_buffer_version = -1
            return None

        content_segments: list[RenderLineSegment] = []
        first_prefix_available = True
        for markdown_segment in rendered.segments:
            has_nonblank = markdown_segment.has_nonblank
            use_first_prefix = first_prefix_available and has_nonblank
            if has_nonblank:
                first_prefix_available = False
            cache_key = (
                markdown_segment.identity,
                markdown_segment.revision,
                use_first_prefix,
            )
            segment = (
                self._draft_stable_segment_cache.get(cache_key)
                if markdown_segment.stable
                else None
            )
            if segment is None:
                prefixed = _prefix_streaming_assistant_segment(
                    markdown_segment.lines,
                    width=render_width,
                    use_first_prefix=use_first_prefix,
                )
                presented_lines = self.presentation.present_lines(
                    prefixed,
                    display_record,
                    width=render_width,
                    theme=self.theme,
                    capabilities=self.capabilities,
                )
                segment = RenderLineSegment(
                    lines=tuple(RenderLine(line) for line in presented_lines),
                    identity=("streaming-markdown", markdown_segment.identity),
                    revision=(
                        markdown_segment.revision,
                        use_first_prefix,
                        render_width,
                        style_signature,
                    ),
                )
                if markdown_segment.stable:
                    self._draft_stable_segment_cache[cache_key] = segment
            content_segments.append(segment)

        content = tuple(content_segments)
        segments: tuple[RenderLineSegment, ...] = content
        if has_committed and content:
            if self._draft_separator_segment is None:
                self._draft_separator_segment = RenderLineSegment(
                    lines=(RenderLine(""),),
                    identity=self._draft_separator_identity,
                    revision=stream_context,
                )
            segments = (self._draft_separator_segment, *content)
        self._draft_has_leading_separator = bool(has_committed and content)

        self._segmented_transient_content_segments = content
        self._segmented_transient_buffer_id = id(buffer)
        self._segmented_transient_buffer_version = buffer.version
        self._segmented_transient_width = width
        self._segmented_transient_style_signature = style_signature
        return segments

    def _clear_draft_segment_cache(self) -> None:
        self._draft_segments_key = None
        self._draft_segments = ()
        self._draft_stream_context = None
        self._draft_stable_segment_cache.clear()
        self._draft_separator_segment = None
        self._draft_has_leading_separator = False
        self._segmented_transient_content_segments = ()
        self._segmented_transient_buffer_id = None
        self._segmented_transient_buffer_version = -1
        self._segmented_transient_width = 0
        self._segmented_transient_style_signature = None

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
        self._committed_segment_key = None
        self._committed_segment = None
        self._committed_render_segments = ()
        self._committed_render_lines = SegmentedRenderLines()
        self._committed_render_lines_segments = None
        self._committed_block_context = None
        self._committed_record_blocks = ()
        self._committed_record_lines = ()
        self._committed_record_segments = ()
        self._committed_separator_rows = frozenset()
        self._clear_draft_segment_cache()
        self._cache_generation = self.window_generation

    def clear_transient_cache(self) -> None:
        self._transient_line_cache_key = None
        self._transient_line_cache_lines = None
        self._transient_source_text = ""
        self._transient_source_width = 0
        self._transient_source_style_signature = None
        self._transient_source_buffer_id = None
        self._transient_source_buffer_version = -1
        self._clear_draft_segment_cache()
        self._markdown_render_cache.clear_streaming()

    def promote_transient_cache(
        self,
        record: AssistantMessageRecord,
        *,
        source_buffer: StreamingTextBuffer | None = None,
    ) -> None:
        if source_buffer is not None and self._segmented_transient_content_segments:
            if self._segmented_transient_buffer_id != id(source_buffer):
                return
            if record.text != source_buffer.text:
                return
            if (
                self._segmented_transient_width <= 0
                or self._segmented_transient_style_signature is None
            ):
                return
            if self._segmented_transient_buffer_version != source_buffer.version:
                # The final delta can arrive after the last screen frame. Render
                # only that new streaming frontier before committing, preserving
                # the already completed segments instead of reparsing the answer.
                self._render_streaming_draft_segments(
                    source_buffer,
                    width=self._segmented_transient_width,
                    style_signature=self._segmented_transient_style_signature,
                    has_committed=self._draft_has_leading_separator,
                )
                if self._segmented_transient_buffer_version != source_buffer.version:
                    return
            canonical_lines = tuple(
                line.text
                for segment in self._segmented_transient_content_segments
                for line in segment.lines
            )
            self._stable_line_cache[
                (
                    record,
                    self._segmented_transient_width,
                    self._segmented_transient_style_signature,
                )
            ] = canonical_lines
            self._enforce_stable_cache_entry_limit()
            return
        if self._transient_line_cache_lines is None:
            return
        if source_buffer is None and record.text != self._transient_source_text:
            return
        if source_buffer is not None and self._transient_source_buffer_id != id(
            source_buffer
        ):
            return
        if (
            source_buffer is not None
            and self._transient_source_buffer_version != source_buffer.version
        ):
            return
        if (
            self._transient_source_width <= 0
            or self._transient_source_style_signature is None
        ):
            return
        canonical_lines = self._render_record_uncached(
            record, width=self._transient_source_width
        )
        self._stable_line_cache[
            (
                record,
                self._transient_source_width,
                self._transient_source_style_signature,
            )
        ] = canonical_lines
        self._enforce_stable_cache_entry_limit()

    def _enforce_stable_cache_entry_limit(self) -> None:
        limit = max(0, self.stable_cache_entry_limit)
        if limit == 0:
            self._stable_line_cache.clear()
            return
        while len(self._stable_line_cache) > limit:
            self._stable_line_cache.pop(next(iter(self._stable_line_cache)))


def _streaming_buffer_render_text(buffer: StreamingTextBuffer) -> str:
    return "\n".join(buffer.logical_lines())


def _presentation_record(record: DisplayRecord) -> DisplayRecord:
    if isinstance(record, AssistantMessageRecord) and not record.stable:
        return replace(record, stable=True)
    return record


def _transcript_style_signature(
    theme: ThemeResolver | None,
    capabilities: Any | None,
) -> tuple[object, ...]:
    capabilities_signature: tuple[bool, bool] | None = None
    if capabilities is not None:
        capabilities_signature = (
            bool(capabilities.truecolor),
            bool(capabilities.hyperlinks),
        )
    if theme is None:
        return (None, capabilities_signature)
    return (id(theme), theme.version, capabilities_signature)


__all__ = [
    "DEFAULT_STABLE_TRANSCRIPT_CACHE_ENTRY_LIMIT",
    "NeutralTranscriptPresentation",
    "TranscriptPresentation",
    "TranscriptRegion",
]
