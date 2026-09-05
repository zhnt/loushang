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
import json
import ntpath
import os
import stat
import struct
import threading
from collections.abc import Callable
from contextlib import suppress
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
    _FILE_TRAVERSE_READ,
    _SUB_CONTAINERS_AND_OBJECTS_INHERIT,
    _CtypesWin32Api,
    _Win32LockedPathIdentity,
    _Win32LpacProfile,
    _Win32ProfileAlreadyExists,
    _Win32ProfileNotFound,
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
_LPAC_PROFILE_ID = "windows-lpac-contained-pe-v1"
_LPAC_PLATFORM_IMPORTS = frozenset({"ADVAPI32.DLL", "KERNEL32.DLL", "WS2_32.DLL"})
_MAX_LPAC_RUNTIME_ENTRIES = 64
_MAX_LPAC_RUNTIME_BYTES = 64 * 1024 * 1024
_MAX_LPAC_ATTEMPT_ID = 96
_LPAC_PROFILE_PREFIX = "Loushang.Lpac."
# File-object-specific expansion of GENERIC_READ | GENERIC_EXECUTE. Generic
# inheritable rights make SetEntriesInAcl split one grant into an effective ACE
# plus an INHERIT_ONLY ACE, so use the stable native mask we can verify exactly.
_LPAC_RUNTIME_ACCESS = 0x001200A9
# Read/write/delete within the attempt-private scratch tree, without ownership
# or DACL mutation rights.  The Package SID also receives a separate
# non-inheriting traverse grant on the platform-owned private root.
_LPAC_PRIVATE_SCRATCH_ACCESS = 0x001301FF
_LPAC_ROOT_ACE_FLAGS = _SUB_CONTAINERS_AND_OBJECTS_INHERIT
_LPAC_WITNESS_STATES = frozenset(
    {
        "PROFILE_CREATED",
        "GRANTS_APPLIED",
        "VERIFIED",
        "ACTIVE",
        "CLEANING",
        "GRANTS_REVOKED",
        "PROFILE_DELETED",
        "SETTLED",
        "DEBT",
    }
)


class _WindowsLaunchApi(Protocol):
    def platform_identity(self) -> str: ...

    def canonical_system_root(self) -> str: ...

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


class _WindowsLpacApi(_WindowsLaunchApi, Protocol):
    def locked_file_sha256(self, handle: int) -> str: ...

    def create_lpac_profile(
        self,
        profile_name: str,
        *,
        on_acquired: Callable[[_Win32LpacProfile], None],
    ) -> _Win32LpacProfile: ...

    def derive_lpac_profile(self, profile_name: str) -> _Win32LpacProfile: ...

    def delete_lpac_profile(self, profile_name: str) -> None: ...

    def free_sid(self, sid: int) -> None: ...

    def grant_lpac_path(
        self,
        path: str,
        sid: int,
        *,
        permissions: int,
        inherit: bool,
    ) -> None: ...

    def revoke_lpac_path(self, path: str, sid: int) -> None: ...

    def lpac_path_access(
        self,
        path: str,
        sid: int,
    ) -> tuple[tuple[int, int], ...]: ...

    def file_stream_names(self, path: str) -> tuple[str, ...]: ...

    def ensure_lpac_private_scratch(self, private_root: str) -> None: ...

    def purge_lpac_private_state(self, private_root: str) -> None: ...


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
        if not ntpath.isabs(self.request.argv[0]) or not ntpath.isabs(self.request.cwd):
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
                "Windows restricted launch requires closed stdin and discarded output"
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


def _build_windows_restricted_launch_capture_spec(
    request: ProcessLaunchRequest,
    *,
    executable_sha256: str,
    _api: _WindowsLaunchApi | None = None,
) -> _WindowsRestrictedLaunchCaptureSpec:
    """Build one opaque trusted-payload spec from OS-owned Windows facts.

    The identities captured here are admission snapshots, not process authority.
    The capture backend reacquires and retains the native owners before spawn.
    """

    if request.effective_environment:
        raise HostingError(
            HostingFailureCategory.PREPARATION_REJECTED,
            "Windows restricted profile rejects caller environment",
        )
    if (
        request.streams.stdin is not ProcessStdinMode.CLOSED
        or request.streams.stdout is not ProcessStdoutMode.DISCARD
        or request.streams.stderr is not ProcessStderrMode.DISCARD
    ):
        raise HostingError(
            HostingFailureCategory.PREPARATION_REJECTED,
            "Windows restricted profile requires closed stdin and discarded output",
        )
    try:
        _require_sha256(executable_sha256)
    except ValueError as error:
        raise HostingError(
            HostingFailureCategory.PREPARATION_REJECTED,
            "Windows restricted profile executable digest is invalid",
        ) from error
    try:
        api = _api or _CtypesWin32Api()
        system_root = _canonical_system_root(api.canonical_system_root())
        platform_identity = api.platform_identity()
        executable = _snapshot_locked_identity(
            api,
            request.argv[0],
            directory=False,
        )
        cwd = _snapshot_locked_identity(api, request.cwd, directory=True)
        if executable.is_directory or not cwd.is_directory:
            raise ValueError("locked path kind is invalid")
        if executable.size < 1 or executable.size > _MAX_EXECUTABLE_BYTES:
            raise ValueError("locked executable bound is invalid")
        trusted_request = ProcessLaunchRequest(
            argv=request.argv,
            cwd=request.cwd,
            effective_environment=(("SystemRoot", system_root),),
            streams=request.streams,
        )
        imports = tuple(sorted(_DIRECT_PLATFORM_IMPORTS))
        execution_closure = (
            f"pe-amd64:sha256:{executable_sha256}",
            f"executable:win32:{executable.volume_serial}:{executable.file_id}",
            f"cwd:win32:{cwd.volume_serial}:{cwd.file_id}",
            _RESTRICTION_ID,
            f"environment:SystemRoot={system_root}",
            f"direct-imports:{','.join(imports)}",
            f"platform:{platform_identity}",
        )
        return _WindowsRestrictedLaunchCaptureSpec(
            request=trusted_request,
            profile_id=_PROFILE_ID,
            execution_closure=execution_closure,
            executable_sha256=executable_sha256,
            executable_volume_serial=executable.volume_serial,
            executable_file_id=executable.file_id,
            cwd_volume_serial=cwd.volume_serial,
            cwd_file_id=cwd.file_id,
            platform_identity=platform_identity,
            platform_imports=imports,
        )
    except HostingError as error:
        if error.category is HostingFailureCategory.PLATFORM_UNSUPPORTED:
            raise
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows restricted profile construction failed",
        ) from error
    except Exception as error:
        raise HostingError(
            HostingFailureCategory.PREPARATION_FAILED,
            "Windows restricted profile construction failed",
        ) from error


