from __future__ import annotations

import json
from dataclasses import replace

import pytest

from loushang.coding.package_product_worker_windows_partial_stage_review import (
    CodingWindowsWorkerPartialStageReviewError,
    CodingWindowsWorkerPartialStageReviewV1,
)


def _review() -> CodingWindowsWorkerPartialStageReviewV1:
    return CodingWindowsWorkerPartialStageReviewV1(
        attempt_id="8" * 32,
        lease_owner_revision=13,
        stage_identity=(1, 10, 1, 0, 100),
        directory_identities=(
            ("worker", (1, 11, 1, 0, 101)),
            ("worker/bin", (1, 12, 1, 0, 102)),
        ),
        entrypoint="worker/bin/query-worker",
        executable_identity=(1, 13, 1, 1024, 103),
        executable_digest="a" * 64,
    )


def test_windows_worker_partial_stage_review_roundtrips_full_and_empty_tree() -> None:
    full = _review()
    empty = replace(
        full,
        directory_identities=(),
        entrypoint=None,
        executable_identity=None,
        executable_digest=None,
    )
    for review in (full, empty):
        assert (
            CodingWindowsWorkerPartialStageReviewV1.from_bytes(review.to_bytes())
            == review
        )
        assert len(review.fingerprint) == 64


@pytest.mark.parametrize(
    "changed",
    [
        {"directoryIdentities": [["worker/bin", [1, 11, 1, 0, 101]]]},
        {"entrypoint": "worker/other/query-worker"},
        {"executableIdentity": [1, 13, 2, 1024, 103]},
        {"executableDigest": "invalid"},
        {"leaseOwnerRevision": 0},
        {"foreign": True},
    ],
)
def test_windows_worker_partial_stage_review_rejects_changed_inputs(
    changed: dict[str, object],
) -> None:
    raw = json.dumps(
        {**json.loads(_review().to_bytes()), **changed},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with pytest.raises(
        CodingWindowsWorkerPartialStageReviewError,
        match="coding_worker_partial_stage_review_invalid",
    ):
        CodingWindowsWorkerPartialStageReviewV1.from_bytes(raw)


def test_windows_worker_partial_stage_review_rejects_noncanonical_record() -> None:
    with pytest.raises(CodingWindowsWorkerPartialStageReviewError):
        CodingWindowsWorkerPartialStageReviewV1.from_bytes(_review().to_bytes() + b" ")
