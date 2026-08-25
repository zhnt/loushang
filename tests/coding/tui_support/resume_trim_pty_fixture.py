from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harnesstui.testing.performance import (
    build_synthetic_long_transcript_records,
)
from loushang.tui import ProcessTerminalPort, RenderLoop, TerminalSize, TuiRuntime
from loushang.tui.transcript import UserPromptRecord


def _render_resume_trim_playback(*, ready_file: Path) -> None:
    app = ScreenCodingTuiApp(
        model_label="faux/resume-trim",
        cwd="/repo",
        branch="main",
        session_label="pty-resume-trim",
        now=lambda: 3.0,
    )
    terminal = ProcessTerminalPort(
        output=sys.stdout,
        size_provider=lambda: TerminalSize(columns=80, rows=18),
        track_screen=False,
    )
    runtime = TuiRuntime(render_loop=RenderLoop(app), terminal=terminal)

    app.start_prompt("before live resume", started_at=0.0)
    runtime.render_now()
    app.begin_assistant()
    for index in range(1, 81):
        app.append_assistant_chunk(f"PRE_RESUME_{index:03d}\n")
        runtime.render_now()
    app.end_assistant()
    app.complete_run(elapsed_seconds=1.0)
    runtime.render_now()

    resumed_records = (
        *build_synthetic_long_transcript_records(
            turns=40,
            tail_tool_output_lines=600,
        ),
        *(
            UserPromptRecord(f"RESUMED_HISTORY_{index:03d}")
            for index in range(1, 31)
        ),
    )
    app.install_resumed_history(resumed_records)
    runtime.render_now()

    app.start_prompt("after live resume", started_at=2.0)
    runtime.render_now()
    app.begin_assistant()
    for index in range(1, 41):
        suffix = "\n" if index < 40 else ""
        app.append_assistant_chunk(f"POST_RESUME_{index:03d}{suffix}")
        runtime.render_now()
    app.end_assistant()
    app.complete_run(elapsed_seconds=1.0)
    runtime.render_now()

    ready_file.touch()
    while True:
        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    _render_resume_trim_playback(ready_file=args.ready_file)


if __name__ == "__main__":
    main()
