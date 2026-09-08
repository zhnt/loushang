"""Test-only kernel-object identity probe; never infer identity from HANDLE values."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes
from typing import Any


class WindowsHandleIdentityProbe:
    def __init__(
        self,
        kernel32: Any = None,
        *,
        last_error: Callable[[], int] | None = None,
    ) -> None:
        if kernel32 is None:
            kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        self._last_error = last_error or getattr(ctypes, "get_last_error")

        def bind(name: str, result: Any, arguments: tuple[Any, ...]) -> Any:
            function = getattr(kernel32, name)
            function.restype = result
            function.argtypes = arguments
            return function

        handle = wintypes.HANDLE
        self._current = bind("GetCurrentProcess", handle, ())
        self._process_id = bind("GetProcessId", wintypes.DWORD, (handle,))
        self._information = bind(
            "GetHandleInformation", wintypes.BOOL,
            (handle, ctypes.POINTER(wintypes.DWORD)),
        )
        self._duplicate = bind(
            "DuplicateHandle", wintypes.BOOL,
            (handle, handle, handle, ctypes.POINTER(handle),
             wintypes.DWORD, wintypes.BOOL, wintypes.DWORD),
        )
        self._compare = bind("CompareObjectHandles", wintypes.BOOL, (handle, handle))
        self._close = bind("CloseHandle", wintypes.BOOL, (handle,))

    def matches(self, process: int, remote: int, expected: int) -> bool:
        """Compare a live child's handle with an already-owned parent object.

        Only an absent child handle is negative evidence. Invalid reference or
        process handles, access denial and cleanup failure must fail the test.
        Duplicate into the parent; never close or inject a handle in the child.
        """
        if not self._process_id(wintypes.HANDLE(process)):
            raise OSError(self._last_error(), "GetProcessId")
        flags = wintypes.DWORD()
        if not self._information(wintypes.HANDLE(expected), ctypes.byref(flags)):
            raise OSError(self._last_error(), "GetHandleInformation(reference)")
        duplicate = wintypes.HANDLE()
        if not self._duplicate(
            wintypes.HANDLE(process), wintypes.HANDLE(remote), self._current(),
            ctypes.byref(duplicate), 0, False, 0x2,  # DUPLICATE_SAME_ACCESS only
        ):
            error = self._last_error()
            if error == 6:  # ERROR_INVALID_HANDLE, with process/reference validated
                return False
            raise OSError(error, "DuplicateHandle")
        try:
            return bool(self._compare(duplicate, wintypes.HANDLE(expected)))
        finally:
            if not self._close(duplicate):
                raise OSError(self._last_error(), "CloseHandle(probe duplicate)")