def _canonical_system_root(value: object) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError("Windows directory is invalid")
    normalized = ntpath.normpath(value)
    drive, tail = ntpath.splitdrive(normalized)
    if (
        normalized != value
        or len(drive) != 2
        or drive[1:] != ":"
        or not tail.startswith("\\")
        or not ntpath.isabs(normalized)
    ):
        raise ValueError("Windows directory is not canonical")
    return normalized


def _snapshot_locked_identity(
    api: _WindowsLaunchApi,
    path: str,
    *,
    directory: bool,
) -> _Win32LockedPathIdentity:
    handles: list[int] = []

    def adopt(handle: int) -> None:
        if type(handle) is not int or handle <= 0 or handles:
            raise ValueError("Windows profile builder received an invalid owner")
        handles.append(handle)

    try:
        if directory:
            api.open_locked_directory(path, on_acquired=adopt)
        else:
            api.open_locked_file(path, on_acquired=adopt)
        if len(handles) != 1:
            raise ValueError("Windows profile builder did not receive one owner")
        return api.locked_path_identity(handles[0])
    finally:
        for handle in tuple(reversed(handles)):
            api.close_handle(handle)


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


@dataclass(frozen=True, slots=True)
class _WindowsLpacRuntimeEntry:
    """One exact member of the dedicated immutable Worker runtime closure."""

    relative_path: str
    volume_serial: int
    file_id: int
    size: int
    is_directory: bool
    sha256: str | None

    def __post_init__(self) -> None:
        relative = self.relative_path
        if (
            not isinstance(relative, str)
            or not relative
            or "\0" in relative
            or ntpath.isabs(relative)
            or ntpath.normpath(relative) != relative
            or relative.startswith("..")
            or ":" in relative
        ):
            raise ValueError("Windows LPAC runtime relative path is invalid")
        if self.volume_serial < 0 or self.file_id <= 0 or self.size < 0:
            raise ValueError("Windows LPAC runtime identity is invalid")
        if self.is_directory:
            if self.sha256 is not None or self.size != 0:
                raise ValueError("Windows LPAC directory identity is invalid")
        else:
            _require_sha256(self.sha256)


@dataclass(frozen=True, slots=True)
class _WindowsLpacProvisionSpec:
    """Caller-owned durable intent for one fresh attempt-scoped profile."""

    request: ProcessLaunchRequest
    runtime_root: str
    runtime_entries: tuple[_WindowsLpacRuntimeEntry, ...]
    executable_relative_path: str
    cwd_relative_path: str
    platform_imports: tuple[str, ...]
    platform_identity: str
    attempt_id: str
    operation_nonce: str
    lifecycle_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.request, ProcessLaunchRequest):
            raise TypeError("Windows LPAC provision request is invalid")
        if self.request.effective_environment:
            raise ValueError("Windows LPAC provision request must have no environment")
        if (
            self.request.streams.stdin is not ProcessStdinMode.CLOSED
            or self.request.streams.stdout is not ProcessStdoutMode.DISCARD
            or self.request.streams.stderr is not ProcessStderrMode.DISCARD
        ):
            raise ValueError("Windows LPAC provision request has unsupported streams")
        _require_local_windows_path(self.runtime_root, "runtime root")
        entries = tuple(self.runtime_entries)
        if (
            not entries
            or len(entries) > _MAX_LPAC_RUNTIME_ENTRIES
            or entries[0].relative_path != "."
            or not entries[0].is_directory
        ):
            raise ValueError("Windows LPAC runtime closure is invalid")
        paths = tuple(entry.relative_path for entry in entries)
        if paths != tuple(sorted(paths, key=str.casefold)) or len(
            {path.casefold() for path in paths}
        ) != len(paths):
            raise ValueError("Windows LPAC runtime closure order is invalid")
        total_bytes = sum(entry.size for entry in entries if not entry.is_directory)
        if total_bytes < 1 or total_bytes > _MAX_LPAC_RUNTIME_BYTES:
            raise ValueError("Windows LPAC runtime closure size is invalid")
        by_path = {entry.relative_path: entry for entry in entries}
        executable = by_path.get(self.executable_relative_path)
        cwd = by_path.get(self.cwd_relative_path)
        if (
            executable is None
            or executable.is_directory
            or cwd is None
            or not cwd.is_directory
        ):
            raise ValueError("Windows LPAC executable or cwd is outside its closure")
        if (
            _relative_lpac_path(self.runtime_root, self.request.argv[0])
            != self.executable_relative_path
        ):
            raise ValueError("Windows LPAC executable path is inconsistent")
        if (
            _relative_lpac_path(self.runtime_root, self.request.cwd)
            != self.cwd_relative_path
        ):
            raise ValueError("Windows LPAC cwd path is inconsistent")
        imports = tuple(sorted(set(self.platform_imports)))
        if (
            not imports
            or imports != self.platform_imports
            or not set(imports) <= _LPAC_PLATFORM_IMPORTS
        ):
            raise ValueError("Windows LPAC platform imports are not closed")
        if (
            not isinstance(self.platform_identity, str)
            or not self.platform_identity.startswith("windows-amd64-")
            or "\0" in self.platform_identity
        ):
            raise ValueError("Windows LPAC platform identity is invalid")
        if (
            not isinstance(self.attempt_id, str)
            or not self.attempt_id
            or len(self.attempt_id) > _MAX_LPAC_ATTEMPT_ID
            or self.attempt_id != self.attempt_id.strip()
            or "\0" in self.attempt_id
        ):
            raise ValueError("Windows LPAC attempt identity is invalid")
        _require_sha256(self.operation_nonce)
        _require_sha256(self.lifecycle_fingerprint)
        object.__setattr__(self, "runtime_entries", entries)


