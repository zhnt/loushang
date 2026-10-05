"""Native Windows rooted-handle primitives for the PLC9B quarantine owner."""

from __future__ import annotations

import os
import stat
from functools import lru_cache
from pathlib import Path
from struct import unpack_from
from typing import Any, NoReturn

_MAX_STREAM_INFO_BYTES = 64 * 1024
_STREAM_INFO_HEADER_BYTES = 24


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
    security_descriptor: int | None = None,
    read_control: bool = False,
) -> int:
    """Open or create one direct directory, anchored to ``dir_fd`` when set."""

    _require_windows()
    if security_descriptor is not None and (
        not create_new
        or type(security_descriptor) is not int
        or security_descriptor <= 0
    ):
        raise ValueError("Windows directory security descriptor requires creation")
    if dir_fd is None:
        if create_new:
            raise ValueError("A rooted parent handle is required to create a directory")
        return _open_directory_path(
            Path(path),
            share_delete=share_delete,
            writable=writable,
            read_control=read_control,
        )
    if create_new and not writable:
        raise ValueError("A newly created Windows directory must be writable")
    name = _component(path)
    raw_handle = _nt_open_at(
        dir_fd,
        name,
        desired_access=(_DIRECTORY_OWNER_ACCESS if writable else _DIRECTORY_READ_ACCESS)
        | (_READ_CONTROL if read_control else 0),
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
        security_descriptor=security_descriptor,
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
    security_descriptor: int | None = None,
    read_control: bool = False,
) -> int:
    """Open one no-follow regular file relative to a pinned directory handle."""

    _require_windows()
    if security_descriptor is not None and (
        not create_new
        or type(security_descriptor) is not int
        or security_descriptor <= 0
    ):
        raise ValueError("Windows file security descriptor requires creation")
    component = _component(name)
    desired_access = _GENERIC_READ | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
    if write:
        desired_access |= _GENERIC_WRITE
    if read_control:
        desired_access |= _READ_CONTROL
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
        security_descriptor=security_descriptor,
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


def windows_regular_file_stream_names(descriptor: int) -> tuple[str, ...]:
    """Enumerate data streams on one pinned, direct regular-file handle."""

    _require_windows()
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or _is_reparse(metadata):
        raise OSError("Windows stream query requires a direct regular file")
    return _windows_handle_stream_names(descriptor)


def windows_directory_stream_names(descriptor: int) -> tuple[str, ...]:
    """Enumerate streams on one pinned, direct directory handle."""

    _require_windows()
    _require_direct_directory(os.fstat(descriptor))
    return _windows_handle_stream_names(descriptor)


def _windows_handle_stream_names(descriptor: int) -> tuple[str, ...]:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    query = kernel32.GetFileInformationByHandleEx
    query.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    query.restype = wintypes.BOOL
    handle = wintypes.HANDLE(getattr(msvcrt, "get_osfhandle")(descriptor))
    size = 4096
    while size <= _MAX_STREAM_INFO_BYTES:
        buffer = ctypes.create_string_buffer(size)
        if query(handle, 7, buffer, size):  # FileStreamInfo
            return _parse_windows_file_stream_info(buffer.raw)
        error = getattr(ctypes, "get_last_error")()
        if error == 38:  # ERROR_HANDLE_EOF: no streams returned
            return ()
        if error not in {122, 234}:  # INSUFFICIENT_BUFFER / MORE_DATA
            raise getattr(ctypes, "WinError")(error)
        size *= 2
    raise OSError("Windows file stream information exceeds the bounded buffer")


def _parse_windows_file_stream_info(raw: bytes) -> tuple[str, ...]:
    """Decode the bounded, 8-byte-aligned FILE_STREAM_INFO chain."""

    if not isinstance(raw, bytes) or len(raw) > _MAX_STREAM_INFO_BYTES:
        raise ValueError("Windows file stream information is invalid")
    names: list[str] = []
    cursor = 0
    while True:
        if cursor + _STREAM_INFO_HEADER_BYTES > len(raw):
            raise ValueError("Windows file stream information is truncated")
        next_offset, name_bytes, _size, _allocation = unpack_from("<IIqq", raw, cursor)
        end = cursor + _STREAM_INFO_HEADER_BYTES + name_bytes
        if name_bytes == 0 or name_bytes % 2 or end > len(raw):
            raise ValueError("Windows file stream name is invalid")
        try:
            name = raw[cursor + _STREAM_INFO_HEADER_BYTES : end].decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise ValueError("Windows file stream name is invalid") from exc
        names.append(name)
        if len(names) > 128:
            raise ValueError("Windows file stream count exceeds the bound")
        if next_offset == 0:
            if len(names) != len(set(names)):
                raise ValueError("Windows file stream names repeat")
            return tuple(names)
        if (
            next_offset % 8
            or next_offset < _STREAM_INFO_HEADER_BYTES + name_bytes
            or cursor + next_offset >= len(raw)
        ):
            raise ValueError("Windows file stream chain is invalid")
        cursor += next_offset


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


