from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.coding import (
    package_product_worker_windows_stage_retirement as retirement,
)
from loushang.coding.package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
)
from loushang.coding.package_product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementError,
    CodingWindowsWorkerStageRetirementReceiptV1,
)
from loushang.coding.package_product_worker_windows_stage_review import (
    CodingWindowsWorkerStageReviewV1,
)


def _receipt() -> CodingWindowsWorkerStageRetirementReceiptV1:
    return CodingWindowsWorkerStageRetirementReceiptV1(
        attempt_id="7" * 32,
        review_fingerprint="a" * 64,
        stage_identity=(1, 10),
    )


@pytest.mark.parametrize("directory", (False, True))
def test_stage_retirement_bridges_exact_identity_to_native_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory: bool
) -> None:
    member = tmp_path / "member"
    if directory:
        member.mkdir()
    else:
        member.write_bytes(b"payload")
    descriptor = os.open(member, os.O_RDONLY)
    try:
        metadata = os.fstat(descriptor)
        expected = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
        calls: list[tuple[int, tuple[int, int, int, int, int], bool]] = []

        def capture(
            value: int, *, expected_identity: tuple[int, int, int, int, int], directory: bool
        ) -> None:
            calls.append((value, expected_identity, directory))

        monkeypatch.setattr(retirement, "windows_delete_open_entry", capture)
        retirement._delete_open_stage_entry(
            descriptor, expected=expected, directory=directory
        )
        assert calls == [
            (
                descriptor,
                (
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_mode,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                ),
                directory,
            )
        ]
        with pytest.raises(
            CodingWindowsWorkerStageRetirementError, match="file_changed"
        ):
            retirement._delete_open_stage_entry(
                descriptor,
                expected=(expected[0], expected[1] + 1, *expected[2:]),
                directory=directory,
            )
        assert len(calls) == 1
    finally:
        os.close(descriptor)


def test_windows_worker_stage_retirement_receipt_is_exact() -> None:
    receipt = _receipt()
    assert (
        CodingWindowsWorkerStageRetirementReceiptV1.from_bytes(receipt.to_bytes())
        == receipt
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"attemptId": "invalid"},
        {"reviewFingerprint": "invalid"},
        {"stageIdentity": [1, -1]},
        {"stageIdentity": [1, 0]},
        {"receiptVersion": 2},
        {"foreign": True},
    ],
)
def test_windows_worker_stage_retirement_refuses_changed_receipts(
    changed: dict[str, object],
) -> None:
    raw = json.dumps(
        {**json.loads(_receipt().to_bytes()), **changed},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with pytest.raises(CodingWindowsWorkerStageRetirementError):
        CodingWindowsWorkerStageRetirementReceiptV1.from_bytes(raw)


def test_windows_worker_stage_retirement_refuses_noncanonical_receipt() -> None:
    with pytest.raises(CodingWindowsWorkerStageRetirementError):
        CodingWindowsWorkerStageRetirementReceiptV1.from_bytes(
            _receipt().to_bytes() + b" "
        )


def test_windows_worker_retirement_inventory_counts_orphaned_receipts() -> None:
    attempt = "7" * 32
    assert retirement._retirement_attempt_ids_from_names(
        (
            "unrelated-product.json",
            f"worker-stage-retire-{attempt}.json",
            f"worker-stage-root-delete-{attempt}.json.stage",
            f"worker-stage-retired-{attempt}.json",
            f"worker-partial-stage-retire-{attempt}.json",
            f"worker-crash-stage-retire-{attempt}.json",
            f"worker-crash-stage-root-delete-{attempt}.json.stage",
            f"worker-crash-stage-retired-{attempt}.json",
        )
    ) == frozenset({attempt})


@pytest.mark.parametrize(
    "name",
    [
        "worker-stage-retired-foreign.json",
        f"worker-stage-retired-{'7' * 32}.json.bak",
        f"Worker-stage-retired-{'7' * 32}.json",
        f"worker-partial-stage-retired-{'7' * 32}.json.bak",
        f"worker-crash-stage-retired-{'7' * 32}.json.bak",
    ],
)
def test_windows_worker_retirement_inventory_rejects_foreign_names(name: str) -> None:
    with pytest.raises(
        CodingWindowsWorkerStageRetirementError,
        match="coding_worker_stage_retirement_artifact_invalid",
    ):
        retirement._retirement_attempt_ids_from_names((name,))


def test_windows_worker_retired_history_requires_all_owner_fingerprints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = CodingWindowsWorkerLaunchIntentV1(
        attempt_id="7" * 32,
        stage_identity=(1, 10),
        receipt_fingerprint="b" * 64,
        request_fingerprint="c" * 64,
        identity_fingerprint="d" * 64,
        runtime_fingerprint="e" * 64,
        payload_digest="f" * 64,
        owner_id="owner-1",
        supervisor_epoch=1,
    )
    review = CodingWindowsWorkerStageReviewV1(
        attempt_id=intent.attempt_id,
        intent_fingerprint=intent.fingerprint,
        lease_owner_revision=3,
        native_revision=4,
        supervisor_revision=5,
        entrypoint="worker.exe",
        stage_identity=(1, 10, 1, 0, 100),
        directory_identities=(),
        marker_identity=(1, 11, 1, 200, 101),
        executable_identity=(1, 12, 1, 1024, 102),
        executable_digest=intent.payload_digest,
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
        native_revision=review.native_revision,
        supervisor_phase="stopped",
        supervisor_revision=review.supervisor_revision,
        supervisor_process_settled=True,
        native_worker_request_fingerprint=intent.request_fingerprint,
        native_receipt_fingerprint=intent.receipt_fingerprint,
        supervisor_identity_fingerprint=intent.identity_fingerprint,
        launch_request_fingerprint=intent.request_fingerprint,
        launch_receipt_fingerprint=intent.receipt_fingerprint,
        launch_identity_fingerprint=intent.identity_fingerprint,
        launch_stage_identity=intent.stage_identity,
    )
    monkeypatch.setattr(retirement, "_read_review", lambda *_: review)
    monkeypatch.setattr(retirement, "_read_receipt", lambda *_: receipt)
    monkeypatch.setattr(retirement, "_read_root_delete_intent", lambda *_: receipt)
    monkeypatch.setattr(retirement, "_read_intent_under_gc_guard", lambda *_: intent)
    monkeypatch.setattr(retirement, "_partial_retirement_artifact_present", lambda *_: False)
    retirement._require_completed_retirement_under_gc_guard(None, attempt)  # type: ignore[arg-type]
    with pytest.raises(
        CodingWindowsWorkerStageRetirementError,
        match="coding_worker_stage_retirement_history_unverified",
    ):
        retirement._require_completed_retirement_under_gc_guard(  # type: ignore[arg-type]
            None, replace(attempt, native_receipt_fingerprint="0" * 64)
        )
    monkeypatch.setattr(retirement, "_read_root_delete_intent", lambda *_: None)
    with pytest.raises(CodingWindowsWorkerStageRetirementError):
        retirement._require_completed_retirement_under_gc_guard(None, attempt)  # type: ignore[arg-type]
