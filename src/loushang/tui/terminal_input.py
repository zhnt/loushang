from __future__ import annotations

import asyncio
import importlib
import os
import select
import sys
import threading
import time
import weakref
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from io import StringIO
from typing import Any, Literal, Protocol, TextIO

from loushang.tui.keyboard_protocol import KeyboardProtocolController

_WINDOWS_EXTENDED_KEY_SEQUENCES = {
    "H": "\x1b[A",
    "P": "\x1b[B",
    "M": "\x1b[C",
    "K": "\x1b[D",
    "G": "\x1b[H",
    "O": "\x1b[F",
    "R": "\x1b[2~",
    "S": "\x1b[3~",
    "I": "\x1b[5~",
    "Q": "\x1b[6~",
    ";": "\x1bOP",
    "<": "\x1bOQ",
    "=": "\x1bOR",
    ">": "\x1bOS",
    "?": "\x1b[15~",
    "@": "\x1b[17~",
    "A": "\x1b[18~",
    "B": "\x1b[19~",
    "C": "\x1b[20~",
    "D": "\x1b[21~",
    "E": "\x1b[23~",
    "F": "\x1b[24~",
}
_WINDOWS_TTY_READ_FUTURES: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Future[str]
] = weakref.WeakKeyDictionary()


class RuntimeLike(Protocol):
    def request_next_animation_frame(self) -> Any: ...
    def render_now(self) -> Any: ...


InputChunkReader = Callable[[TextIO], Awaitable[str]]


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
    _fd: int | None = None
    _original_attrs: list[Any] | None = None
    _termios: Any | None = None
    _enabled: bool = False
    _keyboard_controller: KeyboardProtocolController | None = None

    def __enter__(self) -> TerminalInputMode:
        if not stream_is_tty(self.stdin):
            return self
        if _is_windows_console_platform():
            self._enabled = True
            self._write_enter_sequences()
            return self
        posix_terminal_modules = _load_posix_terminal_modules()
        if posix_terminal_modules is None:
            return self
        termios_module, tty_module = posix_terminal_modules
        self._fd = self.stdin.fileno()
        self._termios = termios_module
        self._original_attrs = termios_module.tcgetattr(self._fd)
        tty_module.setcbreak(self._fd)
        attrs = [*self._original_attrs[:6], list(self._original_attrs[6])]
        attrs[0] &= ~getattr(termios_module, "ICRNL", 0)
        attrs[3] &= ~(
            termios_module.ECHO
            | termios_module.ICANON
            | getattr(termios_module, "ISIG", 0)
            | getattr(termios_module, "IEXTEN", 0)
        )
        attrs[6][termios_module.VMIN] = 1
        attrs[6][termios_module.VTIME] = 0
        termios_module.tcsetattr(self._fd, termios_module.TCSADRAIN, attrs)
        self._write_enter_sequences()
        self._enabled = True
        return self

    def __exit__(
        self, exc_type: object, exc: object, traceback: object
    ) -> Literal[False]:
        del exc_type, exc, traceback
        if not self._enabled:
            return False
        try:
            if self.drain_on_exit:
                drain_input(
                    self.stdin,
                    max_bytes=self.drain_limit,
                    idle_timeout=self.drain_idle_timeout,
                    max_duration=self.drain_max_duration,
                )
            self._write_exit_sequences()
        finally:
            if (
                self._fd is not None
                and self._original_attrs is not None
                and self._termios is not None
            ):
                self._termios.tcsetattr(
                    self._fd, self._termios.TCSADRAIN, self._original_attrs
                )
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
    if _is_windows_console_platform():
        return _drain_windows_tty_input(
            stdin,
            max_bytes=max_bytes,
            idle_timeout=idle_timeout,
            max_duration=max_duration,
            now=now,
        )
    fd = stdin.fileno()
    drained = bytearray()
    deadline = None if max_duration is None else now() + max(0.0, max_duration)
    while len(drained) < max_bytes:
        timeout = idle_timeout
        if deadline is not None:
            remaining = deadline - now()
            if remaining <= 0:
                break
            timeout = min(timeout, remaining)
        try:
            readable, _, _ = select.select([fd], [], [], timeout)
        except (OSError, ValueError):
            break
        if not readable:
            break
        chunk = os.read(fd, min(1024, max_bytes - len(drained)))
        if not chunk:
            break
        drained.extend(chunk)
    return bytes(drained).decode("utf-8", errors="replace")


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
        if _is_windows_console_platform():
            return await _read_windows_tty_input_chunk_async(stdin)
        return await _read_tty_input_chunk_async(stdin)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _read_input_chunk_blocking, stdin)


async def _read_tty_input_chunk_async(stdin: Any) -> str:
    fd = stdin.fileno()
    while True:
        try:
            readable, _, _ = select.select([fd], [], [], 0)
        except (OSError, ValueError):
            return ""
        if readable:
            return _read_tty_input_chunk(stdin)
        await asyncio.sleep(0.01)


def _read_input_chunk_blocking(stdin: Any) -> str:
    if stream_is_tty(stdin):
        if _is_windows_console_platform():
            return _read_windows_tty_input_chunk(stdin)
        return _read_tty_input_chunk(stdin)
    return stdin.read(1)


