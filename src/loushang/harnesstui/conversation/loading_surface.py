"""Loading-only screen ownership; no Product preparation or terminal restoration.

Its coordinator holds the terminal lease and must join before accessing the
transferred screen state. Product preparation never runs on this owner.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import suppress
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import Any, TextIO

from loushang.harnesstui.conversation.input import ConversationExitResult
from loushang.harnesstui.conversation.loading_input import (
    LOADING_MESSAGE,
    LoadingInputRouter,
)
from loushang.harnesstui.conversation.screen_runner import (
    ConversationScreenPort,
    _flush_pending_input,
    _input_events_for_chunk,
    _poll_terminal_runtime,
    configure_runtime_for_terminal_context,
    write_startup_welcome,
)
from loushang.tui.input import InputEvent, InputReader
from loushang.tui.render_loop import RenderLoop
from loushang.tui.runtime import TuiRuntime
from loushang.tui.terminal import ProcessTerminalPort, TerminalSize
from loushang.tui.terminal_backends.posix import PosixTerminalInputReader
from loushang.tui.terminal_input import ESCAPE_SEQUENCE_IDLE_TIMEOUT_MS


@dataclass(frozen=True)
class LoadingScreenTransfer:
    app: ConversationScreenPort
    parser: InputReader
    byte_reader: PosixTerminalInputReader
    runtime: TuiRuntime
    terminal_context: Any
    pending_idle_deadline: float | None
    # Main must discharge queued input through loading policy before arming.
    submission_backlog_pending: bool = True


class LoadingSurfaceJoinTimeout(TimeoutError):
    """The loading thread is still alive; terminal ownership has not moved."""


class LoadingSurfaceWorker:
    """Exclusively borrow a loading screen until an actual joined transfer."""

    def __init__(
        self,
        *,
        app: ConversationScreenPort,
        byte_reader: PosixTerminalInputReader,
        stdout: TextIO,
        terminal_context: Any,
        size_provider: Callable[[], TerminalSize],
        on_closing: Callable[[], None] | None = None,
    ) -> None:
        self._app = app
        self._byte_reader = byte_reader
        self._stdout = stdout
        self._terminal_context = terminal_context
        self._size_provider = size_provider
        self._on_closing = on_closing
        self._stop = Event()
        self._state_lock = Lock()
        self._closing: int | None = None
        self._failure: BaseException | None = None
        self._started = False
        self._first_frame: Future[None] = Future()
        self._finished: Future[LoadingScreenTransfer] = Future()
        self._thread = Thread(
            target=self._run, name="conversation-loading", daemon=False
        )

    @property
    def closing_code(self) -> int | None:
        with self._state_lock:
            return self._closing

    def start(self) -> None:
        with self._state_lock:
            if self._started:
                raise RuntimeError("loading surface may only start once")
            self._started = True
        self._thread.start()

    def wait_first_frame(self, timeout: float) -> None:
        self._first_frame.result(timeout=timeout)

    def request_transfer(self) -> None:
        self._stop.set()

    def join(self, timeout: float) -> LoadingScreenTransfer:
        """A timeout retains worker ownership; it never authorizes restoration."""
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise LoadingSurfaceJoinTimeout(
                "loading surface has not relinquished ownership"
            )
        return self._finished.result()

    def _close(self, code: int) -> None:
        with self._state_lock:
            if self._closing is None:
                self._closing = code
        self._app.state.status_message = "Closing — waiting for preparation cleanup"
        if self._app.render_requester is not None:
            self._app.render_requester("product")
        if self._on_closing is not None:
            self._on_closing()

    def _run(self) -> None:
        try:
            state = asyncio.run(self._serve())
        except BaseException as error:
            with self._state_lock:
                self._failure = error
                if self._closing is None:
                    self._closing = 1
            if not self._first_frame.done():
                self._first_frame.set_exception(error)
            self._finished.set_exception(error)
            if self._on_closing is not None:
                self._on_closing()
        else:
            self._finished.set_result(state)

    async def _serve(self) -> LoadingScreenTransfer:
        app = self._app
        parser = InputReader()
        size = self._size_provider()
        runtime = TuiRuntime(
            render_loop=RenderLoop(app),
            terminal=ProcessTerminalPort(
                output=self._stdout,
                size_provider=self._size_provider,
                track_screen=False,
            ),
        )
        router = LoadingInputRouter(
            app=app,
            should_exit=lambda _: False,
            is_local_command=lambda _: False,
            width=size.columns,
            height=size.rows,
        )
        pending_deadline: float | None = None
        read_task: asyncio.Task[str] | None = None
        app.state.startup_pending = True
        app.state.permission_profile = None
        app.state.status_message = LOADING_MESSAGE
        app.surface_host = runtime.overlay_host()
        app.render_requester = runtime.request_render

        def route_event(event: InputEvent) -> None:
            if self.closing_code is not None:
                return
            result = router.handle(event)
            if isinstance(result, ConversationExitResult):
                self._close(result.exit_code)
            # Never execute Product actions returned by a router.
            if result.render_requested:
                runtime.request_render("input")

        def route(data: str) -> None:
            nonlocal pending_deadline
            if data == "":
                self._close(0)
                return
            events = _input_events_for_chunk(
                parser, data, terminal_context=self._terminal_context
            )
            for event in events:
                route_event(event)
            pending_deadline = (
                time.monotonic() + ESCAPE_SEQUENCE_IDLE_TIMEOUT_MS / 1000
                if parser.has_pending
                else None
            )

        try:
            configure_runtime_for_terminal_context(runtime, app, self._terminal_context)
            write_startup_welcome(app=app, runtime=runtime, stdout=self._stdout)
            runtime.render_now()
            self._first_frame.set_result(None)
            while not self._stop.is_set():
                if read_task is None and self.closing_code is None:
                    read_task = asyncio.create_task(self._byte_reader.read_chunk())
                if read_task is not None:
                    done, _ = await asyncio.wait({read_task}, timeout=0.01)
                    if read_task in done:
                        route(read_task.result())
                        read_task = None
                else:
                    await asyncio.sleep(0.01)
                if (
                    pending_deadline is not None
                    and time.monotonic() >= pending_deadline
                ):
                    for event in _flush_pending_input(
                        parser, terminal_context=self._terminal_context
                    ):
                        route_event(event)
                    pending_deadline = None
                _poll_terminal_runtime(self._terminal_context)
                next_size = self._size_provider()
                if next_size != size:
                    size = next_size
                    router.width, router.height = size.columns, size.rows
                    runtime.request_render("resize")
                if runtime.request_next_animation_frame().render_now:
                    runtime.render_now()
        finally:
            try:
                if read_task is not None:
                    if not read_task.done():
                        read_task.cancel()
                    with suppress(asyncio.CancelledError):
                        route(await read_task)
            finally:
                try:
                    router.dispose()
                finally:
                    # No old-loop callback survives transfer. No terminal mode exit,
                    # drain, parser flush or render-baseline reset belongs here.
                    app.render_requester = None
        return LoadingScreenTransfer(
            app,
            parser,
            self._byte_reader,
            runtime,
            self._terminal_context,
            pending_deadline,
        )
