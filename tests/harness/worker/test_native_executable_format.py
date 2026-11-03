from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from struct import pack_into

import pytest

from loushang.harness.worker.native_executable_format import (
    WorkerNativeExecutableFormatError,
    verify_worker_native_executable_format,
)


@pytest.mark.skipif(
    sys.platform != "linux" or os.uname().machine not in {"x86_64", "AMD64"},
    reason="Linux x86-64 native executable",
)
def test_linux_static_elf_is_admitted_and_dynamic_closure_is_refused(
    tmp_path: Path,
) -> None:
    static = _static_elf()
    verify_worker_native_executable_format(static, platform="linux-x86_64")
    executable = tmp_path / "static-worker"
    executable.write_bytes(static)
    executable.chmod(0o500)
    subprocess.run([str(executable)], check=True, timeout=5, capture_output=True)
    for kind in (2, 3):  # PT_DYNAMIC, PT_INTERP
        with pytest.raises(WorkerNativeExecutableFormatError) as caught:
            verify_worker_native_executable_format(
                _static_elf(extra_program_type=kind), platform="linux-x86_64"
            )
        assert caught.value.code == "worker_executable_format_invalid"


def _static_elf(*, extra_program_type: int | None = None) -> bytes:
    count = 1 if extra_program_type is None else 2
    header_end = 64 + 56 * count
    code = b"\xb8\x3c\x00\x00\x00\x31\xff\x0f\x05"
    body = bytearray(header_end + len(code))
    body[:7] = b"\x7fELF\x02\x01\x01"
    pack_into("<H", body, 16, 2)
    pack_into("<H", body, 18, 62)
    pack_into("<I", body, 20, 1)
    pack_into("<Q", body, 24, 0x400000 + header_end)
    pack_into("<Q", body, 32, 64)
    pack_into("<H", body, 52, 64)
    pack_into("<H", body, 54, 56)
    pack_into("<H", body, 56, count)
    pack_into("<I", body, 64, 1)
    pack_into("<I", body, 68, 5)
    pack_into("<Q", body, 80, 0x400000)
    pack_into("<Q", body, 88, 0x400000)
    pack_into("<Q", body, 96, len(body))
    pack_into("<Q", body, 104, len(body))
    pack_into("<Q", body, 112, 0x1000)
    if extra_program_type is not None:
        pack_into("<I", body, 120, extra_program_type)
    body[header_end:] = code
    return bytes(body)


def test_worker_format_rejects_scripts_and_foreign_architecture() -> None:
    for body in (b"#!/usr/bin/env python3\n", b"MZ" + b"\0" * 128):
        with pytest.raises(WorkerNativeExecutableFormatError) as caught:
            verify_worker_native_executable_format(body, platform="linux-x86_64")
        assert caught.value.code == "worker_executable_format_invalid"

    foreign_elf = bytearray(64)
    foreign_elf[:7] = b"\x7fELF\x02\x01\x01"
    pack_into("<H", foreign_elf, 16, 3)
    pack_into("<H", foreign_elf, 18, 183)  # AArch64
    pack_into("<I", foreign_elf, 20, 1)
    pack_into("<H", foreign_elf, 52, 64)
    with pytest.raises(WorkerNativeExecutableFormatError) as caught:
        verify_worker_native_executable_format(
            bytes(foreign_elf), platform="linux-x86_64"
        )
    assert caught.value.code == "worker_executable_format_invalid"


def test_windows_pe_header_requires_amd64_pe32_plus_executable_shape() -> None:
    # This checks the parser only; native Windows launch needs separate evidence.
    body = bytearray(512)
    body[:2] = b"MZ"
    pack_into("<I", body, 0x3C, 0x80)
    body[0x80:0x84] = b"PE\x00\x00"
    pack_into("<H", body, 0x84, 0x8664)
    pack_into("<H", body, 0x86, 1)
    pack_into("<H", body, 0x94, 112)
    pack_into("<H", body, 0x96, 0x0002)
    pack_into("<H", body, 0x98, 0x20B)
    verify_worker_native_executable_format(bytes(body), platform="windows-amd64")

    pack_into("<H", body, 0x96, 0x2002)  # executable image plus DLL
    with pytest.raises(WorkerNativeExecutableFormatError) as caught:
        verify_worker_native_executable_format(bytes(body), platform="windows-amd64")
    assert caught.value.code == "worker_executable_format_invalid"
    pack_into("<H", body, 0x96, 0x0002)

    pack_into("<H", body, 0x84, 0x014C)  # i386
    with pytest.raises(WorkerNativeExecutableFormatError) as caught:
        verify_worker_native_executable_format(bytes(body), platform="windows-amd64")
    assert caught.value.code == "worker_executable_format_invalid"


def test_unknown_worker_platform_is_never_admitted() -> None:
    with pytest.raises(WorkerNativeExecutableFormatError) as caught:
        verify_worker_native_executable_format(
            b"native-bytes",
            platform="unknown",  # type: ignore[arg-type]
        )
    assert caught.value.code == "worker_executable_platform_unsupported"
