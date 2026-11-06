"""Shared Store receipt and completion rules over narrow native operations."""

from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Generic, Protocol, TypeVar

from .commit_records import PluginRevisionRefV1, VerifiedArtifactRefV1
from .records import canonical_json_bytes
from .staging import (
    PackageArtifactStagingReceiptV1,
    PackageArtifactStagingRequestV1,
    PackagePluginRootTargetV1,
)
from .store_gc import PackageStoreGcResultV1
from .store_settlements import (
    NativeIdentity,
    PackageStoreGcTombstoneV1,
    PackageStoreRole,
    PackageStoreSettlementJournal,
    PackageStoreSettlementJournalError,
    PackageStoreSettlementRecordV1,
    dependency_content_store_revision,
)
from .tree_transfer import (
    PackagePhysicalStagingError,
    PackageVerifiedTreeEntryV1,
    PackageVerifiedTreeManifestV1,
    PackageVerifiedTreeSinkPort,
    PackageVerifiedTreeTransferOwner,
)
from .wheel import VerifiedWheelCandidate

IdentityMap = dict[tuple[str, ...], NativeIdentity]
ObservedTree = tuple[NativeIdentity, IdentityMap, IdentityMap]


class PackageStorePinnedRootPort(Protocol):
    @property
    def identities(self) -> tuple[NativeIdentity, ...]: ...

    @property
    def descriptor(self) -> int: ...

    def close(self) -> None: ...

    def validate_visible(self) -> None: ...

    def read_file(
        self,
        settlement: PackageStoreSettlementRecordV1,
        entry: PackageVerifiedTreeEntryV1,
    ) -> bytes: ...

    def validate_tree(
        self,
        final_name: str,
        manifest: PackageVerifiedTreeManifestV1,
    ) -> ObservedTree: ...


def validate_receipt_at_root(
    root: PackageStorePinnedRootPort,
    receipt: PackageArtifactStagingReceiptV1,
    *,
    store_role: PackageStoreRole,
    store_identity: str,
    settlement_journal: PackageStoreSettlementJournal,
    read_only: bool,
) -> PackageArtifactStagingReceiptV1:
    """Use the original journal authority; native observations grant no rights."""
    stable_ref = receipt.stable_ref
    if (
        stable_ref.store_identity != store_identity
        or (
            store_role == "dependency"
            and not isinstance(stable_ref, VerifiedArtifactRefV1)
        )
        or (store_role == "root" and not isinstance(stable_ref, PluginRevisionRefV1))
    ):
        raise _collision()
    settlements_read = (
        settlement_journal.read_settlements_for_receipt
        if read_only
        else settlement_journal.settlements_for_receipt
    )
    settlements = settlements_read(
        store_role=store_role,
        store_identity=store_identity,
        root_identities=root.identities,
        receipt=receipt,
    )
    if not settlements:
        raise _collision()
    authority = settlements[0]
    tree_identity, directory_identities, file_identities = root.validate_tree(
        authority.final_name,
        authority.manifest,
    )
    authorizes_read = (
        settlement_journal.read_authorizes
        if read_only
        else settlement_journal.authorizes
    )
    if not authorizes_read(
        store_role=store_role,
        store_identity=store_identity,
        root_identities=root.identities,
        tree_identity=tree_identity,
        directory_identities=directory_identities,
        file_identities=file_identities,
        final_name=authority.final_name,
        staging_name=authority.staging_name,
        manifest=authority.manifest,
        receipt=receipt,
    ):
        raise _collision()
    return receipt


def _collision() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store settlement evidence does not authorize this tree",
        code="package_publication_collision",
    )


class PackageVerifiedTreeCompletionPort(Protocol):
    def observe_reused_tree(self) -> ObservedTree: ...

    def prepare_new_tree(self) -> ObservedTree: ...

    def publish_authorized_tree(self) -> None: ...

    def complete_and_close(self) -> None: ...


