"""Immutable executable artifacts owned by the local Process substrate."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import sys
from collections.abc import Callable
from ctypes import CDLL, c_char_p, c_int, c_uint, get_errno
from dataclasses import dataclass
from pathlib import Path
from secrets import token_bytes

from .types import ProcessLaunchRequest

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


def _owner_seal_functions() -> tuple[
    Callable[[bytes], bytes],
    Callable[[bytes, bytes], bool],
]:
    key = token_bytes(32)

    def seal(payload: bytes) -> bytes:
        return hmac.digest(key, payload, "sha256")

    def verify(payload: bytes, evidence: bytes) -> bool:
        return hmac.compare_digest(seal(payload), evidence)

    return seal, verify


_seal_owner_payload, _verify_owner_payload = _owner_seal_functions()


@dataclass(frozen=True, slots=True)
class _SealedProcessExecutable:
    descriptor: int
    logical_path: Path
    digest: str
    size: int
    _device: int
    _inode: int
    _owner_seal: bytes
    _closed: bool = False

    def verify(self) -> None:
        if self._closed:
            raise SealedProcessExecutableUnavailable(
                "sealed process executable is closed"
            )
        metadata = os.fstat(self.descriptor)
        if (
            not _verify_owner_payload(self._owner_payload(), self._owner_seal)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size != self.size
            or metadata.st_dev != self._device
            or metadata.st_ino != self._inode
        ):
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
        if _descriptor_digest(self.descriptor, size=self.size) != self.digest:
            raise SealedProcessExecutableUnavailable(
                "sealed process executable digest changed"
            )
        os.lseek(self.descriptor, 0, os.SEEK_SET)

    def authorization_payload(self) -> dict[str, object]:
        self.verify()
        return {
            "digest": self.digest,
            "logicalPath": str(self.logical_path),
            "size": self.size,
        }

    def _owner_payload(self) -> bytes:
        return (
            f"{self.descriptor}\0{self.logical_path}\0{self.digest}\0{self.size}"
            f"\0{self._device}\0{self._inode}"
        ).encode()

    def close(self) -> None:
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        os.close(self.descriptor)


@dataclass(frozen=True, slots=True)
class _BoundProcessDirectory:
    """Open directory identity retained through contained process spawn."""

    descriptor: int
    logical_path: Path
    device: int
    inode: int
    _owner_seal: bytes
    _closed: bool = False

    def verify(self) -> None:
        if self._closed:
            raise SealedProcessExecutableUnavailable(
                "bound process directory is closed"
            )
        metadata = os.fstat(self.descriptor)
        if (
            not _verify_owner_payload(self._owner_payload(), self._owner_seal)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_dev != self.device
            or metadata.st_ino != self.inode
        ):
            raise SealedProcessExecutableUnavailable(
                "bound process directory identity changed"
            )

    def authorization_payload(self) -> dict[str, object]:
        self.verify()
        return {
            "device": self.device,
            "inode": self.inode,
            "logicalPath": str(self.logical_path),
        }

    def _owner_payload(self) -> bytes:
        return (
            f"directory\0{self.descriptor}\0{self.logical_path}"
            f"\0{self.device}\0{self.inode}"
        ).encode()

    def close(self) -> None:
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        os.close(self.descriptor)


@dataclass(frozen=True, slots=True, kw_only=True)
class _SealedExecutableProcessLaunchRequest(ProcessLaunchRequest):
    """Contained spawn request retaining one verified immutable executable."""

    _sealed_executable: _SealedProcessExecutable
    _bound_cwd_directory: _BoundProcessDirectory | None = None
    _request_owner_seal: bytes = b""

    def __post_init__(self) -> None:
        super(_SealedExecutableProcessLaunchRequest, self).__post_init__()
        if type(self._sealed_executable) is not _SealedProcessExecutable:
            raise TypeError("contained process executable artifact is invalid")
        if (
            self._bound_cwd_directory is not None
            and type(self._bound_cwd_directory) is not _BoundProcessDirectory
        ):
            raise TypeError("contained process cwd artifact is invalid")
        self.verify()

    def verify(self) -> None:
        self._sealed_executable.verify()
        if self._bound_cwd_directory is not None:
            self._bound_cwd_directory.verify()
        if not _verify_owner_payload(
            _contained_request_owner_payload(
                self,
                self._sealed_executable,
                self._bound_cwd_directory,
            ),
            self._request_owner_seal,
        ):
            raise SealedProcessExecutableUnavailable(
                "sealed executable spawn request changed"
            )


def _capture_sealed_process_executable(
    path: Path,
    *,
    expected_digest: str,
) -> _SealedProcessExecutable:
    """Copy verified executable bytes into a write-sealed anonymous file."""

    if os.name != "posix" or fcntl is None or not sys.platform.startswith("linux"):
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
        metadata = os.fstat(descriptor)
        owner_payload = (
            f"{descriptor}\0{logical_path}\0{digest}\0{len(body)}"
            f"\0{metadata.st_dev}\0{metadata.st_ino}"
        ).encode()
        artifact = _SealedProcessExecutable(
            descriptor=descriptor,
            logical_path=logical_path,
            digest=digest,
            size=len(body),
            _device=metadata.st_dev,
            _inode=metadata.st_ino,
            _owner_seal=_seal_owner_payload(owner_payload),
        )
        artifact.verify()
        return artifact
    except BaseException:
        os.close(descriptor)
        raise


def _capture_bound_process_directory(
    path: Path,
    *,
    expected_identity: tuple[int, int],
) -> _BoundProcessDirectory:
    """Open one exact cwd directory so Bubblewrap never re-resolves its source."""

    if os.name != "posix" or not sys.platform.startswith("linux"):
        raise SealedProcessExecutableUnavailable(
            "managed process execution requires bound directory support"
        )
    logical_path = Path(path)
    if not logical_path.is_absolute():
        raise SealedProcessExecutableUnavailable(
            "managed process cwd must be an absolute directory"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(logical_path, flags)
    try:
        metadata = os.fstat(descriptor)
        identity = (metadata.st_dev, metadata.st_ino)
        if not stat.S_ISDIR(metadata.st_mode) or identity != expected_identity:
            raise SealedProcessExecutableUnavailable(
                "managed process cwd identity changed"
            )
        owner_payload = (
            f"directory\0{descriptor}\0{logical_path}"
            f"\0{metadata.st_dev}\0{metadata.st_ino}"
        ).encode()
        artifact = _BoundProcessDirectory(
            descriptor=descriptor,
            logical_path=logical_path,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            _owner_seal=_seal_owner_payload(owner_payload),
        )
        artifact.verify()
        return artifact
    except BaseException:
        os.close(descriptor)
        raise


def _sealed_process_executable_from_request(
    request: object,
) -> _SealedProcessExecutable | None:
    if type(request) is _SealedExecutableProcessLaunchRequest:
        request.verify()
    artifact = getattr(request, "_sealed_executable", None)
    if artifact is None:
        return None
    if type(artifact) is not _SealedProcessExecutable:
        raise TypeError("process request executable artifact is invalid")
    artifact.verify()
    return artifact


def _bound_process_directory_from_request(
    request: object,
) -> _BoundProcessDirectory | None:
    if type(request) is _SealedExecutableProcessLaunchRequest:
        request.verify()
    artifact = getattr(request, "_bound_cwd_directory", None)
    if artifact is None:
        return None
    if type(artifact) is not _BoundProcessDirectory:
        raise TypeError("process request cwd artifact is invalid")
    artifact.verify()
    return artifact


def _process_inherited_file_descriptors(request: object) -> tuple[int, ...]:
    artifacts = (
        _sealed_process_executable_from_request(request),
        _bound_process_directory_from_request(request),
    )
    return tuple(artifact.descriptor for artifact in artifacts if artifact is not None)


def _contained_process_launch_request(
    request: ProcessLaunchRequest,
    *,
    command: tuple[str, ...],
) -> ProcessLaunchRequest:
    """Create spawn material without reconstructing a private Tool envelope."""

    artifact = _sealed_process_executable_from_request(request)
    bound_cwd = _bound_process_directory_from_request(request)
    if artifact is None:
        return ProcessLaunchRequest(
            command=command,
            cwd=request.cwd,
            effective_environment=request.effective_environment,
            stream_stderr=request.stream_stderr,
        )
    base = ProcessLaunchRequest(
        command=command,
        cwd=request.cwd,
        effective_environment=request.effective_environment,
        stream_stderr=request.stream_stderr,
    )
    return _SealedExecutableProcessLaunchRequest(
        command=base.command,
        cwd=base.cwd,
        effective_environment=base.effective_environment,
        stream_stderr=base.stream_stderr,
        _sealed_executable=artifact,
        _bound_cwd_directory=bound_cwd,
        _request_owner_seal=_seal_owner_payload(
            _contained_request_owner_payload(base, artifact, bound_cwd)
        ),
    )


def _contained_request_owner_payload(
    request: ProcessLaunchRequest,
    artifact: _SealedProcessExecutable,
    bound_cwd: _BoundProcessDirectory | None,
) -> bytes:
    return json.dumps(
        {
            "artifact": artifact.authorization_payload(),
            "command": request.command,
            "cwd": request.cwd,
            "cwdArtifact": (
                bound_cwd.authorization_payload() if bound_cwd is not None else None
            ),
            "domain": "loushang.sealed-process-spawn/v1",
            "environment": request.effective_environment,
            "streamStderr": request.stream_stderr,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


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


def _descriptor_digest(descriptor: int, *, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            break
        digest.update(chunk)
        offset += len(chunk)
    if offset != size:
        raise SealedProcessExecutableUnavailable(
            "sealed process executable could not be read completely"
        )
    return digest.hexdigest()


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
