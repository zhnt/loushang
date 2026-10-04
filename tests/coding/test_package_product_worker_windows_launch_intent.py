from __future__ import annotations

import json

import pytest

from loushang.coding.package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentError,
    CodingWindowsWorkerLaunchIntentV1,
)


def _intent() -> CodingWindowsWorkerLaunchIntentV1:
    return CodingWindowsWorkerLaunchIntentV1(
        attempt_id="7" * 32,
        stage_identity=(13, 37),
        receipt_fingerprint="a" * 64,
        request_fingerprint="b" * 64,
        identity_fingerprint="c" * 64,
        runtime_fingerprint="d" * 64,
        payload_digest="e" * 64,
        owner_id="coding.worker.query",
        supervisor_epoch=1,
    )


def test_windows_worker_launch_intent_roundtrips_canonical_identity() -> None:
    intent = _intent()
    assert CodingWindowsWorkerLaunchIntentV1.from_bytes(intent.to_bytes()) == intent
    assert len(intent.fingerprint) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"requestFingerprint": "f" * 63},
        {"stageIdentity": [13, -1]},
        {"intentVersion": 2},
        {"unrecognized": True},
    ],
)
def test_windows_worker_launch_intent_rejects_changed_or_foreign_fields(
    change: dict[str, object],
) -> None:
    document = {**_intent().to_dict(), **change}
    with pytest.raises(
        CodingWindowsWorkerLaunchIntentError,
        match="coding_worker_launch_intent_invalid",
    ):
        CodingWindowsWorkerLaunchIntentV1.from_bytes(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        )


def test_windows_worker_launch_intent_rejects_noncanonical_or_duplicate_bytes() -> None:
    raw = _intent().to_bytes()
    for changed in (raw + b" ", raw[:-1] + b',"attemptId":"' + b"7" * 32 + b'"}'):
        with pytest.raises(CodingWindowsWorkerLaunchIntentError):
            CodingWindowsWorkerLaunchIntentV1.from_bytes(changed)
