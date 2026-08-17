from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO, cast

from loushang.coding.ui.screen_input import (
    CODING_CANCELLATION_MESSAGE,
    CODING_INTERRUPTION_MESSAGE,
    build_screen_input_router,
)
from loushang.harnesstui.conversation.screen_runner import (
    ConversationInputRouterFactoryPort,
    run_conversation_screen,
)

if TYPE_CHECKING:
    from loushang.coding.ui.screen_app import (
        ScreenCodingTuiApp as _PerfScreenCodingTuiAppBase,
    )


_EXAMPLE_DIR = Path(__file__).parent


def _load_example(filename: str, module_name: str) -> Any:
    path = _EXAMPLE_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_perf31 = _load_example(
    "31_native_coding_markdown_perf.py", "_native_coding_markdown_perf31_for33"
)
_perf32 = _load_example(
    "32_native_coding_markdown_perf_trim.py", "_native_coding_markdown_perf32_for33"
)
if not TYPE_CHECKING:
    _PerfScreenCodingTuiAppBase = _perf31.PerfScreenCodingTuiApp


class TrimInteractiveScreenCodingTuiApp(_PerfScreenCodingTuiAppBase):
    __slots__ = ("trim_events",)

    def __init__(self, *, active_line_budget: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.active_transcript_line_budget = active_line_budget
        self.trim_events = 0

    def complete_run(self, *, elapsed_seconds: float | None = None) -> None:
        before_generation = self.state.transcript_window_generation
        before_evicted = self.state.evicted_prefix_record_count
        super().complete_run(elapsed_seconds=elapsed_seconds)
        self.trim_active_transcript_window()
        changed = (
            self.state.transcript_window_generation != before_generation
            or self.state.evicted_prefix_record_count != before_evicted
        )
        if changed:
            self.trim_events += 1
            self.set_status(
                "trimmed active window "
                f"records={len(self.state.records)} "
                f"evicted={self.state.evicted_prefix_record_count} "
                f"budget={self.active_transcript_line_budget}"
            )
        else:
            self.set_status(
                f"active window records={len(self.state.records)} budget={self.active_transcript_line_budget}"
            )


async def run_interactive(
    *,
    stdin: TextIO,
    stdout: TextIO,
    stream_seconds: float,
    active_line_budget: int,
) -> int:
    app = TrimInteractiveScreenCodingTuiApp(
        model_label="fake-model",
        cwd="/repo",
        branch="markdown-perf-trim-interactive",
        session_label="manual",
        active_line_budget=active_line_budget,
    )
    app.set_status(
        f"type 1, 10, 100... /quit exits | trim budget={active_line_budget} lines | per-turn auto trim"
    )
    return await run_conversation_screen(
        app=app,
        stdin=stdin,
        stdout=stdout,
        handle_prompt=lambda prompt: _perf31._fake_markdown_handler(
            app,
            prompt,
            stream_seconds=stream_seconds,
        ),
        on_abort=lambda: None,
        should_exit=lambda text: text.strip() in {"/quit", "/exit", "q"},
        input_router_factory=cast(
            ConversationInputRouterFactoryPort,
            build_screen_input_router,
        ),
        interruption_message=CODING_INTERRUPTION_MESSAGE,
        cancellation_message=CODING_CANCELLATION_MESSAGE,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive fake-model Markdown performance harness with per-turn active transcript trimming."
    )
    parser.add_argument(
        "--script-count",
        type=int,
        help="run scripted fake prompts instead of interactive mode",
    )
    parser.add_argument(
        "--script-rounds",
        type=int,
        default=1,
        help="number of scripted fake prompts to run",
    )
    parser.add_argument(
        "--active-line-budget",
        type=int,
        default=180,
        help="active transcript line budget applied after every completed turn",
    )
    parser.add_argument(
        "--show-final",
        action="store_true",
        help="print the final rendered snapshot in script mode",
    )
    parser.add_argument(
        "--stream-seconds",
        type=float,
        default=cast(float, _perf31.DEFAULT_STREAM_SECONDS),
        help="target fake stream duration",
    )
    parser.add_argument(
        "--script-render-interval-ms",
        type=int,
        default=80,
        help="script render coalescing interval; use 0 to render every chunk",
    )
    parser.add_argument(
        "--trace-memory",
        action="store_true",
        help="enable tracemalloc current/peak memory stats",
    )
    parser.add_argument("--width", type=int, default=100, help="script snapshot width")
    parser.add_argument("--height", type=int, default=32, help="script snapshot height")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    stream_seconds = max(0.05, args.stream_seconds)
    active_line_budget = max(1, args.active_line_budget)
    if args.script_count is not None:
        return asyncio.run(
            _perf32.run_script(
                stdout=sys.stdout,
                count=max(1, args.script_count),
                rounds=max(1, args.script_rounds),
                width=args.width,
                height=args.height,
                stream_seconds=stream_seconds,
                render_interval_ms=args.script_render_interval_ms,
                active_line_budget=active_line_budget,
                trace_memory=args.trace_memory,
                show_final=args.show_final,
            )
        )
    return asyncio.run(
        run_interactive(
            stdin=sys.stdin,
            stdout=sys.stdout,
            stream_seconds=stream_seconds,
            active_line_budget=active_line_budget,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