def open_windows_deletion_entry_at(
    directory_fd: int, name: str, *, directory: bool
) -> int:
    """Open one direct child for same-handle inspection and deletion.

    Writers and other delete/rename opens are excluded while it is held. The caller owns
    the descriptor and must close it after calling ``windows_delete_open_entry``.
    """

    _require_windows()
    if type(directory) is not bool:
        raise TypeError("Windows deletion entry kind must be explicit")
    raw_handle = _nt_open_at(
        directory_fd,
        _component(name),
        desired_access=_GENERIC_READ | _READ_CONTROL | _DELETE | _SYNCHRONIZE,
        share_access=_FILE_SHARE_READ,
        create_disposition=_FILE_OPEN,
        create_options=(
            _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_OPEN_REPARSE_POINT
            | (_FILE_DIRECTORY_FILE if directory else _FILE_NON_DIRECTORY_FILE)
        ),
    )
    descriptor = _descriptor_from_handle(raw_handle, write=False)
    try:
        metadata = os.fstat(descriptor)
        if (
            _is_reparse(metadata)
            or (directory and not stat.S_ISDIR(metadata.st_mode))
            or (not directory and not stat.S_ISREG(metadata.st_mode))
        ):
            raise OSError("Windows deletion entry is not a direct expected kind")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def windows_delete_open_entry(
    descriptor: int,
    *,
    expected_identity: tuple[int, int, int, int, int],
    directory: bool,
) -> None:
    """Delete the inspected object only while its original handle is held."""

    _require_windows()
    import msvcrt

    if (
        type(directory) is not bool
        or type(expected_identity) is not tuple
        or len(expected_identity) != 5
        or any(type(value) is not int or value < 0 for value in expected_identity)
    ):
        raise ValueError("Windows deletion identity is invalid")
    metadata = os.fstat(descriptor)
    raw_handle = getattr(msvcrt, "get_osfhandle")(descriptor)
    is_directory, is_reparse = _handle_entry_kind(raw_handle)
    if (
        is_reparse
        or is_directory != directory
        or (directory and not stat.S_ISDIR(metadata.st_mode))
        or (
            not directory
            and (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1)
        )
    ):
        raise OSError("Windows deletion entry kind changed")
    identity = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )
    if (
        identity[:3] != expected_identity[:3]
        if directory
        else identity != expected_identity
    ):
        raise OSError("Windows deletion entry identity changed")
    _mark_handle_for_delete(raw_handle)


def windows_rename_at(
    directory_fd: int,
    old_name: str,
    new_name: str,
) -> None:
    """Atomically rename one direct child beneath the same pinned directory."""

    raw_handle = _open_for_delete(directory_fd, _component(old_name))
    try:
        _rename_open_windows_handle_at(directory_fd, raw_handle, new_name)
    finally:
        _close_handle(raw_handle)


def windows_rename_open_directory_at(
    directory_fd: int,
    descriptor: int,
    new_name: str,
    *,
    expected_identity: tuple[int, int, int, int, int],
) -> None:
    """Rename a verified direct directory through its already-open handle."""

    _require_windows()
    import msvcrt

    metadata = os.fstat(descriptor)
    raw_handle = getattr(msvcrt, "get_osfhandle")(descriptor)
    is_directory, is_reparse = _handle_entry_kind(raw_handle)
    if (
        type(expected_identity) is not tuple
        or len(expected_identity) != 5
        or any(type(value) is not int or value < 0 for value in expected_identity)
        or not is_directory
        or is_reparse
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino, metadata.st_mode) != expected_identity[:3]
    ):
        raise OSError("Windows rename directory identity changed")
    _rename_open_windows_handle_at(directory_fd, raw_handle, new_name)