@dataclass(frozen=True, slots=True)
class _WindowsLpacProvisionWitness:
    """Pathless durable observation for one native containment transition."""

    state: str
    attempt_id: str
    operation_nonce: str
    spec_fingerprint: str
    profile_fingerprint: str
    sid_fingerprint: str
    private_state_fingerprint: str
    grant_digest: str
    platform_identity: str

    def __post_init__(self) -> None:
        if self.state not in _LPAC_WITNESS_STATES:
            raise ValueError("Windows LPAC witness state is invalid")
        if not self.attempt_id or "\0" in self.attempt_id:
            raise ValueError("Windows LPAC witness attempt identity is invalid")
        for value in (
            self.operation_nonce,
            self.spec_fingerprint,
            self.profile_fingerprint,
            self.sid_fingerprint,
            self.private_state_fingerprint,
            self.grant_digest,
        ):
            _require_sha256(value)
        if not self.platform_identity.startswith("windows-amd64-"):
            raise ValueError("Windows LPAC witness platform identity is invalid")


class _WindowsLpacProfileCollision(HostingError):
    """A create call conclusively observed a foreign pre-existing moniker."""

    def __init__(self) -> None:
        super().__init__(
            HostingFailureCategory.PREPARATION_STALE,
            "Windows LPAC profile name is already owned",
        )


def _build_windows_lpac_provision_spec(
    request: ProcessLaunchRequest,
    *,
    runtime_root: str,
    platform_imports: tuple[str, ...],
    attempt_id: str,
    operation_nonce: str,
    lifecycle_fingerprint: str,
    _api: _WindowsLpacApi | None = None,
) -> _WindowsLpacProvisionSpec:
    if request.effective_environment:
        raise HostingError(
            HostingFailureCategory.PREPARATION_REJECTED,
            "Windows LPAC profile rejects caller environment",
        )
    try:
        api = _api or _CtypesWin32Api()
        entries = _snapshot_lpac_runtime(api, runtime_root)
        executable_relative = _relative_lpac_path(runtime_root, request.argv[0])
        cwd_relative = _relative_lpac_path(runtime_root, request.cwd)
        spec = _WindowsLpacProvisionSpec(
            request=request,
            runtime_root=runtime_root,
            runtime_entries=entries,
            executable_relative_path=executable_relative,
            cwd_relative_path=cwd_relative,
            platform_imports=tuple(sorted(set(platform_imports))),
            platform_identity=api.platform_identity(),
            attempt_id=attempt_id,
            operation_nonce=operation_nonce,
            lifecycle_fingerprint=lifecycle_fingerprint,
        )
        executable = next(
            entry for entry in entries if entry.relative_path == executable_relative
        )
        assert executable.sha256 is not None
        _verify_pe_image(
            Path(request.argv[0]),
            expected_digest=executable.sha256,
            expected_imports=spec.platform_imports,
        )
        return spec
    except HostingError:
        raise
    except (OSError, RuntimeError, StopIteration, ValueError) as error:
        raise HostingError(
            HostingFailureCategory.PREPARATION_REJECTED,
            "Windows LPAC runtime closure admission failed",
        ) from error


