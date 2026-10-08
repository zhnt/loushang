from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_windows_crash_supervisor_settlement as supervisor_settlement
from loushang.coding.package_product_worker_windows_crash_cleanup_review import (
    CodingWindowsWorkerCrashCleanupReviewV1,
)
from loushang.coding.package_product_worker_windows_crash_supervisor_settlement import (
    _settle_crashed_supervisor_record,
)
from loushang.harness.worker import WorkerLaunchIdentityV1
from loushang.harness.worker.journal import WorkerSupervisorJournal


def _identity() -> WorkerLaunchIdentityV1:
    return WorkerLaunchIdentityV1(
        plugin_id="workerprobe",
        plugin_revision_digest="a" * 64,
        contribution_id="query-provider",
        owner_id="coding.worker",
        product_id="coding",
        scope_id="session-one",
        owner_generation=1,
        declaration_fingerprint="b" * 64,
        worker_configuration_fingerprint="c" * 64,
        attempt_id="d" * 32,
        supervisor_epoch=1,
        session_nonce="e" * 64,
    )


def test_windows_crash_supervisor_settles_active_process_once(tmp_path: Path) -> None:
    journal = WorkerSupervisorJournal(tmp_path / "supervisor.jsonl")
    identity = _identity()
    claimed = journal.claim(identity, max_attempts=2)
    launching = journal.transition(
        identity.attempt_id,
        expected_phase="claimed",
        next_phase="launching",
        expected_record_revision=claimed.record_revision,
        expected_supervisor_epoch=identity.supervisor_epoch,
    )
    settled = _settle_crashed_supervisor_record(journal, launching)
    assert settled.phase == "process_settled"
    assert settled.failure_code == "windows_host_crash"
    assert settled.process_settled
    assert journal.status(identity.attempt_id) == settled
    assert _settle_crashed_supervisor_record(journal, settled) == settled
    assert journal.status(identity.attempt_id) == settled


def test_windows_crash_supervisor_preserves_prior_failure(tmp_path: Path) -> None:
    journal = WorkerSupervisorJournal(tmp_path / "supervisor.jsonl")
    identity = _identity()
    claimed = journal.claim(identity, max_attempts=2)
    fenced = journal.transition(
        identity.attempt_id,
        expected_phase="claimed",
        next_phase="fenced",
        expected_record_revision=claimed.record_revision,
        expected_supervisor_epoch=identity.supervisor_epoch,
        failure_code="prior_failure",
    )
    settled = _settle_crashed_supervisor_record(journal, fenced)
    assert settled.phase == "process_settled"
    assert settled.failure_code == "prior_failure"
    assert journal.status(identity.attempt_id) == settled


def test_windows_crash_supervisor_product_keeps_transitions_inside_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = WorkerSupervisorJournal(tmp_path / "supervisor.jsonl")
    identity = _identity()
    claimed = journal.claim(identity, max_attempts=2)
    launching = journal.transition(
        identity.attempt_id,
        expected_phase="claimed",
        next_phase="launching",
        expected_record_revision=claimed.record_revision,
        expected_supervisor_epoch=identity.supervisor_epoch,
    )
    events: list[str] = []
    lease = SimpleNamespace(lease_id="f" * 64)
    job_name = "Global\\LoushangWorker-" + "0" * 64
    attempt = SimpleNamespace(
        launch_identity_fingerprint=identity.fingerprint,
        payload_directory_identity=(1, 2),
        native_revision=2,
        native_job_name=job_name,
        supervisor_phase="launching",
        supervisor_revision=launching.record_revision,
    )
    orphan = SimpleNamespace(
        attempt_id=identity.attempt_id,
        attempt=attempt,
        orphan_leases=(lease,),
    )
    review = CodingWindowsWorkerCrashCleanupReviewV1(
        orphan_review=orphan,
        native_revision=2,
        native_spec_fingerprint="1" * 64,
        payload_directory_identity=(1, 2),
    )
    intent = SimpleNamespace(
        identity_fingerprint=identity.fingerprint,
        stage_identity=(1, 2),
        supervisor_epoch=identity.supervisor_epoch,
    )

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
    def gc_guard():
        events.append("gc.enter")
        try:
            yield
        finally:
            events.append("gc.exit")

    class Product:
        def __init__(self) -> None:
            self.policy = SimpleNamespace(product_id="coding")
            self.gc_gate = SimpleNamespace(guard=gc_guard)
            self.epoch_runtime = SimpleNamespace(registry=Registry())

        def assert_root_gc_authority_current(self) -> None:
            events.append("root.check")

    class Journal:
        def inspect_records(self):
            current = journal.status(identity.attempt_id)
            return () if current is None else (current,)

        def transition(self, *args, **kwargs):
            events.append("supervisor.effect")
            return journal.transition(*args, **kwargs)

    def refreshed(_product):
        current = journal.status(identity.attempt_id)
        assert current is not None
        return (
            SimpleNamespace(
                attempt_id=identity.attempt_id,
                native_revision=2,
                payload_directory_identity=(1, 2),
                launch_identity_fingerprint=identity.fingerprint,
                supervisor_phase=current.phase,
                supervisor_revision=current.record_revision,
                supervisor_process_settled=current.process_settled,
            ),
        )

    monkeypatch.setattr(supervisor_settlement, "WindowsLocalWheelProductSessionOwner", Product)
    monkeypatch.setattr(supervisor_settlement, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        supervisor_settlement, "_review_under_gc_guard", lambda *_a, **_k: orphan
    )
    monkeypatch.setattr(
        supervisor_settlement, "_crash_cleanup_history_matches", lambda _r: True
    )
    monkeypatch.setattr(
        supervisor_settlement, "_read_intent_under_gc_guard", lambda *_a: intent
    )
    monkeypatch.setattr(
        supervisor_settlement,
        "open_coding_windows_product_worker_supervisor_journal",
        lambda _p: Journal(),
    )
    monkeypatch.setattr(
        supervisor_settlement,
        "_inspect_windows_worker_recovery_inventory_under_gc_guard",
        refreshed,
    )
    monkeypatch.setattr(
        supervisor_settlement,
        "observe_windows_worker_job_absent",
        lambda _job: events.append("job.absent") or True,
    )
    settled = supervisor_settlement.settle_coding_windows_product_worker_crash_supervisor(
        Product(), expected_review=review
    )
    assert settled is not None and settled.phase == "process_settled"
    assert events.count("supervisor.effect") == 2
    assert events.index("package.enter") < events.index("gc.enter")
    assert events.index("gc.enter") < events.index("supervisor.effect")
    assert events.index("supervisor.effect") < events.index("gc.exit")
    assert events.index("gc.exit") < events.index("package.exit")
