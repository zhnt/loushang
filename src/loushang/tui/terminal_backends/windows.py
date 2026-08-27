from __future__ import annotations

import asyncio
import ctypes
import importlib
import threading
import time
import weakref
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from functools import partial
from typing import Any

_EXTENDED_KEY_SEQUENCES = {
    # msvcrt.getwch() exposes native Alt+V as NUL followed by scan code 0x2F.
    "/": "\x1bv",
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
_HIGH_SURROGATE_START = 0xD800
_HIGH_SURROGATE_END = 0xDBFF
_LOW_SURROGATE_START = 0xDC00
_LOW_SURROGATE_END = 0xDFFF
_REPLACEMENT_CHARACTER = "\ufffd"
_ESCAPE = "\x1b"
_INPUT_POLL_INTERVAL_SECONDS = 0.001
_ESCAPE_BURST_IDLE_SECONDS = 0.01
_ESCAPE_BURST_MAX_CHARS = 4096

ConsoleModuleLoader = Callable[[], Any | None]
Kernel32Loader = Callable[[], Any | None]

_ENABLE_QUICK_EDIT_MODE = 0x0040
_ENABLE_EXTENDED_FLAGS = 0x0080
_ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
_ENABLE_PROCESSED_OUTPUT = 0x0001
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_INPUT_HANDLE = -10
_STD_OUTPUT_HANDLE = -11
_KEY_EVENT = 0x0001
_RIGHT_ALT_PRESSED = 0x0001
_LEFT_ALT_PRESSED = 0x0002
_VK_MENU = 0x12
_VK_LMENU = 0xA4
_VK_RMENU = 0xA5
_VK_V = 0x56
_KEY_STATE_DOWN_MASK = 0x8000
_MAX_PEEKED_INPUT_RECORDS = 32


class _WindowsCharUnion(ctypes.Union):
    _fields_ = [
        ("UnicodeChar", ctypes.c_wchar),
        ("AsciiChar", ctypes.c_char),
    ]


class _WindowsKeyEventRecord(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", ctypes.c_int32),
        ("wRepeatCount", ctypes.c_uint16),
        ("wVirtualKeyCode", ctypes.c_uint16),
        ("wVirtualScanCode", ctypes.c_uint16),
        ("uChar", _WindowsCharUnion),
        ("dwControlKeyState", ctypes.c_uint32),
    ]


class _WindowsInputEventUnion(ctypes.Union):
    _fields_ = [
        ("KeyEvent", _WindowsKeyEventRecord),
        ("padding", ctypes.c_byte * 16),
    ]


class _WindowsInputRecord(ctypes.Structure):
    _fields_ = [
        ("EventType", ctypes.c_uint16),
        ("Event", _WindowsInputEventUnion),
    ]


def _load_console_module() -> Any | None:
    try:
        return importlib.import_module("msvcrt")
    except ModuleNotFoundError:
        return None


def _load_kernel32() -> Any | None:
    try:
        return ctypes.windll.kernel32  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None


@dataclass(slots=True)
class WindowsConsoleInput:
    """Read Windows console input without leaking UTF-16 units upstream."""

    module_loader: ConsoleModuleLoader = _load_console_module
    _read_futures: weakref.WeakKeyDictionary[
        asyncio.AbstractEventLoop, asyncio.Future[str]
    ] = field(default_factory=weakref.WeakKeyDictionary, init=False, repr=False)

    async def read_chunk(self, stdin: Any) -> str:
        console = self.module_loader()
        loop = asyncio.get_running_loop()
        if console is None:
            return await loop.run_in_executor(None, stdin.read, 1)
        while True:
            try:
                if self._read_futures.get(loop) is not None or console.kbhit():
                    return await self._read_from_module_async(console)
            except (OSError, ValueError):
                return ""
            await asyncio.sleep(_INPUT_POLL_INTERVAL_SECONDS)

    def read_chunk_blocking(self, stdin: Any) -> str:
        del stdin
        console = self.module_loader()
        if console is None:
            return ""
        return _read_from_module(console)

    def drain(
        self,
        stdin: Any,
        *,
        max_bytes: int,
        idle_timeout: float,
        max_duration: float | None,
        now: Callable[[], float],
    ) -> str:
        del stdin
        console = self.module_loader()
        if console is None:
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
                has_input = bool(console.kbhit())
            except (OSError, ValueError):
                break
            if not has_input:
                time.sleep(0.01)
                continue
            chunk = _read_from_module(console)
            if not chunk:
                break
            remaining = max_bytes - drained_size
            drained.append(chunk[:remaining])
            drained_size += min(len(chunk), remaining)
            idle_deadline = now() + max(0.0, idle_timeout)
        return "".join(drained)

    async def _read_from_module_async(self, console: Any) -> str:
        loop = asyncio.get_running_loop()
        future = self._read_futures.get(loop)
        if future is None:
            future = loop.create_future()
            threading.Thread(
                target=self._read_in_thread,
                args=(loop, future, console),
                name="loushang-windows-console-reader",
                daemon=True,
            ).start()
            self._read_futures[loop] = future
        try:
            result = await asyncio.shield(future)
        except asyncio.CancelledError:
            if future.cancelled() and self._read_futures.get(loop) is future:
                del self._read_futures[loop]
            raise
        if self._read_futures.get(loop) is future:
            del self._read_futures[loop]
        return result

    def _read_in_thread(
        self,
        loop: asyncio.AbstractEventLoop,
        future: asyncio.Future[str],
        console: Any,
    ) -> None:
        try:
            result = _read_from_module(console)
        except BaseException as error:
            callback = partial(_set_future_exception, future, error)
        else:
            callback = partial(_set_future_result, future, result)
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(callback)


WINDOWS_CONSOLE_INPUT = WindowsConsoleInput()


@dataclass(slots=True)
class WindowsConsoleMode:
    """Own Win32 console flags for exactly one terminal session."""

    kernel32_loader: Kernel32Loader = _load_kernel32
    console_module_loader: ConsoleModuleLoader = _load_console_module
    _input_handle: int | None = field(default=None, init=False, repr=False)
    _input_original_mode: int | None = field(default=None, init=False, repr=False)
    _vt_input_active: bool = field(default=False, init=False, repr=False)
    _output_handle: int | None = field(default=None, init=False, repr=False)
    _output_original_mode: int | None = field(default=None, init=False, repr=False)
    _vt_output_active: bool = field(default=False, init=False, repr=False)

    def enable_vt_input(
        self,
        stdin: object,
        *,
        preserve_native_selection: bool = False,
    ) -> bool:
        if self._input_handle is not None:
            return self._vt_input_active
        try:
            kernel32 = self.kernel32_loader()
        except Exception:
            return False
        if kernel32 is None:
            return False
        try:
            handle = ctypes.c_void_p(
                _windows_stream_handle(
                    stdin,
                    kernel32,
                    _STD_INPUT_HANDLE,
                    self.console_module_loader,
                )
            )
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            original_mode = int(mode.value)
            requested = ctypes.c_uint32(
                _windows_console_input_mode(
                    original_mode,
                    vt_input=True,
                    preserve_native_selection=preserve_native_selection,
                )
            )
            vt_enabled = bool(kernel32.SetConsoleMode(handle, requested))
            if not vt_enabled:
                fallback = ctypes.c_uint32(
                    _windows_console_input_mode(
                        original_mode,
                        vt_input=False,
                        preserve_native_selection=preserve_native_selection,
                    )
                )
                if not kernel32.SetConsoleMode(handle, fallback):
                    return False
        except Exception:
            return False
        self._input_handle = handle.value
        self._input_original_mode = original_mode
        self._vt_input_active = vt_enabled
        return self._vt_input_active

    def disable_vt_input(self) -> None:
        if self._input_handle is None or self._input_original_mode is None:
            return
        try:
            kernel32 = self.kernel32_loader()
            if kernel32 is not None:
                kernel32.SetConsoleMode(
                    ctypes.c_void_p(self._input_handle),
                    ctypes.c_uint32(self._input_original_mode),
                )
        except Exception:
            pass
        finally:
            self._input_handle = None
            self._input_original_mode = None
            self._vt_input_active = False

    def mode_configured(self) -> bool:
        return self._input_handle is not None and self._input_original_mode is not None

    def vt_input_active(self) -> bool:
        return self._vt_input_active

    def enable_vt_output(self, stdout: object) -> bool:
        if self._output_handle is not None:
            return self._vt_output_active
        try:
            kernel32 = self.kernel32_loader()
        except Exception:
            return False
        if kernel32 is None:
            return False
        try:
            handle = ctypes.c_void_p(
                _windows_stream_handle(
                    stdout,
                    kernel32,
                    _STD_OUTPUT_HANDLE,
                    self.console_module_loader,
                )
            )
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            original_mode = int(mode.value)
            requested = ctypes.c_uint32(_windows_console_output_mode(original_mode))
            if not kernel32.SetConsoleMode(handle, requested):
                return False
        except Exception:
            return False
        self._output_handle = handle.value
        self._output_original_mode = original_mode
        self._vt_output_active = True
        return self._vt_output_active

    def disable_vt_output(self) -> None:
        if self._output_handle is None or self._output_original_mode is None:
            return
        try:
            kernel32 = self.kernel32_loader()
            if kernel32 is not None:
                kernel32.SetConsoleMode(
                    ctypes.c_void_p(self._output_handle),
                    ctypes.c_uint32(self._output_original_mode),
                )
        except Exception:
            pass
        finally:
            self._output_handle = None
            self._output_original_mode = None
            self._vt_output_active = False

    def vt_output_active(self) -> bool:
        return self._vt_output_active


@dataclass(frozen=True, slots=True)
class WindowsTerminalMode:
    """Acknowledge Windows TTY mode ownership without duplicating Win32 flags."""

    def open(self, stdin: Any) -> WindowsTerminalModeLease:
        del stdin
        return WindowsTerminalModeLease()


@dataclass(frozen=True, slots=True)
class WindowsTerminalModeLease:
    """Console flags belong to WindowsConsoleMode behind the public facade."""

    def restore(self) -> None:
        pass


WINDOWS_TERMINAL_MODE = WindowsTerminalMode()


def _read_from_module(console: Any) -> str:
    chunk = _read_logical_character(console)
    if chunk != _ESCAPE:
        return chunk
    return chunk + _read_escape_burst(console)


def _read_logical_character(
    console: Any,
    *,
    recover_plain_alt: bool = True,
) -> str:
    pending_alt_modifier = (
        _windows_pending_alt_modifier() if recover_plain_alt else False
    )
    char = console.getwch()
    if char in {"\x00", "\xe0"}:
        extended = console.getwch()
        return _EXTENDED_KEY_SEQUENCES.get(extended, char + extended)
    if recover_plain_alt and char.lower() == "v" and (
        pending_alt_modifier or _windows_alt_pressed()
    ):
        # Some Windows VT hosts preserve the physical Alt key state but expose
        # Alt+V through getwch() as an unmodified printable character.
        return "\x1bv"
    if _is_high_surrogate(char):
        trailing = console.getwch()
        if _is_low_surrogate(trailing):
            codepoint = (
                0x10000
                + ((ord(char) - _HIGH_SURROGATE_START) << 10)
                + ord(trailing)
                - _LOW_SURROGATE_START
            )
            return chr(codepoint)
        return _REPLACEMENT_CHARACTER + _replace_isolated_surrogate(trailing)
    if _is_low_surrogate(char):
        return _REPLACEMENT_CHARACTER
    return char


def _windows_alt_pressed() -> bool:
    try:
        state = int(ctypes.windll.user32.GetAsyncKeyState(_VK_MENU))  # type: ignore[attr-defined]
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    return bool(state & _KEY_STATE_DOWN_MASK)


def _windows_pending_alt_modifier() -> bool:
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = ctypes.c_void_p(kernel32.GetStdHandle(_STD_INPUT_HANDLE))
        available = ctypes.c_uint32()
        if not kernel32.GetNumberOfConsoleInputEvents(
            handle,
            ctypes.byref(available),
        ):
            return False
        record_count = min(int(available.value), _MAX_PEEKED_INPUT_RECORDS)
        if record_count <= 0:
            return False
        records = (_WindowsInputRecord * record_count)()
        peeked = ctypes.c_uint32()
        if not kernel32.PeekConsoleInputW(
            handle,
            records,
            record_count,
            ctypes.byref(peeked),
        ):
            return False
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    alt_mask = _LEFT_ALT_PRESSED | _RIGHT_ALT_PRESSED
    for record in records[: int(peeked.value)]:
        if record.EventType != _KEY_EVENT:
            continue
        key = record.Event.KeyEvent
        if not key.bKeyDown:
            continue
        if key.wVirtualKeyCode in {_VK_MENU, _VK_LMENU, _VK_RMENU}:
            return True
        return bool(
            key.wVirtualKeyCode == _VK_V
            and key.dwControlKeyState & alt_mask
        )
    return False


def _read_escape_burst(console: Any) -> str:
    """Keep one Windows VT burst together before generic input parsing.

    ``msvcrt.getwch()`` exposes Windows Terminal VT input one UTF-16 unit at a
    time. Focus reports and bracketed-paste markers therefore arrive as an
    initial Escape followed by ordinary-looking characters. The application
    parser deliberately owns their meaning; this physical backend only keeps
    the already-arriving console burst atomic so the parser's Escape timeout
    cannot expose tails such as ``[I`` or ``[201~`` as user text.
    """

    chunks: list[str] = []
    size = 0
    idle_deadline = time.monotonic() + _ESCAPE_BURST_IDLE_SECONDS
    while size < _ESCAPE_BURST_MAX_CHARS:
        try:
            has_input = bool(console.kbhit())
        except (OSError, ValueError):
            break
        if not has_input:
            if time.monotonic() >= idle_deadline:
                break
            time.sleep(_INPUT_POLL_INTERVAL_SECONDS)
            continue
        chunk = _read_logical_character(console, recover_plain_alt=False)
        if not chunk:
            break
        remaining = _ESCAPE_BURST_MAX_CHARS - size
        chunks.append(chunk[:remaining])
        size += min(len(chunk), remaining)
        idle_deadline = time.monotonic() + _ESCAPE_BURST_IDLE_SECONDS
    return "".join(chunks)


def _windows_stream_handle(
    stream: object,
    kernel32: Any,
    std_handle: int,
    console_module_loader: ConsoleModuleLoader,
) -> int:
    fileno = getattr(stream, "fileno", None)
    if callable(fileno):
        try:
            console = console_module_loader()
            if console is not None:
                return int(console.get_osfhandle(fileno()))
        except Exception:
            pass
    return int(kernel32.GetStdHandle(std_handle))


def _windows_console_input_mode(
    mode: int,
    *,
    vt_input: bool,
    preserve_native_selection: bool,
) -> int:
    requested = mode | _ENABLE_EXTENDED_FLAGS
    if not preserve_native_selection:
        requested &= ~_ENABLE_QUICK_EDIT_MODE
    if vt_input:
        requested |= _ENABLE_VIRTUAL_TERMINAL_INPUT
    return requested


def _windows_console_output_mode(mode: int) -> int:
    return mode | _ENABLE_PROCESSED_OUTPUT | _ENABLE_VIRTUAL_TERMINAL_PROCESSING


def _is_high_surrogate(char: str) -> bool:
    return len(char) == 1 and _HIGH_SURROGATE_START <= ord(char) <= _HIGH_SURROGATE_END


def _is_low_surrogate(char: str) -> bool:
    return len(char) == 1 and _LOW_SURROGATE_START <= ord(char) <= _LOW_SURROGATE_END


def _replace_isolated_surrogate(char: str) -> str:
    if _is_high_surrogate(char) or _is_low_surrogate(char):
        return _REPLACEMENT_CHARACTER
    return char


def _set_future_result(future: asyncio.Future[str], result: str) -> None:
    if not future.done():
        future.set_result(result)


def _set_future_exception(future: asyncio.Future[str], error: BaseException) -> None:
    if not future.done():
        future.set_exception(error)


__all__ = [
    "WINDOWS_CONSOLE_INPUT",
    "WINDOWS_TERMINAL_MODE",
    "WindowsConsoleInput",
    "WindowsTerminalMode",
    "WindowsTerminalModeLease",
    "WindowsConsoleMode",
]
