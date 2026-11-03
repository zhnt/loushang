from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.coding.package_product_worker_windows_reserved_review import (
    CodingWindowsWorkerReservedNoEffectReviewV1,
)
from loushang.coding.package_product_worker_windows_reserved_settlement import (
    CodingWindowsWorkerReservedSettlementError,
    _settled_document,
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


def test_reserved_settlement_only_advances_no_effect_revision() -> None:
    current = {
        "attemptId": "5" * 32,
        "phase": "reserved",
        "stateRevision": 1,
        "witness": None,
        "workerRequestFingerprint": "c" * 64,
    }
    settled = _settled_document(current, expected_review=_review())
    assert settled == {
        **current,
        "phase": "settled",
        "stateRevision": 2,
    }
    assert current["phase"] == "reserved"


@pytest.mark.parametrize(
    "changed",
    [
        {"attemptId": "6" * 32},
        {"phase": "profile_effect"},
        {"phase": "settled"},
        {"stateRevision": 2},
        {"stateRevision": True},
        {"witness": {"state": "PROFILE_CREATED"}},
    ],
)
def test_reserved_settlement_rejects_changed_native_history(
    changed: dict[str, object],
) -> None:
    current = {
        "attemptId": "5" * 32,
        "phase": "reserved",
        "stateRevision": 1,
        "witness": None,
    }
    with pytest.raises(
        CodingWindowsWorkerReservedSettlementError,
        match="coding_worker_reserved_settlement_history_changed",
    ):
        _settled_document({**current, **changed}, expected_review=_review())


def test_reserved_settlement_rejects_different_review_attempt() -> None:
    current = {
        "attemptId": "5" * 32,
        "phase": "reserved",
        "stateRevision": 1,
        "witness": None,
    }
    with pytest.raises(CodingWindowsWorkerReservedSettlementError):
        _settled_document(
            current,
            expected_review=replace(_review(), attempt_id="6" * 32),
        )
