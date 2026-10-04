"""Inert native-format check for a bounded local Worker Wheel member.

This is a structural admission check, not a signature, sandbox, launch, or
Product authorization. The native profile owner must still bind the platform.
"""

from __future__ import annotations

from struct import unpack_from
from typing import Literal

WorkerNativeExecutablePlatform = Literal["linux-x86_64", "windows-amd64"]

_MAX_EXECUTABLE_BYTES = 16 * 1024 * 1024


class WorkerNativeExecutableFormatError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def verify_worker_native_executable_format(
    body: bytes, *, platform: WorkerNativeExecutablePlatform
) -> None:
    """Reject scripts, foreign architectures, and truncated ELF/PE headers."""

    if not isinstance(body, bytes) or not 0 < len(body) <= _MAX_EXECUTABLE_BYTES:
        raise WorkerNativeExecutableFormatError("worker_executable_size_invalid")
    if platform == "linux-x86_64":
        program_offset = unpack_from("<Q", body, 32)[0] if len(body) >= 64 else 0
        program_entry_size = unpack_from("<H", body, 54)[0] if len(body) >= 64 else 0
        program_count = unpack_from("<H", body, 56)[0] if len(body) >= 64 else 0
        if (
            len(body) < 64
            or body[:4] != b"\x7fELF"
            or body[4:7] != b"\x02\x01\x01"
            or unpack_from("<H", body, 16)[0] not in {2, 3}
            or unpack_from("<H", body, 18)[0] != 62
            or unpack_from("<I", body, 20)[0] != 1
            or unpack_from("<H", body, 52)[0] != 64
            or program_offset < 64
            or program_entry_size < 56
            or not 1 <= program_count <= 1024
            or program_offset + program_entry_size * program_count > len(body)
        ):
            raise WorkerNativeExecutableFormatError("worker_executable_format_invalid")
        program_types = {
            unpack_from("<I", body, program_offset + index * program_entry_size)[0]
            for index in range(program_count)
        }
        if 1 not in program_types or program_types & {2, 3}:
            raise WorkerNativeExecutableFormatError("worker_executable_format_invalid")
        return
    if platform == "windows-amd64":
        if len(body) < 64 or body[:2] != b"MZ":
            raise WorkerNativeExecutableFormatError("worker_executable_format_invalid")
        pe_offset = unpack_from("<I", body, 0x3C)[0]
        if (
            pe_offset < 64
            or pe_offset > len(body) - 24
            or body[pe_offset : pe_offset + 4] != b"PE\x00\x00"
            or unpack_from("<H", body, pe_offset + 4)[0] != 0x8664
            or unpack_from("<H", body, pe_offset + 6)[0] < 1
        ):
            raise WorkerNativeExecutableFormatError("worker_executable_format_invalid")
        optional_size = unpack_from("<H", body, pe_offset + 20)[0]
        section_count = unpack_from("<H", body, pe_offset + 6)[0]
        characteristics = unpack_from("<H", body, pe_offset + 22)[0]
        optional_offset = pe_offset + 24
        if (
            optional_size < 112
            or optional_offset + optional_size > len(body)
            or optional_offset + optional_size + 40 * section_count > len(body)
            or unpack_from("<H", body, optional_offset)[0] != 0x20B
            or characteristics & 0x0002 == 0
            or characteristics & 0x2000 != 0
        ):
            raise WorkerNativeExecutableFormatError("worker_executable_format_invalid")
        return
    raise WorkerNativeExecutableFormatError("worker_executable_platform_unsupported")


__all__ = [
    "WorkerNativeExecutableFormatError",
    "WorkerNativeExecutablePlatform",
    "verify_worker_native_executable_format",
]
