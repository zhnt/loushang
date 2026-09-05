"""Private, import-safe Win32 calls for the Windows Hosting backend."""

from __future__ import annotations

import ctypes
import hashlib
import ntpath
import os
import platform
import stat
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
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
_CREATE_SUSPENDED = 0x00000004
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY = 0x0002000F
_PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT = 0x00000001
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE = 0xFFFFFFFF
_STILL_ACTIVE = 259
_ERROR_BROKEN_PIPE = 109
_ERROR_INVALID_PARAMETER = 87
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_ALREADY_EXISTS = 183
_ERROR_NO_DATA = 232
_ERROR_OPERATION_ABORTED = 995
_ERROR_NOT_FOUND = 1168
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_THREAD_TERMINATE = 0x0001
_TOKEN_ASSIGN_PRIMARY = 0x0001
_TOKEN_DUPLICATE = 0x0002
_TOKEN_QUERY = 0x0008
_SECURITY_IMPERSONATION = 2
_CTMF_INCLUDE_APPCONTAINER = 0x00000001
_WIN_BUILTIN_ANY_PACKAGE_SID = 84
_SECURITY_MAX_SID_SIZE = 68
_DISABLE_MAX_PRIVILEGE = 0x00000001
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
_TOKEN_IS_APP_CONTAINER = 29
_TOKEN_CAPABILITIES = 30
_TOKEN_APP_CONTAINER_SID = 31
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_GRANT_ACCESS = 1
_REVOKE_ACCESS = 4
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_UNKNOWN = 0
_SUB_CONTAINERS_AND_OBJECTS_INHERIT = 0x3
_ACCESS_ALLOWED_ACE_TYPE = 0
_ACCESS_DENIED_ACE_TYPE = 1
_ACCESS_ALLOWED_COMPOUND_ACE_TYPE = 4
_ACCESS_ALLOWED_OBJECT_ACE_TYPE = 5
_ACCESS_DENIED_OBJECT_ACE_TYPE = 6
_ACCESS_ALLOWED_CALLBACK_ACE_TYPE = 9
_ACCESS_DENIED_CALLBACK_ACE_TYPE = 10
_ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE = 11
_ACCESS_DENIED_CALLBACK_OBJECT_ACE_TYPE = 12
_ACE_OBJECT_TYPE_PRESENT = 0x00000001
_ACE_INHERITED_OBJECT_TYPE_PRESENT = 0x00000002
_ACL_SIZE_INFORMATION_CLASS = 2
_FILE_TRAVERSE_READ = 0x001200A0
_GENERIC_EXECUTE = 0x20000000
_FIND_STREAM_INFO_STANDARD = 0
_ERROR_HANDLE_EOF = 38
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_FILE_ATTRIBUTE_REPARSE_POINT_STAT = 0x00000400
_MAX_LPAC_PRIVATE_ENTRIES = 4096
_MAX_LPAC_PRIVATE_BYTES = 128 * 1024 * 1024
_MAX_LPAC_PRIVATE_DEPTH = 32
_LPAC_REJECT_SETTLEMENT_MILLISECONDS = 5000


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(_SID_AND_ATTRIBUTES)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _TRUSTEE_W(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", ctypes.c_int),
        ("TrusteeForm", ctypes.c_int),
        ("TrusteeType", ctypes.c_int),
        ("ptstrName", wintypes.LPWSTR),
    ]


class _EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", ctypes.c_int),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", _TRUSTEE_W),
    ]


class _ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", wintypes.WORD),
    ]


class _ACCESS_ALLOWED_ACE(ctypes.Structure):
    _fields_ = [
        ("Header", _ACE_HEADER),
        ("Mask", wintypes.DWORD),
        ("SidStart", wintypes.DWORD),
    ]


