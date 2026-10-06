from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import loushang.coding.package_product_worker_windows_crash_lease_repair as repair


def test_windows_crash_lease_repair_rechecks_settlement_under_package_and_gc_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    attempt_id = "a" * 32
    lease = SimpleNamespace(lease_id="b" * 64)
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
        launch_request_fingerprint="c" * 64,
        native_job_name="Global\\LoushangWorker-" + "d" * 64,
    )
    receipt = SimpleNamespace(
        receipt=SimpleNamespace(
            fingerprint="e" * 64,
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
    identity = {
        "workerRequestFingerprint": attempt.launch_request_fingerprint,
        "receiptFingerprint": receipt.receipt.fingerprint,
        "jobObjectName": attempt.native_job_name,
        "nativeProfileId": receipt.receipt.policy.native_profile_id,
        "nativeProfileCatalogRevision": receipt.receipt.policy.native_profile_catalog_revision,
        "specFingerprint": "f" * 64,
    }
    native = SimpleNamespace(
        attempt_id=attempt_id,
        phase="settled",
        state_revision=8,
        phase_history=attempt.native_phase_history,
        witness_present_history=attempt.native_witness_present_history,
        identity=identity,
    )
    state: dict[str, Any] = {"native": native}

    class Registry:
        store_id = "store-1"

        def review_orphans(self, *, store_id: str):
            assert store_id == self.store_id
            events.append("package.review")
            return (lease,)

        def repair_orphan(self, lease_id: str, *, validation_guard: Any):
            assert lease_id == lease.lease_id
            events.append("package.enter")
            try:
                with validation_guard(lease):
                    events.append("package.append")
            finally:
                events.append("package.exit")

    @contextmanager
    def gc_guard(*, require_write: bool = False):
        if require_write:
            events.append("gc.write")
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
            self.gc_gate = SimpleNamespace(guard=gc_guard, read_guard=gc_guard)
            self.epoch_runtime = SimpleNamespace(
                registry=Registry(),
                borrow_product_state_root_descriptor=borrow_root,
            )

        def assert_root_gc_authority_current(self) -> None:
            events.append("root.check")

    monkeypatch.setattr(repair, "WindowsLocalWheelProductSessionOwner", Product)
    monkeypatch.setattr(
        repair,
        "os",
        SimpleNamespace(
            name="nt",
            fstat=lambda _fd: SimpleNamespace(st_dev=1, st_ino=2),
            path=SimpleNamespace(samestat=lambda _a, _b: True),
            close=lambda _fd: events.append("stage.close"),
        ),
    )
    monkeypatch.setattr(repair, "_review_under_gc_guard", lambda *_a, **_k: orphan)
    monkeypatch.setattr(repair, "_crash_settled_history_matches", lambda _r: True)
    monkeypatch.setattr(
        repair,
        "inspect_coding_windows_product_worker_provisioning_attempts",
        lambda _p: (state["native"],),
    )
    monkeypatch.setattr(
        repair,
        "open_windows_directory",
        lambda *_a, **_k: events.append("stage.open") or 11,
    )
    monkeypatch.setattr(
        repair, "windows_stat_at", lambda *_a: SimpleNamespace(st_dev=1, st_ino=2)
    )
    monkeypatch.setattr(
        repair,
        "_rebuild_windows_lpac_cleanup_spec",
        lambda **_k: events.append("spec.check"),
    )
    monkeypatch.setattr(repair, "observe_windows_worker_job_absent", lambda _n: True)

    product = Product()
    expected = repair.review_coding_windows_product_worker_crash_lease_repair(
        product, attempt_id=attempt_id
    )
    events.clear()
    state["native"] = SimpleNamespace(**{**vars(native), "state_revision": 9})
    with pytest.raises(ValueError, match="identity changed"):
        repair.repair_coding_windows_product_worker_crash_orphan_runtime(
            product, expected_review=expected
        )
    assert "package.append" not in events
    state["native"] = native
    events.clear()
    assert (
        repair.repair_coding_windows_product_worker_crash_orphan_runtime(
            product, expected_review=expected
        )
        is lease
    )
    assert events.index("gc.write") < events.index("gc.enter")
    assert events.index("package.enter") < events.index("gc.enter")
    assert events.index("gc.enter") < events.index("stage.open")
    assert events.index("stage.open") < events.index("package.append")
    assert events.index("package.append") < events.index("stage.close")
    assert events.index("stage.close") < events.index("gc.exit")
    assert events.index("gc.exit") < events.index("package.exit")
