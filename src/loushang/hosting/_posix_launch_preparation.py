"""Private H6.2 Linux static-closure launch preparation.

The native profiles are intentionally narrow: bounded static ELF images are
copied into write-sealed memfds and one cwd directory is retained by file
descriptor. Scripts and dynamically loaded executables are rejected because
these profiles cannot prove their interpreter or loader closure. The
contained profile pins a caller-admitted static containment launcher beside
the payload; Hosting binds its identity and invocation but does not interpret
the caller-owned containment meaning.
"""

from __future__ import annotations

import hashlib
import os
import platform
import stat
import struct
import sys
import threading
from collections.abc import Callable
from ctypes import CDLL, c_char_p, c_int, c_uint, get_errno
from dataclasses import dataclass

from ._launch_preparation import (
    _CapturedLaunchMaterial,
    _LaunchCaptureSpec,
    _ManagedSpawnEffect,
)
from ._process_backend import (
    _ProcessBackend,
    _ProcessInheritance,
    _ProcessTransport,
)
from .contracts import ProcessLaunchRequest
from .errors import HostingError, HostingFailureCategory

try:  # pragma: no cover - import availability is platform-specific
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

_DIRECT_PROFILE_ID = "posix-static-elf-v1"
_CONTAINED_PROFILE_ID = "posix-static-contained-elf-v1"
_CONTAINMENT_ARGUMENT_PROTOCOL = "loushang-static-containment-launch/v1"
_PLATFORM_IDENTITY = "platform:linux-x86_64-syscall-abi"
_SUPPORTED_MACHINES = frozenset({"amd64", "x86_64"})
_MAX_EXECUTABLE_BYTES = 64 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024
_MFD_CLOEXEC = 0x0001
_MFD_ALLOW_SEALING = 0x0002
_F_ADD_SEALS = 1033
_F_GET_SEALS = 1034
_F_SEAL_SEAL = 0x0001
_F_SEAL_SHRINK = 0x0002
_F_SEAL_GROW = 0x0004
_F_SEAL_WRITE = 0x0008
_PT_DYNAMIC = 2
_PT_INTERP = 3


@dataclass(frozen=True, slots=True)
class _PosixStaticLaunchCaptureSpec(_LaunchCaptureSpec):
    """Typed Linux profile selected only by trusted private composition."""

    executable_sha256: str
    cwd_device: int
    cwd_inode: int

    def __post_init__(self) -> None:
        super(_PosixStaticLaunchCaptureSpec, self).__post_init__()
        if self.profile_id != _DIRECT_PROFILE_ID:
            raise ValueError("POSIX static launch profile_id is unsupported")
        _require_sha256(self.executable_sha256, name="executable")
        if (
            type(self.cwd_device) is not int
            or self.cwd_device < 0
            or type(self.cwd_inode) is not int
            or self.cwd_inode < 1
        ):
            raise ValueError("POSIX static cwd identity is invalid")
        if not self.request.argv[0].startswith("/") or not self.request.cwd.startswith(
            "/"
        ):
            raise ValueError("POSIX static launch paths must be absolute")
        if self.request.effective_environment:
            raise ValueError("POSIX static closure requires an empty environment")
        expected_closure = (
            f"static-elf:sha256:{self.executable_sha256}",
            f"cwd:posix:{self.cwd_device}:{self.cwd_inode}",
            _PLATFORM_IDENTITY,
        )
        if self.execution_closure != expected_closure:
            raise ValueError("POSIX static execution closure is inconsistent")


