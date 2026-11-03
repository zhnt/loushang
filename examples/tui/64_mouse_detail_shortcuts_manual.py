"""Manual mouse, detail, and clipboard exercise across terminal transports.

Run from this worktree:
PYTHONPATH=src /home/dev/lsspace/loushang/.venv/bin/python examples/tui/64_mouse_detail_shortcuts_manual.py
Use --mouse-policy terminal|application|auto to compare mouse ownership.
Inside tmux, compare `set -g mouse on` and `set -g mouse off`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import cast

from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_input import build_screen_input_router
from loushang.harnesstui.conversation.screen_runner import (
    ConversationInputRouterFactoryPort,
    run_conversation_screen,
)
from loushang.tui.mouse_policy import MousePolicy
from loushang.tui.transcript import AssistantMessageRecord, ToolExecutionRecord


async def main(policy: MousePolicy) -> int:
    app = ScreenCodingTuiApp(
        model_label="manual",
        cwd=str(Path.cwd()),
        branch="mouse-demo",
        session_label="manual",
    )
    app.state.records.append(
        AssistantMessageRecord(
            "\n".join(f"Older transcript line {index}" for index in range(36))
        )
    )
    app.state.records.append(
        AssistantMessageRecord(
            "Try F4, ↑/↓, Enter, Esc; click Show Detail/Show Less; drag to copy; "
            "Ctrl+O copies this answer; Ctrl+T opens the transcript; /quit exits."
        )
    )
    for index in range(3):
        app.state.upsert_tool_record(
            f"demo-{index}",
            ToolExecutionRecord(
                name=f"demo command {index}",
                state="completed",
                elapsed_seconds=0.2,
                command="python demo.py",
                expanded_command=f"python demo.py --item {index} --show-all\n"
                + "detail\n" * 12,
                output="preview output",
                expanded_output=f"full output for item {index}\n"
                + "result line\n" * 12,
            ),
        )

    async def handle_prompt(text: str) -> None:
        app.begin_assistant()
        app.end_assistant(f"Completed answer for: {text}")

    return await run_conversation_screen(
        app=app,
        stdin=sys.stdin,
        stdout=sys.stdout,
        handle_prompt=handle_prompt,
        on_abort=lambda: None,
        should_exit=lambda text: text == "/quit",
        input_router_factory=cast(
            ConversationInputRouterFactoryPort, build_screen_input_router
        ),
        interruption_message="Interrupted",
        cancellation_message="Cancelled",
        mouse_policy=policy,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mouse-policy", choices=("auto", "terminal", "application"), default="auto"
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(cast(MousePolicy, args.mouse_policy))))
