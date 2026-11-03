"""Windows Worker Supervisor cutover keeps old attempts and epoch continuity."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.coding.package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from loushang.coding.package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySourceFileV1,
    CodingWindowsWorkerHistorySourceSnapshotV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerOfflineRecoverySnapshotV1,
)
from loushang.coding.package_product_worker_windows_supervisor_base import (
    CodingWindowsWorkerSupervisorSemanticBaseV1,
)
from loushang.harness.worker.journal import WorkerAttemptPhase, WorkerAttemptRecordV1

_KEY = sha256(b"supervisor-key").hexdigest()
_IDENTITY = sha256(b"identity").hexdigest()
_ATTEMPT_1 = "1" * 32
_ATTEMPT_2 = "2" * 32


def _record(
    *,
    attempt_id: str,
    epoch: int,
    phase: WorkerAttemptPhase,
    revision: int,
    prior: int,
    restart: int,
) -> WorkerAttemptRecordV1:
    return WorkerAttemptRecordV1(
        supervisor_key=_KEY,
        identity_fingerprint=_IDENTITY,
        attempt_id=attempt_id,
        supervisor_epoch=epoch,
        phase=phase,
        record_revision=revision,
        prior_attempt_revision=prior,
        restart_ordinal=restart,
    )


def _semantic_read() -> CodingWindowsWorkerHistorySemanticReadV1:
    first = _record(
        attempt_id=_ATTEMPT_1,
        epoch=1,
        phase="claimed",
        revision=1,
        prior=0,
        restart=1,
    )
    stopped = (
        first,
        _record(
            attempt_id=_ATTEMPT_1,
            epoch=1,
            phase="launching",
            revision=2,
            prior=1,
            restart=1,
        ),
        _record(
            attempt_id=_ATTEMPT_1,
            epoch=1,
            phase="handshaking",
            revision=3,
            prior=2,
            restart=1,
        ),
        _record(
            attempt_id=_ATTEMPT_1,
            epoch=1,
            phase="healthy",
            revision=4,
            prior=3,
            restart=1,
        ),
        _record(
            attempt_id=_ATTEMPT_1,
            epoch=1,
            phase="draining",
            revision=5,
            prior=4,
            restart=1,
        ),
        _record(
            attempt_id=_ATTEMPT_1,
            epoch=1,
            phase="stopped",
            revision=6,
            prior=5,
            restart=1,
        ),
    )
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id="scope-a",
        store_id="store-a",
        lease_owner_revision=3,
        files=(
            CodingWindowsWorkerHistorySourceFileV1(
                name="worker-supervisor.jsonl",
                size=1,
                sha256_digest=sha256(b"source").hexdigest(),
            ),
        ),
    )
    recovery = CodingWindowsWorkerOfflineRecoverySnapshotV1(
        store_id="store-a",
        lease_owner_revision=3,
        attempts=(),
        opt_in_decisions=(),
        receipt_records=(),
        supervisor_records=stopped,
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


def test_supervisor_base_retains_attempt_identity_and_epoch() -> None:
    semantic = _semantic_read()
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    base = CodingWindowsWorkerSupervisorSemanticBaseV1.from_semantic_read(
        prepared, semantic
    )
    assert base.cutoff_revision == 6
    assert base.retired_attempt_ids == (_ATTEMPT_1,)
    assert base.latest_attempts == (semantic.offline_recovery.supervisor_records[-1],)
    assert (
        CodingWindowsWorkerSupervisorSemanticBaseV1.from_bytes(base.to_bytes()) == base
    )
    new = _record(
        attempt_id=_ATTEMPT_2,
        epoch=2,
        phase="claimed",
        revision=7,
        prior=0,
        restart=1,
    )
    replay = base.replay((new,))
    assert replay.last_revision == 7
    assert replay.latest_attempts == (
        semantic.offline_recovery.supervisor_records[-1],
        new,
    )
    launched = _record(
        attempt_id=_ATTEMPT_2,
        epoch=2,
        phase="launching",
        revision=8,
        prior=7,
        restart=1,
    )
    transitioned = base.replay((new, launched))
    assert transitioned.last_revision == 8
    assert transitioned.latest_attempts[-1] == launched
    assert transitioned.attempt_ids == frozenset({_ATTEMPT_1, _ATTEMPT_2})
    with pytest.raises(ValueError, match="retained replay is invalid"):
        base.replay((new, replace(launched, phase="healthy")))
    with pytest.raises(ValueError, match="retained replay is invalid"):
        base.replay((new, replace(launched, prior_attempt_revision=6)))
    with pytest.raises(ValueError, match="retained replay is invalid"):
        base.replay((replace(new, attempt_id=_ATTEMPT_1),))
    with pytest.raises(ValueError, match="retained replay is invalid"):
        base.replay((replace(new, supervisor_epoch=1),))
    with pytest.raises(ValueError, match="retained replay is invalid"):
        base.replay((replace(new, record_revision=8),))


def test_supervisor_base_refuses_missing_source() -> None:
    semantic = _semantic_read()
    changed = replace(
        semantic,
        source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.create(
            scope_id="scope-a",
            store_id="store-a",
            lease_owner_revision=3,
            files=(),
        ),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(changed)
    with pytest.raises(ValueError, match="source is absent"):
        CodingWindowsWorkerSupervisorSemanticBaseV1.from_semantic_read(
            prepared, changed
        )