@dataclass(frozen=True, slots=True)
class _PosixStaticContainedLaunchCaptureSpec(_LaunchCaptureSpec):
    """Caller-selected static launcher and payload with a closed invocation."""

    launcher_path: str
    launcher_sha256: str
    executable_sha256: str
    cwd_device: int
    cwd_inode: int
    containment_profile_sha256: str

    def __post_init__(self) -> None:
        super(_PosixStaticContainedLaunchCaptureSpec, self).__post_init__()
        if self.profile_id != _CONTAINED_PROFILE_ID:
            raise ValueError("POSIX contained launch profile_id is unsupported")
        for name, digest in (
            ("launcher", self.launcher_sha256),
            ("executable", self.executable_sha256),
            ("containment profile", self.containment_profile_sha256),
        ):
            _require_sha256(digest, name=name)
        if (
            type(self.cwd_device) is not int
            or self.cwd_device < 0
            or type(self.cwd_inode) is not int
            or self.cwd_inode < 1
        ):
            raise ValueError("POSIX contained cwd identity is invalid")
        if (
            not isinstance(self.launcher_path, str)
            or not self.launcher_path.startswith("/")
            or "\0" in self.launcher_path
            or not self.request.argv[0].startswith("/")
            or not self.request.cwd.startswith("/")
        ):
            raise ValueError("POSIX contained launch paths must be absolute")
        if self.request.effective_environment:
            raise ValueError("POSIX contained closure requires an empty environment")
        expected_closure = (
            f"containment-launcher-static-elf:sha256:{self.launcher_sha256}",
            f"payload-static-elf:sha256:{self.executable_sha256}",
            f"cwd:posix:{self.cwd_device}:{self.cwd_inode}",
            f"containment-profile:sha256:{self.containment_profile_sha256}",
            f"invocation:{_CONTAINMENT_ARGUMENT_PROTOCOL}",
            _PLATFORM_IDENTITY,
        )
        if self.execution_closure != expected_closure:
            raise ValueError("POSIX contained execution closure is inconsistent")


class _PosixStaticLaunchCaptureBackend:
    """Linux acquisition half matched to ``_PosixProcessBackend``."""

    backend_id = "posix-process-group-v1"

    def __init__(self) -> None:
        if (
            os.name != "posix"
            or not sys.platform.startswith("linux")
            or platform.machine().lower() not in _SUPPORTED_MACHINES
            or fcntl is None
            or not _memfd_available()
            or not callable(getattr(os, "pread", None))
            or any(
                type(getattr(os, name, None)) is not int
                for name in ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
            )
        ):
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "POSIX static launch preparation requires Linux x86_64 memfd sealing",
            )
        if not os.path.isdir("/proc/self/fd"):
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "POSIX static launch preparation requires procfs descriptor paths",
            )

    async def capture(
        self,
        spec: _LaunchCaptureSpec,
        *,
        attempt_id: str,
        attempt_token: object,
        on_capture: Callable[[_CapturedLaunchMaterial], None],
    ) -> "_PosixStaticLaunchMaterial":
        if type(spec) is _PosixStaticLaunchCaptureSpec:
            return await self._capture_direct(
                spec,
                attempt_id=attempt_id,
                attempt_token=attempt_token,
                on_capture=on_capture,
            )
        if type(spec) is _PosixStaticContainedLaunchCaptureSpec:
            return await self._capture_contained(
                spec,
                attempt_id=attempt_id,
                attempt_token=attempt_token,
                on_capture=on_capture,
            )
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "POSIX launch preparation requires an exact static profile",
        )

    async def _capture_direct(
        self,
        spec: _PosixStaticLaunchCaptureSpec,
        *,
        attempt_id: str,
        attempt_token: object,
        on_capture: Callable[[_CapturedLaunchMaterial], None],
    ) -> "_PosixStaticLaunchMaterial":
        executable = _capture_static_elf(
            spec.request.argv[0], expected_digest=spec.executable_sha256
        )
        cwd = -1
        try:
            cwd = _capture_cwd(
                spec.request.cwd,
                expected_identity=(spec.cwd_device, spec.cwd_inode),
            )
            material = _PosixStaticLaunchMaterial(
                spec=spec,
                attempt_id=attempt_id,
                attempt_token=attempt_token,
                executable_descriptor=executable,
                cwd_descriptor=cwd,
            )
            executable = -1
            cwd = -1
            await _attach_captured(material, on_capture=on_capture)
            return material
        except BaseException as primary:
            _close_local_descriptor(cwd, primary=primary, role="cwd")
            _close_local_descriptor(
                executable,
                primary=primary,
                role="executable",
            )
            raise

    async def _capture_contained(
        self,
        spec: _PosixStaticContainedLaunchCaptureSpec,
        *,
        attempt_id: str,
        attempt_token: object,
        on_capture: Callable[[_CapturedLaunchMaterial], None],
    ) -> "_PosixStaticLaunchMaterial":
        launcher = _capture_static_elf(
            spec.launcher_path, expected_digest=spec.launcher_sha256
        )
        executable = -1
        cwd = -1
        try:
            executable = _capture_static_elf(
                spec.request.argv[0], expected_digest=spec.executable_sha256
            )
            cwd = _capture_cwd(
                spec.request.cwd,
                expected_identity=(spec.cwd_device, spec.cwd_inode),
            )
            material = _PosixStaticLaunchMaterial(
                spec=spec,
                attempt_id=attempt_id,
                attempt_token=attempt_token,
                executable_descriptor=executable,
                cwd_descriptor=cwd,
                launcher_descriptor=launcher,
            )
            launcher = -1
            executable = -1
            cwd = -1
            await _attach_captured(material, on_capture=on_capture)
            return material
        except BaseException as primary:
            _close_local_descriptor(cwd, primary=primary, role="cwd")
            _close_local_descriptor(
                executable,
                primary=primary,
                role="executable",
            )
            _close_local_descriptor(
                launcher,
                primary=primary,
                role="containment launcher",
            )
            raise


