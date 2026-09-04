from __future__ import annotations

import json
from pathlib import Path

import pytest

from loushang.harness.worker import WorkerLaunchIdentityV1
from loushang.harness.worker.journal import (
    WorkerSupervisorJournal,
    WorkerSupervisorJournalError,
)


def _identity(*, attempt: str, epoch: int) -> WorkerLaunchIdentityV1:
    return WorkerLaunchIdentityV1(
        plugin_id="review-pack",
        plugin_revision_digest="a" * 64,
        contribution_id="review-provider",
        owner_id="coding.lsp",
        product_id="coding",
        scope_id="session-one",
        owner_generation=3,
        declaration_fingerprint="b" * 64,
        worker_configuration_fingerprint="c" * 64,
        attempt_id=attempt * 32,
        supervisor_epoch=epoch,
        session_nonce=("d" if epoch == 1 else "e") * 64,
    )


def _settle(
    journal: WorkerSupervisorJournal,
    *,
    attempt_id: str,
    epoch: int,
) -> None:
    current = journal.status(attempt_id)
    assert current is not None
    for next_phase in ("launching", "handshaking", "healthy", "draining", "stopped"):
        current = journal.transition(
            attempt_id,
            expected_phase=current.phase,
            next_phase=next_phase,  # type: ignore[arg-type]
            expected_record_revision=current.record_revision,
            expected_supervisor_epoch=epoch,
        )


def test_journal_enforces_exclusive_attempt_epoch_and_contiguous_cas(
    tmp_path: Path,
) -> None:
    journal = WorkerSupervisorJournal(tmp_path / "workers.jsonl")
    first = _identity(attempt="1", epoch=1)
    claimed = journal.claim(first, max_attempts=3)

    assert claimed.phase == "claimed"
    assert claimed.restart_ordinal == 1
    with pytest.raises(WorkerSupervisorJournalError) as caught:
        journal.claim(first, max_attempts=3)
    assert caught.value.code == "worker_attempt_already_claimed"

    with pytest.raises(WorkerSupervisorJournalError) as caught:
        journal.claim(_identity(attempt="2", epoch=2), max_attempts=3)
    assert caught.value.code == "worker_prior_attempt_unsettled"

    launching = journal.transition(
        first.attempt_id,
        expected_phase="claimed",
        next_phase="launching",
        expected_record_revision=claimed.record_revision,
        expected_supervisor_epoch=1,
    )
    with pytest.raises(WorkerSupervisorJournalError) as caught:
        journal.transition(
            first.attempt_id,
            expected_phase="claimed",
            next_phase="launching",
            expected_record_revision=claimed.record_revision,
            expected_supervisor_epoch=1,
        )
    assert caught.value.code == "worker_attempt_cas_conflict"

    fenced = journal.transition(
        first.attempt_id,
        expected_phase=launching.phase,
        next_phase="fenced",
        expected_record_revision=launching.record_revision,
        expected_supervisor_epoch=1,
        failure_code="worker_host_recovered",
    )
    assert fenced.terminal is True
    assert journal.incomplete() == ()

    second = _identity(attempt="2", epoch=2)
    second_claim = journal.claim(second, max_attempts=3)
    assert second_claim.restart_ordinal == 2


def test_journal_rejects_epoch_gaps_and_restart_budget_exhaustion(
    tmp_path: Path,
) -> None:
    journal = WorkerSupervisorJournal(tmp_path / "workers.jsonl")
    first = _identity(attempt="1", epoch=1)
    journal.claim(first, max_attempts=1)
    _settle(journal, attempt_id=first.attempt_id, epoch=1)

    with pytest.raises(WorkerSupervisorJournalError) as caught:
        journal.claim(_identity(attempt="3", epoch=3), max_attempts=3)
    assert caught.value.code == "worker_supervisor_epoch_stale"

    with pytest.raises(WorkerSupervisorJournalError) as caught:
        journal.claim(_identity(attempt="2", epoch=2), max_attempts=1)
    assert caught.value.code == "worker_restart_budget_exhausted"


def test_journal_reopens_incomplete_attempt_without_synthesizing_success(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workers.jsonl"
    identity = _identity(attempt="1", epoch=1)
    journal = WorkerSupervisorJournal(path)
    claimed = journal.claim(identity, max_attempts=3)
    journal.transition(
        identity.attempt_id,
        expected_phase="claimed",
        next_phase="launching",
        expected_record_revision=claimed.record_revision,
        expected_supervisor_epoch=1,
    )

    reopened = WorkerSupervisorJournal(path)
    incomplete = reopened.incomplete()
    assert len(incomplete) == 1
    assert incomplete[0].phase == "launching"
    assert incomplete[0].terminal is False


def test_journal_fails_closed_on_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "workers.jsonl"
    identity = _identity(attempt="1", epoch=1)
    journal = WorkerSupervisorJournal(path)
    journal.claim(identity, max_attempts=3)
    original = path.read_text(encoding="utf-8").strip()
    path.write_text(
        original[:-1] + ',"recordVersion":1}\n',
        encoding="utf-8",
    )

    with pytest.raises(WorkerSupervisorJournalError) as caught:
        WorkerSupervisorJournal(path).status(identity.attempt_id)
    assert caught.value.code == "worker_supervisor_journal_corrupt"


def test_journal_fails_closed_on_cross_attempt_epoch_tampering(tmp_path: Path) -> None:
    path = tmp_path / "workers.jsonl"
    journal = WorkerSupervisorJournal(path)
    first = _identity(attempt="1", epoch=1)
    journal.claim(first, max_attempts=3)
    _settle(journal, attempt_id=first.attempt_id, epoch=1)
    second = _identity(attempt="2", epoch=2)
    journal.claim(second, max_attempts=3)

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[-1])
    tampered["supervisorEpoch"] = 3
    lines[-1] = json.dumps(
        tampered,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(WorkerSupervisorJournalError) as caught:
        WorkerSupervisorJournal(path).status(second.attempt_id)
    assert caught.value.code == "worker_supervisor_journal_corrupt"
