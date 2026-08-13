from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from loushang.ai import TextPart
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.harnesstui.conversation.agent_binding import (
    build_agent_screen_conversation_projection,
)
from loushang.tui import ProcessTerminalPort, RenderLoop, TerminalSize, TuiRuntime


def _assistant(text: str = "") -> object:
    return type(
        "Assistant",
        (),
        {
            "role": "assistant",
            "content": [TextPart(type="text", text=text)] if text else [],
            "stop_reason": "stop",
            "error_message": None,
        },
    )()


def _render_compact_playback(*, ready_file: Path) -> None:
    app = ScreenCodingTuiApp(
        model_label="kimi",
        cwd="/repo",
        branch="main",
        session_label="pty-compact",
        now=lambda: 3.0,
    )
    terminal = ProcessTerminalPort(
        output=sys.stdout,
        size_provider=lambda: TerminalSize(columns=80, rows=18),
        track_screen=False,
    )
    runtime = TuiRuntime(render_loop=RenderLoop(app), terminal=terminal)
    projector = build_agent_screen_conversation_projection(app)

    app.start_prompt("PTY compact playback", started_at=0.0)
    runtime.render_now()
    app.begin_assistant()
    for index in range(1, 81):
        app.append_assistant_chunk(f"PLAYBACK_EARLY_{index:03d}\n")
        runtime.render_now()
    app.end_assistant()
    app.complete_run(elapsed_seconds=1.0)
    runtime.render_now()

    projector.handle({"type": "compaction_start", "reason": "threshold"})
    runtime.render_now()
    projector.handle(
        {
            "type": "compaction_end",
            "reason": "threshold",
            "result": {
                "summary": "hidden summary line one\nhidden summary line two",
                "first_kept_entry_id": "entry-100",
                "tokens_before": 500_000,
            },
        }
    )
    runtime.render_now()

    app.start_prompt("continue after compact", started_at=0.0)
    runtime.render_now()
    projector.handle({"type": "message_start", "message": _assistant()})
    streamed_text = ""
    for index in range(1, 41):
        line = f"AFTER_COMPACT_{index:03d}"
        delta = f"{line}\n" if index < 40 else line
        split_at = min(7, len(delta))
        for chunk in (delta[:split_at], delta[split_at:]):
            if not chunk:
                continue
            streamed_text += chunk
            projector.handle(
                {
                    "type": "message_update",
                    "message": _assistant(streamed_text),
                    "assistant_message_event": {
                        "type": "text_delta",
                        "delta": chunk,
                    },
                }
            )
        runtime.render_now()
    projector.handle({"type": "message_end", "message": _assistant(streamed_text)})
    runtime.render_now()

    ready_file.touch()
    while True:
        time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    _render_compact_playback(ready_file=args.ready_file)


if __name__ == "__main__":
    main()