class _WindowsLpacProvisioner:
    """Synchronous native participant; the future Product owns its journal."""

    def __init__(self, *, api: _WindowsLpacApi | None = None) -> None:
        if api is None and os.name != "nt":
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows LPAC provisioning is unavailable",
            )
        self._api = api or _CtypesWin32Api()
        self._platform_identity = self._api.platform_identity()
        self._lock = threading.Lock()

    def create_profile(
        self,
        spec: _WindowsLpacProvisionSpec,
        *,
        begin_effect: Callable[[], None],
    ) -> _WindowsLpacProvisionWitness:
        self._validate_spec(spec)
        _require_effect_callback(begin_effect)
        with self._lock:
            profile_owner: list[_Win32LpacProfile] = []
            try:
                begin_effect()
                profile = self._api.create_lpac_profile(
                    _lpac_profile_name(spec),
                    on_acquired=profile_owner.append,
                )
                if profile_owner != [profile]:
                    raise RuntimeError("Windows LPAC profile owner attachment failed")
                self._api.ensure_lpac_private_scratch(profile.private_root)
                return self._witness(spec, profile, state="PROFILE_CREATED")
            except _Win32ProfileAlreadyExists as error:
                # The OS conclusively reports that this call created nothing.
                # Product must record a collision and must not synthesize a
                # cleanup witness for the foreign profile.
                raise _WindowsLpacProfileCollision() from error
            except HostingError:
                raise
            except BaseException as error:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows LPAC profile creation failed after its effect gate",
                ) from error
            finally:
                for profile in profile_owner:
                    self._api.free_sid(profile.sid)

    def apply_grants(
        self,
        spec: _WindowsLpacProvisionSpec,
        witness: _WindowsLpacProvisionWitness,
        *,
        begin_effect: Callable[[], None],
    ) -> _WindowsLpacProvisionWitness:
        self._validate_witness(spec, witness, {"PROFILE_CREATED"})
        _require_effect_callback(begin_effect)
        with self._lock:
            profile = self._derive_checked_profile(spec, witness)
            try:
                self._verify_private_identity(witness, profile)
                targets = _lpac_grant_targets(spec) + _lpac_private_grant_targets(
                    profile.private_root
                )
                if any(
                    self._api.lpac_path_access(path, profile.sid)
                    for path, _, _ in targets
                ):
                    raise HostingError(
                        HostingFailureCategory.PREPARATION_STALE,
                        "Windows LPAC grant target already has Package SID authority",
                    )
                begin_effect()
                self._api.ensure_lpac_private_scratch(profile.private_root)
                for path, permissions, inherit in targets:
                    self._api.grant_lpac_path(
                        path,
                        profile.sid,
                        permissions=permissions,
                        inherit=inherit,
                    )
                return self._witness(spec, profile, state="GRANTS_APPLIED")
            except HostingError:
                raise
            except BaseException as error:
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows LPAC grant mutation failed after its effect gate",
                ) from error
            finally:
                self._api.free_sid(profile.sid)

    def verify(
        self,
        spec: _WindowsLpacProvisionSpec,
        witness: _WindowsLpacProvisionWitness,
    ) -> _WindowsLpacProvisionWitness:
        self._validate_witness(spec, witness, {"GRANTS_APPLIED", "VERIFIED"})
        with self._lock:
            profile = self._derive_checked_profile(spec, witness)
            try:
                self._verify_private_identity(witness, profile)
                _verify_lpac_runtime(self._api, spec)
                _verify_lpac_grants(
                    self._api,
                    spec,
                    profile.private_root,
                    profile.sid,
                    present=True,
                )
                return self._witness(spec, profile, state="VERIFIED")
            finally:
                self._api.free_sid(profile.sid)

    def revoke_grants(
        self,
        spec: _WindowsLpacProvisionSpec,
        witness: _WindowsLpacProvisionWitness,
        *,
        begin_effect: Callable[[], None],
    ) -> _WindowsLpacProvisionWitness:
        self._validate_witness(
            spec,
            witness,
            {"GRANTS_APPLIED", "VERIFIED", "ACTIVE", "CLEANING", "DEBT"},
        )
        _require_effect_callback(begin_effect)
        with self._lock:
            profile = self._derive_checked_profile(spec, witness)
            try:
                targets = _lpac_grant_targets(spec) + _lpac_private_grant_targets(
                    profile.private_root
                )
                for path, permissions, inherit in targets:
                    matches = self._api.lpac_path_access(path, profile.sid)
                    expected = ((permissions, _LPAC_ROOT_ACE_FLAGS if inherit else 0),)
                    if matches not in {(), expected}:
                        raise HostingError(
                            HostingFailureCategory.PREPARATION_STALE,
                            "Windows LPAC grant cannot be safely reconciled",
                        )
                begin_effect()
                for path, _, _ in reversed(targets):
                    if self._api.lpac_path_access(path, profile.sid):
                        self._api.revoke_lpac_path(path, profile.sid)
                _verify_lpac_grants(
                    self._api,
                    spec,
                    profile.private_root,
                    profile.sid,
                    present=False,
                )
                # Preserve the durable identity witness. Recovery may begin
                # after profile creation but before Hosting returned the
                # profile-root identity to Product; cleanup does not need to
                # reopen that directory to prove the exact SID ACLs are absent.
                return _replace_lpac_witness_state(witness, "GRANTS_REVOKED")
            except HostingError:
                raise
            except BaseException as error:
                raise HostingError(
                    HostingFailureCategory.CLEANUP_FAILED,
                    "Windows LPAC grant cleanup remains unsettled",
                ) from error
            finally:
                self._api.free_sid(profile.sid)

    def delete_profile(
        self,
        spec: _WindowsLpacProvisionSpec,
        witness: _WindowsLpacProvisionWitness,
        *,
        begin_effect: Callable[[], None],
    ) -> _WindowsLpacProvisionWitness:
        self._validate_witness(
            spec,
            witness,
            {"PROFILE_CREATED", "GRANTS_REVOKED", "PROFILE_DELETED", "DEBT"},
        )
        _require_effect_callback(begin_effect)
        with self._lock:
            profile = self._derive_checked_profile(spec, witness)
            try:
                begin_effect()
                self._api.purge_lpac_private_state(profile.private_root)
                with suppress(_Win32ProfileNotFound):
                    self._api.delete_lpac_profile(_lpac_profile_name(spec))
                return _replace_lpac_witness_state(witness, "PROFILE_DELETED")
            except HostingError:
                raise
            except BaseException as error:
                raise HostingError(
                    HostingFailureCategory.CLEANUP_FAILED,
                    "Windows LPAC profile cleanup remains unsettled",
                ) from error
            finally:
                self._api.free_sid(profile.sid)

    def settle(
        self,
        spec: _WindowsLpacProvisionSpec,
        witness: _WindowsLpacProvisionWitness,
    ) -> _WindowsLpacProvisionWitness:
        self._validate_witness(spec, witness, {"PROFILE_DELETED", "SETTLED"})
        return _replace_lpac_witness_state(witness, "SETTLED")

    def mark_debt(
        self,
        spec: _WindowsLpacProvisionSpec,
        witness: _WindowsLpacProvisionWitness,
    ) -> _WindowsLpacProvisionWitness:
        self._validate_witness(spec, witness, _LPAC_WITNESS_STATES - {"SETTLED"})
        return _replace_lpac_witness_state(witness, "DEBT")

    def recover_cleanup_witness(
        self,
        spec: _WindowsLpacProvisionSpec,
    ) -> _WindowsLpacProvisionWitness:
        """Reconstruct cleanup-only authority from caller-owned durable intent.

        Win32 exposes deterministic AppContainer SID derivation, but no public
        read-only query that proves an arbitrary profile moniker is registered.
        Consequently this method never authorizes launch or grant creation. It
        only creates a DEBT witness accepted by exact revoke/delete transitions.
        """

        self._validate_spec(spec)
        with self._lock:
            profile = self._api.derive_lpac_profile(_lpac_profile_name(spec))
            try:
                return _WindowsLpacProvisionWitness(
                    state="DEBT",
                    attempt_id=spec.attempt_id,
                    operation_nonce=spec.operation_nonce,
                    spec_fingerprint=_lpac_spec_fingerprint(spec),
                    profile_fingerprint=_lpac_profile_fingerprint(spec),
                    sid_fingerprint=_fingerprint(profile.sid_text),
                    private_state_fingerprint=_fingerprint(
                        f"cleanup-only:{ntpath.normcase(profile.private_root)}"
                    ),
                    grant_digest=_lpac_grant_digest(spec),
                    platform_identity=spec.platform_identity,
                )
            finally:
                self._api.free_sid(profile.sid)

    def _validate_spec(self, spec: _WindowsLpacProvisionSpec) -> None:
        if type(spec) is not _WindowsLpacProvisionSpec:
            raise TypeError("Windows LPAC provisioning requires the exact spec")
        if spec.platform_identity != self._platform_identity:
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows LPAC provisioning platform identity changed",
            )

    def _validate_witness(
        self,
        spec: _WindowsLpacProvisionSpec,
        witness: _WindowsLpacProvisionWitness,
        allowed_states: set[str] | frozenset[str],
    ) -> None:
        self._validate_spec(spec)
        if type(witness) is not _WindowsLpacProvisionWitness:
            raise TypeError("Windows LPAC provisioning requires the exact witness")
        if (
            witness.state not in allowed_states
            or witness.attempt_id != spec.attempt_id
            or witness.operation_nonce != spec.operation_nonce
            or witness.spec_fingerprint != _lpac_spec_fingerprint(spec)
            or witness.profile_fingerprint != _lpac_profile_fingerprint(spec)
            or witness.grant_digest != _lpac_grant_digest(spec)
            or witness.platform_identity != spec.platform_identity
        ):
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows LPAC provisioning witness does not match the attempt",
            )

    def _derive_checked_profile(
        self,
        spec: _WindowsLpacProvisionSpec,
        witness: _WindowsLpacProvisionWitness,
    ) -> _Win32LpacProfile:
        profile = self._api.derive_lpac_profile(_lpac_profile_name(spec))
        if _fingerprint(profile.sid_text) != witness.sid_fingerprint:
            self._api.free_sid(profile.sid)
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows LPAC Package SID changed",
            )
        return profile

    def _verify_private_identity(
        self,
        witness: _WindowsLpacProvisionWitness,
        profile: _Win32LpacProfile,
    ) -> None:
        if (
            _private_state_fingerprint(self._api, profile.private_root)
            != witness.private_state_fingerprint
        ):
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows LPAC private state identity changed",
            )

    def _witness(
        self,
        spec: _WindowsLpacProvisionSpec,
        profile: _Win32LpacProfile,
        *,
        state: str,
    ) -> _WindowsLpacProvisionWitness:
        return _WindowsLpacProvisionWitness(
            state=state,
            attempt_id=spec.attempt_id,
            operation_nonce=spec.operation_nonce,
            spec_fingerprint=_lpac_spec_fingerprint(spec),
            profile_fingerprint=_lpac_profile_fingerprint(spec),
            sid_fingerprint=_fingerprint(profile.sid_text),
            private_state_fingerprint=_private_state_fingerprint(
                self._api,
                profile.private_root,
            ),
            grant_digest=_lpac_grant_digest(spec),
            platform_identity=spec.platform_identity,
        )


