"""Guarded Package lease and backup closure for Windows Worker history.

This is a read-only Product preflight input. It does not publish a checkpoint,
switch journal ownership, or authorize deletion of retained source bytes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_history import (
    capture_windows_product_worker_reference_inputs_under_guard,
    review_windows_product_worker_package_references,
)
from loushang.harness.package_product._windows_worker_references import (
    _WindowsPackageReferenceMethods,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)

from .product_backup_types import (
    CodingWorkerBackupReferenceObservationV1,
    observe_coding_worker_backup_references_under_gc_guard,
)
from .product_worker_windows_desired_references import (
    CodingWindowsWorkerDesiredReferenceReviewV1,
)
from .product_worker_windows_history_join import (
    CodingWindowsWorkerHistorySemanticJoinV1,
)
from .product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    _capture_coding_windows_worker_semantics_under_gc_guard,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPackageReferenceReviewV1(_WindowsPackageReferenceMethods):
    _desired_type = CodingWindowsWorkerDesiredReferenceReviewV1
    _join_type = CodingWindowsWorkerHistorySemanticJoinV1
    """One guarded reference set, with no history retirement authority."""

    _backup_observation_type = CodingWorkerBackupReferenceObservationV1

    scope_id: str
    store_id: str
    source_snapshot_digest: str
    semantic_digest: str
    desired_review_digest: str
    history_join_digest: str
    lease_owner_revision: int
    backup_topology_revision: str
    repaired_runtime_leases: tuple[tuple[str, str, int], ...]
    worker_backup_observations: tuple[tuple[str, str], ...]
    review_digest: str

    @classmethod
    def from_guarded_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
        *,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        backup_topology: CodingWorkerBackupReferenceObservationV1,
    ) -> CodingWindowsWorkerPackageReferenceReviewV1:
        return cls._from_guarded_history(
            prepared, semantic, quiescence=quiescence, backup_topology=backup_topology
        )


def review_coding_windows_worker_package_references(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerPackageReferenceReviewV1:
    """Capture all preflight inputs while Package and Product guards stay held."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker Package references require their Product")
    return review_windows_product_worker_package_references(
        product,
        review_under_guard=_review_coding_windows_worker_package_references_under_guard,
    )


def _review_coding_windows_worker_package_references_under_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    quiescence: PackageWindowsRuntimeQuiescenceV1,
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
    allow_checkpoint_stage: bool = False,
    allow_base_stage: bool = False,
) -> tuple[
    CodingWindowsWorkerPackageReferenceReviewV1,
    CodingWindowsWorkerHistoryPreparationV1,
    CodingWindowsWorkerHistorySemanticReadV1,
]:
    """Return the review and exact inputs while both outer locks remain held."""

    return capture_windows_product_worker_reference_inputs_under_guard(
        product,
        record_type=CodingWindowsWorkerPackageReferenceReviewV1,
        preparation_type=CodingWindowsWorkerHistoryPreparationV1,
        capture_semantic=_capture_coding_windows_worker_semantics_under_gc_guard,
        observe_backup=observe_coding_worker_backup_references_under_gc_guard,
        quiescence=quiescence,
        gc_snapshot=gc_snapshot,
        allow_checkpoint_stage=allow_checkpoint_stage,
        allow_base_stage=allow_base_stage,
    )


__all__ = [
    "CodingWindowsWorkerPackageReferenceReviewV1",
    "review_coding_windows_worker_package_references",
]
