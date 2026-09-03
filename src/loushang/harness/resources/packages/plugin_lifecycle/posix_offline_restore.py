"""POSIX rooted snapshot materialization for dark PLC9B4c3b restore.

The wire protocol remains pathless.  This capability owner alone knows the
configured snapshot and restore authorities; it verifies a complete immutable
snapshot bundle, copies it through descriptor-relative no-follow operations,
and atomically publishes one isolated restore namespace.  It never selects a
Product root or writes a PLC9B journal.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
import re
import stat
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

from loushang.harness.resources.packages.plugin_lifecycle.offline_restore import (
    PACKAGE_PRE_B_SNAPSHOT_DOMAINS,
    PackageOfflineRestoreError,
    PackageOfflineRestoreMaterializationReceiptV1,
    PackageOfflineRestoreRequestV1,
    PackageOfflineRestoreSnapshotEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

if os.name == "posix":
    import fcntl as _fcntl
else:  # pragma: no cover - imported by Windows collection only
    _fcntl = None  # type: ignore[assignment]

PACKAGE_POSIX_OFFLINE_RESTORE_TREE_MANIFEST_VERSION = 1
PACKAGE_POSIX_OFFLINE_RESTORE_STATE_MANIFEST_VERSION = 1
DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_ENTRIES = 100_000
DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_BYTES = 16 * 1024 * 1024 * 1024
DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_DEPTH = 128

_LOCK_NAME = ".offline-restore.lock"
_PAYLOAD_NAME = "payload"
_RECEIPT_NAME = "receipt.json"
_STATE_MANIFEST_NAME = "state-manifest.json"
_MAX_RECEIPT_BYTES = 64 * 1024
_MAX_STATE_MANIFEST_BYTES = 1024 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")

_NativeIdentity = tuple[int, int]
_EntryKind = Literal["directory", "file"]


@dataclass(frozen=True, slots=True)
class _TreeEntry:
    logical_path: str
    kind: _EntryKind
    mode: int
    content_digest: str | None = None
    byte_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        if self.kind == "directory":
            return {
                "kind": self.kind,
                "logicalPath": self.logical_path,
                "mode": self.mode,
            }
        return {
            "byteCount": self.byte_count,
            "contentDigest": self.content_digest,
            "kind": self.kind,
            "logicalPath": self.logical_path,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class _TreeInspection:
    entries: tuple[_TreeEntry, ...]
    identities: dict[tuple[str, ...], _NativeIdentity]
    tree_digest: str
    entry_count: int
    byte_count: int


class PackagePosixOfflineRestoreMaterializer:
    """Own rooted snapshot reads and one isolated POSIX restore authority."""

    def __init__(
        self,
        snapshot_authority_root: str | Path,
        restore_authority_root: str | Path,
        *,
        current_b_authority_root: str | Path,
        store_id: str,
        maximum_entries: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_ENTRIES,
        maximum_bytes: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_BYTES,
        maximum_depth: int = DEFAULT_PACKAGE_POSIX_OFFLINE_RESTORE_MAX_DEPTH,
    ) -> None:
        if os.name != "posix" or not _supports_posix_rooted_io():
            raise PackageOfflineRestoreError(
                "POSIX offline restore is unavailable",
                code="package_offline_restore_materialization_invalid",
            )
        self._snapshot_root = _validated_root_path(
            snapshot_authority_root,
            name="snapshot authority",
        )
        self._restore_root = _validated_root_path(
            restore_authority_root,
            name="restore authority",
        )
        self._current_b_root = _validated_root_path(
            current_b_authority_root,
            name="current B authority",
        )
        authority_roots = (
            self._snapshot_root,
            self._restore_root,
            self._current_b_root,
        )
        if any(
            _paths_overlap(left, right)
            for index, left in enumerate(authority_roots)
            for right in authority_roots[index + 1 :]
        ):
            raise PackageOfflineRestoreError(
                "Snapshot, restore, and current B authorities must be disjoint",
                code="package_offline_restore_materialization_invalid",
            )
        if not isinstance(store_id, str) or not _SAFE_ID.fullmatch(store_id):
            raise ValueError("Package store identity is invalid")
        self._store_id = store_id
        self._maximum_entries = _validated_limit(
            maximum_entries,
            name="maximum snapshot entries",
        )
        self._maximum_bytes = _validated_limit(
            maximum_bytes,
            name="maximum snapshot bytes",
        )
        self._maximum_depth = _validated_limit(
            maximum_depth,
            name="maximum snapshot depth",
        )
        self._thread_lock = threading.RLock()
        snapshot: _PinnedRoot | None = None
        restore: _PinnedRoot | None = None
        current_b: _PinnedRoot | None = None
        try:
            snapshot = _PinnedRoot.open(self._snapshot_root)
            restore = _PinnedRoot.open(self._restore_root)
            current_b = _PinnedRoot.open(self._current_b_root)
            pinned_roots = (snapshot, restore, current_b)
            if any(
                _pinned_roots_overlap(left, right)
                for index, left in enumerate(pinned_roots)
                for right in pinned_roots[index + 1 :]
            ):
                raise PackageOfflineRestoreError(
                    "Package offline-restore authorities overlap natively",
                    code="package_offline_restore_materialization_invalid",
                )
            self._snapshot_identities = snapshot.identities
            self._restore_identities = restore.identities
            self._current_b_identities = current_b.identities
        except PackageOfflineRestoreError:
            raise
        except Exception as exc:
            raise _materialization_error(
                "POSIX offline-restore authority is untrusted"
            ) from exc
        finally:
            if current_b is not None:
                current_b.close()
            if restore is not None:
                restore.close()
            if snapshot is not None:
                snapshot.close()

    def restore(
        self,
        request: PackageOfflineRestoreRequestV1,
        snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
        quiescence: PackageEpochCutoverQuiescenceReceiptV1,
    ) -> PackageOfflineRestoreMaterializationReceiptV1:
        _validate_restore_inputs(
            request,
            snapshot,
            quiescence,
            store_id=self._store_id,
        )
        if (
            snapshot.snapshot.entry_count > self._maximum_entries
            or snapshot.snapshot.byte_count > self._maximum_bytes
        ):
            raise PackageOfflineRestoreError(
                "Package offline snapshot exceeds configured materialization budget",
                code="package_offline_restore_snapshot_invalid",
                evidence_ref=snapshot.evidence_id,
            )
        with self._exclusive_restore_root() as restore_root:
            source_root: _PinnedRoot | None = None
            current_b_root: _PinnedRoot | None = None
            source: _ValidatedSnapshot | None = None
            staging_identity: _NativeIdentity | None = None
            staging_created = False
            published = False
            completed = False
            staging_name = f"staging-{request.request_id}"
            try:
                try:
                    current_b_root = _PinnedRoot.open(
                        self._current_b_root,
                        expected_identities=self._current_b_identities,
                    )
                    if (
                        _directory_identity(current_b_root.descriptor)
                        != request.current_root_identity
                    ):
                        raise OSError("Current B root identity changed")
                except Exception as exc:
                    raise _materialization_error(
                        "POSIX current B authority identity changed"
                    ) from exc
                try:
                    source_root = _PinnedRoot.open(
                        self._snapshot_root,
                        expected_identities=self._snapshot_identities,
                    )
                except Exception as exc:
                    raise PackageOfflineRestoreError(
                        "POSIX snapshot authority identity changed",
                        code="package_offline_restore_snapshot_invalid",
                        evidence_ref=snapshot.evidence_id,
                    ) from exc
                source = _validated_snapshot_bundle(
                    source_root,
                    snapshot,
                    maximum_depth=self._maximum_depth,
                )
                if _entry_exists(restore_root.descriptor, request.restore_namespace_id):
                    receipt = _validate_restore_namespace(
                        restore_root,
                        request,
                        snapshot,
                        namespace_name=request.restore_namespace_id,
                        expected_source=source,
                        maximum_depth=self._maximum_depth,
                    )
                    _revalidate_source(
                        source,
                        snapshot,
                        maximum_depth=self._maximum_depth,
                    )
                    source_root.assert_visible()
                    current_b_root.assert_visible()
                    restore_root.assert_visible()
                    completed = True
                    return receipt
                if _entry_exists(restore_root.descriptor, staging_name):
                    raise _materialization_error(
                        "Package offline-restore staging namespace already exists"
                    )
                os.mkdir(staging_name, mode=0o700, dir_fd=restore_root.descriptor)
                staging_created = True
                staging_metadata = os.stat(
                    staging_name,
                    dir_fd=restore_root.descriptor,
                    follow_symlinks=False,
                )
                if not stat.S_ISDIR(staging_metadata.st_mode):
                    raise OSError("Restore staging entry is not a directory")
                staging_identity = _native_identity(staging_metadata)
                staging_fd = _open_directory_at(
                    restore_root.descriptor,
                    staging_name,
                )
                try:
                    if _native_identity(os.fstat(staging_fd)) != staging_identity:
                        raise OSError("Restore staging identity changed")
                    os.mkdir(_PAYLOAD_NAME, mode=0o700, dir_fd=staging_fd)
                    payload_fd = _open_directory_at(staging_fd, _PAYLOAD_NAME)
                    try:
                        _copy_tree(
                            source.payload_fd,
                            payload_fd,
                            source.inspection,
                        )
                        copied = _inspect_tree(
                            payload_fd,
                            maximum_entries=snapshot.snapshot.entry_count,
                            maximum_bytes=snapshot.snapshot.byte_count,
                            maximum_depth=self._maximum_depth,
                        )
                        if copied.entries != source.inspection.entries:
                            raise _materialization_error(
                                "Restored Package tree differs from snapshot"
                            )
                        restored_root_identity = _directory_identity(payload_fd)
                        receipt = PackageOfflineRestoreMaterializationReceiptV1.create(
                            request,
                            snapshot=snapshot,
                            quiescence_receipt_id=quiescence.receipt_id,
                            restored_root_identity=restored_root_identity,
                        )
                        _write_new_file(
                            staging_fd,
                            _RECEIPT_NAME,
                            canonical_json_bytes(receipt.to_dict()),
                        )
                        _fsync_tree(payload_fd, copied.entries)
                        os.fsync(payload_fd)
                    finally:
                        os.close(payload_fd)
                    os.fsync(staging_fd)
                finally:
                    os.close(staging_fd)

                source_root.assert_visible()
                current_b_root.assert_visible()
                restore_root.assert_visible()
                _revalidate_source(
                    source,
                    snapshot,
                    maximum_depth=self._maximum_depth,
                )
                staged_receipt = _validate_restore_namespace(
                    restore_root,
                    request,
                    snapshot,
                    namespace_name=staging_name,
                    expected_source=source,
                    expected_namespace_identity=staging_identity,
                    maximum_depth=self._maximum_depth,
                )
                _rename_directory_noreplace(
                    restore_root.descriptor,
                    staging_name,
                    restore_root.descriptor,
                    request.restore_namespace_id,
                )
                published = True
                os.fsync(restore_root.descriptor)
                restore_root.assert_visible()
                current_b_root.assert_visible()
                receipt = _validate_restore_namespace(
                    restore_root,
                    request,
                    snapshot,
                    namespace_name=request.restore_namespace_id,
                    expected_source=source,
                    expected_namespace_identity=staging_identity,
                    maximum_depth=self._maximum_depth,
                )
                if receipt != staged_receipt:
                    raise _materialization_error(
                        "Published Package restore receipt changed"
                    )
                current_b_root.assert_visible()
                if (
                    _directory_identity(current_b_root.descriptor)
                    != request.current_root_identity
                ):
                    raise OSError("Current B root identity changed before return")
                completed = True
                return receipt
            except PackageOfflineRestoreError:
                raise
            except Exception as exc:
                raise _materialization_error(
                    "POSIX offline restore failed closed"
                ) from exc
            finally:
                if source is not None:
                    source.close()
                if source_root is not None:
                    source_root.close()
                if current_b_root is not None:
                    current_b_root.close()
                if staging_created and not completed:
                    if staging_identity is None:
                        raise PackageOfflineRestoreError(
                            "POSIX offline-restore staging identity was not captured",
                            code="package_offline_restore_cleanup_failed",
                        )
                    try:
                        _remove_owned_namespace(
                            restore_root.descriptor,
                            (
                                request.restore_namespace_id
                                if published
                                else staging_name
                            ),
                            expected_identity=staging_identity,
                        )
                        os.fsync(restore_root.descriptor)
                    except Exception as cleanup_error:
                        raise PackageOfflineRestoreError(
                            "POSIX offline-restore staging cleanup failed",
                            code="package_offline_restore_cleanup_failed",
                        ) from cleanup_error

    def discard(
        self,
        receipt: PackageOfflineRestoreMaterializationReceiptV1,
    ) -> None:
        if not isinstance(receipt, PackageOfflineRestoreMaterializationReceiptV1):
            raise TypeError("Package restore materialization receipt is required")
        if receipt.store_id != self._store_id:
            raise PackageOfflineRestoreError(
                "Package restore receipt store changed",
                code="package_offline_restore_cleanup_failed",
                evidence_ref=receipt.materialization_receipt_id,
            )
        with self._exclusive_restore_root() as restore_root:
            if not _entry_exists(
                restore_root.descriptor,
                receipt.restore_namespace_id,
            ):
                return
            try:
                namespace_fd = _open_directory_at(
                    restore_root.descriptor,
                    receipt.restore_namespace_id,
                )
                try:
                    if set(os.listdir(namespace_fd)) != {_PAYLOAD_NAME, _RECEIPT_NAME}:
                        raise OSError("Restore namespace membership changed")
                    marker, marker_identity = _read_regular_file(
                        namespace_fd,
                        _RECEIPT_NAME,
                        maximum_bytes=_MAX_RECEIPT_BYTES,
                    )
                    recorded = PackageOfflineRestoreMaterializationReceiptV1.from_dict(
                        _strict_json_object(marker, name="restore receipt")
                    )
                    if (
                        marker != canonical_json_bytes(recorded.to_dict())
                        or recorded != receipt
                    ):
                        raise OSError("Restore namespace receipt changed")
                    payload_fd = _open_directory_at(namespace_fd, _PAYLOAD_NAME)
                    try:
                        payload_identity = _native_identity(os.fstat(payload_fd))
                        if (
                            _directory_identity(payload_fd)
                            != receipt.restored_root_identity
                        ):
                            raise OSError("Restored root identity changed")
                        inspection = _inspect_tree(
                            payload_fd,
                            maximum_entries=receipt.entry_count,
                            maximum_bytes=receipt.byte_count,
                            maximum_depth=self._maximum_depth,
                        )
                        if (
                            inspection.tree_digest != receipt.snapshot_tree_digest
                            or inspection.entry_count != receipt.entry_count
                            or inspection.byte_count != receipt.byte_count
                        ):
                            raise OSError("Restored tree identity changed")
                        _delete_inspected_tree(payload_fd, inspection)
                    finally:
                        os.close(payload_fd)
                    _assert_entry_identity(
                        namespace_fd,
                        _PAYLOAD_NAME,
                        payload_identity,
                        expected_kind="directory",
                    )
                    os.rmdir(_PAYLOAD_NAME, dir_fd=namespace_fd)
                    _assert_entry_identity(
                        namespace_fd,
                        _RECEIPT_NAME,
                        marker_identity,
                        expected_kind="file",
                    )
                    os.unlink(_RECEIPT_NAME, dir_fd=namespace_fd)
                    os.fsync(namespace_fd)
                    namespace_identity = _native_identity(os.fstat(namespace_fd))
                finally:
                    os.close(namespace_fd)
                _assert_entry_identity(
                    restore_root.descriptor,
                    receipt.restore_namespace_id,
                    namespace_identity,
                    expected_kind="directory",
                )
                os.rmdir(
                    receipt.restore_namespace_id,
                    dir_fd=restore_root.descriptor,
                )
                os.fsync(restore_root.descriptor)
                restore_root.assert_visible()
            except Exception as exc:
                raise PackageOfflineRestoreError(
                    "Exact isolated Package restore cleanup could not be proven",
                    code="package_offline_restore_cleanup_failed",
                    evidence_ref=receipt.materialization_receipt_id,
                ) from exc

    @contextmanager
    def _exclusive_restore_root(self) -> Iterator[_PinnedRoot]:
        with self._thread_lock:
            root: _PinnedRoot | None = None
            lock_fd: int | None = None
            try:
                root = _PinnedRoot.open(
                    self._restore_root,
                    expected_identities=self._restore_identities,
                )
                lock_fd = os.open(
                    _LOCK_NAME,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
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
                    raise OSError("Offline-restore owner lock is untrusted")
                assert _fcntl is not None
                _fcntl.flock(lock_fd, _fcntl.LOCK_EX)
                root.assert_visible()
                yield root
            except PackageOfflineRestoreError:
                raise
            except Exception as exc:
                raise _materialization_error(
                    "POSIX offline-restore authority is untrusted"
                ) from exc
            finally:
                if lock_fd is not None:
                    if _fcntl is not None:
                        with suppress(OSError):
                            _fcntl.flock(lock_fd, _fcntl.LOCK_UN)
                    with suppress(OSError):
                        os.close(lock_fd)
                if root is not None:
                    root.close()


@dataclass(slots=True)
class _ValidatedSnapshot:
    bundle_fd: int
    payload_fd: int
    inspection: _TreeInspection

    def close(self) -> None:
        with suppress(OSError):
            os.close(self.payload_fd)
        with suppress(OSError):
            os.close(self.bundle_fd)


class _PinnedRoot:
    def __init__(
        self,
        *,
        path: Path,
        components: tuple[str, ...],
        descriptors: list[int],
        identities: tuple[_NativeIdentity, ...],
    ) -> None:
        self.path = path
        self.components = components
        self._descriptors = descriptors
        self.identities = identities
        self._closed = False

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        expected_identities: tuple[_NativeIdentity, ...] | None = None,
    ) -> _PinnedRoot:
        descriptors: list[int] = []
        components = path.parts[1:]
        try:
            current = _open_directory("/")
            descriptors.append(current)
            for component in components:
                current = _open_directory_at(current, component)
                descriptors.append(current)
            identities = tuple(_native_identity(os.fstat(fd)) for fd in descriptors)
            if expected_identities is not None and identities != expected_identities:
                raise OSError("Configured authority identity changed")
            _require_private_directory(descriptors[-1])
            result = cls(
                path=path,
                components=components,
                descriptors=descriptors,
                identities=identities,
            )
            result.assert_visible()
            return result
        except Exception:
            for descriptor in reversed(descriptors):
                with suppress(OSError):
                    os.close(descriptor)
            raise

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Pinned POSIX authority is closed")
        return self._descriptors[-1]

    @property
    def root_identity(self) -> _NativeIdentity:
        return self.identities[-1]

    def assert_visible(self) -> None:
        if self._closed:
            raise OSError("Pinned POSIX authority is closed")
        for descriptor, expected in zip(
            self._descriptors,
            self.identities,
            strict=True,
        ):
            if _native_identity(os.fstat(descriptor)) != expected:
                raise OSError("Pinned POSIX ancestor identity changed")
        _require_private_directory(self.descriptor)
        visible = _open_directory("/")
        try:
            if _native_identity(os.fstat(visible)) != self.identities[0]:
                raise OSError("POSIX filesystem root identity changed")
            for component, expected in zip(
                self.components,
                self.identities[1:],
                strict=True,
            ):
                child = _open_directory_at(visible, component)
                os.close(visible)
                visible = child
                if _native_identity(os.fstat(visible)) != expected:
                    raise OSError("POSIX authority ancestor identity changed")
        finally:
            os.close(visible)

    def close(self) -> None:
        if self._closed:
            return
        for descriptor in reversed(self._descriptors):
            with suppress(OSError):
                os.close(descriptor)
        self._descriptors.clear()
        self._closed = True


def _validated_snapshot_bundle(
    source_root: _PinnedRoot,
    snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
    *,
    maximum_depth: int,
) -> _ValidatedSnapshot:
    bundle_fd: int | None = None
    payload_fd: int | None = None
    try:
        bundle_fd = _open_directory_at(
            source_root.descriptor,
            snapshot.snapshot.snapshot_id,
        )
        if set(os.listdir(bundle_fd)) != {_PAYLOAD_NAME, _STATE_MANIFEST_NAME}:
            raise OSError("Snapshot bundle membership changed")
        payload_fd = _open_directory_at(bundle_fd, _PAYLOAD_NAME)
        inspection = _inspect_tree(
            payload_fd,
            maximum_entries=snapshot.snapshot.entry_count,
            maximum_bytes=snapshot.snapshot.byte_count,
            maximum_depth=maximum_depth,
        )
        if (
            inspection.tree_digest != snapshot.snapshot_tree_digest
            or inspection.entry_count != snapshot.snapshot.entry_count
            or inspection.byte_count != snapshot.snapshot.byte_count
        ):
            raise OSError("Snapshot payload identity changed")
        manifest_bytes, _identity = _read_regular_file(
            bundle_fd,
            _STATE_MANIFEST_NAME,
            maximum_bytes=_MAX_STATE_MANIFEST_BYTES,
        )
        if sha256(manifest_bytes).hexdigest() != snapshot.state_manifest_digest:
            raise OSError("Snapshot state manifest digest changed")
        expected_manifest = _expected_state_manifest(snapshot)
        if (
            manifest_bytes != canonical_json_bytes(expected_manifest)
            or _strict_json_object(manifest_bytes, name="snapshot state manifest")
            != expected_manifest
        ):
            raise OSError("Snapshot state manifest changed")
        return _ValidatedSnapshot(
            bundle_fd=bundle_fd,
            payload_fd=payload_fd,
            inspection=inspection,
        )
    except Exception as exc:
        if payload_fd is not None:
            os.close(payload_fd)
        if bundle_fd is not None:
            os.close(bundle_fd)
        raise PackageOfflineRestoreError(
            "Authenticated Package snapshot bundle is invalid",
            code="package_offline_restore_snapshot_invalid",
            evidence_ref=snapshot.evidence_id,
        ) from exc


def _revalidate_source(
    source: _ValidatedSnapshot,
    snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
    *,
    maximum_depth: int,
) -> None:
    try:
        if set(os.listdir(source.bundle_fd)) != {_PAYLOAD_NAME, _STATE_MANIFEST_NAME}:
            raise OSError("Snapshot bundle membership changed")
        observed = _inspect_tree(
            source.payload_fd,
            maximum_entries=snapshot.snapshot.entry_count,
            maximum_bytes=snapshot.snapshot.byte_count,
            maximum_depth=maximum_depth,
        )
        if observed.entries != source.inspection.entries:
            raise OSError("Snapshot tree changed during restore")
        manifest, _identity = _read_regular_file(
            source.bundle_fd,
            _STATE_MANIFEST_NAME,
            maximum_bytes=_MAX_STATE_MANIFEST_BYTES,
        )
        if sha256(manifest).hexdigest() != snapshot.state_manifest_digest:
            raise OSError("Snapshot state manifest changed during restore")
    except PackageOfflineRestoreError:
        raise
    except Exception as exc:
        raise PackageOfflineRestoreError(
            "Authenticated Package snapshot changed during restore",
            code="package_offline_restore_snapshot_invalid",
            evidence_ref=snapshot.evidence_id,
        ) from exc


def _validate_restore_namespace(
    restore_root: _PinnedRoot,
    request: PackageOfflineRestoreRequestV1,
    snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
    *,
    namespace_name: str,
    expected_source: _ValidatedSnapshot,
    expected_namespace_identity: _NativeIdentity | None = None,
    maximum_depth: int,
) -> PackageOfflineRestoreMaterializationReceiptV1:
    namespace_fd: int | None = None
    payload_fd: int | None = None
    try:
        namespace_fd = _open_directory_at(
            restore_root.descriptor,
            namespace_name,
        )
        if (
            expected_namespace_identity is not None
            and _native_identity(os.fstat(namespace_fd)) != expected_namespace_identity
        ):
            raise OSError("Published restore namespace identity changed")
        if set(os.listdir(namespace_fd)) != {_PAYLOAD_NAME, _RECEIPT_NAME}:
            raise OSError("Published restore namespace membership changed")
        marker, _identity = _read_regular_file(
            namespace_fd,
            _RECEIPT_NAME,
            maximum_bytes=_MAX_RECEIPT_BYTES,
        )
        receipt = PackageOfflineRestoreMaterializationReceiptV1.from_dict(
            _strict_json_object(marker, name="restore receipt")
        )
        if marker != canonical_json_bytes(receipt.to_dict()) or not receipt.matches(
            request, snapshot
        ):
            raise OSError("Published restore receipt does not match request")
        payload_fd = _open_directory_at(namespace_fd, _PAYLOAD_NAME)
        if _directory_identity(payload_fd) != receipt.restored_root_identity:
            raise OSError("Published restored root identity changed")
        inspection = _inspect_tree(
            payload_fd,
            maximum_entries=snapshot.snapshot.entry_count,
            maximum_bytes=snapshot.snapshot.byte_count,
            maximum_depth=maximum_depth,
        )
        if inspection.entries != expected_source.inspection.entries:
            raise OSError("Published restored tree differs from snapshot")
        restore_root.assert_visible()
        return receipt
    except Exception as exc:
        raise _materialization_error(
            "Existing Package restore namespace is not authorized"
        ) from exc
    finally:
        if payload_fd is not None:
            os.close(payload_fd)
        if namespace_fd is not None:
            os.close(namespace_fd)


def _inspect_tree(
    root_fd: int,
    *,
    maximum_entries: int,
    maximum_bytes: int,
    maximum_depth: int,
) -> _TreeInspection:
    entries: list[_TreeEntry] = []
    identities: dict[tuple[str, ...], _NativeIdentity] = {}
    total_bytes = 0

    def visit(directory_fd: int, prefix: tuple[str, ...]) -> None:
        nonlocal total_bytes
        for name in sorted(os.listdir(directory_fd)):
            _validate_entry_name(name)
            metadata = os.stat(
                name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            parts = prefix + (name,)
            if len(parts) > maximum_depth:
                raise OSError("Snapshot tree depth exceeds configured budget")
            logical_path = "/".join(parts)
            if len(entries) >= maximum_entries:
                raise OSError("Snapshot entry count exceeds receipt")
            if stat.S_ISDIR(metadata.st_mode):
                child = _open_directory_at(directory_fd, name)
                try:
                    identity = _native_identity(os.fstat(child))
                    if identity != _native_identity(metadata):
                        raise OSError("Snapshot directory identity changed")
                    entries.append(
                        _TreeEntry(
                            logical_path=logical_path,
                            kind="directory",
                            mode=stat.S_IMODE(metadata.st_mode),
                        )
                    )
                    identities[parts] = identity
                    visit(child, parts)
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                descriptor = _open_regular_file(directory_fd, name, write=False)
                try:
                    opened_before = os.fstat(descriptor)
                    if (
                        _native_identity(opened_before) != _native_identity(metadata)
                        or opened_before.st_nlink != 1
                    ):
                        raise OSError("Snapshot file identity changed")
                    digest = sha256()
                    file_bytes = 0
                    while chunk := os.read(descriptor, 64 * 1024):
                        file_bytes += len(chunk)
                        total_bytes += len(chunk)
                        if total_bytes > maximum_bytes:
                            raise OSError("Snapshot byte count exceeds receipt")
                        digest.update(chunk)
                    opened_after = os.fstat(descriptor)
                    if _stable_file_metadata(opened_before) != _stable_file_metadata(
                        opened_after
                    ):
                        raise OSError("Snapshot file changed while reading")
                    entries.append(
                        _TreeEntry(
                            logical_path=logical_path,
                            kind="file",
                            mode=stat.S_IMODE(metadata.st_mode),
                            content_digest=digest.hexdigest(),
                            byte_count=file_bytes,
                        )
                    )
                    identities[parts] = _native_identity(opened_after)
                finally:
                    os.close(descriptor)
            else:
                raise OSError("Snapshot contains an aliased or special member")

    visit(root_fd, ())
    ordered_entries = tuple(sorted(entries, key=lambda entry: entry.logical_path))
    manifest = {
        "entries": [entry.to_dict() for entry in ordered_entries],
        "manifestVersion": PACKAGE_POSIX_OFFLINE_RESTORE_TREE_MANIFEST_VERSION,
    }
    return _TreeInspection(
        entries=ordered_entries,
        identities=identities,
        tree_digest=sha256(canonical_json_bytes(manifest)).hexdigest(),
        entry_count=len(entries),
        byte_count=total_bytes,
    )


def _copy_tree(
    source_fd: int,
    target_fd: int,
    inspection: _TreeInspection,
) -> None:
    for entry in inspection.entries:
        parts = tuple(entry.logical_path.split("/"))
        target_parent = _open_relative_directory(target_fd, parts[:-1])
        try:
            if entry.kind == "directory":
                os.mkdir(parts[-1], mode=0o700, dir_fd=target_parent)
                continue
            source_parent = _open_relative_directory(source_fd, parts[:-1])
            try:
                source_file = _open_regular_file(
                    source_parent,
                    parts[-1],
                    write=False,
                )
            finally:
                os.close(source_parent)
            try:
                target_file = _open_regular_file(
                    target_parent,
                    parts[-1],
                    create_new=True,
                    write=True,
                )
                try:
                    source_before = os.fstat(source_file)
                    if (
                        _native_identity(source_before) != inspection.identities[parts]
                        or source_before.st_nlink != 1
                    ):
                        raise OSError("Snapshot file identity changed before copy")
                    digest = sha256()
                    byte_count = 0
                    while chunk := os.read(source_file, 64 * 1024):
                        _write_all(target_file, chunk)
                        digest.update(chunk)
                        byte_count += len(chunk)
                        if (
                            entry.byte_count is not None
                            and byte_count > entry.byte_count
                        ):
                            raise OSError("Snapshot file grew during copy")
                    source_after = os.fstat(source_file)
                    if _stable_file_metadata(source_before) != _stable_file_metadata(
                        source_after
                    ):
                        raise OSError("Snapshot file changed during copy")
                    if (
                        byte_count != entry.byte_count
                        or digest.hexdigest() != entry.content_digest
                    ):
                        raise OSError("Snapshot file content changed during copy")
                    os.fchmod(target_file, entry.mode)
                    os.fsync(target_file)
                finally:
                    os.close(target_file)
            finally:
                os.close(source_file)
        finally:
            os.close(target_parent)
    for entry in reversed(inspection.entries):
        if entry.kind != "directory":
            continue
        descriptor = _open_relative_directory(
            target_fd,
            tuple(entry.logical_path.split("/")),
        )
        try:
            os.fchmod(descriptor, entry.mode)
        finally:
            os.close(descriptor)


def _fsync_tree(root_fd: int, entries: tuple[_TreeEntry, ...]) -> None:
    directories = [
        tuple(entry.logical_path.split("/"))
        for entry in entries
        if entry.kind == "directory"
    ]
    for parts in sorted(
        directories, key=lambda value: (len(value), value), reverse=True
    ):
        descriptor = _open_relative_directory(root_fd, parts)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _delete_inspected_tree(
    root_fd: int,
    inspection: _TreeInspection,
) -> None:
    for entry in reversed(inspection.entries):
        parts = tuple(entry.logical_path.split("/"))
        parent = _open_relative_directory(root_fd, parts[:-1])
        try:
            expected = inspection.identities[parts]
            _assert_entry_identity(
                parent,
                parts[-1],
                expected,
                expected_kind=entry.kind,
            )
            if entry.kind == "directory":
                os.rmdir(parts[-1], dir_fd=parent)
            else:
                os.unlink(parts[-1], dir_fd=parent)
        finally:
            os.close(parent)


def _remove_owned_namespace(
    root_fd: int,
    name: str,
    *,
    expected_identity: _NativeIdentity,
) -> None:
    namespace = _open_directory_at(root_fd, name)
    try:
        if _native_identity(os.fstat(namespace)) != expected_identity:
            raise OSError("Owned staging namespace identity changed")
        _remove_directory_contents(namespace)
        if os.listdir(namespace):
            raise OSError("Owned staging namespace is not empty")
    finally:
        os.close(namespace)
    _assert_entry_identity(
        root_fd,
        name,
        expected_identity,
        expected_kind="directory",
    )
    os.rmdir(name, dir_fd=root_fd)


def _remove_directory_contents(directory_fd: int) -> None:
    for name in sorted(os.listdir(directory_fd)):
        _validate_entry_name(name)
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        identity = _native_identity(metadata)
        if stat.S_ISDIR(metadata.st_mode):
            child = _open_directory_at(directory_fd, name)
            try:
                if _native_identity(os.fstat(child)) != identity:
                    raise OSError("Owned staging directory identity changed")
                _remove_directory_contents(child)
            finally:
                os.close(child)
            _assert_entry_identity(
                directory_fd,
                name,
                identity,
                expected_kind="directory",
            )
            os.rmdir(name, dir_fd=directory_fd)
        elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            _assert_entry_identity(
                directory_fd,
                name,
                identity,
                expected_kind="file",
            )
            os.unlink(name, dir_fd=directory_fd)
        else:
            raise OSError("Owned staging namespace contains an unsafe entry")


def _expected_state_manifest(
    snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
) -> dict[str, object]:
    receipt = snapshot.snapshot
    return {
        "byteCount": receipt.byte_count,
        "coveredDomains": list(PACKAGE_PRE_B_SNAPSHOT_DOMAINS),
        "entryCount": receipt.entry_count,
        "legacyRootIdentity": receipt.legacy_root_identity,
        "manifestVersion": PACKAGE_POSIX_OFFLINE_RESTORE_STATE_MANIFEST_VERSION,
        "snapshotId": receipt.snapshot_id,
        "snapshotReceiptId": receipt.receipt_id,
        "snapshotRevision": receipt.snapshot_revision,
        "storeId": receipt.store_id,
        "treeDigest": snapshot.snapshot_tree_digest,
    }


def _validate_restore_inputs(
    request: PackageOfflineRestoreRequestV1,
    snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
    quiescence: PackageEpochCutoverQuiescenceReceiptV1,
    *,
    store_id: str,
) -> None:
    if not isinstance(request, PackageOfflineRestoreRequestV1):
        raise TypeError("Package offline-restore request is required")
    if not isinstance(snapshot, PackageOfflineRestoreSnapshotEvidenceV1):
        raise TypeError("Package offline snapshot evidence is required")
    if not isinstance(quiescence, PackageEpochCutoverQuiescenceReceiptV1):
        raise TypeError("Package epoch quiescence receipt is required")
    receipt = snapshot.snapshot
    if (
        request.store_id != store_id
        or receipt.store_id != store_id
        or quiescence.store_id != store_id
        or not quiescence.is_quiescent
        or request.snapshot_receipt_id != receipt.receipt_id
        or request.snapshot_evidence_id != snapshot.evidence_id
        or request.snapshot_id != receipt.snapshot_id
        or request.snapshot_revision != receipt.snapshot_revision
        or request.snapshot_entry_count != receipt.entry_count
        or request.snapshot_byte_count != receipt.byte_count
        or request.snapshot_tree_digest != snapshot.snapshot_tree_digest
        or request.state_manifest_digest != snapshot.state_manifest_digest
        or request.legacy_root_identity != receipt.legacy_root_identity
        or snapshot.covered_domains != PACKAGE_PRE_B_SNAPSHOT_DOMAINS
    ):
        raise PackageOfflineRestoreError(
            "Package offline-restore evidence changed",
            code="package_offline_restore_snapshot_invalid",
            evidence_ref=request.snapshot_receipt_id,
        )


def _read_regular_file(
    directory_fd: int,
    name: str,
    *,
    maximum_bytes: int,
) -> tuple[bytes, _NativeIdentity]:
    descriptor = _open_regular_file(directory_fd, name, write=False)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError("Expected one regular file")
        contents = bytearray()
        while chunk := os.read(descriptor, 64 * 1024):
            contents.extend(chunk)
            if len(contents) > maximum_bytes:
                raise OSError("Bounded metadata file is too large")
        after = os.fstat(descriptor)
        if _stable_file_metadata(before) != _stable_file_metadata(after):
            raise OSError("Metadata file changed while reading")
        return bytes(contents), _native_identity(after)
    finally:
        os.close(descriptor)


def _write_new_file(directory_fd: int, name: str, contents: bytes) -> None:
    descriptor = _open_regular_file(
        directory_fd,
        name,
        create_new=True,
        write=True,
    )
    try:
        _write_all(descriptor, contents)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, contents: bytes) -> None:
    view = memoryview(contents)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("Restore write made no progress")
        view = view[written:]


def _strict_json_object(payload: bytes, *, name: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{name} contains a duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{name} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return cast(dict[str, object], value)


def _validated_root_path(value: str | Path, *, name: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise TypeError(f"Package {name} root must be a filesystem path")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        raise PackageOfflineRestoreError(
            f"Package {name} root must be absolute and normalized",
            code="package_offline_restore_materialization_invalid",
        )
    return path


def _validated_limit(value: int, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Package {name} must be a non-negative integer")
    return value


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _pinned_roots_overlap(left: _PinnedRoot, right: _PinnedRoot) -> bool:
    return (
        left.root_identity in right.identities or right.root_identity in left.identities
    )


def _validate_entry_name(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or "\x00" in name:
        raise OSError("Snapshot entry name is invalid")
    name.encode("utf-8")


def _open_directory(path: str | Path) -> int:
    return os.open(path, _directory_open_flags())


def _open_directory_at(parent_fd: int, name: str) -> int:
    descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise OSError("Expected a rooted directory")
    return descriptor


def _open_regular_file(
    directory_fd: int,
    name: str,
    *,
    create_new: bool = False,
    write: bool,
) -> int:
    flags = (os.O_WRONLY if write else os.O_RDONLY) | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    if create_new:
        flags |= os.O_CREAT | os.O_EXCL
    return os.open(name, flags, 0o600, dir_fd=directory_fd)


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
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


def _entry_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _native_identity(metadata: os.stat_result) -> _NativeIdentity:
    return metadata.st_dev, metadata.st_ino


def _directory_identity(descriptor: int) -> str:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise OSError("Restored Package root is not a directory")
    return sha256(
        canonical_json_bytes(
            {
                "device": metadata.st_dev,
                "fileType": "directory",
                "identityVersion": 1,
                "inode": metadata.st_ino,
            }
        )
    ).hexdigest()


def _stable_file_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _assert_entry_identity(
    directory_fd: int,
    name: str,
    expected: _NativeIdentity,
    *,
    expected_kind: _EntryKind,
) -> None:
    metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if _native_identity(metadata) != expected:
        raise OSError("Owned restore entry identity changed")
    if expected_kind == "directory" and not stat.S_ISDIR(metadata.st_mode):
        raise OSError("Owned restore directory type changed")
    if expected_kind == "file" and (
        not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
    ):
        raise OSError("Owned restore file type changed")


def _require_private_directory(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise OSError("Package authority root is not private")


def _directory_open_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _supports_posix_rooted_io() -> bool:
    return bool(
        _fcntl is not None
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and os.listdir in os.supports_fd
        and _noreplace_rename_function() is not None
    )


_RenameAt = Any


def _noreplace_rename_function() -> tuple[_RenameAt, int] | None:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except OSError:
        return None
    if sys.platform.startswith("linux"):
        function = getattr(libc, "renameat2", None)
        flag = 1  # RENAME_NOREPLACE
    elif sys.platform == "darwin":
        function = getattr(libc, "renameatx_np", None)
        flag = 0x00000004  # RENAME_EXCL
    else:
        return None
    if function is None:
        return None
    return function, flag


def _rename_directory_noreplace(
    source_directory_fd: int,
    source_name: str,
    target_directory_fd: int,
    target_name: str,
) -> None:
    resolved = _noreplace_rename_function()
    if resolved is None:
        raise OSError(errno.ENOTSUP, "Atomic no-replace rename is unavailable")
    function, flag = resolved
    ctypes.set_errno(0)
    result = function(
        source_directory_fd,
        os.fsencode(source_name),
        target_directory_fd,
        os.fsencode(target_name),
        flag,
    )
    if result != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, os.strerror(error_number), target_name)


def _materialization_error(message: str) -> PackageOfflineRestoreError:
    return PackageOfflineRestoreError(
        message,
        code="package_offline_restore_materialization_invalid",
    )


__all__ = ()
