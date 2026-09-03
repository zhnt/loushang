"""Windows rooted snapshot materialization for dark PLC9B offline restore.

The public protocol remains pathless.  This platform capability owner alone
knows the configured snapshot, restore, and current-B authorities.  Every
lookup, copy, publication, replay, and cleanup operation is performed relative
to an identity-pinned Windows directory handle.
"""

from __future__ import annotations

import json
import os
import re
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

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
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    supports_windows_rooted_io,
    windows_flush_directory,
    windows_flush_file,
    windows_listdir_at,
    windows_rename_at,
    windows_rmdir_at,
    windows_stat_at,
    windows_unlink_at,
)

if os.name == "nt":
    import msvcrt as _msvcrt
else:  # pragma: no cover - collected on non-Windows hosts
    _msvcrt = None  # type: ignore[assignment]

PACKAGE_WINDOWS_OFFLINE_RESTORE_TREE_MANIFEST_VERSION = 1
PACKAGE_WINDOWS_OFFLINE_RESTORE_STATE_MANIFEST_VERSION = 1
DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_ENTRIES = 100_000
DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_BYTES = 16 * 1024 * 1024 * 1024
DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_DEPTH = 128

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


@dataclass(slots=True)
class _ValidatedSnapshot:
    bundle_fd: int
    payload_fd: int
    inspection: _TreeInspection

    def close(self) -> None:
        os.close(self.payload_fd)
        os.close(self.bundle_fd)


