"""Private, import-safe Win32 calls for the Windows Hosting backend."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from .contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
)
from .errors import HostingError, HostingFailureCategory

_CREATE_NO_WINDOW = 0x08000000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WAIT_OBJECT_0 = 0
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE = 0xFFFFFFFF
_STILL_ACTIVE = 259
_ERROR_BROKEN_PIPE = 109
_ERROR_INVALID_PARAMETER = 87
_ERROR_NO_DATA = 232
_ERROR_OPERATION_ABORTED = 995
_ERROR_NOT_FOUND = 1168
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_THREAD_TERMINATE = 0x0001


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


@dataclass(frozen=True, slots=True)
class _Win32SpawnHandles:
    process: int
    job: int
    stdin_write: int | None
    stdout_read: int | None
    stderr_read: int | None


@dataclass(frozen=True, slots=True)
class _Win32AttributeList:
    storage: ctypes.Array[ctypes.c_char]
    pointer: ctypes.c_void_p
    jobs: ctypes.Array[Any]
    handles: ctypes.Array[Any]


class _CtypesWin32Api:
    """Small synchronous Win32 API; async scheduling belongs to its adapter."""

    def __init__(self) -> None:
        if os.name != "nt" or not hasattr(sys, "getwindowsversion"):
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows Job Objects are unavailable",
            )
        if sys.getwindowsversion().major < 10:  # type: ignore[attr-defined]
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "atomic Job Object process creation requires Windows 10 or later",
            )
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Win32 process APIs are unavailable",
            )
        try:
            self._kernel32 = loader("kernel32", use_last_error=True)
            self._bind_functions()
        except (AttributeError, OSError) as exc:
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "required atomic Win32 process APIs are unavailable",
            ) from exc

    def spawn(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int] | None = None,
    ) -> _Win32SpawnHandles:
        owned: list[int] = []
        attributes: _Win32AttributeList | None = None
        try:
            job = self._create_job()
            owned.append(job)

            if endpoint_handles is None:
                child_stdin, parent_stdin = self._stdin_handles(request)
                owned.extend(_present_handles(child_stdin, parent_stdin))
                child_stdout, parent_stdout = self._stdout_handles(request)
                owned.extend(_present_handles(child_stdout, parent_stdout))
                externally_owned: frozenset[int] = frozenset()
            else:
                child_stdin, child_stdout = endpoint_handles
                if (
                    type(child_stdin) is not int
                    or child_stdin <= 0
                    or type(child_stdout) is not int
                    or child_stdout <= 0
                ):
                    raise HostingError(
                        HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                        "Windows endpoint inheritance contains invalid handles",
                    )
                parent_stdin = None
                parent_stdout = None
                externally_owned = frozenset(endpoint_handles)
            child_stderr, parent_stderr = self._stderr_handles(request)
            owned.extend(_present_handles(child_stderr, parent_stderr))

            attributes = self._attribute_list(
                job, (child_stdin, child_stdout, child_stderr)
            )
            startup = _STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = child_stdin
            startup.StartupInfo.hStdOutput = child_stdout
            startup.StartupInfo.hStdError = child_stderr
            startup.lpAttributeList = attributes.pointer

            process_information = _PROCESS_INFORMATION()
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline(request.argv)
            )
            environment = ctypes.create_unicode_buffer(
                _environment_block(request.effective_environment)
            )
            created = self._CreateProcessW(
                request.argv[0],
                command_line,
                None,
                None,
                True,
                _EXTENDED_STARTUPINFO_PRESENT
                | _CREATE_UNICODE_ENVIRONMENT
                | _CREATE_NO_WINDOW,
                ctypes.cast(environment, ctypes.c_void_p),
                request.cwd,
                ctypes.byref(startup.StartupInfo),
                ctypes.byref(process_information),
            )
            if not created:
                self._raise_last_error("CreateProcessW")
            process_handle = _handle_value(process_information.hProcess)
            thread_handle = _handle_value(process_information.hThread)
            owned.extend((process_handle, thread_handle))

            # The Job Object and handle-list attributes made ownership and
            # inheritance atomic. Parent copies of child-only resources can
            # now be closed before the transport is published.
            self.close_handle(thread_handle)
            owned.remove(thread_handle)
            for handle in (child_stdin, child_stdout, child_stderr):
                if handle in externally_owned:
                    continue
                self.close_handle(handle)
                owned.remove(handle)

            result = _Win32SpawnHandles(
                process=process_handle,
                job=job,
                stdin_write=parent_stdin,
                stdout_read=parent_stdout,
                stderr_read=parent_stderr,
            )
            for returned_handle in (
                result.process,
                result.job,
                result.stdin_write,
                result.stdout_read,
                result.stderr_read,
            ):
                if returned_handle is not None:
                    owned.remove(returned_handle)
            return result
        finally:
            if attributes is not None:
                self._DeleteProcThreadAttributeList(attributes.pointer)
            for handle in reversed(owned):
                with suppress(OSError):
                    self.close_handle(handle)

    def read_pipe(self, handle: int, max_bytes: int) -> bytes:
        buffer = ctypes.create_string_buffer(max_bytes)
        read = wintypes.DWORD()
        if not self._ReadFile(handle, buffer, max_bytes, ctypes.byref(read), None):
            error = _last_error()
            if error in {
                _ERROR_BROKEN_PIPE,
                _ERROR_NO_DATA,
                _ERROR_OPERATION_ABORTED,
            }:
                return b""
            self._raise_error(error, "ReadFile")
        return buffer.raw[: read.value]

    def write_pipe(self, handle: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = wintypes.DWORD()
            chunk = data[offset:]
            buffer = ctypes.create_string_buffer(chunk)
            if not self._WriteFile(
                handle, buffer, len(chunk), ctypes.byref(written), None
            ):
                error = _last_error()
                if error in {
                    _ERROR_BROKEN_PIPE,
                    _ERROR_NO_DATA,
                    _ERROR_OPERATION_ABORTED,
                }:
                    raise BrokenPipeError("Windows process stdin is closed")
                self._raise_error(error, "WriteFile")
            if written.value == 0:
                raise BrokenPipeError("Windows process stdin accepted no bytes")
            offset += written.value

    def wait_process(self, handle: int) -> int:
        outcome = self._WaitForSingleObject(handle, _INFINITE)
        if outcome == _WAIT_FAILED:
            self._raise_last_error("WaitForSingleObject")
        if outcome != _WAIT_OBJECT_0:
            raise OSError(f"unexpected process wait result: {outcome}")
        return_code = wintypes.DWORD()
        if not self._GetExitCodeProcess(handle, ctypes.byref(return_code)):
            self._raise_last_error("GetExitCodeProcess")
        return int(return_code.value)

    def process_return_code(self, handle: int) -> int | None:
        return_code = wintypes.DWORD()
        if not self._GetExitCodeProcess(handle, ctypes.byref(return_code)):
            self._raise_last_error("GetExitCodeProcess")
        if return_code.value == _STILL_ACTIVE:
            return None
        return int(return_code.value)

    def job_is_empty(self, handle: int) -> bool:
        accounting = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        if not self._QueryInformationJobObject(
            handle,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            self._raise_last_error("QueryInformationJobObject")
        return accounting.ActiveProcesses == 0

    def terminate_job(self, handle: int, exit_code: int) -> None:
        if not self._TerminateJobObject(handle, exit_code):
            self._raise_last_error("TerminateJobObject")

    def close_handle(self, handle: int) -> None:
        if not self._CloseHandle(handle):
            self._raise_last_error("CloseHandle")

    def create_pipe(self, *, child_reads: bool) -> tuple[int, int]:
        """Create one exact child/host anonymous-pipe pair for H3."""

        return self._pipe(child_reads=child_reads)

    def cancel_synchronous_io(self, thread_id: int) -> None:
        """Cancel blocking endpoint I/O issued by one executor thread."""

        raw_thread = self._OpenThread(_THREAD_TERMINATE, False, thread_id)
        if not raw_thread:
            # The operation may have settled between the adapter snapshot and
            # this call. No live thread means there is nothing left to cancel.
            error = _last_error()
            if error == _ERROR_INVALID_PARAMETER:
                return
            self._raise_error(error, "OpenThread")
        thread = _handle_value(raw_thread)
        try:
            if self._CancelSynchronousIo(thread):
                return
            error = _last_error()
            if error != _ERROR_NOT_FOUND:
                self._raise_error(error, "CancelSynchronousIo")
        finally:
            self.close_handle(thread)

    def _create_job(self) -> int:
        raw_job = self._CreateJobObjectW(None, None)
        if not raw_job:
            self._raise_last_error("CreateJobObjectW")
        job = _handle_value(raw_job)
        limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = _last_error()
            with suppress(OSError):
                self.close_handle(job)
            self._raise_error(error, "SetInformationJobObject")
        return job

    def _stdin_handles(
        self, request: ProcessLaunchRequest
    ) -> tuple[int, int | None]:
        if request.streams.stdin is ProcessStdinMode.PIPE:
            child, parent = self._pipe(child_reads=True)
            return child, parent
        return self._null_handle(read=True), None

    def _stdout_handles(
        self, request: ProcessLaunchRequest
    ) -> tuple[int, int | None]:
        if request.streams.stdout is ProcessStdoutMode.PIPE:
            parent, child = self._pipe(child_reads=False)
            return child, parent
        return self._null_handle(read=False), None

    def _stderr_handles(
        self, request: ProcessLaunchRequest
    ) -> tuple[int, int | None]:
        if request.streams.stderr in {
            ProcessStderrMode.PIPE,
            ProcessStderrMode.CAPTURE_TAIL,
        }:
            parent, child = self._pipe(child_reads=False)
            return child, parent
        return self._null_handle(read=False), None

    def _pipe(self, *, child_reads: bool) -> tuple[int, int]:
        attributes = _SECURITY_ATTRIBUTES(
            nLength=ctypes.sizeof(_SECURITY_ATTRIBUTES),
            lpSecurityDescriptor=None,
            bInheritHandle=True,
        )
        read_handle = wintypes.HANDLE()
        write_handle = wintypes.HANDLE()
        if not self._CreatePipe(
            ctypes.byref(read_handle),
            ctypes.byref(write_handle),
            ctypes.byref(attributes),
            0,
        ):
            self._raise_last_error("CreatePipe")
        read = _handle_value(read_handle)
        write = _handle_value(write_handle)
        parent = write if child_reads else read
        if not self._SetHandleInformation(
            parent, _HANDLE_FLAG_INHERIT, 0
        ):
            error = _last_error()
            with suppress(OSError):
                self.close_handle(read)
            with suppress(OSError):
                self.close_handle(write)
            self._raise_error(error, "SetHandleInformation")
        return read, write

    def _null_handle(self, *, read: bool) -> int:
        attributes = _SECURITY_ATTRIBUTES(
            nLength=ctypes.sizeof(_SECURITY_ATTRIBUTES),
            lpSecurityDescriptor=None,
            bInheritHandle=True,
        )
        raw_handle = self._CreateFileW(
            "NUL",
            _GENERIC_READ if read else _GENERIC_WRITE,
            0,
            ctypes.byref(attributes),
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        handle = _handle_value(raw_handle)
        if handle == _INVALID_HANDLE_VALUE:
            self._raise_last_error("CreateFileW(NUL)")
        return handle

    def _attribute_list(
        self, job: int, inherited_handles: tuple[int, int, int]
    ) -> _Win32AttributeList:
        size = ctypes.c_size_t()
        self._InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        if size.value == 0:
            self._raise_last_error("InitializeProcThreadAttributeList")
        storage = ctypes.create_string_buffer(size.value)
        pointer = ctypes.cast(storage, ctypes.c_void_p)
        if not self._InitializeProcThreadAttributeList(
            pointer, 2, 0, ctypes.byref(size)
        ):
            self._raise_last_error("InitializeProcThreadAttributeList")

        job_list = (wintypes.HANDLE * 1)(job)
        handle_list = (wintypes.HANDLE * len(inherited_handles))(
            *inherited_handles
        )
        if not self._UpdateProcThreadAttribute(
            pointer,
            0,
            _PROC_THREAD_ATTRIBUTE_JOB_LIST,
            ctypes.byref(job_list),
            ctypes.sizeof(job_list),
            None,
            None,
        ):
            self._DeleteProcThreadAttributeList(pointer)
            self._raise_last_error("UpdateProcThreadAttribute(JOB_LIST)")
        if not self._UpdateProcThreadAttribute(
            pointer,
            0,
            _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            ctypes.byref(handle_list),
            ctypes.sizeof(handle_list),
            None,
            None,
        ):
            self._DeleteProcThreadAttributeList(pointer)
            self._raise_last_error("UpdateProcThreadAttribute(HANDLE_LIST)")
        # Win32 may retain pointers to these value arrays until process
        # creation, so the returned owner keeps all three allocations alive.
        return _Win32AttributeList(storage, pointer, job_list, handle_list)

    def _bind_functions(self) -> None:
        kernel32: Any = self._kernel32
        self._CreateJobObjectW = _bind(
            kernel32.CreateJobObjectW,
            [ctypes.POINTER(_SECURITY_ATTRIBUTES), wintypes.LPCWSTR],
            wintypes.HANDLE,
        )
        self._SetInformationJobObject = _bind(
            kernel32.SetInformationJobObject,
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            wintypes.BOOL,
        )
        self._QueryInformationJobObject = _bind(
            kernel32.QueryInformationJobObject,
            [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
            ],
            wintypes.BOOL,
        )
        self._CreatePipe = _bind(
            kernel32.CreatePipe,
            [
                ctypes.POINTER(wintypes.HANDLE),
                ctypes.POINTER(wintypes.HANDLE),
                ctypes.POINTER(_SECURITY_ATTRIBUTES),
                wintypes.DWORD,
            ],
            wintypes.BOOL,
        )
        self._SetHandleInformation = _bind(
            kernel32.SetHandleInformation,
            [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD],
            wintypes.BOOL,
        )
        self._CreateFileW = _bind(
            kernel32.CreateFileW,
            [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(_SECURITY_ATTRIBUTES),
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ],
            wintypes.HANDLE,
        )
        self._InitializeProcThreadAttributeList = _bind(
            kernel32.InitializeProcThreadAttributeList,
            [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p],
            wintypes.BOOL,
        )
        self._UpdateProcThreadAttribute = _bind(
            kernel32.UpdateProcThreadAttribute,
            [
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ],
            wintypes.BOOL,
        )
        self._DeleteProcThreadAttributeList = _bind(
            kernel32.DeleteProcThreadAttributeList,
            [ctypes.c_void_p],
            None,
        )
        self._CreateProcessW = _bind(
            kernel32.CreateProcessW,
            [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.BOOL,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.LPCWSTR,
                ctypes.POINTER(_STARTUPINFOW),
                ctypes.POINTER(_PROCESS_INFORMATION),
            ],
            wintypes.BOOL,
        )
        self._ReadFile = _bind(
            kernel32.ReadFile,
            [
                wintypes.HANDLE,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.c_void_p,
            ],
            wintypes.BOOL,
        )
        self._WriteFile = _bind(
            kernel32.WriteFile,
            [
                wintypes.HANDLE,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.c_void_p,
            ],
            wintypes.BOOL,
        )
        self._OpenThread = _bind(
            kernel32.OpenThread,
            [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
            wintypes.HANDLE,
        )
        self._CancelSynchronousIo = _bind(
            kernel32.CancelSynchronousIo,
            [wintypes.HANDLE],
            wintypes.BOOL,
        )
        self._WaitForSingleObject = _bind(
            kernel32.WaitForSingleObject,
            [wintypes.HANDLE, wintypes.DWORD],
            wintypes.DWORD,
        )
        self._GetExitCodeProcess = _bind(
            kernel32.GetExitCodeProcess,
            [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)],
            wintypes.BOOL,
        )
        self._TerminateJobObject = _bind(
            kernel32.TerminateJobObject,
            [wintypes.HANDLE, wintypes.UINT],
            wintypes.BOOL,
        )
        self._CloseHandle = _bind(
            kernel32.CloseHandle, [wintypes.HANDLE], wintypes.BOOL
        )

    @staticmethod
    def _raise_last_error(operation: str) -> None:
        _CtypesWin32Api._raise_error(_last_error(), operation)

    @staticmethod
    def _raise_error(error: int, operation: str) -> None:
        raise OSError(error, f"{operation} failed with Win32 error {error}")


def _bind(function: Any, argument_types: list[object], result_type: object) -> Any:
    function.argtypes = argument_types
    function.restype = result_type
    return function


def _last_error() -> int:
    getter = getattr(ctypes, "get_last_error", None)
    if getter is None:
        return 0
    return int(getter())


def _handle_value(handle: object) -> int:
    if isinstance(handle, int):
        return handle
    value = ctypes.cast(handle, ctypes.c_void_p).value  # type: ignore[arg-type]
    if value is None:
        return 0
    return value


def _environment_block(environment: tuple[tuple[str, str], ...]) -> str:
    ordered = sorted(environment, key=lambda item: item[0].casefold())
    return "\0".join(f"{name}={value}" for name, value in ordered) + "\0\0"


def _present_handles(*handles: int | None) -> list[int]:
    return [handle for handle in handles if handle is not None]


__all__: list[str] = []