def _snapshot_lpac_runtime(
    api: _WindowsLpacApi,
    runtime_root: str,
) -> tuple[_WindowsLpacRuntimeEntry, ...]:
    _require_local_windows_path(runtime_root, "runtime root")
    root = Path(runtime_root).resolve(strict=True)
    paths = [root]
    paths.extend(
        sorted(
            root.rglob("*"),
            key=lambda path: str(path.relative_to(root)).casefold(),
        )
    )
    if len(paths) > _MAX_LPAC_RUNTIME_ENTRIES:
        raise ValueError("Windows LPAC runtime closure exceeds its entry bound")
    entries: list[_WindowsLpacRuntimeEntry] = []
    total_bytes = 0
    for path in paths:
        information = path.lstat()
        if (
            path.is_symlink()
            or int(getattr(information, "st_file_attributes", 0)) & 0x00000400
        ):
            raise ValueError("Windows LPAC runtime closure contains a reparse point")
        if stat.S_ISDIR(information.st_mode):
            directory = True
        elif stat.S_ISREG(information.st_mode):
            directory = False
        else:
            raise ValueError("Windows LPAC runtime closure contains a special file")
        handles: list[int] = []
        try:
            opener = api.open_locked_directory if directory else api.open_locked_file
            opener(str(path), on_acquired=handles.append)
            if len(handles) != 1:
                raise RuntimeError("Windows LPAC runtime owner attachment failed")
            identity = api.locked_path_identity(handles[0])
            if identity.is_directory != directory:
                raise ValueError("Windows LPAC runtime path kind changed")
            relative = (
                "."
                if path == root
                else str(path.relative_to(root)).replace(os.sep, "\\")
            )
            digest: str | None = None
            size = 0
            if not directory:
                if identity.link_count != 1:
                    raise ValueError("Windows LPAC runtime file has foreign hard links")
                if api.file_stream_names(identity.final_path) not in {
                    (),
                    ("::$DATA",),
                }:
                    raise ValueError("Windows LPAC runtime file has alternate streams")
                size = identity.size
                total_bytes += size
                if total_bytes > _MAX_LPAC_RUNTIME_BYTES:
                    raise ValueError(
                        "Windows LPAC runtime closure exceeds its byte bound"
                    )
                digest = api.locked_file_sha256(handles[0])
            entries.append(
                _WindowsLpacRuntimeEntry(
                    relative_path=relative,
                    volume_serial=identity.volume_serial,
                    file_id=identity.file_id,
                    size=size,
                    is_directory=directory,
                    sha256=digest,
                )
            )
        finally:
            for handle in reversed(handles):
                api.close_handle(handle)
    return tuple(sorted(entries, key=lambda entry: entry.relative_path.casefold()))


def _verify_lpac_runtime(
    api: _WindowsLpacApi,
    spec: _WindowsLpacProvisionSpec,
) -> None:
    if _snapshot_lpac_runtime(api, spec.runtime_root) != spec.runtime_entries:
        raise HostingError(
            HostingFailureCategory.PREPARATION_STALE,
            "Windows LPAC runtime closure changed",
        )
    executable = next(
        entry
        for entry in spec.runtime_entries
        if entry.relative_path == spec.executable_relative_path
    )
    assert executable.sha256 is not None
    _verify_pe_image(
        Path(spec.request.argv[0]),
        expected_digest=executable.sha256,
        expected_imports=spec.platform_imports,
    )


def _lpac_grant_targets(
    spec: _WindowsLpacProvisionSpec,
) -> tuple[tuple[str, int, bool], ...]:
    ancestors = tuple(reversed(_ancestor_directory_paths(spec.runtime_root)))
    return tuple((path, _FILE_TRAVERSE_READ, False) for path in ancestors) + (
        (spec.runtime_root, _LPAC_RUNTIME_ACCESS, True),
    )


def _lpac_private_grant_targets(
    private_root: str,
) -> tuple[tuple[str, int, bool], ...]:
    root = _require_local_windows_path(private_root, "private root")
    return (
        (root, _FILE_TRAVERSE_READ, False),
        (ntpath.join(root, "Temp"), _LPAC_PRIVATE_SCRATCH_ACCESS, True),
    )


