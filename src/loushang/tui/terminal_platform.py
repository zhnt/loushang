from __future__ import annotations

import ctypes
import importlib
import sys
from typing import Protocol

APPLE_TERMINAL_SHIFT_ENTER_SEQUENCE = "\x1b[13;2u"
_APPLE_EVENT_SOURCE_STATE_COMBINED_SESSION = 0
_APPLE_EVENT_FLAG_MASK_SHIFT = 1 << 17
_ENABLE_QUICK_EDIT_MODE = 0x0040
_ENABLE_EXTENDED_FLAGS = 0x0080
_ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
_ENABLE_PROCESSED_OUTPUT = 0x0001
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_INPUT_HANDLE = -10
_STD_OUTPUT_HANDLE = -11


class TerminalPlatformAdapter(Protocol):
    def enable_windows_vt_input(self, stdin: object) -> bool: ...

    def disable_windows_vt_input(self) -> None: ...

    def enable_windows_vt_output(self, stdout: object) -> bool: ...

    def disable_windows_vt_output(self) -> None: ...

    def windows_console_mode_configured(self) -> bool: ...

    def windows_vt_input_active(self) -> bool: ...

    def windows_vt_output_active(self) -> bool: ...

    def apple_shift_pressed(self) -> bool: ...


class DefaultTerminalPlatformAdapter:
    def __init__(self) -> None:
        self._windows_handle: int | None = None
        self._windows_original_mode: int | None = None
        self._windows_vt_input_active = False
        self._windows_output_handle: int | None = None
        self._windows_output_original_mode: int | None = None
        self._windows_vt_output_active = False

    def enable_windows_vt_input(self, stdin: object) -> bool:
        if sys.platform != "win32":
            return False
        if self._windows_handle is not None:
            return self._windows_vt_input_active
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = ctypes.c_void_p(_windows_stdin_handle(stdin, kernel32))
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            original_mode = int(mode.value)
            requested = ctypes.c_uint32(_windows_console_input_mode(original_mode, vt_input=True))
            vt_enabled = bool(kernel32.SetConsoleMode(handle, requested))
            if not vt_enabled:
                fallback = ctypes.c_uint32(_windows_console_input_mode(original_mode, vt_input=False))
                if not kernel32.SetConsoleMode(handle, fallback):
                    return False
        except Exception:
            return False
        self._windows_handle = handle.value
        self._windows_original_mode = original_mode
        self._windows_vt_input_active = vt_enabled
        return self._windows_vt_input_active

    def disable_windows_vt_input(self) -> None:
        if sys.platform != "win32" or self._windows_handle is None or self._windows_original_mode is None:
            return
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetConsoleMode(ctypes.c_void_p(self._windows_handle), ctypes.c_uint32(self._windows_original_mode))
        except Exception:
            pass
        finally:
            self._windows_handle = None
            self._windows_original_mode = None
            self._windows_vt_input_active = False

    def windows_console_mode_configured(self) -> bool:
        return self._windows_handle is not None and self._windows_original_mode is not None

    def windows_vt_input_active(self) -> bool:
        return self._windows_vt_input_active

    def enable_windows_vt_output(self, stdout: object) -> bool:
        if sys.platform != "win32":
            return False
        if self._windows_output_handle is not None:
            return self._windows_vt_output_active
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = ctypes.c_void_p(_windows_stdout_handle(stdout, kernel32))
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            original_mode = int(mode.value)
            requested = ctypes.c_uint32(_windows_console_output_mode(original_mode))
            if not kernel32.SetConsoleMode(handle, requested):
                return False
        except Exception:
            return False
        self._windows_output_handle = handle.value
        self._windows_output_original_mode = original_mode
        self._windows_vt_output_active = True
        return self._windows_vt_output_active

    def disable_windows_vt_output(self) -> None:
        if sys.platform != "win32" or self._windows_output_handle is None or self._windows_output_original_mode is None:
            return
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetConsoleMode(
                ctypes.c_void_p(self._windows_output_handle),
                ctypes.c_uint32(self._windows_output_original_mode),
            )
        except Exception:
            pass
        finally:
            self._windows_output_handle = None
            self._windows_output_original_mode = None
            self._windows_vt_output_active = False

    def windows_vt_output_active(self) -> bool:
        return self._windows_vt_output_active

    def apple_shift_pressed(self) -> bool:
        if sys.platform != "darwin":
            return False
        if _apple_shift_pressed_via_quartz():
            return True
        try:
            native_modifiers = importlib.import_module(
                "loushang.tui.native_modifiers"
            )
            is_shift_pressed = getattr(native_modifiers, "is_shift_pressed")
        except Exception:
            return False
        try:
            return bool(is_shift_pressed())
        except Exception:
            return False


def _windows_stdin_handle(stdin: object, kernel32: object) -> int:
    return _windows_stream_handle(stdin, kernel32, _STD_INPUT_HANDLE)


def _windows_stdout_handle(stdout: object, kernel32: object) -> int:
    return _windows_stream_handle(stdout, kernel32, _STD_OUTPUT_HANDLE)


def _windows_stream_handle(stream: object, kernel32: object, std_handle: int) -> int:
    fileno = getattr(stream, "fileno", None)
    if callable(fileno):
        try:
            msvcrt = importlib.import_module("msvcrt")
            get_osfhandle = getattr(msvcrt, "get_osfhandle")
            return int(get_osfhandle(fileno()))
        except Exception:
            pass
    get_std_handle = getattr(kernel32, "GetStdHandle")
    return int(get_std_handle(std_handle))


def _windows_console_input_mode(mode: int, *, vt_input: bool) -> int:
    requested = (mode | _ENABLE_EXTENDED_FLAGS) & ~_ENABLE_QUICK_EDIT_MODE
    if vt_input:
        requested |= _ENABLE_VIRTUAL_TERMINAL_INPUT
    return requested


def _windows_console_output_mode(mode: int) -> int:
    return mode | _ENABLE_PROCESSED_OUTPUT | _ENABLE_VIRTUAL_TERMINAL_PROCESSING


def _apple_shift_pressed_via_quartz() -> bool:
    try:
        application_services = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        flags_state = application_services.CGEventSourceFlagsState
        flags_state.argtypes = [ctypes.c_uint32]
        flags_state.restype = ctypes.c_uint64
        flags = int(flags_state(_APPLE_EVENT_SOURCE_STATE_COMBINED_SESSION))
    except Exception:
        return False
    return bool(flags & _APPLE_EVENT_FLAG_MASK_SHIFT)


__all__ = [
    "APPLE_TERMINAL_SHIFT_ENTER_SEQUENCE",
    "DefaultTerminalPlatformAdapter",
    "TerminalPlatformAdapter",
]
