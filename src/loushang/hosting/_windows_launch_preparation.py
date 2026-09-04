"""Private H6.3 Windows restricted-token launch preparation.

The profile is deliberately narrow: one locked AMD64 PE image whose declared
direct imports are a fixed platform-name allowlist, locked path ancestors for
the image and cwd, a Hosting-created restricted primary token, one kill-on-close
Job Object, and one non-inherited parent copy of the child's stderr NUL handle.
This is a direct-import mechanics profile, not a proof of the complete Windows
loader closure.  The material is attached before acquisition so every partial
native owner remains reachable through the Child Session reservation.
"""

from __future__ import annotations

import hashlib
import ntpath
import os
import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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
from ._win32_process import (
    _CtypesWin32Api,
    _Win32LockedPathIdentity,
)
from .contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
)
from .errors import HostingError, HostingFailureCategory

_PROFILE_ID = "windows-restricted-direct-import-pe-v1"
_RESTRICTION_ID = "restricted-token:disable-max-privilege-v1"
_DIRECT_PLATFORM_IMPORTS = frozenset({"ADVAPI32.DLL", "KERNEL32.DLL"})
_MAX_EXECUTABLE_BYTES = 64 * 1024 * 1024
_MAX_ANCESTOR_DIRECTORIES = 48
_PE_AMD64_MACHINE = 0x8664
_PE32_PLUS_MAGIC = 0x20B
_IMAGE_DIRECTORY_ENTRY_IMPORT = 1
_IMAGE_DIRECTORY_ENTRY_RESOURCE = 2
_IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT = 13
_IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR = 14
_MAX_IMPORTS = 256
_MAX_IMPORT_NAME_BYTES = 260


class _WindowsLaunchApi(Protocol):
    def platform_identity(self) -> str: ...

    def open_locked_file(
        self,
        path: str,
        *,
        on_acquired: Callable[[int], None],
    ) -> int: ...

    def open_locked_directory(
        self,
        path: str,
        *,
        on_acquired: Callable[[int], None],
    ) -> int: ...

    def locked_path_identity(self, handle: int) -> _Win32LockedPathIdentity: ...

    def open_process_token(self) -> int: ...

    def create_restricted_token(self, source_token: int) -> int: ...

    def create_managed_job(
        self,
        *,
        on_acquired: Callable[[int], None],
    ) -> int: ...

    def managed_job_is_kill_on_close(self, job: int) -> bool: ...

    def create_managed_stderr(self) -> int: ...

    def close_handle(self, handle: int) -> None: ...


@dataclass(frozen=True, slots=True)
class _WindowsRestrictedLaunchCaptureSpec(_LaunchCaptureSpec):
    """One caller-admitted Windows AMD64 direct-import profile."""

    executable_sha256: str
    executable_volume_serial: int
    executable_file_id: int
    cwd_volume_serial: int
    cwd_file_id: int
    platform_identity: str
    platform_imports: tuple[str, ...]

    def __post_init__(self) -> None:
        super(_WindowsRestrictedLaunchCaptureSpec, self).__post_init__()
        if self.profile_id != _PROFILE_ID:
            raise ValueError("Windows restricted launch profile_id is unsupported")
        _require_sha256(self.executable_sha256)
        for name, value, bits in (
            ("executable volume", self.executable_volume_serial, 64),
            ("executable file", self.executable_file_id, 128),
            ("cwd volume", self.cwd_volume_serial, 64),
            ("cwd file", self.cwd_file_id, 128),
        ):
            if type(value) is not int or value < 0 or value >= 1 << bits:
                raise ValueError(f"Windows restricted {name} identity is invalid")
        if self.executable_file_id == 0 or self.cwd_file_id == 0:
            raise ValueError("Windows restricted path identity is invalid")
        if (
            not isinstance(self.platform_identity, str)
            or not self.platform_identity.startswith("windows-amd64-")
            or "\0" in self.platform_identity
        ):
            raise ValueError("Windows restricted platform identity is invalid")
        if not ntpath.isabs(self.request.argv[0]) or not ntpath.isabs(
            self.request.cwd
        ):
            raise ValueError("Windows restricted launch paths must be absolute")
        if (
            len(self.request.effective_environment) != 1
            or self.request.effective_environment[0][0] != "SystemRoot"
            or not ntpath.isabs(self.request.effective_environment[0][1])
        ):
            raise ValueError(
                "Windows restricted launch requires one absolute SystemRoot"
            )
        system_root = self.request.effective_environment[0][1]
        if (
            self.request.streams.stdin is not ProcessStdinMode.CLOSED
            or self.request.streams.stdout is not ProcessStdoutMode.DISCARD
            or self.request.streams.stderr is not ProcessStderrMode.DISCARD
        ):
            raise ValueError(
                "Windows restricted launch requires inherited stdin/stdout and discarded stderr"
            )
        normalized_imports = tuple(sorted(set(self.platform_imports)))
        if (
            not normalized_imports
            or normalized_imports != self.platform_imports
            or not set(normalized_imports) <= _DIRECT_PLATFORM_IMPORTS
        ):
            raise ValueError("Windows restricted platform imports are not closed")
        expected_closure = (
            f"pe-amd64:sha256:{self.executable_sha256}",
            "executable:win32:"
            f"{self.executable_volume_serial}:{self.executable_file_id}",
            f"cwd:win32:{self.cwd_volume_serial}:{self.cwd_file_id}",
            _RESTRICTION_ID,
            f"environment:SystemRoot={system_root}",
            f"direct-imports:{','.join(normalized_imports)}",
            f"platform:{self.platform_identity}",
        )
        if self.execution_closure != expected_closure:
            raise ValueError("Windows restricted execution closure is inconsistent")