class _WIN32_FIND_STREAM_DATA(ctypes.Structure):
    _fields_ = [
        ("StreamSize", ctypes.c_longlong),
        ("cStreamName", wintypes.WCHAR * 296),
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
    link_count: int = 1


@dataclass(frozen=True, slots=True)
class _Win32LpacIdentity:
    sid: int
    sid_text: str


@dataclass(frozen=True, slots=True)
class _Win32LpacProfile:
    sid: int
    sid_text: str
    private_root: str


@dataclass(frozen=True, slots=True)
class _Win32LpacTokenIdentity:
    sid_text: str
    capability_count: int
    is_app_container: bool
    is_lpac: bool


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


class _Win32ProfileAlreadyExists(Exception):
    """The exact LPAC moniker already names a profile not owned by this call."""


class _Win32ProfileNotFound(Exception):
    """The exact LPAC moniker has no registered profile."""


@dataclass(frozen=True, slots=True)
class _Win32AttributeList:
    storage: ctypes.Array[ctypes.c_char]
    pointer: ctypes.c_void_p
    jobs: ctypes.Array[Any]
    handles: ctypes.Array[Any]
    security_capabilities: _SECURITY_CAPABILITIES | None = None
    all_application_packages_policy: wintypes.DWORD | None = None


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
            self._userenv = loader("userenv", use_last_error=True)
            self._ole32 = loader("ole32", use_last_error=True)
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

    def canonical_system_root(self) -> str:
        """Return the OS-owned Windows directory without consulting ambient env."""

        buffer = ctypes.create_unicode_buffer(_MAX_FINAL_PATH_CHARS)
        length = self._GetWindowsDirectoryW(buffer, len(buffer))
        if length == 0:
            self._raise_last_error("GetWindowsDirectoryW")
        if length >= len(buffer):
            raise OSError("Windows directory exceeds its retained bound")
        value = ntpath.normpath(buffer.value)
        drive, tail = ntpath.splitdrive(value)
        if (
            not value
            or "\0" in value
            or len(drive) != 2
            or drive[1:] != ":"
            or not tail.startswith("\\")
            or not ntpath.isabs(value)
        ):
            raise OSError("Windows directory is not a canonical local path")
        return value

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
            size=(int(information.nFileSizeHigh) << 32) | int(information.nFileSizeLow),
            final_path=buffer.value,
            is_directory=bool(attributes & _FILE_ATTRIBUTE_DIRECTORY),
            link_count=int(information.nNumberOfLinks),
        )

    def locked_file_sha256(self, handle: int) -> str:
        identity = self.locked_path_identity(handle)
        if identity.is_directory:
            raise OSError("Windows locked digest target is a directory")
        return hashlib.sha256(Path(identity.final_path).read_bytes()).hexdigest()

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
        token = wintypes.HANDLE()
        if not self._CreateRestrictedToken(
            source_token,
            _DISABLE_MAX_PRIVILEGE,
            0,
            None,
            0,
            None,
            0,
            None,
            ctypes.byref(token),
        ):
            self._raise_last_error("CreateRestrictedToken")
        return _handle_value(token)

    def create_lpac_profile(
        self,
        profile_name: str,
        *,
        on_acquired: Callable[[_Win32LpacProfile], None],
    ) -> _Win32LpacProfile:
        """Create one fresh zero-capability AppContainer profile.

        ``ERROR_ALREADY_EXISTS`` is deliberately not adopted: the caller that
        performed this create has no authority over a predecessor's profile.
        """

        sid = ctypes.c_void_p()
        result = int(
            self._CreateAppContainerProfile(
                profile_name,
                profile_name,
                "Loushang attempt-scoped LPAC Worker",
                None,
                0,
                ctypes.byref(sid),
            )
        )
        if result != 0:
            if _hresult_code(result) == _ERROR_ALREADY_EXISTS:
                raise _Win32ProfileAlreadyExists(profile_name)
            self._raise_hresult(result, "CreateAppContainerProfile")
        sid_value = int(sid.value or 0)
        if sid_value <= 0:
            raise OSError("CreateAppContainerProfile returned no Package SID")
        try:
            sid_text = self.sid_text(sid_value)
            profile = _Win32LpacProfile(
                sid=sid_value,
                sid_text=sid_text,
                private_root=self.lpac_private_root(sid_text),
            )
            on_acquired(profile)
            return profile
        except BaseException:
            self.free_sid(sid_value)
            raise

    def derive_lpac_identity(self, profile_name: str) -> _Win32LpacIdentity:
        """Derive the deterministic Package SID without querying profile state."""

        sid = ctypes.c_void_p()
        result = int(
            self._DeriveAppContainerSidFromAppContainerName(
                profile_name,
                ctypes.byref(sid),
            )
        )
        if result != 0:
            self._raise_hresult(
                result,
                "DeriveAppContainerSidFromAppContainerName",
            )
        sid_value = int(sid.value or 0)
        if sid_value <= 0:
            raise OSError("AppContainer SID derivation returned no Package SID")
        try:
            return _Win32LpacIdentity(
                sid=sid_value,
                sid_text=self.sid_text(sid_value),
            )
        except BaseException:
            self.free_sid(sid_value)
            raise

    def derive_lpac_profile(self, profile_name: str) -> _Win32LpacProfile:
        identity = self.derive_lpac_identity(profile_name)
        try:
            return _Win32LpacProfile(
                sid=identity.sid,
                sid_text=identity.sid_text,
                private_root=self.lpac_private_root(identity.sid_text),
            )
        except BaseException:
            self.free_sid(identity.sid)
            raise

    def delete_lpac_profile(self, profile_name: str) -> None:
        result = int(self._DeleteAppContainerProfile(profile_name))
        if result == 0:
            return
        code = _hresult_code(result)
        if code in {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND}:
            raise _Win32ProfileNotFound(profile_name)
        self._raise_hresult(result, "DeleteAppContainerProfile")

    def free_sid(self, sid: int) -> None:
        if sid <= 0:
            return
        failure = self._FreeSid(sid)
        if failure:
            self._raise_last_error("FreeSid")

    def sid_text(self, sid: int) -> str:
        pointer = wintypes.LPWSTR()
        if not self._ConvertSidToStringSidW(sid, ctypes.byref(pointer)):
            self._raise_last_error("ConvertSidToStringSidW")
        try:
            value = pointer.value
            if not value:
                raise OSError("SID conversion returned an empty value")
            return str(value)
        finally:
            self._LocalFree(ctypes.cast(pointer, ctypes.c_void_p))

    def lpac_private_root(self, sid_text: str) -> str:
        pointer = wintypes.LPWSTR()
        result = int(self._GetAppContainerFolderPath(sid_text, ctypes.byref(pointer)))
        if result != 0:
            if _hresult_code(result) in {
                _ERROR_FILE_NOT_FOUND,
                _ERROR_PATH_NOT_FOUND,
            }:
                raise _Win32ProfileNotFound(sid_text)
            self._raise_hresult(result, "GetAppContainerFolderPath")
        try:
            value = pointer.value
            if not value:
                raise OSError("AppContainer folder lookup returned no path")
            return ntpath.normpath(str(value))
        finally:
            self._CoTaskMemFree(ctypes.cast(pointer, ctypes.c_void_p))

    def grant_lpac_path(
        self,
        path: str,
        sid: int,
        *,
        permissions: int,
        inherit: bool,
    ) -> None:
        self._mutate_lpac_path_acl(
            path,
            sid,
            access_mode=_GRANT_ACCESS,
            permissions=permissions,
            inherit=inherit,
        )

    def revoke_lpac_path(self, path: str, sid: int) -> None:
        self._mutate_lpac_path_acl(
            path,
            sid,
            access_mode=_REVOKE_ACCESS,
            permissions=0,
            inherit=False,
        )

    def lpac_path_access(
        self,
        path: str,
        sid: int,
    ) -> tuple[tuple[int, int, int], ...]:
        security_descriptor = ctypes.c_void_p()
        acl = ctypes.c_void_p()
        result = int(
            self._GetNamedSecurityInfoW(
                path,
                _SE_FILE_OBJECT,
                _DACL_SECURITY_INFORMATION,
                None,
                None,
                ctypes.byref(acl),
                None,
                ctypes.byref(security_descriptor),
            )
        )
        if result != 0:
            self._raise_error(result, "GetNamedSecurityInfoW")
        try:
            if not acl.value:
                raise OSError("Windows runtime path has a null DACL")
            information = _ACL_SIZE_INFORMATION()
            if not self._GetAclInformation(
                acl,
                ctypes.byref(information),
                ctypes.sizeof(information),
                _ACL_SIZE_INFORMATION_CLASS,
            ):
                self._raise_last_error("GetAclInformation")
            matches: list[tuple[int, int, int]] = []
            for index in range(int(information.AceCount)):
                raw_ace = ctypes.c_void_p()
                if not self._GetAce(acl, index, ctypes.byref(raw_ace)):
                    self._raise_last_error("GetAce")
                if not raw_ace.value:
                    raise OSError("GetAce returned an empty ACE")
                header = ctypes.cast(
                    raw_ace,
                    ctypes.POINTER(_ACE_HEADER),
                ).contents
                ace_type = int(header.AceType)
                ace_sid = _access_ace_sid_address(
                    int(raw_ace.value),
                    ace_type,
                    int(header.AceSize),
                )
                if ace_sid is None:
                    continue
                ace = ctypes.cast(
                    raw_ace,
                    ctypes.POINTER(_ACCESS_ALLOWED_ACE),
                ).contents
                if self._EqualSid(ace_sid, sid):
                    matches.append((ace_type, int(ace.Mask), int(ace.Header.AceFlags)))
            return tuple(matches)
        finally:
            if security_descriptor.value:
                self._LocalFree(security_descriptor)

    def file_stream_names(self, path: str) -> tuple[str, ...]:
        data = _WIN32_FIND_STREAM_DATA()
        raw = self._FindFirstStreamW(
            path,
            _FIND_STREAM_INFO_STANDARD,
            ctypes.byref(data),
            0,
        )
        handle = _handle_value(raw)
        if handle == _INVALID_HANDLE_VALUE:
            error = _last_error()
            if error in {_ERROR_HANDLE_EOF, _ERROR_FILE_NOT_FOUND}:
                return ()
            self._raise_error(error, "FindFirstStreamW")
        names = [str(data.cStreamName)]
        try:
            while self._FindNextStreamW(handle, ctypes.byref(data)):
                names.append(str(data.cStreamName))
            error = _last_error()
            if error != _ERROR_HANDLE_EOF:
                self._raise_error(error, "FindNextStreamW")
        finally:
            self._FindClose(handle)
        return tuple(names)

    def ensure_lpac_private_scratch(self, private_root: str) -> None:
        root = Path(private_root)
        if not root.is_dir():
            raise OSError("AppContainer private root is unavailable")
        temp = root / "Temp"
        temp.mkdir(mode=0o700, exist_ok=True)
        identity_handles: list[int] = []
        try:
            self.open_locked_directory(
                str(root),
                on_acquired=identity_handles.append,
            )
            self.open_locked_directory(
                str(temp),
                on_acquired=identity_handles.append,
            )
        finally:
            for handle in reversed(identity_handles):
                self.close_handle(handle)

    def purge_lpac_private_state(self, private_root: str) -> None:
        """Remove Hosting's bounded scratch contents without following links.

        The surrounding AppContainer directory tree is platform-owned and is
        removed, together with private registry state, by
        ``DeleteAppContainerProfile``.
        """

        root = Path(private_root) / "Temp"
        try:
            root_stat = root.stat(follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(root_stat.st_mode) or _stat_is_reparse(root_stat):
            raise OSError("AppContainer private root is not a plain directory")
        entries: list[tuple[Path, os.stat_result, int]] = []
        stack: list[tuple[Path, int]] = [(root, 0)]
        total_bytes = 0
        while stack:
            directory, depth = stack.pop()
            if depth > _MAX_LPAC_PRIVATE_DEPTH:
                raise OSError("AppContainer private state exceeds depth bound")
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    path = Path(entry.path)
                    # CPython 3.11's Windows DirEntry cache reports st_nlink
                    # as zero. A real os.stat call is required before using
                    # the link count as a containment decision.
                    information = os.stat(path, follow_symlinks=False)
                    if entry.is_symlink() or _stat_is_reparse(information):
                        raise OSError("AppContainer private state contains a link")
                    entries.append((path, information, depth + 1))
                    if len(entries) > _MAX_LPAC_PRIVATE_ENTRIES:
                        raise OSError("AppContainer private state exceeds entry bound")
                    if stat.S_ISDIR(information.st_mode):
                        stack.append((path, depth + 1))
                    elif stat.S_ISREG(information.st_mode):
                        if int(information.st_nlink) != 1:
                            raise OSError(
                                "AppContainer private state contains a hard link"
                            )
                        streams = self.file_stream_names(str(path))
                        if streams not in {(), ("::$DATA",)}:
                            raise OSError(
                                "AppContainer private state contains an alternate stream"
                            )
                        total_bytes += int(information.st_size)
                        if total_bytes > _MAX_LPAC_PRIVATE_BYTES:
                            raise OSError(
                                "AppContainer private state exceeds byte bound"
                            )
                    else:
                        raise OSError(
                            "AppContainer private state contains a special file"
                        )
        for path, information, depth in sorted(
            entries,
            key=lambda item: item[2],
            reverse=True,
        ):
            if stat.S_ISDIR(information.st_mode):
                path.rmdir()
            else:
                path.unlink()

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

    def spawn_lpac(
        self,
        request: ProcessLaunchRequest,
        endpoint_handles: tuple[int, int],
        *,
        executable_handle: int,
        cwd_handle: int,
        package_sid: int,
        expected_sid_text: str,
        job: int,
        stderr_handle: int,
        begin_effect: Callable[[], None],
    ) -> _Win32SpawnHandles:
        child_stdin, child_stdout = endpoint_handles
        native_handles = (child_stdin, child_stdout, job, stderr_handle)
        if any(type(handle) is not int or handle <= 0 for handle in native_handles):
            raise _Win32CreateNotStarted(
                HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "Windows LPAC launch received invalid native handles",
                )
            )
        if package_sid <= 0 or not expected_sid_text.startswith("S-1-15-2-"):
            raise _Win32CreateNotStarted(
                HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows LPAC launch received an invalid Package SID",
                )
            )
        if len(set(native_handles)) != len(native_handles):
            raise _Win32CreateNotStarted(
                HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "Windows LPAC endpoint and preparation handles collide",
                )
            )
        attributes: _Win32AttributeList | None = None
        try:
            attributes = self._lpac_attribute_list(
                package_sid,
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
            information = _PROCESS_INFORMATION()
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline(request.argv)
            )
            environment = ctypes.create_unicode_buffer(
                _environment_block(request.effective_environment)
            )
            executable = self.locked_path_identity(executable_handle)
            current_cwd = self.locked_path_identity(cwd_handle)
            if executable.is_directory or not current_cwd.is_directory:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_STALE,
                    "Windows retained LPAC launch path kind changed",
                )
        except BaseException as cause:
            if attributes is not None:
                self._DeleteProcThreadAttributeList(attributes.pointer)
            raise _Win32CreateNotStarted(cause) from cause

        try:
            begin_effect()
            created = self._CreateProcessW(
                executable.final_path,
                command_line,
                None,
                None,
                True,
                _EXTENDED_STARTUPINFO_PRESENT
                | _CREATE_UNICODE_ENVIRONMENT
                | _CREATE_NO_WINDOW
                | _CREATE_SUSPENDED,
                ctypes.cast(environment, ctypes.c_void_p),
                current_cwd.final_path,
                ctypes.byref(startup.StartupInfo),
                ctypes.byref(information),
            )
            if not created:
                try:
                    self._raise_last_error("CreateProcessW(LPAC)")
                except OSError as cause:
                    raise _Win32CreateSettledWithoutProcess(cause) from cause
                raise AssertionError("CreateProcessW(LPAC) error was not raised")
            process = _handle_value(information.hProcess)
            thread = _handle_value(information.hThread)
            if process <= 0 or thread <= 0:
                raise RuntimeError("CreateProcessW(LPAC) returned invalid handles")
            try:
                identity = self.lpac_process_identity(process, job=job)
                if (
                    not identity.is_app_container
                    or not identity.is_lpac
                    or identity.capability_count != 0
                    or identity.sid_text != expected_sid_text
                ):
                    raise HostingError(
                        HostingFailureCategory.PREPARATION_FAILED,
                        "Windows child token did not match the admitted LPAC profile",
                    )
                previous_suspend_count = int(self._ResumeThread(thread))
                if previous_suspend_count == 0xFFFFFFFF:
                    self._raise_last_error("ResumeThread(LPAC)")
                if previous_suspend_count != 1:
                    raise OSError(
                        "Windows LPAC initial thread had an unexpected suspend count"
                    )
            except BaseException as cause:
                self._settle_rejected_lpac_process(
                    process=process,
                    thread=thread,
                    job=job,
                )
                if isinstance(cause, OSError):
                    settled_cause = cause
                else:
                    settled_cause = OSError(
                        "Windows LPAC pre-resume verification failed"
                    )
                raise _Win32CreateSettledWithoutProcess(settled_cause) from cause
            return _Win32SpawnHandles(
                process=process,
                job=job,
                stdin_write=None,
                stdout_read=None,
                stderr_read=None,
                cleanup_handles=(thread, stderr_handle),
            )
        finally:
            self._DeleteProcThreadAttributeList(attributes.pointer)

    def lpac_process_identity(
        self,
        process: int,
        *,
        job: int,
    ) -> _Win32LpacTokenIdentity:
        in_job = wintypes.BOOL()
        if not self._IsProcessInJob(process, job, ctypes.byref(in_job)):
            self._raise_last_error("IsProcessInJob(LPAC)")
        if not in_job.value:
            raise OSError("Windows LPAC process is not in its admitted Job")
        token = wintypes.HANDLE()
        if not self._OpenProcessToken(
            process,
            _TOKEN_QUERY | _TOKEN_DUPLICATE,
            ctypes.byref(token),
        ):
            self._raise_last_error("OpenProcessToken(LPAC)")
        token_value = _handle_value(token)
        try:
            is_app_container = bool(
                self._token_dword(token_value, _TOKEN_IS_APP_CONTAINER)
            )
            is_lpac = self._token_is_lpac(token_value)
            capabilities = self._token_buffer(token_value, _TOKEN_CAPABILITIES)
            capability_count = int(
                ctypes.cast(capabilities, ctypes.POINTER(wintypes.DWORD)).contents.value
            )
            app_container = self._token_buffer(
                token_value,
                _TOKEN_APP_CONTAINER_SID,
            )
            sid = int(
                ctypes.cast(
                    app_container,
                    ctypes.POINTER(ctypes.c_void_p),
                ).contents.value
                or 0
            )
            if sid <= 0:
                raise OSError("Windows LPAC token has no Package SID")
            return _Win32LpacTokenIdentity(
                sid_text=self.sid_text(sid),
                capability_count=capability_count,
                is_app_container=is_app_container,
                is_lpac=is_lpac,
            )
        finally:
            self.close_handle(token_value)

    def _token_is_lpac(self, token: int) -> bool:
        """Prove that the AppContainer token cannot use the ambient AAP SID.

        Server 2022 can reject TokenIsLessPrivilegedAppContainer even though
        it accepts the process-creation opt-out policy.  MembershipEx performs
        the underlying access semantics directly: a regular AppContainer can
        match ALL APPLICATION PACKAGES, while an LPAC must not.
        """

        impersonation = wintypes.HANDLE()
        if not self._DuplicateToken(
            token,
            _SECURITY_IMPERSONATION,
            ctypes.byref(impersonation),
        ):
            self._raise_last_error("DuplicateToken(LPAC verification)")
        impersonation_value = _handle_value(impersonation)
        if impersonation_value <= 0:
            raise OSError("DuplicateToken(LPAC verification) returned no token")
        try:
            sid_storage = (ctypes.c_ubyte * _SECURITY_MAX_SID_SIZE)()
            sid_size = wintypes.DWORD(ctypes.sizeof(sid_storage))
            if not self._CreateWellKnownSid(
                _WIN_BUILTIN_ANY_PACKAGE_SID,
                None,
                ctypes.byref(sid_storage),
                ctypes.byref(sid_size),
            ):
                self._raise_last_error("CreateWellKnownSid(AAP)")
            is_member = wintypes.BOOL()
            if not self._CheckTokenMembershipEx(
                impersonation_value,
                ctypes.byref(sid_storage),
                _CTMF_INCLUDE_APPCONTAINER,
                ctypes.byref(is_member),
            ):
                self._raise_last_error("CheckTokenMembershipEx(AAP)")
            return not bool(is_member.value)
        finally:
            self.close_handle(impersonation_value)

    def _settle_rejected_lpac_process(
        self,
        *,
        process: int,
        thread: int,
        job: int,
    ) -> None:
        failures: list[BaseException] = []
        terminated = False
        try:
            self.terminate_job(job, 0xE0000006)
        except BaseException as error:
            failures.append(error)
        else:
            terminated = True
        if terminated:
            try:
                result = int(
                    self._WaitForSingleObject(
                        process,
                        _LPAC_REJECT_SETTLEMENT_MILLISECONDS,
                    )
                )
                if result == _WAIT_FAILED:
                    self._raise_last_error("WaitForSingleObject(rejected LPAC)")
                if result == _WAIT_TIMEOUT:
                    raise TimeoutError("Windows rejected LPAC process did not drain")
                if result != _WAIT_OBJECT_0:
                    raise OSError("Windows rejected LPAC process wait was invalid")
            except BaseException as error:
                failures.append(error)
        for handle in (thread, process):
            try:
                self.close_handle(handle)
            except BaseException as error:
                failures.append(error)
        if failures:
            raise BaseExceptionGroup(
                "Windows rejected LPAC process cleanup failed",
                failures,
            )

    def _mutate_lpac_path_acl(
        self,
        path: str,
        sid: int,
        *,
        access_mode: int,
        permissions: int,
        inherit: bool,
    ) -> None:
        security_descriptor = ctypes.c_void_p()
        old_acl = ctypes.c_void_p()
        result = int(
            self._GetNamedSecurityInfoW(
                path,
                _SE_FILE_OBJECT,
                _DACL_SECURITY_INFORMATION,
                None,
                None,
                ctypes.byref(old_acl),
                None,
                ctypes.byref(security_descriptor),
            )
        )
        if result != 0:
            self._raise_error(result, "GetNamedSecurityInfoW")
        new_acl = ctypes.c_void_p()
        try:
            entry = _EXPLICIT_ACCESS_W()
            entry.grfAccessPermissions = permissions
            entry.grfAccessMode = access_mode
            entry.grfInheritance = _SUB_CONTAINERS_AND_OBJECTS_INHERIT if inherit else 0
            entry.Trustee.TrusteeForm = _TRUSTEE_IS_SID
            entry.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
            entry.Trustee.ptstrName = ctypes.cast(sid, wintypes.LPWSTR)
            result = int(
                self._SetEntriesInAclW(
                    1,
                    ctypes.byref(entry),
                    old_acl,
                    ctypes.byref(new_acl),
                )
            )
            if result != 0:
                self._raise_error(result, "SetEntriesInAclW")
            result = int(
                self._SetNamedSecurityInfoW(
                    path,
                    _SE_FILE_OBJECT,
                    _DACL_SECURITY_INFORMATION,
                    None,
                    None,
                    new_acl,
                    None,
                )
            )
            if result != 0:
                self._raise_error(result, "SetNamedSecurityInfoW")
        finally:
            if new_acl.value:
                self._LocalFree(new_acl)
            if security_descriptor.value:
                self._LocalFree(security_descriptor)

    def _token_dword(self, token: int, information_class: int) -> int:
        value = wintypes.DWORD()
        returned = wintypes.DWORD()
        if not self._GetTokenInformation(
            token,
            information_class,
            ctypes.byref(value),
            ctypes.sizeof(value),
            ctypes.byref(returned),
        ):
            self._raise_last_error("GetTokenInformation(DWORD)")
        return int(value.value)

    def _token_buffer(
        self,
        token: int,
        information_class: int,
    ) -> ctypes.Array[ctypes.c_char]:
        required = wintypes.DWORD()
        self._GetTokenInformation(
            token,
            information_class,
            None,
            0,
            ctypes.byref(required),
        )
        if _last_error() != _ERROR_INSUFFICIENT_BUFFER or required.value == 0:
            self._raise_last_error("GetTokenInformation(size)")
        buffer = ctypes.create_string_buffer(required.value)
        if not self._GetTokenInformation(
            token,
            information_class,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            self._raise_last_error("GetTokenInformation(value)")
        return buffer

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

    def job_active_process_count(self, handle: int) -> int:
        accounting = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        if not self._QueryInformationJobObject(
            handle,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            self._raise_last_error("QueryInformationJobObject")
        return int(accounting.ActiveProcesses)

    def job_is_empty(self, handle: int) -> bool:
        return self.job_active_process_count(handle) == 0

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

    def _stdin_handles(self, request: ProcessLaunchRequest) -> tuple[int, int | None]:
        if request.streams.stdin is ProcessStdinMode.PIPE:
            child, parent = self._pipe(child_reads=True)
            return child, parent
        return self._null_handle(read=True), None

    def _stdout_handles(self, request: ProcessLaunchRequest) -> tuple[int, int | None]:
        if request.streams.stdout is ProcessStdoutMode.PIPE:
            parent, child = self._pipe(child_reads=False)
            return child, parent
        return self._null_handle(read=False), None

    def _stderr_handles(self, request: ProcessLaunchRequest) -> tuple[int, int | None]:
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
        if not self._SetHandleInformation(parent, _HANDLE_FLAG_INHERIT, 0):
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
        handle_list = (wintypes.HANDLE * len(inherited_handles))(*inherited_handles)
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

    def _lpac_attribute_list(
        self,
        package_sid: int,
        job: int,
        inherited_handles: tuple[int, int, int],
    ) -> _Win32AttributeList:
        size = ctypes.c_size_t()
        self._InitializeProcThreadAttributeList(None, 4, 0, ctypes.byref(size))
        if size.value == 0:
            self._raise_last_error("InitializeProcThreadAttributeList(LPAC size)")
        storage = ctypes.create_string_buffer(size.value)
        pointer = ctypes.cast(storage, ctypes.c_void_p)
        if not self._InitializeProcThreadAttributeList(
            pointer,
            4,
            0,
            ctypes.byref(size),
        ):
            self._raise_last_error("InitializeProcThreadAttributeList(LPAC)")

        security = _SECURITY_CAPABILITIES()
        security.AppContainerSid = package_sid
        security.Capabilities = None
        security.CapabilityCount = 0
        security.Reserved = 0
        policy = wintypes.DWORD(_PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT)
        job_list = (wintypes.HANDLE * 1)(job)
        handle_list = (wintypes.HANDLE * len(inherited_handles))(*inherited_handles)
        attributes = (
            (
                _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(security),
                ctypes.sizeof(security),
                "SECURITY_CAPABILITIES",
            ),
            (
                _PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY,
                ctypes.byref(policy),
                ctypes.sizeof(policy),
                "ALL_APPLICATION_PACKAGES_POLICY",
            ),
            (
                _PROC_THREAD_ATTRIBUTE_JOB_LIST,
                ctypes.byref(job_list),
                ctypes.sizeof(job_list),
                "JOB_LIST",
            ),
            (
                _PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes.byref(handle_list),
                ctypes.sizeof(handle_list),
                "HANDLE_LIST",
            ),
        )
        for attribute, value, value_size, label in attributes:
            if not self._UpdateProcThreadAttribute(
                pointer,
                0,
                attribute,
                value,
                value_size,
                None,
                None,
            ):
                self._DeleteProcThreadAttributeList(pointer)
                self._raise_last_error(f"UpdateProcThreadAttribute({label})")
        return _Win32AttributeList(
            storage=storage,
            pointer=pointer,
            jobs=job_list,
            handles=handle_list,
            security_capabilities=security,
            all_application_packages_policy=policy,
        )

    def _bind_functions(self) -> None:
        kernel32: Any = self._kernel32
        advapi32: Any = self._advapi32
        self._GetCurrentProcess = _bind(
            kernel32.GetCurrentProcess,
            [],
            wintypes.HANDLE,
        )
        self._GetWindowsDirectoryW = _bind(
            kernel32.GetWindowsDirectoryW,
            [wintypes.LPWSTR, wintypes.UINT],
            wintypes.UINT,
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
        self._FindFirstStreamW = _bind(
            kernel32.FindFirstStreamW,
            [
                wintypes.LPCWSTR,
                ctypes.c_int,
                ctypes.POINTER(_WIN32_FIND_STREAM_DATA),
                wintypes.DWORD,
            ],
            wintypes.HANDLE,
        )
        self._FindNextStreamW = _bind(
            kernel32.FindNextStreamW,
            [wintypes.HANDLE, ctypes.POINTER(_WIN32_FIND_STREAM_DATA)],
            wintypes.BOOL,
        )
        self._FindClose = _bind(
            kernel32.FindClose,
            [wintypes.HANDLE],
            wintypes.BOOL,
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
        self._ResumeThread = _bind(
            kernel32.ResumeThread,
            [wintypes.HANDLE],
            wintypes.DWORD,
        )
        self._IsProcessInJob = _bind(
            kernel32.IsProcessInJob,
            [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)],
            wintypes.BOOL,
        )
        self._LocalFree = _bind(
            kernel32.LocalFree,
            [ctypes.c_void_p],
            ctypes.c_void_p,
        )
        self._OpenProcessToken = _bind(
            advapi32.OpenProcessToken,
            [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)],
            wintypes.BOOL,
        )
        self._DuplicateToken = _bind(
            advapi32.DuplicateToken,
            [wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)],
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
        self._CheckTokenMembershipEx = _bind(
            kernel32.CheckTokenMembershipEx,
            [
                wintypes.HANDLE,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.BOOL),
            ],
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
        self._ConvertSidToStringSidW = _bind(
            advapi32.ConvertSidToStringSidW,
            [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)],
            wintypes.BOOL,
        )
        self._FreeSid = _bind(
            advapi32.FreeSid,
            [ctypes.c_void_p],
            ctypes.c_void_p,
        )
        self._EqualSid = _bind(
            advapi32.EqualSid,
            [ctypes.c_void_p, ctypes.c_void_p],
            wintypes.BOOL,
        )
        self._GetNamedSecurityInfoW = _bind(
            advapi32.GetNamedSecurityInfoW,
            [
                wintypes.LPWSTR,
                ctypes.c_int,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
            ],
            wintypes.DWORD,
        )
        self._SetEntriesInAclW = _bind(
            advapi32.SetEntriesInAclW,
            [
                wintypes.ULONG,
                ctypes.POINTER(_EXPLICIT_ACCESS_W),
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ],
            wintypes.DWORD,
        )
        self._SetNamedSecurityInfoW = _bind(
            advapi32.SetNamedSecurityInfoW,
            [
                wintypes.LPWSTR,
                ctypes.c_int,
                wintypes.DWORD,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ],
            wintypes.DWORD,
        )
        self._GetAclInformation = _bind(
            advapi32.GetAclInformation,
            [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int],
            wintypes.BOOL,
        )
        self._GetAce = _bind(
            advapi32.GetAce,
            [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)],
            wintypes.BOOL,
        )
        userenv: Any = self._userenv
        self._CreateAppContainerProfile = _bind(
            userenv.CreateAppContainerProfile,
            [
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                wintypes.LPCWSTR,
                ctypes.POINTER(_SID_AND_ATTRIBUTES),
                wintypes.DWORD,
                ctypes.POINTER(ctypes.c_void_p),
            ],
            ctypes.c_long,
        )
        self._DeleteAppContainerProfile = _bind(
            userenv.DeleteAppContainerProfile,
            [wintypes.LPCWSTR],
            ctypes.c_long,
        )
        self._DeriveAppContainerSidFromAppContainerName = _bind(
            userenv.DeriveAppContainerSidFromAppContainerName,
            [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)],
            ctypes.c_long,
        )
        self._GetAppContainerFolderPath = _bind(
            userenv.GetAppContainerFolderPath,
            [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPWSTR)],
            ctypes.c_long,
        )
        ole32: Any = self._ole32
        self._CoTaskMemFree = _bind(
            ole32.CoTaskMemFree,
            [ctypes.c_void_p],
            None,
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

    @staticmethod
    def _raise_hresult(result: int, operation: str) -> None:
        code = _hresult_code(result)
        raise OSError(
            code, f"{operation} failed with HRESULT {result & 0xFFFFFFFF:#010x}"
        )


def _bind(function: Any, argument_types: list[object], result_type: object) -> Any:
    function.argtypes = argument_types
    function.restype = result_type
    return function


def _last_error() -> int:
    getter = getattr(ctypes, "get_last_error", None)
    if getter is None:
        return 0
    return int(getter())


def _hresult_code(result: int) -> int:
    return int(result) & 0xFFFF


def _access_ace_sid_address(
    raw_ace: int,
    ace_type: int,
    ace_size: int,
) -> int | None:
    """Locate trustees in supported access ACEs and reject ambiguous shapes."""

    basic = {
        _ACCESS_ALLOWED_ACE_TYPE,
        _ACCESS_DENIED_ACE_TYPE,
        _ACCESS_ALLOWED_CALLBACK_ACE_TYPE,
        _ACCESS_DENIED_CALLBACK_ACE_TYPE,
    }
    object_types = {
        _ACCESS_ALLOWED_OBJECT_ACE_TYPE,
        _ACCESS_DENIED_OBJECT_ACE_TYPE,
        _ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE,
        _ACCESS_DENIED_CALLBACK_OBJECT_ACE_TYPE,
    }
    if ace_type in basic:
        sid_offset = _ACCESS_ALLOWED_ACE.SidStart.offset
    elif ace_type == _ACCESS_ALLOWED_COMPOUND_ACE_TYPE:
        # This obsolete two-principal shape cannot be compared as one exact
        # Package-SID trustee, so a dedicated runtime carrying one is unsafe.
        raise OSError("Windows DACL contains an unsupported compound ACE")
    elif ace_type in object_types:
        if raw_ace <= 0 or ace_size < 12:
            raise OSError("Windows DACL contains a malformed object ACE")
        object_flags = ctypes.c_uint32.from_address(raw_ace + 8).value
        if object_flags & ~(
            _ACE_OBJECT_TYPE_PRESENT | _ACE_INHERITED_OBJECT_TYPE_PRESENT
        ):
            raise OSError("Windows DACL object ACE has unknown flags")
        sid_offset = 12
        if object_flags & _ACE_OBJECT_TYPE_PRESENT:
            sid_offset += 16
        if object_flags & _ACE_INHERITED_OBJECT_TYPE_PRESENT:
            sid_offset += 16
    else:
        return None
    # A SID is an 8-byte header followed by N 32-bit sub-authorities. Validate
    # its complete extent before EqualSid is allowed to inspect OS-owned ACL
    # memory; callback application data, when present, follows that extent.
    if raw_ace <= 0 or sid_offset + 8 > ace_size:
        raise OSError("Windows DACL contains a malformed access ACE")
    sub_authority_count = ctypes.c_ubyte.from_address(raw_ace + sid_offset + 1).value
    sid_size = 8 + 4 * int(sub_authority_count)
    if sid_offset + sid_size > ace_size:
        raise OSError("Windows DACL contains a truncated trustee SID")
    return raw_ace + sid_offset


def _stat_is_reparse(value: os.stat_result) -> bool:
    return bool(
        int(getattr(value, "st_file_attributes", 0))
        & _FILE_ATTRIBUTE_REPARSE_POINT_STAT
    )


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
