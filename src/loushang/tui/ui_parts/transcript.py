"""Generic incremental transcript region for full-screen terminal layouts."""

from __future__ import annotations

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
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    StreamingTextBuffer,
    TranscriptView,
    _prefix_streaming_assistant_segment,
    _render_streaming_assistant_markdown_segments,
)

DEFAULT_STABLE_TRANSCRIPT_CACHE_ENTRY_LIMIT = 128


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

    def project_record(self, record: DisplayRecord) -> DisplayRecord: ...

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
        theme: ThemeResolver | None,
        capabilities: Any | None,
    ) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class NeutralTranscriptPresentation:
    """Preserve the generic TranscriptView result without product decoration."""

    @property
    def cache_token(self) -> None:
        return None

    def project_record(self, record: DisplayRecord) -> DisplayRecord:
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
        theme: ThemeResolver | None,
        capabilities: Any | None,
    ) -> tuple[str, ...]:
        del record, theme, capabilities
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
        display_record = _presentation_record(
            self.presentation.project_record(_presentation_record(record))
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
            return SegmentedRenderLines()

        committed = self._render_committed_segment(
            width=width, style_signature=style_signature
        )
        draft_segments = self._render_draft_segments(
            width=width,
            style_signature=style_signature,
            has_committed=committed is not None,
        )
        segments = (
            *((committed,) if committed is not None else ()),
            *draft_segments,
        )
        lines = SegmentedRenderLines.from_segments(segments)
        if len(lines) <= max_height:
            return lines

        start = len(lines) - max_height
        committed_rows = committed.line_count if committed is not None else 0
        starts_at_draft_separator = (
            committed is not None
            and bool(draft_segments)
            and self._draft_has_leading_separator
            and start == committed_rows
        )
        if start in self._committed_separator_rows or starts_at_draft_separator:
            start += 1
        return lines[start:]

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
        )
        if key == self._committed_segment_key:
            return self._committed_segment

        rows: list[str] = []
        separator_rows: set[int] = set()
        for record in self.records:
            block = self._render_record_lines(
                record, width=width, style_signature=style_signature
            )
            if not block:
                continue
            if rows:
                separator_rows.add(len(rows))
                rows.append("")
            rows.extend(block)
        segment = (
            RenderLineSegment(
                lines=tuple(RenderLine(row) for row in rows),
                revision=key,
            )
            if rows
            else None
        )
        self._committed_segment_key = key
        self._committed_segment = segment
        self._committed_separator_rows = frozenset(separator_rows)
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
            self.presentation.project_record(source_record)
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
            if self._segmented_transient_buffer_version != source_buffer.version:
                return
            if record.text != source_buffer.text:
                return
            if (
                self._segmented_transient_width <= 0
                or self._segmented_transient_style_signature is None
            ):
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
