from __future__ import annotations

import runpy
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.tui import (
    RenderConstraints,
    RenderResult,
)

_EXAMPLE = (
    Path(__file__).parents[2] / "examples" / "tui" / "31_native_coding_markdown_perf.py"
)
_TRIM_INTERACTIVE_EXAMPLE = (
    Path(__file__).parents[2]
    / "examples"
    / "tui"
    / "33_native_coding_markdown_perf_trim_interactive.py"
)


def test_markdown_perf_fixture_starts_a_new_block_every_twenty_lines() -> None:
    namespace = runpy.run_path(str(_EXAMPLE))
    markdown_line = namespace["_markdown_line"]
    markdown = "".join(markdown_line(index) for index in range(1, 42))
    tokens = MarkdownIt("commonmark").parse(markdown)

    assert (
        sum(token.type == "heading_open" and token.level == 0 for token in tokens) == 3
    )
    assert (
        sum(token.type == "bullet_list_open" and token.level == 0 for token in tokens)
        == 3
    )


@pytest.mark.tui_render_contract
def test_markdown_perf_render_stats_do_not_iterate_render_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(_EXAMPLE))
    app_class = namespace["PerfScreenCodingTuiApp"]
    lines = _LengthOnlyLines(7)
    expected = RenderResult(lines=lines)
    monkeypatch.setattr(
        ScreenCodingTuiApp,
        "render",
        lambda _app, _constraints: expected,
    )
    app = app_class(
        model_label="fake-model",
        cwd="/repo",
        branch="markdown-perf",
        session_label="test",
    )

    result = app.render(RenderConstraints(width=80, max_height=32))

    assert result is expected
    assert app.render_stats.calls == 1
    assert app.render_stats.last_line_count == 7


@pytest.mark.tui_render_contract
def test_markdown_perf_script_summary_retains_only_the_last_step() -> None:
    namespace = runpy.run_path(str(_EXAMPLE))
    summary_fields = {item.name for item in fields(namespace["ScriptRoundSummary"])}

    assert "last_step" in summary_fields
    assert "steps" not in summary_fields


def test_markdown_perf_example_runs_against_screen_tui() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(_EXAMPLE),
            "--script-count",
            "4",
            "--stream-seconds",
            "0",
            "--script-render-interval-ms",
            "0",
            "--script-render-every-n-chunks",
            "2",
            "--show-final",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "requested_lines=4" in completed.stdout
    assert "markdown_lines_per_block=20" in completed.stdout
    assert "render_every_n_chunks=2" in completed.stdout
    assert "render_calls=2" in completed.stdout
    assert "frames=4" in completed.stdout
    assert "contains_first_line=True" in completed.stdout
    assert "contains_last_line=True" in completed.stdout
    positions = [completed.stdout.index(f"Line {index}:") for index in range(1, 5)]
    assert positions == sorted(positions)


def test_markdown_perf_trim_interactive_example_loads_screen_app() -> None:
    completed = subprocess.run(
        [sys.executable, str(_TRIM_INTERACTIVE_EXAMPLE), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--active-line-budget" in completed.stdout


class _LengthOnlyLines:
    def __init__(self, length: int) -> None:
        self._length = length

    def __len__(self) -> int:
        return self._length

    def __iter__(self) -> None:
        raise AssertionError("performance render stats must not iterate rendered lines")

    def __getitem__(self, _index: object) -> None:
        raise AssertionError("performance render stats must not index rendered lines")
