"""Immutable executable artifacts owned by the local Process substrate."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from ctypes import CDLL, c_char_p, c_int, c_uint, get_errno
from dataclasses import dataclass
from pathlib import Path

try:  # pragma: no cover - import availability is platform-specific
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

_MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
_F_ADD_SEALS = 1033
_F_GET_SEALS = 1034
_F_SEAL_SEAL = 0x0001
_F_SEAL_SHRINK = 0x0002
_F_SEAL_GROW = 0x0004
_F_SEAL_WRITE = 0x0008
_MFD_ALLOW_SEALING = 0x0002


class SealedProcessExecutableUnavailable(RuntimeError):
    """The host cannot bind an executable to immutable Process-owned bytes."""


@dataclass(slots=True)
class _SealedProcessExecutable:
    descriptor: int
    logical_path: Path
    digest: str
    size: int
    _closed: bool = False

    def verify(self) -> None:
        if self._closed:
            raise SealedProcessExecutableUnavailable(
                "sealed process executable is closed"
            )
        metadata = os.fstat(self.descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != self.size:
            raise SealedProcessExecutableUnavailable(
                "sealed process executable identity changed"
            )
        if fcntl is None:
            raise SealedProcessExecutableUnavailable(
                "sealed process executables are unavailable on this platform"
            )
        required = _required_seals()
        if fcntl.fcntl(self.descriptor, _F_GET_SEALS) & required != required:
            raise SealedProcessExecutableUnavailable(
                "process executable is not immutably sealed"
            )
        os.lseek(self.descriptor, 0, os.SEEK_SET)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.close(self.descriptor)


def _capture_sealed_process_executable(
    path: Path,
    *,
    expected_digest: str,
) -> _SealedProcessExecutable:
    """Copy verified executable bytes into a write-sealed anonymous file."""

    if (
        os.name != "posix"
        or fcntl is None
        or not sys.platform.startswith("linux")
    ):
        raise SealedProcessExecutableUnavailable(
            "managed process execution requires sealed executable support"
        )
    logical_path = Path(path).expanduser().resolve(strict=True)
    body = _stable_executable_bytes(logical_path)
    digest = hashlib.sha256(body).hexdigest()
    if digest != expected_digest:
        raise SealedProcessExecutableUnavailable(
            "process executable changed before immutable capture"
        )
    descriptor = _create_memfd()
    try:
        view = memoryview(body)
        written = 0
        while written < len(view):
            written += os.write(descriptor, view[written:])
        os.fchmod(descriptor, 0o500)
        fcntl.fcntl(descriptor, _F_ADD_SEALS, _required_seals())
        artifact = _SealedProcessExecutable(
            descriptor=descriptor,
            logical_path=logical_path,
            digest=digest,
            size=len(body),
        )
        artifact.verify()
        return artifact
    except BaseException:
        os.close(descriptor)
        raise


def _sealed_process_executable_from_request(
    request: object,
) -> _SealedProcessExecutable | None:
    artifact = getattr(request, "_sealed_executable", None)
    if artifact is None:
        return None
    if type(artifact) is not _SealedProcessExecutable:
        raise TypeError("process request executable artifact is invalid")
    artifact.verify()
    return artifact


def _stable_executable_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_EXECUTABLE_BYTES:
            raise SealedProcessExecutableUnavailable(
                "managed runtime must be a bounded regular executable"
            )
        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(body) != before.st_size
        or before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise SealedProcessExecutableUnavailable(
            "managed runtime changed during immutable capture"
        )
    return body


def _create_memfd() -> int:
    native = getattr(os, "memfd_create", None)
    if callable(native):
        return native(
            "loushang-managed-runtime",
            _MFD_ALLOW_SEALING,
        )
    libc = CDLL(None, use_errno=True)
    create = getattr(libc, "memfd_create", None)
    if create is None:
        raise SealedProcessExecutableUnavailable(
            "managed process execution requires memfd_create"
        )
    create.argtypes = (c_char_p, c_uint)
    create.restype = c_int
    descriptor = create(
        b"loushang-managed-runtime",
        _MFD_ALLOW_SEALING,
    )
    if descriptor < 0:
        error_number = get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return descriptor


def _required_seals() -> int:
    return _F_SEAL_SEAL | _F_SEAL_SHRINK | _F_SEAL_GROW | _F_SEAL_WRITE


__all__ = ["SealedProcessExecutableUnavailable"]