class PackageWindowsOfflineRestoreMaterializer:
    """Own rooted snapshot reads and one isolated Windows restore authority."""

    def __init__(
        self,
        snapshot_authority_root: str | Path,
        restore_authority_root: str | Path,
        *,
        current_b_authority_root: str | Path,
        store_id: str,
        maximum_entries: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_ENTRIES,
        maximum_bytes: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_BYTES,
        maximum_depth: int = DEFAULT_PACKAGE_WINDOWS_OFFLINE_RESTORE_MAX_DEPTH,
    ) -> None:
        if os.name != "nt" or not supports_windows_rooted_io() or _msvcrt is None:
            raise _materialization_error("Windows offline restore is unavailable")
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
        roots = (self._snapshot_root, self._restore_root, self._current_b_root)
        if any(
            _paths_overlap(left, right)
            for index, left in enumerate(roots)
            for right in roots[index + 1 :]
        ):
            raise _materialization_error(
                "Snapshot, restore, and current B authorities must be disjoint"
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
        pinned: list[_PinnedWindowsRoot] = []
        try:
            pinned = [_PinnedWindowsRoot.open(root) for root in roots]
            if any(
                _pinned_roots_overlap(left, right)
                for index, left in enumerate(pinned)
                for right in pinned[index + 1 :]
            ):
                raise OSError("Windows offline-restore authorities overlap natively")
            self._snapshot_identities = pinned[0].identities
            self._restore_identities = pinned[1].identities
            self._current_b_identities = pinned[2].identities
        except PackageOfflineRestoreError:
            raise
        except Exception as exc:
            raise _materialization_error(
                "Windows offline-restore authority is untrusted"
            ) from exc
        finally:
            for root in reversed(pinned):
                root.close()

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
            source_root: _PinnedWindowsRoot | None = None
            current_b_root: _PinnedWindowsRoot | None = None
            source: _ValidatedSnapshot | None = None
            staging_fd: int | None = None
            staging_identity: _NativeIdentity | None = None
            staging_created = False
            published = False
            completed = False
            staging_name = f"staging-{request.request_id}"
            try:
                current_b_root = _PinnedWindowsRoot.open(
                    self._current_b_root,
                    expected_identities=self._current_b_identities,
                )
                if (
                    _directory_identity(current_b_root.descriptor)
                    != request.current_root_identity
                ):
                    raise _materialization_error(
                        "Windows current B authority identity changed"
                    )
                source_root = _PinnedWindowsRoot.open(
                    self._snapshot_root,
                    expected_identities=self._snapshot_identities,
                )
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
                staging_fd = _open_directory_at(
                    restore_root.descriptor,
                    staging_name,
                    create_new=True,
                )
                staging_created = True
                staging_identity = _native_identity(os.fstat(staging_fd))
                payload_fd = _open_directory_at(
                    staging_fd,
                    _PAYLOAD_NAME,
                    create_new=True,
                )
                try:
                    _copy_tree(source.payload_fd, payload_fd, source.inspection)
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
                    receipt = PackageOfflineRestoreMaterializationReceiptV1.create(
                        request,
                        snapshot=snapshot,
                        quiescence_receipt_id=quiescence.receipt_id,
                        restored_root_identity=_directory_identity(payload_fd),
                    )
                    _write_new_file(
                        staging_fd,
                        _RECEIPT_NAME,
                        canonical_json_bytes(receipt.to_dict()),
                    )
                    _flush_tree(payload_fd, copied.entries)
                    windows_flush_directory(payload_fd)
                finally:
                    os.close(payload_fd)
                windows_flush_directory(staging_fd)
                os.close(staging_fd)
                staging_fd = None
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
                windows_rename_at(
                    restore_root.descriptor,
                    staging_name,
                    request.restore_namespace_id,
                )
                published = True
                windows_flush_directory(restore_root.descriptor)
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
                    raise _materialization_error(
                        "Current B root identity changed before return"
                    )
                completed = True
                return receipt
            except PackageOfflineRestoreError:
                raise
            except Exception as exc:
                raise _materialization_error(
                    "Windows offline restore failed closed"
                ) from exc
            finally:
                if staging_fd is not None:
                    os.close(staging_fd)
                if source is not None:
                    source.close()
                if source_root is not None:
                    source_root.close()
                if current_b_root is not None:
                    current_b_root.close()
                if staging_created and not completed:
                    if staging_identity is None:
                        raise PackageOfflineRestoreError(
                            "Windows offline-restore staging identity was not captured",
                            code="package_offline_restore_cleanup_failed",
                        )
                    try:
                        _remove_owned_namespace(
                            restore_root.descriptor,
                            request.restore_namespace_id if published else staging_name,
                            expected_identity=staging_identity,
                        )
                        windows_flush_directory(restore_root.descriptor)
                    except Exception as cleanup_error:
                        raise PackageOfflineRestoreError(
                            "Windows offline-restore staging cleanup failed",
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
                    share_delete=True,
                )
                try:
                    if set(windows_listdir_at(namespace_fd)) != {
                        _PAYLOAD_NAME,
                        _RECEIPT_NAME,
                    }:
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
                    payload_fd = _open_directory_at(
                        namespace_fd,
                        _PAYLOAD_NAME,
                        share_delete=True,
                    )
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
                    windows_rmdir_at(namespace_fd, _PAYLOAD_NAME)
                    _assert_entry_identity(
                        namespace_fd,
                        _RECEIPT_NAME,
                        marker_identity,
                        expected_kind="file",
                    )
                    windows_unlink_at(namespace_fd, _RECEIPT_NAME)
                    windows_flush_directory(namespace_fd)
                    namespace_identity = _native_identity(os.fstat(namespace_fd))
                finally:
                    os.close(namespace_fd)
                _assert_entry_identity(
                    restore_root.descriptor,
                    receipt.restore_namespace_id,
                    namespace_identity,
                    expected_kind="directory",
                )
                windows_rmdir_at(
                    restore_root.descriptor,
                    receipt.restore_namespace_id,
                )
                windows_flush_directory(restore_root.descriptor)
                restore_root.assert_visible()
            except Exception as exc:
                raise PackageOfflineRestoreError(
                    "Exact isolated Package restore cleanup could not be proven",
                    code="package_offline_restore_cleanup_failed",
                    evidence_ref=receipt.materialization_receipt_id,
                ) from exc

    @contextmanager
    def _exclusive_restore_root(self) -> Iterator[_PinnedWindowsRoot]:
        if _msvcrt is None:  # pragma: no cover - constructor rejects non-Windows
            raise _materialization_error("Windows locking is unavailable")
        with self._thread_lock:
            root = _PinnedWindowsRoot.open(
                self._restore_root,
                expected_identities=self._restore_identities,
            )
            lock_fd: int | None = None
            locked = False
            try:
                try:
                    lock_fd = open_windows_regular_file_at(
                        root.descriptor,
                        _LOCK_NAME,
                        create_new=False,
                        write=True,
                    )
                except FileNotFoundError:
                    try:
                        lock_fd = open_windows_regular_file_at(
                            root.descriptor,
                            _LOCK_NAME,
                            create_new=True,
                            write=True,
                        )
                        _write_all(lock_fd, b"\0")
                        windows_flush_file(lock_fd)
                        windows_flush_directory(root.descriptor)
                    except FileExistsError:
                        lock_fd = open_windows_regular_file_at(
                            root.descriptor,
                            _LOCK_NAME,
                            create_new=False,
                            write=True,
                        )
                if os.fstat(lock_fd).st_size != 1:
                    raise OSError("Windows restore lock file changed")
                os.lseek(lock_fd, 0, os.SEEK_SET)
                getattr(_msvcrt, "locking")(
                    lock_fd,
                    getattr(_msvcrt, "LK_LOCK"),
                    1,
                )
                locked = True
                root.assert_visible()
                yield root
                root.assert_visible()
            except PackageOfflineRestoreError:
                raise
            except Exception as exc:
                raise _materialization_error(
                    "Windows offline-restore lock or authority is untrusted"
                ) from exc
            finally:
                if lock_fd is not None:
                    if locked:
                        with suppress(OSError):
                            os.lseek(lock_fd, 0, os.SEEK_SET)
                            getattr(_msvcrt, "locking")(
                                lock_fd,
                                getattr(_msvcrt, "LK_UNLCK"),
                                1,
                            )
                    os.close(lock_fd)
                root.close()


class _PinnedWindowsRoot:
    def __init__(
        self,
        *,
        path: Path,
        descriptors: list[int],
        identities: tuple[_NativeIdentity, ...],
    ) -> None:
        self.path = path
        self._descriptors = descriptors
        self.identities = identities
        self._closed = False

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        expected_identities: tuple[_NativeIdentity, ...] | None = None,
    ) -> _PinnedWindowsRoot:
        descriptors: list[int] = []
        try:
            current = open_windows_directory(
                Path(path.anchor),
                share_delete=False,
                writable=False,
            )
            descriptors.append(current)
            for index, component in enumerate(path.parts[1:]):
                current = open_windows_directory(
                    component,
                    dir_fd=current,
                    share_delete=False,
                    writable=index == len(path.parts[1:]) - 1,
                )
                descriptors.append(current)
            identities = tuple(_native_identity(os.fstat(fd)) for fd in descriptors)
            if expected_identities is not None and identities != expected_identities:
                raise OSError("Configured Windows authority identity changed")
            root = cls(path=path, descriptors=descriptors, identities=identities)
            root.assert_visible()
            return root
        except Exception:
            for descriptor in reversed(descriptors):
                with suppress(OSError):
                    os.close(descriptor)
            raise

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Windows authority handle is closed")
        return self._descriptors[-1]

    def assert_visible(self) -> None:
        if self._closed:
            raise OSError("Windows authority handle is closed")
        if (
            tuple(_native_identity(os.fstat(fd)) for fd in self._descriptors)
            != self.identities
        ):
            raise OSError("Pinned Windows authority identity changed")
        visible = _PinnedWindowsRoot.open_unchecked(self.path)
        try:
            if visible.identities != self.identities:
                raise OSError("Visible Windows authority identity changed")
        finally:
            visible.close()

    @classmethod
    def open_unchecked(cls, path: Path) -> _PinnedWindowsRoot:
        descriptors: list[int] = []
        try:
            current = open_windows_directory(
                Path(path.anchor),
                share_delete=False,
                writable=False,
            )
            descriptors.append(current)
            for index, component in enumerate(path.parts[1:]):
                current = open_windows_directory(
                    component,
                    dir_fd=current,
                    share_delete=False,
                    writable=index == len(path.parts[1:]) - 1,
                )
                descriptors.append(current)
            return cls(
                path=path,
                descriptors=descriptors,
                identities=tuple(_native_identity(os.fstat(fd)) for fd in descriptors),
            )
        except Exception:
            for descriptor in reversed(descriptors):
                with suppress(OSError):
                    os.close(descriptor)
            raise

    def close(self) -> None:
        if self._closed:
            return
        for descriptor in reversed(self._descriptors):
            with suppress(OSError):
                os.close(descriptor)
        self._descriptors.clear()
        self._closed = True


