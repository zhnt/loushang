from __future__ import annotations

import pytest

from loushang.harnesstui.conversation.transcript_style import (
    apply_transcript_style,
)
from loushang.tui.cell_width import strip_control_sequences, visible_width
from loushang.tui.theme import ThemeResolver
from loushang.tui.transcript import (
    ErrorRecord,
    ToolExecutionRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)


@pytest.fixture
def theme() -> ThemeResolver:
    return ThemeResolver(
        defaults={
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


def _tool() -> ToolExecutionRecord:
    return ToolExecutionRecord(
        name="git status",
        state="completed",
        elapsed_seconds=0.12,
    )


def test_transcript_style_returns_original_line_when_not_applicable(
    theme: ThemeResolver,
) -> None:
    line = "".join(("unchanged", " line"))

    assert (
        apply_transcript_style(
            line,
            _tool(),
            theme=None,
            capabilities=None,
        )
        is line
    )
    assert (
        apply_transcript_style(
            line,
            UserPromptRecord("question"),
            theme=theme,
            capabilities=None,
        )
        is line
    )
    assert (
        apply_transcript_style(
            line,
            _tool(),
            theme=theme,
            capabilities=None,
        )
        is line
    )


def test_transcript_style_colors_divider_and_error_records(
    theme: ThemeResolver,
) -> None:
    divider = apply_transcript_style(
        "─ Worked for 1.00s ─",
        WorkedDividerRecord(1.0),
        theme=theme,
        capabilities=None,
    )
    error = apply_transcript_style(
        "■ Error: failed",
        ErrorRecord("failed"),
        theme=theme,
        capabilities=None,
    )

    assert divider == "\x1b[2;90m─ Worked for 1.00s ─\x1b[22;39m"
    assert error == "\x1b[31m■ Error: failed\x1b[39m"


@pytest.mark.parametrize("marker", ("•", "■"))
def test_transcript_style_marks_tool_heading_verb_flags_and_timing(
    marker: str,
    theme: ThemeResolver,
) -> None:
    line = f"{marker} Ran git status --short --branch took 0.12s"

    styled = apply_transcript_style(
        line,
        _tool(),
        theme=theme,
        capabilities=None,
    )

    marker_ansi = (
        "\x1b[1;96m•\x1b[22;39m" if marker == "•" else "\x1b[1;31m■\x1b[22;39m"
    )
    assert marker_ansi in styled
    assert "\x1b[1mRan\x1b[22m" in styled
    assert "\x1b[96m--short\x1b[39m" in styled
    assert "\x1b[96m--branch\x1b[39m" in styled
    assert "\x1b[2;90mtook 0.12s\x1b[22;39m" in styled
    assert strip_control_sequences(styled) == line
    assert visible_width(styled) == visible_width(line)


def test_transcript_style_marks_connectors_actions_and_generic_metadata(
    theme: ThemeResolver,
) -> None:
    lines = (
        "  └ Read theme.py",
        "    Search transcript",
        "  │ (no output)",
        "    … +4 lines",
        "    ... (6 hidden lines)",
        "    Elapsed 2.5s",
    )

    styled = tuple(
        apply_transcript_style(
            line,
            _tool(),
            theme=theme,
            capabilities=None,
        )
        for line in lines
    )

    assert "\x1b[2;90m└\x1b[22;39m" in styled[0]
    assert "\x1b[96mRead\x1b[39m" in styled[0]
    assert "\x1b[96mSearch\x1b[39m" in styled[1]
    assert "\x1b[2;90m│\x1b[22;39m" in styled[2]
    assert "\x1b[2;90m(no output)\x1b[22;39m" in styled[2]
    assert "\x1b[2;90m… +4 lines\x1b[22;39m" in styled[3]
    assert "\x1b[2;90m... (6 hidden lines)\x1b[22;39m" in styled[4]
    assert "\x1b[2;90mElapsed 2.5s\x1b[22;39m" in styled[5]
    assert tuple(strip_control_sequences(line) for line in styled) == lines
    assert tuple(visible_width(line) for line in styled) == tuple(
        visible_width(line) for line in lines
    )


def test_transcript_style_keeps_overlapping_git_metadata_as_one_span(
    theme: ThemeResolver,
) -> None:
    line = "  └ nothing to commit took 1.0s"

    styled = apply_transcript_style(
        line,
        _tool(),
        theme=theme,
        capabilities=None,
    )

    assert strip_control_sequences(styled) == line
    assert styled.count("\x1b[2;90m") == 2
    assert "\x1b[2;90mnothing to commit took 1.0s\x1b[22;39m" in styled
