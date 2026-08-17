from __future__ import annotations

from dataclasses import dataclass

import pytest

from loushang.tui.core import (
    CursorDeclaration,
    RenderConstraints,
    RenderLine,
    RenderLineSegment,
    RenderLineSegmentView,
    RenderResult,
    SegmentedRenderLines,
)
from loushang.tui.ui_parts.layout import ScreenRegion, ScreenRegionStack

pytestmark = pytest.mark.tui_render_contract


def _lines(*values: str) -> tuple[RenderLine, ...]:
    return tuple(RenderLine(value) for value in values)


def test_segmented_render_lines_support_sequence_access_and_tuple_equality() -> None:
    first_identity = object()
    first = RenderLineSegment(
        _lines("one", "two"),
        identity=first_identity,
        revision=3,
    )
    second = RenderLineSegment(_lines("three", "four"), revision=4)
    lines = SegmentedRenderLines.from_segments((first, second))

    assert len(lines) == 4
    assert lines.line_count == 4
    assert lines[0] == RenderLine("one")
    assert lines[-1] == RenderLine("four")
    assert tuple(lines.iter_lines()) == _lines("one", "two", "three", "four")
    assert lines == _lines("one", "two", "three", "four")
    assert _lines("one", "two", "three", "four") == lines
    assert first.identity_key == (first_identity, 0, 2)
    assert isinstance(hash(first.identity_key), int)

    with pytest.raises(IndexError, match="render line index out of range"):
        _ = lines[4]


def test_contiguous_slice_and_tail_preserve_segment_views() -> None:
    first = RenderLineSegment(_lines("one", "two", "three"), revision=1)
    second = RenderLineSegment(_lines("four", "five"), revision=2)
    lines = SegmentedRenderLines.from_segments((first, second))

    sliced = lines[1:]

    assert tuple(sliced) == _lines("two", "three", "four", "five")
    assert len(sliced.segments) == 2
    assert isinstance(sliced.segments[0], RenderLineSegmentView)
    assert sliced.segments[0].segment is first
    assert sliced.segments[0].identity_key == (first.identity, 1, 3)
    assert sliced.segments[0].revision == 1
    assert sliced.segments[1] is second
    assert lines.tail(4).segments == sliced.segments
    assert lines.tail(5) is lines
    assert lines.tail(0) == ()


def test_nested_contiguous_slice_collapses_to_a_single_base_segment_view() -> None:
    segment = RenderLineSegment(_lines("zero", "one", "two", "three"), revision=5)
    lines = SegmentedRenderLines.from_segments((segment,))

    nested = lines[1:][1:2]

    assert tuple(nested) == _lines("two")
    assert len(nested.segments) == 1
    view = nested.segments[0]
    assert isinstance(view, RenderLineSegmentView)
    assert view.segment is segment
    assert (view.start, view.stop) == (2, 3)


def test_strided_slice_returns_an_uncacheable_ephemeral_segment() -> None:
    lines = SegmentedRenderLines.from_segments(
        (RenderLineSegment(_lines("zero", "one", "two", "three")),)
    )

    selected = lines[::-2]

    assert tuple(selected) == _lines("three", "one")
    assert len(selected.segments) == 1
    assert selected.segments[0].cacheable is False


def test_render_line_segment_rejects_unhashable_identity() -> None:
    with pytest.raises(TypeError, match="segment identity must be hashable"):
        RenderLineSegment(_lines("line"), identity=[])


@dataclass(frozen=True, slots=True)
class _SegmentedRenderable:
    lines: SegmentedRenderLines
    cursor: CursorDeclaration | None = None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        del constraints
        return RenderResult(lines=self.lines, cursor=self.cursor)


@dataclass(frozen=True, slots=True)
class _PlainRenderable:
    text: str

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines(
            (RenderLine(self.text),),
            constraints=constraints,
        )


def test_screen_region_stack_preserves_segments_and_wraps_plain_results() -> None:
    stable = RenderLineSegment(
        _lines("history one", "history two"),
        identity=object(),
        revision=7,
    )
    transcript = _SegmentedRenderable(SegmentedRenderLines.from_segments((stable,)))
    stack = ScreenRegionStack(
        (
            ScreenRegion("transcript", transcript, gap_after=1),
            ScreenRegion(
                "status", _PlainRenderable("status"), required=True, min_height=1
            ),
        )
    )

    result = stack.render(RenderConstraints(width=40, max_height=5))

    assert isinstance(result.lines, SegmentedRenderLines)
    assert tuple(result.lines) == _lines("history one", "history two", "", "status")
    assert result.lines.segments[0] is stable
    assert result.lines.segments[1].cacheable is False
    assert result.lines.segments[2].cacheable is False


def test_screen_region_stack_offsets_cursor_using_segment_lengths() -> None:
    stable = RenderLineSegment(_lines("history one", "history two"))
    editor_lines = SegmentedRenderLines.from_segments(
        (RenderLineSegment(_lines("editor"), cacheable=False),)
    )
    stack = ScreenRegionStack(
        (
            ScreenRegion(
                "transcript",
                _SegmentedRenderable(SegmentedRenderLines.from_segments((stable,))),
            ),
            ScreenRegion(
                "editor",
                _SegmentedRenderable(
                    editor_lines, cursor=CursorDeclaration(row=0, column=3)
                ),
                required=True,
                min_height=1,
            ),
        )
    )

    result = stack.render(RenderConstraints(width=40, max_height=4))

    assert result.cursor == CursorDeclaration(row=2, column=3)
    assert isinstance(result.lines, SegmentedRenderLines)
    assert result.lines.segments[0] is stable
