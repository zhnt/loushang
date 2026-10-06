"""Product Worker activation-state revisions remain contiguous across seals."""

from __future__ import annotations

import os
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import pytest

import loushang.coding.package_product_worker_activation_state_journal as activation_module
from loushang.coding.package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournalError,
    _canonical_json_bytes,
    _StateRecord,
)
from loushang.harness.worker.product_activation import (
    WorkerCleanupSettlementV1,
    _AttemptKey,
    _initial_state,
)
from tests.harness.worker.test_product_activation import (
    _begin,
    _coordinator,
    _publish,
    _receipt,
    _retire_and_terminal,
    _settlement,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX Product journal")


def _journal(tmp_path: Path) -> CodingProductWorkerActivationStateJournal:
    root = tmp_path / "product-state"
    root.mkdir(mode=0o700)
    return CodingProductWorkerActivationStateJournal(
        root / "worker-activation-state.jsonl"
    )


def _next_state(state: dict[str, object]) -> dict[str, object]:
    next_state = dict(state)
    revision = state["stateRevision"]
    assert type(revision) is int
    next_state["stateRevision"] = revision + 1
    return next_state


def _race_segment_cas(path: Path, barrier: Any, results: Any) -> None:
    journal = CodingProductWorkerActivationStateJournal(path)
    current = journal.load_read_only()
    assert current is not None
    revision = current["stateRevision"]
    assert type(revision) is int
    barrier.wait(timeout=15)
    results.put(
        journal.compare_and_swap(
            expected_revision=revision,
            document=_next_state(dict(current)),
        )
    )


def _registered_attempt(*, receipt: str, attempt_id: str) -> dict[str, object]:
    return {
        "attemptId": attempt_id,
        "bootIdentity": "boot-a",
        "cleanupContractVersion": 1,
        "cleanupDebt": None,
        "cleanupSettlement": None,
        "domainRetired": False,
        "evidenceAuthorityFingerprint": "d" * 64,
        "evidenceAuthorityId": "evidence-a",
        "hostIdentity": "host-a",
        "owner": "hosting",
        "ownerGeneration": 1,
        "phase": "registered",
        "policyFingerprint": "c" * 64,
        "protocolTerminal": False,
        "readiness": "pending",
        "receiptFingerprint": receipt,
        "required": False,
        "restartOrdinal": 0,
    }


def test_activation_state_reopens_multiple_sealed_generations_and_refuses_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(activation_module, "_MAX_REVISIONS", 1)
    journal = _journal(tmp_path)
    assert journal.load_read_only() is None
    assert tuple(journal.path.parent.iterdir()) == ()

    initial = _initial_state(restart_budget=3)
    second = _next_state(initial)
    third = _next_state(second)
    assert journal.compare_and_swap(expected_revision=0, document=initial)
    assert journal.compare_and_swap(expected_revision=1, document=second)
    assert journal.compare_and_swap(expected_revision=2, document=third)
    manifest = journal.path.parent / "worker-activation-state.segments.json"
    assert manifest.is_file()
    assert (journal.path.parent / "worker-activation-state.g00000001.jsonl").is_file()
    assert CodingProductWorkerActivationStateJournal(journal.path).load_read_only() == third
    assert not journal.compare_and_swap(expected_revision=1, document=second)

    original = journal.path.read_bytes()
    journal.path.write_bytes(original + b" ")
    with pytest.raises(WorkerActivationStateJournalError) as changed:
        CodingProductWorkerActivationStateJournal(journal.path).load_read_only()
    assert changed.value.code == "worker_activation_state_corrupt"


def test_activation_state_reopens_after_manifest_publication_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(activation_module, "_MAX_REVISIONS", 1)
    journal = _journal(tmp_path)
    initial = _initial_state(restart_budget=3)
    second = _next_state(initial)
    assert journal.compare_and_swap(expected_revision=0, document=initial)

    append = activation_module.append_jsonl_record

    def interrupted(*args: object, **kwargs: object) -> None:
        raise OSError("interrupted after manifest publication")

    monkeypatch.setattr(activation_module, "append_jsonl_record", interrupted)
    with pytest.raises(OSError, match="interrupted after manifest publication"):
        journal.compare_and_swap(expected_revision=1, document=second)
    monkeypatch.setattr(activation_module, "append_jsonl_record", append)

    assert (journal.path.parent / "worker-activation-state.segments.json").is_file()
    assert (journal.path.parent / "worker-activation-state.g00000001.jsonl").read_bytes() == b""
    reopened = CodingProductWorkerActivationStateJournal(journal.path)
    assert reopened.load_read_only() == initial
    assert reopened.compare_and_swap(expected_revision=1, document=second)
    assert reopened.load_read_only() == second


def test_activation_state_refuses_unpublished_generation(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    assert journal.compare_and_swap(
        expected_revision=0, document=_initial_state(restart_budget=3)
    )
    (journal.path.parent / "worker-activation-state.g00000001.jsonl").write_bytes(
        b"orphan"
    )
    with pytest.raises(WorkerActivationStateJournalError) as orphan:
        journal.load_read_only()
    assert orphan.value.code == "worker_activation_state_corrupt"


def test_activation_state_refuses_missing_initial_history_with_unsettled_attempt(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    initial = _initial_state(restart_budget=3)
    assert journal.compare_and_swap(expected_revision=0, document=initial)
    registered = _next_state(initial)
    receipt = "a" * 64
    attempt_id = "b" * 32
    registered["attempts"] = {
        _AttemptKey(receipt, attempt_id, 1).encoded: _registered_attempt(
            receipt=receipt, attempt_id=attempt_id
        )
    }
    assert journal.compare_and_swap(expected_revision=1, document=registered)
    assert (journal.path.parent / "worker-activation-state.jsonl.lock").is_file()
    journal.path.unlink()

    reopened = CodingProductWorkerActivationStateJournal(journal.path)
    with pytest.raises(WorkerActivationStateJournalError) as lost:
        reopened.load()
    assert lost.value.code == "worker_activation_state_corrupt"
    with pytest.raises(WorkerActivationStateJournalError) as reset:
        reopened.compare_and_swap(expected_revision=0, document=initial)
    assert reset.value.code == "worker_activation_state_corrupt"


def test_activation_state_cross_process_rollover_cas_has_one_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(activation_module, "_MAX_REVISIONS", 1)
    journal = _journal(tmp_path)
    initial = _initial_state(restart_budget=3)
    assert journal.compare_and_swap(expected_revision=0, document=initial)
    context = get_context("fork")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = tuple(
        context.Process(
            target=_race_segment_cas, args=(journal.path, barrier, results)
        )
        for _ in range(2)
    )
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=20)
        assert all(process.exitcode == 0 for process in processes)
        assert sorted(results.get(timeout=2) for _ in processes) == [False, True]
        assert CodingProductWorkerActivationStateJournal(journal.path).load_read_only() == (
            _next_state(initial)
        )
        assert (journal.path.parent / "worker-activation-state.segments.json").is_file()
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()


def test_activation_state_refuses_compacted_attempt_reuse_across_generations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(activation_module, "_MAX_REVISIONS", 1)
    journal = _journal(tmp_path)
    receipt = "a" * 64
    attempt_id = "b" * 32
    key = _AttemptKey(receipt, attempt_id, 1).encoded
    attempt = _registered_attempt(receipt=receipt, attempt_id=attempt_id)
    initial = _initial_state(restart_budget=3)
    registered = _next_state(initial)
    registered["attempts"] = {key: attempt}
    settled = _next_state(registered)
    settled_attempt = dict(attempt)
    settled_attempt.update(
        phase="settled",
        domainRetired=True,
        protocolTerminal=True,
        cleanupSettlement=WorkerCleanupSettlementV1(
            receipt_fingerprint=receipt,
            attempt_id=attempt_id,
            owner_generation=1,
            host_identity="host-a",
            boot_identity="boot-a",
            protocol_terminal=True,
            domain_retired=True,
            tree_settled=True,
        ).to_dict(),
    )
    settled["attempts"] = {key: settled_attempt}
    compacted = _next_state(settled)
    compacted["attempts"] = {}
    reused = _next_state(compacted)
    reused["attempts"] = {key: attempt}

    for revision, state in enumerate((initial, registered, settled, compacted)):
        assert journal.compare_and_swap(expected_revision=revision, document=state)
    before = tuple(sorted(path.name for path in journal.path.parent.iterdir()))
    with pytest.raises(WorkerActivationStateJournalError) as conflict:
        journal.compare_and_swap(expected_revision=4, document=reused)
    assert conflict.value.code == "worker_activation_state_history_conflict"
    assert tuple(sorted(path.name for path in journal.path.parent.iterdir())) == before
    assert CodingProductWorkerActivationStateJournal(journal.path).load_read_only() == (
        compacted
    )
    retained = CodingProductWorkerActivationStateJournal(
        journal.path
    ).retained_attempts_read_only()
    assert len(retained) == 1
    assert retained[0].attempt_id == attempt_id
    assert retained[0].receipt_fingerprint == receipt
    assert retained[0].owner_generation == 1
    assert retained[0].phase == "settled"
    assert retained[0].last_seen_revision == 3
    assert not retained[0].current

    monkeypatch.setattr(activation_module, "_MAX_REVISIONS", 2)
    active = journal.path.parent / "worker-activation-state.g00000003.jsonl"
    active.write_bytes(
        active.read_bytes()
        + _canonical_json_bytes(_StateRecord.create(reused).to_dict())
        + b"\n"
    )
    with pytest.raises(WorkerActivationStateJournalError) as changed:
        CodingProductWorkerActivationStateJournal(journal.path).load_read_only()
    assert changed.value.code == "worker_activation_state_corrupt"


@pytest.mark.parametrize("field", ("hostIdentity", "bootIdentity"))
def test_activation_state_refuses_rebinding_existing_attempt_identity(
    tmp_path: Path, field: str
) -> None:
    journal = _journal(tmp_path)
    receipt = "a" * 64
    attempt_id = "b" * 32
    key = _AttemptKey(receipt, attempt_id, 1).encoded
    initial = _initial_state(restart_budget=3)
    registered = _next_state(initial)
    registered_attempt = _registered_attempt(receipt=receipt, attempt_id=attempt_id)
    registered["attempts"] = {key: registered_attempt}
    assert journal.compare_and_swap(expected_revision=0, document=initial)
    assert journal.compare_and_swap(expected_revision=1, document=registered)

    rebound = _next_state(registered)
    attempt = dict(registered_attempt)
    attempt[field] = "different-owner"
    rebound["attempts"] = {key: attempt}
    with pytest.raises(WorkerActivationStateJournalError) as conflict:
        journal.compare_and_swap(expected_revision=2, document=rebound)
    assert conflict.value.code == "worker_activation_state_history_conflict"
    assert journal.load_read_only() == registered
    journal.path.write_bytes(
        journal.path.read_bytes()
        + _canonical_json_bytes(_StateRecord.create(rebound).to_dict())
        + b"\n"
    )
    with pytest.raises(WorkerActivationStateJournalError) as corrupt:
        CodingProductWorkerActivationStateJournal(journal.path).load_read_only()
    assert corrupt.value.code == "worker_activation_state_corrupt"


def test_activation_state_product_journal_runs_real_c5_lifecycle_across_seals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(activation_module, "_MAX_REVISIONS", 2)
    journal = _journal(tmp_path)
    receipt = _receipt()
    coordinator, authority = _coordinator(receipt=receipt, store=journal)
    _begin(coordinator, receipt)
    assert _publish(coordinator, receipt)["reason"] == "published"
    _retire_and_terminal(coordinator, receipt)
    evidence = authority.evidence_authority
    assert coordinator.record_cleanup_settlement(
        _settlement(receipt), witness=evidence.tree_witness
    )["reason"] == "cleanup_settled"
    state = coordinator.snapshot()
    assert CodingProductWorkerActivationStateJournal(journal.path).load_read_only() == (
        state
    )
    assert (journal.path.parent / "worker-activation-state.segments.json").is_file()
