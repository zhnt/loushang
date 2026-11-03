from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import loushang.coding.package_product_worker_windows_crash_native_settlement as settlement
from loushang.coding.package_product_worker_windows_crash_cleanup_review import (
    CodingWindowsWorkerCrashCleanupReviewV1,
)


def test_windows_crash_native_effect_requires_package_then_product_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    attempt_id = "a" * 32
    spec_fingerprint = "b" * 64
    receipt_fingerprint = "c" * 64
    request_fingerprint = "d" * 64
    job_name = "Global\\LoushangWorker-" + "e" * 64
    lease = SimpleNamespace(lease_id="f" * 64)
    attempt = SimpleNamespace(
        native_phase="profile_effect",
        native_phase_history=("reserved", "profile_effect"),
        native_witness_present_history=(False, False),
        payload_directory_identity=(1, 2),
        launch_request_fingerprint=request_fingerprint,
        native_job_name=job_name,
        supervisor_phase=None,
        supervisor_process_settled=None,
    )
    receipt = SimpleNamespace(
        receipt=SimpleNamespace(
            fingerprint=receipt_fingerprint,
            policy=SimpleNamespace(
                native_profile_id="windows-lpac-contained-pe-v1",
                native_profile_catalog_revision="catalog-1",
            ),
        )
    )
    orphan = SimpleNamespace(
        attempt_id=attempt_id,
        attempt=attempt,
        receipt_record=receipt,
        orphan_leases=(lease,),
    )
    expected = CodingWindowsWorkerCrashCleanupReviewV1(
        orphan_review=orphan,
        native_revision=2,
        native_spec_fingerprint=spec_fingerprint,
        payload_directory_identity=(1, 2),
    )
    identity = {
        "specFingerprint": spec_fingerprint,
        "receiptFingerprint": receipt_fingerprint,
        "workerRequestFingerprint": request_fingerprint,
        "jobObjectName": job_name,
        "nativeProfileId": "windows-lpac-contained-pe-v1",
        "nativeProfileCatalogRevision": "catalog-1",
    }
    provisioned = SimpleNamespace(
        attempt_id=attempt_id,
        phase="profile_effect",
        phase_history=attempt.native_phase_history,
        witness_present_history=attempt.native_witness_present_history,
        state_revision=2,
        identity=identity,
    )
    state: dict[str, Any] = {"review": orphan, "latest": None}

    class Registry:
        store_id = "store-1"

        @contextmanager
        def guard_orphan_recovery(self, *, store_id: str, lease_id: str):
            assert (store_id, lease_id) == (self.store_id, lease.lease_id)
            events.append("package.enter")
            try:
                yield lease
            finally:
                events.append("package.exit")

    @contextmanager
    def gc_guard(*, require_write: bool):
        assert require_write
        events.append("gc.enter")
        try:
            yield
        finally:
            events.append("gc.exit")

    @contextmanager
    def borrow_root():
        events.append("root.enter")
        try:
            yield 10
        finally:
            events.append("root.exit")

    class Product:
        def __init__(self) -> None:
            self.policy = SimpleNamespace(product_id="coding")
            self.state_root = Path("/product")
            self.gc_gate = SimpleNamespace(guard=gc_guard)
            self.epoch_runtime = SimpleNamespace(
                registry=Registry(),
                borrow_product_state_root_descriptor=borrow_root,
            )

        def assert_root_gc_authority_current(self) -> None:
            events.append("root.check")

    class Journal:
        def __init__(self, path: Path, *, identity: dict[str, object]) -> None:
            assert path.name == f"worker-native-provisioning-{attempt_id}.jsonl"
            assert identity == provisioned.identity

        def load(self, *, directory_fd: int):
            assert directory_fd == 10
            return state["latest"]

    def native_effect(**arguments: object) -> None:
        assert isinstance(arguments["provisioning_state_store"], settlement._PinnedRecoveryStore)
        events.append("native.effect")
        state["latest"] = {
            "phase": "settled",
            "stateRevision": 8,
            "witness": {"state": "SETTLED"},
        }

    monkeypatch.setattr(settlement, "WindowsLocalWheelProductSessionOwner", Product)
    monkeypatch.setattr(
        settlement,
        "os",
        SimpleNamespace(
            name="nt",
            fstat=lambda _fd: SimpleNamespace(st_dev=1, st_ino=2),
            path=SimpleNamespace(samestat=lambda _a, _b: True),
            close=lambda _fd: events.append("stage.close"),
        ),
    )
    monkeypatch.setattr(settlement, "_review_under_gc_guard", lambda *_a, **_k: state["review"])
    monkeypatch.setattr(settlement, "_crash_cleanup_history_matches", lambda _r: True)
    monkeypatch.setattr(
        settlement,
        "inspect_coding_windows_product_worker_provisioning_attempts",
        lambda _p: (provisioned,),
    )
    monkeypatch.setattr(
        settlement,
        "open_windows_directory",
        lambda *_a, **_k: events.append("stage.open") or 11,
    )
    monkeypatch.setattr(
        settlement, "windows_stat_at", lambda *_a: SimpleNamespace(st_dev=1, st_ino=2)
    )
    monkeypatch.setattr(settlement, "_rebuild_windows_lpac_cleanup_spec", lambda **_k: object())
    monkeypatch.setattr(settlement, "observe_windows_worker_job_absent", lambda _n: True)
    monkeypatch.setattr(
        settlement,
        "read_coding_windows_worker_installed_backend_release",
        lambda _p: SimpleNamespace(expectation="reviewed-backend"),
    )
    monkeypatch.setattr(
        settlement,
        "verify_windows_backend_material_expectation",
        lambda value: events.append("backend.verify") if value == "reviewed-backend" else None,
    )
    monkeypatch.setattr(settlement, "WindowsWorkerProvisioningStateJournal", Journal)
    monkeypatch.setattr(settlement, "_recover_windows_lpac_containment_cleanup", native_effect)

    product = Product()
    state["review"] = SimpleNamespace(attempt_id="changed")
    with pytest.raises(ValueError, match="stale"):
        settlement.settle_coding_windows_product_worker_crash_native(
            product, expected_review=expected
        )
    assert "stage.open" not in events and "native.effect" not in events

    events.clear()
    state["review"] = orphan
    attempt.supervisor_phase = "healthy"
    attempt.supervisor_process_settled = False
    with pytest.raises(ValueError, match="Supervisor is unsettled"):
        settlement.settle_coding_windows_product_worker_crash_native(
            product, expected_review=expected
        )
    assert "stage.open" not in events and "native.effect" not in events

    events.clear()
    attempt.supervisor_phase = None
    attempt.supervisor_process_settled = None
    result = settlement.settle_coding_windows_product_worker_crash_native(
        product, expected_review=expected
    )
    assert (result.attempt_id, result.native_revision, result.spec_fingerprint) == (
        attempt_id,
        8,
        spec_fingerprint,
    )
    assert events.index("package.enter") < events.index("gc.enter")
    assert events.index("gc.enter") < events.index("stage.open")
    assert events.index("gc.enter") < events.index("backend.verify")
    assert events.index("backend.verify") < events.index("native.effect")
    assert events.index("stage.open") < events.index("native.effect")
    assert events.index("native.effect") < events.index("gc.exit")
    assert events.index("gc.exit") < events.index("package.exit")
