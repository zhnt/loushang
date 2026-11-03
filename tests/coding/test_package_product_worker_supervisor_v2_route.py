"""Supervisor CAS preserves epochs and restart budget after retired deletion."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_supervisor_journal as supervisor_module
import loushang.harness.worker.journal as generic_supervisor_module
from loushang.coding.package_product_worker_history_deletion_v2 import (
    CodingWorkerV2DeletionLedger,
)
from loushang.coding.package_product_worker_history_read_v2 import (
    read_coding_worker_v2_retained_history,
)
from loushang.coding.package_product_worker_history_segments import (
    _head_name,
    _segment_name,
)
from loushang.coding.package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
    PRODUCT_OWNER_INDEX_NAME,
)
from loushang.coding.package_product_worker_supervisor_journal import (
    CodingProductWorkerSupervisorJournal,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.worker.journal import WorkerSupervisorJournalError
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted
from tests.coding.test_package_product_worker_supervisor_segments import _identity


def _product(root: Path) -> PosixLocalWheelProductSessionOwner:
    product = object.__new__(PosixLocalWheelProductSessionOwner)
    object.__setattr__(product, "state_root", root)
    object.__setattr__(
        product,
        "gc_gate",
        PluginPackageGcReservationJournal(root / "gc-reservations.jsonl"),
    )
    object.__setattr__(
        product,
        "policy",
        SimpleNamespace(product_id="coding", project_scope_id="scope"),
    )
    object.__setattr__(
        product,
        "epoch_runtime",
        SimpleNamespace(registry=SimpleNamespace(store_id="store")),
    )
    return product


def test_supervisor_v2_transition_and_claim_after_retired_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stem = "worker-supervisor"
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        rooted.sibling(stem + ".jsonl.lock").create_new(b"")
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(prepared.index.to_bytes())
        rooted.sibling(DELETION_LEDGER_NAME).create_new(
            CodingWorkerV2DeletionLedger.from_prepared(prepared).to_bytes()
        )
        rooted.sibling(_segment_name(stem, 0)).unlink()
        rooted.sibling(_head_name(stem, 0)).unlink()

    monkeypatch.setattr(
        PosixLocalWheelProductSessionOwner,
        "assert_root_gc_authority_current",
        lambda _self: None,
    )
    monkeypatch.setattr(
        generic_supervisor_module, "_supervisor_key", lambda _id: "c" * 64
    )
    journal = CodingProductWorkerSupervisorJournal(_product(tmp_path))
    assert journal.status("a" * 32) is None
    current = journal.status("e" * 32)
    assert current is not None and current.phase == "launching"
    assert journal.attempts() == (current,)
    assert journal.incomplete() == (current,)
    next_identity = _identity(attempt="f", epoch=3)
    with pytest.raises(WorkerSupervisorJournalError, match="not durably settled"):
        journal.next_supervisor_epoch(next_identity)
    with pytest.raises(WorkerSupervisorJournalError) as retired:
        journal.claim(_identity(attempt="a", epoch=3), max_attempts=3)
    assert retired.value.code == "worker_attempt_already_claimed"

    failed = journal.transition(
        "e" * 32,
        expected_phase="launching",
        next_phase="failed",
        expected_record_revision=5,
        expected_supervisor_epoch=2,
        failure_code="test_failure",
    )
    assert failed.record_revision == 6
    settled = journal.transition(
        "e" * 32,
        expected_phase="failed",
        next_phase="process_settled",
        expected_record_revision=6,
        expected_supervisor_epoch=2,
        failure_code="test_failure",
    )
    assert settled.record_revision == 7
    assert journal.next_supervisor_epoch(next_identity) == 3
    with pytest.raises(WorkerSupervisorJournalError) as exhausted:
        journal.claim(next_identity, max_attempts=2)
    assert exhausted.value.code == "worker_restart_budget_exhausted"
    monkeypatch.setattr(supervisor_module, "_MAX_RECORDS", 1)
    claimed = journal.claim(next_identity, max_attempts=3)
    assert claimed.record_revision == 8
    assert claimed.restart_ordinal == 3
    assert journal.status(next_identity.attempt_id) == claimed
    assert not (tmp_path / (stem + ".jsonl")).exists()
    with _rooted(tmp_path) as rooted:
        assert (
            read_coding_worker_v2_retained_history(rooted, stem=stem).last_revision == 8
        )

    (tmp_path / (stem + ".jsonl.lock")).unlink()
    with pytest.raises(WorkerSupervisorJournalError) as missing:
        journal.status(next_identity.attempt_id)
    assert missing.value.code == "worker_supervisor_journal_corrupt"
    assert not (tmp_path / (stem + ".jsonl")).exists()
