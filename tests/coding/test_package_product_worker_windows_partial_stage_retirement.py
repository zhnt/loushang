from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.coding import (
    package_product_worker_windows_partial_stage_retirement as retirement,
)
from loushang.coding.package_product_worker_windows_partial_stage_review import (
    CodingWindowsWorkerPartialStageReviewV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)
from loushang.coding.package_product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementReceiptV1,
)


def _review() -> CodingWindowsWorkerPartialStageReviewV1:
    return CodingWindowsWorkerPartialStageReviewV1(
        attempt_id="8" * 32,
        lease_owner_revision=11,
        stage_identity=(1, 10, 1, 0, 100),
        directory_identities=(),
        entrypoint=None,
        executable_identity=None,
        executable_digest=None,
    )


def test_windows_worker_partial_retirement_requires_all_exact_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = _review()
    receipt = CodingWindowsWorkerStageRetirementReceiptV1(
        attempt_id=review.attempt_id,
        review_fingerprint=review.fingerprint,
        stage_identity=review.stage_identity[:2],
    )
    attempt = CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id=review.attempt_id,
        payload_directory_identity=None,
        native_phase=None,
        native_revision=None,
        supervisor_phase=None,
        supervisor_revision=None,
        supervisor_process_settled=None,
    )
    monkeypatch.setattr(retirement, "_read_start", lambda *_: review)
    monkeypatch.setattr(retirement, "_read_receipt", lambda *_: receipt)
    monkeypatch.setattr(retirement, "_read_root_intent", lambda *_: receipt)
    monkeypatch.setattr(
        retirement, "_full_retirement_artifact_present", lambda *_: False
    )
    retirement._require_completed_partial_retirement_under_gc_guard(  # type: ignore[arg-type]
        None, attempt
    )

    for changed in (
        replace(attempt, payload_directory_identity=review.stage_identity[:2]),
        replace(attempt, native_phase="reserved"),
    ):
        with pytest.raises(
            retirement.CodingWindowsWorkerPartialStageRetirementError,
            match="coding_worker_partial_retirement_history_unverified",
        ):
            retirement._require_completed_partial_retirement_under_gc_guard(  # type: ignore[arg-type]
                None, changed
            )
    monkeypatch.setattr(retirement, "_read_root_intent", lambda *_: None)
    with pytest.raises(retirement.CodingWindowsWorkerPartialStageRetirementError):
        retirement._require_completed_partial_retirement_under_gc_guard(  # type: ignore[arg-type]
            None, attempt
        )
