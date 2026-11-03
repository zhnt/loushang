"""Package lease and backup inputs must be joined under one Product guard."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_product_backup_types import (
    CodingWorkerBackupReferenceObservationV1,
)
from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    _coding_windows_worker_desired_history_digest,
)
from loushang.coding.package_product_worker_windows_package_references import (
    CodingWindowsWorkerPackageReferenceReviewV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from tests.coding.test_package_product_worker_windows_desired_references import (
    _desired_capture,
)
from tests.coding.test_package_product_worker_windows_receipt_base import (
    _semantic_read,
)


def _inputs(tmp_path: Path):
    semantic = _semantic_read()
    receipt = semantic.offline_recovery.receipt_records[0].receipt
    snapshot, transitions = _desired_capture(
        tmp_path, artifact_digest=receipt.policy.plugin_revision_digest
    )
    semantic = replace(
        semantic,
        desired_inventory_revision=snapshot.inventory_revision,
        desired_history_digest=_coding_windows_worker_desired_history_digest(
            snapshot, transitions
        ),
        desired_snapshot=snapshot,
        desired_transitions=transitions,
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    quiescence = PackageWindowsRuntimeQuiescenceV1(
        store_id="store-a", owner_revision=4, active_runtime_lease_ids=()
    )
    topology = CodingWorkerBackupReferenceObservationV1(
        attempt_id="0" * 32,
        owner_revision="coding-product-backup-types:" + sha256(b"topology").hexdigest(),
        worker_backup_supported=False,
        references=(),
    )
    return prepared, semantic, quiescence, topology


def test_windows_package_reference_review_binds_desired_and_quiescent_lease(
    tmp_path: Path,
) -> None:
    prepared, semantic, quiescence, topology = _inputs(tmp_path)
    review = CodingWindowsWorkerPackageReferenceReviewV1.from_guarded_read(
        prepared, semantic, quiescence=quiescence, backup_topology=topology
    )
    assert review.lease_owner_revision == 4
    assert review.worker_backup_observations == ()
    assert review.repaired_runtime_leases == ()


def test_windows_package_reference_review_keeps_repaired_worker_lease(
    tmp_path: Path,
) -> None:
    prepared, semantic, quiescence, topology = _inputs(tmp_path)
    lease = PackageEpochRuntimeLeaseV1.create(
        runtime_id="runtime-a",
        runtime_epoch=1,
        store_root_identity=sha256(b"root").hexdigest(),
        registration_receipt_id=sha256(b"registration").hexdigest(),
    )
    record = PackageEpochRuntimeLeaseRecordV1(
        record_revision=3,
        store_id="store-a",
        kind="orphan_repaired",
        lease=lease,
    )
    review = CodingWindowsWorkerPackageReferenceReviewV1.from_guarded_read(
        prepared,
        semantic,
        quiescence=replace(quiescence, repaired_runtime_records=(record,)),
        backup_topology=topology,
    )
    assert review.repaired_runtime_leases == (("runtime-a", lease.lease_id, 3),)


def test_windows_package_reference_review_refuses_stale_or_active_lease(
    tmp_path: Path,
) -> None:
    prepared, semantic, quiescence, topology = _inputs(tmp_path)
    for changed in (
        replace(quiescence, owner_revision=5),
        replace(quiescence, active_runtime_lease_ids=("a" * 64,)),
    ):
        with pytest.raises(ValueError, match="closure changed"):
            CodingWindowsWorkerPackageReferenceReviewV1.from_guarded_read(
                prepared, semantic, quiescence=changed, backup_topology=topology
            )


def test_windows_package_reference_review_refuses_unmatched_backup_observation(
    tmp_path: Path,
) -> None:
    _, semantic, quiescence, topology = _inputs(tmp_path)
    observation = CodingWorkerBackupReferenceObservationV1(
        attempt_id="a" * 32,
        owner_revision="coding-product-backup-types:" + sha256(b"topology").hexdigest(),
        worker_backup_supported=False,
        references=(),
    )
    changed = replace(
        semantic,
        offline_recovery=replace(
            semantic.offline_recovery,
            worker_backup_observations=(observation,),
        ),
    )
    with pytest.raises(ValueError, match="backup references are not closed"):
        CodingWindowsWorkerPackageReferenceReviewV1.from_guarded_read(
            CodingWindowsWorkerHistoryPreparationV1.create(changed),
            changed,
            quiescence=quiescence,
            backup_topology=topology,
        )
