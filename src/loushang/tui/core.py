from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import overload

from loushang.tui.cell_width import visible_width

CURSOR_MARKER = "\x1b_loushang:cursor\x07"


@dataclass(frozen=True, slots=True)
class RenderConstraints:
    width: int
    max_height: int
    visible_height: int | None = None

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError("width must be positive")
        if self.max_height <= 0:
            raise ValueError("max_height must be positive")
        if self.visible_height is not None and self.visible_height <= 0:
            raise ValueError("visible_height must be positive")


@dataclass(frozen=True, slots=True)
class CursorDeclaration:
    row: int
    column: int

    def __post_init__(self) -> None:
        if self.row < 0:
            raise ValueError("cursor row must be non-negative")
        if self.column < 0:
            raise ValueError("cursor column must be non-negative")


@dataclass(frozen=True, slots=True)
class RenderLine:
    text: str

    @property
    def width(self) -> int:
        return visible_width(self.text)


@dataclass(frozen=True, slots=True)
class RenderLineSegment:
    lines: tuple[RenderLine, ...]
    identity: object = field(default_factory=object)
    revision: object = 0
    cacheable: bool = True
    _identity_key: tuple[object, int, int] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.lines, tuple):
            object.__setattr__(self, "lines", tuple(self.lines))
        try:
            hash(self.identity)
        except TypeError as exc:
            raise TypeError("segment identity must be hashable") from exc
        object.__setattr__(self, "_identity_key", (self.identity, 0, len(self.lines)))

    @property
    def identity_key(self) -> tuple[object, int, int]:
        return self._identity_key

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def iter_lines(self) -> Iterator[RenderLine]:
        return iter(self.lines)


@dataclass(frozen=True, slots=True)
class RenderLineSegmentView:
    segment: RenderLineSegment
    start: int
    stop: int
    _identity_key: tuple[object, int, int] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("segment view start must be non-negative")
        if self.stop < self.start:
            raise ValueError("segment view stop must not precede start")
        if self.stop > self.segment.line_count:
            raise ValueError("segment view stop exceeds segment line count")
        object.__setattr__(
            self,
            "_identity_key",
            (self.segment.identity, self.start, self.stop),
        )

    @property
    def identity_key(self) -> tuple[object, int, int]:
        return self._identity_key

    @property
    def revision(self) -> object:
        return self.segment.revision

    @property
    def cacheable(self) -> bool:
        return self.segment.cacheable

    @property
    def line_count(self) -> int:
        return self.stop - self.start

    def iter_lines(self) -> Iterator[RenderLine]:
        lines = self.segment.lines
        return (lines[index] for index in range(self.start, self.stop))


RenderLineSegmentLike = RenderLineSegment | RenderLineSegmentView


@dataclass(frozen=True, slots=True, eq=False)
class SegmentedRenderLines(Sequence[RenderLine]):
    segments: tuple[RenderLineSegmentLike, ...] = ()
    _segment_ends: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        segments = tuple(segment for segment in self.segments if segment.line_count > 0)
        if segments != self.segments:
            object.__setattr__(self, "segments", segments)
        total = 0
        ends: list[int] = []
        for segment in segments:
            total += segment.line_count
            ends.append(total)
        object.__setattr__(self, "_segment_ends", tuple(ends))

    @classmethod
    def from_segments(
        cls, segments: tuple[RenderLineSegmentLike, ...]
    ) -> SegmentedRenderLines:
        return cls(segments=segments)

    @classmethod
    def concat(
        cls, before: SegmentedRenderLines, after: SegmentedRenderLines
    ) -> SegmentedRenderLines:
        if not before.segments:
            return after
        if not after.segments:
            return before
        combined = object.__new__(cls)
        object.__setattr__(combined, "segments", before.segments + after.segments)
        offset = len(before)
        object.__setattr__(
            combined,
            "_segment_ends",
            before._segment_ends + tuple(offset + end for end in after._segment_ends),
        )
        return combined

    @property
    def line_count(self) -> int:
        return len(self)

    def iter_lines(self) -> Iterator[RenderLine]:
        return iter(self)

    def __len__(self) -> int:
        return self._segment_ends[-1] if self._segment_ends else 0

    def __iter__(self) -> Iterator[RenderLine]:
        for segment in self.segments:
            yield from segment.iter_lines()

    @overload
    def __getitem__(self, index: int) -> RenderLine: ...

    @overload
    def __getitem__(self, index: slice) -> SegmentedRenderLines: ...

    def __getitem__(self, index: int | slice) -> RenderLine | SegmentedRenderLines:
        if isinstance(index, slice):
            return self._slice(index)
        normalized = index
        if normalized < 0:
            normalized += len(self)
        if normalized < 0 or normalized >= len(self):
            raise IndexError("render line index out of range")
        segment_index = bisect_right(self._segment_ends, normalized)
        segment_start = self._segment_ends[segment_index - 1] if segment_index else 0
        segment = self.segments[segment_index]
        return _segment_line_at(segment, normalized - segment_start)

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if not isinstance(other, Sequence):
            return NotImplemented
        if len(self) != len(other):
            return False
        return all(
            current == candidate for current, candidate in zip(self, other, strict=True)
        )

    def tail(self, max_rows: int) -> SegmentedRenderLines:
        if max_rows <= 0:
            return SegmentedRenderLines()
        if max_rows >= len(self):
            return self
        return self[len(self) - max_rows :]

    def _slice(self, requested: slice) -> SegmentedRenderLines:
        start, stop, step = requested.indices(len(self))
        if step != 1:
            selected = tuple(self[index] for index in range(start, stop, step))
            if not selected:
                return SegmentedRenderLines()
            return SegmentedRenderLines.from_segments(
                (RenderLineSegment(selected, cacheable=False),)
            )
        if start >= stop:
            return SegmentedRenderLines()
        if start == 0 and stop == len(self):
            return self

        selected_segments: list[RenderLineSegmentLike] = []
        first = bisect_right(self._segment_ends, start)
        segment_start = self._segment_ends[first - 1] if first else 0
        for segment, segment_end in zip(
            self.segments[first:], self._segment_ends[first:], strict=True
        ):
            if segment_start >= stop:
                break
            local_start = max(0, start - segment_start)
            local_stop = min(segment.line_count, stop - segment_start)
            selected_segments.append(_slice_segment(segment, local_start, local_stop))
            segment_start = segment_end
        return SegmentedRenderLines.from_segments(tuple(selected_segments))


