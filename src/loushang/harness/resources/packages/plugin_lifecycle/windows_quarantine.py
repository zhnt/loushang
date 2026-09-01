"""Native Windows rooted-handle primitives for the PLC9B quarantine owner."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import NoReturn


def supports_windows_rooted_io() -> bool:
    """Return whether this process can use the required native Windows APIs."""

    return os.name == "nt"


def open_windows_directory(
    path: str | Path,
    *,
    dir_fd: int | None = None,
    create_new: bool = False,
    share_delete: bool = False,
    writable: bool = True,
) -> int:
    """Open or create one direct directory, anchored to ``dir_fd`` when set."""

    _require_windows()
    if dir_fd is None:
        if create_new:
            raise ValueError("A rooted parent handle is required to create a directory")
        return _open_directory_path(
            Path(path),
            share_delete=share_delete,
            writable=writable,
        )
    if create_new and not writable:
        raise ValueError("A newly created Windows directory must be writable")
    name = _component(path)
    raw_handle = _nt_open_at(
        dir_fd,
        name,
        desired_access=(
            _DIRECTORY_OWNER_ACCESS if writable else _DIRECTORY_READ_ACCESS
        ),
        share_access=(
            _FILE_SHARE_READ
            | _FILE_SHARE_WRITE
            | (_FILE_SHARE_DELETE if share_delete else 0)
        ),
        create_disposition=_FILE_CREATE if create_new else _FILE_OPEN,
        create_options=(
            _FILE_SYNCHRONOUS_IO_NONALERT
            | (_FILE_DIRECTORY_FILE if create_new else _FILE_OPEN_REPARSE_POINT)
        ),
    )
    descriptor = _descriptor_from_handle(raw_handle, write=False)
    try:
        _require_direct_directory(os.fstat(descriptor))
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def open_windows_regular_file_at(
    directory_fd: int,
    name: str,
    *,
    create_new: bool,
    write: bool,
) -> int:
    """Open one no-follow regular file relative to a pinned directory handle."""

    _require_windows()
    component = _component(name)
    desired_access = _GENERIC_READ | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
    if write:
        desired_access |= _GENERIC_WRITE
    raw_handle = _nt_open_at(
        directory_fd,
        component,
        desired_access=desired_access,
        share_access=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        create_disposition=_FILE_CREATE if create_new else _FILE_OPEN,
        create_options=(
            _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_NON_DIRECTORY_FILE
            | _FILE_OPEN_REPARSE_POINT
        ),
    )
    descriptor = _descriptor_from_handle(raw_handle, write=write)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or _is_reparse(metadata):
            raise OSError("Windows quarantine child is not a direct regular file")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def windows_stat_at(directory_fd: int, name: str) -> os.stat_result:
    """Stat one direct child without following a reparse point."""

    raw_handle = _nt_open_at(
        directory_fd,
        _component(name),
        desired_access=_FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        share_access=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        create_disposition=_FILE_OPEN,
        create_options=_FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT,
    )
    descriptor = _descriptor_from_handle(raw_handle, write=False)
    try:
        return os.fstat(descriptor)
    finally:
        os.close(descriptor)


def windows_listdir_at(directory_fd: int) -> tuple[str, ...]:
    """Enumerate names through the final path of an identity-pinned handle."""

    _require_direct_directory(os.fstat(directory_fd))
    final_path = _final_path(directory_fd)
    return tuple(_component(name) for name in os.listdir(final_path))


def windows_unlink_at(directory_fd: int, name: str) -> None:
    """Delete a file or reparse entry itself, never its target."""

    raw_handle = _open_for_delete(directory_fd, name)
    try:
        is_directory, is_reparse = _handle_entry_kind(raw_handle)
        if is_directory and not is_reparse:
            raise IsADirectoryError(name)
        _mark_handle_for_delete(raw_handle)
    finally:
        _close_handle(raw_handle)


def windows_rmdir_at(directory_fd: int, name: str) -> None:
    """Delete one empty direct directory relative to a pinned parent."""

    raw_handle = _open_for_delete(directory_fd, name)
    try:
        is_directory, is_reparse = _handle_entry_kind(raw_handle)
        if not is_directory or is_reparse:
            raise OSError("Windows quarantine entry is not a direct directory")
        _mark_handle_for_delete(raw_handle)
    finally:
        _close_handle(raw_handle)


def windows_rename_at(
    directory_fd: int,
    old_name: str,
    new_name: str,
) -> None:
    """Atomically rename one direct child beneath the same pinned directory."""

    import ctypes
    import msvcrt
    from ctypes import wintypes

    old_component = _component(old_name)
    new_component = _component(new_name)
    raw_handle = _open_for_delete(directory_fd, old_component)
    try:
        encoded_name = new_component.encode("utf-16-le")

        class _FileRenameInfo(ctypes.Structure):
            _fields_ = (
                ("replace_if_exists", wintypes.BOOL),
                ("root_directory", wintypes.HANDLE),
                ("file_name_length", wintypes.DWORD),
                ("file_name", ctypes.c_byte * len(encoded_name)),
            )

        information = _FileRenameInfo(
            replace_if_exists=False,
            root_directory=wintypes.HANDLE(
                getattr(msvcrt, "get_osfhandle")(directory_fd)
            ),
            file_name_length=len(encoded_name),
            file_name=(ctypes.c_byte * len(encoded_name)).from_buffer_copy(
                encoded_name
            ),
        )
        kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        set_information = kernel32.SetFileInformationByHandle
        set_information.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        set_information.restype = wintypes.BOOL
        if not set_information(
            wintypes.HANDLE(raw_handle),
            _FILE_RENAME_INFO,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            _raise_last_windows_error()
    finally:
        _close_handle(raw_handle)


def windows_flush_file(descriptor: int) -> None:
    """Flush one writable native file handle to its backing device."""

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    flush = kernel32.FlushFileBuffers
    flush.argtypes = (wintypes.HANDLE,)
    flush.restype = wintypes.BOOL
    handle = wintypes.HANDLE(getattr(msvcrt, "get_osfhandle")(descriptor))
    if not flush(handle):
        _raise_last_windows_error()


def _open_directory_path(
    path: Path,
    *,
    share_delete: bool,
    writable: bool,
) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        _DIRECTORY_OWNER_ACCESS if writable else _DIRECTORY_READ_ACCESS,
        (
            _FILE_SHARE_READ
            | _FILE_SHARE_WRITE
            | (_FILE_SHARE_DELETE if share_delete else 0)
        ),
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        _raise_last_windows_error()
    raw_handle = int(handle)
    descriptor: int | None = None
    try:
        descriptor = getattr(msvcrt, "open_osfhandle")(
            raw_handle,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0),
        )
        opened = os.fstat(descriptor)
        _require_direct_directory(opened)
        visible = path.lstat()
        _require_direct_directory(visible)
        if not os.path.samestat(opened, visible):
            raise OSError("Windows quarantine directory identity changed")
        return descriptor
    except BaseException:
        if descriptor is None:
            _close_handle(raw_handle)
        else:
            os.close(descriptor)
        raise


def _nt_open_at(
    directory_fd: int,
    name: str,
    *,
    desired_access: int,
    share_access: int,
    create_disposition: int,
    create_options: int,
) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _UnicodeString(ctypes.Structure):
        _fields_ = (
            ("length", wintypes.USHORT),
            ("maximum_length", wintypes.USHORT),
            ("buffer", wintypes.LPWSTR),
        )

    class _IoStatusValue(ctypes.Union):
        _fields_ = (("status", wintypes.LONG), ("pointer", wintypes.LPVOID))

    class _IoStatusBlock(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = (
            ("value", _IoStatusValue),
            ("information", ctypes.c_size_t),
        )

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = (
            ("length", wintypes.ULONG),
            ("root_directory", wintypes.HANDLE),
            ("object_name", ctypes.POINTER(_UnicodeString)),
            ("attributes", wintypes.ULONG),
            ("security_descriptor", wintypes.LPVOID),
            ("security_quality_of_service", wintypes.LPVOID),
        )

    ntdll = getattr(ctypes, "WinDLL")("ntdll")
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
    )
    nt_create_file.restype = wintypes.LONG
    name_buffer = ctypes.create_unicode_buffer(name)
    name_length = len(name.encode("utf-16-le"))
    unicode_name = _UnicodeString(
        length=name_length,
        maximum_length=name_length + ctypes.sizeof(ctypes.c_wchar),
        buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    object_attributes = _ObjectAttributes(
        length=ctypes.sizeof(_ObjectAttributes),
        root_directory=wintypes.HANDLE(getattr(msvcrt, "get_osfhandle")(directory_fd)),
        object_name=ctypes.pointer(unicode_name),
        attributes=_OBJ_CASE_INSENSITIVE,
        security_descriptor=None,
        security_quality_of_service=None,
    )
    io_status = _IoStatusBlock()
    opened_handle = wintypes.HANDLE()
    status = nt_create_file(
        ctypes.byref(opened_handle),
        desired_access,
        ctypes.byref(object_attributes),
        ctypes.byref(io_status),
        None,
        _FILE_ATTRIBUTE_NORMAL,
        share_access,
        create_disposition,
        create_options,
        None,
        0,
    )
    if status < 0:
        rtl_status_to_dos_error = ntdll.RtlNtStatusToDosError
        rtl_status_to_dos_error.argtypes = (wintypes.LONG,)
        rtl_status_to_dos_error.restype = wintypes.ULONG
        raise getattr(ctypes, "WinError")(rtl_status_to_dos_error(status))
    if opened_handle.value is None:
        raise OSError("Windows returned an invalid quarantine handle")
    return int(opened_handle.value)


def _open_for_delete(
    directory_fd: int,
    name: str,
) -> int:
    options = _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT
    return _nt_open_at(
        directory_fd,
        _component(name),
        desired_access=_DELETE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        share_access=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        create_disposition=_FILE_OPEN,
        create_options=options,
    )


def _mark_handle_for_delete(raw_handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    class _FileDispositionInfo(ctypes.Structure):
        _fields_ = (("delete_file", ctypes.c_ubyte),)

    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    set_information.restype = wintypes.BOOL
    information = _FileDispositionInfo(delete_file=True)
    if not set_information(
        wintypes.HANDLE(raw_handle),
        _FILE_DISPOSITION_INFO,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        _raise_last_windows_error()


def _handle_entry_kind(raw_handle: int) -> tuple[bool, bool]:
    import ctypes
    from ctypes import wintypes

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = (
            ("file_attributes", wintypes.DWORD),
            ("reparse_tag", wintypes.DWORD),
        )

    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL
    information = _FileAttributeTagInfo()
    if not get_information(
        wintypes.HANDLE(raw_handle),
        _FILE_ATTRIBUTE_TAG_INFO,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        _raise_last_windows_error()
    is_directory = bool(information.file_attributes & _FILE_ATTRIBUTE_DIRECTORY)
    is_reparse = bool(
        information.file_attributes & _FILE_ATTRIBUTE_REPARSE_POINT
        or information.reparse_tag
    )
    return is_directory, is_reparse


def _descriptor_from_handle(raw_handle: int, *, write: bool) -> int:
    import msvcrt

    try:
        return getattr(msvcrt, "open_osfhandle")(
            raw_handle,
            (os.O_RDWR if write else os.O_RDONLY)
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOINHERIT", 0),
        )
    except BaseException:
        _close_handle(raw_handle)
        raise


def _final_path(directory_fd: int) -> str:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    handle = wintypes.HANDLE(getattr(msvcrt, "get_osfhandle")(directory_fd))
    required = get_final_path(handle, None, 0, 0)
    if required == 0:
        _raise_last_windows_error()
    buffer = ctypes.create_unicode_buffer(required + 1)
    written = get_final_path(handle, buffer, len(buffer), 0)
    if written == 0 or written >= len(buffer):
        _raise_last_windows_error()
    return buffer.value


def _close_handle(raw_handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not close_handle(wintypes.HANDLE(raw_handle)):
        _raise_last_windows_error()


def _component(value: str | Path) -> str:
    name = os.fspath(value)
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "\0" in name
        or "/" in name
        or "\\" in name
        or ":" in name
        or Path(name).name != name
    ):
        raise ValueError("Windows quarantine child must be one direct component")
    return name


def _require_direct_directory(metadata: os.stat_result) -> None:
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        raise OSError("Windows quarantine entry is not a direct directory")


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_reparse_tag", 0)
        or (
            _FILE_ATTRIBUTE_REPARSE_POINT
            and getattr(metadata, "st_file_attributes", 0)
            & _FILE_ATTRIBUTE_REPARSE_POINT
        )
    )


def _require_windows() -> None:
    if os.name != "nt":
        raise OSError("Native Windows quarantine I/O is unavailable")


def _raise_last_windows_error() -> NoReturn:
    import ctypes

    get_last_error = getattr(ctypes, "get_last_error")
    win_error = getattr(ctypes, "WinError")
    raise win_error(get_last_error())


_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_ADD_FILE = 0x00000002
_FILE_ADD_SUBDIRECTORY = 0x00000004
_FILE_TRAVERSE = 0x00000020
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_WRITE_ATTRIBUTES = 0x00000100
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_OPEN_REPARSE_POINT = 0x00200000
_FILE_OPEN = 1
_FILE_CREATE = 2
_OPEN_EXISTING = 3
_OBJ_CASE_INSENSITIVE = 0x00000040
_FILE_RENAME_INFO = 3
_FILE_DISPOSITION_INFO = 4
_FILE_ATTRIBUTE_TAG_INFO = 9
_DIRECTORY_READ_ACCESS = (
    _FILE_LIST_DIRECTORY | _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
)
_DIRECTORY_OWNER_ACCESS = (
    _FILE_LIST_DIRECTORY
    | _FILE_ADD_FILE
    | _FILE_ADD_SUBDIRECTORY
    | _FILE_TRAVERSE
    | _FILE_READ_ATTRIBUTES
    | _FILE_WRITE_ATTRIBUTES
    | _SYNCHRONIZE
)


__all__ = [
    "open_windows_directory",
    "open_windows_regular_file_at",
    "supports_windows_rooted_io",
    "windows_flush_file",
    "windows_listdir_at",
    "windows_rename_at",
    "windows_rmdir_at",
    "windows_stat_at",
    "windows_unlink_at",
]
