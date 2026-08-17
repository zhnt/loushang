from __future__ import annotations

import argparse
import asyncio
import sys
from io import StringIO
from typing import TextIO

from loushang.coding.ui.native_app import NativeCodingTuiApp
from loushang.coding.ui.native_loop import run_native_coding_tui

from loushang.tui import RenderConstraints, strip_control_sequences
from loushang.tui.transcript import (
    AssistantMessageRecord,
    UserPromptRecord,
    WorkedDividerRecord,
)

SCRIPTED_PROMPT = "你好，请展示 native coding TUI。"


async def _fake_model_handler(app: NativeCodingTuiApp, text: str) -> int | None:
    app.begin_assistant()
    for chunk in _fake_model_chunks(text):
        app.append_assistant_chunk(chunk)
        await asyncio.sleep(0.06)
    app.end_assistant()
    return None


def _fake_model_chunks(text: str) -> tuple[str, ...]:
    return (
        "### Native coding TUI\n\n",
        f"You submitted: `{text}`\n\n",
        "- The active transcript window is bounded and product-owned.\n",
        "- The TUI render loop keeps only current logical lines plus previous rendered lines.\n",
        "- Window rebuilds request a baseline repaint instead of diffing against evicted history.\n",
        "\n```text\n",
        "currentLines          active logical screen\n",
        "previousRenderedLines last successfully flushed line array\n",
        "sessionStore          full persisted conversation outside the TUI renderer\n",
        "```\n",
    )


async def run_script(
    *,
    stdout: TextIO,
    width: int,
    height: int,
    prefix_records: int,
    active_window_records: int,
) -> int:
    app = NativeCodingTuiApp(
        model_label="fake-model",
        cwd="/repo",
        branch="feat/loushang-tui-native",
        session_label="script",
    )
    old_first = "old prompt 0"
    old_last = f"old prompt {max(0, prefix_records - 1)}"
    app.state.records.extend(UserPromptRecord(f"old prompt {index}") for index in range(prefix_records))
    pre_compaction_count = len(app.state.records)
    prefix_first_verified = bool(prefix_records == 0 or app.state.records[0] == UserPromptRecord(old_first))
    prefix_last_verified = bool(prefix_records == 0 or app.state.records[-1] == UserPromptRecord(old_last))
    prefix_checksum = sum(len(record.text) for record in app.state.records if isinstance(record, UserPromptRecord))
    expected_checksum = sum(len(f"old prompt {index}") for index in range(prefix_records))
    preflight_height = max(height, (prefix_records * 2) + 32)
    preflight_render = app.render(
        RenderConstraints(width=width, max_height=preflight_height, visible_height=height)
    )
    preflight_text = "\n".join(strip_control_sequences(line.text) for line in preflight_render.lines)
    preflight_line_count = len(preflight_render.lines)
    preflight_rendered_first = prefix_records == 0 or old_first in preflight_text
    preflight_rendered_last = prefix_records == 0 or old_last in preflight_text
    app.state.records.extend(
        [
            UserPromptRecord("recent prompt before compaction"),
            AssistantMessageRecord("recent answer before compaction"),
            WorkedDividerRecord(2.4),
        ]
    )
    app.append_context_compaction_record(
        summary=f"{prefix_records} materialized old records were compacted out of the active UI window.",
        tokens_before=prefix_records,
        max_records=active_window_records,
    )
    materialized_prefix_verified = (
        pre_compaction_count == prefix_records
        and prefix_first_verified
        and prefix_last_verified
        and prefix_checksum == expected_checksum
        and preflight_rendered_first
        and preflight_rendered_last
    )
    captured = StringIO()
    result = await run_native_coding_tui(
        app=app,
        stdin=StringIO(SCRIPTED_PROMPT + "\r"),
        stdout=captured,
        handle_prompt=lambda prompt: _fake_model_handler(app, prompt),
        on_abort=lambda: None,
        should_exit=lambda text: text in {"/quit", "/exit"},
    )

    final = app.render(RenderConstraints(width=width, max_height=height, visible_height=height))
    final_text = "\n".join(strip_control_sequences(line.text) for line in final.lines)
    stdout.write("Native coding fake-model script\n")
    stdout.write(f"exit_code={result}\n")
    stdout.write(f"materialized_prefix_records={prefix_records}\n")
    stdout.write(f"pre_compaction_record_count={pre_compaction_count}\n")
    stdout.write(f"prefix_first_verified={prefix_first_verified}\n")
    stdout.write(f"prefix_last_verified={prefix_last_verified}\n")
    stdout.write(f"prefix_checksum={prefix_checksum}\n")
    stdout.write(f"expected_checksum={expected_checksum}\n")
    stdout.write(f"preflight_render_line_count={preflight_line_count}\n")
    stdout.write(f"preflight_rendered_first={preflight_rendered_first}\n")
    stdout.write(f"preflight_rendered_last={preflight_rendered_last}\n")
    stdout.write(f"materialized_prefix_verified={materialized_prefix_verified}\n")
    stdout.write(f"evicted_prefix_records={app.state.evicted_prefix_record_count}\n")
    stdout.write(f"active_window_record_limit={active_window_records}\n")
    stdout.write(f"active_record_count={len(app.state.records)}\n")
    stdout.write(f"old_prefix_visible={old_first in final_text or old_last in final_text}\n\n")
    for line in final.lines:
        stdout.write(strip_control_sequences(line.text) + "\n")
    return result if materialized_prefix_verified else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scriptable fake-model acceptance harness for native coding TUI.")
    parser.add_argument("--script", action="store_true", help="run one fake-model prompt through the native coding loop")
    parser.add_argument("--prefix-records", type=int, default=5_000, help="old records to materialize before compaction")
    parser.add_argument("--active-window-records", type=int, default=4, help="record limit retained after fake compaction")
    parser.add_argument("--width", type=int, default=100, help="final snapshot width")
    parser.add_argument("--height", type=int, default=32, help="final snapshot height")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.script:
        print("Pass --script to run the fake-model acceptance harness.", file=sys.stderr)
        return 2
    return asyncio.run(
        run_script(
            stdout=sys.stdout,
            width=args.width,
            height=args.height,
            prefix_records=max(0, args.prefix_records),
            active_window_records=max(1, args.active_window_records),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
