"""Native Windows private file creation and handle admission for G16 records.

This adapter owns its Win32 bindings; it does not import Hosting internals.
Import is safe on other platforms, but native construction is Windows-only.
"""

from __future__ import annotations

import ctypes as C
import errno
import os
from ctypes import wintypes as W
from importlib import import_module
from pathlib import Path
from typing import Any

from ._local_record_files import FileIdentity, FileMode, _RecordFiles
from ._local_record_values import LocalRecordError, LocalRecordErrorCodeV1

_INVALID_HANDLE = C.c_void_p(-1).value
_FULL_ACCESS = 0x001F01FF
_SYSTEM = "S-1-5-18"


class _Attributes(C.Structure):
    _fields_ = [("length", W.DWORD), ("descriptor", C.c_void_p), ("inherit", W.BOOL)]


class _TokenUser(C.Structure):
    _fields_ = [("sid", C.c_void_p), ("attributes", W.DWORD)]


class _FileInfo(C.Structure):
    _fields_ = [
        ("attributes", W.DWORD), ("created", W.FILETIME), ("accessed", W.FILETIME),
        ("written", W.FILETIME), ("volume", W.DWORD), ("size_high", W.DWORD),
        ("size_low", W.DWORD), ("links", W.DWORD), ("index_high", W.DWORD),
        ("index_low", W.DWORD),
    ]


class _FileId(C.Structure):
    _fields_ = [("volume", C.c_ulonglong), ("identifier", C.c_ubyte * 16)]


class _AclInfo(C.Structure):
    _fields_ = [("count", W.DWORD), ("used", W.DWORD), ("free", W.DWORD)]


class _Ace(C.Structure):
    _fields_ = [("kind", C.c_ubyte), ("flags", C.c_ubyte),
                ("size", W.WORD), ("mask", W.DWORD)]


def _bind(library: Any, name: str, arguments: list[Any], result: Any) -> None:
    function = getattr(library, name)
    function.argtypes = arguments
    function.restype = result


def _last_error() -> int:
    return int(getattr(C, "get_last_error")())