async def _attach_captured(
    material: "_PosixStaticLaunchMaterial",
    *,
    on_capture: Callable[[_CapturedLaunchMaterial], None],
) -> None:
    try:
        on_capture(material)
    except BaseException as primary:
        try:
            await material.close()
        except BaseException as cleanup:
            primary.add_note(
                f"POSIX captured material cleanup also failed: {cleanup}"
            )
            raise primary from cleanup
        raise


class _PosixStaticLaunchMaterial:
    """One attempt-bound set of retained executable, cwd, and launcher fds."""

    backend_id = "posix-process-group-v1"

    def __init__(
        self,
        *,
        spec: _PosixStaticLaunchCaptureSpec
        | _PosixStaticContainedLaunchCaptureSpec,
        attempt_id: str,
        attempt_token: object,
        executable_descriptor: int,
        cwd_descriptor: int,
        launcher_descriptor: int = -1,
    ) -> None:
        self._spec = spec
        self._attempt_id = attempt_id
        self._attempt_token = attempt_token
        self._executable_descriptor = executable_descriptor
        self._cwd_descriptor = cwd_descriptor
        self._launcher_descriptor = launcher_descriptor
        executable_stat = os.fstat(executable_descriptor)
        self._executable_identity = (executable_stat.st_dev, executable_stat.st_ino)
        self._launcher_identity: tuple[int, int] | None = None
        if launcher_descriptor >= 0:
            launcher_stat = os.fstat(launcher_descriptor)
            self._launcher_identity = (launcher_stat.st_dev, launcher_stat.st_ino)
        self._inherited_slot_count = 3 if launcher_descriptor >= 0 else 2
        self._state = "captured"
        self._lock = threading.Lock()

    @property
    def attempt_id(self) -> str:
        return self._attempt_id

    @property
    def attempt_token(self) -> object:
        return self._attempt_token

    @property
    def profile_id(self) -> str:
        return self._spec.profile_id

    @property
    def execution_closure(self) -> tuple[str, ...]:
        return self._spec.execution_closure

    @property
    def request(self) -> ProcessLaunchRequest:
        return self._spec.request

    @property
    def inherited_slot_count(self) -> int:
        return self._inherited_slot_count

    async def verify_current(self, request: ProcessLaunchRequest) -> None:
        if request != self._spec.request:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "POSIX static launch request changed before verification",
            )
        with self._lock:
            if self._state != "captured":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "POSIX static launch material cannot be verified",
                )
            _verify_static_descriptor(
                self._executable_descriptor,
                expected_digest=self._spec.executable_sha256,
                expected_identity=self._executable_identity,
            )
            _verify_cwd_descriptor(
                self._cwd_descriptor,
                expected_identity=(self._spec.cwd_device, self._spec.cwd_inode),
            )
            if type(self._spec) is _PosixStaticContainedLaunchCaptureSpec:
                if self._launcher_descriptor < 0 or self._launcher_identity is None:
                    raise HostingError(
                        HostingFailureCategory.PREPARATION_STALE,
                        "POSIX containment launcher is unavailable",
                    )
                _verify_static_descriptor(
                    self._launcher_descriptor,
                    expected_digest=self._spec.launcher_sha256,
                    expected_identity=self._launcher_identity,
                )
            self._state = "verified"

    async def spawn(
        self,
        backend: _ProcessBackend,
        request: ProcessLaunchRequest,
        *,
        effect: _ManagedSpawnEffect,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None,
    ) -> _ProcessTransport:
        from ._posix_process import _PosixProcessBackend

        if type(backend) is not _PosixProcessBackend:
            raise effect.not_created(
                HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "POSIX static material received a mismatched process backend",
                )
            )
        return await backend._spawn_static_prepared(
            self,
            request,
            effect=effect,
            on_spawn=on_spawn,
            inheritance=inheritance,
        )

    def _claim_descriptors(self) -> tuple[int, int, int | None]:
        with self._lock:
            if self._state != "verified":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "POSIX static material is not verified for spawn",
                )
            self._state = "claimed"
            return (
                self._executable_descriptor,
                self._cwd_descriptor,
                self._launcher_descriptor if self._launcher_descriptor >= 0 else None,
            )

    def _contained_invocation(
        self,
        *,
        executable_descriptor: int,
        cwd_descriptor: int,
        launcher_descriptor: int,
    ) -> tuple[str, ...]:
        if type(self._spec) is not _PosixStaticContainedLaunchCaptureSpec:
            raise RuntimeError("POSIX direct material has no containment invocation")
        return (
            self._spec.launcher_path,
            "--loushang-protocol",
            _CONTAINMENT_ARGUMENT_PROTOCOL,
            "--loushang-profile-sha256",
            self._spec.containment_profile_sha256,
            "--loushang-payload-fd",
            str(executable_descriptor),
            "--loushang-preparation-fds",
            f"{launcher_descriptor},{executable_descriptor},{cwd_descriptor}",
            "--",
            *self._spec.request.argv,
        )

    def _mark_transferred(self) -> None:
        with self._lock:
            if self._state != "claimed":
                raise RuntimeError("POSIX static transfer state is inconsistent")
            self._state = "transferred"

    async def close(self) -> None:
        with self._lock:
            if self._state == "closed":
                return
            descriptors = (
                ("_executable_descriptor", self._executable_descriptor),
                ("_cwd_descriptor", self._cwd_descriptor),
                ("_launcher_descriptor", self._launcher_descriptor),
            )
        failures: list[BaseException] = []
        for attribute, descriptor in descriptors:
            if descriptor < 0:
                continue
            # Linux releases the numeric descriptor early in close(2), even
            # when a later flush/reporting step returns an error. Never retry
            # that number: another thread may already have reused it.
            with self._lock:
                if getattr(self, attribute) != descriptor:
                    continue
                setattr(self, attribute, -1)
            try:
                os.close(descriptor)
            except BaseException as error:
                failures.append(error)
        with self._lock:
            self._state = (
                "closed"
                if self._executable_descriptor < 0
                and self._cwd_descriptor < 0
                and self._launcher_descriptor < 0
                else "close-failed"
            )
        if failures:
            raise BaseExceptionGroup(
                "POSIX static launch descriptor cleanup failed",
                failures,
            )


