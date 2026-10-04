from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import loushang.coding.package_product_worker_windows_crash_stage_review as stage_review
from loushang.coding.package_product_worker_windows_crash_stage_review import (
    CodingWindowsWorkerCrashStageReviewV1,
)


@pytest.mark.parametrize("supervisor_revision", [None, 4])
def test_windows_crash_stage_review_roundtrips_real_supervisor_revision(
    supervisor_revision: int | None,
) -> None:
    review = CodingWindowsWorkerCrashStageReviewV1(
        attempt_id="a" * 32,
        intent_fingerprint="b" * 64,
        lease_owner_revision=3,
        repaired_lease_id="3" * 64,
        lease_repair_revision=2,
        native_revision=8,
        supervisor_revision=supervisor_revision,
        native_spec_fingerprint="c" * 64,
        entrypoint="bin/worker.exe",
        stage_identity=(1, 2, 1, 0, 3),
        directory_identities=(("bin", (1, 4, 1, 0, 5)),),
        marker_identity=(1, 6, 1, 100, 7),
        executable_identity=(1, 8, 1, 3, 9),
        executable_digest="d" * 64,
    )
    assert CodingWindowsWorkerCrashStageReviewV1.from_bytes(review.to_bytes()) == review
    assert len(review.fingerprint) == 64
    changed = replace(review, native_revision=9)
    assert changed.fingerprint != review.fingerprint
    document = json.loads(review.to_bytes())
    document["supervisorRevision"] = 0
    with pytest.raises(ValueError, match="invalid"):
        CodingWindowsWorkerCrashStageReviewV1.from_bytes(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        )


def test_windows_crash_stage_review_requires_quiescence_and_current_native_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    attempt_id = "a" * 32
    attempt = SimpleNamespace(
        native_revision=8,
        native_phase_history=(
            "reserved",
            "profile_effect",
            "cleaning",
            "revoke_effect",
            "grants_revoked",
            "delete_effect",
            "profile_deleted",
            "settled",
        ),
        native_witness_present_history=(False, False) + (True,) * 6,
        payload_directory_identity=(1, 2),
        native_job_name="Global\\LoushangWorker-" + "b" * 64,
        supervisor_revision=None,
        launch_request_fingerprint="c" * 64,
        launch_receipt_fingerprint="d" * 64,
        launch_identity_fingerprint="e" * 64,
    )
    receipt = SimpleNamespace(
        receipt=SimpleNamespace(
            fingerprint=attempt.launch_receipt_fingerprint,
            policy=SimpleNamespace(
                product_runtime_id="runtime-1",
                native_profile_id="windows-lpac-contained-pe-v1",
                native_profile_catalog_revision="catalog-1",
            ),
        )
    )
    joined = SimpleNamespace(attempt=attempt, receipt_record=receipt)
    intent = SimpleNamespace(
        fingerprint="f" * 64,
        request_fingerprint=attempt.launch_request_fingerprint,
        receipt_fingerprint=attempt.launch_receipt_fingerprint,
        identity_fingerprint=attempt.launch_identity_fingerprint,
    )
    identity = {
        "workerRequestFingerprint": attempt.launch_request_fingerprint,
        "receiptFingerprint": receipt.receipt.fingerprint,
        "jobObjectName": attempt.native_job_name,
        "nativeProfileId": receipt.receipt.policy.native_profile_id,
        "nativeProfileCatalogRevision": receipt.receipt.policy.native_profile_catalog_revision,
        "specFingerprint": "1" * 64,
    }
    native = SimpleNamespace(
        attempt_id=attempt_id,
        phase="settled",
        state_revision=8,
        phase_history=attempt.native_phase_history,
        witness_present_history=attempt.native_witness_present_history,
        identity=identity,
    )
    repaired = SimpleNamespace(
        lease=SimpleNamespace(runtime_id="runtime-1", lease_id="3" * 64),
        record_revision=2,
    )
    state: dict[str, Any] = {"active": (), "native": native, "repaired": (repaired,)}

    class Registry:
        store_id = "store-1"

        @contextmanager
        def exclusive_runtime_quiescence(self, *, store_id: str):
            assert store_id == self.store_id
            events.append("package.enter")
            try:
                yield SimpleNamespace(
                    active_runtime_lease_ids=state["active"],
                    owner_revision=3,
                    repaired_runtime_records=state["repaired"],
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

    class Product:
        def __init__(self) -> None:
            self.policy = SimpleNamespace(product_id="coding")
            self.state_root = Path("/product")
            self.epoch_runtime = SimpleNamespace(registry=Registry())
            self.gc_gate = SimpleNamespace(read_guard=gc_guard)

        def assert_root_gc_authority_current(self) -> None:
            events.append("root.check")

    monkeypatch.setattr(stage_review, "WindowsLocalWheelProductSessionOwner", Product)
    monkeypatch.setattr(stage_review, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        stage_review, "_review_under_gc_guard", lambda *_a, **_k: joined
    )
    monkeypatch.setattr(
        stage_review,
        "_crash_settled_history_matches",
        lambda _r, *, repaired_lease: repaired_lease,
    )
    monkeypatch.setattr(stage_review, "_read_intent_under_gc_guard", lambda *_a: intent)
    monkeypatch.setattr(
        stage_review,
        "inspect_coding_windows_product_worker_provisioning_attempts",
        lambda _p: (state["native"],),
    )
    monkeypatch.setattr(
        stage_review,
        "_rebuild_windows_lpac_cleanup_spec",
        lambda **_k: events.append("spec.check"),
    )
    monkeypatch.setattr(
        stage_review,
        "_capture_stage_bytes",
        lambda *_a, **_k: (
            events.append("stage.capture")
            or SimpleNamespace(
                entrypoint="bin/worker.exe",
                stage_identity=(1, 2, 1, 0, 3),
                directory_identities=(("bin", (1, 4, 1, 0, 5)),),
                marker_identity=(1, 6, 1, 100, 7),
                executable_identity=(1, 8, 1, 3, 9),
                executable_digest="2" * 64,
            )
        ),
    )

    product = Product()
    state["active"] = ("active",)
    with pytest.raises(ValueError, match="active leases"):
        stage_review.review_coding_windows_product_worker_crash_stage(
            product, attempt_id=attempt_id
        )
    assert "stage.capture" not in events
    state["active"] = ()
    events.clear()
    state["native"] = SimpleNamespace(**{**vars(native), "state_revision": 9})
    with pytest.raises(ValueError, match="native identity changed"):
        stage_review.review_coding_windows_product_worker_crash_stage(
            product, attempt_id=attempt_id
        )
    assert "stage.capture" not in events
    state["native"] = native
    events.clear()
    state["repaired"] = ()
    with pytest.raises(ValueError, match="lease repair is unverified"):
        stage_review.review_coding_windows_product_worker_crash_stage(
            product, attempt_id=attempt_id
        )
    assert "stage.capture" not in events
    state["repaired"] = (repaired,)
    events.clear()
    reviewed = stage_review.review_coding_windows_product_worker_crash_stage(
        product, attempt_id=attempt_id
    )
    assert reviewed.supervisor_revision is None
    assert reviewed.repaired_lease_id == "3" * 64
    assert reviewed.native_spec_fingerprint == "1" * 64
    assert events.index("package.enter") < events.index("gc.enter")
    assert events.index("gc.enter") < events.index("spec.check")
    assert events.index("spec.check") < events.index("stage.capture")
    assert events.index("stage.capture") < events.index("gc.exit")
    assert events.index("gc.exit") < events.index("package.exit")