def _segment_line_at(segment: RenderLineSegmentLike, index: int) -> RenderLine:
    if isinstance(segment, RenderLineSegmentView):
        return segment.segment.lines[segment.start + index]
    return segment.lines[index]


def _slice_segment(
    segment: RenderLineSegmentLike,
    start: int,
    stop: int,
) -> RenderLineSegmentLike:
    if start == 0 and stop == segment.line_count:
        return segment
    if isinstance(segment, RenderLineSegmentView):
        return RenderLineSegmentView(
            segment.segment,
            segment.start + start,
            segment.start + stop,
        )
    return RenderLineSegmentView(segment, start, stop)


@dataclass(frozen=True, slots=True)
class RenderResult:
    lines: Sequence[RenderLine]
    cursor: CursorDeclaration | None = None

    @classmethod
    def from_text(cls, text: str, *, constraints: RenderConstraints) -> RenderResult:
        cursor: CursorDeclaration | None = None
        rendered_lines: list[RenderLine] = []
        for row, line in enumerate(text.split("\n")):
            if CURSOR_MARKER in line:
                before_marker, marker, after_marker = line.partition(CURSOR_MARKER)
                if marker and cursor is not None:
                    raise ValueError("render result contains multiple cursor markers")
                cursor = CursorDeclaration(row=row, column=visible_width(before_marker))
                line = before_marker + after_marker
            rendered_lines.append(RenderLine(line))
        return cls.from_lines(rendered_lines, constraints=constraints, cursor=cursor)

    @classmethod
    def from_lines(
        cls,
        lines: Sequence[RenderLine],
        *,
        constraints: RenderConstraints,
        cursor: CursorDeclaration | None = None,
    ) -> RenderResult:
        rendered_lines: list[RenderLine] = []
        marker_cursor = cursor
        for row, line in enumerate(lines):
            text = line.text
            if CURSOR_MARKER in text:
                before_marker, marker, after_marker = text.partition(CURSOR_MARKER)
                if marker and marker_cursor is not None:
                    raise ValueError("render result contains multiple cursor markers")
                marker_cursor = CursorDeclaration(
                    row=row, column=visible_width(before_marker)
                )
                text = before_marker + after_marker
            rendered_lines.append(RenderLine(text))
        result = cls(lines=tuple(rendered_lines), cursor=marker_cursor)
        result.validate(constraints)
        return result

    def validate(self, constraints: RenderConstraints) -> None:
        if len(self.lines) > constraints.max_height:
            raise ValueError(
                f"render result exceeds max height {constraints.max_height}"
            )

        for index, line in enumerate(self.lines):
            if line.width > constraints.width:
                raise ValueError(f"line {index} exceeds width {constraints.width}")

        if self.cursor is None:
            return
        if self.cursor.row >= len(self.lines):
            raise ValueError("cursor row out of range")
        if self.cursor.column > self.lines[self.cursor.row].width:
            raise ValueError("cursor column out of range")
