from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import pytest

import loushang.tui.markdown.renderer as markdown_renderer
import loushang.tui.ui_parts.transcript as transcript_region_module
from loushang.tui import RenderConstraints, RenderLoop, TerminalSize
from loushang.tui.core import RenderLineSegment
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    StreamingTextBuffer,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)
from loushang.tui.ui_parts.transcript import TranscriptRegion

_STREAMING_MARKDOWN = "Intro\n\n```python\nprint(1)\n```\n\nTail"


@dataclass(slots=True)
class _SpyPresentation:
    token_reads: int = 0
    project_calls: int = 0
    width_calls: int = 0
    present_calls: int = 0

    @property
    def cache_token(self) -> str:
        self.token_reads += 1
        return "stable"

    def project_record(self, record: DisplayRecord, *, width: int) -> DisplayRecord:
        del width
        self.project_calls += 1
        return record

    def record_render_width(
        self,
        record: DisplayRecord,
        *,
        width: int,
    ) -> int:
        del record
        self.width_calls += 1
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
        self.present_calls += 1
        return lines


class _ProjectingPresentation:
    cache_token = "projecting"

    def project_record(self, record: DisplayRecord, *, width: int) -> DisplayRecord:
        del width
        if isinstance(record, AssistantMessageRecord):
            return replace(record, text="PROJECTED")
        return record

    def record_render_width(
        self,
        record: DisplayRecord,
        *,
        width: int,
    ) -> int:
        del record, width
        return 5

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
class _TokenPresentation:
    token: str = "A"

    @property
    def cache_token(self) -> str:
        return self.token

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
        return tuple(f"{self.token}:{line}" for line in lines)


class _StabilityPresentation:
    cache_token = "stable-parity"

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
        del width, theme, capabilities
        prefix = (
            "S:"
            if not isinstance(record, AssistantMessageRecord) or record.stable
            else "D:"
        )
        return tuple(f"{prefix}{line}" for line in lines)


def test_transcript_region_neutral_presentation_renders_generic_records() -> None:
    region = TranscriptRegion(records=[UserPromptRecord("hello")], records_revision=1)

    result = region.render(RenderConstraints(width=40, max_height=10))

    assert tuple(line.text for line in result.lines) == ("> hello",)


@pytest.mark.tui_render_contract
def test_transcript_region_stable_frame_reuses_projection_and_lines() -> None:
    presentation = _SpyPresentation()
    records = [UserPromptRecord("hello")]
    region = TranscriptRegion(
        records=records,
        records_revision=1,
        presentation=presentation,
    )
    constraints = RenderConstraints(width=40, max_height=10)

    first = region.render(constraints)
    first_segment = region._committed_segment
    second = region.render(constraints)

    assert tuple(line.text for line in first.lines) == tuple(
        line.text for line in second.lines
    )
    assert region.records is records
    assert region.presentation is presentation
    assert region._committed_segment is first_segment
    assert presentation.token_reads == 2
    assert presentation.project_calls == 1
    assert presentation.width_calls == 1
    assert presentation.present_calls == 1


@pytest.mark.tui_render_contract
def test_committed_blocks_reuse_unchanged_records_and_invalidate_changed_context() -> (
    None
):
    presentation = _SpyPresentation()
    records = [UserPromptRecord(f"record {index}") for index in range(3)]
    region = TranscriptRegion(
        records=records,
        records_revision=1,
        presentation=presentation,
        stable_cache_entry_limit=1,
    )
    constraints = RenderConstraints(width=40, max_height=30)

    region.render(constraints)
    assert presentation.project_calls == 3

    records.append(UserPromptRecord("appended"))
    region.records_revision += 1
    region.render(constraints)
    assert presentation.project_calls == 4

    records[1] = UserPromptRecord("replaced")
    region.records_revision += 1
    rendered = region.render(constraints)
    assert presentation.project_calls == 5
    assert any("replaced" in line.text for line in rendered.lines)
    assert all("record 1" not in line.text for line in rendered.lines)

    region.presentation = _TokenPresentation("changed")
    rendered = region.render(constraints)
    assert all("changed:" in line.text for line in rendered.lines if line.text)