class _Win32:
    def __init__(self) -> None:
        if os.name != "nt":
            raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
        loader = getattr(C, "WinDLL")
        self.kernel: Any = loader("kernel32", use_last_error=True)
        self.security: Any = loader("advapi32", use_last_error=True)
        self.crt = import_module("msvcrt")
        self.descriptor = C.c_void_p()
        self.user_sid = ""
        self._handles: set[int] = set()
        ptr = C.c_void_p
        pptr = C.POINTER(ptr)
        _bind(self.kernel, "CreateFileW", [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(_Attributes), W.DWORD, W.DWORD, W.HANDLE], W.HANDLE)
        _bind(self.kernel, "CreateDirectoryW", [W.LPCWSTR, C.POINTER(_Attributes)], W.BOOL)
        _bind(self.kernel, "CloseHandle", [W.HANDLE], W.BOOL)
        _bind(self.kernel, "GetCurrentProcess", [], W.HANDLE)
        _bind(self.kernel, "LocalFree", [ptr], ptr)
        _bind(self.kernel, "GetFileInformationByHandle", [W.HANDLE, C.POINTER(_FileInfo)], W.BOOL)
        _bind(self.kernel, "GetFileInformationByHandleEx", [W.HANDLE, C.c_int, ptr, W.DWORD], W.BOOL)
        _bind(self.kernel, "SetFileInformationByHandle", [W.HANDLE, C.c_int, ptr, W.DWORD], W.BOOL)
        _bind(self.security, "OpenProcessToken", [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)], W.BOOL)
        _bind(self.security, "GetTokenInformation", [W.HANDLE, C.c_int, ptr, W.DWORD, C.POINTER(W.DWORD)], W.BOOL)
        _bind(self.security, "ConvertSidToStringSidW", [ptr, C.POINTER(W.LPWSTR)], W.BOOL)
        _bind(self.security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", [W.LPCWSTR, W.DWORD, pptr, C.POINTER(W.DWORD)], W.BOOL)
        _bind(self.security, "GetSecurityInfo", [W.HANDLE, C.c_int, W.DWORD, pptr, pptr, pptr, pptr, pptr], W.DWORD)
        _bind(self.security, "GetSecurityDescriptorControl", [ptr, C.POINTER(W.WORD), C.POINTER(W.DWORD)], W.BOOL)
        _bind(self.security, "GetSecurityDescriptorDacl", [ptr, C.POINTER(W.BOOL), pptr, C.POINTER(W.BOOL)], W.BOOL)
        _bind(self.security, "GetAclInformation", [ptr, ptr, W.DWORD, C.c_int], W.BOOL)
        _bind(self.security, "GetAce", [ptr, W.DWORD, pptr], W.BOOL)

    @staticmethod
    def check(result: object) -> None:
        if result:
            return
        code = _last_error()
        if code in {2, 3}:
            raise FileNotFoundError(code, "local record object is absent")
        if code in {80, 183}:
            raise FileExistsError(code, "local record object exists")
        raise OSError(code, "local record native IO failed")

    def close_handle(self, handle: int) -> None:
        self.check(self.kernel.CloseHandle(handle))
        self._handles.discard(handle)

    def transfer_handle(self, handle: int) -> None:
        self._handles.remove(handle)

    def sid_string(self, sid: C.c_void_p) -> str:
        if not sid:
            raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
        value = W.LPWSTR()
        self.check(self.security.ConvertSidToStringSidW(sid, C.byref(value)))
        try:
            if value.value is None:
                raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
            return value.value
        finally:
            self.kernel.LocalFree(C.cast(value, C.c_void_p))

    def prepare_security(self) -> None:
        if self.descriptor.value is not None:
            return
        token = W.HANDLE()
        self.check(self.security.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x8, C.byref(token)))
        assert token.value is not None
        self._handles.add(token.value)
        try:
            size = W.DWORD()
            self.security.GetTokenInformation(token, 1, None, 0, C.byref(size))
            if not 1 <= size.value <= 4096:
                raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
            buffer = C.create_string_buffer(size.value)
            self.check(self.security.GetTokenInformation(token, 1, buffer, size.value, C.byref(size)))
            user = C.cast(buffer, C.POINTER(_TokenUser)).contents
            self.user_sid = self.sid_string(C.c_void_p(user.sid))
        finally:
            self.close_handle(token.value)
        sids = sorted({self.user_sid, _SYSTEM})
        sddl = "O:" + self.user_sid + "D:P" + "".join(f"(A;;FA;;;{sid})" for sid in sids)
        self.check(self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, C.byref(self.descriptor), None
        ))

    def attributes(self) -> _Attributes:
        return _Attributes(C.sizeof(_Attributes), self.descriptor, False)

    def open(self, path: str, mode: FileMode, *, directory: bool = False) -> int:
        access = 0x00020080 if directory else 0x80020000
        if mode in {"lock", "new"}:
            access |= 0x40000000
        if mode in {"new", "delete"}:
            access |= 0x00010000
        disposition = {"read": 3, "delete": 3, "lock": 4, "new": 1}[mode]
        flags = 0x00200000 | (0x02000000 if directory else 0x80)
        attributes = self.attributes()
        handle = self.kernel.CreateFileW(path, access, 3 if directory else 7,
                                        C.byref(attributes), disposition, flags, None)
        if handle in (None, _INVALID_HANDLE):
            self.check(False)
        self._handles.add(int(handle))
        return int(handle)

    def private_identity(self, handle: int, *, directory: bool = False) -> FileIdentity:
        info = _FileInfo()
        self.check(self.kernel.GetFileInformationByHandle(handle, C.byref(info)))
        if (
            info.attributes & 0x400 or bool(info.attributes & 0x10) != directory
            or (not directory and info.links != 1)
        ):
            raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
        self._validate_security(handle)
        identity = _FileId()
        self.check(self.kernel.GetFileInformationByHandleEx(handle, 18, C.byref(identity), C.sizeof(identity)))
        return identity.volume, int.from_bytes(bytes(identity.identifier), "little")

    def _validate_security(self, handle: int) -> None:
        owner, dacl, descriptor = C.c_void_p(), C.c_void_p(), C.c_void_p()
        code = self.security.GetSecurityInfo(handle, 1, 0x5, C.byref(owner), None,
                                            C.byref(dacl), None, C.byref(descriptor))
        if code:
            raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
        try:
            control, revision = W.WORD(), W.DWORD()
            self.check(self.security.GetSecurityDescriptorControl(descriptor, C.byref(control), C.byref(revision)))
            present, defaulted = W.BOOL(), W.BOOL()
            self.check(self.security.GetSecurityDescriptorDacl(descriptor, C.byref(present), C.byref(dacl), C.byref(defaulted)))
            if (
                self.sid_string(owner) != self.user_sid or not present.value or not dacl.value
                or not control.value & 0x1000 or defaulted.value
            ):
                raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
            info = _AclInfo()
            self.check(self.security.GetAclInformation(dacl, C.byref(info), C.sizeof(info), 2))
            expected = {self.user_sid, _SYSTEM}
            if info.count != len(expected):
                raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
            admitted: set[str] = set()
            for index in range(info.count):
                pointer = C.c_void_p()
                self.check(self.security.GetAce(dacl, index, C.byref(pointer)))
                ace = C.cast(pointer, C.POINTER(_Ace)).contents
                if ace.kind != 0 or ace.flags != 0 or ace.size < 12 or ace.mask != _FULL_ACCESS:
                    raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
                assert pointer.value is not None
                admitted.add(self.sid_string(C.c_void_p(pointer.value + C.sizeof(_Ace))))
            if admitted != expected:
                raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
        finally:
            self.kernel.LocalFree(descriptor)

    def close(self) -> None:
        failed = False
        for handle in tuple(self._handles):
            try:
                self.close_handle(handle)
            except OSError:
                failed = True
        if self.descriptor.value is not None:
            if self.kernel.LocalFree(self.descriptor):
                raise LocalRecordError(LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE)
            self.descriptor = C.c_void_p()
        if failed:
            raise LocalRecordError(LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE)


