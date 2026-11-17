"""Windows Worker history publication at the existing Package Product boundary.

The original Product retains GC/runtime authority and the existing private
receipt owner performs all IO. These fixed operations coordinate proof capture,
exact staged retry and read-back; they introduce no journal or authority switch.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import ClassVar, Protocol, TypeVar, cast

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product._windows_worker_references import (
    capture_windows_product_worker_desired_history,
    windows_worker_desired_history_digest,
)
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
from loushang.harness.worker.history._windows_checkpoint import (
    _WindowsHistoryCheckpointMethods,
    _WindowsHistoryPreparationMethods,
    _WindowsHistorySemanticFacts,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _DIGEST,
    _RecoveryFacts,
)
from loushang.harness.worker.history._windows_sources import (
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
        store: PackageWindowsEpochRuntimeLeaseRegistry,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
        allow_preparation_stage: bool = False,
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
    ) -> _CheckpointT_co: ...


def prepare_windows_product_worker_history(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    record_type: type[_PreparationT],
    capture_semantic: CapturePreparedWindowsSemantic[_WindowsHistorySemanticFacts],
    io: WindowsPrivateReceiptIO,
    name: str,
) -> _PreparationT:
    """Complete the original preparation transaction under unchanged guards."""
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker history runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            gc_snapshot = product.gc_gate.snapshot()
            if gc_snapshot.active:
                raise ValueError("Windows Worker history GC reservation remains")
            path = product.state_root / name
            published = io.read_private_receipt(
                path,
                maximum_bytes=record_type._wire_maximum(),
                allow_unpublished_stage=True,
            )
            staged = io.read_private_receipt(
                path.with_name(name + ".stage"),
                maximum_bytes=record_type._wire_maximum(),
            )
            if staged is not None:
                record_type.from_bytes(staged)
            semantic = capture_semantic(
                product,
                store=registry,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
                allow_preparation_stage=staged is not None,
            )()
            prepared = record_type._create_from_semantic_read(semantic)
            for existing in (published, staged):
                if existing is not None:
                    record_type.from_bytes(existing)._require_semantic_read(semantic)
            if staged is not None:
                io.write_private_receipt(
                    path, staged, maximum_bytes=record_type._wire_maximum()
                )
            if published is None and staged is None:
                io.write_private_receipt(
                    path, prepared.to_bytes(), maximum_bytes=record_type._wire_maximum()
                )
            retained = io.read_private_receipt(
                path, maximum_bytes=record_type._wire_maximum()
            )
            if retained != prepared.to_bytes():
                raise ValueError("Windows Worker history preparation changed")
            product.assert_root_gc_authority_current()
        return prepared


def read_windows_product_worker_checkpoint(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    record_type: type[_CheckpointT],
    review_checkpoint: ReviewWindowsCheckpoint[_CheckpointT],
    io: WindowsPrivateReceiptIO,
    name: str,
) -> _CheckpointT:
    """Use existing proof and IO owners without granting an authority switch."""
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker checkpoint runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            published = io.read_private_receipt(
                product.state_root / name,
                maximum_bytes=record_type._wire_maximum(),
            )
            if published is None:
                raise ValueError("Windows Worker checkpoint is absent")
            checkpoint = record_type.from_bytes(published)
            current = review_checkpoint(
                product,
                quiescence=quiescence,
                gc_snapshot=product.gc_gate.snapshot(),
                allow_checkpoint_stage=False,
            )
            if checkpoint != current:
                raise ValueError("Windows Worker checkpoint source changed")
            retained = io.read_private_receipt(
                product.state_root / name,
                maximum_bytes=record_type._wire_maximum(),
            )
            if retained != published:
                raise ValueError("Windows Worker checkpoint publication changed")
            product.assert_root_gc_authority_current()
            return checkpoint


def publish_windows_product_worker_checkpoint(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    record_type: type[_CheckpointT],
    review_checkpoint: ReviewWindowsCheckpoint[_CheckpointT],
    io: WindowsPrivateReceiptIO,
    name: str,
) -> _CheckpointT:
    """Use existing proof and IO owners without granting an authority switch."""
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker checkpoint runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            gc_snapshot = product.gc_gate.snapshot()
            path = product.state_root / name
            published = io.read_private_receipt(
                path,
                maximum_bytes=record_type._wire_maximum(),
                allow_unpublished_stage=True,
            )
            staged = io.read_private_receipt(
                path.with_name(name + ".stage"),
                maximum_bytes=record_type._wire_maximum(),
            )
            for raw in (published, staged):
                if raw is not None:
                    record_type.from_bytes(raw)
            checkpoint = review_checkpoint(
                product,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
                allow_checkpoint_stage=staged is not None,
            )
            candidate = checkpoint.to_bytes()
            if any(raw is not None and raw != candidate for raw in (published, staged)):
                raise ValueError("Windows Worker checkpoint source changed")
            if published is None:
                io.write_private_receipt(
                    path, candidate, maximum_bytes=record_type._wire_maximum()
                )
            retained = io.read_private_receipt(
                path, maximum_bytes=record_type._wire_maximum()
            )
            if retained != candidate:
                raise ValueError("Windows Worker checkpoint publication changed")
            product.assert_root_gc_authority_current()
            return checkpoint


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


def capture_windows_product_worker_history_sources(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    snapshot_type: type[_SourceSnapshotT],
    settlement_type: Callable[
        [WindowsLocalWheelProductSessionOwner], WindowsHistorySettlement
    ],
    require_settled_history: bool,
) -> _SourceSnapshotT:
    """Capture under original runtime/GC lifetimes; approval stays at the caller."""
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker history runtime remains active")
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


def read_windows_product_worker_history_semantics(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    capture_semantic: CapturePreparedWindowsSemantic[_SemanticT],
) -> _SemanticT:
    """Keep the original read guards and construct immutable values after exit."""
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker history runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.read_snapshot_guard() as gc_snapshot:
            if gc_snapshot.active:
                raise ValueError("Windows Worker history GC reservation remains")
            build_semantic = capture_semantic(
                product,
                store=registry,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
            )
        product.assert_root_gc_authority_current()
    return build_semantic()


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


def capture_windows_product_worker_history_semantics_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    semantic_type: type[_SemanticRecordT],
    settlement_type: Callable[
        [WindowsLocalWheelProductSessionOwner], WindowsHistorySettlement
    ],
    recovery_reader: ReadWindowsOfflineRecovery,
    store: PackageWindowsEpochRuntimeLeaseRegistry | PackageWindowsRuntimeQuiescenceV1,
    quiescence: PackageWindowsRuntimeQuiescenceV1,
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
    allow_preparation_stage: bool = False,
    allow_checkpoint_stage: bool = False,
    allow_base_stage: bool = False,
) -> Callable[[], _SemanticRecordT]:
    """Capture source/recovery/Desired/source in order, then build a pure value."""
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
