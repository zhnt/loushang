"""Retained Windows service identity and process-exit observations."""

from __future__ import annotations

import ctypes as C
import os
import re
import socket
import sys
from contextlib import ExitStack
from ctypes import wintypes as W
from dataclasses import dataclass, field, replace
from threading import RLock
from time import monotonic
from typing import Any

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl

from ._win32_process import (
    _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
    _SECURITY_ATTRIBUTES,
    _CtypesWin32Api,
)
from .contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
)
from .errors import HostingError, HostingFailureCategory

_WINDOWS = sys.platform == "win32"
_SID = re.compile(r"S-1-(?:0|[1-9][0-9]{0,14})(?:-(?:0|[1-9][0-9]{0,9})){1,15}\Z")
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_JOB_QUERY = 0x0004
_ERROR_ALREADY_EXISTS = 183
_MAX_STARTUP = 128 * 1024
_ATTEMPT = re.compile(r"[a-f0-9]{32}\Z")
_SYNCHRONIZE = 0x100000
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258


@dataclass(frozen=True, slots=True)
class WindowsServiceIdentityV1:
    """Exact process creation time and token user, bound to a native PID."""

    pid: int = field(repr=False)
    creation_filetime: int
    user_id: str

    def __post_init__(self) -> None:
        if (
            type(self.pid) is not int or not 1 <= self.pid < 2**32
            or type(self.creation_filetime) is not int or not 0 < self.creation_filetime < 2**64
            or type(self.user_id) is not str or _SID.fullmatch(self.user_id) is None
        ):
            raise _error(HostingFailureCategory.INVALID_REQUEST)