class _WindowsRecordFiles(_RecordFiles):
    _api: _Win32 | None = None
    _directory: int | None = None
    _directory_identity: FileIdentity | None = None

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self._unconverted: dict[str, int] = {}

    @property
    def api(self) -> _Win32:
        assert self._api is not None
        return self._api

    def _path(self, name: str = "") -> str:
        return "\\\\?\\" + str(self.root / name)

    def prepare(self, *, create: bool) -> None:
        if self._api is None:
            self._api = _Win32()
        self.api.prepare_security()
        if self._directory is not None:
            self.check_root()
            return
        if create:
            attributes = self.api.attributes()
            if (not self.api.kernel.CreateDirectoryW(self._path(), C.byref(attributes))
                    and _last_error() != 183):
                self.api.check(False)
        self._directory = self.api.open(self._path(), "read", directory=True)
        self._directory_identity = self.api.private_identity(self._directory, directory=True)
        self.check_root()

    def check_root(self) -> None:
        if self._directory is None:
            raise LocalRecordError(LocalRecordErrorCodeV1.CLOSED)
        identity = self.api.private_identity(self._directory, directory=True)
        current = self.api.open(self._path(), "read", directory=True)
        try:
            if identity != self._directory_identity or self.api.private_identity(current, directory=True) != identity:
                raise LocalRecordError(LocalRecordErrorCodeV1.CONFLICT)
        finally:
            self.api.close_handle(current)

    def _open(self, name: str, mode: FileMode) -> int:
        handle = self.api.open(self._path(name), mode)
        if mode == "new":
            self._unconverted[name] = handle
        try:
            flags = getattr(os, "O_BINARY") | getattr(os, "O_NOINHERIT")
            flags |= os.O_RDWR if mode in {"new", "lock"} else os.O_RDONLY
            descriptor = int(self.api.crt.open_osfhandle(handle, flags))
        except BaseException:
            if mode != "new":
                self.api.close_handle(handle)
            raise
        self.api.transfer_handle(handle)
        self._unconverted.pop(name, None)
        return descriptor

    def discard_unopened(self, name: str) -> None:
        handle = self._unconverted.get(name)
        if handle is None:
            super().discard_unopened(name)
            return
        self._delete_handle(handle)
        self.api.close_handle(handle)
        self._unconverted.pop(name)

    def _delete_handle(self, handle: int) -> None:
        delete = C.c_ubyte(1)
        self.api.check(self.api.kernel.SetFileInformationByHandle(
            handle, 4, C.byref(delete), C.sizeof(delete)
        ))

    def identity(self, descriptor: int) -> FileIdentity:
        return self.api.private_identity(self.api.crt.get_osfhandle(descriptor))

    def replace(self, source: str, target: str) -> None:
        self.check_root()
        os.replace(self.root / source, self.root / target)

    def remove(self, name: str, expected: FileIdentity) -> None:
        try:
            descriptor = self.open(name, "delete")
        except FileNotFoundError:
            return
        try:
            if self.identity(descriptor) == expected:
                self._delete_handle(self.api.crt.get_osfhandle(descriptor))
        finally:
            self.close_descriptor(descriptor)

    def lock(self, descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            self.api.crt.locking(descriptor, self.api.crt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise LocalRecordError(LocalRecordErrorCodeV1.LOCKED) from None
            raise

    def unlock(self, descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        self.api.crt.locking(descriptor, self.api.crt.LK_UNLCK, 1)

    def _close_root(self) -> None:
        for name in tuple(self._unconverted):
            self.discard_unopened(name)
        if self._directory is not None:
            self.api.close_handle(self._directory)
            self._directory = None
        if self._api is not None:
            self._api.close()