def _verify_lpac_grants(
    api: _WindowsLpacApi,
    spec: _WindowsLpacProvisionSpec,
    private_root: str,
    sid: int,
    *,
    present: bool,
) -> None:
    targets = _lpac_grant_targets(spec) + _lpac_private_grant_targets(private_root)
    for path, permissions, inherit in targets:
        actual = api.lpac_path_access(path, sid)
        expected = (
            ((permissions, _LPAC_ROOT_ACE_FLAGS if inherit else 0),) if present else ()
        )
        if actual != expected:
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows LPAC grant changed "
                f"(expected={expected!r}, observed={actual!r})",
            )


def _private_state_fingerprint(api: _WindowsLpacApi, private_root: str) -> str:
    handles: list[int] = []
    try:
        api.open_locked_directory(private_root, on_acquired=handles.append)
        if len(handles) != 1:
            raise RuntimeError("Windows LPAC private owner attachment failed")
        identity = api.locked_path_identity(handles[0])
        if not identity.is_directory:
            raise ValueError("Windows LPAC private root is not a directory")
        return _fingerprint(
            f"{identity.volume_serial}:{identity.file_id}:"
            f"{ntpath.normcase(identity.final_path)}"
        )
    finally:
        for handle in reversed(handles):
            api.close_handle(handle)


def _lpac_profile_name(spec: _WindowsLpacProvisionSpec) -> str:
    digest = hashlib.sha256(
        f"{spec.attempt_id}\0{spec.operation_nonce}".encode("utf-8")
    ).hexdigest()
    return f"{_LPAC_PROFILE_PREFIX}{digest[:40]}"


def _lpac_profile_fingerprint(spec: _WindowsLpacProvisionSpec) -> str:
    return _fingerprint(_lpac_profile_name(spec))


def _lpac_spec_fingerprint(spec: _WindowsLpacProvisionSpec) -> str:
    payload = {
        "attempt": spec.attempt_id,
        "lifecycle": spec.lifecycle_fingerprint,
        "nonce": spec.operation_nonce,
        "platform": spec.platform_identity,
        "request": {
            "argv": spec.request.argv,
            "cwd": spec.request.cwd,
            "streams": (
                spec.request.streams.stdin.value,
                spec.request.streams.stdout.value,
                spec.request.streams.stderr.value,
            ),
        },
        "runtime": [
            (
                entry.relative_path,
                entry.volume_serial,
                entry.file_id,
                entry.size,
                entry.is_directory,
                entry.sha256,
            )
            for entry in spec.runtime_entries
        ],
        "imports": spec.platform_imports,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _lpac_grant_digest(spec: _WindowsLpacProvisionSpec) -> str:
    payload = [
        (path.casefold(), permissions, inherit)
        for path, permissions, inherit in _lpac_grant_targets(spec)
    ]
    payload.extend(
        (
            ("@profile-private-root", _FILE_TRAVERSE_READ, False),
            ("@profile-private-temp", _LPAC_PRIVATE_SCRATCH_ACCESS, True),
        )
    )
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _replace_lpac_witness_state(
    witness: _WindowsLpacProvisionWitness,
    state: str,
) -> _WindowsLpacProvisionWitness:
    return _WindowsLpacProvisionWitness(
        state=state,
        attempt_id=witness.attempt_id,
        operation_nonce=witness.operation_nonce,
        spec_fingerprint=witness.spec_fingerprint,
        profile_fingerprint=witness.profile_fingerprint,
        sid_fingerprint=witness.sid_fingerprint,
        private_state_fingerprint=witness.private_state_fingerprint,
        grant_digest=witness.grant_digest,
        platform_identity=witness.platform_identity,
    )


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_effect_callback(callback: Callable[[], None]) -> None:
    if not callable(callback):
        raise TypeError("Windows LPAC native effect callback is not callable")


def _require_local_windows_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"Windows LPAC {label} is invalid")
    normalized = ntpath.normpath(value)
    drive, tail = ntpath.splitdrive(normalized)
    if (
        normalized != value
        or not drive
        or not tail.startswith("\\")
        or not ntpath.isabs(normalized)
        or drive.upper().startswith("\\\\?\\UNC")
        or drive.startswith("\\\\")
    ):
        raise ValueError(f"Windows LPAC {label} must be a canonical local path")
    return normalized


def _relative_lpac_path(root: str, value: str) -> str:
    _require_local_windows_path(root, "runtime root")
    _require_local_windows_path(value, "runtime member")
    try:
        relative = ntpath.relpath(value, root)
    except ValueError as error:
        raise ValueError("Windows LPAC runtime member crosses volumes") from error
    normalized = ntpath.normpath(relative)
    if normalized == ".":
        return normalized
    if normalized.startswith("..") or ntpath.isabs(normalized) or ":" in normalized:
        raise ValueError("Windows LPAC runtime member escapes its root")
    return normalized


@dataclass(frozen=True, slots=True)
class _WindowsLpacLaunchCaptureSpec(_LaunchCaptureSpec):
    """One verified LPAC profile joined to an exact immutable launch closure."""

    provision: _WindowsLpacProvisionSpec
    witness: _WindowsLpacProvisionWitness

    def __post_init__(self) -> None:
        super(_WindowsLpacLaunchCaptureSpec, self).__post_init__()
        if self.profile_id != _LPAC_PROFILE_ID:
            raise ValueError("Windows LPAC launch profile_id is unsupported")
        if type(self.provision) is not _WindowsLpacProvisionSpec:
            raise TypeError("Windows LPAC launch provision spec is invalid")
        if type(self.witness) is not _WindowsLpacProvisionWitness:
            raise TypeError("Windows LPAC launch witness is invalid")
        if self.witness.state != "VERIFIED":
            raise ValueError("Windows LPAC launch requires a verified witness")
        if (
            self.request.argv != self.provision.request.argv
            or self.request.cwd != self.provision.request.cwd
        ):
            raise ValueError("Windows LPAC launch request changed")
        environment = dict(self.request.effective_environment)
        if set(environment) != {"LOCALAPPDATA", "SystemRoot", "TEMP", "TMP"}:
            raise ValueError("Windows LPAC launch environment is not closed")
        if environment["TEMP"] != environment["TMP"]:
            raise ValueError("Windows LPAC launch scratch environment is inconsistent")
        if ntpath.dirname(environment["TEMP"]) != environment["LOCALAPPDATA"]:
            raise ValueError("Windows LPAC launch scratch escaped private state")
        expected_closure = _lpac_execution_closure(
            self.provision,
            self.witness,
            self.request.effective_environment,
        )
        if self.execution_closure != expected_closure:
            raise ValueError("Windows LPAC execution closure is inconsistent")


