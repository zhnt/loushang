"""Windows-native rooted Store materialization for PLC9B3e-3c2.

The Store path remains private configuration of one role-specific owner.  Each
operation pins the complete visible ancestor chain, creates and settles bytes
through root-relative native handles, and returns only an existing typed ref.
"""

from __future__ import annotations

import os
import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.resources.packages.plugin_lifecycle._file_sinks import (
    ReuseFileSink as _ReuseFileSink,
)
from loushang.harness.resources.packages.plugin_lifecycle._file_sinks import (
    VerifiedFileSink as _WindowsFileSink,
)
from loushang.harness.resources.packages.plugin_lifecycle._materialization_shared import (
    ObservedTree,
    PackageStorePinnedRootPort,
    PackageStorePlatformPort,
    finish_verified_tree,
    validate_receipt_at_root,
)
from loushang.harness.resources.packages.plugin_lifecycle._tree_validation import (
    TreeDirectoryReadPort,
    TreeEntryObservation,
    TreeFileReadPort,
)
from loushang.harness.resources.packages.plugin_lifecycle._tree_validation import (
    collect_tree as _collect_observed_tree,
)
from loushang.harness.resources.packages.plugin_lifecycle._tree_validation import (
    validate_tree_contents as _validate_observed_tree_contents,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingReceiptV1,
    PackageArtifactStagingRequestV1,
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_gc import (
    PackageStoreGcResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreGcTombstoneV1,
    PackageStoreSettlementJournal,
    PackageStoreSettlementJournalError,
    PackageStoreSettlementRecordV1,
    dependency_content_store_revision,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
    PackageVerifiedTreeEntryV1,
    PackageVerifiedTreeManifestV1,
    PackageVerifiedTreeSinkPort,
    PackageVerifiedTreeTransferOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    supports_windows_rooted_io,
    windows_flush_file,
    windows_listdir_at,
    windows_rename_at,
    windows_rmdir_at,
    windows_stat_at,
    windows_unlink_at,
)

_Role = Literal["dependency", "root"]
_Identity = tuple[int, int]


class WindowsPackageDependencyMaterializationStore:
    """Dependency-only adapter over one configured immutable Windows Store."""

    def __init__(
        self,
        root: str | Path,
        *,
        store_identity: str,
        settlement_journal: PackageStoreSettlementJournal,
        transfer: PackageVerifiedTreeTransferOwner | None = None,
        commit_probe: Callable[[], None] | None = None,
        receipt_probe: Callable[[], None] | None = None,
    ) -> None:
        self._store = _WindowsRoleStore(
            root,
            role="dependency",
            store_identity=store_identity,
            settlement_journal=settlement_journal,
            transfer=transfer,
            commit_probe=commit_probe,
            receipt_probe=receipt_probe,
        )

    def open_dependency_sink(
        self,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> AbstractContextManager[PackageVerifiedTreeSinkPort]:
        return self._store.open_sink(request, manifest)

    def stage_dependency(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.stage(request, candidate)

    def validate_dependency_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.validate_receipt(receipt)

    def read_validate_dependency_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.read_validate_receipt(receipt)

    def read_operation_settlements(
        self, operation_id: str
    ) -> tuple[PackageStoreSettlementRecordV1, ...]:
        return self._store.read_operation_settlements(operation_id)

    def delete_settlement(
        self, settlement: PackageStoreSettlementRecordV1
    ) -> PackageStoreGcResultV1:
        """Apply a caller-authorized exact dependency Store deletion."""

        return self._store.delete_settlement(settlement)


class WindowsPackageDependencyReadOnlyStore:
    """Store-verified dependency bytes for Product-owned execution proof."""

    read_only = True

    def __init__(
        self,
        root: str | Path,
        *,
        store_identity: str,
        settlement_journal: PackageStoreSettlementJournal,
    ) -> None:
        self._store = _WindowsRoleStore(
            root,
            role="dependency",
            store_identity=store_identity,
            settlement_journal=settlement_journal,
            transfer=None,
            commit_probe=None,
            receipt_probe=None,
            read_only=True,
        )

    def read_dependency_file(
        self,
        settlement: PackageStoreSettlementRecordV1,
        logical_path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        return self._store.read_settlement_file(
            settlement, logical_path, max_bytes=max_bytes
        )

    def read_dependency_files(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
    ) -> tuple[bytes, ...]:
        return self._store.read_settlement_files(settlement, members)


class WindowsPackagePluginRootMaterializationStore:
    """Designated-Plugin-root adapter over one configured Windows Store."""

    def __init__(
        self,
        root: str | Path,
        *,
        store_identity: str,
        package_store_id: str | None = None,
        settlement_journal: PackageStoreSettlementJournal,
        transfer: PackageVerifiedTreeTransferOwner | None = None,
        commit_probe: Callable[[], None] | None = None,
        receipt_probe: Callable[[], None] | None = None,
    ) -> None:
        self._store = _WindowsRoleStore(
            root,
            role="root",
            store_identity=store_identity,
            settlement_journal=settlement_journal,
            transfer=transfer,
            commit_probe=commit_probe,
            receipt_probe=receipt_probe,
        )
        if package_store_id is not None and not package_store_id:
            raise ValueError("Package store identity is required")
        self._package_store_id = package_store_id

    def open_root_sink(
        self,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> AbstractContextManager[PackageVerifiedTreeSinkPort]:
        return self._store.open_sink(request, manifest)

    def stage_root(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.stage(request, candidate)

    def validate_root_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.validate_receipt(receipt)

    def read_validate_root_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        return self._store.read_validate_receipt(receipt)

    def read_operation_settlements(
        self, operation_id: str
    ) -> tuple[PackageStoreSettlementRecordV1, ...]:
        return self._store.read_operation_settlements(operation_id)

    def read_root_file(
        self,
        settlement: PackageStoreSettlementRecordV1,
        logical_path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        """Read one verified root member through pinned Windows handles."""

        return self._store.read_settlement_file(
            settlement, logical_path, max_bytes=max_bytes
        )

    def read_root_files(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
    ) -> tuple[bytes, ...]:
        """Read one verified member set under a single native owner lock."""

        return self._store.read_settlement_files(settlement, members)

    def delete_settlement(
        self, settlement: PackageStoreSettlementRecordV1
    ) -> PackageStoreGcResultV1:
        """Delete only an exact root settlement through this Store owner."""

        return self._store.delete_settlement(settlement)

    def authorize_adoption(
        self,
        *,
        store_id: str,
        current_root_identity: str,
        target: PackagePluginRootTargetV1,
    ) -> bool:
        """Prove that adoption names this configured Windows root."""

        if (
            self._package_store_id is None
            or store_id != self._package_store_id
            or not isinstance(target, PackagePluginRootTargetV1)
        ):
            return False
        return self._store.authorizes_root_identity(current_root_identity)


class WindowsPackagePluginRootReadOnlyStore:
    """Store-verified root reads for inert Windows Product projections."""

    read_only = True

    def __init__(
        self,
        root: str | Path,
        *,
        store_identity: str,
        settlement_journal: PackageStoreSettlementJournal,
    ) -> None:
        self._store = _WindowsRoleStore(
            root,
            role="root",
            store_identity=store_identity,
            settlement_journal=settlement_journal,
            transfer=None,
            commit_probe=None,
            receipt_probe=None,
            read_only=True,
        )

    def read_root_file(
        self,
        settlement: PackageStoreSettlementRecordV1,
        logical_path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        return self._store.read_settlement_file(
            settlement, logical_path, max_bytes=max_bytes
        )

    def read_root_files(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
    ) -> tuple[bytes, ...]:
        return self._store.read_settlement_files(settlement, members)


class _WindowsRoleStore:
    def __init__(
        self,
        root: str | Path,
        *,
        role: _Role,
        store_identity: str,
        settlement_journal: PackageStoreSettlementJournal,
        transfer: PackageVerifiedTreeTransferOwner | None,
        commit_probe: Callable[[], None] | None,
        receipt_probe: Callable[[], None] | None,
        read_only: bool = False,
    ) -> None:
        if os.name != "nt" or not supports_windows_rooted_io():
            raise PackagePhysicalStagingError(
                "Windows rooted Store operations are unavailable",
                code="package_publication_root_untrusted",
            )
        if not isinstance(root, (str, Path)):
            raise TypeError("Package Store root must be a filesystem path")
        if not isinstance(store_identity, str) or not store_identity:
            raise TypeError("Package Store identity is required")
        if not isinstance(settlement_journal, PackageStoreSettlementJournal):
            raise TypeError("Package Store settlement journal is required")
        if transfer is not None and not isinstance(
            transfer, PackageVerifiedTreeTransferOwner
        ):
            raise TypeError("Verified-tree transfer owner is required")
        if commit_probe is not None and not callable(commit_probe):
            raise TypeError("Package Store commit probe must be callable")
        if receipt_probe is not None and not callable(receipt_probe):
            raise TypeError("Package Store receipt probe must be callable")
        raw_root = Path(root)
        if not raw_root.is_absolute() or ".." in raw_root.parts:
            raise PackagePhysicalStagingError(
                "Package Store root must be an absolute normalized path",
                code="package_publication_root_untrusted",
            )
        if not raw_root.anchor or raw_root == Path(raw_root.anchor):
            raise PackagePhysicalStagingError(
                "Filesystem root cannot be a Package Store root",
                code="package_publication_root_untrusted",
            )
        self._root = raw_root
        self._role = role
        self._store_identity = store_identity
        self._settlement_journal = settlement_journal
        self._transfer = transfer or PackageVerifiedTreeTransferOwner()
        self._commit_probe = commit_probe
        self._receipt_probe = receipt_probe
        self._read_only = read_only
        self._lock = threading.RLock()
        provisioned = _PinnedWindowsRoot.open(self._root, writable=not read_only)
        try:
            self._root_identities = provisioned.identities
        finally:
            provisioned.close()
        self._platform: PackageStorePlatformPort = _WindowsStorePlatform(
            self._root, self._root_identities, self._read_only
        )
        try:
            validate = (
                self._settlement_journal.read_validate_store_root
                if read_only
                else self._settlement_journal.validate_store_root
            )
            validate(
                store_role=self._role,
                store_identity=self._store_identity,
                root_identities=self._root_identities,
            )
            if not read_only:
                with self._settlement_journal.owner_lock():
                    pass
        except PackageStoreSettlementJournalError:
            raise _root_untrusted() from None

    def stage(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        if self._read_only:
            raise _root_untrusted()
        if not isinstance(candidate, VerifiedWheelCandidate):
            raise TypeError("Verified Wheel candidate is required")
        with self.open_sink(request, candidate.transfer_manifest) as sink:
            return self._transfer.transfer(request, candidate, sink)

    def validate_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        if self._read_only:
            raise _root_untrusted()
        return self._validate_receipt(receipt, read_only=False)

    def read_validate_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        """Validate an exact settled tree without repairing owner journals."""

        return self._validate_receipt(receipt, read_only=True)

    def _validate_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
        *,
        read_only: bool,
    ) -> PackageArtifactStagingReceiptV1:
        if not isinstance(receipt, PackageArtifactStagingReceiptV1):
            raise TypeError("Package artifact staging receipt is required")
        self._lock.acquire()
        durable_owner_lock = (
            self._settlement_journal.read_owner_lock()
            if read_only
            else self._settlement_journal.owner_lock()
        )
        try:
            durable_owner_lock.__enter__()
        except Exception:
            self._lock.release()
            raise _root_untrusted() from None
        try:
            with self._platform.pin_root() as root:
                return validate_receipt_at_root(
                    root, receipt,
                    store_role=self._role,
                    store_identity=self._store_identity,
                    settlement_journal=self._settlement_journal,
                    read_only=read_only,
                )
        except PackagePhysicalStagingError:
            raise
        except PackageStoreSettlementJournalError:
            raise _root_untrusted() from None
        except Exception:
            raise _root_untrusted() from None
        finally:
            try:
                durable_owner_lock.__exit__(None, None, None)
            finally:
                self._lock.release()

    def read_operation_settlements(
        self, operation_id: str
    ) -> tuple[PackageStoreSettlementRecordV1, ...]:
        """Account for all Store settlements of one Package operation."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package operation identity is required")
        self._lock.acquire()
        durable_owner_lock = self._settlement_journal.read_owner_lock()
        try:
            durable_owner_lock.__enter__()
        except Exception:
            self._lock.release()
            raise _root_untrusted() from None
        try:
            root = _PinnedWindowsRoot.open(
                self._root,
                expected_identities=self._root_identities,
                writable=not self._read_only,
            )
            try:
                events = self._settlement_journal.read_events()
                records = tuple(
                    event
                    for event in events
                    if isinstance(event, PackageStoreSettlementRecordV1)
                    and event.receipt.operation_id == operation_id
                )
                if any(
                    record.store_role != self._role
                    or record.store_identity != self._store_identity
                    or tuple(item.to_native() for item in record.root_identities)
                    != root.identities
                    for record in records
                ):
                    raise _root_untrusted()
                settled_refs = {
                    record.receipt.stable_ref.ref_id for record in records
                }
                if any(
                    isinstance(event, PackageStoreGcTombstoneV1)
                    and event.stable_ref_id in settled_refs
                    for event in events
                ):
                    raise _collision()
                return records
            finally:
                root.close()
        except PackagePhysicalStagingError:
            raise
        except Exception:
            raise _root_untrusted() from None
        finally:
            try:
                durable_owner_lock.__exit__(None, None, None)
            finally:
                self._lock.release()

    def read_settlement_file(
        self,
        settlement: PackageStoreSettlementRecordV1,
        logical_path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        if (
            not isinstance(settlement, PackageStoreSettlementRecordV1)
            or settlement.store_role != self._role
            or settlement.store_identity != self._store_identity
        ):
            raise _collision()
        if not isinstance(logical_path, str):
            raise TypeError("Package Store logical path is required")
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("Package Store read budget is invalid")
        entry = next(
            (
                item
                for item in settlement.manifest.entries
                if item.logical_path == logical_path
            ),
            None,
        )
        if entry is None or entry.byte_count > max_bytes:
            raise _collision()
        try:
            with self._lock, self._settlement_journal.read_owner_lock():
                root = _PinnedWindowsRoot.open(
                    self._root,
                    expected_identities=self._root_identities,
                    writable=not self._read_only,
                )
                try:
                    events = self._settlement_journal.read_events()
                    if (
                        tuple(
                            identity.to_native()
                            for identity in settlement.root_identities
                        )
                        != root.identities
                        or settlement not in events
                        or any(
                            isinstance(event, PackageStoreGcTombstoneV1)
                            and event.stable_ref_id
                            == settlement.receipt.stable_ref.ref_id
                            for event in events
                        )
                    ):
                        raise _collision()
                    return _read_existing_tree_file(root, settlement, entry)
                finally:
                    root.close()
        except PackagePhysicalStagingError:
            raise
        except Exception:
            raise _root_untrusted() from None

    def read_settlement_files(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
    ) -> tuple[bytes, ...]:
        if (
            not isinstance(settlement, PackageStoreSettlementRecordV1)
            or settlement.store_role != self._role
            or settlement.store_identity != self._store_identity
        ):
            raise _collision()
        if (
            not isinstance(members, tuple)
            or not 1 <= len(members) <= 64
            or any(
                not isinstance(member, tuple)
                or len(member) != 2
                or not isinstance(member[0], str)
                or type(member[1]) is not int
                or member[1] < 0
                for member in members
            )
        ):
            raise ValueError("Package Store read set is invalid")
        by_path = {entry.logical_path: entry for entry in settlement.manifest.entries}
        if len({path for path, _ in members}) != len(members) or any(
            path not in by_path or by_path[path].byte_count > budget
            for path, budget in members
        ):
            raise _collision()
        try:
            with self._lock, self._settlement_journal.read_owner_lock():
                root = _PinnedWindowsRoot.open(
                    self._root,
                    expected_identities=self._root_identities,
                    writable=not self._read_only,
                )
                try:
                    events = self._settlement_journal.read_events()
                    if (
                        tuple(
                            identity.to_native()
                            for identity in settlement.root_identities
                        )
                        != root.identities
                        or settlement not in events
                        or any(
                            isinstance(event, PackageStoreGcTombstoneV1)
                            and event.stable_ref_id
                            == settlement.receipt.stable_ref.ref_id
                            for event in events
                        )
                    ):
                        raise _collision()
                    return tuple(
                        _read_existing_tree_file(root, settlement, by_path[path])
                        for path, _ in members
                    )
                finally:
                    root.close()
        except PackagePhysicalStagingError:
            raise
        except Exception:
            raise _root_untrusted() from None

    def delete_settlement(
        self, settlement: PackageStoreSettlementRecordV1
    ) -> PackageStoreGcResultV1:
        """Delete the exact native tree and permit an identity-checked retry."""

        if self._read_only:
            raise _root_untrusted()
        if (
            not isinstance(settlement, PackageStoreSettlementRecordV1)
            or settlement.store_role != self._role
            or settlement.store_identity != self._store_identity
        ):
            raise _collision()
        self._lock.acquire()
        owner_lock = self._settlement_journal.owner_lock()
        owner_locked = False
        try:
            owner_lock.__enter__()
            owner_locked = True
            root = _PinnedWindowsRoot.open(
                self._root, expected_identities=self._root_identities
            )
            try:
                if (
                    tuple(
                        identity.to_native() for identity in settlement.root_identities
                    )
                    != root.identities
                    or settlement not in self._settlement_journal.records()
                ):
                    raise _collision()
                self._settlement_journal.tombstone(settlement)
                if not _entry_exists(root.descriptor, settlement.final_name):
                    root.validate_visible()
                    return PackageStoreGcResultV1.create(
                        settlement, disposition="already_absent"
                    )
                tree_fd = _open_directory(
                    settlement.final_name,
                    dir_fd=root.descriptor,
                    writable=True,
                )
                try:
                    if (
                        _identity(os.fstat(tree_fd))
                        != settlement.tree_identity.to_native()
                    ):
                        raise _collision()
                    directories = {
                        tuple(
                            item.logical_path.split("/")
                        ): item.native_identity.to_native()
                        for item in settlement.directory_identities
                    }
                    files = {
                        tuple(
                            item.logical_path.split("/")
                        ): item.native_identity.to_native()
                        for item in settlement.file_identities
                    }
                    expected = {
                        item.logical_path: item for item in settlement.manifest.entries
                    }
                    observed, present_directories, present_files = _collect_tree(
                        tree_fd,
                        expected,
                        directory_identities=directories,
                        file_identities=files,
                        allow_partial=True,
                    )
                    if any(
                        observed[path]
                        != (expected[path].byte_count, expected[path].content_digest)
                        for path in observed
                    ):
                        raise _collision()
                    for parts in sorted(present_files, reverse=True):
                        parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                        try:
                            current = windows_stat_at(parent_fd, parts[-1])
                            if (
                                not stat.S_ISREG(current.st_mode)
                                or _is_reparse(current)
                                or _identity(current) != present_files[parts]
                            ):
                                raise _collision()
                            windows_unlink_at(parent_fd, parts[-1])
                        finally:
                            os.close(parent_fd)
                    for parts in sorted(
                        present_directories,
                        key=lambda value: (len(value), value),
                        reverse=True,
                    ):
                        parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                        try:
                            current = windows_stat_at(parent_fd, parts[-1])
                            if (
                                not stat.S_ISDIR(current.st_mode)
                                or _is_reparse(current)
                                or _identity(current) != present_directories[parts]
                            ):
                                raise _collision()
                            windows_rmdir_at(parent_fd, parts[-1])
                        finally:
                            os.close(parent_fd)
                finally:
                    os.close(tree_fd)
                root.validate_visible()
                windows_rmdir_at(root.descriptor, settlement.final_name)
                root.validate_visible()
                if _entry_exists(root.descriptor, settlement.final_name):
                    raise _root_untrusted()
                return PackageStoreGcResultV1.create(settlement, disposition="deleted")
            finally:
                root.close()
        except PackagePhysicalStagingError:
            raise
        except Exception:
            raise _root_untrusted() from None
        finally:
            try:
                if owner_locked:
                    owner_lock.__exit__(None, None, None)
            finally:
                self._lock.release()

    def authorizes_root_identity(self, expected_identity: str) -> bool:
        if self._role != "root" or not isinstance(expected_identity, str):
            return False
        self._lock.acquire()
        try:
            root = _PinnedWindowsRoot.open(
                self._root, expected_identities=self._root_identities
            )
            try:
                metadata = os.fstat(root.descriptor)
                observed = sha256(
                    canonical_json_bytes(
                        {
                            "device": metadata.st_dev,
                            "fileType": "directory",
                            "inode": metadata.st_ino,
                            "identityVersion": 1,
                        }
                    )
                ).hexdigest()
                return observed == expected_identity
            finally:
                root.close()
        except Exception:
            return False
        finally:
            self._lock.release()

    def open_sink(
        self,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> _WindowsVerifiedTreeSink:
        if self._read_only:
            raise _root_untrusted()
        _validate_role_request(self._role, request, manifest)
        self._lock.acquire()
        durable_owner_lock = self._settlement_journal.owner_lock()
        try:
            durable_owner_lock.__enter__()
        except Exception:
            self._lock.release()
            raise _root_untrusted() from None

        def release_owner_lock() -> None:
            try:
                durable_owner_lock.__exit__(None, None, None)
            finally:
                self._lock.release()

        try:
            root = _PinnedWindowsRoot.open(
                self._root,
                expected_identities=self._root_identities,
            )
            try:
                return _WindowsVerifiedTreeSink(
                    root=root,
                    role=self._role,
                    store_identity=self._store_identity,
                    request=request,
                    manifest=manifest,
                    commit_probe=self._commit_probe,
                    receipt_probe=self._receipt_probe,
                    settlement_journal=self._settlement_journal,
                    release_owner_lock=release_owner_lock,
                )
            except Exception:
                root.close()
                raise
        except Exception:
            release_owner_lock()
            raise


@dataclass(frozen=True)
class _WindowsStorePlatform:
    root: Path
    expected_identities: tuple[_Identity, ...]
    construction_read_only: bool

    @contextmanager
    def pin_root(self) -> Iterator[PackageStorePinnedRootPort]:
        root = _PinnedWindowsRoot.open(
            self.root,
            expected_identities=self.expected_identities,
            writable=not self.construction_read_only,
        )
        try:
            yield root
        finally:
            root.close()


class _PinnedWindowsRoot:
    def __init__(
        self,
        *,
        path: Path,
        anchor: Path,
        components: tuple[str, ...],
        descriptors: list[int],
        identities: tuple[_Identity, ...],
        writable: bool,
    ) -> None:
        self.path = path
        self.anchor = anchor
        self.components = components
        self._descriptors = descriptors
        self.identities = identities
        self._writable = writable
        self._closed = False

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        expected_identities: tuple[_Identity, ...] | None = None,
        writable: bool = True,
    ) -> _PinnedWindowsRoot:
        anchor = Path(path.anchor)
        components = tuple(path.parts[1:])
        descriptors: list[int] = []
        try:
            current = _open_directory(anchor, writable=False)
            descriptors.append(current)
            for index, component in enumerate(components):
                current = _open_directory(
                    component,
                    dir_fd=current,
                    writable=writable and index == len(components) - 1,
                )
                descriptors.append(current)
            identities = tuple(_identity(os.fstat(fd)) for fd in descriptors)
            if expected_identities is not None and identities != expected_identities:
                raise OSError("Configured Package Store root identity changed")
            _require_direct_directory(os.fstat(descriptors[-1]))
            pinned = cls(
                path=path,
                anchor=anchor,
                components=components,
                descriptors=descriptors,
                identities=identities,
                writable=writable,
            )
            pinned.validate_visible()
            return pinned
        except Exception:
            for descriptor in reversed(descriptors):
                with suppress(OSError):
                    os.close(descriptor)
            raise _root_untrusted() from None

    @property
    def descriptor(self) -> int:
        if self._closed:
            raise RuntimeError("Package Store root handle is closed")
        return self._descriptors[-1]

    def validate_visible(self) -> None:
        if self._closed:
            raise OSError("Package Store root handle is closed")
        for descriptor, expected in zip(
            self._descriptors, self.identities, strict=True
        ):
            metadata = os.fstat(descriptor)
            _require_direct_directory(metadata)
            if _identity(metadata) != expected:
                raise OSError("Pinned Package Store ancestor identity changed")
        visible = _open_directory(self.anchor, writable=False)
        try:
            if _identity(os.fstat(visible)) != self.identities[0]:
                raise OSError("Package Store volume root identity changed")
            for index, (component, expected) in enumerate(
                zip(self.components, self.identities[1:], strict=True)
            ):
                child = _open_directory(
                    component,
                    dir_fd=visible,
                    writable=self._writable and index == len(self.components) - 1,
                )
                os.close(visible)
                visible = child
                if _identity(os.fstat(visible)) != expected:
                    raise OSError("Package Store ancestor path identity changed")
        finally:
            os.close(visible)

    def validate_tree(
        self, final_name: str, manifest: PackageVerifiedTreeManifestV1,
    ) -> ObservedTree:
        return _validate_existing_tree(self, final_name, manifest)

    def close(self) -> None:
        if self._closed:
            return
        for descriptor in reversed(self._descriptors):
            with suppress(OSError):
                os.close(descriptor)
        self._descriptors.clear()
        self._closed = True


class _WindowsVerifiedTreeSink:
    def __init__(
        self,
        *,
        root: _PinnedWindowsRoot,
        role: _Role,
        store_identity: str,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
        commit_probe: Callable[[], None] | None,
        receipt_probe: Callable[[], None] | None,
        settlement_journal: PackageStoreSettlementJournal,
        release_owner_lock: Callable[[], None],
    ) -> None:
        self._root = root
        self._role = role
        self._request = request
        self._manifest = manifest
        self._commit_probe = commit_probe
        self._receipt_probe = receipt_probe
        self._settlement_journal = settlement_journal
        self._release_owner_lock = release_owner_lock
        self._store_identity = store_identity
        self._stable_ref = _stable_ref(
            role,
            store_identity=store_identity,
            request=request,
            manifest=manifest,
        )
        prefix = "artifact" if role == "dependency" else "revision"
        self._final_name = f"{prefix}-{self._stable_ref.ref_id}"
        self._staging_name = f"staging-{request.staging_request_id}"
        self._receipt = PackageArtifactStagingReceiptV1.create(
            self._request,
            stable_ref=self._stable_ref,
        )
        self._staging_fd: int | None = None
        self._staging_identity: _Identity | None = None
        self._directory_identities: dict[tuple[str, ...], _Identity] = {}
        self._file_identities: dict[tuple[str, ...], _Identity] = {}
        self._next_entry = 0
        self._active_file: _WindowsFileSink | _ReuseFileSink | None = None
        self._reuse = False
        self._reuse_alias = False
        self._authorized = False
        self._renamed = False
        self._finished = False
        self._closed = False
        self._prepare()

    def __enter__(self) -> _WindowsVerifiedTreeSink:
        if self._closed:
            raise RuntimeError("Package verified-tree sink is closed")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None or not self._finished:
            self.abort()

    def _prepare(self) -> None:
        try:
            self._root.validate_visible()
            if self._settlement_journal.is_tombstoned(self._stable_ref.ref_id):
                raise _collision()
            if _entry_exists(self._root.descriptor, self._staging_name):
                raise _root_untrusted()
            if _entry_exists(self._root.descriptor, self._final_name):
                tree_identity, directory_identities, file_identities = (
                    _validate_existing_tree(
                        self._root,
                        self._final_name,
                        self._manifest,
                    )
                )
                exact = self._settlement_journal.authorizes(
                    store_role=self._role,
                    store_identity=self._store_identity,
                    root_identities=self._root.identities,
                    tree_identity=tree_identity,
                    directory_identities=directory_identities,
                    file_identities=file_identities,
                    final_name=self._final_name,
                    staging_name=self._staging_name,
                    manifest=self._manifest,
                    receipt=self._receipt,
                )
                alias = (
                    self._role == "dependency"
                    and not exact
                    and self._settlement_journal.authorizes_dependency_reuse(
                        store_identity=self._store_identity,
                        root_identities=self._root.identities,
                        tree_identity=tree_identity,
                        directory_identities=directory_identities,
                        file_identities=file_identities,
                        final_name=self._final_name,
                        staging_name=self._staging_name,
                        manifest=self._manifest,
                        receipt=self._receipt,
                    )
                )
                if not exact and not alias:
                    raise PackagePhysicalStagingError(
                        "Package Store final identity lacks durable owner evidence",
                        code="package_publication_collision",
                    )
                self._reuse = True
                self._reuse_alias = alias
                return
            self._staging_fd = _open_directory(
                self._staging_name,
                dir_fd=self._root.descriptor,
                create_new=True,
                writable=True,
            )
            self._staging_identity = _identity(os.fstat(self._staging_fd))
        except PackagePhysicalStagingError:
            raise
        except PackageStoreSettlementJournalError:
            raise _root_untrusted() from None
        except Exception:
            raise _root_untrusted() from None

    def open_file(
        self,
        entry: PackageVerifiedTreeEntryV1,
    ) -> AbstractContextManager[_WindowsFileSink | _ReuseFileSink]:
        self._require_open()
        if self._active_file is not None:
            raise RuntimeError("Previous Package Store file sink is still open")
        if (
            self._next_entry >= len(self._manifest.entries)
            or entry != self._manifest.entries[self._next_entry]
        ):
            raise PackagePhysicalStagingError(
                "Package Store file order changed from verified manifest",
                code="package_artifact_identity_changed",
            )
        if self._reuse:
            file_sink: _WindowsFileSink | _ReuseFileSink = _ReuseFileSink(
                entry=entry,
                on_finished=self._file_finished,
            )
        else:
            file_sink = self._create_file_sink(entry)
        self._active_file = file_sink
        return file_sink

    def _create_file_sink(self, entry: PackageVerifiedTreeEntryV1) -> _WindowsFileSink:
        if self._staging_fd is None:
            raise RuntimeError("Package Store staging root is unavailable")
        parts = tuple(entry.logical_path.split("/"))
        self._ensure_directories(parts[:-1])
        parent_fd = self._open_staging_directory(parts[:-1])
        try:
            descriptor = open_windows_regular_file_at(
                parent_fd,
                parts[-1],
                create_new=True,
                write=True,
            )
        except Exception:
            os.close(parent_fd)
            raise _root_untrusted() from None
        os.close(parent_fd)
        identity = _identity(os.fstat(descriptor))
        self._file_identities[parts] = identity
        return _WindowsFileSink(
            entry=entry,
            writer=_WindowsFileWriter(descriptor=descriptor, identity=identity),
            on_finished=self._file_finished,
        )

    def _ensure_directories(self, parts: tuple[str, ...]) -> None:
        for depth in range(1, len(parts) + 1):
            current = parts[:depth]
            if current in self._directory_identities:
                continue
            parent_fd = self._open_staging_directory(current[:-1])
            try:
                child_fd = _open_directory(
                    current[-1],
                    dir_fd=parent_fd,
                    create_new=True,
                    writable=True,
                )
            except Exception:
                os.close(parent_fd)
                raise _root_untrusted() from None
            os.close(parent_fd)
            try:
                self._directory_identities[current] = _identity(os.fstat(child_fd))
            finally:
                os.close(child_fd)

    def _open_staging_directory(self, parts: tuple[str, ...]) -> int:
        if self._staging_fd is None or self._staging_identity is None:
            raise RuntimeError("Package Store staging root is unavailable")
        if _identity(os.fstat(self._staging_fd)) != self._staging_identity:
            raise _root_untrusted()
        current_fd = os.dup(self._staging_fd)
        try:
            for depth, part in enumerate(parts, start=1):
                child_fd = _open_directory(
                    part,
                    dir_fd=current_fd,
                    writable=True,
                )
                expected = self._directory_identities.get(parts[:depth])
                if expected is None or _identity(os.fstat(child_fd)) != expected:
                    os.close(child_fd)
                    raise OSError("Package Store staging ancestor changed")
                os.close(current_fd)
                current_fd = child_fd
            return current_fd
        except PackagePhysicalStagingError:
            os.close(current_fd)
            raise
        except Exception:
            os.close(current_fd)
            raise _root_untrusted() from None

    def _file_finished(self, sink: _WindowsFileSink | _ReuseFileSink) -> None:
        if sink is not self._active_file:
            raise RuntimeError("Package Store file sink ownership changed")
        self._active_file = None
        self._next_entry += 1

    def finish(self) -> PackageArtifactStagingReceiptV1:
        self._require_open()
        return finish_verified_tree(
            self,
            store_role=self._role,
            store_identity=self._store_identity,
            root_identities=self._root.identities,
            final_name=self._final_name,
            staging_name=self._staging_name,
            manifest=self._manifest,
            receipt=self._receipt,
            settlement_journal=self._settlement_journal,
            reuse=self._reuse,
            reuse_alias=self._reuse_alias,
            completed_entries=self._next_entry,
            has_active_file=self._active_file is not None,
        )

    def observe_reused_tree(self) -> ObservedTree:
        self._root.validate_visible()
        return _validate_existing_tree(self._root, self._final_name, self._manifest)

    def prepare_new_tree(self) -> ObservedTree:
        if self._staging_fd is None or self._staging_identity is None:
            raise RuntimeError("Package Store staging root is unavailable")
        _validate_owned_tree(
            self._staging_fd,
            self._staging_identity,
            self._manifest,
            directory_identities=self._directory_identities,
            file_identities=self._file_identities,
        )
        visible = _open_directory(
            self._staging_name,
            dir_fd=self._root.descriptor,
            writable=True,
        )
        try:
            if _identity(os.fstat(visible)) != self._staging_identity:
                raise OSError("Package Store staging path identity changed")
        finally:
            os.close(visible)
        os.close(self._staging_fd)
        self._staging_fd = None
        if self._commit_probe is not None:
            self._commit_probe()
        try:
            self._root.validate_visible()
            visible = _open_directory(
                self._staging_name,
                dir_fd=self._root.descriptor,
                writable=True,
            )
            try:
                _validate_owned_tree(
                    visible,
                    self._staging_identity,
                    self._manifest,
                    directory_identities=self._directory_identities,
                    file_identities=self._file_identities,
                )
            finally:
                os.close(visible)
        except PackagePhysicalStagingError:
            raise
        except Exception:
            raise _root_untrusted() from None
        if _entry_exists(self._root.descriptor, self._final_name):
            raise PackagePhysicalStagingError(
                "Package Store final identity already exists",
                code="package_publication_collision",
            )
        return (
            self._staging_identity, self._directory_identities, self._file_identities,
        )

    def publish_authorized_tree(self) -> None:
        self._authorized = True
        try:
            windows_rename_at(
                self._root.descriptor,
                self._staging_name,
                self._final_name,
            )
            self._renamed = True
            self._root.validate_visible()
            _validate_existing_tree(
                self._root,
                self._final_name,
                self._manifest,
                expected_tree_identity=self._staging_identity,
                directory_identities=self._directory_identities,
                file_identities=self._file_identities,
            )
            if self._receipt_probe is not None:
                self._receipt_probe()
        except PackagePhysicalStagingError:
            raise
        except Exception:
            raise _root_untrusted() from None


    def complete_and_close(self) -> None:
        self._finished = True
        self._close_handles()

    def abort(self) -> None:
        if self._closed:
            return
        if self._active_file is not None:
            self._active_file.abort()
            self._active_file = None
        with suppress(Exception):
            if not self._reuse and not (self._renamed and self._authorized):
                name = self._final_name if self._renamed else self._staging_name
                expected = self._staging_identity
                if expected is not None:
                    self._remove_owned_tree(name, expected)
        self._close_handles()

    def _remove_owned_tree(self, name: str, expected: _Identity) -> None:
        if self._staging_fd is not None:
            os.close(self._staging_fd)
            self._staging_fd = None
        tree_fd = _open_directory(
            name,
            dir_fd=self._root.descriptor,
            writable=True,
        )
        try:
            if _identity(os.fstat(tree_fd)) != expected:
                raise OSError("Package Store owned tree identity changed")
            for parts in sorted(self._file_identities, reverse=True):
                parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                try:
                    metadata = windows_stat_at(parent_fd, parts[-1])
                    if (
                        _identity(metadata) != self._file_identities[parts]
                        or not stat.S_ISREG(metadata.st_mode)
                        or _is_reparse(metadata)
                    ):
                        raise OSError("Package Store owned file identity changed")
                    windows_unlink_at(parent_fd, parts[-1])
                finally:
                    os.close(parent_fd)
            for parts in sorted(
                self._directory_identities,
                key=lambda value: (len(value), value),
                reverse=True,
            ):
                parent_fd = _open_relative_directory(tree_fd, parts[:-1])
                try:
                    metadata = windows_stat_at(parent_fd, parts[-1])
                    if (
                        _identity(metadata) != self._directory_identities[parts]
                        or not stat.S_ISDIR(metadata.st_mode)
                        or _is_reparse(metadata)
                    ):
                        raise OSError("Package Store owned directory identity changed")
                    windows_rmdir_at(parent_fd, parts[-1])
                finally:
                    os.close(parent_fd)
        finally:
            os.close(tree_fd)
        windows_rmdir_at(self._root.descriptor, name)

    def _close_handles(self) -> None:
        if self._staging_fd is not None:
            with suppress(OSError):
                os.close(self._staging_fd)
            self._staging_fd = None
        self._root.close()
        self._release_owner_lock()
        self._closed = True

    def _require_open(self) -> None:
        if self._closed or self._finished:
            raise RuntimeError("Package verified-tree sink is closed")


class _WindowsFileWriter:
    def __init__(self, *, descriptor: int, identity: _Identity) -> None:
        self._descriptor: int | None = descriptor
        self._identity = identity

    def require_open(self) -> None:
        self._require_descriptor()

    def write(self, view: memoryview) -> int:
        return os.write(self._require_descriptor(), view)

    def identity_matches(self) -> bool:
        metadata = os.fstat(self._require_descriptor())
        return (
            _identity(metadata) == self._identity
            and metadata.st_nlink == 1
            and not _is_reparse(metadata)
        )

    def flush(self) -> None:
        windows_flush_file(self._require_descriptor())

    def close(self) -> None:
        os.close(self._require_descriptor())
        self._descriptor = None

    def abort(self) -> None:
        if self._descriptor is not None:
            with suppress(OSError):
                os.close(self._descriptor)
            self._descriptor = None

    def _require_descriptor(self) -> int:
        if self._descriptor is None:
            raise RuntimeError("Package Store file sink is closed")
        return self._descriptor


def _validate_role_request(
    role: _Role,
    request: PackageArtifactStagingRequestV1,
    manifest: PackageVerifiedTreeManifestV1,
) -> None:
    if not isinstance(request, PackageArtifactStagingRequestV1):
        raise TypeError("Package artifact staging request is required")
    if not isinstance(manifest, PackageVerifiedTreeManifestV1):
        raise TypeError("Package verified-tree manifest is required")
    node = request.plan_node
    if (
        node.role != role
        or (role == "dependency" and request.root_target is not None)
        or (role == "root" and request.root_target is None)
        or request.operation_id != manifest.operation_id
        or request.attempt_epoch != manifest.attempt_epoch
        or request.node_id != manifest.node_id
        or node.distribution != manifest.distribution
        or node.version != manifest.version
        or node.wheel_evidence_fingerprint != manifest.wheel_evidence_fingerprint
        or node.artifact_digest != manifest.artifact_digest
        or node.extraction_tree_digest != manifest.extraction_tree_digest
    ):
        raise PackagePhysicalStagingError(
            "Package Store request changed verified role or artifact identity",
            code="package_artifact_identity_changed",
        )


def _stable_ref(
    role: _Role,
    *,
    store_identity: str,
    request: PackageArtifactStagingRequestV1,
    manifest: PackageVerifiedTreeManifestV1,
) -> VerifiedArtifactRefV1 | PluginRevisionRefV1:
    values = {
        "store_identity": store_identity,
        "store_revision": (
            dependency_content_store_revision(manifest)
            if role == "dependency"
            else f"tree:{manifest.manifest_id}"
        ),
        "distribution": manifest.distribution,
        "version": manifest.version,
        "artifact_digest": manifest.artifact_digest,
        "extraction_tree_digest": manifest.extraction_tree_digest,
    }
    if role == "dependency":
        return VerifiedArtifactRefV1.create(**values)
    target = request.root_target
    assert target is not None
    return PluginRevisionRefV1.create(
        **values,
        installation_id=target.installation_id,
        plugin_id=target.plugin_id,
    )


def _validate_existing_tree(
    root: _PinnedWindowsRoot,
    final_name: str,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    expected_tree_identity: _Identity | None = None,
    directory_identities: dict[tuple[str, ...], _Identity] | None = None,
    file_identities: dict[tuple[str, ...], _Identity] | None = None,
) -> tuple[
    _Identity,
    dict[tuple[str, ...], _Identity],
    dict[tuple[str, ...], _Identity],
]:
    try:
        root.validate_visible()
    except Exception:
        raise _root_untrusted() from None
    try:
        tree_fd = _open_directory(
            final_name,
            dir_fd=root.descriptor,
            writable=False,
        )
        try:
            tree_identity = _identity(os.fstat(tree_fd))
            if (
                expected_tree_identity is not None
                and tree_identity != expected_tree_identity
            ):
                raise OSError("Published Package tree identity changed")
            observed_directories, observed_files = _validate_tree_contents(
                tree_fd,
                manifest,
                directory_identities=directory_identities,
                file_identities=file_identities,
            )
        finally:
            os.close(tree_fd)
    except Exception:
        raise PackagePhysicalStagingError(
            "Existing Package Store object conflicts with verified identity",
            code="package_publication_collision",
        ) from None
    try:
        root.validate_visible()
    except Exception:
        raise _root_untrusted() from None
    return tree_identity, observed_directories, observed_files


def _read_existing_tree_file(
    root: _PinnedWindowsRoot,
    settlement: PackageStoreSettlementRecordV1,
    entry: PackageVerifiedTreeEntryV1,
) -> bytes:
    directories = {
        tuple(item.logical_path.split("/")): item.native_identity.to_native()
        for item in settlement.directory_identities
    }
    files = {
        tuple(item.logical_path.split("/")): item.native_identity.to_native()
        for item in settlement.file_identities
    }
    tree_identity = settlement.tree_identity.to_native()
    _validate_existing_tree(
        root,
        settlement.final_name,
        settlement.manifest,
        expected_tree_identity=tree_identity,
        directory_identities=directories,
        file_identities=files,
    )
    try:
        tree_fd = _open_directory(
            settlement.final_name, dir_fd=root.descriptor, writable=False
        )
        try:
            if _identity(os.fstat(tree_fd)) != tree_identity:
                raise OSError("Published Package tree identity changed")
            parts = tuple(entry.logical_path.split("/"))
            parent_fd = os.dup(tree_fd)
            try:
                for depth, part in enumerate(parts[:-1], start=1):
                    child_fd = _open_directory(
                        part, dir_fd=parent_fd, writable=False
                    )
                    os.close(parent_fd)
                    parent_fd = child_fd
                    if _identity(os.fstat(parent_fd)) != directories.get(parts[:depth]):
                        raise OSError("Published Package directory identity changed")
                expected_parent = (
                    directories.get(parts[:-1]) if len(parts) > 1 else tree_identity
                )
                if _identity(os.fstat(parent_fd)) != expected_parent:
                    raise OSError("Published Package directory identity changed")
                file_fd = open_windows_regular_file_at(
                    parent_fd, parts[-1], create_new=False, write=False
                )
                try:
                    metadata = os.fstat(file_fd)
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or metadata.st_nlink != 1
                        or _is_reparse(metadata)
                        or _identity(metadata) != files.get(parts)
                        or metadata.st_size != entry.byte_count
                    ):
                        raise OSError("Published Package file identity changed")
                    data = bytearray()
                    while chunk := os.read(
                        file_fd, min(64 * 1024, entry.byte_count + 1 - len(data))
                    ):
                        data.extend(chunk)
                        if len(data) > entry.byte_count:
                            raise OSError("Published Package file exceeds verified size")
                    if (
                        _identity(os.fstat(file_fd)) != files[parts]
                        or len(data) != entry.byte_count
                        or sha256(data).hexdigest() != entry.content_digest
                    ):
                        raise OSError("Published Package file content changed")
                finally:
                    os.close(file_fd)
            finally:
                os.close(parent_fd)
        finally:
            os.close(tree_fd)
        root.validate_visible()
        if (
            _identity(windows_stat_at(root.descriptor, settlement.final_name))
            != tree_identity
        ):
            raise OSError("Published Package tree visibility changed")
        return bytes(data)
    except Exception:
        raise _collision() from None


def _validate_owned_tree(
    tree_fd: int,
    expected_tree_identity: _Identity,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    directory_identities: dict[tuple[str, ...], _Identity],
    file_identities: dict[tuple[str, ...], _Identity],
) -> None:
    if _identity(os.fstat(tree_fd)) != expected_tree_identity:
        raise _root_untrusted()
    try:
        _validate_tree_contents(
            tree_fd,
            manifest,
            directory_identities=directory_identities,
            file_identities=file_identities,
        )
    except PackagePhysicalStagingError:
        raise
    except Exception:
        raise _root_untrusted() from None


def _validate_tree_contents(
    root_fd: int,
    manifest: PackageVerifiedTreeManifestV1,
    *,
    directory_identities: dict[tuple[str, ...], _Identity] | None,
    file_identities: dict[tuple[str, ...], _Identity] | None,
) -> tuple[
    dict[tuple[str, ...], _Identity],
    dict[tuple[str, ...], _Identity],
]:
    return _validate_observed_tree_contents(
        _WindowsTreeDirectoryReader(root_fd), manifest,
        directory_identities=directory_identities,
        file_identities=file_identities,
    )


def _collect_tree(
    root_fd: int,
    expected: dict[str, PackageVerifiedTreeEntryV1],
    *,
    directory_identities: dict[tuple[str, ...], _Identity] | None,
    file_identities: dict[tuple[str, ...], _Identity] | None,
    allow_partial: bool = False,
) -> tuple[
    dict[str, tuple[int, str]],
    dict[tuple[str, ...], _Identity],
    dict[tuple[str, ...], _Identity],
]:
    return _collect_observed_tree(
        _WindowsTreeDirectoryReader(root_fd), expected,
        directory_identities=directory_identities,
        file_identities=file_identities,
        allow_partial=allow_partial,
    )


@dataclass(frozen=True)
class _WindowsTreeFileReader:
    descriptor: int

    def read(self, max_bytes: int) -> bytes:
        return os.read(self.descriptor, max_bytes)

    def identity_and_links(self) -> tuple[_Identity, int]:
        metadata = os.fstat(self.descriptor)
        if _is_reparse(metadata):
            raise OSError("Published Package file identity changed")
        return _identity(metadata), metadata.st_nlink


@dataclass(frozen=True)
class _WindowsTreeDirectoryReader:
    descriptor: int

    def identity(self) -> _Identity:
        return _identity(os.fstat(self.descriptor))

    @contextmanager
    def entries(self) -> Iterator[Iterator[TreeEntryObservation]]:
        names = windows_listdir_at(self.descriptor)

        def observe() -> Iterator[TreeEntryObservation]:
            for name in names:
                metadata = windows_stat_at(self.descriptor, name)
                if _is_reparse(metadata):
                    raise OSError("Published Package tree contains a reparse point")
                yield TreeEntryObservation(
                    name,
                    "directory" if stat.S_ISDIR(metadata.st_mode) else (
                        "file" if stat.S_ISREG(metadata.st_mode) else "other"
                    ),
                    _identity(metadata), metadata.st_nlink,
                )
        yield observe()

    @contextmanager
    def open_directory(self, name: str) -> Iterator[TreeDirectoryReadPort]:
        descriptor = _open_directory(name, dir_fd=self.descriptor, writable=False)
        try:
            yield _WindowsTreeDirectoryReader(descriptor)
        finally:
            os.close(descriptor)

    @contextmanager
    def file_reader(self, name: str) -> Iterator[TreeFileReadPort]:
        descriptor = open_windows_regular_file_at(self.descriptor, name, create_new=False, write=False)
        try:
            yield _WindowsTreeFileReader(descriptor)
        finally:
            os.close(descriptor)


def _open_directory(
    path: str | Path,
    *,
    dir_fd: int | None = None,
    create_new: bool = False,
    writable: bool,
) -> int:
    return open_windows_directory(
        path,
        dir_fd=dir_fd,
        create_new=create_new,
        share_delete=True,
        writable=writable,
    )


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            child_fd = _open_directory(
                part,
                dir_fd=current_fd,
                writable=True,
            )
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _entry_exists(directory_fd: int, name: str) -> bool:
    try:
        windows_stat_at(directory_fd, name)
    except FileNotFoundError:
        return False
    return True


def _require_direct_directory(metadata: os.stat_result) -> None:
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        raise OSError("Windows Package Store entry is not a direct directory")


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_reparse_tag", 0)
        or getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _identity(metadata: os.stat_result) -> _Identity:
    return int(metadata.st_dev), int(metadata.st_ino)


def _root_untrusted() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store root or owned staging identity changed",
        code="package_publication_root_untrusted",
    )


def _collision() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store settlement evidence does not authorize this tree",
        code="package_publication_collision",
    )


__all__ = [
    "PackagePhysicalStagingError",
    "WindowsPackageDependencyMaterializationStore",
    "WindowsPackagePluginRootMaterializationStore",
    "WindowsPackagePluginRootReadOnlyStore",
]
