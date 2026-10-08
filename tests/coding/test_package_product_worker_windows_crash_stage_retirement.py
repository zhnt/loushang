from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import loushang.coding.package_product_worker_windows_crash_stage_retirement as retirement
from loushang.coding.package_product_worker_windows_crash_stage_review import (
    CodingWindowsWorkerCrashStageReviewV1,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _current_after_verified_retirements_under_gc_guard,
)


def test_windows_crash_retirement_rechecks_history_before_and_after_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    review = CodingWindowsWorkerCrashStageReviewV1(
        attempt_id="a" * 32,
        intent_fingerprint="b" * 64,
        lease_owner_revision=3,
        repaired_lease_id="3" * 64,
        lease_repair_revision=2,
        native_revision=len(phases),
        supervisor_revision=None,
        native_spec_fingerprint="c" * 64,
        entrypoint="worker.exe",
        stage_identity=(1, 2, 1, 0, 3),
        directory_identities=(),
        marker_identity=(1, 4, 1, 100, 5),
        executable_identity=(1, 6, 1, 3, 7),
        executable_digest="d" * 64,
    )
    intent = SimpleNamespace(
        fingerprint=review.intent_fingerprint,
        request_fingerprint="e" * 64,
        receipt_fingerprint="f" * 64,
        identity_fingerprint="0" * 64,
    )
    attempt = CodingWindowsWorkerRecoveryAttemptV1(
        attempt_id=review.attempt_id,
        payload_directory_identity=review.stage_identity[:2],
        native_phase="settled",
        native_revision=review.native_revision,
        supervisor_phase=None,
        supervisor_revision=None,
        supervisor_process_settled=None,
        native_phase_history=phases,
        native_witness_present_history=(False, False) + (True,) * 6,
        native_witness_state="SETTLED",
        native_worker_request_fingerprint=intent.request_fingerprint,
        native_receipt_fingerprint=intent.receipt_fingerprint,
        native_job_name="Global\\LoushangWorker-" + "1" * 64,
        launch_request_fingerprint=intent.request_fingerprint,
        launch_receipt_fingerprint=intent.receipt_fingerprint,
        launch_identity_fingerprint=intent.identity_fingerprint,
        launch_stage_identity=review.stage_identity[:2],
    )
    receipt = SimpleNamespace(
        receipt=SimpleNamespace(
            fingerprint=intent.receipt_fingerprint,
            policy=SimpleNamespace(
                native_profile_id="windows-lpac-contained-pe-v1",
                native_profile_catalog_revision="catalog-1",
            ),
        )
    )
    identity = {
        "specFingerprint": review.native_spec_fingerprint,
        "workerRequestFingerprint": intent.request_fingerprint,
        "receiptFingerprint": intent.receipt_fingerprint,
        "jobObjectName": attempt.native_job_name,
        "nativeProfileId": receipt.receipt.policy.native_profile_id,
        "nativeProfileCatalogRevision": receipt.receipt.policy.native_profile_catalog_revision,
    }
    native = SimpleNamespace(
        attempt_id=review.attempt_id,
        phase="settled",
        state_revision=review.native_revision,
        phase_history=phases,
        witness_present_history=attempt.native_witness_present_history,
        identity=identity,
    )
    state = {"attempt": attempt, "missing": ("orphan_lease_absent",), "native": native}
    monkeypatch.setattr(
        retirement,
        "_review_under_gc_guard",
        lambda *_a, **_k: SimpleNamespace(
            attempt=state["attempt"],
            receipt_record=receipt,
            missing_proofs=state["missing"],
        ),
    )
    monkeypatch.setattr(retirement, "_read_intent_under_gc_guard", lambda *_a: intent)
    monkeypatch.setattr(
        retirement,
        "inspect_coding_windows_product_worker_provisioning_attempts",
        lambda _p: (state["native"],),
    )
    product = SimpleNamespace(assert_root_gc_authority_current=lambda: None)
    retirement._require_crash_history(product, review, stage_present=True)  # type: ignore[arg-type]
    state["attempt"] = replace(attempt, payload_directory_identity=None)
    retirement._require_crash_history(product, review, stage_present=False)  # type: ignore[arg-type]
    state["missing"] = ("orphan_lease_absent", "native_job_present")
    with pytest.raises(ValueError, match="history changed"):
        retirement._require_crash_history(product, review, stage_present=False)  # type: ignore[arg-type]
    state["missing"] = ("orphan_lease_absent",)
    state["native"] = SimpleNamespace(
        **{**vars(native), "identity": {**identity, "specFingerprint": "2" * 64}}
    )
    with pytest.raises(ValueError, match="native identity changed"):
        retirement._require_crash_history(product, review, stage_present=False)  # type: ignore[arg-type]


