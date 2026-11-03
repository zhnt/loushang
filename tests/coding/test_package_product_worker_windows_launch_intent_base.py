"""Windows Worker launch-intent cutover preserves exact old attempt IDs."""

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
from loushang.coding.package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
)
from loushang.coding.package_product_worker_windows_launch_intent_base import (
    CodingWindowsWorkerLaunchIntentSemanticBaseV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerOfflineRecoverySnapshotV1,
    CodingWindowsWorkerRecoveryAttemptV1,
)

_ATTEMPT = "a" * 32
_DIGEST = sha256(b"identity").hexdigest()


def _intent(attempt_id: str = _ATTEMPT) -> CodingWindowsWorkerLaunchIntentV1:
    return CodingWindowsWorkerLaunchIntentV1(
        attempt_id=attempt_id,
        stage_identity=(1, 2),
        receipt_fingerprint=_DIGEST,
        request_fingerprint=_DIGEST,
        identity_fingerprint=_DIGEST,
        runtime_fingerprint=_DIGEST,
        payload_digest=_DIGEST,
        owner_id="coding",
        supervisor_epoch=1,
    )


def _semantic_read() -> CodingWindowsWorkerHistorySemanticReadV1:
    intent = _intent()
    name = f"worker-launch-intent-{_ATTEMPT}.json"
    source = CodingWindowsWorkerHistorySourceSnapshotV1.create(
        scope_id="scope-a",
        store_id="store-a",
        lease_owner_revision=3,
        files=(
            CodingWindowsWorkerHistorySourceFileV1(
                name=name,
                size=len(intent.to_bytes()),
                sha256_digest=sha256(intent.to_bytes()).hexdigest(),
            ),
        ),
    )
    recovery = CodingWindowsWorkerOfflineRecoverySnapshotV1(
        store_id="store-a",
        lease_owner_revision=3,
        attempts=(
            CodingWindowsWorkerRecoveryAttemptV1(
                attempt_id=_ATTEMPT,
                payload_directory_identity=(1, 2),
                native_phase=None,
                native_revision=None,
                supervisor_phase=None,
                supervisor_revision=None,
                supervisor_process_settled=None,
                launch_request_fingerprint=intent.request_fingerprint,
                launch_receipt_fingerprint=intent.receipt_fingerprint,
                launch_identity_fingerprint=intent.identity_fingerprint,
                launch_stage_identity=intent.stage_identity,
            ),
        ),
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
        launch_intents=(intent,),
    )
    return CodingWindowsWorkerHistorySemanticReadV1(
        source_snapshot=source, offline_recovery=recovery
    )


def test_windows_launch_intent_base_keeps_source_and_old_id() -> None:
    semantic = _semantic_read()
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    base = CodingWindowsWorkerLaunchIntentSemanticBaseV1.from_semantic_read(
        prepared, semantic
    )
    assert base.intent_attempt_ids == (_ATTEMPT,)
    assert base.retained_intents == semantic.offline_recovery.launch_intents
    assert (
        CodingWindowsWorkerLaunchIntentSemanticBaseV1.from_bytes(base.to_bytes())
        == base
    )
    with pytest.raises(ValueError, match="retained replay is invalid"):
        base.replay((_intent(),))
    assert base.replay((_intent("b" * 32),)).attempt_ids == frozenset(
        {_ATTEMPT, "b" * 32}
    )


def test_windows_launch_intent_base_refuses_changed_source_and_join() -> None:
    semantic = _semantic_read()
    original_preparation = CodingWindowsWorkerHistoryPreparationV1.create(semantic)
    without_intent = replace(
        semantic,
        offline_recovery=replace(semantic.offline_recovery, launch_intents=()),
    )
    with pytest.raises(ValueError, match="semantic read changed"):
        original_preparation.require_semantic_read(without_intent)
    source_file = semantic.source_snapshot.files[0]
    changed_source = replace(
        semantic,
        source_snapshot=CodingWindowsWorkerHistorySourceSnapshotV1.create(
            scope_id="scope-a",
            store_id="store-a",
            lease_owner_revision=3,
            files=(replace(source_file, sha256_digest=sha256(b"changed").hexdigest()),),
        ),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(changed_source)
    with pytest.raises(ValueError, match="source changed"):
        CodingWindowsWorkerLaunchIntentSemanticBaseV1.from_semantic_read(
            prepared, changed_source
        )
    no_join = replace(
        semantic,
        offline_recovery=replace(semantic.offline_recovery, attempts=()),
    )
    prepared = CodingWindowsWorkerHistoryPreparationV1.create(no_join)
    with pytest.raises(ValueError, match="recovery join is invalid"):
        CodingWindowsWorkerLaunchIntentSemanticBaseV1.from_semantic_read(
            prepared, no_join
        )