class WindowsServiceObserverV1:
    """Retain one process object without rights to terminate it."""

    def __init__(self, kernel: Any, handle: int, identity: WindowsServiceIdentityV1) -> None:
        self._kernel = kernel
        self._handle: int | None = handle
        self._identity = identity
        self._mutex = RLock()
        self._close_unknown = False

    @property
    def identity(self) -> WindowsServiceIdentityV1:
        return self._identity

    @classmethod
    def capture(cls, pid: int) -> WindowsServiceObserverV1:
        return cls._open(pid, None)

    @classmethod
    def reopen(cls, expected: WindowsServiceIdentityV1) -> WindowsServiceObserverV1:
        if type(expected) is not WindowsServiceIdentityV1:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        return cls._open(expected.pid, expected)

    @classmethod
    def _open(cls, pid: int, expected: WindowsServiceIdentityV1 | None) -> WindowsServiceObserverV1:
        if not _WINDOWS:
            raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
        if type(pid) is not int or not 1 <= pid < 2**32:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        kernel = _bind_kernel()
        handle = kernel.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid)
        if not handle:
            raise _error(HostingFailureCategory.PREPARATION_FAILED)
        try:
            creation, exit_time, kernel_time, user_time = (W.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(
                handle, C.byref(creation), C.byref(exit_time), C.byref(kernel_time), C.byref(user_time),
            ):
                raise _error(HostingFailureCategory.PREPARATION_FAILED)
            with WindowsPrivateDirectoryAcl() as acl:
                user_id = acl.process_user_sid(handle)
                if user_id != acl.user_sid:
                    raise _error(HostingFailureCategory.PREPARATION_REJECTED)
            created = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            identity = WindowsServiceIdentityV1(pid, created, user_id)
            if expected is not None and expected != identity:
                raise _error(HostingFailureCategory.PREPARATION_STALE)
            return cls(kernel, handle, identity)
        except BaseException as error:
            if not kernel.CloseHandle(handle):
                error.add_note("service_observer_cleanup_incomplete")
            if isinstance(error, OSError):
                raise _error(HostingFailureCategory.PREPARATION_FAILED) from None
            raise

    def open_scope(self, attempt_id: str) -> WindowsServiceJobV1:
        with self._mutex:
            if self._handle is None:
                raise _error(HostingFailureCategory.HOST_CLOSED)
            return WindowsServiceJobV1.reopen(self._kernel, self._handle, attempt_id)

    def exited(self, *, timeout: float = 0.0) -> bool:
        if type(timeout) not in (int, float) or not 0 <= timeout <= 30:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        deadline = monotonic() + timeout
        if not self._mutex.acquire(timeout=timeout):
            raise _error(HostingFailureCategory.CAPACITY_EXHAUSTED)
        try:
            if self._handle is None:
                raise _error(HostingFailureCategory.HOST_CLOSED)
            result = self._kernel.WaitForSingleObject(self._handle, int(max(0, deadline - monotonic()) * 1000))
            if result not in {_WAIT_OBJECT_0, _WAIT_TIMEOUT}:
                raise _error(HostingFailureCategory.PREPARATION_FAILED)
            return result == _WAIT_OBJECT_0
        finally:
            self._mutex.release()

    def close(self) -> None:
        if not self._mutex.acquire(timeout=30):
            raise _error(HostingFailureCategory.CLEANUP_FAILED)
        try:
            if self._close_unknown:
                raise _error(HostingFailureCategory.CLEANUP_FAILED)
            handle, self._handle = self._handle, None
            if handle is not None:
                self._close_unknown = True
                if not self._kernel.CloseHandle(handle):
                    raise _error(HostingFailureCategory.CLEANUP_FAILED)
                self._close_unknown = False
        finally:
            self._mutex.release()



class WindowsServiceJobV1:
    """Named service scope with no kill-on-close or breakaway rights."""

    def __init__(self, kernel: Any, handle: int) -> None:
        self._kernel = kernel
        self._handle: int | None = handle
        self._close_unknown = False

    @property
    def handle(self) -> int:
        if self._handle is None:
            raise _error(HostingFailureCategory.HOST_CLOSED)
        return self._handle

    @classmethod
    def create(cls, kernel: Any, attempt_id: str) -> WindowsServiceJobV1:
        name = _job_name(attempt_id)
        with WindowsPrivateDirectoryAcl() as acl:
            attributes = _SECURITY_ATTRIBUTES(C.sizeof(_SECURITY_ATTRIBUTES), acl.security_descriptor, False)
            handle = kernel.CreateJobObjectW(C.byref(attributes), name)
            error = getattr(C, "get_last_error")()
        if not handle:
            raise _error(HostingFailureCategory.SPAWN_FAILED)
        scope = cls(kernel, handle)
        if error == _ERROR_ALREADY_EXISTS:
            scope.close()
            raise _error(HostingFailureCategory.PREPARATION_STALE)
        return scope

    @classmethod
    def reopen(cls, kernel: Any, process: int, attempt_id: str) -> WindowsServiceJobV1:
        handle = kernel.OpenJobObjectW(_JOB_QUERY, False, _job_name(attempt_id))
        if not handle:
            raise _error(HostingFailureCategory.PREPARATION_FAILED)
        scope = cls(kernel, handle)
        try:
            if not _in_job(kernel, process, handle):
                raise _error(HostingFailureCategory.PREPARATION_STALE)
            return scope
        except BaseException:
            scope.close()
            raise

    def exited(self) -> bool:
        accounting = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        if not self._kernel.QueryInformationJobObject(
            self.handle, 1, C.byref(accounting), C.sizeof(accounting), None,
        ):
            raise _error(HostingFailureCategory.PREPARATION_FAILED)
        return accounting.ActiveProcesses == 0

    def close(self) -> None:
        if self._close_unknown:
            raise _error(HostingFailureCategory.CLEANUP_FAILED)
        handle, self._handle = self._handle, None
        if handle is not None:
            self._close_unknown = True
            if not self._kernel.CloseHandle(handle):
                raise _error(HostingFailureCategory.CLEANUP_FAILED)
            self._close_unknown = False


@dataclass(frozen=True, slots=True)
class WindowsServiceLaunchRequestV1:
    """Bounded private startup data sent over the inherited service channel."""

    process: ProcessLaunchRequest
    startup: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (type(self.process) is not ProcessLaunchRequest
                or type(self.startup) is not bytes or not 0 < len(self.startup) <= _MAX_STARTUP):
            raise _error(HostingFailureCategory.INVALID_REQUEST)


class WindowsServiceProcessV1:
    """Launch one detached child and release only the launcher's native handles."""

    def __init__(self, request: WindowsServiceLaunchRequestV1, child_endpoint: socket.socket,
                 attempt_id: str) -> None:
        if not _WINDOWS:
            raise _error(HostingFailureCategory.PLATFORM_UNSUPPORTED)
        _job_name(attempt_id)
        if type(request) is not WindowsServiceLaunchRequestV1 or type(child_endpoint) is not socket.socket:
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        launch = request.process
        if (not os.path.isabs(launch.argv[0]) or launch.streams.stdin is not ProcessStdinMode.CLOSED
                or launch.streams.stdout is not ProcessStdoutMode.DISCARD
                or launch.streams.stderr is not ProcessStderrMode.DISCARD):
            raise _error(HostingFailureCategory.INVALID_REQUEST)
        self._request: WindowsServiceLaunchRequestV1 | None = request
        self._child = child_endpoint
        self._attempt = attempt_id
        self._observer: WindowsServiceObserverV1 | None = None
        self._scope: WindowsServiceJobV1 | None = None
        self._identity: WindowsServiceIdentityV1 | None = None
        self._launcher_handle: int | None = None
        self._launcher_close_unknown = False
        self._child_closed = self._child_close_unknown = self._closed = False
        self._mutex = RLock()

    @property
    def identity(self) -> WindowsServiceIdentityV1 | None:
        return self._identity

    @property
    def handles_closed(self) -> bool:
        return self._closed

    def spawn(self, parent: socket.socket, *, deadline: float) -> WindowsServiceIdentityV1:
        with self._mutex:
            request, self._request = self._request, None
            if request is None or monotonic() >= deadline:
                raise _error(HostingFailureCategory.SPAWN_FAILED)
            kernel = _bind_kernel()
            self._scope = WindowsServiceJobV1.create(kernel, self._attempt)
            try:
                self._launch(request.process, kernel, self._scope.handle)
                self._close_child()
                pid = self._send_startup(parent, request.startup, deadline)
                # A venv executable can be a redirector. Bind the actual
                # interpreter that adopted the inherited job and channel.
                self._observer = WindowsServiceObserverV1.capture(pid)
                assert self._observer._handle is not None
                if not _in_job(kernel, self._observer._handle, self._scope.handle):
                    raise _error(HostingFailureCategory.PREPARATION_STALE)
                self._identity = self._observer.identity
                self._close_launcher(kernel)
                return self._identity
            except OSError:
                raise _error(HostingFailureCategory.SPAWN_FAILED) from None

    def _launch(self, request: ProcessLaunchRequest, kernel: Any, job: int) -> None:
        set_inheritable = getattr(os, "set_handle_inheritable")
        launch = replace(request, argv=(*request.argv, str(job)))
        with ExitStack() as restore:
            self._child.set_inheritable(True)
            restore.callback(self._child.set_inheritable, False)
            set_inheritable(job, True)
            restore.callback(set_inheritable, job, False)
            self._launcher_handle = _CtypesWin32Api().spawn_service(
                launch, job, self._child.fileno(), breakaway=_in_job(kernel, kernel.GetCurrentProcess(), None),
            )

    @staticmethod
    def _send_startup(parent: socket.socket, startup: bytes, deadline: float) -> int:
        timeout = parent.gettimeout()
        try:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError
            parent.settimeout(min(5.0, remaining))
            parent.sendall(len(startup).to_bytes(4, "big") + startup)
            return int.from_bytes(_receive(parent, 4, deadline), "big")
        finally:
            parent.settimeout(timeout)

    def _close_launcher(self, kernel: Any) -> None:
        if self._launcher_close_unknown:
            raise _error(HostingFailureCategory.CLEANUP_FAILED)
        handle, self._launcher_handle = self._launcher_handle, None
        if handle is not None:
            self._launcher_close_unknown = True
            if not kernel.CloseHandle(handle):
                raise _error(HostingFailureCategory.CLEANUP_FAILED)
            self._launcher_close_unknown = False

    def _close_child(self) -> None:
        if self._child_close_unknown:
            raise _error(HostingFailureCategory.CLEANUP_FAILED)
        if not self._child_closed:
            self._child_close_unknown = True
            self._child.close()
            self._child_closed = True
            self._child_close_unknown = False

    def close(self) -> None:
        with self._mutex:
            self._request = None
            try:
                with ExitStack() as cleanup:
                    if self._launcher_handle is not None or self._launcher_close_unknown:
                        cleanup.callback(self._close_launcher, _bind_kernel())
                    if self._observer is not None:
                        cleanup.callback(self._observer.close)
                    if self._scope is not None:
                        cleanup.callback(self._scope.close)
                    self._close_child()
            except OSError:
                raise _error(HostingFailureCategory.CLEANUP_FAILED) from None
            self._closed = True


def read_windows_service_startup(endpoint: socket.socket, job: int) -> bytes:
    """Acquire startup bytes before taking any application authority."""

    getattr(os, "set_handle_inheritable")(job, False)
    endpoint.set_inheritable(False)
    deadline = monotonic() + 15.0
    size = int.from_bytes(_receive(endpoint, 4, deadline), "big")
    if not 0 < size <= _MAX_STARTUP:
        raise _error(HostingFailureCategory.INVALID_REQUEST)
    payload = _receive(endpoint, size, deadline)
    kernel = _bind_kernel()
    if not _in_job(kernel, kernel.GetCurrentProcess(), job):
        raise _error(HostingFailureCategory.PREPARATION_STALE)
    # Keep the inherited job handle until OS exit. This preserves the named
    # scope for later status/stop processes after the original launcher exits.
    endpoint.settimeout(5.0)
    endpoint.sendall(os.getpid().to_bytes(4, "big"))
    endpoint.settimeout(None)
    return payload


def _receive(endpoint: socket.socket, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError
        endpoint.settimeout(remaining)
        block = endpoint.recv(size - len(data))
        if not block:
            raise _error(HostingFailureCategory.PREPARATION_FAILED)
        data.extend(block)
    return bytes(data)


def _job_name(attempt_id: str) -> str:
    if type(attempt_id) is not str or _ATTEMPT.fullmatch(attempt_id) is None:
        raise _error(HostingFailureCategory.INVALID_REQUEST)
    return "Global\\Loushang.AppHost." + attempt_id


def _in_job(kernel: Any, process: int, job: int | None) -> bool:
    result = W.BOOL()
    if not kernel.IsProcessInJob(process, job, C.byref(result)):
        raise _error(HostingFailureCategory.PREPARATION_FAILED)
    return bool(result.value)


def _bind_kernel() -> Any:
    kernel = getattr(C, "WinDLL")("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (W.DWORD, W.BOOL, W.DWORD)
    kernel.OpenProcess.restype = W.HANDLE
    kernel.GetProcessTimes.argtypes = (W.HANDLE, *(C.POINTER(W.FILETIME) for _ in range(4)))
    kernel.GetProcessTimes.restype = W.BOOL
    kernel.WaitForSingleObject.argtypes = (W.HANDLE, W.DWORD)
    kernel.WaitForSingleObject.restype = W.DWORD
    kernel.GetCurrentProcess.argtypes = ()
    kernel.GetCurrentProcess.restype = W.HANDLE
    kernel.IsProcessInJob.argtypes = (W.HANDLE, W.HANDLE, C.POINTER(W.BOOL))
    kernel.IsProcessInJob.restype = W.BOOL
    kernel.CreateJobObjectW.argtypes = (C.POINTER(_SECURITY_ATTRIBUTES), W.LPCWSTR)
    kernel.CreateJobObjectW.restype = W.HANDLE
    kernel.OpenJobObjectW.argtypes = (W.DWORD, W.BOOL, W.LPCWSTR)
    kernel.OpenJobObjectW.restype = W.HANDLE
    kernel.QueryInformationJobObject.argtypes = (W.HANDLE, C.c_int, W.LPVOID, W.DWORD, C.POINTER(W.DWORD))
    kernel.QueryInformationJobObject.restype = W.BOOL
    kernel.CloseHandle.argtypes = (W.HANDLE,)
    kernel.CloseHandle.restype = W.BOOL
    return kernel


def _error(category: HostingFailureCategory) -> HostingError:
    return HostingError(category, "service_observer_" + category.value)
