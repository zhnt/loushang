"""Independent Win32 observation/fault API; no Product backend imports."""

from __future__ import annotations

import ctypes
import sysconfig
import time

DWORD = ctypes.c_uint32
HANDLE = ctypes.c_void_p
INVALID = ctypes.c_void_p(-1).value


class ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("size", DWORD), ("usage", DWORD), ("pid", DWORD), ("heap", ctypes.c_size_t),
        ("module", DWORD), ("threads", DWORD), ("parent", DWORD),
        ("priority", ctypes.c_int32), ("flags", DWORD), ("exe", ctypes.c_wchar * 260),
    ]


class ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", DWORD), ("usage", DWORD), ("tid", DWORD), ("pid", DWORD),
        ("priority", ctypes.c_int32), ("delta", ctypes.c_int32), ("flags", DWORD),
    ]


class WindowsObservationApi:
    def __init__(self):
        self.failed_closes = set()
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)

    def call(self, name, arguments, result, *values):
        operation = getattr(self.api, name)
        operation.argtypes, operation.restype = arguments, result
        return operation(*values)

    def close(self, handle):
        if not self.call("CloseHandle", [HANDLE], ctypes.c_int, handle):
            self.failed_closes.add(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        self.failed_closes.discard(handle)

    def retry_closes(self):
        errors = []
        for handle in tuple(self.failed_closes):
            try:
                self.close(handle)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("native handle cleanup pending", errors)

    def console_processes(self):
        values = (DWORD * 128)()
        count = self.call("GetConsoleProcessList", [ctypes.POINTER(DWORD), DWORD], DWORD,
                          values, len(values))
        if not count or count > len(values):
            raise RuntimeError("console process observation incomplete")
        return list(values[:count])

    def modes(self):
        result = []
        for kind in (-10, -11):
            handle = self.call("GetStdHandle", [DWORD], HANDLE, kind & 0xFFFFFFFF)
            mode = DWORD()
            if not self.call("GetConsoleMode", [HANDLE, ctypes.POINTER(DWORD)], ctypes.c_int,
                             handle, ctypes.byref(mode)):
                raise ctypes.WinError(ctypes.get_last_error())
            result.append(mode.value)
        return result

    def protect_witness_interrupt(self):
        # A real handler affects only this witness. NULL+TRUE would set the
        # inherited ignore-Ctrl+C attribute and invalidate child cancellation.
        # https://learn.microsoft.com/en-us/windows/console/setconsolectrlhandler
        handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, DWORD)
        self.handler = handler_type(lambda event: int(event in (0, 1)))
        for handler, enabled in ((None, False), (self.handler, True)):
            pointer = None if handler is None else ctypes.cast(handler, ctypes.c_void_p)
            if not self.call("SetConsoleCtrlHandler", [ctypes.c_void_p, ctypes.c_int],
                             ctypes.c_int, pointer, enabled):
                raise ctypes.WinError(ctypes.get_last_error())

    def entries(self, *, threads=False):
        structure = ThreadEntry if threads else ProcessEntry
        prefix = "Thread32" if threads else "Process32"
        suffix = "" if threads else "W"
        snapshot = self.call("CreateToolhelp32Snapshot", [DWORD, DWORD], HANDLE,
                             4 if threads else 2, 0)
        if snapshot == INVALID:
            raise ctypes.WinError(ctypes.get_last_error())
        result = []
        try:
            entry = structure()
            entry.size = ctypes.sizeof(entry)
            operation = "First"
            while self.call(prefix + operation + suffix,
                            [HANDLE, ctypes.POINTER(structure)], ctypes.c_int,
                            snapshot, ctypes.byref(entry)):
                result.append((int(entry.tid), int(entry.pid)) if threads else
                              (int(entry.pid), int(entry.parent)))
                operation = "Next"
                entry.size = ctypes.sizeof(entry)
            if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                raise ctypes.WinError(ctypes.get_last_error())
            return dict(result)
        finally:
            self.close(snapshot)

    def open_process(self, pid):
        handle = self.call("OpenProcess", [DWORD, ctypes.c_int, DWORD], HANDLE,
                           0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def ended(self, handle):
        result = self.call("WaitForSingleObject", [HANDLE, DWORD], DWORD, handle, 0)
        if result not in (0, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def open_thread(self, tid, pid):
        handle = self.call("OpenThread", [DWORD, ctypes.c_int, DWORD], HANDLE,
                           0x00100000 | 0x0800 | 0x0002 | 0x0008, False, tid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        owner = self.call("GetProcessIdOfThread", [HANDLE], DWORD, handle)
        if owner != pid:
            self.close(handle)
            raise RuntimeError("thread identity changed before fault admission")
        return handle

    def suspend(self, handle):
        if self.call("SuspendThread", [HANDLE], DWORD, handle) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())

    def confirm_stopped(self, handle):
        # SuspendThread is asynchronous. GetThreadContext is the synchronous
        # barrier; InitializeContext owns CONTEXT sizing and alignment.
        # https://devblogs.microsoft.com/oldnewthing/20150205-00/?p=44743
        if sysconfig.get_platform() != "win-amd64":
            raise RuntimeError("this fault observer requires same-architecture Windows AMD64")
        length, context = DWORD(), HANDLE()
        arguments = [HANDLE, DWORD, ctypes.POINTER(HANDLE), ctypes.POINTER(DWORD)]
        result = self.call("InitializeContext", arguments, ctypes.c_int,
                           None, 0x00100001, ctypes.byref(context), ctypes.byref(length))
        if result or ctypes.get_last_error() != 122 or not 0 < length.value <= 65536:
            raise RuntimeError("native thread context sizing failed")
        buffer = ctypes.create_string_buffer(length.value)
        if not self.call("InitializeContext", arguments, ctypes.c_int,
                         buffer, 0x00100001, ctypes.byref(context), ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.call("GetThreadContext", [HANDLE, HANDLE], ctypes.c_int, handle, context):
            raise ctypes.WinError(ctypes.get_last_error())

    def resume(self, handle):
        if self.call("ResumeThread", [HANDLE], DWORD, handle) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())


class SuspendedThreads:
    """Only controlled same-architecture Python services, not hostile injection."""

    def __init__(self, api, pid, process):
        self.api, self.pid, self.process = api, pid, process
        self.handles = {}  # Thread handles pin identity across snapshot retries.
        self.resumed = set()
        self.suspended = set()
        self.uncertain = set()

    def stop(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.api.ended(self.process):
                raise RuntimeError("fault target exited")
            threads = {tid for tid, pid in self.api.entries(threads=True).items() if pid == self.pid}
            unseen = threads - self.handles.keys()
            if threads and not unseen:
                return
            for tid in unseen:
                if len(self.handles) >= 128 or time.monotonic() >= deadline:
                    raise RuntimeError("fault thread bound exceeded")
                handle = self.api.open_thread(tid, self.pid)
                self.handles[tid] = handle
                self.uncertain.add(tid)
                try:
                    self.api.suspend(handle)
                except OSError:
                    self.uncertain.discard(tid)  # API reports no increment.
                    raise
                self.suspended.add(tid)
                self.uncertain.discard(tid)
                self.api.confirm_stopped(handle)
        raise TimeoutError("fault thread suspension did not settle")

    def close(self):
        errors = []
        for tid, handle in tuple(self.handles.items()):
            try:
                if tid in self.uncertain:
                    raise RuntimeError("unknown suspend/resume effect; outer Job must reclaim")
                if tid not in self.resumed:
                    if tid in self.suspended and not self.api.ended(handle):
                        self.uncertain.add(tid)
                        try:
                            self.api.resume(handle)  # Undo exactly our single increment.
                        except OSError:
                            self.uncertain.discard(tid)  # API reports no decrement.
                            raise
                        self.resumed.add(tid)
                        self.uncertain.discard(tid)
                    else:
                        self.resumed.add(tid)
                self.api.close(handle)
            except Exception as error:
                errors.append(error)
            else:
                del self.handles[tid]
                self.resumed.discard(tid)
                self.suspended.discard(tid)
        if errors:
            raise ExceptionGroup("fault suspension cleanup pending", errors)
