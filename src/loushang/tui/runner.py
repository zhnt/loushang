from __future__ import annotations

import asyncio
import inspect
import sys
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TextIO

from loushang.tui._runner_utils import (
    configure_runtime_for_terminal_context,
    finish_tui_exit,
    flush_pending_input,
    input_events_for_chunk,
    poll_terminal_runtime,
    request_runtime_render,
    terminal_runtime_wakeup_ms,
)
from loushang.tui.input import InputEvent, InputReader
from loushang.tui.render_loop import RenderLoop
from loushang.tui.runtime import TuiRuntime
from loushang.tui.scheduler import RenderRequestKind
from loushang.tui.terminal import (
    ProcessTerminalPort,
    TerminalSize,
    terminal_size_from_environment,
)
from loushang.tui.terminal_input import (
    InputChunkReader,
    read_input_chunk_or_render_tick,
)
from loushang.tui.terminal_session import TerminalSession
from loushang.tui.tui import Tui

TuiInputHandler = Callable[
    [InputEvent, "TuiRunContext"],
    "TuiInputResult | Awaitable[TuiInputResult | None] | None",
]
TuiStartHandler = Callable[
    ["TuiRunContext"],
    "Awaitable[None] | None",
]
TerminalSessionFactory = Callable[[TextIO, TextIO], AbstractContextManager[object]]
TerminalSizeProvider = Callable[[], TerminalSize]


@dataclass(slots=True)
class TuiInputResult:
    """Input handler result for a running TUI session."""

    render_requested: bool = True
    exit_code: int | None = None


@dataclass(slots=True)
class TuiRunContext:
    """Runtime handles exposed to a TuiRunner input handler."""

    tui: Tui
    runtime: TuiRuntime
    terminal_context: object
    reader: InputReader
    _render_wakeup: asyncio.Event = field(repr=False)

    def request_render(self, kind: RenderRequestKind = "input") -> None:
        self.runtime.request_render(kind)
        self._render_wakeup.set()

    def stop(self, exit_code: int = 0) -> TuiInputResult:
        return TuiInputResult(exit_code=exit_code)


@dataclass(slots=True)
class TuiRunner:
    """Run a Tui with terminal mode setup, input parsing, rendering, and cleanup.

    During run(), the runner temporarily owns the Tui terminal/runtime/context fields
    and restores their previous values before returning. When on_input is provided it
    fully owns app event handling; call context.tui.handle_input(event) from the
    handler to use the default Tui routing path.
    """

    tui: Tui
    stdin: TextIO | None = None
    stdout: TextIO | None = None
    terminal_size_provider: TerminalSizeProvider | None = None
    terminal_session_factory: TerminalSessionFactory | None = None
    input_chunk_reader: InputChunkReader | None = None
    _running: bool = field(default=False, init=False, repr=False)

    async def run(
        self,
        on_input: TuiInputHandler | None = None,
        *,
        on_start: TuiStartHandler | None = None,
    ) -> int:
        if self._running:
            raise RuntimeError(
                "TuiRunner.run() cannot be called while the runner is already running"
            )
        self._running = True
        stdin = self.stdin if self.stdin is not None else sys.stdin
        stdout = self.stdout if self.stdout is not None else sys.stdout
        size_provider = self.terminal_size_provider or terminal_size_from_environment
        terminal = ProcessTerminalPort(
            output=stdout, size_provider=size_provider, track_screen=False
        )
        runtime = TuiRuntime(
            render_loop=RenderLoop(self.tui._screen_root), terminal=terminal
        )
        reader = InputReader()
        render_wakeup = asyncio.Event()

        previous_terminal = self.tui.terminal
        previous_runtime = self.tui._runtime
        previous_context = self.tui.terminal_context
        previous_progress_reporter = self.tui._progress_reporter

        self.tui.attach_terminal(terminal)
        self.tui._runtime = runtime
        session_factory = (
            self.terminal_session_factory or _default_terminal_session_factory
        )
        try:
            with session_factory(stdin, stdout) as terminal_context:
                self.tui.terminal_context = terminal_context
                configure_runtime_for_terminal_context(runtime, terminal_context)
                context = TuiRunContext(
                    tui=self.tui,
                    runtime=runtime,
                    terminal_context=terminal_context,
                    reader=reader,
                    _render_wakeup=render_wakeup,
                )
                if on_start is not None:
                    start_result = on_start(context)
                    if inspect.isawaitable(start_result):
                        await start_result
                runtime.render_now()
                while True:
                    data = await read_input_chunk_or_render_tick(
                        stdin,
                        runtime=runtime,
                        active_task=None,
                        input_chunk_reader=self.input_chunk_reader,
                        render_wakeup=render_wakeup,
                        pending_input_idle_ms=10 if reader.has_pending else None,
                        idle_wakeup_ms=terminal_runtime_wakeup_ms(terminal_context),
                    )
                    if data is None:
                        poll_terminal_runtime(terminal_context)
                        if not reader.has_pending:
                            continue
                        input_events = flush_pending_input(
                            reader, terminal_context=terminal_context
                        )
                    elif data == "" and reader.has_pending:
                        input_events = flush_pending_input(
                            reader, terminal_context=terminal_context
                        )
                    elif data == "":
                        runtime.render_now()
                        return finish_tui_exit(
                            runtime=runtime, stdout=stdout, exit_code=0
                        )
                    else:
                        input_events = input_events_for_chunk(
                            reader, data, terminal_context=terminal_context
                        )

                    for event in input_events:
                        result = await _dispatch_input(
                            event, context=context, on_input=on_input
                        )
                        if result.exit_code is not None:
                            if result.render_requested:
                                runtime.render_now()
                            return finish_tui_exit(
                                runtime=runtime,
                                stdout=stdout,
                                exit_code=result.exit_code,
                            )
                        if result.render_requested:
                            request_runtime_render(runtime, "input")
        finally:
            self.tui.terminal = previous_terminal
            self.tui._runtime = previous_runtime
            self.tui.terminal_context = previous_context
            self.tui._progress_reporter = previous_progress_reporter
            self._running = False


async def _dispatch_input(
    event: InputEvent,
    *,
    context: TuiRunContext,
    on_input: TuiInputHandler | None,
) -> TuiInputResult:
    if on_input is None:
        context.tui.handle_input(event)
        return TuiInputResult()
    result = on_input(event, context)
    if inspect.isawaitable(result):
        result = await result
    if result is None:
        return TuiInputResult()
    if isinstance(result, TuiInputResult):
        return result
    raise TypeError("on_input must return TuiInputResult or None")


def _default_terminal_session_factory(stdin: TextIO, stdout: TextIO) -> TerminalSession:
    return TerminalSession(stdin=stdin, stdout=stdout)


__all__ = [
    "TerminalSessionFactory",
    "TerminalSizeProvider",
    "TuiInputHandler",
    "TuiInputResult",
    "TuiRunContext",
    "TuiRunner",
    "TuiStartHandler",
]