def _capture_static_elf(path: str, *, expected_digest: str) -> int:
    source_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    source_flags |= getattr(os, "O_NOFOLLOW", 0)
    source = os.open(path, source_flags)
    destination = -1
    try:
        destination = _ensure_preparation_descriptor(_create_memfd())
        before = os.fstat(source)
        if (
            not stat.S_ISREG(before.st_mode)
            or not before.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            or before.st_size < 1
            or before.st_size > _MAX_EXECUTABLE_BYTES
        ):
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "POSIX static executable is not a bounded executable file",
            )
        digest = hashlib.sha256()
        copied = 0
        while copied < before.st_size:
            chunk = os.read(source, min(_COPY_CHUNK_BYTES, before.st_size - copied))
            if not chunk:
                break
            digest.update(chunk)
            _write_all(destination, chunk)
            copied += len(chunk)
        extra = os.read(source, 1)
        after = os.fstat(source)
        if (
            copied != before.st_size
            or extra
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or digest.hexdigest() != expected_digest
        ):
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "POSIX static executable changed during capture",
            )
        os.fchmod(destination, 0o500)
        assert fcntl is not None
        fcntl.fcntl(destination, _F_ADD_SEALS, _required_seals())
        _verify_static_elf(destination, size=copied)
        destination_stat = os.fstat(destination)
        _verify_static_descriptor(
            destination,
            expected_digest=expected_digest,
            expected_identity=(destination_stat.st_dev, destination_stat.st_ino),
        )
    except BaseException as primary:
        _close_local_descriptor(
            destination,
            primary=primary,
            role="captured executable",
        )
        _close_local_descriptor(source, primary=primary, role="source executable")
        raise
    try:
        os.close(source)
    except BaseException as primary:
        _close_local_descriptor(
            destination,
            primary=primary,
            role="captured executable",
        )
        raise
    return destination


