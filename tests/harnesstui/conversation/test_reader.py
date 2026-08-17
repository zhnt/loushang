from __future__ import annotations

from dataclasses import dataclass

from loushang.harnesstui.conversation.reader import TranscriptReaderSurface
from loushang.harnesstui.conversation.source import TranscriptSnapshot
from loushang.tui import RenderConstraints, strip_control_sequences
from loushang.tui.input import InputEvent, InputIntent
from loushang.tui.transcript import (
    AssistantMessageRecord,
    DisplayRecord,
    ErrorRecord,
    ThinkingRecord,
    ThinkingVisibility,
    ToolExecutionRecord,
    UserPromptRecord,
)


@dataclass(slots=True)
class _Source:
    records: tuple[DisplayRecord, ...]
    evicted_prefix_record_count: int = 0
    snapshot_calls: int = 0

    def snapshot(self) -> TranscriptSnapshot:
        self.snapshot_calls += 1
        return TranscriptSnapshot(
            records=self.records,
            evicted_prefix_record_count=self.evicted_prefix_record_count,
            complete=False,
            source_label="Transcript window",
        )

    def recent_assistant_texts(self) -> tuple[str, ...]:
        return tuple(
            record.text
            for record in reversed(self.records)
            if isinstance(record, AssistantMessageRecord) and record.text
        )


def _render_text(
    reader: TranscriptReaderSurface,
    *,
    width: int = 48,
    height: int = 6,
) -> tuple[str, ...]:
    result = reader.render(RenderConstraints(width=width, max_height=height))
    return tuple(strip_control_sequences(line.text) for line in result.lines)


def _render_raw(
    reader: TranscriptReaderSurface,
    *,
    width: int = 48,
    height: int = 6,
) -> tuple[str, ...]:
    result = reader.render(RenderConstraints(width=width, max_height=height))
    return tuple(line.text for line in result.lines)


def test_transcript_reader_renders_frozen_snapshot_and_footer() -> None:
    source = _Source(
        (UserPromptRecord("hello"), AssistantMessageRecord("first")),
        evicted_prefix_record_count=2,
    )
    reader = TranscriptReaderSurface(source)

    first = _render_text(reader, width=80, height=9)
    source.records = (AssistantMessageRecord("second"),)
    second = _render_text(reader, width=80, height=9)

    assert source.snapshot_calls == 1
    assert first == second
    assert first[0] == "Transcript window"
    assert "Earlier transcript records were trimmed." in first
    assert first[-3] == "─" * 80
    assert first[-2] == "↑/↓ scroll   PgUp/Ctrl+B · PgDn/Ctrl+F page   Home/End jump"
    assert first[-1] == "Ctrl+O/q/Esc close   / search   n/N next   d detail   r raw"
    assert any("first" in line for line in first)
    assert all("second" not in line for line in first)


def test_transcript_reader_footer_chrome_is_dim_gray() -> None:
    reader = TranscriptReaderSurface(_Source((AssistantMessageRecord("answer"),)))

    raw = _render_raw(reader, width=80, height=6)

    assert raw[-3].startswith("\x1b[2;90m")
    assert raw[-2].startswith("\x1b[2;90m")
    assert raw[-1].startswith("\x1b[2;90m")


def test_transcript_reader_short_content_fills_full_height_with_footer_at_bottom() -> (
    None
):
    reader = TranscriptReaderSurface(_Source((AssistantMessageRecord("short answer"),)))

    rendered = _render_text(reader, width=40, height=8)

    assert len(rendered) == 8
    assert rendered[0] == "Transcript window"
    assert any("short answer" in line for line in rendered)
    assert rendered[-3] == "─" * 40
    assert rendered[-2].startswith("↑/↓ scroll   PgUp/Ctrl+B")
    assert "PgDn/Ctrl" in rendered[-2]
    assert rendered[-1].startswith("Ctrl+O/q/Esc close   / search")


