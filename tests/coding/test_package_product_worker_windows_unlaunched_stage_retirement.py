from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.coding import (
    package_product_worker_windows_unlaunched_stage_retirement as retirement,
)
from loushang.coding.package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)
from loushang.coding.package_product_worker_windows_reserved_review import (
    CodingWindowsWorkerReservedNoEffectReviewV1,
)
from loushang.coding.package_product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementReceiptV1,
    _retirement_attempt_ids_from_names,
)


def _history() -> tuple[
    CodingWindowsWorkerLaunchIntentV1,
    CodingWindowsWorkerReservedNoEffectReviewV1,
    CodingWindowsWorkerStageRetirementReceiptV1,
    CodingWindowsWorkerRecoveryAttemptV1,
]:
    intent = CodingWindowsWorkerLaunchIntentV1(
        attempt_id="a" * 32,
        stage_identity=(1, 10),
        receipt_fingerprint="b" * 64,
        request_fingerprint="c" * 64,
        identity_fingerprint="d" * 64,
        runtime_fingerprint="e" * 64,
        payload_digest="f" * 64,
        owner_id="owner-1",
        supervisor_epoch=1,
    )
    review = CodingWindowsWorkerReservedNoEffectReviewV1(
        attempt_id=intent.attempt_id,
        intent_fingerprint=intent.fingerprint,
        lease_owner_revision=3,
        native_revision=2,
        stage_identity=(1, 10, 1, 0, 100),
        directory_identities=(),
        marker_identity=(1, 11, 1, 200, 101),
        executable_identity=(1, 12, 1, 1024, 102),
        executable_digest=intent.payload_digest,
        entrypoint="worker.exe",
    )
    receipt = CodingWindowsWorkerStageRetirementReceiptV1(
        attempt_id=intent.attempt_id,
        review_fingerprint=review.fingerprint,
        stage_identity=intent.stage_identity,
    )
    attempt = CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id=intent.attempt_id,
        payload_directory_identity=None,
        native_phase="settled",
        native_revision=2,
        native_phase_history=("reserved", "settled"),
        native_witness_present_history=(False, False),
        supervisor_phase=None,
        supervisor_revision=None,
        supervisor_process_settled=None,
        native_worker_request_fingerprint=intent.request_fingerprint,
        native_receipt_fingerprint=intent.receipt_fingerprint,
        launch_request_fingerprint=intent.request_fingerprint,
        launch_receipt_fingerprint=intent.receipt_fingerprint,
        launch_identity_fingerprint=intent.identity_fingerprint,
        launch_stage_identity=intent.stage_identity,
    )
    return intent, review, receipt, attempt


def test_unlaunched_retirement_inventory_keeps_partial_publications() -> None:
    attempt_id = "a" * 32
    assert _retirement_attempt_ids_from_names(
        (
            f"worker-unlaunched-stage-retire-{attempt_id}.json.stage",
            f"worker-unlaunched-stage-root-delete-{attempt_id}.json",
            f"worker-unlaunched-stage-retired-{attempt_id}.json",
        )
    ) == frozenset({attempt_id})


def test_completed_unlaunched_retirement_requires_exact_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent, review, receipt, attempt = _history()
    monkeypatch.setattr(retirement, "_read_start", lambda *_: review)
    monkeypatch.setattr(retirement, "_read_receipt", lambda *_: receipt)
    monkeypatch.setattr(retirement, "_read_root_intent", lambda *_: receipt)
    monkeypatch.setattr(retirement, "_read_intent_under_gc_guard", lambda *_: intent)
    monkeypatch.setattr(
        retirement, "_other_retirement_artifact_present", lambda *_: False
    )
    retirement._require_completed_unlaunched_retirement_under_gc_guard(
        None,
        attempt,  # type: ignore[arg-type]
    )
    for changed in (
        {"native_phase_history": ("profile_effect", "settled")},
        {"native_witness_present_history": (False, True)},
        {"native_revision": 3},
        {"supervisor_phase": "stopped"},
        {"native_receipt_fingerprint": "0" * 64},
        {"payload_directory_identity": intent.stage_identity},
    ):
        with pytest.raises(retirement.CodingWindowsWorkerUnlaunchedRetirementError):
            retirement._require_completed_unlaunched_retirement_under_gc_guard(
                None,
                replace(attempt, **changed),  # type: ignore[arg-type]
            )
    monkeypatch.setattr(retirement, "_read_root_intent", lambda *_: None)
    with pytest.raises(retirement.CodingWindowsWorkerUnlaunchedRetirementError):
        retirement._require_completed_unlaunched_retirement_under_gc_guard(
            None,
            attempt,  # type: ignore[arg-type]
        )
