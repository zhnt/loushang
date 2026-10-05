# mypy: disable-error-code=attr-defined
"""Windows AppContainer adapter for PLC9B offline-restore activation.

The accepted protocol is pathless.  This dark platform owner validates a
Windows-native restored tree, grants one request-specific AppContainer only
the filesystem authority it needs, launches the old runtime in a kill-on-close
Job Object, and persists a private marker bound to native process identity.
"""

from __future__ import annotations

import ctypes
import os
import re
import stat
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PackageLegacyRuntimeActivationReceiptV1,
    PackageOfflineRestoreError,
    PackageOfflineRestoreMaterializationReceiptV1,
    PackageOfflineRestoreRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_offline_restore import (
    _PAYLOAD_NAME,
    DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_BYTES,
    DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_DEPTH,
    DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_ENTRIES,
    _directory_identity,
    _inspect_tree,
    _native_identity,
    _open_directory_at,
    _paths_overlap,
    _pinned_roots_overlap,
    _PinnedWindowsRoot,
    _read_regular_file,
    _remove_directory_contents,
    _strict_json_object,
    _validated_limit,
    _validated_root_path,
    _write_new_file,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    supports_windows_rooted_io,
    windows_flush_directory,
    windows_listdir_at,
    windows_rmdir_at,
    windows_stat_at,
    windows_unlink_at,
)

if os.name == "nt":
    import msvcrt as _msvcrt
    from ctypes import wintypes as _wintypes
else:  # pragma: no cover - collected only on non-Windows hosts
    _msvcrt = None  # type: ignore[assignment]
    _wintypes = None  # type: ignore[assignment]

PACKAGE_WINDOWS_LEGACY_RUNTIME_MARKER_VERSION = 1
DEFAULT_PACKAGE_WINDOWS_LEGACY_RUNTIME_STARTUP_TIMEOUT_SECONDS = 10.0
DEFAULT_PACKAGE_WINDOWS_LEGACY_RUNTIME_TERMINATION_GRACE_SECONDS = 3.0

_ACTIVE_MARKER_NAME = "active-runtime.json"
_STARTING_MARKER_NAME = "starting-runtime.json"
_SETTLING_MARKER_NAME = "settling-runtime.json"
_SETTLED_RECEIPT_NAME = "settled-runtime.json"
_LOCK_NAME = ".legacy-runtime.lock"
_READY_NAME = "ready.txt"
_RUNTIME_PREFIX = "runtime-"
_MAX_MARKER_BYTES = 128 * 1024
_MAX_READY_BYTES = 4096
_MAX_COMMAND_ARGUMENTS = 256
_MAX_COMMAND_BYTES = 128 * 1024
_MAX_ENVIRONMENT_ENTRIES = 256
_MAX_ENVIRONMENT_BYTES = 128 * 1024
_READY_PATH_ENV = "LOUSHANG_LEGACY_RUNTIME_READY_PATH"
_READY_TOKEN_ENV = "LOUSHANG_LEGACY_RUNTIME_READY_TOKEN"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_PROFILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.]{0,63}\Z")

_ERROR_ALREADY_EXISTS = 183
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_ERROR_INSUFFICIENT_BUFFER = 122
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_STILL_ACTIVE = 259
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_TOKEN_QUERY = 0x0008
_TOKEN_DUPLICATE = 0x0002
_TOKEN_IMPERSONATE = 0x0004
_SECURITY_IMPERSONATION = 2
_TOKEN_IS_APP_CONTAINER = 29
_TOKEN_CAPABILITIES = 30
_TOKEN_APP_CONTAINER_SID = 31
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_SHARE_ALL = 0x00000007
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_GRANT_ACCESS = 1
_REVOKE_ACCESS = 4
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_UNKNOWN = 0
_SUB_CONTAINERS_AND_OBJECTS_INHERIT = 0x3
_GENERIC_ALL = 0x10000000
_GENERIC_READ = 0x80000000
_GENERIC_EXECUTE = 0x20000000
_FILE_TRAVERSE_READ = 0x001200A0