def test_transcript_reader_opens_at_tail_and_scrolls_by_page() -> None:
    source = _Source(
        (AssistantMessageRecord("\n".join(f"line {index}" for index in range(8))),)
    )
    reader = TranscriptReaderSurface(source)

    tail = _render_text(reader, height=7)
    assert any("line 7" in line for line in tail)
    assert all("line 0" not in line for line in tail)

    assert reader.handle_input(InputEvent(kind="key", key="pageUp")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    older = _render_text(reader, height=7)
    assert any("line 4" in line for line in older)
    assert reader.scroll_offset < reader.max_scroll_offset

    assert reader.handle_input(InputEvent(kind="key", key="end")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    assert any("line 7" in line for line in _render_text(reader, height=7))


def test_transcript_reader_ctrl_b_and_ctrl_f_page_backward_and_forward() -> None:
    source = _Source(
        (AssistantMessageRecord("\n".join(f"line {index}" for index in range(12))),)
    )
    reader = TranscriptReaderSurface(source)

    tail = _render_text(reader, height=12)
    assert any("line 11" in line for line in tail)

    assert reader.handle_input(InputEvent(kind="key", key="ctrl+b")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    older = _render_text(reader, height=12)
    assert any("line 0" in line for line in older)
    assert reader.scroll_offset < reader.max_scroll_offset

    assert reader.handle_input(InputEvent(kind="key", key="ctrl+f")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    newer = _render_text(reader, height=12)
    assert any("line 11" in line for line in newer)
    assert reader.scroll_offset == reader.max_scroll_offset


def test_transcript_reader_clamps_scroll_offset_after_resize() -> None:
    source = _Source(
        (AssistantMessageRecord("\n".join(f"line {index}" for index in range(6))),)
    )
    reader = TranscriptReaderSurface(source)

    reader.handle_input(InputEvent(kind="key", key="home"))
    _render_text(reader, height=5)
    assert reader.scroll_offset == 0

    reader.handle_input(InputEvent(kind="key", key="end"))
    _render_text(reader, height=5)
    assert reader.scroll_offset == reader.max_scroll_offset

    _render_text(reader, height=12)
    assert reader.scroll_offset == 0
    assert reader.max_scroll_offset == 0


def test_transcript_reader_close_keys_return_surface_close() -> None:
    reader = TranscriptReaderSurface(_Source((AssistantMessageRecord("answer"),)))

    for key in ("q", "esc", "escape", "ctrl+c", "ctrl_c", "ctrl+o", "ctrl_o"):
        assert reader.handle_input(InputEvent(kind="key", key=key)) == InputIntent(
            kind="surface_close"
        )


def test_transcript_reader_strictly_consumes_unrecognized_input() -> None:
    reader = TranscriptReaderSurface(_Source((AssistantMessageRecord("answer"),)))

    assert reader.handle_input(InputEvent(kind="key", key="tab")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    assert reader.handle_input(InputEvent(kind="text", text="x")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )


def test_transcript_reader_detail_and_raw_toggles_are_stable() -> None:
    reader = TranscriptReaderSurface(_Source((AssistantMessageRecord("answer"),)))

    assert reader.handle_input(InputEvent(kind="key", key="d")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    assert reader.detail_mode is True
    assert reader.handle_input(InputEvent(kind="key", key="d")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    assert reader.detail_mode is False

    assert reader.handle_input(InputEvent(kind="key", key="r")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    assert reader.raw_mode is True
    assert reader.handle_input(InputEvent(kind="key", key="r")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    assert reader.raw_mode is False


def test_transcript_reader_title_shows_current_render_mode() -> None:
    reader = TranscriptReaderSurface(_Source((AssistantMessageRecord("answer"),)))

    assert _render_text(reader, width=80, height=6)[0] == "Transcript window"

    reader.handle_input(InputEvent(kind="key", key="d"))
    assert _render_text(reader, width=80, height=6)[0] == "Transcript window · detail"

    reader.handle_input(InputEvent(kind="key", key="r"))
    assert (
        _render_text(reader, width=80, height=6)[0] == "Transcript window · raw+detail"
    )

    reader.handle_input(InputEvent(kind="key", key="d"))
    assert _render_text(reader, width=80, height=6)[0] == "Transcript window · raw"


def test_transcript_reader_raw_mode_renders_copy_friendly_logical_text() -> None:
    reader = TranscriptReaderSurface(
        _Source(
            (
                UserPromptRecord("show status"),
                AssistantMessageRecord("Use **markdown** literally."),
                ToolExecutionRecord(
                    name="pytest",
                    state="completed",
                    elapsed_seconds=1.25,
                    command="uv run pytest",
                    output="2 passed",
                ),
            )
        )
    )

    reader.handle_input(InputEvent(kind="key", key="r"))
    rendered = _render_text(reader, width=80, height=14)

    assert "User" in rendered
    assert "show status" in rendered
    assert "Assistant" in rendered
    assert "Use **markdown** literally." in rendered
    assert "Tool: pytest completed in 1.25s" in rendered
    assert "command: uv run pytest" in rendered
    assert "2 passed" in rendered
    assert not any(line.startswith(("> ", "* ", "- Ran ")) for line in rendered)


def test_transcript_reader_detail_mode_includes_error_diagnostics() -> None:
    reader = TranscriptReaderSurface(
        _Source((ErrorRecord(summary="Request failed", diagnostics="Traceback line"),))
    )

    compact = _render_text(reader, width=80, height=8)
    reader.handle_input(InputEvent(kind="key", key="d"))
    detailed = _render_text(reader, width=80, height=8)

    assert any("Request failed" in line for line in compact)
    assert all("Traceback line" not in line for line in compact)
    assert any("Traceback line" in line for line in detailed)


def test_transcript_reader_raw_mode_does_not_expose_hidden_thinking() -> None:
    reader = TranscriptReaderSurface(
        _Source(
            (
                ThinkingRecord("hidden reasoning", ThinkingVisibility.HIDDEN),
                ThinkingRecord("visible thinking", ThinkingVisibility.VISIBLE),
            )
        )
    )

    reader.handle_input(InputEvent(kind="key", key="r"))
    rendered = _render_text(reader, width=80, height=10)

    assert all("hidden reasoning" not in line for line in rendered)
    assert any("visible thinking" in line for line in rendered)


def test_transcript_reader_search_finds_matches_and_navigates_without_closing() -> None:
    reader = TranscriptReaderSurface(
        _Source(
            (
                AssistantMessageRecord(
                    "\n".join(("alpha one", "beta two", "gamma beta three"))
                ),
            )
        )
    )
    _render_text(reader, width=80, height=7)

    assert reader.handle_input(InputEvent(kind="text", text="/")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    assert reader.handle_input(InputEvent(kind="text", text="beta")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    editing = _render_text(reader, width=80, height=7)
    assert editing[-1] == "Search: beta"

    assert reader.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    first = _render_text(reader, width=80, height=7)
    assert first[0] == "Transcript window · search beta 1/2"
    assert any("beta two" in line for line in first)

    assert reader.handle_input(InputEvent(kind="text", text="n")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    second = _render_text(reader, width=80, height=7)
    assert second[0] == "Transcript window · search beta 2/2"
    assert any("gamma beta three" in line for line in second)

    assert reader.handle_input(InputEvent(kind="text", text="N")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    previous = _render_text(reader, width=80, height=7)
    assert previous[0] == "Transcript window · search beta 1/2"


def test_transcript_reader_search_highlights_matches_without_changing_text() -> None:
    reader = TranscriptReaderSurface(
        _Source((AssistantMessageRecord("alpha beta beta"),))
    )

    reader.handle_input(InputEvent(kind="text", text="/"))
    reader.handle_input(InputEvent(kind="text", text="beta"))
    reader.handle_input(InputEvent(kind="key", key="enter"))

    raw = _render_raw(reader, width=80, height=7)
    stripped = tuple(strip_control_sequences(line) for line in raw)
    match_line = next(
        line
        for line in raw
        if strip_control_sequences(line).endswith("alpha beta beta")
    )

    assert "\x1b[" in match_line
    assert any(line.endswith("alpha beta beta") for line in stripped)


def test_transcript_reader_search_does_not_highlight_without_query() -> None:
    reader = TranscriptReaderSurface(_Source((AssistantMessageRecord("alpha beta"),)))

    raw = _render_raw(reader, width=80, height=7)

    assert all("\x1b[" not in line for line in raw[:-3])


def test_transcript_reader_search_escape_exits_search_input_without_closing() -> None:
    reader = TranscriptReaderSurface(_Source((AssistantMessageRecord("alpha beta"),)))

    reader.handle_input(InputEvent(kind="text", text="/"))
    reader.handle_input(InputEvent(kind="text", text="beta"))

    assert reader.handle_input(InputEvent(kind="key", key="esc")) == InputIntent(
        kind="consumed",
        note="transcript_reader",
    )
    rendered = _render_text(reader, width=80, height=7)
    assert rendered[0] == "Transcript window"
    assert "Search: beta" not in rendered
