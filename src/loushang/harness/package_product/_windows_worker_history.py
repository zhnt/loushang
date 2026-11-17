"""Windows Worker history publication at the existing Package Product boundary.

The original Product retains GC/runtime authority and the existing private
receipt owner performs all IO. These fixed operations coordinate proof capture,
exact staged retry and read-back; they introduce no journal or authority switch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
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


class CapturePreparedWindowsSemantic(Protocol):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        store: PackageWindowsEpochRuntimeLeaseRegistry,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
        allow_preparation_stage: bool = False,
    ) -> Callable[[], _WindowsHistorySemanticFacts]: ...


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
    capture_semantic: CapturePreparedWindowsSemantic,
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