class _WindowsRestrictedLaunchCaptureBackend:
    """Exact Windows owner acquisition; selected only by trusted composition."""

    backend_id = "windows-job-v1"

    def __init__(self, *, api: _WindowsLaunchApi | None = None) -> None:
        if api is None and os.name != "nt":
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows restricted launch preparation is unavailable",
            )
        self._api = api or _CtypesWin32Api()
        self._platform_identity = self._api.platform_identity()

    async def capture(
        self,
        spec: _LaunchCaptureSpec,
        *,
        attempt_id: str,
        attempt_token: object,
        on_capture: Callable[[_CapturedLaunchMaterial], None],
    ) -> "_WindowsRestrictedLaunchMaterial":
        if type(spec) is not _WindowsRestrictedLaunchCaptureSpec:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows launch preparation requires the exact restricted profile",
            )
        if spec.platform_identity != self._platform_identity:
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows launch preparation platform identity changed",
            )
        material = _WindowsRestrictedLaunchMaterial(
            api=self._api,
            spec=spec,
            attempt_id=attempt_id,
            attempt_token=attempt_token,
        )
        if not callable(on_capture):
            raise TypeError("Windows launch capture callback is not callable")
        try:
            on_capture(material)
        except BaseException as primary:
            try:
                await material.close()
            except BaseException as cleanup:
                primary.add_note(
                    f"Windows empty material cleanup also failed: {cleanup}"
                )
                raise primary from cleanup
            raise
        material._capture()
        return material


