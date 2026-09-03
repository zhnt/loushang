"""Linux-native sandbox adapter for PLC9B offline-restore activation.

The accepted wire protocol is pathless.  This dark capability owner alone
knows the restore, current-B, and activation authorities.  It validates the
exact materialization marker, launches one long-lived legacy runtime in a
required Bubblewrap scope, proves the child mount/identity boundary through
procfs, and persists only private process-lifetime evidence.
"""

from __future__ import annotations

import ctypes
import errno
import os
import re
import secrets
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from queue import Empty, Queue
from typing import cast

from loushang.harness.environment import LocalHostEnvironmentProbe
from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PackageLegacyRuntimeActivationReceiptV1,
    PackageOfflineRestoreError,
    PackageOfflineRestoreMaterializationReceiptV1,
    PackageOfflineRestoreRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_offline_restore import (
    _MAX_RECEIPT_BYTES,
    _PAYLOAD_NAME,
    DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_BYTES,
    DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_DEPTH,
    DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_ENTRIES,
    _directory_identity,
    _inspect_tree,
    _open_directory_at,
    _paths_overlap,
    _pinned_roots_overlap,
    _PinnedRoot,
    _read_regular_file,
    _strict_json_object,
    _validated_limit,
    _validated_root_path,
    _write_new_file,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.sandbox.backends.linux import LinuxBubblewrapBackend
from loushang.harness.sandbox.types import SandboxScopeRequest

if sys.platform.startswith("linux"):
    import fcntl as _fcntl
else:  # pragma: no cover - collected on non-Linux hosts
    _fcntl = None  # type: ignore[assignment]

PACKAGE_LINUX_LEGACY_RUNTIME_MARKER_VERSION = 1
DEFAULT_PACKAGE_LINUX_LEGACY_RUNTIME_STARTUP_TIMEOUT_SECONDS = 5.0
DEFAULT_PACKAGE_LINUX_LEGACY_RUNTIME_TERMINATION_GRACE_SECONDS = 1.0

_ACTIVE_MARKER_NAME = "active-runtime.json"
_LOCK_NAME = ".legacy-runtime.lock"
_MAX_MARKER_BYTES = 128 * 1024
_MAX_COMMAND_ARGUMENTS = 256
_MAX_COMMAND_BYTES = 128 * 1024
_MAX_ENVIRONMENT_ENTRIES = 256
_MAX_ENVIRONMENT_BYTES = 128 * 1024
_READY_FD_ENV = "LOUSHANG_LEGACY_RUNTIME_READY_FD"
_READY_TOKEN_ENV = "LOUSHANG_LEGACY_RUNTIME_READY_TOKEN"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_REQUIRED_CAPABILITIES = frozenset(
    {
        "filesystem_roots",
        "filesystem_denied_roots",
        "network_isolation",
        "private_temporary_directory",
        "subprocess_inheritance",
    }
)
_NAMESPACE_NAMES = ("mnt", "pid", "net", "ipc", "uts", "user")


@dataclass(frozen=True, slots=True)
class _ProcessIdentity:
    pid: int
    start_time: int

    def __post_init__(self) -> None:
        if self.pid < 1 or self.start_time < 1:
            raise ValueError("native process identity is invalid")


@dataclass(slots=True)
class _GuardedProcess:
    process: subprocess.Popen[bytes]
    guardian: threading.Thread
    settled: threading.Event

    @property
    def pid(self) -> int:
        return self.process.pid

    def poll(self) -> int | None:
        return self.process.poll()

    def join(self, timeout: float) -> None:
        if not self.settled.wait(timeout):
            raise TimeoutError("Legacy runtime guardian did not settle")
        self.guardian.join()
        if self.guardian.is_alive():
            raise TimeoutError("Legacy runtime guardian did not settle")


@dataclass(frozen=True, slots=True)
class _ActivationMarker:
    receipt: PackageLegacyRuntimeActivationReceiptV1
    supervisor: _ProcessIdentity
    sandbox: _ProcessIdentity
    boot_id_digest: str
    current_b_root_identity: str
    restore_namespace_id: str
    sandbox_profile_digest: str
    marker_version: int = PACKAGE_LINUX_LEGACY_RUNTIME_MARKER_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.boot_id_digest, "boot identity digest"),
            (self.current_b_root_identity, "current B root identity"),
            (self.restore_namespace_id, "restore namespace identity"),
            (self.sandbox_profile_digest, "sandbox profile digest"),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(f"{name} is invalid")
        if self.marker_version != PACKAGE_LINUX_LEGACY_RUNTIME_MARKER_VERSION:
            raise ValueError("unsupported legacy runtime marker")
        expected_instance = _runtime_instance_identity(
            request_id=self.receipt.request_id,
            materialization_receipt_id=self.receipt.materialization_receipt_id,
            supervisor=self.supervisor,
            sandbox=self.sandbox,
            boot_id_digest=self.boot_id_digest,
        )
        if self.receipt.runtime_instance_id != expected_instance or (
            self.receipt.runtime_lease_id
            != sha256(f"legacy-lease:{expected_instance}".encode()).hexdigest()
        ):
            raise ValueError("legacy runtime marker process identity is not bound")

    def to_dict(self) -> dict[str, object]:
        return {
            "bootIdDigest": self.boot_id_digest,
            "currentBRootIdentity": self.current_b_root_identity,
            "markerVersion": self.marker_version,
            "receipt": self.receipt.to_dict(),
            "restoreNamespaceId": self.restore_namespace_id,
            "sandboxPid": self.sandbox.pid,
            "sandboxProfileDigest": self.sandbox_profile_digest,
            "sandboxStartTime": self.sandbox.start_time,
            "supervisorPid": self.supervisor.pid,
            "supervisorStartTime": self.supervisor.start_time,
        }

    @classmethod
    def from_dict(cls, value: object) -> _ActivationMarker:
        document = _strict_object(
            value,
            expected={
                "bootIdDigest",
                "currentBRootIdentity",
                "markerVersion",
                "receipt",
                "restoreNamespaceId",
                "sandboxPid",
                "sandboxProfileDigest",
                "sandboxStartTime",
                "supervisorPid",
                "supervisorStartTime",
            },
            name="legacy runtime marker",
        )
        return cls(
            receipt=PackageLegacyRuntimeActivationReceiptV1.from_dict(
                document["receipt"]
            ),
            supervisor=_ProcessIdentity(
                pid=_strict_positive_int(document["supervisorPid"]),
                start_time=_strict_positive_int(document["supervisorStartTime"]),
            ),
            sandbox=_ProcessIdentity(
                pid=_strict_positive_int(document["sandboxPid"]),
                start_time=_strict_positive_int(document["sandboxStartTime"]),
            ),
            boot_id_digest=_strict_string(document["bootIdDigest"]),
            current_b_root_identity=_strict_string(document["currentBRootIdentity"]),
            restore_namespace_id=_strict_string(document["restoreNamespaceId"]),
            sandbox_profile_digest=_strict_string(document["sandboxProfileDigest"]),
            marker_version=_strict_positive_int(document["markerVersion"]),
        )


