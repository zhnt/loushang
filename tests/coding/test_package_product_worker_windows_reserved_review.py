from __future__ import annotations

import json
from dataclasses import replace

import pytest

from loushang.coding.package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)
from loushang.coding.package_product_worker_windows_reserved_review import (
    CodingWindowsWorkerReservedNoEffectReviewV1,
    CodingWindowsWorkerReservedReviewError,
    _require_reserved_no_effect_candidate,
    _require_settled_no_effect_candidate,
)


def _intent() -> CodingWindowsWorkerLaunchIntentV1:
    return CodingWindowsWorkerLaunchIntentV1(
        attempt_id="5" * 32,
        stage_identity=(1, 10),
        receipt_fingerprint="a" * 64,
        request_fingerprint="b" * 64,
        identity_fingerprint="c" * 64,
        runtime_fingerprint="d" * 64,
        payload_digest="e" * 64,
        owner_id="owner-1",
        supervisor_epoch=1,
    )


def _attempt(
    intent: CodingWindowsWorkerLaunchIntentV1,
) -> CodingWindowsWorkerRecoveryAttemptV1:
    return CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id=intent.attempt_id,
        payload_directory_identity=intent.stage_identity,
        native_phase="reserved",
        native_revision=1,
        native_phase_history=("reserved",),
        native_witness_present_history=(False,),
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


def _review() -> CodingWindowsWorkerReservedNoEffectReviewV1:
    return CodingWindowsWorkerReservedNoEffectReviewV1(
        attempt_id="5" * 32,
        intent_fingerprint="a" * 64,
        lease_owner_revision=10,
        native_revision=1,
        stage_identity=(1, 10, 1, 0, 100),
        directory_identities=(("worker", (1, 11, 1, 0, 101)),),
        marker_identity=(1, 12, 1, 200, 102),
        executable_identity=(1, 13, 1, 1024, 103),
        executable_digest="b" * 64,
        entrypoint="worker/query-worker",
    )


def test_windows_worker_reserved_review_roundtrips_exact_stage() -> None:
    review = _review()
    assert (
        CodingWindowsWorkerReservedNoEffectReviewV1.from_bytes(review.to_bytes())
        == review
    )
    assert len(review.fingerprint) == 64


@pytest.mark.parametrize(
    "changed",
    [
        {"nativeRevision": 3},
        {"stageIdentity": [1, 0, 1, 0, 100]},
        {"entrypoint": "other/query-worker"},
        {"directoryIdentities": []},
        {"foreign": True},
    ],
)
def test_windows_worker_reserved_review_rejects_changed_record(
    changed: dict[str, object],
) -> None:
    raw = json.dumps(
        {**json.loads(_review().to_bytes()), **changed},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with pytest.raises(CodingWindowsWorkerReservedReviewError):
        CodingWindowsWorkerReservedNoEffectReviewV1.from_bytes(raw)


def test_windows_worker_reserved_review_rejects_noncanonical_bytes() -> None:
    with pytest.raises(CodingWindowsWorkerReservedReviewError):
        CodingWindowsWorkerReservedNoEffectReviewV1.from_bytes(
            _review().to_bytes() + b" "
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"payload_directory_identity": None},
        {"native_phase": "profile_effect"},
        {"native_revision": 2},
        {"native_phase_history": ("profile_effect",)},
        {"native_witness_present_history": (True,)},
        {"supervisor_phase": "starting"},
        {"native_worker_request_fingerprint": "f" * 64},
        {"launch_stage_identity": (1, 11)},
    ],
)
def test_windows_worker_reserved_candidate_requires_no_effect_and_exact_join(
    changed: dict[str, object],
) -> None:
    intent = _intent()
    _require_reserved_no_effect_candidate(_attempt(intent), intent)
    with pytest.raises(
        CodingWindowsWorkerReservedReviewError,
        match="coding_worker_reserved_history_unverified",
    ):
        _require_reserved_no_effect_candidate(
            replace(_attempt(intent), **changed), intent
        )


def test_windows_worker_settled_unlaunched_requires_exact_no_effect_history() -> None:
    intent = _intent()
    settled = replace(
        _attempt(intent),
        native_phase="settled",
        native_revision=2,
        native_phase_history=("reserved", "settled"),
        native_witness_present_history=(False, False),
    )
    _require_settled_no_effect_candidate(settled, intent)
    for changed in (
        {"native_phase_history": ("profile_effect", "settled")},
        {"native_witness_present_history": (False, True)},
        {"native_revision": 3},
        {"supervisor_phase": "stopped"},
        {"payload_directory_identity": None},
    ):
        with pytest.raises(CodingWindowsWorkerReservedReviewError):
            _require_settled_no_effect_candidate(replace(settled, **changed), intent)