def _capture_cwd(path: str, *, expected_identity: tuple[int, int]) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = _ensure_preparation_descriptor(os.open(path, flags))
    try:
        _verify_cwd_descriptor(
            descriptor,
            expected_identity=expected_identity,
        )
        return descriptor
    except BaseException as primary:
        _close_local_descriptor(descriptor, primary=primary, role="cwd")
        raise


def _verify_static_descriptor(
    descriptor: int,
    *,
    expected_digest: str,
    expected_identity: tuple[int, int],
) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino) != expected_identity
        or metadata.st_size < 1
        or metadata.st_size > _MAX_EXECUTABLE_BYTES
    ):
        raise HostingError(
            HostingFailureCategory.PREPARATION_STALE,
            "POSIX sealed executable identity changed",
        )
    assert fcntl is not None
    if fcntl.fcntl(descriptor, _F_GET_SEALS) & _required_seals() != _required_seals():
        raise HostingError(
            HostingFailureCategory.PREPARATION_STALE,
            "POSIX executable memfd is no longer sealed",
        )
    if _descriptor_digest(descriptor, metadata.st_size) != expected_digest:
        raise HostingError(
            HostingFailureCategory.PREPARATION_STALE,
            "POSIX sealed executable digest changed",
        )


def _verify_cwd_descriptor(
    descriptor: int,
    *,
    expected_identity: tuple[int, int],
) -> None:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or (
        metadata.st_dev,
        metadata.st_ino,
    ) != expected_identity:
        raise HostingError(
            HostingFailureCategory.PREPARATION_STALE,
            "POSIX cwd directory identity changed",
        )