def test_windows_crash_stage_retirement_resumes_after_root_delete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    review = CodingWindowsWorkerCrashStageReviewV1(
        attempt_id="a" * 32,
        intent_fingerprint="b" * 64,
        lease_owner_revision=3,
        repaired_lease_id="3" * 64,
        lease_repair_revision=2,
        native_revision=8,
        supervisor_revision=None,
        native_spec_fingerprint="c" * 64,
        entrypoint="worker.exe",
        stage_identity=(1, 2, 1, 0, 3),
        directory_identities=(),
        marker_identity=(1, 4, 1, 100, 5),
        executable_identity=(1, 6, 1, 3, 7),
        executable_digest="d" * 64,
    )
    events: list[str] = []
    stored: dict[Path, bytes] = {}
    state: dict[str, Any] = {"stage_present": True, "current": review, "first": True}

    class Registry:
        store_id = "store-1"

        @contextmanager
        def exclusive_runtime_quiescence(self, *, store_id: str):
            assert store_id == self.store_id
            events.append("package.enter")
            try:
                yield SimpleNamespace(
                    active_runtime_lease_ids=(),
                    owner_revision=3,
                    repaired_runtime_records=(),
                )
            finally:
                events.append("package.exit")

    @contextmanager
    def gc_guard():
        events.append("gc.enter")
        try:
            yield
        finally:
            events.append("gc.exit")

    @contextmanager
    def root_guard():
        events.append("root.enter")
        try:
            yield 10
        finally:
            events.append("root.exit")

    class Product:
        def __init__(self) -> None:
            self.policy = SimpleNamespace(product_id="coding")
            self.state_root = tmp_path
            self.gc_gate = SimpleNamespace(guard=gc_guard)
            self.epoch_runtime = SimpleNamespace(
                registry=Registry(),
                borrow_product_state_root_descriptor=root_guard,
            )

        def assert_root_gc_authority_current(self) -> None:
            events.append("root.check")

    @contextmanager
    def acl_guard():
        yield object()

    def write_receipt(path: Path, raw: bytes, *, maximum_bytes: int) -> None:
        assert len(raw) <= maximum_bytes
        events.append("write." + path.name.split("-stage-")[1].split("-")[0])
        stored[path] = raw

    def delete_stage(
        product: Product,
        root: int,
        start: CodingWindowsWorkerCrashStageReviewV1,
        intent: object,
        receipt: object,
        *,
        root_delete_intent_path: Path,
        read_root_delete_intent: Any,
    ) -> None:
        assert root == 10 and start == review
        assert intent is not None and receipt is not None
        events.append("stage.delete")
        if state["first"]:
            write_receipt(
                root_delete_intent_path, receipt.to_bytes(), maximum_bytes=1024
            )
            assert read_root_delete_intent() == receipt
            state["stage_present"] = False
            state["first"] = False
            raise RuntimeError("interrupted after root delete")
        assert read_root_delete_intent() == receipt
        assert not state["stage_present"]

    monkeypatch.setattr(retirement, "WindowsLocalWheelProductSessionOwner", Product)
    monkeypatch.setattr(
        retirement,
        "os",
        SimpleNamespace(
            name="nt",
            fstat=lambda _fd: object(),
            path=SimpleNamespace(samestat=lambda _a, _b: True),
        ),
    )
    monkeypatch.setattr(retirement, "WindowsPrivateDirectoryAcl", acl_guard)
    monkeypatch.setattr(retirement, "_require_direct", lambda *_a, **_k: None)
    monkeypatch.setattr(retirement, "_require_no_other_retirement", lambda *_a: None)
    monkeypatch.setattr(
        retirement,
        "_review_crash_stage_under_gc_guard",
        lambda *_a, **_k: state["current"],
    )
    monkeypatch.setattr(
        retirement,
        "_require_crash_history",
        lambda *_a, stage_present, **_k: events.append("history." + str(stage_present)),
    )
    monkeypatch.setattr(retirement, "_stage_exists", lambda *_a: state["stage_present"])
    monkeypatch.setattr(retirement, "_read_intent_under_gc_guard", lambda *_a: object())
    monkeypatch.setattr(retirement, "_remove_remaining_stage", delete_stage)
    monkeypatch.setattr(
        retirement,
        "read_windows_private_receipt",
        lambda path, **_k: stored.get(path),
    )
    monkeypatch.setattr(retirement, "write_windows_private_receipt", write_receipt)

    product = Product()
    state["current"] = replace(review, native_revision=9)
    with pytest.raises(ValueError, match="stale"):
        retirement.retire_coding_windows_product_worker_crash_stage(
            product, expected_review=review
        )
    assert stored == {}
    state["current"] = review
    with pytest.raises(RuntimeError, match="interrupted"):
        retirement.retire_coding_windows_product_worker_crash_stage(
            product, expected_review=review
        )
    assert retirement._start_path(product, review.attempt_id) in stored  # type: ignore[arg-type]
    assert retirement._root_intent_path(product, review.attempt_id) in stored  # type: ignore[arg-type]
    assert retirement._receipt_path(product, review.attempt_id) not in stored  # type: ignore[arg-type]
    events.clear()
    result = retirement.retire_coding_windows_product_worker_crash_stage(
        product, expected_review=review
    )
    assert result.review_fingerprint == review.fingerprint
    assert events.index("package.enter") < events.index("gc.enter")
    assert events.index("gc.enter") < events.index("history.False")
    assert events.index("history.False") < events.index("stage.delete")
    assert events.index("stage.delete") < events.index("root.exit")
    assert events.index("root.exit") < events.index("gc.exit")
    assert events.index("gc.exit") < events.index("package.exit")


def test_windows_crash_retirement_admission_routes_settled_native_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        payload_directory_identity=None,
        native_phase="settled",
        native_revision=len(phases),
        supervisor_phase=None,
        supervisor_revision=None,
        supervisor_process_settled=None,
        native_phase_history=phases,
        native_witness_present_history=(False, False) + (True,) * 6,
        native_witness_state="SETTLED",
    )
    observed: list[str] = []
    monkeypatch.setattr(
        retirement,
        "_require_completed_crash_retirement_under_gc_guard",
        lambda _product, _attempt: observed.append("crash"),
    )
    product = SimpleNamespace(assert_root_gc_authority_current=lambda: None)
    assert (
        _current_after_verified_retirements_under_gc_guard(  # type: ignore[arg-type]
            product, (attempt,), attempt_id="b" * 32
        )
        == ()
    )
    assert observed == ["crash"]