if os.name == "nt":

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", _wintypes.DWORD)]

    class _SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [
            ("AppContainerSid", ctypes.c_void_p),
            ("Capabilities", ctypes.POINTER(_SID_AND_ATTRIBUTES)),
            ("CapabilityCount", _wintypes.DWORD),
            ("Reserved", _wintypes.DWORD),
        ]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", _wintypes.DWORD),
            ("lpReserved", _wintypes.LPWSTR),
            ("lpDesktop", _wintypes.LPWSTR),
            ("lpTitle", _wintypes.LPWSTR),
            ("dwX", _wintypes.DWORD),
            ("dwY", _wintypes.DWORD),
            ("dwXSize", _wintypes.DWORD),
            ("dwYSize", _wintypes.DWORD),
            ("dwXCountChars", _wintypes.DWORD),
            ("dwYCountChars", _wintypes.DWORD),
            ("dwFillAttribute", _wintypes.DWORD),
            ("dwFlags", _wintypes.DWORD),
            ("wShowWindow", _wintypes.WORD),
            ("cbReserved2", _wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
            ("hStdInput", _wintypes.HANDLE),
            ("hStdOutput", _wintypes.HANDLE),
            ("hStdError", _wintypes.HANDLE),
        ]

    class _STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", _STARTUPINFOW),
            ("lpAttributeList", ctypes.c_void_p),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", _wintypes.HANDLE),
            ("hThread", _wintypes.HANDLE),
            ("dwProcessId", _wintypes.DWORD),
            ("dwThreadId", _wintypes.DWORD),
        ]

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", _wintypes.DWORD),
            ("dwHighDateTime", _wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", _wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", _wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", _wintypes.DWORD),
            ("SchedulingClass", _wintypes.DWORD),
        ]

    class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", _wintypes.DWORD),
            ("TotalProcesses", _wintypes.DWORD),
            ("ActiveProcesses", _wintypes.DWORD),
            ("TotalTerminatedProcesses", _wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _TRUSTEE_W(ctypes.Structure):
        pass

    _TRUSTEE_W._fields_ = [
        ("pMultipleTrustee", ctypes.POINTER(_TRUSTEE_W)),
        ("MultipleTrusteeOperation", ctypes.c_int),
        ("TrusteeForm", ctypes.c_int),
        ("TrusteeType", ctypes.c_int),
        ("ptstrName", _wintypes.LPWSTR),
    ]

    class _EXPLICIT_ACCESS_W(ctypes.Structure):
        _fields_ = [
            ("grfAccessPermissions", _wintypes.DWORD),
            ("grfAccessMode", ctypes.c_int),
            ("grfInheritance", _wintypes.DWORD),
            ("Trustee", _TRUSTEE_W),
        ]


@dataclass(frozen=True, slots=True)
class _ProcessIdentity:
    pid: int
    creation_time: int

    def __post_init__(self) -> None:
        if self.pid < 1 or self.creation_time < 1:
            raise ValueError("Windows process identity is invalid")


class _UnsettledUnboundProcessError(OSError):
    """A child with failed Job-membership proof could not be proven dead."""


@dataclass(frozen=True, slots=True)
class _ActivationMarker:
    receipt: PackageLegacyRuntimeActivationReceiptV1
    process: _ProcessIdentity
    profile_name: str
    profile_sid: str
    job_name: str
    current_b_root_identity: str
    restore_namespace_id: str
    sandbox_profile_digest: str
    marker_version: int = PACKAGE_WINDOWS_LEGACY_RUNTIME_MARKER_VERSION

    def __post_init__(self) -> None:
        if not _SAFE_PROFILE.fullmatch(self.profile_name):
            raise ValueError("Windows AppContainer profile name is invalid")
        for value, name in (
            (self.current_b_root_identity, "current B root identity"),
            (self.restore_namespace_id, "restore namespace identity"),
            (self.sandbox_profile_digest, "sandbox profile digest"),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"{name} is invalid")
        if not self.profile_sid.startswith("S-1-") or len(self.profile_sid) > 184:
            raise ValueError("Windows AppContainer SID is invalid")
        if not self.job_name.startswith("Local\\Loushang.PLC9B."):
            raise ValueError("Windows legacy-runtime Job Object name is invalid")
        if self.marker_version != PACKAGE_WINDOWS_LEGACY_RUNTIME_MARKER_VERSION:
            raise ValueError("Unsupported Windows legacy-runtime marker")
        expected = _runtime_instance_identity(
            request_id=self.receipt.request_id,
            materialization_receipt_id=self.receipt.materialization_receipt_id,
            process=self.process,
            profile_sid=self.profile_sid,
        )
        if self.receipt.runtime_instance_id != expected:
            raise ValueError("Windows runtime marker identity does not match")
        if (
            self.receipt.runtime_lease_id
            != sha256(f"legacy-lease:{expected}".encode()).hexdigest()
        ):
            raise ValueError("Windows runtime lease identity does not match")

    def to_dict(self) -> dict[str, object]:
        return {
            "currentBRootIdentity": self.current_b_root_identity,
            "jobName": self.job_name,
            "markerVersion": self.marker_version,
            "processCreationTime": self.process.creation_time,
            "processPid": self.process.pid,
            "profileName": self.profile_name,
            "profileSid": self.profile_sid,
            "receipt": self.receipt.to_dict(),
            "restoreNamespaceId": self.restore_namespace_id,
            "sandboxProfileDigest": self.sandbox_profile_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> _ActivationMarker:
        if not isinstance(value, dict) or set(value) != {
            "currentBRootIdentity",
            "jobName",
            "markerVersion",
            "processCreationTime",
            "processPid",
            "profileName",
            "profileSid",
            "receipt",
            "restoreNamespaceId",
            "sandboxProfileDigest",
        }:
            raise ValueError("Windows legacy-runtime marker has an invalid schema")
        return cls(
            receipt=PackageLegacyRuntimeActivationReceiptV1.from_dict(value["receipt"]),
            process=_ProcessIdentity(
                pid=_positive_int(value["processPid"]),
                creation_time=_positive_int(value["processCreationTime"]),
            ),
            profile_name=_string(value["profileName"]),
            profile_sid=_string(value["profileSid"]),
            job_name=_string(value["jobName"]),
            current_b_root_identity=_string(value["currentBRootIdentity"]),
            restore_namespace_id=_string(value["restoreNamespaceId"]),
            sandbox_profile_digest=_string(value["sandboxProfileDigest"]),
            marker_version=_positive_int(value["markerVersion"]),
        )


@dataclass(frozen=True, slots=True)
class _ActivationStartIntentV1:
    """Pre-effect reservation for one exact Windows activation attempt."""

    request_id: str
    materialization_receipt_id: str
    store_id: str
    legacy_runtime_version: str
    restore_namespace_id: str
    current_b_root_identity: str
    sandbox_profile_digest: str
    profile_name: str
    job_name: str
    intent_id: str
    intent_version: int = 1

    def __post_init__(self) -> None:
        for value in (
            self.request_id,
            self.materialization_receipt_id,
            self.restore_namespace_id,
            self.current_b_root_identity,
            self.sandbox_profile_digest,
            self.intent_id,
        ):
            if (
                not isinstance(value, str)
                or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise ValueError("Windows activation start identity is invalid")
        if (
            not isinstance(self.store_id, str)
            or not _SAFE_ID.fullmatch(self.store_id)
            or not isinstance(self.legacy_runtime_version, str)
            or not self.legacy_runtime_version
            or len(self.legacy_runtime_version) > 128
            or self.profile_name != f"Loushang.PLC9B.{self.request_id[:32]}"
            or self.job_name != f"Local\\Loushang.PLC9B.{self.request_id[:32]}"
            or type(self.intent_version) is not int
            or self.intent_version != 1
            or self.intent_id
            != sha256(canonical_json_bytes(self._identity())).hexdigest()
        ):
            raise ValueError("Windows activation start intent changed")

    @classmethod
    def create(
        cls,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
        *,
        sandbox_profile_digest: str,
        profile_name: str,
        job_name: str,
    ) -> _ActivationStartIntentV1:
        identity = {
            "requestId": request.request_id,
            "materializationReceiptId": materialization.materialization_receipt_id,
            "storeId": request.store_id,
            "legacyRuntimeVersion": request.legacy_runtime_version,
            "restoreNamespaceId": request.restore_namespace_id,
            "currentBRootIdentity": request.current_root_identity,
            "sandboxProfileDigest": sandbox_profile_digest,
            "profileName": profile_name,
            "jobName": job_name,
            "intentVersion": 1,
        }
        return cls(
            request_id=request.request_id,
            materialization_receipt_id=materialization.materialization_receipt_id,
            store_id=request.store_id,
            legacy_runtime_version=request.legacy_runtime_version,
            restore_namespace_id=request.restore_namespace_id,
            current_b_root_identity=request.current_root_identity,
            sandbox_profile_digest=sandbox_profile_digest,
            profile_name=profile_name,
            job_name=job_name,
            intent_id=sha256(canonical_json_bytes(identity)).hexdigest(),
        )

    def matches_marker(self, marker: _ActivationMarker) -> bool:
        return (
            self.request_id == marker.receipt.request_id
            and self.materialization_receipt_id
            == marker.receipt.materialization_receipt_id
            and self.store_id == marker.receipt.store_id
            and self.legacy_runtime_version == marker.receipt.legacy_runtime_version
            and self.restore_namespace_id == marker.restore_namespace_id
            and self.current_b_root_identity == marker.current_b_root_identity
            and self.sandbox_profile_digest == marker.sandbox_profile_digest
            and self.profile_name == marker.profile_name
            and self.job_name == marker.job_name
        )

    def _identity(self) -> dict[str, object]:
        return {
            "requestId": self.request_id,
            "materializationReceiptId": self.materialization_receipt_id,
            "storeId": self.store_id,
            "legacyRuntimeVersion": self.legacy_runtime_version,
            "restoreNamespaceId": self.restore_namespace_id,
            "currentBRootIdentity": self.current_b_root_identity,
            "sandboxProfileDigest": self.sandbox_profile_digest,
            "profileName": self.profile_name,
            "jobName": self.job_name,
            "intentVersion": self.intent_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity(), "intentId": self.intent_id}

    @classmethod
    def from_dict(cls, value: object) -> _ActivationStartIntentV1:
        if not isinstance(value, dict) or set(value) != {
            "requestId",
            "materializationReceiptId",
            "storeId",
            "legacyRuntimeVersion",
            "restoreNamespaceId",
            "currentBRootIdentity",
            "sandboxProfileDigest",
            "profileName",
            "jobName",
            "intentVersion",
            "intentId",
        }:
            raise ValueError("Windows activation start intent schema changed")
        return cls(
            request_id=_string(value["requestId"]),
            materialization_receipt_id=_string(value["materializationReceiptId"]),
            store_id=_string(value["storeId"]),
            legacy_runtime_version=_string(value["legacyRuntimeVersion"]),
            restore_namespace_id=_string(value["restoreNamespaceId"]),
            current_b_root_identity=_string(value["currentBRootIdentity"]),
            sandbox_profile_digest=_string(value["sandboxProfileDigest"]),
            profile_name=_string(value["profileName"]),
            job_name=_string(value["jobName"]),
            intent_version=_positive_int(value["intentVersion"]),
            intent_id=_string(value["intentId"]),
        )


@dataclass(frozen=True, slots=True)
class PackageWindowsLegacyRuntimeSettlementReceiptV1:
    """Durable evidence for one exact Windows legacy-runtime settlement."""

    activation_receipt_id: str
    runtime_instance_id: str
    store_id: str
    intent_id: str
    settlement_id: str
    receipt_version: int = 1

    def __post_init__(self) -> None:
        for value in (
            self.activation_receipt_id,
            self.runtime_instance_id,
            self.intent_id,
            self.settlement_id,
        ):
            if (
                not isinstance(value, str)
                or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise ValueError(
                    "Windows legacy-runtime settlement identity is invalid"
                )
        if not isinstance(self.store_id, str) or not _SAFE_ID.fullmatch(self.store_id):
            raise ValueError("Windows legacy-runtime settlement store is invalid")
        if (
            type(self.receipt_version) is not int
            or self.receipt_version != 1
            or self.settlement_id
            != sha256(canonical_json_bytes(self._identity())).hexdigest()
        ):
            raise ValueError("Windows legacy-runtime settlement receipt changed")

    @classmethod
    def create(
        cls, marker: _ActivationMarker
    ) -> PackageWindowsLegacyRuntimeSettlementReceiptV1:
        intent_id = sha256(canonical_json_bytes(marker.to_dict())).hexdigest()
        identity = {
            "activationReceiptId": marker.receipt.activation_receipt_id,
            "intentId": intent_id,
            "receiptVersion": 1,
            "runtimeInstanceId": marker.receipt.runtime_instance_id,
            "storeId": marker.receipt.store_id,
        }
        return cls(
            activation_receipt_id=marker.receipt.activation_receipt_id,
            runtime_instance_id=marker.receipt.runtime_instance_id,
            store_id=marker.receipt.store_id,
            intent_id=intent_id,
            settlement_id=sha256(canonical_json_bytes(identity)).hexdigest(),
        )

    def _identity(self) -> dict[str, object]:
        return {
            "activationReceiptId": self.activation_receipt_id,
            "intentId": self.intent_id,
            "receiptVersion": self.receipt_version,
            "runtimeInstanceId": self.runtime_instance_id,
            "storeId": self.store_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity(), "settlementId": self.settlement_id}

    @classmethod
    def from_dict(cls, value: object) -> PackageWindowsLegacyRuntimeSettlementReceiptV1:
        if not isinstance(value, dict) or set(value) != {
            "activationReceiptId",
            "intentId",
            "receiptVersion",
            "runtimeInstanceId",
            "settlementId",
            "storeId",
        }:
            raise ValueError("Windows legacy-runtime settlement receipt schema changed")
        return cls(
            activation_receipt_id=_string(value["activationReceiptId"]),
            intent_id=_string(value["intentId"]),
            receipt_version=_positive_int(value["receiptVersion"]),
            runtime_instance_id=_string(value["runtimeInstanceId"]),
            settlement_id=_string(value["settlementId"]),
            store_id=_string(value["storeId"]),
        )


class PackageWindowsLegacyRuntimeActivationOwner:
    """Activate one restored old runtime in a zero-capability AppContainer."""

    def __init__(
        self,
        restore_authority_root: str | Path,
        activation_authority_root: str | Path,
        *,
        current_b_authority_root: str | Path,
        store_id: str,
        legacy_runtime_version: str,
        command: Sequence[str],
        environment: Mapping[str, str] | Sequence[tuple[str, str]] = (),
        startup_timeout_seconds: float = DEFAULT_PACKAGE_WINDOWS_LEGACY_RUNTIME_STARTUP_TIMEOUT_SECONDS,
        termination_grace_seconds: float = DEFAULT_PACKAGE_WINDOWS_LEGACY_RUNTIME_TERMINATION_GRACE_SECONDS,
        maximum_entries: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_ENTRIES,
        maximum_bytes: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_BYTES,
        maximum_depth: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_DEPTH,
    ) -> None:
        if os.name != "nt" or _msvcrt is None or not supports_windows_rooted_io():
            raise _activation_error("Windows legacy runtime isolation is unavailable")
        self._restore_root = _validated_root_path(
            restore_authority_root, name="restore authority"
        )
        self._activation_root = _validated_root_path(
            activation_authority_root, name="activation authority"
        )
        self._current_b_root = _validated_root_path(
            current_b_authority_root, name="current B authority"
        )
        roots = (self._restore_root, self._activation_root, self._current_b_root)
        if any(
            _paths_overlap(left, right)
            for index, left in enumerate(roots)
            for right in roots[index + 1 :]
        ):
            raise _activation_error(
                "Restore, activation, and current B authorities must be disjoint"
            )
        if not isinstance(store_id, str) or not _SAFE_ID.fullmatch(store_id):
            raise ValueError("Package store identity is invalid")
        if (
            not isinstance(legacy_runtime_version, str)
            or not legacy_runtime_version
            or len(legacy_runtime_version) > 128
        ):
            raise ValueError("Legacy Package runtime version is invalid")
        self._store_id = store_id
        self._legacy_runtime_version = legacy_runtime_version
        self._command = _validated_command(command)
        self._environment = _validated_environment(environment)
        self._startup_timeout = _timeout(startup_timeout_seconds, "startup timeout")
        self._termination_grace = _timeout(
            termination_grace_seconds, "termination grace"
        )
        self._maximum_entries = _validated_limit(
            maximum_entries, name="maximum activation entries"
        )
        self._maximum_bytes = _validated_limit(
            maximum_bytes, name="maximum activation bytes"
        )
        self._maximum_depth = _validated_limit(
            maximum_depth, name="maximum activation depth"
        )
        self._thread_lock = threading.RLock()
        self._jobs: dict[str, int] = {}
        pinned: list[_PinnedWindowsRoot] = []
        try:
            pinned = [_PinnedWindowsRoot.open(path) for path in roots]
            if any(
                _pinned_roots_overlap(left, right)
                for index, left in enumerate(pinned)
                for right in pinned[index + 1 :]
            ):
                raise OSError("Windows activation authorities overlap natively")
            self._restore_identities = pinned[0].identities
            self._activation_identities = pinned[1].identities
            self._current_b_identities = pinned[2].identities
        except Exception as exc:
            raise _activation_error(
                "Windows legacy runtime authorities are untrusted"
            ) from exc
        finally:
            for root in reversed(pinned):
                root.close()
        self._profile_digest = sha256(
            canonical_json_bytes(
                {
                    "backendId": "windows-appcontainer-job-v1",
                    "capabilityCount": 0,
                    "commandDigest": sha256(
                        canonical_json_bytes(list(self._command))
                    ).hexdigest(),
                    "environmentDigest": sha256(
                        canonical_json_bytes(list(self._environment))
                    ).hexdigest(),
                    "legacyRuntimeVersion": legacy_runtime_version,
                    "profileVersion": 1,
                }
            )
        ).hexdigest()

    def activate(
        self,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> PackageLegacyRuntimeActivationReceiptV1:
        _validate_activation_inputs(
            request,
            materialization,
            store_id=self._store_id,
            legacy_runtime_version=self._legacy_runtime_version,
        )
        profile_name = f"Loushang.PLC9B.{request.request_id[:32]}"
        job_name = f"Local\\Loushang.PLC9B.{request.request_id[:32]}"
        start_intent = _ActivationStartIntentV1.create(
            request,
            materialization,
            sandbox_profile_digest=self._profile_digest,
            profile_name=profile_name,
            job_name=job_name,
        )
        with self._exclusive_activation_root() as activation_root:
            if (
                self._read_settlement_intent(activation_root) is not None
                or self._read_settlement_receipt(activation_root) is not None
            ):
                raise _activation_error(
                    "Windows legacy-runtime settlement prevents another activation"
                )
            start = self._read_start_intent(activation_root)
            marker = self._read_marker(activation_root)
            if start is not None and (
                start != start_intent
                or (marker is not None and not start.matches_marker(marker))
            ):
                raise _activation_error("Windows legacy-runtime start intent changed")
            if marker is not None:
                if (
                    not marker.receipt.matches(request, materialization)
                    or marker.sandbox_profile_digest != self._profile_digest
                ):
                    raise _activation_error("Another legacy runtime owns activation")
                replay_process = _open_bound_process(marker.process)
                try:
                    with self._observed_settlement_job(marker.job_name) as job:
                        if job is None:
                            raise OSError("Windows legacy-runtime Job is missing")
                        _assert_isolated_process(
                            replay_process,
                            expected_sid=marker.profile_sid,
                            job=job,
                            restored_root=self._restored_path_from_marker(marker),
                            current_b_root=self._current_b_root,
                        )
                    self._open_bound_payload(request, materialization)
                    activation_root.assert_visible()
                    return marker.receipt
                finally:
                    _close_handle(replay_process)
            if start is not None:
                raise _activation_error(
                    "Incomplete Windows legacy-runtime start requires cleanup"
                )

            opened = self._open_bound_payload(request, materialization, keep_open=True)
            assert opened is not None
            restore_root, current_b_root, namespace_fd, payload_fd = opened
            runtime_name = f"{_RUNTIME_PREFIX}{request.request_id}"
            runtime_fd: int | None = None
            profile_sid: int | None = None
            profile_sid_string: str | None = None
            profile_created = False
            process: int | None = None
            marker_written = False
            start_written = False
            grants: list[tuple[Path, bool]] = []
            completed = False
            unbound_process_unsettled = False
            try:
                _write_new_file(
                    activation_root.descriptor,
                    _STARTING_MARKER_NAME,
                    canonical_json_bytes(start_intent.to_dict()),
                )
                start_written = True
                windows_flush_directory(activation_root.descriptor)
                runtime_fd = _open_directory_at(
                    activation_root.descriptor, runtime_name, create_new=True
                )
                profile_sid = _create_new_profile(profile_name)
                profile_created = True
                sid_string = _sid_string(profile_sid)
                profile_sid_string = sid_string
                _grant_runtime_authority(
                    sid=profile_sid,
                    restored_path=self._restored_path(request),
                    runtime_path=self._activation_root / runtime_name,
                    attempted=grants,
                )
                ready_path = self._activation_root / runtime_name / _READY_NAME
                job = self._create_job(job_name)
                process, identity = _launch_appcontainer_process(
                    self._command,
                    cwd=self._restored_path(request),
                    environment=_runtime_environment(
                        self._environment,
                        ready_path=ready_path,
                        token=request.request_id,
                        runtime_path=ready_path.parent,
                    ),
                    appcontainer_sid=profile_sid,
                    job=job,
                    termination_grace=self._termination_grace,
                )
                _assert_isolated_process(
                    process,
                    expected_sid=sid_string,
                    job=job,
                    restored_root=self._restored_path(request),
                    current_b_root=self._current_b_root,
                )
                _await_ready(
                    ready_path, request.request_id, process, self._startup_timeout
                )
                instance_id = _runtime_instance_identity(
                    request_id=request.request_id,
                    materialization_receipt_id=materialization.materialization_receipt_id,
                    process=identity,
                    profile_sid=sid_string,
                )
                receipt = PackageLegacyRuntimeActivationReceiptV1.create(
                    request,
                    materialization=materialization,
                    runtime_instance_id=instance_id,
                    runtime_lease_id=sha256(
                        f"legacy-lease:{instance_id}".encode()
                    ).hexdigest(),
                )
                marker = _ActivationMarker(
                    receipt=receipt,
                    process=identity,
                    profile_name=profile_name,
                    profile_sid=sid_string,
                    job_name=job_name,
                    current_b_root_identity=request.current_root_identity,
                    restore_namespace_id=request.restore_namespace_id,
                    sandbox_profile_digest=self._profile_digest,
                )
                _write_new_file(
                    activation_root.descriptor,
                    _ACTIVE_MARKER_NAME,
                    canonical_json_bytes(marker.to_dict()),
                )
                marker_written = True
                windows_flush_directory(activation_root.descriptor)
                _assert_isolated_process(
                    process,
                    expected_sid=sid_string,
                    job=job,
                    restored_root=self._restored_path(request),
                    current_b_root=self._current_b_root,
                )
                restore_root.assert_visible()
                current_b_root.assert_visible()
                activation_root.assert_visible()
                completed = True
                return receipt
            except PackageOfflineRestoreError:
                raise
            except Exception as exc:
                unbound_process_unsettled = isinstance(
                    exc, _UnsettledUnboundProcessError
                )
                raise _activation_error(
                    "Windows legacy runtime activation failed closed",
                    evidence_ref=materialization.materialization_receipt_id,
                ) from exc
            finally:
                if process is not None:
                    _close_handle(process)
                if profile_sid is not None:
                    _free_sid(profile_sid)
                cleanup_error: Exception | None = None
                try:
                    if not completed:
                        if runtime_fd is not None:
                            os.close(runtime_fd)
                            runtime_fd = None
                        if unbound_process_unsettled:
                            job = self._jobs.pop(job_name, None)
                            if job is not None:
                                _close_handle(job)
                            cleanup_error = _UnsettledUnboundProcessError(
                                "Windows unbound process remains unproven"
                            )
                        else:
                            cleanup_error = self._rollback_start(
                                activation_root,
                                runtime_name=runtime_name,
                                job_name=job_name,
                                profile_name=profile_name,
                                profile_sid=profile_sid_string,
                                profile_created=profile_created,
                                grants=grants,
                                marker_written=marker_written,
                                start_intent=(start_intent if start_written else None),
                            )
                finally:
                    if runtime_fd is not None:
                        os.close(runtime_fd)
                    os.close(payload_fd)
                    os.close(namespace_fd)
                    current_b_root.close()
                    restore_root.close()
                if cleanup_error is not None:
                    raise PackageOfflineRestoreError(
                        "Windows legacy runtime activation cleanup failed",
                        code="package_offline_restore_cleanup_failed",
                        evidence_ref=materialization.materialization_receipt_id,
                    ) from cleanup_error

    def review_incomplete_start(
        self,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> _ActivationStartIntentV1:
        """Read one exact pre-marker debt without creating or repairing state."""

        _validate_activation_inputs(
            request,
            materialization,
            store_id=self._store_id,
            legacy_runtime_version=self._legacy_runtime_version,
        )
        expected = _ActivationStartIntentV1.create(
            request,
            materialization,
            sandbox_profile_digest=self._profile_digest,
            profile_name=f"Loushang.PLC9B.{request.request_id[:32]}",
            job_name=f"Local\\Loushang.PLC9B.{request.request_id[:32]}",
        )
        try:
            with self._exclusive_activation_root(create_lock=False) as root:
                current = self._read_start_intent(root)
                if (
                    current != expected
                    or self._read_marker(root) is not None
                    or self._read_settlement_intent(root) is not None
                    or self._read_settlement_receipt(root) is not None
                ):
                    raise OSError("Windows activation has no exact pre-marker debt")
                self._open_bound_payload(request, materialization)
                root.assert_visible()
                return expected
        except Exception as exc:
            raise PackageOfflineRestoreError(
                "Windows legacy-runtime start debt could not be proven",
                code="package_offline_restore_cleanup_failed",
                evidence_ref=request.request_id,
            ) from exc

    def deactivate(self, receipt: PackageLegacyRuntimeActivationReceiptV1) -> None:
        self._deactivate(receipt)

    def deactivate_required(
        self, receipt: PackageLegacyRuntimeActivationReceiptV1
    ) -> None:
        """Require an active marker, then durably settle its exact runtime."""

        self._validate_settlement_input(receipt)
        try:
            with self._exclusive_activation_root() as root:
                marker = self._read_marker(root)
                if marker is None or marker.receipt != receipt:
                    raise OSError("Matching active Windows runtime is required")
                self._require_start_intent(root, marker)
                self._assert_settlement_owner(marker)
                intent = self._read_settlement_intent(root)
                if intent is None:
                    if self._read_settlement_receipt(root) is not None:
                        raise OSError("Windows settlement receipt has no intent")
                    _write_new_file(
                        root.descriptor,
                        _SETTLING_MARKER_NAME,
                        canonical_json_bytes(marker.to_dict()),
                    )
                    windows_flush_directory(root.descriptor)
                elif intent != marker:
                    raise OSError(
                        "Active Windows runtime differs from settlement intent"
                    )
        except Exception as exc:
            raise self._settlement_error(receipt) from exc
        self.settle_required(receipt)

    def settle_required(
        self, receipt: PackageLegacyRuntimeActivationReceiptV1
    ) -> PackageWindowsLegacyRuntimeSettlementReceiptV1:
        """Durably settle one activation and retry an interrupted exact intent."""

        self._validate_settlement_input(receipt)
        try:
            with self._exclusive_activation_root() as root:
                intent = self._read_settlement_intent(root)
                settled = self._read_settlement_receipt(root)
                if intent is None:
                    if settled is not None:
                        raise OSError("Windows settlement receipt has no intent")
                    marker = self._read_marker(root)
                    if marker is None or marker.receipt != receipt:
                        raise OSError("Matching active Windows runtime is required")
                    self._require_start_intent(root, marker)
                    self._assert_settlement_owner(marker)
                    _write_new_file(
                        root.descriptor,
                        _SETTLING_MARKER_NAME,
                        canonical_json_bytes(marker.to_dict()),
                    )
                    windows_flush_directory(root.descriptor)
                    intent = marker
                if intent.receipt != receipt:
                    raise OSError("Windows settlement intent changed")
                self._require_start_intent(root, intent)
                self._assert_settlement_owner(intent)
                expected = PackageWindowsLegacyRuntimeSettlementReceiptV1.create(intent)
                marker = self._read_marker(root)
                if settled is not None:
                    if settled != expected or marker is not None:
                        raise OSError("Windows settlement receipt changed")
                    self._assert_settlement_absent(intent)
                    root.assert_visible()
                    return settled
                if marker is not None and marker != intent:
                    raise OSError(
                        "Active Windows runtime differs from settlement intent"
                    )
                self._terminate_settlement_job(intent)
                self._assert_settlement_absent(intent)
                self._cleanup_authority(intent, root)
                self._assert_settlement_absent(intent)
                if marker is not None:
                    marker_bytes, marker_identity = _read_regular_file(
                        root.descriptor,
                        _ACTIVE_MARKER_NAME,
                        maximum_bytes=_MAX_MARKER_BYTES,
                    )
                    if (
                        marker_bytes != canonical_json_bytes(intent.to_dict())
                        or _native_identity(
                            windows_stat_at(root.descriptor, _ACTIVE_MARKER_NAME)
                        )
                        != marker_identity
                    ):
                        raise OSError(
                            "Windows runtime marker changed during settlement"
                        )
                    windows_unlink_at(root.descriptor, _ACTIVE_MARKER_NAME)
                    windows_flush_directory(root.descriptor)
                _write_new_file(
                    root.descriptor,
                    _SETTLED_RECEIPT_NAME,
                    canonical_json_bytes(expected.to_dict()),
                )
                windows_flush_directory(root.descriptor)
                if self._read_settlement_receipt(root) != expected:
                    raise OSError("Windows settlement receipt changed")
                root.assert_visible()
                return expected
        except Exception as exc:
            raise self._settlement_error(receipt) from exc

    def read_settlement(
        self, receipt: PackageLegacyRuntimeActivationReceiptV1
    ) -> PackageWindowsLegacyRuntimeSettlementReceiptV1:
        """Reopen exact settlement without creating missing lock state."""

        self._validate_settlement_input(receipt)
        try:
            with self._exclusive_activation_root(create_lock=False) as root:
                intent = self._read_settlement_intent(root)
                settled = self._read_settlement_receipt(root)
                if (
                    intent is None
                    or intent.receipt != receipt
                    or settled is None
                    or settled
                    != PackageWindowsLegacyRuntimeSettlementReceiptV1.create(intent)
                    or self._read_marker(root) is not None
                ):
                    raise OSError("Windows legacy-runtime settlement is incomplete")
                self._assert_settlement_owner(intent)
                self._require_start_intent(root, intent)
                self._assert_settlement_absent(intent)
                root.assert_visible()
                return settled
        except Exception as exc:
            raise self._settlement_error(receipt) from exc

    def _validate_settlement_input(
        self, receipt: PackageLegacyRuntimeActivationReceiptV1
    ) -> None:
        if not isinstance(receipt, PackageLegacyRuntimeActivationReceiptV1):
            raise TypeError("Legacy runtime activation receipt is required")
        if (
            receipt.store_id != self._store_id
            or receipt.legacy_runtime_version != self._legacy_runtime_version
        ):
            raise self._settlement_error(receipt)

    @staticmethod
    def _settlement_error(
        receipt: PackageLegacyRuntimeActivationReceiptV1,
    ) -> PackageOfflineRestoreError:
        return PackageOfflineRestoreError(
            "Windows legacy-runtime settlement could not be proven",
            code="package_offline_restore_cleanup_failed",
            evidence_ref=receipt.activation_receipt_id,
        )

    def _assert_settlement_owner(self, marker: _ActivationMarker) -> None:
        if (
            marker.receipt.store_id != self._store_id
            or marker.receipt.legacy_runtime_version != self._legacy_runtime_version
            or marker.sandbox_profile_digest != self._profile_digest
        ):
            raise OSError("Windows settlement owner or profile changed")
        current_b_root = _PinnedWindowsRoot.open(
            self._current_b_root, expected_identities=self._current_b_identities
        )
        try:
            if (
                _directory_identity(current_b_root.descriptor)
                != marker.current_b_root_identity
            ):
                raise OSError("Windows settlement B root changed")
            current_b_root.assert_visible()
        finally:
            current_b_root.close()

    def _terminate_settlement_job(self, marker: _ActivationMarker) -> None:
        with self._observed_settlement_job(marker.job_name) as job:
            if job is None or _job_active_processes(job) == 0:
                return
            process = _open_bound_process(marker.process)
            try:
                _assert_isolated_process(
                    process,
                    expected_sid=marker.profile_sid,
                    job=job,
                    restored_root=self._restored_path_from_marker(marker),
                    current_b_root=self._current_b_root,
                )
                _terminate_job(job, process, self._termination_grace)
            finally:
                _close_handle(process)

    def _assert_settlement_absent(self, marker: _ActivationMarker) -> None:
        self._assert_settlement_owner(marker)
        with self._observed_settlement_job(marker.job_name) as job:
            if job is not None and _job_active_processes(job) != 0:
                raise OSError("Windows legacy-runtime Job remains active")
        if _bound_process_is_active(marker.process):
            raise OSError("Windows legacy-runtime process remains active")

    @contextmanager
    def _observed_settlement_job(self, name: str) -> Iterator[int | None]:
        owned = self._jobs.get(name)
        if owned is not None:
            yield owned
            return
        try:
            observed = _open_job(name)
        except OSError as exc:
            if getattr(exc, "winerror", None) == _ERROR_FILE_NOT_FOUND:
                yield None
                return
            raise
        try:
            yield observed
        finally:
            _close_handle(observed)

    def _deactivate(
        self,
        receipt: PackageLegacyRuntimeActivationReceiptV1,
    ) -> None:
        if not isinstance(receipt, PackageLegacyRuntimeActivationReceiptV1):
            raise TypeError("Legacy runtime activation receipt is required")
        if (
            receipt.store_id != self._store_id
            or receipt.legacy_runtime_version != self._legacy_runtime_version
        ):
            raise PackageOfflineRestoreError(
                "Windows legacy-runtime cleanup owner changed",
                code="package_offline_restore_cleanup_failed",
                evidence_ref=receipt.activation_receipt_id,
            )
        try:
            with self._exclusive_activation_root() as activation_root:
                marker = self._read_marker(activation_root)
                if marker is None:
                    if (
                        self._read_start_intent(activation_root) is not None
                        and self._read_settlement_receipt(activation_root) is None
                    ):
                        raise OSError("Windows legacy-runtime start debt is unresolved")
                    job_name = f"Local\\Loushang.PLC9B.{receipt.request_id[:32]}"
                    owned_job = self._jobs.get(job_name)
                    if owned_job is not None:
                        if _job_active_processes(owned_job) != 0:
                            raise OSError("Windows legacy-runtime Job remains active")
                        self._jobs.pop(job_name)
                        _close_handle(owned_job)
                    return
                if marker.receipt != receipt:
                    raise OSError("Windows runtime cleanup receipt changed")
                start = self._read_start_intent(activation_root)
                if start is not None and not start.matches_marker(marker):
                    raise OSError("Windows runtime start intent changed")
                self._assert_settlement_owner(marker)
                process = _open_bound_process(marker.process)
                try:
                    with self._observed_settlement_job(marker.job_name) as job:
                        if job is None:
                            raise OSError("Windows legacy-runtime Job is missing")
                        _assert_isolated_process(
                            process,
                            expected_sid=marker.profile_sid,
                            job=job,
                            restored_root=self._restored_path_from_marker(marker),
                            current_b_root=self._current_b_root,
                        )
                        _terminate_job(job, process, self._termination_grace)
                finally:
                    _close_handle(process)
                marker_bytes, marker_identity = _read_regular_file(
                    activation_root.descriptor,
                    _ACTIVE_MARKER_NAME,
                    maximum_bytes=_MAX_MARKER_BYTES,
                )
                if marker_bytes != canonical_json_bytes(marker.to_dict()):
                    raise OSError("Windows runtime marker changed during cleanup")
                if (
                    _native_identity(
                        windows_stat_at(activation_root.descriptor, _ACTIVE_MARKER_NAME)
                    )
                    != marker_identity
                ):
                    raise OSError("Windows runtime marker identity changed")
                windows_unlink_at(activation_root.descriptor, _ACTIVE_MARKER_NAME)
                self._cleanup_authority(marker, activation_root)
                if start is not None:
                    self._clear_start_intent(activation_root, start)
                windows_flush_directory(activation_root.descriptor)
        except Exception as exc:
            if isinstance(exc, PackageOfflineRestoreError) and exc.code == (
                "package_offline_restore_cleanup_failed"
            ):
                raise
            raise PackageOfflineRestoreError(
                "Windows legacy runtime deactivation could not be proven",
                code="package_offline_restore_cleanup_failed",
                evidence_ref=receipt.activation_receipt_id,
            ) from exc

    def _open_bound_payload(
        self,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
        *,
        keep_open: bool = False,
    ) -> tuple[_PinnedWindowsRoot, _PinnedWindowsRoot, int, int] | None:
        restore_root: _PinnedWindowsRoot | None = None
        current_b_root: _PinnedWindowsRoot | None = None
        namespace_fd: int | None = None
        payload_fd: int | None = None
        try:
            restore_root = _PinnedWindowsRoot.open(
                self._restore_root, expected_identities=self._restore_identities
            )
            current_b_root = _PinnedWindowsRoot.open(
                self._current_b_root, expected_identities=self._current_b_identities
            )
            if (
                _directory_identity(current_b_root.descriptor)
                != request.current_root_identity
            ):
                raise OSError("Current B authority identity changed")
            namespace_fd = _open_directory_at(
                restore_root.descriptor, request.restore_namespace_id
            )
            if set(windows_listdir_at(namespace_fd)) != {_PAYLOAD_NAME, "receipt.json"}:
                raise OSError("Windows restore namespace membership changed")
            durable, _identity = _read_regular_file(
                namespace_fd, "receipt.json", maximum_bytes=_MAX_MARKER_BYTES
            )
            recorded = PackageOfflineRestoreMaterializationReceiptV1.from_dict(
                _strict_json_object(durable, name="restore receipt")
            )
            if (
                durable != canonical_json_bytes(recorded.to_dict())
                or recorded != materialization
            ):
                raise OSError("Windows restore receipt changed")
            payload_fd = _open_directory_at(namespace_fd, _PAYLOAD_NAME)
            if (
                _directory_identity(payload_fd)
                != materialization.restored_root_identity
            ):
                raise OSError("Windows restored root identity changed")
            inspected = _inspect_tree(
                payload_fd,
                maximum_entries=self._maximum_entries,
                maximum_bytes=self._maximum_bytes,
                maximum_depth=self._maximum_depth,
            )
            if (
                inspected.tree_digest != materialization.snapshot_tree_digest
                or inspected.entry_count != materialization.entry_count
                or inspected.byte_count != materialization.byte_count
            ):
                raise OSError("Windows restored tree changed before activation")
            restore_root.assert_visible()
            current_b_root.assert_visible()
            if keep_open:
                result = (restore_root, current_b_root, namespace_fd, payload_fd)
                restore_root = None
                current_b_root = None
                namespace_fd = None
                payload_fd = None
                return result
            return None
        except Exception as exc:
            raise _activation_error(
                "Windows restored authority is not activation-ready",
                evidence_ref=materialization.materialization_receipt_id,
            ) from exc
        finally:
            if payload_fd is not None:
                os.close(payload_fd)
            if namespace_fd is not None:
                os.close(namespace_fd)
            if current_b_root is not None:
                current_b_root.close()
            if restore_root is not None:
                restore_root.close()

    def _restored_path(self, request: PackageOfflineRestoreRequestV1) -> Path:
        return self._restore_root / request.restore_namespace_id / _PAYLOAD_NAME

    @contextmanager
    def _exclusive_activation_root(
        self, *, create_lock: bool = True
    ) -> Iterator[_PinnedWindowsRoot]:
        with self._thread_lock:
            root = _PinnedWindowsRoot.open(
                self._activation_root, expected_identities=self._activation_identities
            )
            lock_fd: int | None = None
            try:
                created = False
                try:
                    lock_fd = open_windows_regular_file_at(
                        root.descriptor, _LOCK_NAME, create_new=False, write=True
                    )
                except FileNotFoundError:
                    if not create_lock:
                        raise
                    try:
                        lock_fd = open_windows_regular_file_at(
                            root.descriptor, _LOCK_NAME, create_new=True, write=True
                        )
                        created = True
                        os.write(lock_fd, b"0")
                        os.fsync(lock_fd)
                        windows_flush_directory(root.descriptor)
                    except FileExistsError:
                        lock_fd = open_windows_regular_file_at(
                            root.descriptor, _LOCK_NAME, create_new=False, write=True
                        )
                if not created:
                    deadline = time.monotonic() + 5.0
                    while (
                        os.fstat(lock_fd).st_size == 0 and time.monotonic() < deadline
                    ):
                        time.sleep(0.001)
                lock_stat = os.fstat(lock_fd)
                if lock_stat.st_nlink != 1 or lock_stat.st_size != 1:
                    raise OSError("Windows activation lock is untrusted")
                os.lseek(lock_fd, 0, os.SEEK_SET)
                _msvcrt.locking(lock_fd, _msvcrt.LK_LOCK, 1)
                root.assert_visible()
                yield root
            finally:
                if lock_fd is not None:
                    with suppress(OSError):
                        os.lseek(lock_fd, 0, os.SEEK_SET)
                        _msvcrt.locking(lock_fd, _msvcrt.LK_UNLCK, 1)
                    os.close(lock_fd)
                root.close()

    def _read_marker(self, root: _PinnedWindowsRoot) -> _ActivationMarker | None:
        if _ACTIVE_MARKER_NAME not in windows_listdir_at(root.descriptor):
            return None
        payload, _identity = _read_regular_file(
            root.descriptor, _ACTIVE_MARKER_NAME, maximum_bytes=_MAX_MARKER_BYTES
        )
        marker = _ActivationMarker.from_dict(
            _strict_json_object(payload, name="Windows runtime marker")
        )
        if payload != canonical_json_bytes(marker.to_dict()):
            raise OSError("Windows runtime marker is not canonical")
        return marker

    def _read_start_intent(
        self, root: _PinnedWindowsRoot
    ) -> _ActivationStartIntentV1 | None:
        if _STARTING_MARKER_NAME not in windows_listdir_at(root.descriptor):
            return None
        payload, _identity = _read_regular_file(
            root.descriptor, _STARTING_MARKER_NAME, maximum_bytes=_MAX_MARKER_BYTES
        )
        intent = _ActivationStartIntentV1.from_dict(
            _strict_json_object(payload, name="Windows runtime start intent")
        )
        if payload != canonical_json_bytes(intent.to_dict()):
            raise OSError("Windows runtime start intent is not canonical")
        return intent

    def _require_start_intent(
        self, root: _PinnedWindowsRoot, marker: _ActivationMarker
    ) -> _ActivationStartIntentV1:
        intent = self._read_start_intent(root)
        if intent is None or not intent.matches_marker(marker):
            raise OSError("Windows runtime start intent is missing or changed")
        return intent

    def _clear_start_intent(
        self, root: _PinnedWindowsRoot, expected: _ActivationStartIntentV1
    ) -> None:
        payload, identity = _read_regular_file(
            root.descriptor, _STARTING_MARKER_NAME, maximum_bytes=_MAX_MARKER_BYTES
        )
        if (
            payload != canonical_json_bytes(expected.to_dict())
            or self._read_start_intent(root) != expected
            or _native_identity(windows_stat_at(root.descriptor, _STARTING_MARKER_NAME))
            != identity
        ):
            raise OSError("Windows runtime start intent changed during cleanup")
        windows_unlink_at(root.descriptor, _STARTING_MARKER_NAME)
        windows_flush_directory(root.descriptor)

    def _read_settlement_intent(
        self, root: _PinnedWindowsRoot
    ) -> _ActivationMarker | None:
        if _SETTLING_MARKER_NAME not in windows_listdir_at(root.descriptor):
            return None
        payload, _identity = _read_regular_file(
            root.descriptor, _SETTLING_MARKER_NAME, maximum_bytes=_MAX_MARKER_BYTES
        )
        marker = _ActivationMarker.from_dict(
            _strict_json_object(payload, name="Windows runtime settlement intent")
        )
        if payload != canonical_json_bytes(marker.to_dict()):
            raise OSError("Windows settlement intent is not canonical")
        return marker

    def _read_settlement_receipt(
        self, root: _PinnedWindowsRoot
    ) -> PackageWindowsLegacyRuntimeSettlementReceiptV1 | None:
        if _SETTLED_RECEIPT_NAME not in windows_listdir_at(root.descriptor):
            return None
        payload, _identity = _read_regular_file(
            root.descriptor, _SETTLED_RECEIPT_NAME, maximum_bytes=_MAX_MARKER_BYTES
        )
        receipt = PackageWindowsLegacyRuntimeSettlementReceiptV1.from_dict(
            _strict_json_object(payload, name="Windows runtime settlement receipt")
        )
        if payload != canonical_json_bytes(receipt.to_dict()):
            raise OSError("Windows settlement receipt is not canonical")
        return receipt

    def _create_job(self, name: str) -> int:
        job = _create_or_open_job(name)
        self._jobs[name] = job
        return job

    def _rollback_start(
        self,
        activation_root: _PinnedWindowsRoot,
        *,
        runtime_name: str,
        job_name: str,
        profile_name: str,
        profile_sid: str | None,
        profile_created: bool,
        grants: Sequence[tuple[Path, bool]],
        marker_written: bool,
        start_intent: _ActivationStartIntentV1 | None,
    ) -> Exception | None:
        try:
            job = self._jobs.pop(job_name, None)
            if job is not None:
                try:
                    if _job_active_processes(job) != 0:
                        _terminate_job(job, None, self._termination_grace)
                    _await_empty_job(job, self._termination_grace)
                finally:
                    _close_handle(job)
            if marker_written and _ACTIVE_MARKER_NAME in windows_listdir_at(
                activation_root.descriptor
            ):
                windows_unlink_at(activation_root.descriptor, _ACTIVE_MARKER_NAME)
            if profile_sid is not None:
                for path, recursive in reversed(grants):
                    _revoke_path(path, profile_sid, recursive=recursive)
            _remove_runtime_dir(activation_root.descriptor, runtime_name)
            if profile_created:
                _delete_profile(profile_name)
            if start_intent is not None:
                self._clear_start_intent(activation_root, start_intent)
            return None
        except Exception as exc:
            return exc

    def _cleanup_authority(
        self,
        marker: _ActivationMarker,
        activation_root: _PinnedWindowsRoot,
    ) -> None:
        runtime_name = f"{_RUNTIME_PREFIX}{marker.receipt.request_id}"
        runtime_path = self._activation_root / runtime_name
        runtime_present = runtime_name in windows_listdir_at(activation_root.descriptor)
        grants = _authority_paths(
            restored_path=self._restored_path_from_marker(marker),
            runtime_path=runtime_path,
        )
        for path, recursive in reversed(grants):
            # A prior settlement attempt may have removed this private runtime
            # directory before its terminal receipt was published.
            if path == runtime_path and not runtime_present:
                continue
            _revoke_path(path, marker.profile_sid, recursive=recursive)
        _remove_runtime_dir(activation_root.descriptor, runtime_name)
        _delete_profile(marker.profile_name)
        job = self._jobs.pop(marker.job_name, None)
        if job is not None:
            _close_handle(job)

    def _restored_path_from_marker(self, marker: _ActivationMarker) -> Path:
        return self._restore_root / marker.restore_namespace_id / _PAYLOAD_NAME


def _validate_activation_inputs(
    request: PackageOfflineRestoreRequestV1,
    materialization: PackageOfflineRestoreMaterializationReceiptV1,
    *,
    store_id: str,
    legacy_runtime_version: str,
) -> None:
    if not isinstance(request, PackageOfflineRestoreRequestV1):
        raise TypeError("Package offline-restore request is required")
    if not isinstance(materialization, PackageOfflineRestoreMaterializationReceiptV1):
        raise TypeError("Package restore materialization receipt is required")
    if (
        request.store_id != store_id
        or request.legacy_runtime_version != legacy_runtime_version
        or materialization.request_id != request.request_id
        or materialization.store_id != request.store_id
        or materialization.snapshot_receipt_id != request.snapshot_receipt_id
        or materialization.snapshot_evidence_id != request.snapshot_evidence_id
        or materialization.snapshot_id != request.snapshot_id
        or materialization.snapshot_revision != request.snapshot_revision
        or materialization.restore_namespace_id != request.restore_namespace_id
        or materialization.legacy_root_identity != request.legacy_root_identity
        or materialization.snapshot_tree_digest != request.snapshot_tree_digest
        or materialization.state_manifest_digest != request.state_manifest_digest
        or materialization.entry_count != request.snapshot_entry_count
        or materialization.byte_count != request.snapshot_byte_count
        or not materialization.legacy_snapshot_exact
        or not materialization.b_namespace_unreachable
    ):
        raise _activation_error(
            "Windows activation input does not match the restore request",
            evidence_ref=materialization.materialization_receipt_id,
        )


def _validated_command(command: Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, (str, bytes)):
        raise TypeError("Windows legacy runtime command must be an argument sequence")
    values = tuple(command)
    if not values or len(values) > _MAX_COMMAND_ARGUMENTS:
        raise ValueError("Windows legacy runtime command is invalid")
    if any(
        not isinstance(value, str) or not value or "\x00" in value for value in values
    ):
        raise ValueError("Windows legacy runtime command is invalid")
    if sum(len(value.encode("utf-8")) for value in values) > _MAX_COMMAND_BYTES:
        raise ValueError("Windows legacy runtime command is too large")
    return values


def _validated_environment(
    environment: Mapping[str, str] | Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    items = (
        tuple(environment.items())
        if isinstance(environment, Mapping)
        else tuple(environment)
    )
    if len(items) > _MAX_ENVIRONMENT_ENTRIES:
        raise ValueError("Windows legacy runtime environment is too large")
    normalized: dict[str, str] = {}
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError("Windows legacy runtime environment is invalid")
        key, value = item
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or "=" in key
            or "\x00" in key
            or "\x00" in value
        ):
            raise ValueError("Windows legacy runtime environment is invalid")
        normalized[key] = value
    ordered = tuple(sorted(normalized.items(), key=lambda item: item[0].casefold()))
    if (
        sum(len(key.encode()) + len(value.encode()) for key, value in ordered)
        > _MAX_ENVIRONMENT_BYTES
    ):
        raise ValueError("Windows legacy runtime environment is too large")
    return ordered


def _runtime_environment(
    values: Sequence[tuple[str, str]],
    *,
    ready_path: Path,
    token: str,
    runtime_path: Path,
) -> dict[str, str]:
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    system_drive = os.environ.get("SYSTEMDRIVE", Path(system_root).drive or "C:")
    user_profile = os.environ.get(
        "USERPROFILE", str(Path(system_drive + os.sep) / "Users" / "Default")
    )
    environment = {
        "COMSPEC": os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
        "APPDATA": os.environ.get(
            "APPDATA", str(Path(user_profile) / "AppData" / "Roaming")
        ),
        "HOMEDRIVE": os.environ.get("HOMEDRIVE", system_drive),
        "HOMEPATH": os.environ.get("HOMEPATH", r"\Users\Default"),
        "LOCALAPPDATA": os.environ.get(
            "LOCALAPPDATA", str(Path(user_profile) / "AppData" / "Local")
        ),
        "OS": "Windows_NT",
        "PATH": os.environ.get("PATH", r"C:\Windows\System32"),
        "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
        "PROGRAMDATA": os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
        "SYSTEMDRIVE": system_drive,
        "SYSTEMROOT": system_root,
        "TEMP": str(runtime_path),
        "TMP": str(runtime_path),
        "USERPROFILE": user_profile,
        "WINDIR": os.environ.get("WINDIR", system_root),
        **dict(values),
    }
    environment[_READY_PATH_ENV] = str(ready_path)
    environment[_READY_TOKEN_ENV] = token
    return environment


def _create_new_profile(profile: str) -> int:
    if not _SAFE_PROFILE.fullmatch(profile):
        raise ValueError("Windows AppContainer profile name is invalid")
    pointer = ctypes.c_void_p()
    result = _userenv().CreateAppContainerProfile(
        profile,
        profile,
        "Loushang isolated legacy Package runtime",
        None,
        0,
        ctypes.byref(pointer),
    )
    if result == 0:
        if pointer.value is None:
            with suppress(OSError):
                _delete_profile(profile)
            raise OSError("Windows AppContainer SID is unavailable")
        return int(pointer.value)
    if result & 0xFFFFFFFF == 0x80070000 | _ERROR_ALREADY_EXISTS:
        raise OSError("Windows AppContainer profile name is already owned")
    raise OSError(result, "Could not create Windows AppContainer profile")


def _delete_profile(profile: str) -> None:
    result = _userenv().DeleteAppContainerProfile(profile)
    if result != 0 and result & 0xFFFF not in {
        _ERROR_FILE_NOT_FOUND,
        _ERROR_PATH_NOT_FOUND,
    }:
        raise OSError(result, "Could not delete Windows AppContainer profile")


def _grant_runtime_authority(
    *,
    sid: int,
    restored_path: Path,
    runtime_path: Path,
    attempted: list[tuple[Path, bool]],
) -> None:
    for path, recursive in _authority_paths(
        restored_path=restored_path, runtime_path=runtime_path
    ):
        permissions = (
            _GENERIC_ALL
            if path == runtime_path
            else (
                _GENERIC_READ | _GENERIC_EXECUTE if recursive else _FILE_TRAVERSE_READ
            )
        )
        # Record before the native write: it may publish the ACL and still fail.
        attempted.append((path, recursive))
        _mutate_path_acl(
            path,
            sid,
            access_mode=_GRANT_ACCESS,
            permissions=permissions,
            recursive=recursive,
        )


def _authority_paths(
    *,
    restored_path: Path,
    runtime_path: Path,
) -> list[tuple[Path, bool]]:
    ordered: list[tuple[Path, bool]] = []
    seen: set[str] = set()
    for target in (restored_path, runtime_path):
        ancestors = list(target.parents)
        for path in reversed(ancestors[:-1]):
            key = os.path.normcase(str(path))
            if key not in seen:
                ordered.append((path, False))
                seen.add(key)
        key = os.path.normcase(str(target))
        if key not in seen:
            ordered.append((target, True))
            seen.add(key)
    return ordered


def _revoke_path(path: Path, sid: str, *, recursive: bool) -> None:
    pointer = _string_sid(sid)
    try:
        _mutate_path_acl(
            path,
            pointer,
            access_mode=_REVOKE_ACCESS,
            permissions=0,
            recursive=recursive,
        )
    finally:
        _local_free(pointer)


def _mutate_path_acl(
    path: Path,
    sid: int,
    *,
    access_mode: int,
    permissions: int,
    recursive: bool,
) -> None:
    security_descriptor = ctypes.c_void_p()
    old_acl = ctypes.c_void_p()
    result = _advapi32().GetNamedSecurityInfoW(
        str(path),
        _SE_FILE_OBJECT,
        _DACL_SECURITY_INFORMATION,
        None,
        None,
        ctypes.byref(old_acl),
        None,
        ctypes.byref(security_descriptor),
    )
    if result != 0:
        raise OSError(result, f"Could not read Windows ACL for {path.name}")
    new_acl = ctypes.c_void_p()
    try:
        entry = _EXPLICIT_ACCESS_W()
        entry.grfAccessPermissions = permissions
        entry.grfAccessMode = access_mode
        entry.grfInheritance = _SUB_CONTAINERS_AND_OBJECTS_INHERIT if recursive else 0
        entry.Trustee.TrusteeForm = _TRUSTEE_IS_SID
        entry.Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
        entry.Trustee.ptstrName = ctypes.cast(sid, _wintypes.LPWSTR)
        result = _advapi32().SetEntriesInAclW(
            1, ctypes.byref(entry), old_acl, ctypes.byref(new_acl)
        )
        if result != 0:
            raise OSError(result, f"Could not compose Windows ACL for {path.name}")
        result = _advapi32().SetNamedSecurityInfoW(
            str(path),
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            new_acl,
            None,
        )
        if result != 0:
            raise OSError(result, f"Could not publish Windows ACL for {path.name}")
    finally:
        if new_acl.value:
            _local_free(int(new_acl.value))
        if security_descriptor.value:
            _local_free(int(security_descriptor.value))


def _create_or_open_job(name: str) -> int:
    handle = _kernel32().CreateJobObjectW(None, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _close_handle(int(handle))
        raise OSError("Windows legacy-runtime Job name is already owned")
    limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = (
        _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    if not _kernel32().SetInformationJobObject(
        handle,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        error = ctypes.get_last_error()
        _close_handle(int(handle))
        raise ctypes.WinError(error)
    return int(handle)


def _open_job(name: str) -> int:
    handle = _kernel32().OpenJobObjectW(0x001F001F, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _job_active_processes(job: int) -> int:
    accounting = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    if not _kernel32().QueryInformationJobObject(
        job,
        _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
        ctypes.byref(accounting),
        ctypes.sizeof(accounting),
        None,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(accounting.ActiveProcesses)


def _await_empty_job(job: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while _job_active_processes(job) != 0:
        if time.monotonic() >= deadline:
            raise TimeoutError("Windows legacy-runtime Job did not settle")
        time.sleep(0.01)


def _launch_appcontainer_process(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    appcontainer_sid: int,
    job: int,
    termination_grace: float,
) -> tuple[int, _ProcessIdentity]:
    size = ctypes.c_size_t()
    _kernel32().InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(size.value)
    attribute_list = ctypes.cast(buffer, ctypes.c_void_p)
    if not _kernel32().InitializeProcThreadAttributeList(
        attribute_list, 2, 0, ctypes.byref(size)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    security = _SECURITY_CAPABILITIES()
    security.AppContainerSid = appcontainer_sid
    security.Capabilities = None
    security.CapabilityCount = 0
    security.Reserved = 0
    # Attribute values must remain alive through process creation.
    job_list = (_wintypes.HANDLE * 1)(job)
    process_info = _PROCESS_INFORMATION()
    try:
        if not _kernel32().UpdateProcThreadAttribute(
            attribute_list,
            0,
            _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(security),
            ctypes.sizeof(security),
            None,
            None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not _kernel32().UpdateProcThreadAttribute(
            attribute_list,
            0,
            _PROC_THREAD_ATTRIBUTE_JOB_LIST,
            ctypes.byref(job_list),
            ctypes.sizeof(job_list),
            None,
            None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        startup = _STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.lpAttributeList = attribute_list
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        environment_block = ctypes.create_unicode_buffer(
            "\x00".join(
                f"{key}={value}"
                for key, value in sorted(
                    environment.items(), key=lambda item: item[0].casefold()
                )
            )
            + "\x00\x00"
        )
        # Security capabilities create the AppContainer token during process
        # creation; there is no preexisting primary token to pass as a user.
        if not _kernel32().CreateProcessW(
            command[0],
            command_line,
            None,
            None,
            False,
            _EXTENDED_STARTUPINFO_PRESENT
            | _CREATE_UNICODE_ENVIRONMENT
            | _CREATE_SUSPENDED
            | _CREATE_NO_WINDOW,
            environment_block,
            str(cwd),
            ctypes.byref(startup),
            ctypes.byref(process_info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        process = int(process_info.hProcess)
        assigned_to_job = False
        try:
            in_job = _wintypes.BOOL()
            if (
                not _kernel32().IsProcessInJob(
                    process_info.hProcess, job, ctypes.byref(in_job)
                )
                or not in_job.value
            ):
                raise OSError("Windows process was not assigned to its creation Job")
            assigned_to_job = True
            identity = _process_identity(process, int(process_info.dwProcessId))
            if _kernel32().ResumeThread(process_info.hThread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            return process, identity
        except Exception as exc:
            try:
                if not assigned_to_job:
                    _kernel32().TerminateProcess(process_info.hProcess, 1)
                    result = _kernel32().WaitForSingleObject(
                        process_info.hProcess, int(termination_grace * 1000)
                    )
                    if result != _WAIT_OBJECT_0:
                        raise _UnsettledUnboundProcessError(
                            "Windows unbound process escaped cleanup"
                        ) from exc
            finally:
                _close_handle(process)
            raise
        finally:
            _close_handle(int(process_info.hThread))
    finally:
        _kernel32().DeleteProcThreadAttributeList(attribute_list)


def _assert_isolated_process(
    process: int,
    *,
    expected_sid: str,
    job: int,
    restored_root: Path,
    current_b_root: Path,
) -> None:
    if not _process_active(process):
        raise OSError("Windows legacy runtime is not live")
    in_job = _wintypes.BOOL()
    if (
        not _kernel32().IsProcessInJob(process, job, ctypes.byref(in_job))
        or not in_job.value
    ):
        raise OSError("Windows legacy runtime escaped its Job Object")
    token = _wintypes.HANDLE()
    if not _advapi32().OpenProcessToken(
        process,
        _TOKEN_QUERY | _TOKEN_DUPLICATE | _TOKEN_IMPERSONATE,
        ctypes.byref(token),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        token_value = int(token.value or 0)
        is_appcontainer = _token_dword(token_value, _TOKEN_IS_APP_CONTAINER)
        if is_appcontainer != 1:
            raise OSError("Windows legacy runtime lacks an AppContainer token")
        sid_buffer = _token_buffer(token_value, _TOKEN_APP_CONTAINER_SID)
        sid_pointer = ctypes.c_void_p.from_buffer(sid_buffer).value
        if sid_pointer is None or _sid_string(sid_pointer) != expected_sid:
            raise OSError("Windows legacy runtime AppContainer SID changed")
        capability_buffer = _token_buffer(token_value, _TOKEN_CAPABILITIES)
        capability_count = ctypes.c_uint32.from_buffer(capability_buffer).value
        if capability_count != 0:
            raise OSError("Windows legacy runtime unexpectedly has capabilities")
        duplicate = _wintypes.HANDLE()
        if not _advapi32().DuplicateToken(
            token, _SECURITY_IMPERSONATION, ctypes.byref(duplicate)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not _advapi32().ImpersonateLoggedOnUser(duplicate):
                raise ctypes.WinError(ctypes.get_last_error())
            restored = _kernel32().CreateFileW(
                str(restored_root),
                _GENERIC_READ,
                _FILE_SHARE_ALL,
                None,
                _OPEN_EXISTING,
                _FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
            if restored == _INVALID_HANDLE_VALUE:
                raise ctypes.WinError(ctypes.get_last_error())
            _close_handle(int(restored))
            handle = _kernel32().CreateFileW(
                str(current_b_root),
                _FILE_READ_ATTRIBUTES,
                _FILE_SHARE_ALL,
                None,
                _OPEN_EXISTING,
                _FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
            error = ctypes.get_last_error()
            if handle != _INVALID_HANDLE_VALUE:
                _close_handle(int(handle))
                raise OSError("Current B authority is reachable in Windows sandbox")
            if error not in {
                _ERROR_ACCESS_DENIED,
                _ERROR_FILE_NOT_FOUND,
                _ERROR_PATH_NOT_FOUND,
            }:
                raise ctypes.WinError(error)
        finally:
            _advapi32().RevertToSelf()
            _close_handle(int(duplicate.value or 0))
    finally:
        _close_handle(int(token.value or 0))


def _open_bound_process(identity: _ProcessIdentity) -> int:
    handle = _kernel32().OpenProcess(
        _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE,
        False,
        identity.pid,
    )
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    process = int(handle)
    if _process_identity(process, identity.pid) != identity or not _process_active(
        process
    ):
        _close_handle(process)
        raise OSError("Windows legacy runtime process identity changed")
    return process


def _bound_process_is_active(identity: _ProcessIdentity) -> bool:
    handle = _kernel32().OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE,
        False,
        identity.pid,
    )
    if not handle:
        if ctypes.get_last_error() == _ERROR_INVALID_PARAMETER:
            return False
        raise ctypes.WinError(ctypes.get_last_error())
    process = int(handle)
    try:
        return _process_identity(process, identity.pid) == identity and _process_active(
            process
        )
    finally:
        _close_handle(process)


def _process_identity(process: int, pid: int) -> _ProcessIdentity:
    created = _FILETIME()
    exited = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    if not _kernel32().GetProcessTimes(
        process,
        ctypes.byref(created),
        ctypes.byref(exited),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    value = int(created.dwHighDateTime) << 32 | int(created.dwLowDateTime)
    return _ProcessIdentity(pid=pid, creation_time=value)


def _process_active(process: int) -> bool:
    return _process_exit_code(process) == _STILL_ACTIVE


def _process_exit_code(process: int) -> int:
    code = _wintypes.DWORD()
    if not _kernel32().GetExitCodeProcess(process, ctypes.byref(code)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(code.value)


def _terminate_job(job: int, process: int | None, timeout: float) -> None:
    if not _kernel32().TerminateJobObject(job, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    if process is not None:
        result = _kernel32().WaitForSingleObject(process, int(timeout * 1000))
        if result == _WAIT_TIMEOUT:
            raise TimeoutError("Windows legacy runtime did not terminate")
        if result != _WAIT_OBJECT_0:
            raise ctypes.WinError(ctypes.get_last_error())


def _await_ready(path: Path, token: str, process: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            exit_code = _process_exit_code(process)
            if exit_code != _STILL_ACTIVE:
                raise OSError(
                    "Windows legacy runtime exited before readiness "
                    f"with status 0x{exit_code:08x}"
                )
            time.sleep(0.025)
            continue
        if len(payload) > _MAX_READY_BYTES:
            raise OSError("Windows legacy runtime readiness is oversized")
        normalized = payload.strip()
        if not normalized:
            exit_code = _process_exit_code(process)
            if exit_code != _STILL_ACTIVE:
                raise OSError(
                    "Windows legacy runtime exited before readiness "
                    f"with status 0x{exit_code:08x}"
                )
            time.sleep(0.025)
            continue
        if normalized != token.encode("ascii"):
            raise OSError("Windows legacy runtime readiness changed")
        exit_code = _process_exit_code(process)
        if exit_code != _STILL_ACTIVE:
            raise OSError(
                "Windows legacy runtime exited after readiness "
                f"with status 0x{exit_code:08x}"
            )
        return
    raise TimeoutError("Windows legacy runtime readiness timed out")


def _remove_runtime_dir(activation_fd: int, name: str) -> None:
    if name not in windows_listdir_at(activation_fd):
        return
    metadata = windows_stat_at(activation_fd, name)
    if not stat.S_ISDIR(metadata.st_mode):
        raise OSError("Windows runtime IPC authority changed type")
    directory = _open_directory_at(activation_fd, name, share_delete=True)
    try:
        _remove_directory_contents(directory)
    finally:
        os.close(directory)
    windows_rmdir_at(activation_fd, name)


def _runtime_instance_identity(
    *,
    request_id: str,
    materialization_receipt_id: str,
    process: _ProcessIdentity,
    profile_sid: str,
) -> str:
    return sha256(
        canonical_json_bytes(
            {
                "materializationReceiptId": materialization_receipt_id,
                "processCreationTime": process.creation_time,
                "processPid": process.pid,
                "profileSid": profile_sid,
                "requestId": request_id,
                "runtimeIdentityVersion": 1,
            }
        )
    ).hexdigest()


def _token_dword(token: int, information_class: int) -> int:
    value = _wintypes.DWORD()
    returned = _wintypes.DWORD()
    if not _advapi32().GetTokenInformation(
        token,
        information_class,
        ctypes.byref(value),
        ctypes.sizeof(value),
        ctypes.byref(returned),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(value.value)


def _token_buffer(token: int, information_class: int) -> ctypes.Array[Any]:
    required = _wintypes.DWORD()
    _advapi32().GetTokenInformation(
        token, information_class, None, 0, ctypes.byref(required)
    )
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or required.value == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(required.value)
    if not _advapi32().GetTokenInformation(
        token,
        information_class,
        buffer,
        required.value,
        ctypes.byref(required),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer


def _sid_string(sid: int) -> str:
    pointer = _wintypes.LPWSTR()
    if not _advapi32().ConvertSidToStringSidW(sid, ctypes.byref(pointer)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return str(pointer.value)
    finally:
        _local_free(ctypes.cast(pointer, ctypes.c_void_p).value)


def _string_sid(value: str) -> int:
    pointer = ctypes.c_void_p()
    if not _advapi32().ConvertStringSidToSidW(value, ctypes.byref(pointer)):
        raise ctypes.WinError(ctypes.get_last_error())
    if pointer.value is None:
        raise OSError("Windows SID conversion returned no SID")
    return int(pointer.value)


def _free_sid(pointer: int) -> None:
    result = _advapi32().FreeSid(pointer)
    if result:
        raise ctypes.WinError(ctypes.get_last_error())


def _local_free(pointer: int | None) -> None:
    if pointer:
        _kernel32().LocalFree(pointer)


def _close_handle(handle: int) -> None:
    if handle and handle != _INVALID_HANDLE_VALUE:
        _kernel32().CloseHandle(handle)


_KERNEL32_DLL: Any | None = None
_ADVAPI32_DLL: Any | None = None
_USERENV_DLL: Any | None = None


def _kernel32() -> Any:
    global _KERNEL32_DLL
    if _KERNEL32_DLL is None:
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = _wintypes.HANDLE
        dll.CreateJobObjectW.argtypes = [ctypes.c_void_p, _wintypes.LPCWSTR]
        dll.CreateJobObjectW.restype = handle
        dll.OpenJobObjectW.argtypes = [
            _wintypes.DWORD,
            _wintypes.BOOL,
            _wintypes.LPCWSTR,
        ]
        dll.OpenJobObjectW.restype = handle
        dll.SetInformationJobObject.argtypes = [
            handle,
            ctypes.c_int,
            ctypes.c_void_p,
            _wintypes.DWORD,
        ]
        dll.SetInformationJobObject.restype = _wintypes.BOOL
        dll.QueryInformationJobObject.argtypes = [
            handle,
            ctypes.c_int,
            ctypes.c_void_p,
            _wintypes.DWORD,
            ctypes.c_void_p,
        ]
        dll.QueryInformationJobObject.restype = _wintypes.BOOL
        dll.InitializeProcThreadAttributeList.argtypes = [
            ctypes.c_void_p,
            _wintypes.DWORD,
            _wintypes.DWORD,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        dll.InitializeProcThreadAttributeList.restype = _wintypes.BOOL
        dll.UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        dll.UpdateProcThreadAttribute.restype = _wintypes.BOOL
        dll.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        dll.CreateProcessW.argtypes = [
            _wintypes.LPCWSTR,
            _wintypes.LPWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            _wintypes.BOOL,
            _wintypes.DWORD,
            ctypes.c_void_p,
            _wintypes.LPCWSTR,
            ctypes.POINTER(_STARTUPINFOEXW),
            ctypes.POINTER(_PROCESS_INFORMATION),
        ]
        dll.CreateProcessW.restype = _wintypes.BOOL
        dll.ResumeThread.argtypes = [handle]
        dll.ResumeThread.restype = _wintypes.DWORD
        dll.TerminateProcess.argtypes = [handle, _wintypes.UINT]
        dll.TerminateProcess.restype = _wintypes.BOOL
        dll.IsProcessInJob.argtypes = [
            handle,
            handle,
            ctypes.POINTER(_wintypes.BOOL),
        ]
        dll.IsProcessInJob.restype = _wintypes.BOOL
        dll.CreateFileW.argtypes = [
            _wintypes.LPCWSTR,
            _wintypes.DWORD,
            _wintypes.DWORD,
            ctypes.c_void_p,
            _wintypes.DWORD,
            _wintypes.DWORD,
            handle,
        ]
        dll.CreateFileW.restype = handle
        dll.OpenProcess.argtypes = [
            _wintypes.DWORD,
            _wintypes.BOOL,
            _wintypes.DWORD,
        ]
        dll.OpenProcess.restype = handle
        dll.GetProcessTimes.argtypes = [
            handle,
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
            ctypes.POINTER(_FILETIME),
        ]
        dll.GetProcessTimes.restype = _wintypes.BOOL
        dll.GetExitCodeProcess.argtypes = [handle, ctypes.POINTER(_wintypes.DWORD)]
        dll.GetExitCodeProcess.restype = _wintypes.BOOL
        dll.TerminateJobObject.argtypes = [handle, _wintypes.UINT]
        dll.TerminateJobObject.restype = _wintypes.BOOL
        dll.WaitForSingleObject.argtypes = [handle, _wintypes.DWORD]
        dll.WaitForSingleObject.restype = _wintypes.DWORD
        dll.CloseHandle.argtypes = [handle]
        dll.CloseHandle.restype = _wintypes.BOOL
        dll.LocalFree.argtypes = [ctypes.c_void_p]
        dll.LocalFree.restype = ctypes.c_void_p
        _KERNEL32_DLL = dll
    return _KERNEL32_DLL


def _advapi32() -> Any:
    global _ADVAPI32_DLL
    if _ADVAPI32_DLL is None:
        dll = ctypes.WinDLL("advapi32", use_last_error=True)
        handle = _wintypes.HANDLE
        dll.GetNamedSecurityInfoW.argtypes = [
            _wintypes.LPWSTR,
            ctypes.c_int,
            _wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        dll.GetNamedSecurityInfoW.restype = _wintypes.DWORD
        dll.SetEntriesInAclW.argtypes = [
            _wintypes.ULONG,
            ctypes.POINTER(_EXPLICIT_ACCESS_W),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        dll.SetEntriesInAclW.restype = _wintypes.DWORD
        dll.SetNamedSecurityInfoW.argtypes = [
            _wintypes.LPWSTR,
            ctypes.c_int,
            _wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        dll.SetNamedSecurityInfoW.restype = _wintypes.DWORD
        dll.OpenProcessToken.argtypes = [
            handle,
            _wintypes.DWORD,
            ctypes.POINTER(handle),
        ]
        dll.OpenProcessToken.restype = _wintypes.BOOL
        dll.GetTokenInformation.argtypes = [
            handle,
            ctypes.c_int,
            ctypes.c_void_p,
            _wintypes.DWORD,
            ctypes.POINTER(_wintypes.DWORD),
        ]
        dll.GetTokenInformation.restype = _wintypes.BOOL
        dll.DuplicateToken.argtypes = [handle, ctypes.c_int, ctypes.POINTER(handle)]
        dll.DuplicateToken.restype = _wintypes.BOOL
        dll.ImpersonateLoggedOnUser.argtypes = [handle]
        dll.ImpersonateLoggedOnUser.restype = _wintypes.BOOL
        dll.RevertToSelf.restype = _wintypes.BOOL
        dll.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_wintypes.LPWSTR),
        ]
        dll.ConvertSidToStringSidW.restype = _wintypes.BOOL
        dll.ConvertStringSidToSidW.argtypes = [
            _wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        dll.ConvertStringSidToSidW.restype = _wintypes.BOOL
        dll.FreeSid.argtypes = [ctypes.c_void_p]
        dll.FreeSid.restype = ctypes.c_void_p
        _ADVAPI32_DLL = dll
    return _ADVAPI32_DLL


def _userenv() -> Any:
    global _USERENV_DLL
    if _USERENV_DLL is None:
        dll = ctypes.WinDLL("userenv", use_last_error=True)
        dll.CreateAppContainerProfile.argtypes = [
            _wintypes.LPCWSTR,
            _wintypes.LPCWSTR,
            _wintypes.LPCWSTR,
            ctypes.POINTER(_SID_AND_ATTRIBUTES),
            _wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        dll.CreateAppContainerProfile.restype = ctypes.c_long
        dll.DeleteAppContainerProfile.argtypes = [_wintypes.LPCWSTR]
        dll.DeleteAppContainerProfile.restype = ctypes.c_long
        _USERENV_DLL = dll
    return _USERENV_DLL


def _positive_int(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("Windows runtime marker integer is invalid")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Windows runtime marker string is invalid")
    return value


def _timeout(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"Windows legacy runtime {name} is invalid")
    return float(value)


def _activation_error(
    message: str,
    *,
    evidence_ref: str | None = None,
) -> PackageOfflineRestoreError:
    return PackageOfflineRestoreError(
        message,
        code="package_offline_restore_activation_invalid",
        evidence_ref=evidence_ref,
    )


__all__ = ()
