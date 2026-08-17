from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import pytest

import loushang.tui.ui_parts.transcript as transcript_region_module
from loushang.tui import RenderConstraints, RenderLoop, TerminalSize
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    StreamingTextBuffer,
    UserPromptRecord,
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

    def project_record(self, record: DisplayRecord) -> DisplayRecord:
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
        theme: ThemeResolver | None,
        capabilities: Any | None,
    ) -> tuple[str, ...]:
        del record, theme, capabilities
        self.present_calls += 1
        return lines


class _ProjectingPresentation:
    cache_token = "projecting"

    def project_record(self, record: DisplayRecord) -> DisplayRecord:
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
        theme: ThemeResolver | None,
        capabilities: Any | None,
    ) -> tuple[str, ...]:
        del record, theme, capabilities
        return lines


@dataclass(slots=True)
class _TokenPresentation:
    token: str = "A"

    @property
    def cache_token(self) -> str:
        return self.token

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
        return tuple(f"{self.token}:{line}" for line in lines)


class _StabilityPresentation:
    cache_token = "stable-parity"

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
        del theme, capabilities
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