def finish_verified_tree(
    platform: PackageVerifiedTreeCompletionPort,
    *,
    store_role: PackageStoreRole,
    store_identity: str,
    root_identities: tuple[NativeIdentity, ...],
    final_name: str,
    staging_name: str,
    manifest: PackageVerifiedTreeManifestV1,
    receipt: PackageArtifactStagingReceiptV1,
    settlement_journal: PackageStoreSettlementJournal,
    reuse: bool,
    reuse_alias: bool,
    completed_entries: int,
    has_active_file: bool,
) -> PackageArtifactStagingReceiptV1:
    """Authorize before native publication; the original sink owns all flags."""
    if has_active_file or completed_entries != len(manifest.entries):
        raise PackagePhysicalStagingError(
            "Package Store received an incomplete verified tree",
            code="package_artifact_identity_changed",
        )
    try:
        if reuse:
            tree_identity, directory_identities, file_identities = (
                platform.observe_reused_tree()
            )
            exact = settlement_journal.authorizes(
                store_role=store_role,
                store_identity=store_identity,
                root_identities=root_identities,
                tree_identity=tree_identity,
                directory_identities=directory_identities,
                file_identities=file_identities,
                final_name=final_name,
                staging_name=staging_name,
                manifest=manifest,
                receipt=receipt,
            )
            if reuse_alias and not exact:
                if not settlement_journal.authorizes_dependency_reuse(
                    store_identity=store_identity,
                    root_identities=root_identities,
                    tree_identity=tree_identity,
                    directory_identities=directory_identities,
                    file_identities=file_identities,
                    final_name=final_name,
                    staging_name=staging_name,
                    manifest=manifest,
                    receipt=receipt,
                ):
                    raise _collision()
                settlement_journal.authorize(
                    store_role=store_role,
                    store_identity=store_identity,
                    root_identities=root_identities,
                    tree_identity=tree_identity,
                    directory_identities=directory_identities,
                    file_identities=file_identities,
                    final_name=final_name,
                    staging_name=staging_name,
                    manifest=manifest,
                    receipt=receipt,
                )
            elif not exact:
                raise PackagePhysicalStagingError(
                    "Package Store final identity lacks durable owner evidence",
                    code="package_publication_collision",
                )
        else:
            tree_identity, directory_identities, file_identities = (
                platform.prepare_new_tree()
            )
            settlement_journal.authorize(
                store_role=store_role,
                store_identity=store_identity,
                root_identities=root_identities,
                tree_identity=tree_identity,
                directory_identities=directory_identities,
                file_identities=file_identities,
                final_name=final_name,
                staging_name=staging_name,
                manifest=manifest,
                receipt=receipt,
            )
            platform.publish_authorized_tree()
    except PackagePhysicalStagingError:
        raise
    except PackageStoreSettlementJournalError:
        raise _root_untrusted() from None
    except Exception:
        raise _root_untrusted() from None
    platform.complete_and_close()
    return receipt


def _root_untrusted() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store root or owned staging identity changed",
        code="package_publication_root_untrusted",
    )


RootT = TypeVar("RootT", bound=PackageStorePinnedRootPort)
SinkT = TypeVar("SinkT", bound=AbstractContextManager[PackageVerifiedTreeSinkPort])


