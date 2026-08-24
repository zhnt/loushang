from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable, Coroutine
from contextlib import suppress
from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Literal, Protocol, TextIO

from loushang.tui.keyboard_protocol import KeyboardProtocolController
from loushang.tui.terminal_backends import (
    NativeTerminalModeLease,
    native_terminal_input_backend,
    native_terminal_mode_factory,
)


class RuntimeLike(Protocol):
    def request_next_animation_frame(self) -> Any: ...
    def render_now(self) -> Any: ...


InputChunkReader = Callable[[TextIO], Coroutine[Any, Any, str]]


@dataclass(slots=True)
class TerminalInputMode:
    stdin: Any
    stdout: TextIO
    bracketed_paste: bool = True
    focus_events: bool = True
    keyboard_protocols: bool = True
    keyboard_fallback_immediate: bool = True
    drain_on_exit: bool = True
    drain_limit: int = 4096
    drain_idle_timeout: float = 0.05
    drain_max_duration: float = 1.0
    _native_mode_lease: NativeTerminalModeLease | None = field(
        default=None, init=False, repr=False
    )
    _enabled: bool = False
    _keyboard_controller: KeyboardProtocolController | None = None

    def __enter__(self) -> TerminalInputMode:
        if not stream_is_tty(self.stdin):
            return self
        lease = native_terminal_mode_factory(sys.platform).open(self.stdin)
        if lease is None:
            return self
        self._native_mode_lease = lease
        try:
            self._write_enter_sequences()
        except BaseException:
            self._native_mode_lease = None
            lease.restore()
            raise
        self._enabled = True
        return self

    def __exit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> Literal[False]:
        del exc_type, exc, traceback
        if not self._enabled:
            return False
        self._enabled = False
        lease = self._native_mode_lease
        self._native_mode_lease = None
        try:
            try:
                if self.drain_on_exit:
                    drain_input(
                        self.stdin,
                        max_bytes=self.drain_limit,
                        idle_timeout=self.drain_idle_timeout,
                        max_duration=self.drain_max_duration,
                    )
            finally:
                self._write_exit_sequences()
        finally:
            if lease is not None:
                lease.restore()
        return False

    def _write_enter_sequences(self) -> None:
        if self.bracketed_paste:
            self.stdout.write("\x1b[?2004h")
        if self.focus_events:
            self.stdout.write("\x1b[?1004h")
        if self.keyboard_protocols:
            self._keyboard_controller = KeyboardProtocolController()
            self.stdout.write(
                "".join(self._keyboard_controller.startup_sequences(now_ms=0))
            )
            if self.keyboard_fallback_immediate:
                self.stdout.write(
                    "".join(
                        self._keyboard_controller.fallback_sequences_if_due(now_ms=150)
                    )
                )
        if self.bracketed_paste or self.focus_events or self.keyboard_protocols:
            self.stdout.flush()

    def _write_exit_sequences(self) -> None:
        if self.bracketed_paste:
            self.stdout.write("\x1b[?2004l")
        if self.focus_events:
            self.stdout.write("\x1b[?1004l")
        if self.keyboard_protocols and self._keyboard_controller is not None:
            self.stdout.write("".join(self._keyboard_controller.shutdown_sequences()))
        if self.bracketed_paste or self.focus_events or self.keyboard_protocols:
            self.stdout.flush()


def drain_input(
    stdin: Any,
    *,
    max_bytes: int = 4096,
    idle_timeout: float = 0.05,
    max_duration: float | None = 1.0,
    now: Callable[[], float] = time.monotonic,
) -> str:
    if max_bytes <= 0:
        return ""
    if isinstance(stdin, StringIO):
        return stdin.read(max_bytes)
    if not stream_is_tty(stdin):
        return ""
    return native_terminal_input_backend(sys.platform).drain(
        stdin,
        max_bytes=max_bytes,
        idle_timeout=idle_timeout,
        max_duration=max_duration,
        now=now,
    )


async def read_input_chunk_or_render_tick(
    stdin: TextIO,
    *,
    runtime: RuntimeLike,
    active_task: asyncio.Task[Any] | None,
    input_chunk_reader: InputChunkReader | None = None,
    render_wakeup: asyncio.Event | None = None,
    pending_input_idle_ms: int | None = None,
    idle_wakeup_ms: int | None = None,
) -> str | None:
    read_chunk = input_chunk_reader or read_input_chunk
    input_task = asyncio.create_task(read_chunk(stdin))
    try:
        while True:
            await asyncio.sleep(0)
            if input_task.done():
                return input_task.result()
            if active_task is not None and active_task.done():
                return None

            wait_for: set[asyncio.Task[Any]] = {input_task}
            if active_task is not None and not active_task.done():
                wait_for.add(active_task)
            render_task: asyncio.Task[bool] | None = None
            if render_wakeup is not None:
                render_task = asyncio.create_task(render_wakeup.wait())
                wait_for.add(render_task)

            decision = runtime.request_next_animation_frame()
            timeout = None
            timeout_reason = "render"
            if decision.render_now:
                runtime.render_now()
                continue
            if decision.delay_ms > 0:
                timeout = decision.delay_ms / 1000
            if pending_input_idle_ms is not None:
                pending_timeout = max(0, pending_input_idle_ms) / 1000
                if timeout is None or pending_timeout <= timeout:
                    timeout = pending_timeout
                    timeout_reason = "pending_input"
            if idle_wakeup_ms is not None:
                idle_timeout = max(0, idle_wakeup_ms) / 1000
                if timeout is None or idle_timeout <= timeout:
                    timeout = idle_timeout
                    timeout_reason = "idle_wakeup"

            done, _pending = await asyncio.wait(
                wait_for, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            render_wakeup_fired = render_task is not None and render_task in done
            if render_wakeup_fired and render_wakeup is not None:
                render_wakeup.clear()
            if render_task is not None and not render_task.done():
                render_task.cancel()
                with suppress(asyncio.CancelledError):
                    await render_task
            if input_task in done:
                return input_task.result()
            if active_task is not None and active_task in done:
                return None
            if render_wakeup_fired:
                continue
            if timeout_reason in {"pending_input", "idle_wakeup"}:
                return None
            runtime.render_now()
    finally:
        if not input_task.done():
            input_task.cancel()
            with suppress(asyncio.CancelledError):
                await input_task


async def read_input_chunk(stdin: TextIO) -> str:
    if isinstance(stdin, StringIO):
        return stdin.read(1)
    if stream_is_tty(stdin):
        return await native_terminal_input_backend(sys.platform).read_chunk(stdin)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _read_input_chunk_blocking, stdin)


def _read_input_chunk_blocking(stdin: Any) -> str:
    if stream_is_tty(stdin):
        return native_terminal_input_backend(sys.platform).read_chunk_blocking(stdin)
    return stdin.read(1)


def stream_is_tty(stream: Any) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())
__all__ = [
    "TerminalInputMode",
    "drain_input",
    "read_input_chunk",
    "read_input_chunk_or_render_tick",
    "stream_is_tty",
]