def _rename_open_windows_handle_at(
    directory_fd: int, raw_handle: int, new_name: str
) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    encoded_name = _component(new_name).encode("utf-16-le")

    class _IoStatusValue(ctypes.Union):
        _fields_ = (("status", wintypes.LONG), ("pointer", wintypes.LPVOID))

    class _IoStatusBlock(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = (("value", _IoStatusValue), ("information", ctypes.c_size_t))

    class _FileRenameInformation(ctypes.Structure):
        _fields_ = (
            ("replace_if_exists", ctypes.c_ubyte),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
            ("file_name", ctypes.c_byte * len(encoded_name)),
        )

    information = _FileRenameInformation(
        replace_if_exists=False,
        root_directory=wintypes.HANDLE(getattr(msvcrt, "get_osfhandle")(directory_fd)),
        file_name_length=len(encoded_name),
        file_name=(ctypes.c_byte * len(encoded_name)).from_buffer_copy(encoded_name),
    )
    io_status = _IoStatusBlock()
    ntdll = getattr(ctypes, "WinDLL")("ntdll")
    set_information = ntdll.NtSetInformationFile
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        ctypes.c_int,
    )
    set_information.restype = wintypes.LONG
    status = set_information(
        wintypes.HANDLE(raw_handle),
        ctypes.byref(io_status),
        ctypes.byref(information),
        ctypes.sizeof(information),
        _FILE_RENAME_INFORMATION,
    )
    if status < 0:
        rtl_status_to_dos_error = ntdll.RtlNtStatusToDosError
        rtl_status_to_dos_error.argtypes = (wintypes.LONG,)
        rtl_status_to_dos_error.restype = wintypes.ULONG
        raise getattr(ctypes, "WinError")(rtl_status_to_dos_error(status))


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


def windows_flush_directory(descriptor: int) -> None:
    """Synchronously flush directory data and metadata through its native handle."""

    import ctypes
    import msvcrt
    from ctypes import wintypes

    _require_direct_directory(os.fstat(descriptor))

    class _IoStatusValue(ctypes.Union):
        _fields_ = (("status", wintypes.LONG), ("pointer", wintypes.LPVOID))

    class _IoStatusBlock(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = (("value", _IoStatusValue), ("information", ctypes.c_size_t))

    ntdll = getattr(ctypes, "WinDLL")("ntdll")
    flush = ntdll.NtFlushBuffersFileEx
    flush.argtypes = (
        wintypes.HANDLE,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
        ctypes.POINTER(_IoStatusBlock),
    )
    flush.restype = wintypes.LONG
    io_status = _IoStatusBlock()
    status = flush(
        wintypes.HANDLE(getattr(msvcrt, "get_osfhandle")(descriptor)),
        0,
        None,
        0,
        ctypes.byref(io_status),
    )
    if status < 0:
        rtl_status_to_dos_error = ntdll.RtlNtStatusToDosError
        rtl_status_to_dos_error.argtypes = (wintypes.LONG,)
        rtl_status_to_dos_error.restype = wintypes.ULONG
        raise getattr(ctypes, "WinError")(rtl_status_to_dos_error(status))


def _open_directory_path(
    path: Path,
    *,
    share_delete: bool,
    writable: bool,
    read_control: bool,
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
        (_DIRECTORY_OWNER_ACCESS if writable else _DIRECTORY_READ_ACCESS)
        | (_READ_CONTROL if read_control else 0),
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
    security_descriptor: int | None = None,
) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    (
        _ntdll,
        nt_create_file,
        rtl_status_to_dos_error,
        unicode_type,
        io_status_type,
        attributes_type,
    ) = _nt_open_bindings()
    name_buffer = ctypes.create_unicode_buffer(name)
    name_length = len(name.encode("utf-16-le"))
    unicode_name = unicode_type(
        length=name_length,
        maximum_length=name_length + ctypes.sizeof(ctypes.c_wchar),
        buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    object_attributes = attributes_type(
        length=ctypes.sizeof(attributes_type),
        root_directory=wintypes.HANDLE(getattr(msvcrt, "get_osfhandle")(directory_fd)),
        object_name=ctypes.pointer(unicode_name),
        attributes=_OBJ_CASE_INSENSITIVE,
        security_descriptor=ctypes.c_void_p(security_descriptor),
        security_quality_of_service=None,
    )
    io_status = io_status_type()
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
        raise getattr(ctypes, "WinError")(rtl_status_to_dos_error(status))
    if opened_handle.value is None:
        raise OSError("Windows returned an invalid quarantine handle")
    return int(opened_handle.value)


@lru_cache(maxsize=1)
def _nt_open_bindings() -> tuple[Any, Any, Any, type[Any], type[Any], type[Any]]:
    """Retain one native ABI binding instead of creating ctypes types per open."""

    import ctypes
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
    rtl_status_to_dos_error = ntdll.RtlNtStatusToDosError
    rtl_status_to_dos_error.argtypes = (wintypes.LONG,)
    rtl_status_to_dos_error.restype = wintypes.ULONG
    return (
        ntdll,
        nt_create_file,
        rtl_status_to_dos_error,
        _UnicodeString,
        _IoStatusBlock,
        _ObjectAttributes,
    )


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
_READ_CONTROL = 0x00020000
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
_FILE_RENAME_INFORMATION = 10
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
    "windows_flush_directory",
    "windows_flush_file",
    "windows_listdir_at",
    "windows_rename_at",
    "windows_rmdir_at",
    "windows_stat_at",
    "windows_unlink_at",
]