class PackageLinuxLegacyRuntimeActivationOwner:
    """Activate exactly one restored old runtime under required Linux isolation."""

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
        bwrap_path: str | Path | None = None,
        startup_timeout_seconds: float = (
            DEFAULT_PACKAGE_LINUX_LEGACY_RUNTIME_STARTUP_TIMEOUT_SECONDS
        ),
        termination_grace_seconds: float = (
            DEFAULT_PACKAGE_LINUX_LEGACY_RUNTIME_TERMINATION_GRACE_SECONDS
        ),
        maximum_entries: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_ENTRIES,
        maximum_bytes: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_BYTES,
        maximum_depth: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_DEPTH,
    ) -> None:
        if not sys.platform.startswith("linux") or _fcntl is None:
            raise _activation_error("Linux legacy runtime isolation is unavailable")
        self._restore_root = _activation_root_path(
            restore_authority_root,
            name="restore authority",
        )
        self._activation_root = _activation_root_path(
            activation_authority_root,
            name="activation authority",
        )
        self._current_b_root = _activation_root_path(
            current_b_authority_root,
            name="current B authority",
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
        self._startup_timeout = _validated_timeout(
            startup_timeout_seconds,
            name="startup timeout",
        )
        self._termination_grace = _validated_timeout(
            termination_grace_seconds,
            name="termination grace",
        )
        self._maximum_entries = _validated_limit(
            maximum_entries,
            name="maximum activation entries",
        )
        self._maximum_bytes = _validated_limit(
            maximum_bytes,
            name="maximum activation bytes",
        )
        self._maximum_depth = _validated_limit(
            maximum_depth,
            name="maximum activation depth",
        )
        self._thread_lock = threading.RLock()
        self._processes: dict[int, _GuardedProcess] = {}

        pinned: list[_PinnedRoot] = []
        try:
            pinned = [_PinnedRoot.open(path) for path in roots]
            if any(
                _pinned_roots_overlap(left, right)
                for index, left in enumerate(pinned)
                for right in pinned[index + 1 :]
            ):
                raise OSError("Package activation authorities overlap natively")
            self._restore_identities = pinned[0].identities
            self._activation_identities = pinned[1].identities
            self._current_b_identities = pinned[2].identities
        except Exception as exc:
            raise _activation_error(
                "Linux legacy runtime authorities are untrusted"
            ) from exc
        finally:
            for root in reversed(pinned):
                root.close()

        backend = LinuxBubblewrapBackend(bwrap_path=bwrap_path)
        status = backend.probe(LocalHostEnvironmentProbe().detect())
        if status.state != "available" or not _REQUIRED_CAPABILITIES.issubset(
            status.enforced_capabilities
        ):
            detail = status.reason or "required capabilities are unavailable"
            raise _activation_error(f"Required Linux sandbox is unavailable: {detail}")
        self._sandbox_backend = backend
        _probe_pidfd_support()
        self._boot_id_digest = _boot_id_digest()
        self._profile_digest = sha256(
            canonical_json_bytes(
                {
                    "backendId": status.backend_id,
                    "capabilities": sorted(_REQUIRED_CAPABILITIES),
                    "commandDigest": sha256(
                        canonical_json_bytes(list(self._command))
                    ).hexdigest(),
                    "environmentDigest": sha256(
                        canonical_json_bytes(list(self._environment))
                    ).hexdigest(),
                    "legacyRuntimeVersion": self._legacy_runtime_version,
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
        with self._exclusive_activation_root() as activation_root:
            marker = self._read_marker(activation_root)
            if marker is not None:
                if (
                    not marker.receipt.matches(request, materialization)
                    or marker.restore_namespace_id != request.restore_namespace_id
                    or marker.current_b_root_identity != request.current_root_identity
                ):
                    raise _activation_error(
                        "Another legacy Package runtime already owns activation"
                    )
                restore_root, current_b_root, payload_fd = self._open_bound_payload(
                    request,
                    materialization,
                )
                try:
                    self._assert_live_sandbox(
                        marker,
                        payload_fd=payload_fd,
                        restored_path=self._restored_path(request),
                        current_b_root=current_b_root,
                    )
                    restore_root.assert_visible()
                    activation_root.assert_visible()
                    return marker.receipt
                finally:
                    os.close(payload_fd)
                    current_b_root.close()
                    restore_root.close()

            restore_root, current_b_root, payload_fd = self._open_bound_payload(
                request,
                materialization,
            )
            process: _GuardedProcess | None = None
            issued_marker: _ActivationMarker | None = None
            marker_written = False
            completed = False
            try:
                restored_path = self._restored_path(request)
                process, issued_marker = self._start_sandboxed_runtime(
                    request,
                    materialization,
                    payload_fd=payload_fd,
                    restored_path=restored_path,
                    current_b_root=current_b_root,
                )
                _write_new_file(
                    activation_root.descriptor,
                    _ACTIVE_MARKER_NAME,
                    canonical_json_bytes(issued_marker.to_dict()),
                )
                marker_written = True
                os.fsync(activation_root.descriptor)
                self._assert_live_sandbox(
                    issued_marker,
                    payload_fd=payload_fd,
                    restored_path=restored_path,
                    current_b_root=current_b_root,
                )
                restore_root.assert_visible()
                current_b_root.assert_visible()
                activation_root.assert_visible()
                self._processes[issued_marker.supervisor.pid] = process
                completed = True
                return issued_marker.receipt
            except PackageOfflineRestoreError:
                raise
            except Exception as exc:
                raise _activation_error(
                    "Linux legacy runtime activation failed closed",
                    evidence_ref=materialization.materialization_receipt_id,
                ) from exc
            finally:
                if process is not None and process.poll() is not None:
                    self._processes.pop(process.pid, None)
                if not completed and process is not None:
                    cleanup_error = self._rollback_start(
                        process,
                        marker=issued_marker,
                        activation_root=activation_root,
                        marker_written=marker_written,
                    )
                    if cleanup_error is not None:
                        raise PackageOfflineRestoreError(
                            "Legacy Package runtime activation cleanup failed",
                            code="package_offline_restore_cleanup_failed",
                            evidence_ref=(materialization.materialization_receipt_id),
                        ) from cleanup_error
                os.close(payload_fd)
                current_b_root.close()
                restore_root.close()

    def deactivate(self, receipt: PackageLegacyRuntimeActivationReceiptV1) -> None:
        if not isinstance(receipt, PackageLegacyRuntimeActivationReceiptV1):
            raise TypeError("Legacy Package runtime activation receipt is required")
        if receipt.store_id != self._store_id:
            raise PackageOfflineRestoreError(
                "Legacy Package runtime receipt store changed",
                code="package_offline_restore_cleanup_failed",
                evidence_ref=receipt.activation_receipt_id,
            )
        try:
            with self._exclusive_activation_root() as activation_root:
                marker = self._read_marker(activation_root)
                if marker is None:
                    return
                if marker.receipt != receipt:
                    raise PackageOfflineRestoreError(
                        "Legacy Package runtime marker does not match cleanup receipt",
                        code="package_offline_restore_cleanup_failed",
                        evidence_ref=receipt.activation_receipt_id,
                    )
                self._validate_live_marker_for_deactivation(marker)
                self._terminate_marker(marker)
                marker_bytes, marker_identity = _read_regular_file(
                    activation_root.descriptor,
                    _ACTIVE_MARKER_NAME,
                    maximum_bytes=_MAX_MARKER_BYTES,
                )
                if marker_bytes != canonical_json_bytes(marker.to_dict()):
                    raise OSError("Legacy runtime marker changed during cleanup")
                current = os.stat(
                    _ACTIVE_MARKER_NAME,
                    dir_fd=activation_root.descriptor,
                    follow_symlinks=False,
                )
                if (current.st_dev, current.st_ino) != marker_identity:
                    raise OSError("Legacy runtime marker identity changed")
                os.unlink(_ACTIVE_MARKER_NAME, dir_fd=activation_root.descriptor)
                os.fsync(activation_root.descriptor)
                activation_root.assert_visible()
        except PackageOfflineRestoreError as exc:
            if exc.code == "package_offline_restore_cleanup_failed":
                raise
            raise PackageOfflineRestoreError(
                "Legacy Package runtime deactivation could not be proven",
                code="package_offline_restore_cleanup_failed",
                evidence_ref=receipt.activation_receipt_id,
            ) from exc
        except Exception as exc:
            raise PackageOfflineRestoreError(
                "Legacy Package runtime deactivation could not be proven",
                code="package_offline_restore_cleanup_failed",
                evidence_ref=receipt.activation_receipt_id,
            ) from exc

    def _start_sandboxed_runtime(
        self,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
        *,
        payload_fd: int,
        restored_path: Path,
        current_b_root: _PinnedRoot,
    ) -> tuple[_GuardedProcess, _ActivationMarker]:
        command = self._sandbox_backend._prepare_guarded_command(
            SandboxScopeRequest(
                cwd=restored_path,
                writable_roots=(restored_path,),
                denied_roots=(self._current_b_root,),
                network="denied",
            ),
            self._command,
        )
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
        token = secrets.token_hex(32)
        environment = dict(self._environment)
        environment[_READY_FD_ENV] = str(write_fd)
        environment[_READY_TOKEN_ENV] = token
        process: _GuardedProcess | None = None
        try:
            try:
                process = _spawn_guarded_process(
                    command,
                    cwd=restored_path,
                    env=environment,
                    pass_fds=(write_fd,),
                    timeout=self._startup_timeout,
                )
            finally:
                os.close(write_fd)
            try:
                _await_ready(
                    read_fd,
                    token,
                    process.process,
                    self._startup_timeout,
                )
            finally:
                os.close(read_fd)
            supervisor = _process_identity(process.pid)
            sandbox = _single_live_child(supervisor, timeout=self._startup_timeout)
            instance_id = _runtime_instance_identity(
                request_id=request.request_id,
                materialization_receipt_id=(materialization.materialization_receipt_id),
                supervisor=supervisor,
                sandbox=sandbox,
                boot_id_digest=self._boot_id_digest,
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
                supervisor=supervisor,
                sandbox=sandbox,
                boot_id_digest=self._boot_id_digest,
                current_b_root_identity=request.current_root_identity,
                restore_namespace_id=request.restore_namespace_id,
                sandbox_profile_digest=self._profile_digest,
            )
            self._assert_live_sandbox(
                marker,
                payload_fd=payload_fd,
                restored_path=restored_path,
                current_b_root=current_b_root,
            )
            return process, marker
        except Exception:
            with suppress(OSError):
                os.close(read_fd)
            if process is not None:
                with suppress(ProcessLookupError):
                    process.process.kill()
                with suppress(Exception):
                    process.join(self._termination_grace)
            raise

    def _assert_live_sandbox(
        self,
        marker: _ActivationMarker,
        *,
        payload_fd: int,
        restored_path: Path,
        current_b_root: _PinnedRoot,
    ) -> None:
        if marker.boot_id_digest != self._boot_id_digest:
            raise OSError("Legacy runtime belongs to another host boot")
        if marker.sandbox_profile_digest != self._profile_digest:
            raise OSError("Legacy runtime sandbox profile changed")
        if marker.current_b_root_identity != _directory_identity(
            current_b_root.descriptor
        ):
            raise OSError("Legacy runtime current B identity changed")
        if not _process_matches(marker.supervisor):
            raise OSError("Legacy runtime supervisor is not live")
        if not _process_matches(marker.sandbox):
            raise OSError("Legacy runtime sandbox process is not live")
        if _process_parent_pid(marker.sandbox.pid) != marker.supervisor.pid:
            raise OSError("Legacy runtime sandbox ownership changed")
        children = _process_children(marker.supervisor.pid)
        if children != (marker.sandbox.pid,):
            raise OSError("Legacy runtime supervisor has an unexpected process set")
        for namespace in _NAMESPACE_NAMES:
            if _namespace_identity(marker.sandbox.pid, namespace) == (
                _namespace_identity(os.getpid(), namespace)
            ):
                raise OSError(f"Legacy runtime did not isolate {namespace} namespace")
        proc_root_fd = os.open(
            f"/proc/{marker.sandbox.pid}/root",
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
        )
        restored_fd: int | None = None
        visible_b_fd: int | None = None
        try:
            restored_fd = _open_relative_path(proc_root_fd, restored_path.parts[1:])
            if _directory_identity(restored_fd) != _directory_identity(payload_fd):
                raise OSError("Sandbox restored root identity changed")
            try:
                visible_b_fd = _open_relative_path(
                    proc_root_fd,
                    self._current_b_root.parts[1:],
                )
            except FileNotFoundError:
                pass
            else:
                if (
                    os.fstat(visible_b_fd).st_dev,
                    os.fstat(visible_b_fd).st_ino,
                ) == current_b_root.root_identity:
                    raise OSError("Current B authority is reachable in legacy sandbox")
            current_b_root.assert_visible()
        finally:
            if visible_b_fd is not None:
                os.close(visible_b_fd)
            if restored_fd is not None:
                os.close(restored_fd)
            os.close(proc_root_fd)

    def _open_bound_payload(
        self,
        request: PackageOfflineRestoreRequestV1,
        materialization: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> tuple[_PinnedRoot, _PinnedRoot, int]:
        restore_root: _PinnedRoot | None = None
        current_b_root: _PinnedRoot | None = None
        namespace_fd: int | None = None
        payload_fd: int | None = None
        try:
            if (
                materialization.entry_count > self._maximum_entries
                or materialization.byte_count > self._maximum_bytes
            ):
                raise OSError("Restored Package tree exceeds activation budget")
            restore_root = _PinnedRoot.open(
                self._restore_root,
                expected_identities=self._restore_identities,
            )
            current_b_root = _PinnedRoot.open(
                self._current_b_root,
                expected_identities=self._current_b_identities,
            )
            if _directory_identity(current_b_root.descriptor) != (
                request.current_root_identity
            ):
                raise OSError("Current B authority identity changed")
            namespace_fd = _open_directory_at(
                restore_root.descriptor,
                request.restore_namespace_id,
            )
            if set(os.listdir(namespace_fd)) != {_PAYLOAD_NAME, "receipt.json"}:
                raise OSError("Restore namespace membership changed")
            durable, _identity = _read_regular_file(
                namespace_fd,
                "receipt.json",
                maximum_bytes=_MAX_RECEIPT_BYTES,
            )
            recorded = PackageOfflineRestoreMaterializationReceiptV1.from_dict(
                _strict_json_object(durable, name="restore receipt")
            )
            if (
                durable != canonical_json_bytes(recorded.to_dict())
                or recorded != materialization
            ):
                raise OSError("Restore materialization marker changed")
            payload_fd = _open_directory_at(namespace_fd, _PAYLOAD_NAME)
            if (
                _directory_identity(payload_fd)
                != materialization.restored_root_identity
            ):
                raise OSError("Restored Package root identity changed")
            inspection = _inspect_tree(
                payload_fd,
                maximum_entries=materialization.entry_count,
                maximum_bytes=materialization.byte_count,
                maximum_depth=self._maximum_depth,
            )
            if (
                inspection.tree_digest != materialization.snapshot_tree_digest
                or inspection.entry_count != materialization.entry_count
                or inspection.byte_count != materialization.byte_count
            ):
                raise OSError("Restored Package tree changed before activation")
            restore_root.assert_visible()
            current_b_root.assert_visible()
            assert payload_fd is not None
            result = (restore_root, current_b_root, payload_fd)
            restore_root = None
            current_b_root = None
            payload_fd = None
            return result
        except Exception as exc:
            raise _activation_error(
                "Restored Package authority is not activation-ready",
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

    @contextmanager
    def _exclusive_activation_root(self) -> Iterator[_PinnedRoot]:
        with self._thread_lock:
            root: _PinnedRoot | None = None
            lock_fd: int | None = None
            try:
                root = _PinnedRoot.open(
                    self._activation_root,
                    expected_identities=self._activation_identities,
                )
                lock_fd = os.open(
                    _LOCK_NAME,
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=root.descriptor,
                )
                metadata = os.fstat(lock_fd)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) & 0o077
                ):
                    raise OSError("Legacy runtime activation lock is untrusted")
                _fcntl.flock(lock_fd, _fcntl.LOCK_EX)
                root.assert_visible()
                entries = set(os.listdir(root.descriptor))
                if not entries <= {_LOCK_NAME, _ACTIVE_MARKER_NAME}:
                    raise OSError(
                        "Legacy runtime activation authority has foreign state"
                    )
                yield root
            except PackageOfflineRestoreError:
                raise
            except Exception as exc:
                raise _activation_error(
                    "Legacy runtime activation authority is untrusted"
                ) from exc
            finally:
                if lock_fd is not None:
                    with suppress(OSError):
                        _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
                    with suppress(OSError):
                        os.close(lock_fd)
                if root is not None:
                    root.close()

    def _read_marker(self, root: _PinnedRoot) -> _ActivationMarker | None:
        try:
            os.stat(
                _ACTIVE_MARKER_NAME,
                dir_fd=root.descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        payload, _identity = _read_regular_file(
            root.descriptor,
            _ACTIVE_MARKER_NAME,
            maximum_bytes=_MAX_MARKER_BYTES,
        )
        marker = _ActivationMarker.from_dict(
            _strict_json_object(payload, name="legacy runtime marker")
        )
        if payload != canonical_json_bytes(marker.to_dict()):
            raise OSError("Legacy runtime marker is not canonical")
        return marker

    def _terminate_marker(self, marker: _ActivationMarker) -> None:
        identities = (marker.sandbox, marker.supervisor)
        pinned: list[tuple[_ProcessIdentity, int]] = []
        try:
            for native in identities:
                descriptor = _open_matching_pidfd(native)
                if descriptor is not None:
                    pinned.append((native, descriptor))
            for _native, descriptor in pinned:
                _pidfd_send_signal(descriptor, signal.SIGTERM)
            deadline = time.monotonic() + self._termination_grace
            while any(_process_matches(native) for native, _descriptor in pinned):
                if time.monotonic() >= deadline:
                    break
                _reap_child(marker.supervisor.pid)
                time.sleep(0.01)
            for native, descriptor in pinned:
                if _process_matches(native):
                    _pidfd_send_signal(descriptor, signal.SIGKILL)
            deadline = time.monotonic() + self._termination_grace
            while any(_process_matches(native) for native, _descriptor in pinned):
                _reap_child(marker.supervisor.pid)
                if time.monotonic() >= deadline:
                    raise OSError("Legacy runtime process did not terminate")
                time.sleep(0.01)
            process = self._processes.pop(marker.supervisor.pid, None)
            if process is not None:
                process.join(self._termination_grace)
            else:
                _reap_child(marker.supervisor.pid)
        finally:
            for _native, descriptor in pinned:
                os.close(descriptor)

    def _validate_live_marker_for_deactivation(
        self,
        marker: _ActivationMarker,
    ) -> None:
        supervisor_live = _process_matches(marker.supervisor)
        sandbox_live = _process_matches(marker.sandbox)
        if not supervisor_live and not sandbox_live:
            return
        if not supervisor_live or not sandbox_live:
            raise OSError("Legacy runtime process set is only partially live")
        restore_root: _PinnedRoot | None = None
        current_b_root: _PinnedRoot | None = None
        namespace_fd: int | None = None
        payload_fd: int | None = None
        try:
            restore_root = _PinnedRoot.open(
                self._restore_root,
                expected_identities=self._restore_identities,
            )
            current_b_root = _PinnedRoot.open(
                self._current_b_root,
                expected_identities=self._current_b_identities,
            )
            namespace_fd = _open_directory_at(
                restore_root.descriptor,
                marker.restore_namespace_id,
            )
            payload_fd = _open_directory_at(namespace_fd, _PAYLOAD_NAME)
            if _directory_identity(payload_fd) != marker.receipt.restored_root_identity:
                raise OSError("Legacy runtime cleanup root identity changed")
            self._assert_live_sandbox(
                marker,
                payload_fd=payload_fd,
                restored_path=(
                    self._restore_root / marker.restore_namespace_id / _PAYLOAD_NAME
                ),
                current_b_root=current_b_root,
            )
            restore_root.assert_visible()
        finally:
            if payload_fd is not None:
                os.close(payload_fd)
            if namespace_fd is not None:
                os.close(namespace_fd)
            if current_b_root is not None:
                current_b_root.close()
            if restore_root is not None:
                restore_root.close()

    def _rollback_start(
        self,
        process: _GuardedProcess,
        *,
        marker: _ActivationMarker | None,
        activation_root: _PinnedRoot,
        marker_written: bool,
    ) -> Exception | None:
        try:
            if marker is not None:
                self._processes[marker.supervisor.pid] = process
                self._terminate_marker(marker)
            else:
                with suppress(ProcessLookupError):
                    process.process.kill()
                process.join(self._termination_grace)
            if marker_written:
                os.unlink(_ACTIVE_MARKER_NAME, dir_fd=activation_root.descriptor)
                os.fsync(activation_root.descriptor)
            return None
        except Exception as exc:  # pragma: no cover - explicit cleanup debt path
            return exc

    def _restored_path(self, request: PackageOfflineRestoreRequestV1) -> Path:
        return self._restore_root / request.restore_namespace_id / _PAYLOAD_NAME


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
            "Legacy runtime activation inputs do not match",
            evidence_ref=request.request_id,
        )


def _runtime_instance_identity(
    *,
    request_id: str,
    materialization_receipt_id: str,
    supervisor: _ProcessIdentity,
    sandbox: _ProcessIdentity,
    boot_id_digest: str,
) -> str:
    return sha256(
        canonical_json_bytes(
            {
                "bootIdDigest": boot_id_digest,
                "materializationReceiptId": materialization_receipt_id,
                "requestId": request_id,
                "sandboxPid": sandbox.pid,
                "sandboxStartTime": sandbox.start_time,
                "supervisorPid": supervisor.pid,
                "supervisorStartTime": supervisor.start_time,
            }
        )
    ).hexdigest()


def _spawn_guarded_process(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str],
    pass_fds: tuple[int, ...],
    timeout: float,
) -> _GuardedProcess:
    published: Queue[tuple[subprocess.Popen[bytes] | None, BaseException | None]] = (
        Queue(maxsize=1)
    )
    cancelled = threading.Event()
    settled = threading.Event()

    def guard() -> None:
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=pass_fds,
                start_new_session=True,
            )
            if cancelled.is_set():
                process.kill()
            published.put((process, None))
            process.wait()
        except BaseException as exc:
            if process is None:
                published.put((None, exc))
        finally:
            settled.set()

    guardian = threading.Thread(
        target=guard,
        name="package-linux-legacy-runtime-guardian",
        daemon=True,
    )
    guardian.start()
    try:
        process, error = published.get(timeout=timeout)
    except Empty as exc:
        cancelled.set()
        raise TimeoutError("Legacy runtime native spawn timed out") from exc
    if error is not None:
        raise error
    assert process is not None
    return _GuardedProcess(
        process=process,
        guardian=guardian,
        settled=settled,
    )


def _await_ready(
    descriptor: int,
    token: str,
    process: subprocess.Popen[bytes],
    timeout: float,
) -> None:
    expected = f"ready:{token}\n".encode()
    observed = bytearray()
    deadline = time.monotonic() + timeout
    while len(observed) < len(expected):
        if process.poll() is not None:
            raise OSError("Legacy runtime exited before readiness")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Legacy runtime readiness timed out")
        readable, _, _ = select.select((descriptor,), (), (), min(0.05, remaining))
        if not readable:
            continue
        chunk = os.read(descriptor, len(expected) - len(observed) + 1)
        if not chunk:
            raise OSError("Legacy runtime closed readiness without acknowledgement")
        observed.extend(chunk)
        if len(observed) > len(expected):
            break
    if bytes(observed) != expected:
        raise OSError("Legacy runtime readiness acknowledgement is invalid")


def _single_live_child(
    supervisor: _ProcessIdentity,
    *,
    timeout: float,
) -> _ProcessIdentity:
    deadline = time.monotonic() + timeout
    while True:
        if not _process_matches(supervisor):
            raise OSError("Legacy runtime supervisor exited during startup")
        children = _process_children(supervisor.pid)
        if len(children) == 1:
            child = _process_identity(children[0])
            if _process_parent_pid(child.pid) == supervisor.pid:
                return child
        if len(children) > 1:
            raise OSError("Legacy runtime supervisor has multiple sandbox children")
        if time.monotonic() >= deadline:
            raise TimeoutError("Legacy runtime sandbox child was not published")
        time.sleep(0.01)


def _process_identity(pid: int) -> _ProcessIdentity:
    values = _process_stat(pid)
    return _ProcessIdentity(pid=pid, start_time=int(values[19]))


def _probe_pidfd_support() -> None:
    try:
        descriptor = _pidfd_open(os.getpid())
    except Exception as exc:
        raise _activation_error("Linux pidfd process ownership is unavailable") from exc
    os.close(descriptor)


def _open_matching_pidfd(identity: _ProcessIdentity) -> int | None:
    if not _process_matches(identity):
        return None
    try:
        descriptor = _pidfd_open(identity.pid)
    except ProcessLookupError:
        return None
    if _process_matches(identity):
        return descriptor
    os.close(descriptor)
    return None


def _pidfd_open(pid: int) -> int:
    function = getattr(ctypes.CDLL(None, use_errno=True), "pidfd_open", None)
    if function is None:
        raise OSError(errno.ENOSYS, "pidfd_open is unavailable")
    function.argtypes = (ctypes.c_int, ctypes.c_uint)
    function.restype = ctypes.c_int
    descriptor = int(function(pid, 0))
    if descriptor < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return descriptor


def _pidfd_send_signal(descriptor: int, requested_signal: int) -> None:
    function = getattr(
        ctypes.CDLL(None, use_errno=True),
        "pidfd_send_signal",
        None,
    )
    if function is None:
        raise OSError(errno.ENOSYS, "pidfd_send_signal is unavailable")
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = int(function(descriptor, requested_signal, None, 0))
    if result < 0:
        error = ctypes.get_errno()
        if error == errno.ESRCH:
            return
        raise OSError(error, os.strerror(error))


def _process_parent_pid(pid: int) -> int:
    return int(_process_stat(pid)[1])


def _process_matches(identity: _ProcessIdentity) -> bool:
    try:
        values = _process_stat(identity.pid)
        return values[0] != "Z" and int(values[19]) == identity.start_time
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
        return False


def _process_stat(pid: int) -> tuple[str, ...]:
    payload = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    closing = payload.rfind(")")
    if closing < 0:
        raise ValueError("native process stat is invalid")
    values = tuple(payload[closing + 2 :].split())
    if len(values) < 20:
        raise ValueError("native process stat is incomplete")
    return values


def _process_children(pid: int) -> tuple[int, ...]:
    payload = Path(f"/proc/{pid}/task/{pid}/children").read_text(encoding="ascii")
    return tuple(int(value) for value in payload.split())


def _namespace_identity(pid: int, name: str) -> tuple[int, int]:
    metadata = os.stat(f"/proc/{pid}/ns/{name}")
    return metadata.st_dev, metadata.st_ino


def _open_relative_path(root_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            child = _open_directory_at(current, part)
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def _boot_id_digest() -> str:
    boot_id = (
        Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    )
    if not boot_id or len(boot_id) > 128:
        raise _activation_error("Linux boot identity is unavailable")
    return sha256(boot_id.encode()).hexdigest()


def _reap_child(pid: int) -> None:
    with suppress(ChildProcessError, ProcessLookupError):
        os.waitpid(pid, os.WNOHANG)


def _validated_command(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("Legacy runtime command must be an argument sequence")
    command = tuple(value)
    if (
        not command
        or len(command) > _MAX_COMMAND_ARGUMENTS
        or any(not isinstance(argument, str) or not argument for argument in command)
        or sum(len(argument.encode("utf-8")) for argument in command)
        > _MAX_COMMAND_BYTES
    ):
        raise ValueError("Legacy runtime command is invalid or exceeds its budget")
    executable = Path(command[0])
    if (
        not executable.is_absolute()
        or ".." in executable.parts
        or executable == Path(executable.anchor)
    ):
        raise ValueError(
            "Legacy runtime executable must be an absolute normalized path"
        )
    return cast(tuple[str, ...], command)


def _validated_environment(
    value: Mapping[str, str] | Sequence[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    items = tuple(value.items()) if isinstance(value, Mapping) else tuple(value)
    if len(items) > _MAX_ENVIRONMENT_ENTRIES:
        raise ValueError("Legacy runtime environment exceeds its entry budget")
    normalized: list[tuple[str, str]] = []
    for item in items:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or "=" in item[0]
            or "\x00" in item[0]
            or not isinstance(item[1], str)
            or "\x00" in item[1]
        ):
            raise TypeError("Legacy runtime environment must contain string pairs")
        normalized.append(item)
    names = tuple(name for name, _item in normalized)
    if len(set(names)) != len(names) or {_READY_FD_ENV, _READY_TOKEN_ENV} & set(names):
        raise ValueError("Legacy runtime environment has duplicate or reserved names")
    if sum(len(name.encode()) + len(item.encode()) for name, item in normalized) > (
        _MAX_ENVIRONMENT_BYTES
    ):
        raise ValueError("Legacy runtime environment exceeds its byte budget")
    return tuple(sorted(normalized))


def _validated_timeout(value: float, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"Legacy runtime {name} must be numeric")
    normalized = float(value)
    if normalized <= 0 or normalized > 60:
        raise ValueError(f"Legacy runtime {name} must be between 0 and 60 seconds")
    return normalized


def _activation_root_path(value: str | Path, *, name: str) -> Path:
    try:
        return _validated_root_path(value, name=name)
    except PackageOfflineRestoreError as exc:
        raise _activation_error(f"Package {name} is invalid") from exc


def _strict_object(
    value: object,
    *,
    expected: set[str],
    name: str,
) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or any(not isinstance(key, str) for key in value)
    ):
        raise ValueError(f"{name} does not match its versioned schema")
    return cast(dict[str, object], value)


def _strict_positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("legacy runtime marker integer is invalid")
    return value


def _strict_string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("legacy runtime marker string is invalid")
    return value


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
