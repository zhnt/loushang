"""The Product Start Gate uses its V2 base after retired bytes are removed."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_start_gate_journal as gate_module
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
from loushang.coding.package_product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
    CodingWorkerStartGateJournalError,
)
from loushang.harness.journal import DURABLE_LOCKED_JOURNAL
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted
from tests.coding.test_package_product_worker_start_gate_base_v2 import _record


def _journal(root: Path) -> CodingWorkerStartGateJournal:
    # Only the Product shell is replaced; journal IO, GC gate, and fixtures are real.
    journal = object.__new__(CodingWorkerStartGateJournal)
    journal._product = SimpleNamespace(  # type: ignore[assignment]
        state_root=root,
        gc_gate=PluginPackageGcReservationJournal(root / "gc-reservations.jsonl"),
        policy=SimpleNamespace(
            project_scope_id="scope",
            bindings=(SimpleNamespace(source_trust_class="local-worker-candidate"),),
        ),
        epoch_runtime=SimpleNamespace(registry=SimpleNamespace(store_id="store")),
        assert_root_gc_authority_current=lambda: None,
    )
    journal._path = root / "worker-start-gates.jsonl"
    journal._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
    return journal


def test_start_gate_v2_current_and_append_after_retired_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stem = "worker-start-gates"
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        rooted.sibling(stem + ".jsonl.lock").create_new(b"")
        rooted.sibling("worker-activation-state.jsonl.lock").create_new(b"")
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(prepared.index.to_bytes())
        rooted.sibling(DELETION_LEDGER_NAME).create_new(
            CodingWorkerV2DeletionLedger.from_prepared(prepared).to_bytes()
        )
        rooted.sibling(_segment_name(stem, 0)).unlink()
        rooted.sibling(_head_name(stem, 0)).unlink()
        rooted.sibling(_segment_name("worker-activation-state", 0)).unlink()
        rooted.sibling(_head_name("worker-activation-state", 0)).unlink()

    journal = _journal(tmp_path)
    assert journal.current("a" * 32) is None
    current = journal.current("b" * 32)
    assert current is not None and current.phase == "bound"
    assert journal.attempts() == (current,)
    retired = _record(5, attempt_id="a" * 32, bound=False)
    with pytest.raises(CodingWorkerStartGateJournalError, match="attempt_retired"):
        journal.append(
            phase="intent",
            attempt_id=retired.attempt_id,
            worker_identity_fingerprint=retired.worker_identity_fingerprint,
            receipt_fingerprint=retired.receipt_fingerprint,
            policy_fingerprint=retired.policy_fingerprint,
            scope_id=retired.scope_id,
            native_closure_digest=retired.native_closure_digest,
        )
    new = _record(5, attempt_id="c" * 32, bound=False)
    intent = journal.append(
        phase="intent",
        attempt_id=new.attempt_id,
        worker_identity_fingerprint=new.worker_identity_fingerprint,
        receipt_fingerprint=new.receipt_fingerprint,
        policy_fingerprint=new.policy_fingerprint,
        scope_id=new.scope_id,
        native_closure_digest=new.native_closure_digest,
    )
    assert intent.journal_revision == 5
    assert journal.current(new.attempt_id) == intent
    monkeypatch.setattr(gate_module, "_MAX_EVENTS", 1)
    bound_source = _record(6, attempt_id="c" * 32, bound=True)
    bound = journal.append(
        phase="bound",
        attempt_id=bound_source.attempt_id,
        worker_identity_fingerprint=bound_source.worker_identity_fingerprint,
        receipt_fingerprint=bound_source.receipt_fingerprint,
        policy_fingerprint=bound_source.policy_fingerprint,
        scope_id=bound_source.scope_id,
        native_closure_digest=bound_source.native_closure_digest,
        identity=bound_source.identity,
    )
    assert bound.journal_revision == 6
    assert journal.current(new.attempt_id) == bound
    assert not (tmp_path / "worker-start-gates.jsonl").exists()
    with _rooted(tmp_path) as rooted:
        assert (
            read_coding_worker_v2_retained_history(rooted, stem=stem).last_revision == 6
        )
    journal._product.policy.project_scope_id = "other"
    with pytest.raises(CodingWorkerStartGateJournalError, match="v2_owner_changed"):
        journal.current(new.attempt_id)
    journal._product.policy.project_scope_id = "scope"
    (tmp_path / (stem + ".jsonl.lock")).unlink()
    with pytest.raises(CodingWorkerStartGateJournalError, match="lock_missing"):
        journal.current(new.attempt_id)
    assert not (tmp_path / "worker-start-gates.jsonl").exists()