def _verify_static_elf(descriptor: int, *, size: int) -> None:
    header = os.pread(descriptor, min(size, 64), 0)
    if len(header) < 58 or header[:4] != b"\x7fELF":
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "POSIX static profile requires an ELF executable",
        )
    elf_class = header[4]
    byte_order = header[5]
    if elf_class != 2 or byte_order != 1:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "POSIX ELF header is unsupported",
        )
    endian = "<" if byte_order == 1 else ">"
    machine = struct.unpack_from(f"{endian}H", header, 18)[0]
    if machine != 62:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "POSIX static ELF does not match the running machine",
        )
    program_offset = struct.unpack_from(f"{endian}Q", header, 32)[0]
    entry_size = struct.unpack_from(f"{endian}H", header, 54)[0]
    entry_count = struct.unpack_from(f"{endian}H", header, 56)[0]
    if entry_size < 4 or entry_count < 1 or entry_count > 1024:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "POSIX ELF program-header table is invalid",
        )
    table_size = entry_size * entry_count
    if program_offset > size or table_size > size - program_offset:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "POSIX ELF program-header table is out of bounds",
        )
    table = os.pread(descriptor, table_size, program_offset)
    if len(table) != table_size:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "POSIX ELF program-header table is incomplete",
        )
    program_types = {
        struct.unpack_from(f"{endian}I", table, offset)[0]
        for offset in range(0, table_size, entry_size)
    }
    if _PT_INTERP in program_types or _PT_DYNAMIC in program_types:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "POSIX static profile rejects interpreter or dynamic-loader closure",
        )


def _descriptor_digest(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(_COPY_CHUNK_BYTES, size - offset), offset)
        if not chunk:
            break
        digest.update(chunk)
        offset += len(chunk)
    if offset != size:
        raise HostingError(
            HostingFailureCategory.PREPARATION_STALE,
            "POSIX sealed executable read was incomplete",
        )
    return digest.hexdigest()


def _write_all(descriptor: int, body: bytes) -> None:
    view = memoryview(body)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            raise OSError("POSIX executable capture made no forward progress")
        offset += written


def _required_seals() -> int:
    return _F_SEAL_SEAL | _F_SEAL_SHRINK | _F_SEAL_GROW | _F_SEAL_WRITE


def _close_local_descriptor(
    descriptor: int,
    *,
    primary: BaseException,
    role: str,
) -> None:
    if descriptor < 0:
        return
    try:
        os.close(descriptor)
    except BaseException as cleanup:
        primary.add_note(f"POSIX {role} cleanup also failed: {cleanup}")


def _ensure_preparation_descriptor(descriptor: int) -> int:
    if descriptor >= 3:
        try:
            os.set_inheritable(descriptor, False)
            return descriptor
        except BaseException as primary:
            try:
                os.close(descriptor)
            except BaseException as cleanup:
                primary.add_note(
                    f"POSIX descriptor normalization cleanup also failed: {cleanup}"
                )
            raise
    assert fcntl is not None
    try:
        duplicate = fcntl.fcntl(
            descriptor,
            getattr(fcntl, "F_DUPFD_CLOEXEC", 1030),
            3,
        )
    except BaseException as primary:
        _close_local_descriptor(
            descriptor,
            primary=primary,
            role="low descriptor after duplication failure",
        )
        raise
    try:
        os.close(descriptor)
        return duplicate
    except BaseException as primary:
        _close_local_descriptor(
            duplicate,
            primary=primary,
            role="duplicate descriptor",
        )
        raise


def _require_sha256(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"POSIX static {name} digest is invalid")


def _memfd_available() -> bool:
    if callable(getattr(os, "memfd_create", None)):
        return True
    return getattr(CDLL(None, use_errno=True), "memfd_create", None) is not None


def _create_memfd() -> int:
    native = getattr(os, "memfd_create", None)
    if callable(native):
        return native(
            "loushang-hosting-static-elf",
            _MFD_CLOEXEC | _MFD_ALLOW_SEALING,
        )
    libc = CDLL(None, use_errno=True)
    create = getattr(libc, "memfd_create", None)
    if create is None:
        raise HostingError(
            HostingFailureCategory.PLATFORM_UNSUPPORTED,
            "POSIX static launch preparation requires memfd_create",
        )
    create.argtypes = (c_char_p, c_uint)
    create.restype = c_int
    descriptor = create(
        b"loushang-hosting-static-elf",
        _MFD_CLOEXEC | _MFD_ALLOW_SEALING,
    )
    if descriptor < 0:
        error_number = get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return descriptor


__all__: list[str] = []