@pytest.mark.tui_render_contract
def test_append_assistant_and_worked_reuses_committed_line_objects() -> None:
    records: list[DisplayRecord] = [
        ToolExecutionRecord(
            name="bash",
            state="completed",
            elapsed_seconds=0.1,
            output="preview",
            expanded_output="full output",
        ),
        *(UserPromptRecord(f"history {index}") for index in range(200)),
    ]
    region = TranscriptRegion(
        records=records,
        records_revision=1,
        expanded_tool_indices=frozenset({0}),
        focused_tool_index=0,
    )
    constraints = RenderConstraints(width=80, max_height=1000)
    region.render(constraints)
    previous_segment = region._committed_segment
    assert previous_segment is not None
    previous_controls = dict(region._committed_control_rows)

    records.extend((AssistantMessageRecord("final"), WorkedDividerRecord(2.0)))
    region.records_revision += 1
    actual = region.render(constraints)
    segment = region._committed_segment
    assert segment is not None
    assert all(
        current is previous
        for current, previous in zip(
            segment.lines[: previous_segment.line_count],
            previous_segment.lines,
            strict=True,
        )
    )
    assert region._committed_control_rows == previous_controls
    expected = TranscriptRegion(
        records=list(records),
        expanded_tool_indices=frozenset({0}),
        focused_tool_index=0,
    ).render(constraints)
    assert [line.text for line in actual.lines] == [
        line.text for line in expected.lines
    ]


@pytest.mark.tui_render_contract
def test_tool_updates_reuse_history_lines_and_keep_detail_controls_current() -> None:
    history = [UserPromptRecord(f"history {index}") for index in range(200)]
    tool = ToolExecutionRecord(
        name="bash",
        state="running",
        elapsed_seconds=0.0,
        output="preview",
        expanded_output="detail",
    )
    records: list[DisplayRecord] = [*history, tool]
    region = TranscriptRegion(records=records, records_revision=1)
    constraints = RenderConstraints(width=80, max_height=1000)
    region.render(constraints)
    previous = region._committed_segment
    assert previous is not None
    previous_blocks = region._committed_record_blocks
    old_history_lines = {
        line.text: line for line in previous.lines if "history " in line.text
    }

    records[-1] = replace(tool, state="completed", elapsed_seconds=1.0, output="done")
    region.records_revision += 1
    region.focused_tool_index = len(history)
    region.expanded_tool_indices = frozenset({len(history)})
    rendered = region.render(constraints)
    current = region._committed_segment
    assert current is not None
    assert all(
        line is old_history_lines[line.text]
        for line in current.lines
        if line.text in old_history_lines
    )
    assert all(
        region._committed_record_blocks[index] is previous_blocks[index]
        for index in range(len(history))
    )
    fresh = TranscriptRegion(
        records=list(records),
        focused_tool_index=len(history),
        expanded_tool_indices=frozenset({len(history)}),
    ).render(constraints)
    assert rendered.lines == fresh.lines
    assert region.visible_controls == {len(rendered.lines) - 1: len(history)}

    # Completion's suffix fast path must populate the same per-record cache
    # before a later tool update takes the general replacement path.
    records.extend((AssistantMessageRecord("final"), WorkedDividerRecord(1.0)))
    region.records_revision += 1
    region.render(constraints)
    records[len(history)] = replace(tool, output="changed after completion")
    region.records_revision += 1
    assert (
        region.render(constraints).lines
        == TranscriptRegion(
            records=list(records),
            focused_tool_index=len(history),
            expanded_tool_indices=frozenset({len(history)}),
        )
        .render(constraints)
        .lines
    )


@pytest.mark.tui_render_contract
def test_cached_layout_tracks_anchor_changes_without_changing_tool_focus() -> None:
    records: list[DisplayRecord] = [
        ToolExecutionRecord(
            name="bash",
            state="completed",
            elapsed_seconds=1.0,
            output="first",
            expanded_output="detail",
        ),
        *(UserPromptRecord(f"prompt {i}") for i in range(100)),
    ]
    region = TranscriptRegion(
        records=records, focused_tool_index=0, anchor_tool_index=0
    )
    constraints = RenderConstraints(width=80, max_height=5)
    region.render(constraints)
    region.anchor_tool_index = None
    assert (
        region.render(constraints).lines
        == TranscriptRegion(
            records=records,
            focused_tool_index=0,
        )
        .render(constraints)
        .lines
    )


@pytest.mark.tui_render_contract
@pytest.mark.parametrize("height", [8, 1_000_000])
def test_repeated_render_does_not_recount_historical_segments(
    monkeypatch: pytest.MonkeyPatch,
    height: int,
) -> None:
    records = [UserPromptRecord(f"history {index}") for index in range(200)]
    region = TranscriptRegion(records=records, records_revision=1)
    constraints = RenderConstraints(width=80, max_height=height)
    expected = tuple(line.text for line in region.render(constraints).lines)

    original_count = RenderLineSegment.line_count.fget
    assert original_count is not None
    counted = 0

    def count_segment_lines(segment: RenderLineSegment) -> int:
        nonlocal counted
        counted += 1
        return original_count(segment)

    monkeypatch.setattr(RenderLineSegment, "line_count", property(count_segment_lines))
    actual = region.render(constraints)

    assert tuple(line.text for line in actual.lines) == expected
    assert counted < 30


