"""The Windows cutover review keeps six typed bases on one source read."""

from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.coding.package_product_worker_windows_history_join import (
    CodingWindowsWorkerHistorySemanticJoinV1,
)
from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerOfflineRecoverySnapshotV1,
    CodingWindowsWorkerRecoveryAttemptV1,
)


def _empty_read() -> CodingWindowsWorkerHistorySemanticReadV1:
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id="scope-a", store_id="store-a", lease_owner_revision=1, files=()
    )
    recovery = CodingWindowsWorkerOfflineRecoverySnapshotV1(
        store_id="store-a",
        lease_owner_revision=1,
        attempts=(),
        opt_in_decisions=(),
        receipt_records=(),
        supervisor_records=(),
        activation_state_owner_present=False,
        activation_state_revision=0,
        retained_activation_attempts=(),
        native_job_absence=(),
        gc_reservation_revision=0,
        gc_revision_refs=frozenset(),
        worker_backup_observations=(),
    )
    return CodingWindowsWorkerHistorySemanticReadV1(
        source_snapshot=source, offline_recovery=recovery
    )


def _unlaunched_attempt() -> CodingWindowsWorkerRecoveryAttemptV1:
    return CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id="a" * 32,
        payload_directory_identity=None,
        native_phase=None,
        native_revision=None,
        supervisor_phase=None,
        supervisor_revision=None,
        supervisor_process_settled=None,
    )


def test_windows_history_join_binds_empty_bases_and_observed_old_id() -> None:
    semantic = _empty_read()
    unlaunched = replace(
        semantic,
        offline_recovery=replace(
            semantic.offline_recovery, attempts=(_unlaunched_attempt(),)
        ),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(unlaunched)
    joined = CodingWindowsWorkerHistorySemanticJoinV1.from_semantic_read(
        prepared, unlaunched
    )
    assert joined.observed_attempt_ids == ("a" * 32,)
    assert joined.launched_attempt_ids == ()
    assert joined.source_snapshot_digest == unlaunched.source_snapshot.snapshot_digest
    with pytest.raises(ValueError, match="semantic join is invalid"):
        replace(joined, launched_attempt_ids=("a" * 32,))


def test_windows_history_join_refuses_duplicate_attempt_or_stale_preparation() -> None:
    semantic = _empty_read()
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    duplicate = replace(
        semantic,
        offline_recovery=replace(
            semantic.offline_recovery,
            attempts=(_unlaunched_attempt(), _unlaunched_attempt()),
        ),
    )
    with pytest.raises(ValueError, match="semantic read changed"):
        CodingWindowsWorkerHistorySemanticJoinV1.from_semantic_read(prepared, duplicate)
    with pytest.raises(ValueError, match="attempt inventory is invalid"):
        CodingWindowsWorkerHistorySemanticJoinV1.from_semantic_read(
            CodingWindowsWorkerHistoryPreparationV1.create(duplicate), duplicate
        )
