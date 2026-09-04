"""Private, import-safe Win32 calls for the Windows Hosting backend."""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys
from collections.abc import Callable
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
_TOKEN_ASSIGN_PRIMARY = 0x0001
_TOKEN_DUPLICATE = 0x0002
_TOKEN_QUERY = 0x0008
_DISABLE_MAX_PRIVILEGE = 0x00000001
_LUA_TOKEN = 0x00000004
_WRITE_RESTRICTED = 0x00000008
_WIN_WORLD_SID = 1
_WIN_BUILTIN_ADMINISTRATORS_SID = 26
_WIN_BUILTIN_USERS_SID = 27
_SECURITY_MAX_SID_SIZE = 68
_TOKEN_USER_INFORMATION_CLASS = 1
_TOKEN_GROUPS_INFORMATION_CLASS = 2
_SE_GROUP_LOGON_ID = 0xC0000000
_MAX_TOKEN_GROUPS = 1024
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_NAME_NORMALIZED = 0x0
_FILE_ID_INFO_CLASS = 18
_MAX_FINAL_PATH_CHARS = 32768


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", wintypes.DWORD),
    ]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _TOKEN_GROUPS(ctypes.Structure):
    _fields_ = [
        ("GroupCount", wintypes.DWORD),
        ("Groups", _SID_AND_ATTRIBUTES * 1),
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


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _FILE_ID_128(ctypes.Structure):
    _fields_ = [("Identifier", wintypes.BYTE * 16)]


class _FILE_ID_INFO(ctypes.Structure):
    _fields_ = [
        ("VolumeSerialNumber", ctypes.c_ulonglong),
        ("FileId", _FILE_ID_128),
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
    cleanup_handles: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class _Win32LockedPathIdentity:
    volume_serial: int
    file_id: int
    size: int
    final_path: str
    is_directory: bool


class _Win32CreateNotStarted(Exception):
    """Expected setup failure before the unique CreateProcess effect."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__("Win32 process creation did not start")
        self.cause = cause


class _Win32CreateSettledWithoutProcess(Exception):
    """CreateProcessAsUserW returned false and created no process owner."""

    def __init__(self, cause: OSError) -> None:
        super().__init__("Win32 process creation settled without a process")
        self.cause = cause


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
            self._advapi32 = loader("advapi32", use_last_error=True)
            self._bind_functions()
        except (AttributeError, OSError) as exc:
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "required atomic Win32 process APIs are unavailable",
            ) from exc

    def platform_identity(self) -> str:
        machine = platform.machine().lower()
        if machine not in {"amd64", "x86_64"}:
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows managed launch requires AMD64",
            )
        version = sys.getwindowsversion()  # type: ignore[attr-defined]
        return f"windows-amd64-{version.major}.{version.minor}.{version.build}"

    def open_locked_file(
        self,
        path: str,
        *,
        on_acquired: Callable[[int], None],
    ) -> int:
        return self._open_locked_path(
            path,
            directory=False,
            on_acquired=on_acquired,
        )

    def open_locked_directory(
        self,
        path: str,
        *,
        on_acquired: Callable[[int], None],
    ) -> int:
        return self._open_locked_path(
            path,
            directory=True,
            on_acquired=on_acquired,
        )

    def locked_path_identity(self, handle: int) -> _Win32LockedPathIdentity:
        information = _BY_HANDLE_FILE_INFORMATION()
        if not self._GetFileInformationByHandle(handle, ctypes.byref(information)):
            self._raise_last_error("GetFileInformationByHandle")
        file_id = _FILE_ID_INFO()
        if not self._GetFileInformationByHandleEx(
            handle,
            _FILE_ID_INFO_CLASS,
            ctypes.byref(file_id),
            ctypes.sizeof(file_id),
        ):
            self._raise_last_error("GetFileInformationByHandleEx(FileIdInfo)")
        attributes = int(information.dwFileAttributes)
        if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows managed launch rejects reparse-point paths",
            )
        buffer = ctypes.create_unicode_buffer(_MAX_FINAL_PATH_CHARS)
        length = self._GetFinalPathNameByHandleW(
            handle,
            buffer,
            len(buffer),
            _FILE_NAME_NORMALIZED,
        )
        if length == 0:
            self._raise_last_error("GetFinalPathNameByHandleW")
        if length >= len(buffer):
            raise OSError("Windows final path exceeds its retained bound")
        return _Win32LockedPathIdentity(
            volume_serial=int(file_id.VolumeSerialNumber),
            file_id=int.from_bytes(bytes(file_id.FileId.Identifier), "little"),
            size=(int(information.nFileSizeHigh) << 32)
            | int(information.nFileSizeLow),
            final_path=buffer.value,
            is_directory=bool(attributes & _FILE_ATTRIBUTE_DIRECTORY),
        )

    def open_process_token(self) -> int:
        token = wintypes.HANDLE()
        access = _TOKEN_ASSIGN_PRIMARY | _TOKEN_DUPLICATE | _TOKEN_QUERY
        if not self._OpenProcessToken(
            self._GetCurrentProcess(),
            access,
            ctypes.byref(token),
        ):
            self._raise_last_error("OpenProcessToken")
        return _handle_value(token)

    def create_restricted_token(self, source_token: int) -> int:
        user_size = wintypes.DWORD()
        self._GetTokenInformation(
            source_token,
            _TOKEN_USER_INFORMATION_CLASS,
            None,
            0,
            ctypes.byref(user_size),
        )
        if user_size.value < ctypes.sizeof(_TOKEN_USER):
            self._raise_last_error("GetTokenInformation(TokenUser size)")
        user_storage = ctypes.create_string_buffer(user_size.value)
        if not self._GetTokenInformation(
            source_token,
            _TOKEN_USER_INFORMATION_CLASS,
            ctypes.byref(user_storage),
            user_size.value,
            ctypes.byref(user_size),
        ):
            self._raise_last_error("GetTokenInformation(TokenUser)")
        user_sid = ctypes.cast(
            ctypes.byref(user_storage),
            ctypes.POINTER(_TOKEN_USER),
        ).contents.User.Sid

        groups_size = wintypes.DWORD()
        self._GetTokenInformation(
            source_token,
            _TOKEN_GROUPS_INFORMATION_CLASS,
            None,
            0,
            ctypes.byref(groups_size),
        )
        if groups_size.value < ctypes.sizeof(_TOKEN_GROUPS):
            self._raise_last_error("GetTokenInformation(TokenGroups size)")
        groups_storage = ctypes.create_string_buffer(groups_size.value)
        if not self._GetTokenInformation(
            source_token,
            _TOKEN_GROUPS_INFORMATION_CLASS,
            ctypes.byref(groups_storage),
            groups_size.value,
            ctypes.byref(groups_size),
        ):
            self._raise_last_error("GetTokenInformation(TokenGroups)")
        token_groups = ctypes.cast(
            ctypes.byref(groups_storage),
            ctypes.POINTER(_TOKEN_GROUPS),
        ).contents
        group_count = int(token_groups.GroupCount)
        available_group_count = (
            groups_size.value - _TOKEN_GROUPS.Groups.offset
        ) // ctypes.sizeof(_SID_AND_ATTRIBUTES)
        if (
            group_count < 1
            or group_count > _MAX_TOKEN_GROUPS
            or group_count > available_group_count
        ):
            raise OSError("Windows token group list is invalid")
        group_array_type = _SID_AND_ATTRIBUTES * group_count
        groups = ctypes.cast(
            ctypes.byref(groups_storage, _TOKEN_GROUPS.Groups.offset),
            ctypes.POINTER(group_array_type),
        ).contents
        logon_sids = [
            group.Sid
            for group in groups
            if group.Attributes & _SE_GROUP_LOGON_ID == _SE_GROUP_LOGON_ID
        ]
        if len(logon_sids) != 1:
            raise OSError("Windows token must contain exactly one logon SID")

        admin_storage = ctypes.create_string_buffer(_SECURITY_MAX_SID_SIZE)
        admin_size = wintypes.DWORD(ctypes.sizeof(admin_storage))
        if not self._CreateWellKnownSid(
            _WIN_BUILTIN_ADMINISTRATORS_SID,
            None,
            ctypes.byref(admin_storage),
            ctypes.byref(admin_size),
        ):
            self._raise_last_error(
                "CreateWellKnownSid(WinBuiltinAdministratorsSid)"
            )
        disabled_sids = (_SID_AND_ATTRIBUTES * 1)(
            _SID_AND_ATTRIBUTES(
                Sid=ctypes.cast(admin_storage, ctypes.c_void_p),
                Attributes=0,
            )
        )

        world_storage = ctypes.create_string_buffer(_SECURITY_MAX_SID_SIZE)
        world_size = wintypes.DWORD(ctypes.sizeof(world_storage))
        if not self._CreateWellKnownSid(
            _WIN_WORLD_SID,
            None,
            ctypes.byref(world_storage),
            ctypes.byref(world_size),
        ):
            self._raise_last_error("CreateWellKnownSid(WinWorldSid)")
        users_storage = ctypes.create_string_buffer(_SECURITY_MAX_SID_SIZE)
        users_size = wintypes.DWORD(ctypes.sizeof(users_storage))
        if not self._CreateWellKnownSid(
            _WIN_BUILTIN_USERS_SID,
            None,
            ctypes.byref(users_storage),
            ctypes.byref(users_size),
        ):
            self._raise_last_error("CreateWellKnownSid(WinBuiltinUsersSid)")
        restricting_sids = (_SID_AND_ATTRIBUTES * 4)(
            _SID_AND_ATTRIBUTES(Sid=user_sid, Attributes=0),
            _SID_AND_ATTRIBUTES(Sid=logon_sids[0], Attributes=0),
            _SID_AND_ATTRIBUTES(
                Sid=ctypes.cast(world_storage, ctypes.c_void_p),
                Attributes=0,
            ),
            _SID_AND_ATTRIBUTES(
                Sid=ctypes.cast(users_storage, ctypes.c_void_p),
                Attributes=0,
            ),
        )
        token = wintypes.HANDLE()
        flags = _DISABLE_MAX_PRIVILEGE | _LUA_TOKEN | _WRITE_RESTRICTED
        if not self._CreateRestrictedToken(
            source_token,
            flags,
            1,
            ctypes.byref(disabled_sids),
            0,
            None,
            4,
            ctypes.byref(restricting_sids),
            ctypes.byref(token),
        ):
            self._raise_last_error("CreateRestrictedToken")
        return _handle_value(token)

    def token_is_restricted(self, token: int) -> bool:
        return bool(self._IsTokenRestricted(token))

    def create_managed_job(
        self,
        *,
        on_acquired: Callable[[int], None],
    ) -> int:
        return self._create_job(on_acquired=on_acquired)

    def managed_job_is_kill_on_close(self, job: int) -> bool:
        limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        if not self._QueryInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
            None,
        ):
            self._raise_last_error("QueryInformationJobObject")
        return bool(
            limits.BasicLimitInformation.LimitFlags
            & _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )

    def create_managed_stderr(self) -> int:
        return self._null_handle(read=False)

    def spawn_restricted(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int],
        *,
        executable_handle: int,
        cwd_handle: int,
        token: int,
        job: int,
        stderr_handle: int,
        begin_effect: Callable[[], None],
    ) -> _Win32SpawnHandles:
        child_stdin, child_stdout = endpoint_handles
        native_handles = (child_stdin, child_stdout, stderr_handle, token, job)
        if any(type(handle) is not int or handle <= 0 for handle in native_handles):
            raise _Win32CreateNotStarted(
                HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "Windows managed launch received invalid native handles",
                )
            )
        if len(set(native_handles)) != len(native_handles):
            raise _Win32CreateNotStarted(
                HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "Windows endpoint and preparation handles collide",
                )
            )
        attributes: _Win32AttributeList | None = None
        try:
            attributes = self._attribute_list(
                job,
                (child_stdin, child_stdout, stderr_handle),
            )
            startup = _STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = child_stdin
            startup.StartupInfo.hStdOutput = child_stdout
            startup.StartupInfo.hStdError = stderr_handle
            startup.lpAttributeList = attributes.pointer
            process_information = _PROCESS_INFORMATION()
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline(request.argv)
            )
            environment = ctypes.create_unicode_buffer(
                _environment_block(request.effective_environment)
            )
            # Resolve the retained identities inside the synchronous effect
            # seam, immediately before CreateProcessAsUserW. This follows a
            # legitimate pre-effect rename instead of re-resolving the
            # caller's stale path string.
            executable = self.locked_path_identity(executable_handle)
            current_cwd = self.locked_path_identity(cwd_handle)
            if executable.is_directory or not current_cwd.is_directory:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_STALE,
                    "Windows retained launch path kind changed",
                )
        except BaseException as cause:
            if attributes is not None:
                self._DeleteProcThreadAttributeList(attributes.pointer)
            raise _Win32CreateNotStarted(cause) from cause

        try:
            begin_effect()
            created = self._CreateProcessAsUserW(
                token,
                executable.final_path,
                command_line,
                None,
                None,
                True,
                _EXTENDED_STARTUPINFO_PRESENT
                | _CREATE_UNICODE_ENVIRONMENT
                | _CREATE_NO_WINDOW,
                ctypes.cast(environment, ctypes.c_void_p),
                current_cwd.final_path,
                ctypes.byref(startup.StartupInfo),
                ctypes.byref(process_information),
            )
            if not created:
                try:
                    self._raise_last_error("CreateProcessAsUserW")
                except OSError as cause:
                    raise _Win32CreateSettledWithoutProcess(cause) from cause
                raise AssertionError("CreateProcessAsUserW error was not raised")
            process_handle = _handle_value(process_information.hProcess)
            thread_handle = _handle_value(process_information.hThread)
            if process_handle <= 0 or thread_handle <= 0:
                raise RuntimeError("CreateProcessAsUserW returned invalid handles")
            # Every post-create handle is returned to one process owner.  No
            # cleanup call can turn a known created process into an ambiguous
            # exception before synchronous attachment.
            return _Win32SpawnHandles(
                process=process_handle,
                job=job,
                stdin_write=None,
                stdout_read=None,
                stderr_read=None,
                cleanup_handles=(thread_handle, stderr_handle),
            )
        finally:
            self._DeleteProcThreadAttributeList(attributes.pointer)

    def _open_locked_path(
        self,
        path: str,
        *,
        directory: bool,
        on_acquired: Callable[[int], None],
    ) -> int:
        flags = _FILE_FLAG_OPEN_REPARSE_POINT
        share = _FILE_SHARE_READ
        if directory:
            flags |= _FILE_FLAG_BACKUP_SEMANTICS
            share |= _FILE_SHARE_WRITE
        raw_handle = self._CreateFileW(
            path,
            _FILE_READ_ATTRIBUTES | (0 if directory else _GENERIC_READ),
            share,
            None,
            _OPEN_EXISTING,
            flags,
            None,
        )
        handle = _handle_value(raw_handle)
        if handle == _INVALID_HANDLE_VALUE:
            self._raise_last_error("CreateFileW(locked path)")
        # Transfer ownership before any operation that can fail.  The caller's
        # attached material, not this helper's stack, is now the retryable
        # cleanup authority for the raw handle.
        on_acquired(handle)
        identity = self.locked_path_identity(handle)
        if identity.is_directory is not directory:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows managed launch path kind is invalid",
            )
        return handle

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

    def _create_job(
        self,
        *,
        on_acquired: Callable[[int], None] | None = None,
    ) -> int:
        raw_job = self._CreateJobObjectW(None, None)
        if not raw_job:
            self._raise_last_error("CreateJobObjectW")
        job = _handle_value(raw_job)
        if on_acquired is not None:
            on_acquired(job)
        limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = _last_error()
            if on_acquired is None:
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
        advapi32: Any = self._advapi32
        self._GetCurrentProcess = _bind(
            kernel32.GetCurrentProcess,
            [],
            wintypes.HANDLE,
        )
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
        self._GetFileInformationByHandle = _bind(
            kernel32.GetFileInformationByHandle,
            [wintypes.HANDLE, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)],
            wintypes.BOOL,
        )
        self._GetFileInformationByHandleEx = _bind(
            kernel32.GetFileInformationByHandleEx,
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            wintypes.BOOL,
        )
        self._GetFinalPathNameByHandleW = _bind(
            kernel32.GetFinalPathNameByHandleW,
            [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD],
            wintypes.DWORD,
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
        self._OpenProcessToken = _bind(
            advapi32.OpenProcessToken,
            [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)],
            wintypes.BOOL,
        )
        self._CreateRestrictedToken = _bind(
            advapi32.CreateRestrictedToken,
            [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.HANDLE),
            ],
            wintypes.BOOL,
        )
        self._CreateWellKnownSid = _bind(
            advapi32.CreateWellKnownSid,
            [
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.DWORD),
            ],
            wintypes.BOOL,
        )
        self._GetTokenInformation = _bind(
            advapi32.GetTokenInformation,
            [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
            ],
            wintypes.BOOL,
        )
        self._IsTokenRestricted = _bind(
            advapi32.IsTokenRestricted,
            [wintypes.HANDLE],
            wintypes.BOOL,
        )
        self._CreateProcessAsUserW = _bind(
            advapi32.CreateProcessAsUserW,
            [
                wintypes.HANDLE,
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