@pytest.mark.tui_render_contract
@pytest.mark.parametrize("width", [28, 80])
@pytest.mark.parametrize("height", [1, 4, 10, 30])
@pytest.mark.parametrize("anchor", [None, 0, 3, 18])
@pytest.mark.parametrize(
    "draft", [None, AssistantMessageRecord("draft\n\nlast", stable=False)]
)
def test_segmented_layout_matches_full_layout_with_anchor_and_draft(
    width: int, height: int, anchor: int | None, draft: AssistantMessageRecord | None
) -> None:
    records: list[DisplayRecord] = []
    for index in range(20):
        records.append(
            ToolExecutionRecord(
                name="bash",
                state="completed",
                elapsed_seconds=1.0,
                command=f"command {index}",
                output="short output\n" + "wrapped output " * 5,
                expanded_output="detail\n" * 4,
            )
            if index % 3 == 0
            else UserPromptRecord(f"prompt {index}")
        )
    options = dict(
        records=records,
        draft=draft,
        expanded_tool_indices=frozenset({0, 3, 18}),
        focused_tool_index=anchor,
        anchor_tool_index=anchor,
    )
    reference = TranscriptRegion(**options)
    full = reference.render(RenderConstraints(width=width, max_height=10000))
    start = max(0, len(full.lines) - height)
    anchor_row = reference._committed_control_by_index.get(anchor)
    if anchor_row is not None and not start <= anchor_row < start + height:
        start = max(0, min(anchor_row - height + 1, len(full.lines) - height))
    committed = reference._committed_segment
    if start in reference._committed_separator_rows or (
        draft is not None and committed is not None and start == committed.line_count
    ):
        start += 1
    expected = full.lines[start : start + height]
    expected_controls = {
        row - start: index
        for row, index in reference._committed_control_rows.items()
        if start <= row < start + len(expected)
    }

    region = TranscriptRegion(**options)
    actual = region.render(RenderConstraints(width=width, max_height=height))
    assert actual.lines == expected
    assert region.visible_controls == expected_controls


@pytest.mark.tui_render_contract
def test_worked_append_finalizes_only_new_lines_in_render_loop() -> None:
    records: list[DisplayRecord] = [
        UserPromptRecord(f"history {index}") for index in range(200)
    ]
    region = TranscriptRegion(records=records, records_revision=1)
    loop = RenderLoop(region)
    size = TerminalSize(columns=80, rows=24)
    first = loop.plan(size)
    loop.commit(first, size=size)

    records.extend((AssistantMessageRecord("final"), WorkedDividerRecord(2.0)))
    region.records_revision += 1
    worked = loop.plan(size)

    assert worked.reused_render_segment_count >= 1
    assert worked.materialized_logical_line_count <= 6
    assert worked.flattened_logical_line_count == 0

    loop.commit(worked, size=size)
    records[5] = UserPromptRecord("replaced history")
    region.records_revision += 1
    changed = loop.plan(size)
    assert changed.materialized_logical_line_count <= 6
    assert any("replaced history" in line for line in changed.current_logical_lines)


@pytest.mark.tui_render_contract
def test_tool_update_keeps_history_segments_in_complete_logical_frame() -> None:
    records: list[DisplayRecord] = [
        *(UserPromptRecord(f"history {index}") for index in range(2000)),
        ToolExecutionRecord(name="bash", state="running", elapsed_seconds=0.0),
    ]
    region = TranscriptRegion(records=records, records_revision=1)
    loop = RenderLoop(region)
    size = TerminalSize(columns=80, rows=24)
    first = loop.plan(size)
    loop.commit(first, size=size)

    records[-1] = ToolExecutionRecord(
        name="bash", state="completed", elapsed_seconds=1.0, output="done"
    )
    region.records_revision += 1
    updated = loop.plan(size)

    assert updated.materialized_logical_line_count <= 5
    assert updated.reused_render_segment_count >= 2000
    assert updated.flattened_logical_line_count == 0
    assert len(updated.current_logical_lines) >= 4000
    assert any("history 0" in line for line in updated.current_logical_lines)
    assert any("history 1999" in line for line in updated.current_logical_lines)


