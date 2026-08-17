from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from loushang.coding.presentation.tui.history import (
    load_persisted_session_history_records,
)
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harnesstui.testing.performance import (
    build_synthetic_long_transcript_records,
    characterize_long_transcript_rendering,
)
from loushang.tui import RenderLoop


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe native coding TUI performance with a long transcript."
    )
    parser.add_argument(
        "--session-file",
        help="load transcript records from a persisted coding session jsonl file",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=180,
        help="synthetic turns to generate when --session-file is not set",
    )
    parser.add_argument(
        "--tail-tool-output-lines",
        type=int,
        default=2400,
        help="tool output lines in the synthetic tail record",
    )
    parser.add_argument("--width", type=int, default=100, help="terminal width")
    parser.add_argument("--height", type=int, default=30, help="terminal height")
    parser.add_argument(
        "--composer-text",
        default="hello",
        help="composer text to apply before measuring the second render",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.session_file:
        records = asyncio.run(
            load_persisted_session_history_records(Path(args.session_file))
        )
        source = str(Path(args.session_file).expanduser().resolve())
    else:
        records = build_synthetic_long_transcript_records(
            turns=max(1, args.turns),
            tail_tool_output_lines=max(1, args.tail_tool_output_lines),
        )
        source = (
            f"synthetic turns={max(1, args.turns)} "
            f"tail_tool_output_lines={max(1, args.tail_tool_output_lines)}"
        )

    app = ScreenCodingTuiApp(
        model_label="fake-model",
        cwd="/repo",
        branch="main",
        session_label="perf-probe",
    )
    app.replace_transcript_window(records, reason="perf_probe")
    render_loop = RenderLoop(screen_root=app)

    first = characterize_long_transcript_rendering(
        app,
        width=max(10, args.width),
        height=max(5, args.height),
        render_loop=render_loop,
        commit_plan=True,
    )
    second = characterize_long_transcript_rendering(
        app,
        width=max(10, args.width),
        height=max(5, args.height),
        composer_text=args.composer_text,
        render_loop=render_loop,
        commit_plan=True,
    )

    print("Native coding TUI long transcript perf probe")
    print(f"source={source}")
    print(f"records={len(records)}")
    print(f"width={max(10, args.width)} height={max(5, args.height)}")
    print()
    print("first_render")
    print(f"  visible_render_ms={first.visible_render_ms:.2f}")
    print(f"  visible_render_line_count={first.visible_render_line_count}")
    print(f"  render_loop_plan_ms={first.render_loop_plan_ms:.2f}")
    print(f"  render_loop_logical_line_count={first.render_loop_logical_line_count}")
    print(f"  render_loop_operation_class={first.render_loop_operation_class}")
    print(f"  changed_line_range={first.changed_line_range}")
    print()
    print("after_composer_update")
    print(f"  visible_render_ms={second.visible_render_ms:.2f}")
    print(f"  visible_render_line_count={second.visible_render_line_count}")
    print(f"  render_loop_plan_ms={second.render_loop_plan_ms:.2f}")
    print(f"  render_loop_logical_line_count={second.render_loop_logical_line_count}")
    print(f"  render_loop_operation_class={second.render_loop_operation_class}")
    print(f"  changed_line_range={second.changed_line_range}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