class PackageRoleStore(ABC, Generic[RootT, SinkT]):
    """Store transaction rules shared by native role-specific implementations.

    Native roots retain handle ownership and all filesystem operations. The
    settlement journal remains the sole authority for receipts and reuse.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        role: PackageStoreRole,
        store_identity: str,
        settlement_journal: PackageStoreSettlementJournal,
        transfer: PackageVerifiedTreeTransferOwner | None,
        commit_probe: Callable[[], None] | None,
        receipt_probe: Callable[[], None] | None,
        read_only: bool = False,
    ) -> None:
        self._check_available()
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
        self._root = raw_root
        if self._root == Path(self._root.anchor):
            raise PackagePhysicalStagingError(
                "Filesystem root cannot be a Package Store root",
                code="package_publication_root_untrusted",
            )
        self._role = role
        self._store_identity = store_identity
        self._settlement_journal = settlement_journal
        self._transfer = transfer or PackageVerifiedTreeTransferOwner()
        self._commit_probe = commit_probe
        self._receipt_probe = receipt_probe
        self._lock = threading.RLock()
        self._read_only = read_only
        provisioned = self._open_root(read_only=read_only)
        try:
            self._root_identities = provisioned.identities
        finally:
            provisioned.close()
        try:
            validate_store_root = (
                self._settlement_journal.read_validate_store_root
                if read_only
                else self._settlement_journal.validate_store_root
            )
            validate_store_root(
                store_role=self._role,
                store_identity=self._store_identity,
                root_identities=self._root_identities,
            )
            if not read_only:
                with self._settlement_journal.owner_lock():
                    pass
        except PackageStoreSettlementJournalError:
            raise _root_untrusted() from None

    @contextmanager
    def pin_root(self) -> Iterator[RootT]:
        root = self._open_root(
            expected_identities=self._root_identities, read_only=self._read_only
        )
        try:
            yield root
        finally:
            root.close()

    def read_settlement_file(
        self,
        settlement: PackageStoreSettlementRecordV1,
        logical_path: str,
        *,
        max_bytes: int,
        read_only: bool = False,
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
        result = self._read_entries(settlement, (entry,), read_only=read_only)
        return result[0]

    def read_settlement_files(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
        *,
        read_only: bool = False,
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
        result = self._read_entries(
            settlement, tuple(by_path[path] for path, _ in members), read_only=read_only
        )
        return result

    def _read_entries(
        self,
        settlement: PackageStoreSettlementRecordV1,
        entries: tuple[PackageVerifiedTreeEntryV1, ...],
        *,
        read_only: bool,
    ) -> tuple[bytes, ...]:
        try:
            owner_lock = (
                self._settlement_journal.read_owner_lock()
                if read_only
                else self._settlement_journal.owner_lock()
            )
            with self._lock, owner_lock:
                root = self._open_root(
                    expected_identities=self._root_identities,
                    read_only=self._read_only,
                )
                try:
                    events = (
                        self._settlement_journal.read_events()
                        if read_only
                        else self._settlement_journal.capture_events()
                    )
                    tombstoned = any(
                        isinstance(event, PackageStoreGcTombstoneV1)
                        and event.stable_ref_id == settlement.receipt.stable_ref.ref_id
                        for event in events
                    )
                    if (
                        tuple(
                            identity.to_native()
                            for identity in settlement.root_identities
                        )
                        != root.identities
                        or not self._settlement_present(events, settlement)
                        or tombstoned
                    ):
                        raise _collision()
                    return tuple(root.read_file(settlement, entry) for entry in entries)
                finally:
                    root.close()
        except PackagePhysicalStagingError:
            raise
        except (OSError, PackageStoreSettlementJournalError):
            raise _root_untrusted() from None

    def _settlement_present(
        self, events: Iterable[object], settlement: PackageStoreSettlementRecordV1
    ) -> bool:
        return settlement_record_present(events, settlement)

    @abstractmethod
    def delete_settlement(
        self, settlement: PackageStoreSettlementRecordV1
    ) -> PackageStoreGcResultV1: ...

    @abstractmethod
    def _check_available(self) -> None: ...

    def _check_writable(self) -> None:
        """Platforms with construction-time handle restrictions override this."""

    @abstractmethod
    def _open_root(
        self,
        *,
        expected_identities: tuple[NativeIdentity, ...] | None = None,
        read_only: bool = False,
    ) -> RootT: ...

    @abstractmethod
    def _create_sink(
        self,
        root: RootT,
        request: PackageArtifactStagingRequestV1,
        manifest: PackageVerifiedTreeManifestV1,
        release_owner_lock: Callable[[], None],
    ) -> SinkT: ...

    def stage(
        self,
        request: PackageArtifactStagingRequestV1,
        candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        self._check_writable()
        if not isinstance(candidate, VerifiedWheelCandidate):
            raise TypeError("Verified Wheel candidate is required")
        with self.open_sink(request, candidate.transfer_manifest) as sink:
            return self._transfer.transfer(request, candidate, sink)

    def validate_receipt(
        self,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageArtifactStagingReceiptV1:
        self._check_writable()
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
            with self.pin_root() as root:
                return validate_receipt_at_root(
                    root,
                    receipt,
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
            root = self._open_root(
                expected_identities=self._root_identities,
                read_only=self._read_only,
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
                settled_refs = {record.receipt.stable_ref.ref_id for record in records}
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

    def authorizes_root_identity(self, expected_identity: str) -> bool:
        if self._role != "root" or not isinstance(expected_identity, str):
            return False
        self._lock.acquire()
        try:
            root = self._open_root(
                expected_identities=self._root_identities,
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
    ) -> SinkT:
        self._check_writable()
        validate_role_request(self._role, request, manifest)
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
            root = self._open_root(
                expected_identities=self._root_identities,
            )
            try:
                return self._create_sink(root, request, manifest, release_owner_lock)
            except Exception:
                root.close()
                raise
        except Exception:
            release_owner_lock()
            raise


def validate_role_request(
    role: PackageStoreRole,
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


def stable_ref(
    role: PackageStoreRole,
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


class PackageDependencyMaterializationStore:
    """Dependency-only adapter over one configured immutable Store root."""

    _store_type: ClassVar[type[PackageRoleStore]]

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
        self._store = self._store_type(
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


class PackageDependencyReadOnlyStore:
    """Store-verified dependency bytes for Product-owned execution proof."""

    _store_type: ClassVar[type[PackageRoleStore]]

    read_only = True

    def __init__(
        self,
        root: str | Path,
        *,
        store_identity: str,
        settlement_journal: PackageStoreSettlementJournal,
    ) -> None:
        self._store = self._store_type(
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
            settlement, logical_path, max_bytes=max_bytes, read_only=True
        )

    def read_dependency_files(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
    ) -> tuple[bytes, ...]:
        return self._store.read_settlement_files(settlement, members, read_only=True)


class PackagePluginRootMaterializationStore:
    """Designated-Plugin-root adapter over one configured revision Store root."""

    _store_type: ClassVar[type[PackageRoleStore]]

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
        self._store = self._store_type(
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
        """Read one verified member without exposing a Store pathname."""

        return self._store.read_settlement_file(
            settlement, logical_path, max_bytes=max_bytes
        )

    def read_root_files(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
    ) -> tuple[bytes, ...]:
        """Verify one settlement and read its members under the same owner lock."""

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
        """Prove that an adoption request names this exact configured root."""

        if (
            self._package_store_id is None
            or store_id != self._package_store_id
            or not isinstance(target, PackagePluginRootTargetV1)
        ):
            return False
        return self._store.authorizes_root_identity(current_root_identity)


class PackagePluginRootReadOnlyStore:
    """Store-verified root reads for inert Product explanation and preview."""

    _store_type: ClassVar[type[PackageRoleStore]]

    read_only = True

    def __init__(
        self,
        root: str | Path,
        *,
        store_identity: str,
        settlement_journal: PackageStoreSettlementJournal,
    ) -> None:
        self._store = self._store_type(
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
            settlement, logical_path, max_bytes=max_bytes, read_only=True
        )

    def read_root_files(
        self,
        settlement: PackageStoreSettlementRecordV1,
        members: tuple[tuple[str, int], ...],
    ) -> tuple[bytes, ...]:
        return self._store.read_settlement_files(settlement, members, read_only=True)


def settlement_record_present(
    events: Iterable[object], settlement: PackageStoreSettlementRecordV1
) -> bool:
    """Compare a full record only after its authenticated identity matches."""

    return any(
        isinstance(event, PackageStoreSettlementRecordV1)
        and event.settlement_id == settlement.settlement_id
        and event == settlement
        for event in events
    )