class _WindowsRestrictedLaunchMaterial:
    """One attempt-bound Windows native owner set."""

    backend_id = "windows-job-v1"

    def __init__(
        self,
        *,
        api: _WindowsLaunchApi,
        spec: _WindowsRestrictedLaunchCaptureSpec,
        attempt_id: str,
        attempt_token: object,
    ) -> None:
        self._api = api
        self._spec = spec
        self._attempt_id = attempt_id
        self._attempt_token = attempt_token
        self._executable_handle = -1
        self._cwd_handle = -1
        self._source_token = -1
        self._restricted_token = -1
        self._job_handle = -1
        self._stderr_handle = -1
        self._ancestor_handles: list[int] = []
        self._ancestor_identities: list[_Win32LockedPathIdentity] = []
        self._executable_identity: _Win32LockedPathIdentity | None = None
        self._cwd_identity: _Win32LockedPathIdentity | None = None
        self._state = "capturing"
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
        # Admission happens when the empty material is attached, before any
        # native acquisition. Reserve the complete worst-case profile bound;
        # the count must never grow after admission.
        return 5 + _MAX_ANCESTOR_DIRECTORIES

    @property
    def executable_path(self) -> str:
        identity = self._executable_identity
        if identity is None:
            raise RuntimeError("Windows executable identity is unavailable")
        return identity.final_path

    @property
    def cwd_path(self) -> str:
        identity = self._cwd_identity
        if identity is None:
            raise RuntimeError("Windows cwd identity is unavailable")
        return identity.final_path

    def _capture(self) -> None:
        try:
            self._api.open_locked_file(
                self._spec.request.argv[0],
                on_acquired=lambda handle: self._adopt_handle(
                    "_executable_handle", handle
                ),
            )
            executable = self._api.locked_path_identity(self._executable_handle)
            self._api.open_locked_directory(
                self._spec.request.cwd,
                on_acquired=lambda handle: self._adopt_handle("_cwd_handle", handle),
            )
            cwd = self._api.locked_path_identity(self._cwd_handle)
            self._capture_ancestor_chain(executable.final_path, cwd.final_path)
            self._source_token = self._api.open_process_token()
            self._restricted_token = self._api.create_restricted_token(
                self._source_token
            )
            self._close_attribute("_source_token")
            self._api.create_managed_job(
                on_acquired=lambda handle: self._adopt_handle("_job_handle", handle)
            )
            self._stderr_handle = self._api.create_managed_stderr()
            self._verify_owned()
        except BaseException:
            with self._lock:
                self._state = "capture-failed"
            raise
        with self._lock:
            self._state = "captured"

    async def verify_current(self, request: ProcessLaunchRequest) -> None:
        if request != self._spec.request:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows restricted launch request changed before verification",
            )
        with self._lock:
            if self._state != "captured":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows restricted launch material cannot be verified",
                )
        self._verify_owned()
        with self._lock:
            if self._state != "captured":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows restricted launch verification lost ownership",
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
        from ._windows_process import _WindowsProcessBackend

        if type(backend) is not _WindowsProcessBackend:
            raise effect.not_created(
                HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "Windows restricted material received a mismatched backend",
                )
            )
        return await backend._spawn_static_prepared(
            self,
            request,
            effect=effect,
            on_spawn=on_spawn,
            inheritance=inheritance,
        )

    def _claim_handles(self) -> tuple[int, int, int, int, int]:
        with self._lock:
            if self._state != "verified":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows restricted material is not verified for spawn",
                )
            handles = (
                self._executable_handle,
                self._cwd_handle,
                self._restricted_token,
                self._job_handle,
                self._stderr_handle,
            )
            if any(handle <= 0 for handle in handles):
                raise HostingError(
                    HostingFailureCategory.PREPARATION_STALE,
                    "Windows restricted material lost a native owner",
                )
            self._state = "claimed"
            return handles

    def _mark_transferred(self) -> None:
        with self._lock:
            if self._state != "claimed":
                raise RuntimeError("Windows restricted transfer state is inconsistent")
            self._job_handle = -1
            self._stderr_handle = -1
            self._state = "transferred"

    async def close(self) -> None:
        failures: list[BaseException] = []
        for attribute in (
            "_stderr_handle",
            "_job_handle",
            "_restricted_token",
            "_source_token",
            "_cwd_handle",
            "_executable_handle",
        ):
            try:
                self._close_attribute(attribute)
            except BaseException as error:
                failures.append(error)
        for handle in tuple(reversed(self._ancestor_handles)):
            try:
                self._api.close_handle(handle)
            except BaseException as error:
                failures.append(error)
            else:
                self._ancestor_handles.remove(handle)
        with self._lock:
            remaining = any(
                getattr(self, attribute) > 0
                for attribute in (
                    "_stderr_handle",
                    "_job_handle",
                    "_restricted_token",
                    "_source_token",
                    "_cwd_handle",
                    "_executable_handle",
                )
            ) or bool(self._ancestor_handles)
            self._state = "close-failed" if remaining else "closed"
        if failures:
            raise BaseExceptionGroup(
                "Windows restricted launch handle cleanup failed",
                failures,
            )

    def _close_attribute(self, attribute: str) -> None:
        with self._lock:
            handle = getattr(self, attribute)
        if handle <= 0:
            return
        self._api.close_handle(handle)
        with self._lock:
            if getattr(self, attribute) == handle:
                setattr(self, attribute, -1)

    def _adopt_handle(self, attribute: str, handle: int) -> None:
        if type(handle) is not int or handle <= 0:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows launch helper returned an invalid native owner",
            )
        with self._lock:
            if getattr(self, attribute) > 0:
                raise RuntimeError("Windows launch native owner attached twice")
            setattr(self, attribute, handle)

    def _adopt_ancestor(self, handle: int) -> None:
        if type(handle) is not int or handle <= 0:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows ancestor helper returned an invalid native owner",
            )
        self._ancestor_handles.append(handle)

    def _capture_ancestor_chain(self, *final_paths: str) -> None:
        paths: dict[str, str] = {}
        for final_path in final_paths:
            for ancestor in _ancestor_directory_paths(final_path):
                paths.setdefault(ntpath.normcase(ancestor), ancestor)
        if len(paths) > _MAX_ANCESTOR_DIRECTORIES:
            raise HostingError(
                HostingFailureCategory.CAPACITY_EXHAUSTED,
                "Windows managed launch ancestor chain exceeds its bound",
            )
        for ancestor in paths.values():
            self._api.open_locked_directory(
                ancestor,
                on_acquired=self._adopt_ancestor,
            )
            self._ancestor_identities.append(
                self._api.locked_path_identity(self._ancestor_handles[-1])
            )

    def _verify_owned(self) -> None:
        executable = self._api.locked_path_identity(self._executable_handle)
        cwd = self._api.locked_path_identity(self._cwd_handle)
        if executable.is_directory or (
            executable.volume_serial,
            executable.file_id,
        ) != (
            self._spec.executable_volume_serial,
            self._spec.executable_file_id,
        ):
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows executable identity changed",
            )
        if executable.size < 1 or executable.size > _MAX_EXECUTABLE_BYTES:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows executable is not a bounded file",
            )
        if not cwd.is_directory or (cwd.volume_serial, cwd.file_id) != (
            self._spec.cwd_volume_serial,
            self._spec.cwd_file_id,
        ):
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows cwd identity changed",
            )
        if len(self._ancestor_handles) != len(self._ancestor_identities):
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows ancestor ownership is incomplete",
            )
        for handle, expected in zip(
            self._ancestor_handles,
            self._ancestor_identities,
            strict=True,
        ):
            current = self._api.locked_path_identity(handle)
            if not current.is_directory or current != expected:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_STALE,
                    "Windows ancestor identity changed",
                )
        expected_ancestor_paths = {
            ntpath.normcase(path)
            for final_path in (executable.final_path, cwd.final_path)
            for path in _ancestor_directory_paths(final_path)
        }
        retained_ancestor_paths = {
            ntpath.normcase(identity.final_path)
            for identity in self._ancestor_identities
        }
        if retained_ancestor_paths != expected_ancestor_paths:
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows retained ancestor chain no longer closes the launch paths",
            )
        _verify_pe_image(
            Path(executable.final_path),
            expected_digest=self._spec.executable_sha256,
            expected_imports=self._spec.platform_imports,
        )
        if not self._api.managed_job_is_kill_on_close(self._job_handle):
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows managed Job Object lost kill-on-close",
            )
        self._executable_identity = executable
        self._cwd_identity = cwd