@pytest.mark.tui_render_contract
def test_streaming_segments_honor_projection_and_effective_width() -> None:
    presentation = _ProjectingPresentation()
    theme = ThemeResolver()
    buffer = StreamingTextBuffer.from_text(_STREAMING_MARKDOWN)
    constraints = RenderConstraints(width=40, max_height=30)
    flat = TranscriptRegion(
        draft=AssistantMessageRecord(_STREAMING_MARKDOWN, stable=False),
        presentation=presentation,
        theme=theme,
    )
    streaming = TranscriptRegion(
        draft_buffer=buffer,
        presentation=presentation,
        theme=theme,
    )

    flat_lines = tuple(line.text for line in flat.render(constraints).lines)
    streaming_lines = tuple(line.text for line in streaming.render(constraints).lines)

    assert streaming._segmented_transient_content_segments
    assert streaming_lines == flat_lines
    assert all(len(line) <= 5 for line in streaming_lines)


@pytest.mark.tui_render_contract
def test_streaming_segment_revision_changes_with_presentation_token() -> None:
    presentation = _TokenPresentation()
    region = TranscriptRegion(
        draft_buffer=StreamingTextBuffer.from_text(_STREAMING_MARKDOWN),
        presentation=presentation,
        theme=ThemeResolver(),
    )
    loop = RenderLoop(region)
    size = TerminalSize(columns=40, rows=20)

    first = loop.plan(size)
    loop.commit(first, size=size)
    assert tuple(first.current_logical_lines)[0] == "A:* Intro"

    presentation.token = "B"
    second = loop.plan(size)

    assert tuple(second.current_logical_lines)[0] == "B:* Intro"


@pytest.mark.tui_render_contract
def test_streaming_cache_promotion_hides_assistant_stability_metadata() -> None:
    presentation = _StabilityPresentation()
    theme = ThemeResolver()
    buffer = StreamingTextBuffer.from_text(_STREAMING_MARKDOWN)
    constraints = RenderConstraints(width=40, max_height=30)
    region = TranscriptRegion(
        draft_buffer=buffer,
        presentation=presentation,
        theme=theme,
    )

    draft_lines = tuple(line.text for line in region.render(constraints).lines)
    committed_record = AssistantMessageRecord(buffer.text)
    region.promote_transient_cache(committed_record, source_buffer=buffer)
    region.clear_transient_cache()
    region.draft_buffer = None
    region.records.append(committed_record)
    region.records_revision += 1
    committed_lines = tuple(line.text for line in region.render(constraints).lines)
    fresh_lines = tuple(
        line.text
        for line in TranscriptRegion(
            records=[committed_record],
            records_revision=1,
            presentation=presentation,
            theme=theme,
        )
        .render(constraints)
        .lines
    )

    assert draft_lines == committed_lines == fresh_lines
    assert draft_lines[0] == "S:* Intro"


@pytest.mark.tui_render_contract
def test_streaming_cache_promotion_renders_unseen_final_delta_without_full_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "".join(
        f"- item {index} **bold** [link](https://example.com/{index})\n"
        for index in range(128)
    )
    buffer = StreamingTextBuffer.from_text(source)
    constraints = RenderConstraints(width=72, max_height=1000)
    region = TranscriptRegion(draft_buffer=buffer, theme=ThemeResolver())
    region.render(constraints)

    buffer.append("- final **item** [link](https://example.com/final)\n")
    committed_record = AssistantMessageRecord(buffer.text)
    with monkeypatch.context() as patch:
        patch.setattr(
            markdown_renderer,
            "_parse_normalized_markdown_blocks",
            lambda _source: pytest.fail("completion should reuse streaming segments"),
        )
        region.promote_transient_cache(committed_record, source_buffer=buffer)
        region.clear_transient_cache()
        region.draft_buffer = None
        region.records.append(committed_record)
        region.records_revision += 1
        committed_lines = tuple(line.text for line in region.render(constraints).lines)

    expected_lines = tuple(
        line.text
        for line in TranscriptRegion(
            records=[committed_record], records_revision=1, theme=ThemeResolver()
        )
        .render(constraints)
        .lines
    )
    assert committed_lines == expected_lines


@pytest.mark.tui_render_contract
def test_streaming_flat_fallback_preserves_markdown_streaming_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        transcript_region_module,
        "_render_streaming_assistant_markdown_segments",
        lambda *args, **kwargs: None,
    )
    buffer = StreamingTextBuffer.from_text(_STREAMING_MARKDOWN)
    region = TranscriptRegion(
        draft_buffer=buffer,
        presentation=_StabilityPresentation(),
        theme=ThemeResolver(),
    )

    lines = tuple(
        line.text
        for line in region.render(RenderConstraints(width=40, max_height=30)).lines
    )

    assert lines[0] == "S:* Intro"
    assert not region._segmented_transient_content_segments
    assert region._markdown_render_cache._streaming_key is buffer
