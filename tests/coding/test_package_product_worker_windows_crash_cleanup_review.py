from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from loushang.coding.package_product_worker_windows_crash_cleanup_review import (
    _crash_settled_history_matches,
    _valid_crash_cleanup_history,
    _valid_crash_native_settlement_history,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)


def test_windows_crash_cleanup_requires_contiguous_effect_history() -> None:
    phases = (
        "reserved",
        "profile_effect",
        "profile_created",
        "grant_effect",
        "grants_applied",
        "verified",
        "active",
        "debt",
    )
    attempt = CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id="a" * 32,
        payload_directory_identity=(1, 2),
        native_phase="debt",
        native_revision=len(phases),
        supervisor_phase="healthy",
        supervisor_revision=3,
        supervisor_process_settled=False,
        native_phase_history=phases,
        native_witness_present_history=(False, False) + (True,) * 6,
    )
    assert _valid_crash_cleanup_history(attempt)
    assert _valid_crash_cleanup_history(
        replace(
            attempt,
            native_phase="cleaning",
            native_revision=3,
            native_phase_history=("reserved", "profile_effect", "cleaning"),
            native_witness_present_history=(False, False, True),
        )
    )
    assert _valid_crash_cleanup_history(
        replace(
            attempt,
            native_phase="revoke_effect",
            native_revision=len(phases) + 2,
            native_phase_history=phases + ("cleaning", "revoke_effect"),
            native_witness_present_history=(False, False) + (True,) * 8,
        )
    )
    for changed in (
        replace(attempt, native_phase_history=phases[:2] + phases[3:]),
        replace(
            attempt,
            native_witness_present_history=(False, False, False) + (True,) * 5,
        ),
        replace(attempt, native_revision=len(phases) + 1),
        replace(attempt, native_phase="settled"),
    ):
        assert not _valid_crash_cleanup_history(changed)


def test_windows_crash_native_settlement_requires_full_cleanup_tail() -> None:
    phases = (
        "reserved",
        "profile_effect",
        "cleaning",
        "revoke_effect",
        "grants_revoked",
        "delete_effect",
        "profile_deleted",
        "settled",
    )
    attempt = CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id="a" * 32,
        payload_directory_identity=(1, 2),
        native_phase="settled",
        native_revision=len(phases),
        supervisor_phase="process_settled",
        supervisor_revision=4,
        supervisor_process_settled=True,
        native_phase_history=phases,
        native_witness_present_history=(False, False) + (True,) * 6,
        native_witness_state="SETTLED",
    )
    assert _valid_crash_native_settlement_history(attempt)
    settled = replace(
        attempt,
        launch_request_fingerprint="b" * 64,
        launch_stage_identity=(1, 2),
        native_worker_request_fingerprint="b" * 64,
        launch_receipt_fingerprint="c" * 64,
        native_receipt_fingerprint="c" * 64,
        launch_identity_fingerprint="d" * 64,
        supervisor_identity_fingerprint="d" * 64,
    )
    review = SimpleNamespace(
        missing_proofs=(), attempt=settled, receipt_record=object()
    )
    assert _crash_settled_history_matches(review)
    assert _crash_settled_history_matches(
        SimpleNamespace(
            missing_proofs=("orphan_lease_absent",),
            attempt=settled,
            receipt_record=object(),
        ),
        repaired_lease=True,
    )
    assert not _crash_settled_history_matches(
        SimpleNamespace(
            missing_proofs=("orphan_lease_absent",),
            attempt=settled,
            receipt_record=object(),
        )
    )
    assert not _crash_settled_history_matches(
        SimpleNamespace(
            missing_proofs=(),
            attempt=replace(settled, supervisor_phase="stopped"),
            receipt_record=object(),
        )
    )
    assert not _crash_settled_history_matches(
        SimpleNamespace(
            missing_proofs=("native_job_present",),
            attempt=settled,
            receipt_record=object(),
        )
    )
    for changed in (
        replace(attempt, native_phase_history=phases[:3] + phases[4:]),
        replace(attempt, native_witness_state=None),
        replace(
            attempt,
            native_witness_present_history=(False, False, False) + (True,) * 5,
        ),
        replace(attempt, native_revision=len(phases) + 1),
    ):
        assert not _valid_crash_native_settlement_history(changed)
