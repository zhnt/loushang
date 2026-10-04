from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.coding.package_product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAdmissionError,
    CodingWindowsWorkerRecoveryAttemptV1,
    require_coding_windows_worker_current_attempt,
)

_ATTEMPT = "7" * 32
_STAGE = (13, 37)
_REQUEST = "a" * 64
_RECEIPT = "b" * 64
_IDENTITY = "c" * 64


def test_windows_worker_orphan_review_never_infers_job_absence() -> None:
    review = CodingWindowsWorkerOrphanRuntimeReviewV1(
        attempt_id=_ATTEMPT,
        attempt=None,
        receipt_record=None,
        orphan_leases=(),
        runtime_epoch=1,
        store_root_identity="a" * 64,
    )
    assert review.missing_proofs == (
        "attempt_history_absent",
        "activation_receipt_absent",
        "orphan_lease_absent",
        "native_job_absence_unverified",
    )


def test_windows_worker_orphan_review_distinguishes_observed_job_state() -> None:
    attempt = replace(
        _candidate(), native_job_name="Global\\LoushangWorker-" + "a" * 64
    )
    review = CodingWindowsWorkerOrphanRuntimeReviewV1(
        attempt_id=_ATTEMPT,
        attempt=attempt,
        receipt_record=None,
        orphan_leases=(),
        runtime_epoch=1,
        store_root_identity="a" * 64,
        native_job_absent=True,
    )
    assert "native_job_absence_unverified" not in review.missing_proofs
    assert "native_job_present" not in review.missing_proofs
    present = replace(review, native_job_absent=False)
    assert "native_job_present" in present.missing_proofs
    assert "native_job_absence_unverified" not in present.missing_proofs


def _candidate() -> CodingWindowsWorkerRecoveryAttemptV1:
    return CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id=_ATTEMPT,
        payload_directory_identity=_STAGE,
        native_phase=None,
        native_revision=None,
        supervisor_phase=None,
        supervisor_revision=None,
        supervisor_process_settled=None,
    )


def test_windows_worker_clean_exit_repair_requires_complete_native_history() -> None:
    phases = (
        "reserved", "profile_effect", "profile_created", "grant_effect",
        "grants_applied", "verified", "active", "cleaning", "revoke_effect",
        "grants_revoked", "delete_effect", "profile_deleted", "settled",
    )
    settled = replace(
        _candidate(),
        native_phase="settled",
        native_revision=len(phases),
        native_phase_history=phases,
        native_witness_present_history=(False, False) + (True,) * (len(phases) - 2),
        native_witness_state="SETTLED",
        native_worker_request_fingerprint=_REQUEST,
        native_receipt_fingerprint=_RECEIPT,
        supervisor_phase="stopped",
        supervisor_revision=4,
        supervisor_process_settled=True,
        supervisor_identity_fingerprint=_IDENTITY,
        launch_request_fingerprint=_REQUEST,
        launch_receipt_fingerprint=_RECEIPT,
        launch_identity_fingerprint=_IDENTITY,
        launch_stage_identity=_STAGE,
    )
    assert settled.clean_exit_settled
    assert not replace(settled, native_witness_state="DEBT").clean_exit_settled
    assert not replace(settled, native_phase_history=phases[:7] + ("settled",)).clean_exit_settled
    assert not replace(
        settled,
        native_phase_history=phases[:8] + ("debt",) + phases[8:],
        native_revision=len(phases) + 1,
    ).clean_exit_settled
    assert not replace(settled, supervisor_process_settled=False).clean_exit_settled


def _require(*attempts: CodingWindowsWorkerRecoveryAttemptV1, initial: bool) -> None:
    require_coding_windows_worker_current_attempt(
        attempts,
        attempt_id=_ATTEMPT,
        payload_directory_identity=_STAGE,
        initial=initial,
        request_fingerprint=None if initial else _REQUEST,
        receipt_fingerprint=None if initial else _RECEIPT,
        identity_fingerprint=None if initial else _IDENTITY,
    )


