"""Windows Worker history publication at the existing Package Product boundary.

The original Product retains GC/runtime authority and the existing private
receipt owner performs all IO. These fixed operations coordinate proof capture,
exact staged retry and read-back; they introduce no journal or authority switch.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Generic, Protocol, TypeVar, cast

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product._windows_worker_references import (
    _WindowsPackageReferenceMethods,
    _WindowsProductHistorySemanticFacts,
    capture_windows_product_worker_desired_history,
    windows_worker_desired_history_digest,
)
from loushang.harness.package_product._worker_history_access import (
    windows_product_worker_quiescence,
)
from loushang.harness.package_product._worker_windows_attempt import is_windows_product
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsEpochRuntimeLeaseRegistry,
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.worker.history._native_approval import _NativeDecision
from loushang.harness.worker.history._windows_checkpoint import (
    _WindowsHistoryCheckpointMethods,
    _WindowsHistoryPreparationMethods,
    _WindowsHistorySemanticFacts,
)
from loushang.harness.worker.history._windows_persisted import (
    _WindowsHistoryCutoverMethods,
    _WindowsPersistedBasesMethods,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _DIGEST,
    _RecoveryFacts,
    _WorkerBackupObservationFacts,
)
from loushang.harness.worker.history._windows_sources import (
    WINDOWS_WORKER_BASE_FILES,
    WINDOWS_WORKER_HISTORY_CHECKPOINT_MAX_BYTES,
    WINDOWS_WORKER_HISTORY_CHECKPOINT_NAME,
    WINDOWS_WORKER_HISTORY_PREPARATION_NAME,
    WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES,
    _WindowsHistorySourceSnapshotMethods,
)

_SemanticT_co = TypeVar(
    "_SemanticT_co", bound=_WindowsHistorySemanticFacts, covariant=True
)
_SemanticT = TypeVar("_SemanticT", bound=_WindowsHistorySemanticFacts)
_SourceSnapshotT = TypeVar(
    "_SourceSnapshotT", bound=_WindowsHistorySourceSnapshotMethods
)


class CapturePreparedWindowsSemantic(Protocol[_SemanticT_co]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        store: PackageWindowsEpochRuntimeLeaseRegistry
        | PackageWindowsRuntimeQuiescenceV1,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
        allow_preparation_stage: bool = False,
        allow_checkpoint_stage: bool = False,
        allow_base_stage: bool = False,
    ) -> Callable[[], _SemanticT_co]: ...


_CheckpointT_co = TypeVar(
    "_CheckpointT_co", bound=_WindowsHistoryCheckpointMethods, covariant=True
)
_PreparationT = TypeVar("_PreparationT", bound=_WindowsHistoryPreparationMethods)
_CheckpointT = TypeVar("_CheckpointT", bound=_WindowsHistoryCheckpointMethods)


class ReviewWindowsCheckpoint(Protocol[_CheckpointT_co]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
        allow_checkpoint_stage: bool,
        allow_base_stage: bool = False,
    ) -> _CheckpointT_co: ...


def _read_pending_history_publication(
    io: WindowsPrivateReceiptIO, path: Path, *, maximum_bytes: int,
) -> tuple[bytes | None, bytes | None]:
    published = io.read_private_receipt(
        path, maximum_bytes=maximum_bytes, allow_unpublished_stage=True,
    )
    staged = io.read_private_receipt(
        path.with_name(path.name + ".stage"), maximum_bytes=maximum_bytes,
    )
    return published, staged


@contextmanager
def _hold_windows_worker_history(
    product: WindowsLocalWheelProductSessionOwner, *, active_message: str
) -> Iterator[
    tuple[PackageWindowsEpochRuntimeLeaseRegistry, PackageWindowsRuntimeQuiescenceV1]
]:
    """Borrow existing offline and GC guards for a complete history operation."""

    with windows_product_worker_quiescence(
        product, active_message=active_message
    ) as authority:
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            yield authority


def _require_windows_history_product(
    product: WindowsLocalWheelProductSessionOwner, product_id: str, message: str
) -> None:
    if not is_windows_product(
        product, product_id, os.name, WindowsLocalWheelProductSessionOwner
    ):
        raise ValueError(message)


class WindowsHistorySettlement(Protocol):
    def require_settled(
        self,
        *,
        observed_names: tuple[str, ...],
        allow_preparation_stage: bool = False,
        allow_checkpoint_stage: bool = False,
        allow_base_stage: bool = False,
    ) -> None: ...


def capture_windows_product_worker_sources_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    snapshot_type: type[_SourceSnapshotT],
    settlement_type: Callable[
        [WindowsLocalWheelProductSessionOwner], WindowsHistorySettlement
    ],
    store_id: str,
    lease_owner_revision: int,
    require_settled_history: bool,
    allow_preparation_stage: bool = False,
    allow_checkpoint_stage: bool = False,
    allow_base_stage: bool = False,
) -> _SourceSnapshotT:
    """Hold original Product roots through source capture and settlement proof."""
    product.assert_root_gc_authority_current()
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        with WindowsPrivateDirectoryAcl() as acl:
            acl.validate(root)
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise ValueError("Windows Worker history root changed")
            with snapshot_type._source_reader().capture(
                root,
                acl,
                allow_preparation_stage=allow_preparation_stage,
                allow_checkpoint_stage=allow_checkpoint_stage,
                allow_base_stage=allow_base_stage,
            ) as (before, files):
                if require_settled_history:
                    settlement_type(product).require_settled(
                        observed_names=before,
                        allow_preparation_stage=allow_preparation_stage,
                        allow_checkpoint_stage=allow_checkpoint_stage,
                        allow_base_stage=allow_base_stage,
                    )
            if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                raise ValueError("Windows Worker history root changed")
    product.assert_root_gc_authority_current()
    return snapshot_type._from_files(
        scope_id=product.policy.project_scope_id,
        store_id=store_id,
        lease_owner_revision=lease_owner_revision,
        files=tuple(files),
    )


class _WindowsHistorySemanticReadMethods:
    __slots__ = ()
    _source_snapshot_type: ClassVar[type[_WindowsHistorySourceSnapshotMethods]]
    _recovery_snapshot_type: ClassVar[type[_RecoveryFacts]]
    source_snapshot: _WindowsHistorySourceSnapshotMethods
    offline_recovery: _RecoveryFacts
    desired_inventory_revision: int | None
    desired_history_digest: str | None
    desired_snapshot: PluginDesiredStateSnapshotV1 | None
    desired_transitions: tuple[PluginDesiredStateJournalTransition, ...] | None

    def __post_init__(self) -> None:
        if (
            type(self.source_snapshot) is not self._source_snapshot_type
            or type(self.offline_recovery) is not self._recovery_snapshot_type
            or self.source_snapshot.store_id != self.offline_recovery.store_id
            or self.source_snapshot.lease_owner_revision
            != self.offline_recovery.lease_owner_revision
            or (
                (self.desired_inventory_revision is None)
                != (self.desired_history_digest is None)
            )
            or ((self.desired_snapshot is None) != (self.desired_transitions is None))
            or (
                (self.desired_snapshot is None) != (self.desired_history_digest is None)
            )
            or (
                self.desired_inventory_revision is not None
                and (
                    type(self.desired_inventory_revision) is not int
                    or self.desired_inventory_revision < 0
                    or type(self.desired_history_digest) is not str
                    or _DIGEST.fullmatch(self.desired_history_digest) is None
                )
            )
            or (
                self.desired_snapshot is not None
                and (
                    type(self.desired_snapshot) is not PluginDesiredStateSnapshotV1
                    or type(self.desired_transitions) is not tuple
                    or self.desired_snapshot.inventory_revision
                    != self.desired_inventory_revision
                    or windows_worker_desired_history_digest(
                        self.desired_snapshot, self.desired_transitions
                    )
                    != self.desired_history_digest
                )
            )
            or self.offline_recovery.gc_revision_refs
            or any(
                observation.worker_backup_supported or observation.references
                for observation in self.offline_recovery.worker_backup_observations
            )
        ):
            raise ValueError("Windows Worker history semantic read is invalid")


class ReadWindowsOfflineRecovery(Protocol):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        store_id: str,
        lease_owner_revision: int,
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
    ) -> _RecoveryFacts: ...


_SemanticRecordT = TypeVar("_SemanticRecordT", bound=_WindowsHistorySemanticReadMethods)
_SettlementReviewT = TypeVar("_SettlementReviewT")


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerHistorySources(
    Generic[_SourceSnapshotT, _SemanticRecordT, _SettlementReviewT]
):
    """Configured source and semantic reads using the original history owners.

    Only nominal factories and Product identity are bound here. Runtime/GC
    guards, source IO, settlement and recovery keep their existing owners.
    """

    product_id: str
    snapshot_type: type[_SourceSnapshotT]
    semantic_type: type[_SemanticRecordT]
    settlement_review: Callable[[_SourceSnapshotT], _SettlementReviewT]
    settlement_type: Callable[
        [WindowsLocalWheelProductSessionOwner], WindowsHistorySettlement
    ]
    recovery_reader: ReadWindowsOfflineRecovery

    def _require_product(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        _require_windows_history_product(
            product, self.product_id, "Windows Worker history requires its Product owner"
        )

    def capture_sources(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> _SourceSnapshotT:
        """Hash all recognized Worker-owned files without changing Product state."""
        return self.capture_sources_with_settlement(
            product, require_settled_history=False
        )

    def review_settled_sources(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> _SettlementReviewT:
        """Join source bytes to GC's complete-attempt retirement proof."""
        return self.settlement_review(
            self.capture_sources_with_settlement(
                product, require_settled_history=True
            )
        )

    def capture_sources_with_settlement(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        require_settled_history: bool,
    ) -> _SourceSnapshotT:
        """Capture source bytes and optionally verify GC's settlement proof."""
        self._require_product(product)
        snapshot_type = self.snapshot_type
        settlement_type = self.settlement_type
        with windows_product_worker_quiescence(
            product, active_message="Windows Worker history runtime remains active"
        ) as (registry, quiescence):
            product.assert_root_gc_authority_current()
            with product.gc_gate.guard(require_write=True):
                snapshot = capture_windows_product_worker_sources_under_guard(
                    product,
                    snapshot_type=snapshot_type,
                    settlement_type=settlement_type,
                    store_id=registry.store_id,
                    lease_owner_revision=quiescence.owner_revision,
                    require_settled_history=require_settled_history,
                )
            product.assert_root_gc_authority_current()
        return snapshot

    def read_semantics(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> _SemanticRecordT:
        """Join settled source bytes and retained semantics without publication."""
        self._require_product(product)
        with windows_product_worker_quiescence(
            product, active_message="Windows Worker history runtime remains active"
        ) as (registry, quiescence):
            product.assert_root_gc_authority_current()
            with product.gc_gate.read_snapshot_guard() as gc_snapshot:
                if gc_snapshot.active:
                    raise ValueError("Windows Worker history GC reservation remains")
                build_semantic = self.capture_semantics_under_guard(
                    product,
                    store=registry,
                    quiescence=quiescence,
                    gc_snapshot=gc_snapshot,
                )
            product.assert_root_gc_authority_current()
        return build_semantic()

    def capture_sources_under_guard(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        store_id: str,
        lease_owner_revision: int,
        require_settled_history: bool,
        allow_preparation_stage: bool = False,
        allow_checkpoint_stage: bool = False,
        allow_base_stage: bool = False,
    ) -> _SourceSnapshotT:
        """Pin original Product roots through the shared source owner."""
        return capture_windows_product_worker_sources_under_guard(
            product,
            snapshot_type=self.snapshot_type,
            settlement_type=self.settlement_type,
            store_id=store_id,
            lease_owner_revision=lease_owner_revision,
            require_settled_history=require_settled_history,
            allow_preparation_stage=allow_preparation_stage,
            allow_checkpoint_stage=allow_checkpoint_stage,
            allow_base_stage=allow_base_stage,
        )

    def capture_semantics_under_guard(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        store: PackageWindowsEpochRuntimeLeaseRegistry | PackageWindowsRuntimeQuiescenceV1,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
        allow_preparation_stage: bool = False,
        allow_checkpoint_stage: bool = False,
        allow_base_stage: bool = False,
    ) -> Callable[[], _SemanticRecordT]:
        """Bind nominal record/recovery families to the shared capture owner."""
        semantic_type = self.semantic_type
        settlement_type = self.settlement_type
        recovery_reader = self.recovery_reader
        source = capture_windows_product_worker_sources_under_guard(
            product,
            snapshot_type=semantic_type._source_snapshot_type,
            settlement_type=settlement_type,
            store_id=store.store_id,
            lease_owner_revision=quiescence.owner_revision,
            require_settled_history=True,
            allow_preparation_stage=allow_preparation_stage,
            allow_checkpoint_stage=allow_checkpoint_stage,
            allow_base_stage=allow_base_stage,
        )
        recovery = recovery_reader(
            product,
            store_id=store.store_id,
            lease_owner_revision=quiescence.owner_revision,
            gc_snapshot=gc_snapshot,
        )
        desired_snapshot, desired_transitions, desired_digest = (
            capture_windows_product_worker_desired_history(product)
        )
        if source != capture_windows_product_worker_sources_under_guard(
            product,
            snapshot_type=semantic_type._source_snapshot_type,
            settlement_type=settlement_type,
            store_id=store.store_id,
            lease_owner_revision=quiescence.owner_revision,
            require_settled_history=False,
            allow_preparation_stage=allow_preparation_stage,
            allow_checkpoint_stage=allow_checkpoint_stage,
            allow_base_stage=allow_base_stage,
        ):
            raise ValueError("Windows Worker history sources changed")

        def build_semantic() -> _SemanticRecordT:
            return cast(Callable[..., _SemanticRecordT], semantic_type)(
                source_snapshot=source,
                offline_recovery=recovery,
                desired_inventory_revision=desired_snapshot.inventory_revision,
                desired_history_digest=desired_digest,
                desired_snapshot=desired_snapshot,
                desired_transitions=desired_transitions,
            )

        return build_semantic


_ReferenceT = TypeVar("_ReferenceT", bound=_WindowsPackageReferenceMethods)
_ProductSemanticT = TypeVar(
    "_ProductSemanticT", bound=_WindowsProductHistorySemanticFacts
)
_CutoverT = TypeVar("_CutoverT", bound=_WindowsHistoryCutoverMethods)
_PersistedT = TypeVar("_PersistedT", bound=_WindowsPersistedBasesMethods)
_PersistedT_co = TypeVar(
    "_PersistedT_co", bound=_WindowsPersistedBasesMethods, covariant=True
)


class ObserveWindowsWorkerBackup(Protocol):
    def __call__(
        self, product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
    ) -> _WorkerBackupObservationFacts: ...


class _NativeApprovalHistory(Protocol):
    def history_read_only(
        self, *, directory_fd: int
    ) -> tuple[_NativeDecision, ...]: ...


class ReadWindowsPersistedBases(Protocol[_PersistedT_co]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        root: int,
        *,
        require_cutover: bool,
    ) -> tuple[_PersistedT_co, _WindowsHistoryCutoverMethods | None]: ...


def capture_windows_product_worker_persisted_history(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    read_under_guard: ReadWindowsPersistedBases[_PersistedT],
    require_cutover: bool,
) -> tuple[_PersistedT, _WindowsHistoryCutoverMethods | None]:
    with _hold_windows_worker_history(
        product, active_message="Windows Worker persisted bases runtime remains active"
    ):
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            result = read_under_guard(
                product, root, require_cutover=require_cutover
            )
        product.assert_root_gc_authority_current()
        return result


def review_windows_product_worker_history_cutover_candidate(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    product_id: str,
    record_type: type[_CutoverT],
    read_persisted: ReadWindowsPersistedBases[_WindowsPersistedBasesMethods],
    review_checkpoint: ReviewWindowsCheckpoint[_WindowsHistoryCheckpointMethods],
) -> _CutoverT:
    """Reprove both old sources and retained bases; no marker writer is borrowed."""
    _require_windows_history_product(
        product, product_id, "Windows Worker cutover review requires its Product"
    )
    with _hold_windows_worker_history(
        product, active_message="Windows Worker cutover runtime remains active"
    ) as (_, quiescence):
        gc_snapshot = product.gc_gate.snapshot()
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            persisted, marker = read_persisted(product, root, require_cutover=False)
        if marker is not None:
            raise ValueError("Windows Worker cutover marker is already present")
        current = review_checkpoint(
            product,
            quiescence=quiescence,
            gc_snapshot=gc_snapshot,
            allow_checkpoint_stage=False,
        )
        if current != persisted.checkpoint:
            raise ValueError("Windows Worker cutover source changed")
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            reread, marker = read_persisted(product, root, require_cutover=False)
        if marker is not None or reread != persisted:
            raise ValueError("Windows Worker cutover bases changed")
        product.assert_root_gc_authority_current()
        return record_type._from_persisted_bases(persisted)


class _WindowsSemanticBase(Protocol):
    @property
    def record_digest(self) -> str: ...
    def to_bytes(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerHistoryCommands(
    Generic[_ProductSemanticT, _PreparationT, _ReferenceT, _CheckpointT]
):
    """Coordinate source proofs and publication with one Product history binding."""

    product_id: str
    preparation_type: type[_PreparationT]
    reference_type: type[_ReferenceT]
    checkpoint_type: type[_CheckpointT]
    capture_semantic: CapturePreparedWindowsSemantic[_ProductSemanticT]
    observe_backup: ObserveWindowsWorkerBackup
    approval_journal: Callable[..., _NativeApprovalHistory]
    io: WindowsPrivateReceiptIO

    def prepare(self, product: WindowsLocalWheelProductSessionOwner) -> _PreparationT:
        """Complete the original preparation transaction under unchanged guards."""
        _require_windows_history_product(
            product, self.product_id, "Windows Worker history preparation requires its Product"
        )
        with _hold_windows_worker_history(
            product, active_message="Windows Worker history runtime remains active"
        ) as (registry, quiescence):
            gc_snapshot = product.gc_gate.snapshot()
            if gc_snapshot.active:
                raise ValueError("Windows Worker history GC reservation remains")
            path = product.state_root / WINDOWS_WORKER_HISTORY_PREPARATION_NAME
            published, staged = _read_pending_history_publication(
                self.io, path,
                maximum_bytes=self.preparation_type._wire_maximum(),
            )
            if staged is not None:
                self.preparation_type.from_bytes(staged)
            semantic = self.capture_semantic(
                product,
                store=registry,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
                allow_preparation_stage=staged is not None,
            )()
            prepared = self.preparation_type._create_from_semantic_read(semantic)
            for existing in (published, staged):
                if existing is not None:
                    self.preparation_type.from_bytes(existing)._require_semantic_read(semantic)
            if staged is not None:
                self.io.write_private_receipt(
                    path, staged, maximum_bytes=self.preparation_type._wire_maximum()
                )
            if published is None and staged is None:
                self.io.write_private_receipt(
                    path, prepared.to_bytes(), maximum_bytes=self.preparation_type._wire_maximum()
                )
            retained = self.io.read_private_receipt(
                path, maximum_bytes=self.preparation_type._wire_maximum()
            )
            if retained != prepared.to_bytes():
                raise ValueError("Windows Worker history preparation changed")
            product.assert_root_gc_authority_current()
        return prepared

    def references_under_guard(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
        allow_checkpoint_stage: bool = False,
        allow_base_stage: bool = False,
    ) -> tuple[_ReferenceT, _PreparationT, _ProductSemanticT]:
        """Close the entire captured reference set under the caller's actual guards."""
        if gc_snapshot.active:
            raise ValueError("Windows Worker GC reservation remains active")
        product.assert_root_gc_authority_current()
        semantic = self.capture_semantic(
            product,
            store=quiescence,
            quiescence=quiescence,
            gc_snapshot=gc_snapshot,
            allow_checkpoint_stage=allow_checkpoint_stage,
            allow_base_stage=allow_base_stage,
        )()
        prepared = self.preparation_type._create_from_semantic_read(semantic)
        backup_topology = self.observe_backup(product, attempt_id="0" * 32)
        review = self.reference_type._from_guarded_history(
            prepared,
            semantic,
            quiescence=quiescence,
            backup_topology=backup_topology,
        )
        product.assert_root_gc_authority_current()
        return review, prepared, semantic

    def review_references(self, product: WindowsLocalWheelProductSessionOwner) -> _ReferenceT:
        """Capture the reference closure under quiescence and a read snapshot guard."""
        _require_windows_history_product(
            product, self.product_id, "Windows Worker Package references require their Product"
        )
        with windows_product_worker_quiescence(
            product, active_message="Windows Worker Package runtime remains active"
        ) as (_, quiescence):
            product.assert_root_gc_authority_current()
            with product.gc_gate.read_snapshot_guard() as gc_snapshot:
                review, _, _ = self.references_under_guard(
                    product, quiescence=quiescence, gc_snapshot=gc_snapshot
                )
            product.assert_root_gc_authority_current()
        return review

    def checkpoint_under_guard(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
        allow_checkpoint_stage: bool,
        allow_base_stage: bool = False,
    ) -> _CheckpointT:
        review, prepared, semantic = self.references_under_guard(
            product,
            quiescence=quiescence,
            gc_snapshot=gc_snapshot,
            allow_checkpoint_stage=allow_checkpoint_stage,
            allow_base_stage=allow_base_stage,
        )
        retained_preparation = self.io.read_private_receipt(
            product.state_root / WINDOWS_WORKER_HISTORY_PREPARATION_NAME,
            maximum_bytes=self.checkpoint_type._wire_maximum(),
        )
        if retained_preparation != prepared.to_bytes():
            raise ValueError("Windows Worker checkpoint preparation changed")
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            native_approvals = self.approval_journal(
                product.state_root / "worker-native-release-approvals.jsonl",
                scope_id=product.policy.project_scope_id,
            ).history_read_only(directory_fd=root)
        return self.checkpoint_type._from_guarded_history(
            prepared, semantic, review, native_approvals
        )

    def read_checkpoint(self, product: WindowsLocalWheelProductSessionOwner) -> _CheckpointT:
        """Use existing proof and IO owners without granting an authority switch."""
        _require_windows_history_product(
            product, self.product_id, "Windows Worker checkpoint requires its Product"
        )
        with _hold_windows_worker_history(
            product, active_message="Windows Worker checkpoint runtime remains active"
        ) as (_, quiescence):
            published = self.io.read_private_receipt(
                product.state_root / WINDOWS_WORKER_HISTORY_CHECKPOINT_NAME,
                maximum_bytes=self.checkpoint_type._wire_maximum(),
            )
            if published is None:
                raise ValueError("Windows Worker checkpoint is absent")
            checkpoint = self.checkpoint_type.from_bytes(published)
            current = self.checkpoint_under_guard(
                product,
                quiescence=quiescence,
                gc_snapshot=product.gc_gate.snapshot(),
                allow_checkpoint_stage=False,
            )
            if checkpoint != current:
                raise ValueError("Windows Worker checkpoint source changed")
            retained = self.io.read_private_receipt(
                product.state_root / WINDOWS_WORKER_HISTORY_CHECKPOINT_NAME,
                maximum_bytes=self.checkpoint_type._wire_maximum(),
            )
            if retained != published:
                raise ValueError("Windows Worker checkpoint publication changed")
            product.assert_root_gc_authority_current()
            return checkpoint

    def publish_checkpoint(self, product: WindowsLocalWheelProductSessionOwner) -> _CheckpointT:
        """Use existing proof and IO owners without granting an authority switch."""
        _require_windows_history_product(
            product, self.product_id, "Windows Worker checkpoint requires its Product"
        )
        with _hold_windows_worker_history(
            product, active_message="Windows Worker checkpoint runtime remains active"
        ) as (_, quiescence):
            gc_snapshot = product.gc_gate.snapshot()
            path = product.state_root / WINDOWS_WORKER_HISTORY_CHECKPOINT_NAME
            published, staged = _read_pending_history_publication(
                self.io, path,
                maximum_bytes=self.checkpoint_type._wire_maximum(),
            )
            for raw in (published, staged):
                if raw is not None:
                    self.checkpoint_type.from_bytes(raw)
            checkpoint = self.checkpoint_under_guard(
                product,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
                allow_checkpoint_stage=staged is not None,
            )
            candidate = checkpoint.to_bytes()
            if any(raw is not None and raw != candidate for raw in (published, staged)):
                raise ValueError("Windows Worker checkpoint source changed")
            if published is None:
                self.io.write_private_receipt(
                    path, candidate, maximum_bytes=self.checkpoint_type._wire_maximum()
                )
            retained = self.io.read_private_receipt(
                path, maximum_bytes=self.checkpoint_type._wire_maximum()
            )
            if retained != candidate:
                raise ValueError("Windows Worker checkpoint publication changed")
            product.assert_root_gc_authority_current()
            return checkpoint

    def history_bases(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        publish: bool,
    ) -> _CheckpointT:
        """Reprove all six bases, then read or publish exactly matching retained bytes.

        The old sources remain authoritative. This operation owns guard/retry/IO
        custody, and grants neither a history cutover nor source retirement.
        """
        _require_windows_history_product(
            product, self.product_id, "Windows Worker bases require their Product"
        )
        with _hold_windows_worker_history(
            product, active_message="Windows Worker bases runtime remains active"
        ) as (_, quiescence):
            checkpoint_path = product.state_root / WINDOWS_WORKER_HISTORY_CHECKPOINT_NAME
            published_checkpoint = self.io.read_private_receipt(
                checkpoint_path, maximum_bytes=WINDOWS_WORKER_HISTORY_CHECKPOINT_MAX_BYTES
            )
            if published_checkpoint is None:
                raise ValueError("Windows Worker bases checkpoint is absent")
            checkpoint = self.checkpoint_type.from_bytes(published_checkpoint)
            gc_snapshot = product.gc_gate.snapshot()
            current = self.checkpoint_under_guard(
                product,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
                allow_checkpoint_stage=False,
                allow_base_stage=publish,
            )
            if checkpoint != current:
                raise ValueError("Windows Worker bases checkpoint changed")
            review, prepared, semantic = self.references_under_guard(
                product,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
                allow_base_stage=publish,
            )
            if (
                semantic.source_snapshot != checkpoint.source_snapshot
                or prepared.record_digest != checkpoint.preparation_digest
                or review.review_digest != checkpoint.package_reference_digest
            ):
                raise ValueError("Windows Worker bases checkpoint changed")
            joined = self.checkpoint_type._join_type._from_prepared_history(prepared, semantic)
            bases: tuple[_WindowsSemanticBase, ...] = (
                joined.opt_in,
                joined.receipt,
                joined.supervisor,
                joined.c5,
                joined.launch_intent,
                joined.native_provisioning,
            )
            if checkpoint.base_digests != tuple(
                (key, base.record_digest)
                for (key, _), base in zip(WINDOWS_WORKER_BASE_FILES, bases, strict=True)
            ):
                raise ValueError("Windows Worker bases checkpoint changed")
            expected = tuple(
                (product.state_root / name, base.to_bytes())
                for (_, name), base in zip(
                    WINDOWS_WORKER_BASE_FILES, bases, strict=True
                )
            )
            retained_bases: list[bytes | None] = []
            for path, raw in expected:
                retained = self.io.read_private_receipt(
                    path,
                    maximum_bytes=WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES,
                    allow_unpublished_stage=publish,
                )
                staged = (
                    self.io.read_private_receipt(
                        path.with_name(path.name + ".stage"),
                        maximum_bytes=WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES,
                    )
                    if publish
                    else None
                )
                if (retained is not None and retained != raw) or (
                    staged is not None and staged != raw
                ):
                    raise ValueError("Windows Worker base source changed")
                retained_bases.append(retained)
            if not publish and any(raw is None for raw in retained_bases):
                raise ValueError("Windows Worker base is absent")
            if publish:
                for (path, raw), retained in zip(expected, retained_bases, strict=True):
                    if retained is None:
                        self.io.write_private_receipt(
                            path, raw, maximum_bytes=WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES
                        )
            if any(
                self.io.read_private_receipt(
                    path, maximum_bytes=WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES
                ) != raw
                for path, raw in expected
            ):
                raise ValueError("Windows Worker base publication changed")
            if (
                self.io.read_private_receipt(
                    checkpoint_path, maximum_bytes=WINDOWS_WORKER_HISTORY_CHECKPOINT_MAX_BYTES
                )
                != published_checkpoint
            ):
                raise ValueError("Windows Worker bases checkpoint changed")
            product.assert_root_gc_authority_current()
            return checkpoint