def _build_windows_lpac_launch_capture_spec(
    request: ProcessLaunchRequest,
    *,
    provision: _WindowsLpacProvisionSpec,
    witness: _WindowsLpacProvisionWitness,
    _api: _WindowsLpacApi | None = None,
) -> _WindowsLpacLaunchCaptureSpec:
    if request != provision.request or request.effective_environment:
        raise HostingError(
            HostingFailureCategory.PREPARATION_REJECTED,
            "Windows LPAC capture request does not match its provisioned attempt",
        )
    try:
        api = _api or _CtypesWin32Api()
        verified = _WindowsLpacProvisioner(api=api).verify(provision, witness)
        profile = api.derive_lpac_profile(_lpac_profile_name(provision))
        try:
            if _fingerprint(profile.sid_text) != verified.sid_fingerprint:
                raise ValueError("Windows LPAC Package SID changed")
            system_root = _canonical_system_root(api.canonical_system_root())
            private_root = ntpath.normpath(profile.private_root)
            scratch = ntpath.join(private_root, "Temp")
            environment = tuple(
                sorted(
                    (
                        ("LOCALAPPDATA", private_root),
                        ("SystemRoot", system_root),
                        ("TEMP", scratch),
                        ("TMP", scratch),
                    ),
                    key=lambda item: item[0].casefold(),
                )
            )
            trusted_request = ProcessLaunchRequest(
                argv=request.argv,
                cwd=request.cwd,
                effective_environment=environment,
                streams=request.streams,
            )
            return _WindowsLpacLaunchCaptureSpec(
                request=trusted_request,
                profile_id=_LPAC_PROFILE_ID,
                execution_closure=_lpac_execution_closure(
                    provision,
                    verified,
                    environment,
                ),
                provision=provision,
                witness=verified,
            )
        finally:
            api.free_sid(profile.sid)
    except HostingError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise HostingError(
            HostingFailureCategory.PREPARATION_REJECTED,
            "Windows LPAC capture construction failed",
        ) from error


class _WindowsLpacLaunchCaptureBackend:
    """Exact Windows LPAC owner acquisition, still dark to all Products."""

    backend_id = "windows-job-v1"

    def __init__(self, *, api: _WindowsLpacApi | None = None) -> None:
        if api is None and os.name != "nt":
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows LPAC launch preparation is unavailable",
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
    ) -> "_WindowsLpacLaunchMaterial":
        if type(spec) is not _WindowsLpacLaunchCaptureSpec:
            raise HostingError(
                HostingFailureCategory.PREPARATION_FAILED,
                "Windows LPAC launch requires the exact capture profile",
            )
        if spec.provision.platform_identity != self._platform_identity:
            raise HostingError(
                HostingFailureCategory.PLATFORM_UNSUPPORTED,
                "Windows LPAC launch platform identity changed",
            )
        material = _WindowsLpacLaunchMaterial(
            api=self._api,
            spec=spec,
            attempt_id=attempt_id,
            attempt_token=attempt_token,
        )
        if not callable(on_capture):
            raise TypeError("Windows LPAC capture callback is not callable")
        try:
            on_capture(material)
        except BaseException as primary:
            try:
                await material.close()
            except BaseException as cleanup:
                primary.add_note(f"Windows empty LPAC cleanup also failed: {cleanup}")
                raise primary from cleanup
            raise
        material._capture()
        return material