def _verify_pe_image(
    path: Path,
    *,
    expected_digest: str,
    expected_imports: tuple[str, ...],
) -> None:
    body = path.read_bytes()
    if (
        len(body) < 0x40
        or len(body) > _MAX_EXECUTABLE_BYTES
        or hashlib.sha256(body).hexdigest() != expected_digest
    ):
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE image digest or bound changed",
        )
    pe_offset = _unpack_from("<I", body, 0x3C)
    if pe_offset > len(body) - 24 or body[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows restricted profile requires a PE image",
        )
    machine, section_count = struct.unpack_from("<HH", body, pe_offset + 4)
    optional_size = _unpack_from("<H", body, pe_offset + 20)
    optional = pe_offset + 24
    if (
        machine != _PE_AMD64_MACHINE
        or section_count < 1
        or section_count > 96
        or optional_size < 128
        or optional > len(body) - optional_size
        or _unpack_from("<H", body, optional) != _PE32_PLUS_MAGIC
    ):
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE image is not a bounded AMD64 image",
        )
    directory_count = _unpack_from("<I", body, optional + 108)
    if directory_count <= _IMAGE_DIRECTORY_ENTRY_IMPORT:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE image has no import closure",
        )
    for directory in (
        _IMAGE_DIRECTORY_ENTRY_RESOURCE,
        _IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT,
        _IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR,
    ):
        if directory_count > directory:
            if optional_size < 112 + (directory + 1) * 8:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows PE data-directory table is truncated",
                )
            rva, size = struct.unpack_from("<II", body, optional + 112 + directory * 8)
            if rva != 0 or size != 0:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows direct-import profile rejects resources, delayed loading, or managed loading",
                )
    import_rva, import_size = struct.unpack_from("<II", body, optional + 120)
    if import_rva == 0 or import_size < 20:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE import directory is invalid",
        )
    sections = _pe_sections(body, optional + optional_size, section_count)
    import_offset = _rva_offset(body, import_rva, optional, sections)
    imports: set[str] = set()
    descriptor_count = min(_MAX_IMPORTS, import_size // 20)
    for index in range(descriptor_count):
        descriptor = import_offset + index * 20
        if descriptor > len(body) - 20:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows PE import table is truncated",
            )
        values = struct.unpack_from("<IIIII", body, descriptor)
        if values == (0, 0, 0, 0, 0):
            break
        name_rva = values[3]
        name_offset = _rva_offset(body, name_rva, optional, sections)
        imports.add(_read_import_name(body, name_offset))
    else:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE import table has no in-range terminator",
        )
    if tuple(sorted(imports)) != expected_imports:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE platform-image import closure changed",
        )


