"""Bounded Windows file-stream parsing and native named-stream refusal inputs."""

from __future__ import annotations

import os
from pathlib import Path
from struct import pack

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    _parse_windows_file_stream_info,
    open_windows_directory,
    open_windows_regular_file_at,
    windows_directory_stream_names,
    windows_regular_file_stream_names,
)


def _stream_record(name: str, *, next_offset: int = 0) -> bytes:
    encoded = name.encode("utf-16-le")
    record = pack("<IIqq", next_offset, len(encoded), 0, 0) + encoded
    return record.ljust(next_offset, b"\0") if next_offset else record


def test_windows_stream_info_decodes_default_and_named_records() -> None:
    default = "::$DATA"
    named = ":hidden:$DATA"
    first_size = (len(_stream_record(default)) + 7) & ~7
    raw = _stream_record(default, next_offset=first_size) + _stream_record(named)
    assert _parse_windows_file_stream_info(raw) == (default, named)
    assert _parse_windows_file_stream_info(_stream_record(default)) == (default,)


@pytest.mark.parametrize(
    "raw",
    (
        b"",
        pack("<IIqq", 0, 3, 0, 0) + b"odd",
        pack("<IIqq", 8, 2, 0, 0) + b"a\0",
        _stream_record("::$DATA", next_offset=32) + _stream_record("::$DATA"),
    ),
)
def test_windows_stream_info_rejects_malformed_or_repeated_records(raw: bytes) -> None:
    with pytest.raises(ValueError):
        _parse_windows_file_stream_info(raw)


@pytest.mark.skipif(os.name != "nt", reason="native Windows named data streams")
def test_windows_stream_query_observes_named_data_stream(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_bytes(b"main")
    parent_fd = open_windows_directory(tmp_path)
    try:
        assert all(
            not name.casefold().endswith(":$data") or name.casefold() == "::$data"
            for name in windows_directory_stream_names(parent_fd)
        )
        file_fd = open_windows_regular_file_at(
            parent_fd, path.name, create_new=False, write=False
        )
        try:
            assert windows_regular_file_stream_names(file_fd) == ("::$DATA",)
        finally:
            os.close(file_fd)
        with open(str(path) + ":hidden", "wb") as stream:
            stream.write(b"secret")
        file_fd = open_windows_regular_file_at(
            parent_fd, path.name, create_new=False, write=False
        )
        try:
            assert set(windows_regular_file_stream_names(file_fd)) == {
                "::$DATA",
                ":hidden:$DATA",
            }
        finally:
            os.close(file_fd)
    finally:
        os.close(parent_fd)


@pytest.mark.skipif(os.name != "nt", reason="native Windows directory streams")
def test_windows_stream_query_observes_named_directory_stream(tmp_path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    directory = tmp_path / "private"
    directory.mkdir()
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
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(directory) + ":hidden:$DATA",
        0x40000000,  # GENERIC_WRITE
        0x00000007,  # FILE_SHARE_READ | WRITE | DELETE
        None,
        4,  # OPEN_ALWAYS
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
        None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())
    assert close_handle(wintypes.HANDLE(handle))
    directory_fd = open_windows_directory(directory)
    try:
        assert ":hidden:$DATA" in windows_directory_stream_names(directory_fd)
    finally:
        os.close(directory_fd)