def _read_tty_input_chunk(stdin: Any) -> str:
    fd = stdin.fileno()
    first = os.read(fd, 1)
    if first == b"":
        return ""
    return (first + _read_utf8_tail(fd, first)).decode("utf-8", errors="replace")


def _read_utf8_tail(fd: int, first: bytes) -> bytes:
    needed = _utf8_sequence_length(first[0])
    tail = b""
    while len(tail) < needed - 1:
        chunk = os.read(fd, 1)
        if chunk == b"":
            break
        tail += chunk
    return tail


def _utf8_sequence_length(first_byte: int) -> int:
    if first_byte & 0b1000_0000 == 0:
        return 1
    if first_byte & 0b1110_0000 == 0b1100_0000:
        return 2
    if first_byte & 0b1111_0000 == 0b1110_0000:
        return 3
    if first_byte & 0b1111_1000 == 0b1111_0000:
        return 4
    return 1


def stream_is_tty(stream: Any) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())


def _is_windows_console_platform() -> bool:
    return sys.platform == "win32"


async def _read_windows_tty_input_chunk_async(stdin: Any) -> str:
    msvcrt = _load_windows_console_module()
    loop = asyncio.get_running_loop()
    if msvcrt is None:
        return await loop.run_in_executor(None, stdin.read, 1)
    while True:
        try:
            if (
                _WINDOWS_TTY_READ_FUTURES.get(loop) is not None
                or msvcrt.kbhit()
            ):
                return await _read_windows_tty_input_chunk_from_module_async(msvcrt)
        except (OSError, ValueError):
            return ""
        await asyncio.sleep(0.01)


def _read_windows_tty_input_chunk(stdin: Any) -> str:
    del stdin
    msvcrt = _load_windows_console_module()
    if msvcrt is None:
        return ""
    return _read_windows_tty_input_chunk_from_module(msvcrt)


async def _read_windows_tty_input_chunk_from_module_async(msvcrt: Any) -> str:
    loop = asyncio.get_running_loop()
    future = _WINDOWS_TTY_READ_FUTURES.get(loop)
    if future is None:
        future = loop.create_future()
        threading.Thread(
            target=_read_windows_tty_input_in_thread,
            args=(loop, future, msvcrt),
            name="loushang-windows-console-reader",
            daemon=True,
        ).start()
        _WINDOWS_TTY_READ_FUTURES[loop] = future
    try:
        result = await asyncio.shield(future)
    except asyncio.CancelledError:
        if future.cancelled() and _WINDOWS_TTY_READ_FUTURES.get(loop) is future:
            del _WINDOWS_TTY_READ_FUTURES[loop]
        raise
    if _WINDOWS_TTY_READ_FUTURES.get(loop) is future:
        del _WINDOWS_TTY_READ_FUTURES[loop]
    return result


def _read_windows_tty_input_in_thread(
    loop: asyncio.AbstractEventLoop,
    future: asyncio.Future[str],
    msvcrt: Any,
) -> None:
    try:
        result = _read_windows_tty_input_chunk_from_module(msvcrt)
    except BaseException as error:
        callback = partial(_set_future_exception, future, error)
    else:
        callback = partial(_set_future_result, future, result)
    with suppress(RuntimeError):
        loop.call_soon_threadsafe(callback)


def _set_future_result(future: asyncio.Future[str], result: str) -> None:
    if not future.done():
        future.set_result(result)


def _set_future_exception(
    future: asyncio.Future[str], error: BaseException
) -> None:
    if not future.done():
        future.set_exception(error)


def _read_windows_tty_input_chunk_from_module(msvcrt: Any) -> str:
    char = msvcrt.getwch()
    if char in {"\x00", "\xe0"}:
        extended = msvcrt.getwch()
        return _WINDOWS_EXTENDED_KEY_SEQUENCES.get(extended, char + extended)
    return char


def _drain_windows_tty_input(
    stdin: Any,
    *,
    max_bytes: int,
    idle_timeout: float,
    max_duration: float | None,
    now: Callable[[], float],
) -> str:
    del stdin
    msvcrt = _load_windows_console_module()
    if msvcrt is None:
        return ""
    drained: list[str] = []
    drained_size = 0
    idle_deadline = now() + max(0.0, idle_timeout)
    max_deadline = None if max_duration is None else now() + max(0.0, max_duration)
    while drained_size < max_bytes:
        current = now()
        if max_deadline is not None and current >= max_deadline:
            break
        if current >= idle_deadline:
            break
        try:
            has_input = bool(msvcrt.kbhit())
        except (OSError, ValueError):
            break
        if not has_input:
            time.sleep(0.01)
            continue
        chunk = _read_windows_tty_input_chunk_from_module(msvcrt)
        if not chunk:
            break
        remaining = max_bytes - drained_size
        drained.append(chunk[:remaining])
        drained_size += min(len(chunk), remaining)
        idle_deadline = now() + max(0.0, idle_timeout)
    return "".join(drained)


def _load_posix_terminal_modules() -> tuple[Any, Any] | None:
    try:
        return importlib.import_module("termios"), importlib.import_module("tty")
    except ModuleNotFoundError:
        return None


def _load_windows_console_module() -> Any | None:
    try:
        return importlib.import_module("msvcrt")
    except ModuleNotFoundError:
        return None


__all__ = [
    "TerminalInputMode",
    "drain_input",
    "read_input_chunk",
    "read_input_chunk_or_render_tick",
    "stream_is_tty",
]