def _ancestor_directory_paths(final_path: str) -> tuple[str, ...]:
    normalized = ntpath.normpath(final_path)
    drive, tail = ntpath.splitdrive(normalized)
    if not drive or not tail.startswith("\\") or drive.upper().startswith("\\\\?\\UNC\\"):
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows managed launch requires a local absolute volume path",
        )
    root = f"{drive}\\"
    current = ntpath.dirname(normalized)
    ancestors: list[str] = []
    while current and ntpath.normcase(current) != ntpath.normcase(root):
        ancestors.append(current)
        parent = ntpath.dirname(current)
        if parent == current:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows managed launch ancestor chain is malformed",
            )
        current = parent
    if not current:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows managed launch ancestor chain has no volume root",
        )
    return tuple(ancestors)


def _pe_sections(
    body: bytes,
    section_offset: int,
    section_count: int,
) -> tuple[tuple[int, int, int, int], ...]:
    table_size = section_count * 40
    if section_offset > len(body) - table_size:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE section table is truncated",
        )
    sections: list[tuple[int, int, int, int]] = []
    for index in range(section_count):
        offset = section_offset + index * 40
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", body, offset + 8
        )
        if raw_offset > len(body) or raw_size > len(body) - raw_offset:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows PE section range is invalid",
            )
        for existing_virtual, existing_size, existing_raw, existing_raw_size in sections:
            if _ranges_overlap(
                virtual_address,
                max(virtual_size, raw_size),
                existing_virtual,
                max(existing_size, existing_raw_size),
            ) or _ranges_overlap(raw_offset, raw_size, existing_raw, existing_raw_size):
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows PE section ranges overlap",
                )
        sections.append((virtual_address, virtual_size, raw_offset, raw_size))
    return tuple(sections)


def _ranges_overlap(left: int, left_size: int, right: int, right_size: int) -> bool:
    if left_size == 0 or right_size == 0:
        return False
    return left < right + right_size and right < left + left_size


def _rva_offset(
    body: bytes,
    rva: int,
    optional_offset: int,
    sections: tuple[tuple[int, int, int, int], ...],
) -> int:
    header_size = _unpack_from("<I", body, optional_offset + 60)
    if rva < header_size and rva < len(body):
        return rva
    for virtual_address, virtual_size, raw_offset, raw_size in sections:
        span = max(virtual_size, raw_size)
        if virtual_address <= rva < virtual_address + span:
            delta = rva - virtual_address
            if delta >= raw_size or raw_offset + delta >= len(body):
                break
            return raw_offset + delta
    raise HostingError(
        HostingFailureCategory.PREPARATION_FAILED,
        "Windows PE RVA is outside the captured image",
    )


def _read_import_name(body: bytes, offset: int) -> str:
    end = body.find(b"\0", offset, min(len(body), offset + _MAX_IMPORT_NAME_BYTES))
    if end < 0:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE import name is unterminated",
        )
    try:
        name = body[offset:end].decode("ascii").upper()
    except UnicodeDecodeError as error:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE import name is not ASCII",
        ) from error
    if not name or "\\" in name or "/" in name or "\0" in name:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE import name is invalid",
        )
    return name


def _unpack_from(format_string: str, body: bytes, offset: int) -> int:
    size = struct.calcsize(format_string)
    if offset < 0 or offset > len(body) - size:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows PE image metadata is truncated",
        )
    value = struct.unpack_from(format_string, body, offset)[0]
    if not isinstance(value, int):
        raise TypeError("Windows PE integer field is invalid")
    return value


def _require_sha256(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("Windows restricted executable digest is invalid")


__all__: list[str] = []
