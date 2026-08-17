from __future__ import annotations

import argparse
import asyncio
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.application.run_in_terminal import run_in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.styles import Style

REPO_ROOT = Path(__file__).resolve().parents[2]


INTRO = """\
Inline terminal composer demo

This example keeps prompt_toolkit on the primary terminal screen:
- finished transcript blocks are written to real stdout, so terminal scrollback works
- streaming text is buffered in memory and only a short live tail is shown
- the composer stays at the bottom, with one blank line above the status bar

Commands: /help, /error, /verbose, /quiet, /exit
"""


@dataclass
class DemoOptions:
    delay: float
    max_live_chars: int
    verbose: bool


@dataclass
class DemoState:
    running: bool = False
    started_at: float | None = None
    live_tail: str = ""
    status_message: str = "model=faux-inline | enter send | ctrl-j newline | /exit quit"
    turns: int = 0
    verbose: bool = False


class InlineTerminalAssistantDemo:
    def __init__(self, options: DemoOptions) -> None:
        self.options = options
        self.state = DemoState(verbose=options.verbose)
        self.input_buffer = Buffer(
            multiline=True,
            read_only=Condition(lambda: self.state.running),
        )
        self.current_task: asyncio.Task[None] | None = None
        self.app = self._build_application()

    async def run(self) -> int:
        self._write_block(INTRO)
        result = await self.app.run_async()
        return int(result or 0)

    def _build_application(self) -> Application[int]:
        key_bindings = self._build_key_bindings()
        live_line = ConditionalContainer(
            Window(
                FormattedTextControl(self._render_live_line),
                height=1,
                style="class:working",
            ),
            filter=Condition(lambda: self.state.running),
        )
        composer = Window(
            BufferControl(
                buffer=self.input_buffer,
                input_processors=[BeforeInput([("class:prompt", "> ")])],
                focusable=True,
            ),
            height=self._composer_height,
            wrap_lines=True,
            style="class:composer",
        )
        layout = Layout(
            HSplit(
                [
                    live_line,
                    composer,
                    Window(height=1),
                    Window(
                        FormattedTextControl(self._render_status_bar),
                        height=1,
                        style="class:status",
                    ),
                ]
            ),
            focused_element=composer,
        )
        return Application(
            layout=layout,
            key_bindings=key_bindings,
            full_screen=False,
            erase_when_done=True,
            refresh_interval=0.1,
            style=Style.from_dict(
                {
                    "composer": "#d7d7d7",
                    "prompt": "#8bd5ff bold",
                    "working": "#ffd75f",
                    "status": "bg:#303030 #d7d7d7",
                    "status.key": "bg:#303030 #8bd5ff bold",
                    "status.warn": "bg:#303030 #ffaf5f bold",
                }
            ),
        )

    def _build_key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("enter")
        def _submit(event: Any) -> None:
            del event
            self._submit_buffer()

        @bindings.add("c-j")
        def _insert_newline(event: Any) -> None:
            del event
            if not self.state.running:
                self.input_buffer.insert_text("\n")

        @bindings.add("escape")
        def _interrupt(event: Any) -> None:
            del event
            if self.current_task is not None and not self.current_task.done():
                self.current_task.cancel()
                self.state.status_message = "interrupt requested"
            else:
                self.state.status_message = "nothing running | type /exit to quit"
            self.app.invalidate()

        @bindings.add("c-c")
        def _ctrl_c(event: Any) -> None:
            del event
            if self.current_task is not None and not self.current_task.done():
                self.current_task.cancel()
                self.state.status_message = "interrupt requested"
            else:
                self.app.exit(result=130)
            self.app.invalidate()

        @bindings.add("c-d")
        def _ctrl_d(event: Any) -> None:
            del event
            if not self.input_buffer.text and not self.state.running:
                self.app.exit(result=0)

        return bindings

    def _submit_buffer(self) -> None:
        if self.state.running:
            self.state.status_message = "assistant is running | esc to interrupt"
            self.app.invalidate()
            return

        prompt = self.input_buffer.text.strip()
        self.input_buffer.reset(document=Document(""))
        if not prompt:
            self.state.status_message = "empty prompt ignored"
            self.app.invalidate()
            return

        if prompt == "/exit":
            self.app.exit(result=0)
            return
        if prompt == "/verbose":
            self.state.verbose = True
            self.state.status_message = "diagnostics enabled"
            self.app.invalidate()
            return
        if prompt == "/quiet":
            self.state.verbose = False
            self.state.status_message = "diagnostics disabled"
            self.app.invalidate()
            return

        self.current_task = asyncio.create_task(self._run_turn(prompt))

    async def _run_turn(self, prompt: str) -> None:
        self.state.turns += 1
        await self._emit_transcript(self._format_user_prompt(prompt))

        self.state.running = True
        self.state.started_at = time.monotonic()
        self.state.live_tail = ""
        self.state.status_message = "streaming response"
        self.app.invalidate()

        chunks: list[str] = []
        try:
            async for chunk in self._fake_stream(prompt):
                chunks.append(chunk)
                self.state.live_tail = self._tail("".join(chunks))
                self.app.invalidate()
                await asyncio.sleep(self.options.delay)
        except asyncio.CancelledError:
            elapsed = self._elapsed()
            self._finish_live_state("interrupted")
            await self._emit_transcript(f"\n─ Interrupted after {elapsed:.1f}s ─\n")
            return
        except Exception as exc:
            elapsed = self._elapsed()
            self._finish_live_state("failed")
            await self._emit_transcript(self._format_error(exc, elapsed))
            return

        elapsed = self._elapsed()
        self._finish_live_state("idle")
        answer = "".join(chunks).rstrip()
        await self._emit_transcript(
            f"\nAssistant:\n{textwrap.indent(answer, '  ')}\n\n─ Worked for {elapsed:.1f}s ─\n"
        )

    async def _fake_stream(self, prompt: str):
        if prompt == "/help":
            response = """\
This is an offline prompt_toolkit rendering sample.

Try:
- paste several lines, then press Enter to submit them as one prompt
- type /error to see concise error handling
- type /verbose, then /error, to see diagnostics output
- press Esc while the working line is visible to interrupt the turn
"""
        elif prompt == "/error":
            raise RuntimeError("simulated provider failure: upstream closed the stream")
        else:
            response = f"""\
Received {len(prompt.splitlines())} input line(s).

Tool output:
  $ pwd
  {REPO_ROOT}

Rendering notes:
- no stream token was printed directly to stdout
- the live line displayed only a short tail while chunks arrived
- this final answer was committed as a stable transcript block
"""

        for token in _chunk_text(response):
            yield token

    async def _emit_transcript(self, text: str) -> None:
        await run_in_terminal(lambda: self._write_block(text), render_cli_done=False)

    def _write_block(self, text: str) -> None:
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()

    def _format_user_prompt(self, prompt: str) -> str:
        return f"\nUser:\n{textwrap.indent(prompt, '  ')}\n"

    def _format_error(self, exc: Exception, elapsed: float) -> str:
        summary = f"\nError: {exc}\n─ Failed after {elapsed:.1f}s ─\n"
        if not self.state.verbose:
            return summary
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return f"{summary}\nDiagnostics:\n{textwrap.indent(details.rstrip(), '  ')}\n"

    def _finish_live_state(self, status: str) -> None:
        self.state.running = False
        self.state.started_at = None
        self.state.live_tail = ""
        self.state.status_message = f"{status} | turns={self.state.turns} | /exit quit"
        self.app.invalidate()

    def _elapsed(self) -> float:
        if self.state.started_at is None:
            return 0.0
        return time.monotonic() - self.state.started_at

    def _tail(self, text: str) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= self.options.max_live_chars:
            return normalized
        return "..." + normalized[-self.options.max_live_chars :]

    def _composer_height(self) -> Dimension:
        lines = max(1, self.input_buffer.document.line_count)
        return Dimension.exact(min(lines, 8))

    def _render_live_line(self) -> AnyFormattedText:
        elapsed = self._elapsed()
        suffix = f" | {self.state.live_tail}" if self.state.live_tail else ""
        return [("class:working", f"◦ Working ({elapsed:.1f}s • esc to interrupt){suffix}")]

    def _render_status_bar(self) -> AnyFormattedText:
        mode = "verbose" if self.state.verbose else "quiet"
        return [
            ("class:status", " "),
            ("class:status.key", "loushang-tui"),
            ("class:status", f" | {self.state.status_message} | diagnostics={mode} "),
        ]


def _chunk_text(text: str, size: int = 18) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def _parse_args(argv: list[str]) -> DemoOptions:
    parser = argparse.ArgumentParser(
        description="Demonstrate an inline terminal coding-assistant composer with prompt_toolkit."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.08,
        help="Seconds between fake stream chunks.",
    )
    parser.add_argument(
        "--max-live-chars",
        type=int,
        default=72,
        help="Maximum stream tail shown in the live line.",
    )
    parser.add_argument(
        "--verbose",
        "--diagnostics",
        action="store_true",
        help="Print tracebacks for demo errors.",
    )
    args = parser.parse_args(argv)
    return DemoOptions(
        delay=max(0.0, args.delay),
        max_live_chars=max(16, args.max_live_chars),
        verbose=bool(args.verbose),
    )


async def main(argv: list[str] | None = None) -> int:
    options = _parse_args(sys.argv[1:] if argv is None else argv)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.stderr.write("This example needs an interactive terminal.\n")
        return 2
    return await InlineTerminalAssistantDemo(options).run()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