def test_windows_worker_current_attempt_allows_only_fresh_then_inflight() -> None:
    fresh = _candidate()
    _require(fresh, initial=True)
    _require(fresh, initial=False)

    active = replace(
        fresh,
        native_phase="active",
        native_revision=8,
        native_worker_request_fingerprint=_REQUEST,
        native_receipt_fingerprint=_RECEIPT,
        supervisor_phase="healthy",
        supervisor_revision=4,
        supervisor_process_settled=False,
        supervisor_identity_fingerprint=_IDENTITY,
        launch_request_fingerprint=_REQUEST,
        launch_receipt_fingerprint=_RECEIPT,
        launch_identity_fingerprint=_IDENTITY,
        launch_stage_identity=_STAGE,
    )
    _require(active, initial=False)
    with pytest.raises(
        CodingWindowsWorkerRecoveryAdmissionError,
        match="coding_worker_payload_recovery_required",
    ):
        _require(active, initial=True)


@pytest.mark.parametrize(
    "attempts,initial",
    [
        ((), True),
        ((_candidate(), replace(_candidate(), attempt_id="8" * 32)), True),
        ((replace(_candidate(), payload_directory_identity=(13, 38)),), True),
        ((replace(_candidate(), launch_request_fingerprint=_REQUEST),), True),
        (
            (
                replace(
                    _candidate(),
                    native_phase="active",
                    native_worker_request_fingerprint=_REQUEST,
                    native_receipt_fingerprint=_RECEIPT,
                ),
            ),
            False,
        ),
        ((replace(_candidate(), native_phase="settled"),), False),
        (
            (
                replace(
                    _candidate(),
                    supervisor_phase="stopped",
                    supervisor_process_settled=True,
                ),
            ),
            False,
        ),
    ],
)
def test_windows_worker_current_attempt_refuses_replay_and_foreign_debt(
    attempts: tuple[CodingWindowsWorkerRecoveryAttemptV1, ...], initial: bool
) -> None:
    with pytest.raises(
        CodingWindowsWorkerRecoveryAdmissionError,
        match="coding_worker_payload_recovery_required",
    ):
        _require(*attempts, initial=initial)


@pytest.mark.parametrize(
    "changed",
    [
        {"native_worker_request_fingerprint": "d" * 64},
        {"native_receipt_fingerprint": "d" * 64},
        {"supervisor_identity_fingerprint": "d" * 64},
        {"launch_request_fingerprint": "d" * 64},
        {"launch_receipt_fingerprint": "d" * 64},
        {"launch_identity_fingerprint": "d" * 64},
        {"launch_stage_identity": (13, 38)},
    ],
)
def test_windows_worker_current_attempt_refuses_cross_owner_identity_mismatch(
    changed: dict[str, object],
) -> None:
    active = replace(
        _candidate(),
        native_phase="active",
        native_revision=8,
        native_worker_request_fingerprint=_REQUEST,
        native_receipt_fingerprint=_RECEIPT,
        supervisor_phase="healthy",
        supervisor_revision=4,
        supervisor_process_settled=False,
        supervisor_identity_fingerprint=_IDENTITY,
        launch_request_fingerprint=_REQUEST,
        launch_receipt_fingerprint=_RECEIPT,
        launch_identity_fingerprint=_IDENTITY,
        launch_stage_identity=_STAGE,
    )
    with pytest.raises(
        CodingWindowsWorkerRecoveryAdmissionError,
        match="coding_worker_payload_recovery_required",
    ):
        _require(replace(active, **changed), initial=False)


def test_windows_worker_recovery_inventory_names_cross_owner_conflicts() -> None:
    matching = replace(
        _candidate(),
        native_phase="settled",
        native_revision=8,
        native_worker_request_fingerprint=_REQUEST,
        native_receipt_fingerprint=_RECEIPT,
        supervisor_phase="stopped",
        supervisor_revision=4,
        supervisor_process_settled=True,
        supervisor_identity_fingerprint=_IDENTITY,
        launch_request_fingerprint=_REQUEST,
        launch_receipt_fingerprint=_RECEIPT,
        launch_identity_fingerprint=_IDENTITY,
        launch_stage_identity=_STAGE,
    )
    assert matching.observed_debts == (
        "payload_retained",
        "launch_intent_retained",
    )
    changed = replace(
        matching,
        native_receipt_fingerprint="d" * 64,
        supervisor_identity_fingerprint="e" * 64,
        launch_stage_identity=(13, 38),
    )
    assert changed.observed_debts == (
        "payload_retained",
        "launch_intent_retained",
        "launch_stage_mismatch",
        "native_launch_identity_mismatch",
        "supervisor_launch_identity_mismatch",
    )