class _WindowsLpacLaunchMaterial:
    """Attempt-bound LPAC SID, closure locks, Job, and discarded stderr."""

    backend_id = "windows-job-v1"

    def __init__(
        self,
        *,
        api: _WindowsLpacApi,
        spec: _WindowsLpacLaunchCaptureSpec,
        attempt_id: str,
        attempt_token: object,
    ) -> None:
        self._api = api
        self._spec = spec
        self._attempt_id = attempt_id
        self._attempt_token = attempt_token
        self._runtime_handles: dict[str, int] = {}
        self._runtime_identities: dict[str, _Win32LockedPathIdentity] = {}
        self._profile: _Win32LpacProfile | None = None
        self._job_handle = -1
        self._stderr_handle = -1
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
        return len(self._spec.provision.runtime_entries) + 3

    def _capture(self) -> None:
        try:
            provision = self._spec.provision
            for entry in provision.runtime_entries:
                path = _lpac_runtime_path(provision.runtime_root, entry.relative_path)
                opener = (
                    self._api.open_locked_directory
                    if entry.is_directory
                    else self._api.open_locked_file
                )
                relative = entry.relative_path

                def adopt_runtime(handle: int, *, relative: str = relative) -> None:
                    self._adopt_runtime_handle(relative, handle)

                opener(path, on_acquired=adopt_runtime)
                self._runtime_identities[entry.relative_path] = (
                    self._api.locked_path_identity(
                        self._runtime_handles[entry.relative_path]
                    )
                )
            profile = self._api.derive_lpac_profile(_lpac_profile_name(provision))
            self._profile = profile
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
                "Windows LPAC launch request changed before verification",
            )
        with self._lock:
            if self._state != "captured":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows LPAC material cannot be verified",
                )
        self._verify_owned()
        with self._lock:
            if self._state != "captured":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows LPAC verification lost ownership",
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
                    "Windows LPAC material received a mismatched backend",
                )
            )
        return await backend._spawn_lpac_prepared(
            self,
            request,
            effect=effect,
            on_spawn=on_spawn,
            inheritance=inheritance,
        )

    def _claim_handles(self) -> tuple[int, int, int, str, int, int]:
        with self._lock:
            if self._state != "verified":
                raise HostingError(
                    HostingFailureCategory.PREPARATION_FAILED,
                    "Windows LPAC material is not verified for spawn",
                )
            provision = self._spec.provision
            executable = self._runtime_handles[provision.executable_relative_path]
            cwd = self._runtime_handles[provision.cwd_relative_path]
            profile = self._profile
            if profile is None or any(
                handle <= 0
                for handle in (executable, cwd, self._job_handle, self._stderr_handle)
            ):
                raise HostingError(
                    HostingFailureCategory.PREPARATION_STALE,
                    "Windows LPAC material lost a native owner",
                )
            self._state = "claimed"
            return (
                executable,
                cwd,
                profile.sid,
                profile.sid_text,
                self._job_handle,
                self._stderr_handle,
            )

    def _mark_transferred(self) -> None:
        with self._lock:
            if self._state != "claimed":
                raise RuntimeError("Windows LPAC transfer state is inconsistent")
            self._job_handle = -1
            self._stderr_handle = -1
            self._state = "transferred"

    async def close(self) -> None:
        failures: list[BaseException] = []
        for attribute in ("_stderr_handle", "_job_handle"):
            try:
                self._close_attribute(attribute)
            except BaseException as error:
                failures.append(error)
        for relative, handle in tuple(reversed(tuple(self._runtime_handles.items()))):
            try:
                self._api.close_handle(handle)
            except BaseException as error:
                failures.append(error)
            else:
                self._runtime_handles.pop(relative, None)
        profile = self._profile
        if profile is not None:
            try:
                self._api.free_sid(profile.sid)
            except BaseException as error:
                failures.append(error)
            else:
                self._profile = None
        with self._lock:
            remaining = (
                self._stderr_handle > 0
                or self._job_handle > 0
                or bool(self._runtime_handles)
                or self._profile is not None
            )
            self._state = "close-failed" if remaining else "closed"
        if failures:
            raise BaseExceptionGroup("Windows LPAC material cleanup failed", failures)

    def _adopt_runtime_handle(self, relative: str, handle: int) -> None:
        if handle <= 0 or relative in self._runtime_handles:
            raise RuntimeError("Windows LPAC runtime owner attachment is invalid")
        self._runtime_handles[relative] = handle

    def _adopt_handle(self, attribute: str, handle: int) -> None:
        if handle <= 0:
            raise RuntimeError("Windows LPAC owner attachment is invalid")
        with self._lock:
            if getattr(self, attribute) > 0:
                raise RuntimeError("Windows LPAC owner attached twice")
            setattr(self, attribute, handle)

    def _close_attribute(self, attribute: str) -> None:
        with self._lock:
            handle = getattr(self, attribute)
        if handle <= 0:
            return
        self._api.close_handle(handle)
        with self._lock:
            if getattr(self, attribute) == handle:
                setattr(self, attribute, -1)

    def _verify_owned(self) -> None:
        provision = self._spec.provision
        if len(self._runtime_handles) != len(provision.runtime_entries):
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows LPAC runtime ownership is incomplete",
            )
        for entry in provision.runtime_entries:
            current = self._api.locked_path_identity(
                self._runtime_handles[entry.relative_path]
            )
            expected = self._runtime_identities[entry.relative_path]
            if current != expected or (
                current.volume_serial,
                current.file_id,
                current.size if not current.is_directory else 0,
                current.is_directory,
            ) != (
                entry.volume_serial,
                entry.file_id,
                entry.size,
                entry.is_directory,
            ):
                raise HostingError(
                    HostingFailureCategory.PREPARATION_STALE,
                    "Windows LPAC locked runtime identity changed",
                )
            if not entry.is_directory:
                if current.link_count != 1 or self._api.file_stream_names(
                    current.final_path
                ) not in {(), ("::$DATA",)}:
                    raise HostingError(
                        HostingFailureCategory.PREPARATION_STALE,
                        "Windows LPAC runtime file topology changed",
                    )
                assert entry.sha256 is not None
                if (
                    self._api.locked_file_sha256(
                        self._runtime_handles[entry.relative_path]
                    )
                    != entry.sha256
                ):
                    raise HostingError(
                        HostingFailureCategory.PREPARATION_STALE,
                        "Windows LPAC runtime content changed",
                    )
        profile = self._profile
        if profile is None:
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows LPAC profile owner is unavailable",
            )
        witness = self._spec.witness
        if (
            _fingerprint(profile.sid_text) != witness.sid_fingerprint
            or _private_state_fingerprint(self._api, profile.private_root)
            != witness.private_state_fingerprint
        ):
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows LPAC profile identity changed",
            )
        _verify_lpac_grants(
            self._api,
            provision,
            profile.private_root,
            profile.sid,
            present=True,
        )
        if not self._api.managed_job_is_kill_on_close(self._job_handle):
            raise HostingError(
                HostingFailureCategory.PREPARATION_STALE,
                "Windows LPAC Job lost kill-on-close",
            )


def _lpac_execution_closure(
    provision: _WindowsLpacProvisionSpec,
    witness: _WindowsLpacProvisionWitness,
    environment: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    return (
        f"runtime:sha256:{_lpac_runtime_fingerprint(provision)}",
        f"provision:sha256:{witness.spec_fingerprint}",
        f"profile:sha256:{witness.profile_fingerprint}",
        f"package-sid:sha256:{witness.sid_fingerprint}",
        f"private-state:sha256:{witness.private_state_fingerprint}",
        f"grant:sha256:{witness.grant_digest}",
        "capabilities:none",
        "all-application-packages:opt-out",
        "attributes:security-capabilities,aap-policy,job-list,handle-list",
        f"environment:sha256:{_fingerprint(json.dumps(environment, separators=(',', ':')))}",
        f"platform:{provision.platform_identity}",
    )


def _lpac_runtime_fingerprint(spec: _WindowsLpacProvisionSpec) -> str:
    return _fingerprint(
        json.dumps(
            [
                (
                    entry.relative_path,
                    entry.volume_serial,
                    entry.file_id,
                    entry.size,
                    entry.is_directory,
                    entry.sha256,
                )
                for entry in spec.runtime_entries
            ],
            separators=(",", ":"),
        )
    )


def _lpac_runtime_path(root: str, relative: str) -> str:
    return root if relative == "." else ntpath.join(root, relative)


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
    if (
        not drive
        or not tail.startswith("\\")
        or drive.upper().startswith("\\\\?\\UNC\\")
    ):
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
        for (
            existing_virtual,
            existing_size,
            existing_raw,
            existing_raw_size,
        ) in sections:
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
