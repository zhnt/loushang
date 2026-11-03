"""Guarded Package lease and backup closure for Windows Worker history.

This is a read-only Product preflight input. It does not publish a checkpoint,
switch journal ownership, or authorize deletion of retained source bytes.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)

from .package_product_backup_types import (
    CodingWorkerBackupReferenceObservationV1,
    observe_coding_worker_backup_references_under_gc_guard,
)
from .package_product_worker_windows_desired_references import (
    CodingWindowsWorkerDesiredReferenceReviewV1,
)
from .package_product_worker_windows_history_join import (
    CodingWindowsWorkerHistorySemanticJoinV1,
)
from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    _capture_coding_windows_worker_desired_history_under_gc_guard,
    _capture_coding_windows_worker_history_sources_under_gc_guard,
)
from .package_product_worker_windows_recovery_inventory import (
    _inspect_coding_windows_product_worker_offline_recovery_under_gc_guard,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPackageReferenceReviewV1:
    """One guarded reference set, with no history retirement authority."""

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

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or type(self.store_id) is not str
            or not self.store_id
            or any(
                type(value) is not str or _DIGEST.fullmatch(value) is None
                for value in (
                    self.source_snapshot_digest,
                    self.semantic_digest,
                    self.desired_review_digest,
                    self.history_join_digest,
                    self.review_digest,
                )
            )
            or type(self.lease_owner_revision) is not int
            or self.lease_owner_revision < 1
            or type(self.backup_topology_revision) is not str
            or not self.backup_topology_revision
            or self.repaired_runtime_leases
            != tuple(sorted(set(self.repaired_runtime_leases)))
            or any(
                type(runtime_id) is not str
                or not runtime_id
                or type(lease_id) is not str
                or _DIGEST.fullmatch(lease_id) is None
                or type(revision) is not int
                or not 0 < revision < self.lease_owner_revision
                for runtime_id, lease_id, revision in self.repaired_runtime_leases
            )
            or self.worker_backup_observations
            != tuple(sorted(set(self.worker_backup_observations)))
            or any(
                type(attempt_id) is not str
                or re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None
                or type(owner_revision) is not str
                or not owner_revision
                for attempt_id, owner_revision in self.worker_backup_observations
            )
            or self.review_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker Package reference review is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "backupTopologyRevision": self.backup_topology_revision,
            "desiredReviewDigest": self.desired_review_digest,
            "historyJoinDigest": self.history_join_digest,
            "leaseOwnerRevision": self.lease_owner_revision,
            "repairedRuntimeLeases": [
                list(item) for item in self.repaired_runtime_leases
            ],
            "scopeId": self.scope_id,
            "semanticDigest": self.semantic_digest,
            "sourceSnapshotDigest": self.source_snapshot_digest,
            "storeId": self.store_id,
            "version": 1,
            "workerBackupObservations": [
                list(item) for item in self.worker_backup_observations
            ],
        }

    @classmethod
    def from_guarded_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
        *,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
        backup_topology: CodingWorkerBackupReferenceObservationV1,
    ) -> CodingWindowsWorkerPackageReferenceReviewV1:
        """Join Package and Product facts captured under the same held guards."""

        prepared.require_semantic_read(semantic)
        recovery = semantic.offline_recovery
        if (
            type(quiescence) is not PackageWindowsRuntimeQuiescenceV1
            or quiescence.store_id != semantic.source_snapshot.store_id
            or quiescence.owner_revision
            != semantic.source_snapshot.lease_owner_revision
            or quiescence.active_runtime_lease_ids
            or recovery.gc_revision_refs
            or type(backup_topology) is not CodingWorkerBackupReferenceObservationV1
            or backup_topology.attempt_id != "0" * 32
            or backup_topology.worker_backup_supported
            or backup_topology.references
        ):
            raise ValueError("Windows Worker Package reference closure changed")
        desired = CodingWindowsWorkerDesiredReferenceReviewV1.from_semantic_read(
            prepared, semantic
        )
        joined = CodingWindowsWorkerHistorySemanticJoinV1.from_semantic_read(
            prepared, semantic
        )
        attempts = tuple(sorted(item.attempt_id for item in recovery.attempts))
        observations = recovery.worker_backup_observations
        if (
            len(observations) != len(attempts)
            or tuple(sorted(item.attempt_id for item in observations)) != attempts
            or any(
                item.worker_backup_supported or item.references for item in observations
            )
            or any(
                item.owner_revision != backup_topology.owner_revision
                for item in observations
            )
        ):
            raise ValueError("Windows Worker backup references are not closed")
        receipts = {
            record.receipt.fingerprint: record.receipt
            for record in recovery.receipt_records
        }
        runtime_ids = {
            receipt.policy.product_runtime_id for receipt in receipts.values()
        }
        repaired_records = quiescence.repaired_runtime_records
        if any(
            record.store_id != quiescence.store_id
            or record.kind != "orphan_repaired"
            or record.record_revision >= quiescence.owner_revision
            for record in repaired_records
        ):
            raise ValueError("Windows Worker Package lease repair changed")
        relevant_repairs = tuple(
            sorted(
                (
                    record.lease.runtime_id,
                    record.lease.lease_id,
                    record.record_revision,
                )
                for record in repaired_records
                if record.lease.runtime_id in runtime_ids
            )
        )
        if len({item[0] for item in relevant_repairs}) != len(relevant_repairs):
            raise ValueError("Windows Worker Package lease repair is ambiguous")
        backups = tuple(
            sorted((item.attempt_id, item.owner_revision) for item in observations)
        )
        unsigned = {
            "backupTopologyRevision": backup_topology.owner_revision,
            "desiredReviewDigest": desired.review_digest,
            "historyJoinDigest": joined.review_digest,
            "leaseOwnerRevision": quiescence.owner_revision,
            "repairedRuntimeLeases": [list(item) for item in relevant_repairs],
            "scopeId": semantic.source_snapshot.scope_id,
            "semanticDigest": prepared.semantic_digest,
            "sourceSnapshotDigest": semantic.source_snapshot.snapshot_digest,
            "storeId": quiescence.store_id,
            "version": 1,
            "workerBackupObservations": [list(item) for item in backups],
        }
        return cls(
            scope_id=semantic.source_snapshot.scope_id,
            store_id=quiescence.store_id,
            source_snapshot_digest=semantic.source_snapshot.snapshot_digest,
            semantic_digest=prepared.semantic_digest,
            desired_review_digest=desired.review_digest,
            history_join_digest=joined.review_digest,
            lease_owner_revision=quiescence.owner_revision,
            backup_topology_revision=backup_topology.owner_revision,
            repaired_runtime_leases=relevant_repairs,
            worker_backup_observations=backups,
            review_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
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
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker Package runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.read_snapshot_guard() as gc_snapshot:
            review, _, _ = _review_coding_windows_worker_package_references_under_guard(
                product,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
            )
        product.assert_root_gc_authority_current()
    return review


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

    if gc_snapshot.active:
        raise ValueError("Windows Worker GC reservation remains active")
    product.assert_root_gc_authority_current()
    source = _capture_coding_windows_worker_history_sources_under_gc_guard(
        product,
        store_id=quiescence.store_id,
        lease_owner_revision=quiescence.owner_revision,
        require_settled_history=True,
        allow_checkpoint_stage=allow_checkpoint_stage,
        allow_base_stage=allow_base_stage,
    )
    recovery = _inspect_coding_windows_product_worker_offline_recovery_under_gc_guard(
        product,
        store_id=quiescence.store_id,
        lease_owner_revision=quiescence.owner_revision,
        gc_snapshot=gc_snapshot,
    )
    desired_snapshot, desired_transitions, desired_digest = (
        _capture_coding_windows_worker_desired_history_under_gc_guard(product)
    )
    if source != _capture_coding_windows_worker_history_sources_under_gc_guard(
        product,
        store_id=quiescence.store_id,
        lease_owner_revision=quiescence.owner_revision,
        require_settled_history=False,
        allow_checkpoint_stage=allow_checkpoint_stage,
        allow_base_stage=allow_base_stage,
    ):
        raise ValueError("Windows Worker history sources changed")
    semantic = CodingWindowsWorkerHistorySemanticReadV1(
        source_snapshot=source,
        offline_recovery=recovery,
        desired_inventory_revision=desired_snapshot.inventory_revision,
        desired_history_digest=desired_digest,
        desired_snapshot=desired_snapshot,
        desired_transitions=desired_transitions,
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    backup_topology = observe_coding_worker_backup_references_under_gc_guard(
        product, attempt_id="0" * 32
    )
    review = CodingWindowsWorkerPackageReferenceReviewV1.from_guarded_read(
        prepared,
        semantic,
        quiescence=quiescence,
        backup_topology=backup_topology,
    )
    product.assert_root_gc_authority_current()
    return review, prepared, semantic


__all__ = [
    "CodingWindowsWorkerPackageReferenceReviewV1",
    "review_coding_windows_worker_package_references",
]