def _validated_snapshot_bundle(
    source_root: _PinnedWindowsRoot,
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
        if set(windows_listdir_at(bundle_fd)) != {_PAYLOAD_NAME, _STATE_MANIFEST_NAME}:
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
        manifest_bytes, _ = _read_regular_file(
            bundle_fd,
            _STATE_MANIFEST_NAME,
            maximum_bytes=_MAX_STATE_MANIFEST_BYTES,
        )
        expected = _expected_state_manifest(snapshot)
        if (
            sha256(manifest_bytes).hexdigest() != snapshot.state_manifest_digest
            or manifest_bytes != canonical_json_bytes(expected)
            or _strict_json_object(manifest_bytes, name="snapshot state manifest")
            != expected
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
        if set(windows_listdir_at(source.bundle_fd)) != {
            _PAYLOAD_NAME,
            _STATE_MANIFEST_NAME,
        }:
            raise OSError("Snapshot bundle membership changed")
        observed = _inspect_tree(
            source.payload_fd,
            maximum_entries=snapshot.snapshot.entry_count,
            maximum_bytes=snapshot.snapshot.byte_count,
            maximum_depth=maximum_depth,
        )
        if observed.entries != source.inspection.entries:
            raise OSError("Snapshot tree changed during restore")
        manifest, _ = _read_regular_file(
            source.bundle_fd,
            _STATE_MANIFEST_NAME,
            maximum_bytes=_MAX_STATE_MANIFEST_BYTES,
        )
        if sha256(manifest).hexdigest() != snapshot.state_manifest_digest:
            raise OSError("Snapshot state manifest changed during restore")
    except Exception as exc:
        raise PackageOfflineRestoreError(
            "Authenticated Package snapshot changed during restore",
            code="package_offline_restore_snapshot_invalid",
            evidence_ref=snapshot.evidence_id,
        ) from exc


def _validate_restore_namespace(
    restore_root: _PinnedWindowsRoot,
    request: PackageOfflineRestoreRequestV1,
    snapshot: PackageOfflineRestoreSnapshotEvidenceV1,
    *,
    namespace_name: str,
    expected_source: _ValidatedSnapshot,
    maximum_depth: int,
    expected_namespace_identity: _NativeIdentity | None = None,
) -> PackageOfflineRestoreMaterializationReceiptV1:
    namespace_fd: int | None = None
    payload_fd: int | None = None
    try:
        namespace_fd = _open_directory_at(restore_root.descriptor, namespace_name)
        if (
            expected_namespace_identity is not None
            and _native_identity(os.fstat(namespace_fd)) != expected_namespace_identity
        ):
            raise OSError("Published restore namespace identity changed")
        if set(windows_listdir_at(namespace_fd)) != {_PAYLOAD_NAME, _RECEIPT_NAME}:
            raise OSError("Published restore namespace membership changed")
        marker, _ = _read_regular_file(
            namespace_fd,
            _RECEIPT_NAME,
            maximum_bytes=_MAX_RECEIPT_BYTES,
        )
        receipt = PackageOfflineRestoreMaterializationReceiptV1.from_dict(
            _strict_json_object(marker, name="restore receipt")
        )
        if marker != canonical_json_bytes(receipt.to_dict()) or not receipt.matches(
            request,
            snapshot,
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
        for name in sorted(windows_listdir_at(directory_fd)):
            _validate_entry_name(name)
            metadata = windows_stat_at(directory_fd, name)
            parts = prefix + (name,)
            if len(parts) > maximum_depth or len(entries) >= maximum_entries:
                raise OSError("Snapshot tree exceeds configured entry/depth budget")
            logical_path = "/".join(parts)
            if stat.S_ISDIR(metadata.st_mode) and not _is_reparse(metadata):
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
            elif (
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_nlink == 1
                and not _is_reparse(metadata)
            ):
                descriptor = open_windows_regular_file_at(
                    directory_fd,
                    name,
                    create_new=False,
                    write=False,
                )
                try:
                    before = os.fstat(descriptor)
                    if _native_identity(before) != _native_identity(metadata):
                        raise OSError("Snapshot file identity changed")
                    digest = sha256()
                    file_bytes = 0
                    while chunk := os.read(descriptor, 64 * 1024):
                        file_bytes += len(chunk)
                        total_bytes += len(chunk)
                        if total_bytes > maximum_bytes:
                            raise OSError("Snapshot byte count exceeds receipt")
                        digest.update(chunk)
                    after = os.fstat(descriptor)
                    if _stable_file_metadata(before) != _stable_file_metadata(after):
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
                    identities[parts] = _native_identity(after)
                finally:
                    os.close(descriptor)
            else:
                raise OSError("Snapshot contains an aliased or special member")

    visit(root_fd, ())
    ordered = tuple(sorted(entries, key=lambda entry: entry.logical_path))
    manifest = {
        "entries": [entry.to_dict() for entry in ordered],
        "manifestVersion": PACKAGE_WINDOWS_OFFLINE_RESTORE_TREE_MANIFEST_VERSION,
    }
    return _TreeInspection(
        entries=ordered,
        identities=identities,
        tree_digest=sha256(canonical_json_bytes(manifest)).hexdigest(),
        entry_count=len(ordered),
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
                child = _open_directory_at(
                    target_parent,
                    parts[-1],
                    create_new=True,
                )
                os.close(child)
                continue
            source_parent = _open_relative_directory(source_fd, parts[:-1])
            try:
                source_file = open_windows_regular_file_at(
                    source_parent,
                    parts[-1],
                    create_new=False,
                    write=False,
                )
            finally:
                os.close(source_parent)
            try:
                target_file = open_windows_regular_file_at(
                    target_parent,
                    parts[-1],
                    create_new=True,
                    write=True,
                )
                try:
                    before = os.fstat(source_file)
                    if _native_identity(before) != inspection.identities[parts]:
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
                    after = os.fstat(source_file)
                    if _stable_file_metadata(before) != _stable_file_metadata(after):
                        raise OSError("Snapshot file changed during copy")
                    if (
                        byte_count != entry.byte_count
                        or digest.hexdigest() != entry.content_digest
                    ):
                        raise OSError("Snapshot file content changed during copy")
                    windows_flush_file(target_file)
                finally:
                    os.close(target_file)
            finally:
                os.close(source_file)
        finally:
            os.close(target_parent)


def _flush_tree(root_fd: int, entries: tuple[_TreeEntry, ...]) -> None:
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
            windows_flush_directory(descriptor)
        finally:
            os.close(descriptor)


def _delete_inspected_tree(root_fd: int, inspection: _TreeInspection) -> None:
    for entry in reversed(inspection.entries):
        parts = tuple(entry.logical_path.split("/"))
        parent = _open_relative_directory(root_fd, parts[:-1])
        try:
            _assert_entry_identity(
                parent,
                parts[-1],
                inspection.identities[parts],
                expected_kind=entry.kind,
            )
            if entry.kind == "directory":
                windows_rmdir_at(parent, parts[-1])
            else:
                windows_unlink_at(parent, parts[-1])
        finally:
            os.close(parent)


def _remove_owned_namespace(
    root_fd: int,
    name: str,
    *,
    expected_identity: _NativeIdentity,
) -> None:
    namespace = _open_directory_at(root_fd, name, share_delete=True)
    try:
        if _native_identity(os.fstat(namespace)) != expected_identity:
            raise OSError("Owned staging namespace identity changed")
        _remove_directory_contents(namespace)
        if windows_listdir_at(namespace):
            raise OSError("Owned staging namespace is not empty")
    finally:
        os.close(namespace)
    _assert_entry_identity(root_fd, name, expected_identity, expected_kind="directory")
    windows_rmdir_at(root_fd, name)


def _remove_directory_contents(directory_fd: int) -> None:
    for name in sorted(windows_listdir_at(directory_fd)):
        _validate_entry_name(name)
        metadata = windows_stat_at(directory_fd, name)
        identity = _native_identity(metadata)
        if stat.S_ISDIR(metadata.st_mode) and not _is_reparse(metadata):
            child = _open_directory_at(directory_fd, name, share_delete=True)
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
            windows_rmdir_at(directory_fd, name)
        elif (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and not _is_reparse(metadata)
        ):
            _assert_entry_identity(
                directory_fd,
                name,
                identity,
                expected_kind="file",
            )
            windows_unlink_at(directory_fd, name)
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
        "manifestVersion": PACKAGE_WINDOWS_OFFLINE_RESTORE_STATE_MANIFEST_VERSION,
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
        or request.legacy_root_identity != receipt.legacy_root_identity
        or request.snapshot_tree_digest != snapshot.snapshot_tree_digest
        or request.state_manifest_digest != snapshot.state_manifest_digest
        or snapshot.covered_domains != PACKAGE_PRE_B_SNAPSHOT_DOMAINS
    ):
        raise PackageOfflineRestoreError(
            "Package offline-restore request does not match snapshot/quiescence",
            code="package_offline_restore_snapshot_invalid",
            evidence_ref=snapshot.evidence_id,
        )


def _read_regular_file(
    directory_fd: int,
    name: str,
    *,
    maximum_bytes: int,
) -> tuple[bytes, _NativeIdentity]:
    descriptor = open_windows_regular_file_at(
        directory_fd,
        name,
        create_new=False,
        write=False,
    )
    try:
        before = os.fstat(descriptor)
        if before.st_size > maximum_bytes:
            raise OSError("Windows restore metadata exceeds budget")
        payload = bytearray()
        while chunk := os.read(descriptor, min(64 * 1024, maximum_bytes + 1)):
            payload.extend(chunk)
            if len(payload) > maximum_bytes:
                raise OSError("Windows restore metadata exceeds budget")
        after = os.fstat(descriptor)
        if _stable_file_metadata(before) != _stable_file_metadata(after):
            raise OSError("Windows restore metadata changed while reading")
        return bytes(payload), _native_identity(after)
    finally:
        os.close(descriptor)


def _write_new_file(directory_fd: int, name: str, contents: bytes) -> None:
    descriptor = open_windows_regular_file_at(
        directory_fd,
        name,
        create_new=True,
        write=True,
    )
    try:
        _write_all(descriptor, contents)
        windows_flush_file(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, contents: bytes) -> None:
    view = memoryview(contents)
    while view:
        written = os.write(descriptor, view)
        if written < 1:
            raise OSError("Windows restore write made no progress")
        view = view[written:]


def _strict_json_object(payload: bytes, *, name: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate field in {name}")
            result[key] = value
        return result

    try:
        value = json.loads(payload, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {name}") from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"Invalid {name}")
    return value


def _validated_root_path(value: str | Path, *, name: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise TypeError(f"Package {name} root must be a filesystem path")
    root = Path(value)
    if (
        not root.is_absolute()
        or ".." in root.parts
        or not root.anchor
        or root == Path(root.anchor)
    ):
        raise _materialization_error(
            f"Package {name} root must be absolute and normalized"
        )
    return root


def _validated_limit(value: int, *, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"Package {name} must be a positive integer")
    return value


def _paths_overlap(left: Path, right: Path) -> bool:
    left_parts = tuple(part.casefold() for part in left.parts)
    right_parts = tuple(part.casefold() for part in right.parts)
    shorter, longer = sorted((left_parts, right_parts), key=len)
    return longer[: len(shorter)] == shorter


def _pinned_roots_overlap(
    left: _PinnedWindowsRoot,
    right: _PinnedWindowsRoot,
) -> bool:
    left_root = left.identities[-1]
    right_root = right.identities[-1]
    return left_root in right.identities or right_root in left.identities


def _validate_entry_name(name: str) -> None:
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
    ):
        raise OSError("Windows restore entry name is unsafe")


def _open_directory_at(
    parent_fd: int,
    name: str,
    *,
    create_new: bool = False,
    share_delete: bool = False,
) -> int:
    _validate_entry_name(name)
    descriptor = open_windows_directory(
        name,
        dir_fd=parent_fd,
        create_new=create_new,
        share_delete=share_delete,
        writable=True,
    )
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        os.close(descriptor)
        raise OSError("Windows restore child is not a direct directory")
    return descriptor


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
        windows_stat_at(directory_fd, name)
    except FileNotFoundError:
        return False
    return True


def _native_identity(metadata: os.stat_result) -> _NativeIdentity:
    return int(metadata.st_dev), int(metadata.st_ino)


def _directory_identity(descriptor: int) -> str:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        raise OSError("Windows restore directory identity is invalid")
    return sha256(
        canonical_json_bytes(
            {
                "device": int(metadata.st_dev),
                "fileType": "directory",
                "identityVersion": 1,
                "inode": int(metadata.st_ino),
            }
        )
    ).hexdigest()


def _stable_file_metadata(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        int(metadata.st_ctime_ns),
        int(metadata.st_nlink),
        int(getattr(metadata, "st_file_attributes", 0)),
        int(getattr(metadata, "st_reparse_tag", 0)),
    )


def _assert_entry_identity(
    directory_fd: int,
    name: str,
    expected: _NativeIdentity,
    *,
    expected_kind: _EntryKind,
) -> None:
    metadata = windows_stat_at(directory_fd, name)
    if _native_identity(metadata) != expected or _is_reparse(metadata):
        raise OSError("Windows restore entry identity changed")
    if expected_kind == "directory" and not stat.S_ISDIR(metadata.st_mode):
        raise OSError("Windows restore entry type changed")
    if expected_kind == "file" and (
        not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
    ):
        raise OSError("Windows restore entry type changed")


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_reparse_tag", 0)
        or getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _materialization_error(message: str) -> PackageOfflineRestoreError:
    return PackageOfflineRestoreError(
        message,
        code="package_offline_restore_materialization_invalid",
    )


__all__ = ()
