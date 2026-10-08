from __future__ import annotations

import json

import pytest

from loushang.coding.package_product_worker_windows_stage_review import (
    CodingWindowsWorkerStageReviewError,
    CodingWindowsWorkerStageReviewV1,
)


def _review() -> CodingWindowsWorkerStageReviewV1:
    return CodingWindowsWorkerStageReviewV1(
        attempt_id="7" * 32,
        intent_fingerprint="a" * 64,
        lease_owner_revision=13,
        native_revision=8,
        supervisor_revision=4,
        entrypoint="worker/bin/query-worker",
        stage_identity=(1, 10, 1, 0, 100),
        directory_identities=(
            ("worker", (1, 11, 1, 0, 101)),
            ("worker/bin", (1, 12, 1, 0, 102)),
        ),
        marker_identity=(1, 13, 1, 300, 103),
        executable_identity=(1, 14, 1, 2048, 104),
        executable_digest="b" * 64,
    )


def test_windows_worker_stage_review_roundtrips_exact_retirement_input() -> None:
    review = _review()
    assert CodingWindowsWorkerStageReviewV1.from_bytes(review.to_bytes()) == review
    assert len(review.fingerprint) == 64


@pytest.mark.parametrize(
    "changed",
    [
        {"directoryIdentities": [["worker", [1, 11, 1, 0, 101]]]},
        {"executableIdentity": [1, 14, 2, 2048, 104]},
        {"supervisorRevision": 0},
        {"foreign": True},
    ],
)
def test_windows_worker_stage_review_rejects_changed_retirement_input(
    changed: dict[str, object],
) -> None:
    raw = json.dumps(
        {**_review().to_dict(), **changed}, sort_keys=True, separators=(",", ":")
    ).encode()
    with pytest.raises(
        CodingWindowsWorkerStageReviewError,
        match="coding_worker_stage_review_record_invalid",
    ):
        CodingWindowsWorkerStageReviewV1.from_bytes(raw)


def test_windows_worker_stage_review_rejects_noncanonical_bytes() -> None:
    with pytest.raises(CodingWindowsWorkerStageReviewError):
        CodingWindowsWorkerStageReviewV1.from_bytes(_review().to_bytes() + b" ")
