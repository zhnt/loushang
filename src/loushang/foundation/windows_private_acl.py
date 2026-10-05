"""Native owner-only Windows directory ACL creation and handle validation.

The accepted descriptor is protected and grants full access only to the
current user and LocalSystem. This module is import-safe outside Windows.
"""

from __future__ import annotations

import ctypes as C
import os
from ctypes import wintypes as W
from importlib import import_module

_FULL_ACCESS = 0x001F01FF
_SYSTEM_SID = "S-1-5-18"
_CHILD_INHERIT_FLAGS = 0x03
_INHERITED_ACE = 0x10


class _TokenUser(C.Structure):
    _fields_ = (("sid", C.c_void_p), ("attributes", W.DWORD))


class _AclInfo(C.Structure):
    _fields_ = (("count", W.DWORD), ("used", W.DWORD), ("free", W.DWORD))


class _Ace(C.Structure):
    _fields_ = (
        ("kind", C.c_ubyte),
        ("flags", C.c_ubyte),
        ("size", W.WORD),
        ("mask", W.DWORD),
    )


class WindowsPrivateDirectoryAcl:
    """Mint and verify an exact user/System protected directory DACL."""

    def __init__(self, *, inherit_children: bool = False) -> None:
        if os.name != "nt":
            raise OSError("Windows private directory ACL is unavailable")
        if type(inherit_children) is not bool:
            raise TypeError("Windows private ACL inheritance policy is invalid")
        self._inherit_children = inherit_children
        self._ace_flags = _CHILD_INHERIT_FLAGS if inherit_children else 0
        loader = getattr(C, "WinDLL")
        self._kernel = loader("kernel32", use_last_error=True)
        self._security = loader("advapi32", use_last_error=True)
        self._crt = import_module("msvcrt")
        self._bind()
        self._descriptor = C.c_void_p()
        self._user_sid = self._current_user_sid()
        admitted = sorted({self._user_sid, _SYSTEM_SID})
        sddl = (
            "O:"
            + self._user_sid
            + "D:P"
            + "".join(
                f"(A;{'OICI' if inherit_children else ''};FA;;;{sid})"
                for sid in admitted
            )
        )
        self._check(
            self._security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, C.byref(self._descriptor), None
            )
        )

    @property
    def security_descriptor(self) -> int:
        if self._descriptor.value is None:
            raise ValueError("Windows private directory ACL owner is closed")
        return self._descriptor.value

    def validate(self, descriptor: int, *, inherited_file: bool = False) -> None:
        """Reject a foreign owner, unexpected inheritance, or extra trustee."""

        if self._descriptor.value is None:
            raise ValueError("Windows private directory ACL owner is closed")
        if type(inherited_file) is not bool or (
            inherited_file and not self._inherit_children
        ):
            raise ValueError("Windows private ACL file policy is invalid")
        if type(descriptor) is not int or descriptor < 0:
            raise ValueError("Windows directory descriptor is invalid")
        native = W.HANDLE(self._crt.get_osfhandle(descriptor))
        owner = C.c_void_p()
        dacl = C.c_void_p()
        security_descriptor = C.c_void_p()
        result = self._security.GetSecurityInfo(
            native,
            1,
            0x5,
            C.byref(owner),
            None,
            C.byref(dacl),
            None,
            C.byref(security_descriptor),
        )
        if result:
            raise OSError(result, "Could not read Windows private directory ACL")
        try:
            control = W.WORD()
            revision = W.DWORD()
            self._check(
                self._security.GetSecurityDescriptorControl(
                    security_descriptor, C.byref(control), C.byref(revision)
                )
            )
            present = W.BOOL()
            defaulted = W.BOOL()
            self._check(
                self._security.GetSecurityDescriptorDacl(
                    security_descriptor,
                    C.byref(present),
                    C.byref(dacl),
                    C.byref(defaulted),
                )
            )
            if self._sid_string(owner) != self._user_sid:
                reason = "owner"
            elif not present.value:
                reason = "dacl_absent"
            elif not dacl.value:
                reason = "dacl_null"
            elif not inherited_file and not control.value & 0x1000:
                reason = "dacl_inherited"
            elif defaulted.value and not inherited_file:
                reason = "dacl_defaulted"
            else:
                reason = None
            if reason is not None:
                raise OSError(f"Windows private directory ACL is not protected: {reason}")
            info = _AclInfo()
            self._check(
                self._security.GetAclInformation(dacl, C.byref(info), C.sizeof(info), 2)
            )
            if info.count != 2:
                raise OSError("Windows private directory ACL has extra trustees")
            admitted: set[str] = set()
            for index in range(info.count):
                pointer = C.c_void_p()
                self._check(self._security.GetAce(dacl, index, C.byref(pointer)))
                if pointer.value is None:
                    raise OSError("Windows private directory ACL has an empty ACE")
                ace = C.cast(pointer, C.POINTER(_Ace)).contents
                if (
                    ace.kind != 0
                    or (
                        bool(ace.flags & ~(_CHILD_INHERIT_FLAGS | _INHERITED_ACE))
                        if inherited_file
                        else ace.flags != self._ace_flags
                    )
                    or ace.mask != _FULL_ACCESS
                    or ace.size < C.sizeof(_Ace) + 8
                ):
                    raise OSError("Windows private directory ACL has an invalid ACE")
                sid_address = pointer.value + C.sizeof(_Ace)
                sid_header = (C.c_ubyte * 2).from_address(sid_address)
                sid_size = 8 + 4 * sid_header[1]
                if (
                    sid_header[0] != 1
                    or sid_header[1] > 15
                    or ace.size != C.sizeof(_Ace) + sid_size
                ):
                    raise OSError("Windows private directory ACL has a malformed SID")
                admitted.add(self._sid_string(C.c_void_p(sid_address)))
            if admitted != {self._user_sid, _SYSTEM_SID}:
                raise OSError("Windows private directory ACL trustee changed")
        finally:
            self._kernel.LocalFree(security_descriptor)

    def close(self) -> None:
        if self._descriptor.value is not None:
            descriptor, self._descriptor = self._descriptor, C.c_void_p()
            if self._kernel.LocalFree(descriptor):
                raise OSError("Windows private ACL descriptor cleanup failed")

    def __enter__(self) -> WindowsPrivateDirectoryAcl:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _current_user_sid(self) -> str:
        token = W.HANDLE()
        self._check(
            self._security.OpenProcessToken(
                self._kernel.GetCurrentProcess(), 0x8, C.byref(token)
            )
        )
        try:
            size = W.DWORD()
            self._security.GetTokenInformation(token, 1, None, 0, C.byref(size))
            if not 1 <= size.value <= 4096:
                raise OSError("Windows current-user token is invalid")
            buffer = C.create_string_buffer(size.value)
            self._check(
                self._security.GetTokenInformation(
                    token, 1, buffer, size.value, C.byref(size)
                )
            )
            user = C.cast(buffer, C.POINTER(_TokenUser)).contents
            return self._sid_string(C.c_void_p(user.sid))
        finally:
            self._kernel.CloseHandle(token)

    def _sid_string(self, sid: C.c_void_p) -> str:
        if not sid.value:
            raise OSError("Windows security SID is absent")
        value = W.LPWSTR()
        self._check(self._security.ConvertSidToStringSidW(sid, C.byref(value)))
        try:
            if value.value is None:
                raise OSError("Windows security SID could not be decoded")
            return value.value
        finally:
            self._kernel.LocalFree(C.cast(value, C.c_void_p))

    @staticmethod
    def _check(result: object) -> None:
        if not result:
            raise getattr(C, "WinError")(getattr(C, "get_last_error")())

    def _bind(self) -> None:
        def bind(
            library: object, name: str, args: tuple[object, ...], result: object
        ) -> None:
            function = getattr(library, name)
            function.argtypes = args
            function.restype = result

        pointer = C.c_void_p
        pointer_pointer = C.POINTER(pointer)
        bind(self._kernel, "GetCurrentProcess", (), W.HANDLE)
        bind(self._kernel, "CloseHandle", (W.HANDLE,), W.BOOL)
        bind(self._kernel, "LocalFree", (pointer,), pointer)
        bind(
            self._security,
            "OpenProcessToken",
            (W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)),
            W.BOOL,
        )
        bind(
            self._security,
            "GetTokenInformation",
            (W.HANDLE, C.c_int, pointer, W.DWORD, C.POINTER(W.DWORD)),
            W.BOOL,
        )
        bind(
            self._security,
            "ConvertSidToStringSidW",
            (pointer, C.POINTER(W.LPWSTR)),
            W.BOOL,
        )
        bind(
            self._security,
            "ConvertStringSecurityDescriptorToSecurityDescriptorW",
            (W.LPCWSTR, W.DWORD, pointer_pointer, C.POINTER(W.DWORD)),
            W.BOOL,
        )
        bind(
            self._security,
            "GetSecurityInfo",
            (
                W.HANDLE,
                C.c_int,
                W.DWORD,
                pointer_pointer,
                pointer_pointer,
                pointer_pointer,
                pointer_pointer,
                pointer_pointer,
            ),
            W.DWORD,
        )
        bind(
            self._security,
            "GetSecurityDescriptorControl",
            (pointer, C.POINTER(W.WORD), C.POINTER(W.DWORD)),
            W.BOOL,
        )
        bind(
            self._security,
            "GetSecurityDescriptorDacl",
            (pointer, C.POINTER(W.BOOL), pointer_pointer, C.POINTER(W.BOOL)),
            W.BOOL,
        )
        bind(
            self._security,
            "GetAclInformation",
            (pointer, pointer, W.DWORD, C.c_int),
            W.BOOL,
        )
        bind(
            self._security,
            "GetAce",
            (pointer, W.DWORD, pointer_pointer),
            W.BOOL,
        )


__all__ = ["WindowsPrivateDirectoryAcl"]
