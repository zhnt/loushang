"""Test supervisor's independent Windows Job, assigned before start admission."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


class Accounting(ctypes.Structure):
    _fields_ = [
        ("user", ctypes.c_longlong), ("kernel", ctypes.c_longlong),
        ("period_user", ctypes.c_longlong), ("period_kernel", ctypes.c_longlong),
        ("faults", wintypes.DWORD), ("total", wintypes.DWORD),
        ("active", wintypes.DWORD), ("terminated", wintypes.DWORD),
    ]


class EvidenceJob:
    def __init__(self, process):
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        self._create = api.CreateJobObjectW
        self._create.argtypes, self._create.restype = [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE
        self._assign = api.AssignProcessToJobObject
        self._assign.argtypes, self._assign.restype = [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL
        self._query = api.QueryInformationJobObject
        self._query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self._query.restype = wintypes.BOOL
        self._terminate = api.TerminateJobObject
        self._terminate.argtypes, self._terminate.restype = [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL
        self._close = api.CloseHandle
        self._close.argtypes, self._close.restype = [wintypes.HANDLE], wintypes.BOOL
        self.handle = self._create(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        # The wrapper is waiting for 'start'; no descendant can precede this
        # admission. Default Job limits do not permit breakaway. Hosting Jobs
        # nested below this Job do not escape its process accounting.
        if not self._assign(self.handle, int(process._handle)):
            error = ctypes.WinError(ctypes.get_last_error())
            self._close(self.handle)
            raise error

    def active(self):
        value = Accounting()
        if not self._query(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.active

    def terminate(self):
        if not self._terminate(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.active():
            raise RuntimeError("evidence Job still owns live processes")
        if not self._close(self.handle):
            raise ctypes.WinError(ctypes.get_last_error())
