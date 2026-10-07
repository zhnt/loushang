"""Product opt-in routes through the V2 owner after retired bytes are gone."""

from __future__ import annotations

from pathlib import Path

import pytest

import loushang.coding.package_product_worker_opt_in as opt_in_module
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
from loushang.coding.package_product_worker_opt_in import (
    CodingWorkerOptInJournal,
    CodingWorkerOptInJournalError,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted


def test_product_opt_in_v2_reads_and_writes_after_retired_segment_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        rooted.sibling("worker-opt-in.jsonl.lock").create_new(b"")
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(prepared.index.to_bytes())
        rooted.sibling(DELETION_LEDGER_NAME).create_new(
            CodingWorkerV2DeletionLedger.from_prepared(prepared).to_bytes()
        )
        rooted.sibling(_segment_name("worker-opt-in", 0)).unlink()
        rooted.sibling(_head_name("worker-opt-in", 0)).unlink()

    journal = CodingWorkerOptInJournal(
        tmp_path / "worker-opt-in.jsonl",
        scope_id="scope",
        gc_gate=PluginPackageGcReservationJournal(tmp_path / "gc-reservations.jsonl"),
        store_id="store",
    )
    assert journal.current("plugin-a").generation == 3  # type: ignore[union-attr]
    assert journal.current_read_only("plugin-a").generation == 3  # type: ignore[union-attr]
    with pytest.raises(
        CodingWorkerOptInJournalError, match="v2_full_history_unavailable"
    ):
        journal.history_read_only()
    with pytest.raises(CodingWorkerOptInJournalError, match="operation_retired"):
        journal.change(
            plugin_id="plugin-a",
            operation_id="allow-a1",
            expected_generation=3,
            action="revoke",
            opt_in=None,
        )
    decision = journal.change(
        plugin_id="plugin-a",
        operation_id="revoke-a4",
        expected_generation=3,
        action="revoke",
        opt_in=None,
    )
    assert decision.journal_revision == 5
    assert decision.generation == 4
    assert journal.current("plugin-a") == decision
    assert (
        journal.change(
            plugin_id="plugin-a",
            operation_id="revoke-a4",
            expected_generation=3,
            action="revoke",
            opt_in=None,
        )
        == decision
    )
    monkeypatch.setattr(opt_in_module, "_MAX_EVENTS", 1)
    second = journal.change(
        plugin_id="plugin-b",
        operation_id="revoke-b2",
        expected_generation=1,
        action="revoke",
        opt_in=None,
    )
    assert second.journal_revision == 6
    assert journal.current("plugin-b") == second
    assert not (tmp_path / "worker-opt-in.jsonl").exists()
    with _rooted(tmp_path) as rooted:
        assert (
            read_coding_worker_v2_retained_history(
                rooted, stem="worker-opt-in"
            ).last_revision
            == 6
        )
    wrong_scope = CodingWorkerOptInJournal(
        journal.path,
        scope_id="other",
        gc_gate=journal.gc_gate,
        store_id="store",
    )
    with pytest.raises(CodingWorkerOptInJournalError, match="v2_owner_changed"):
        wrong_scope.current("plugin-a")
    (tmp_path / "worker-opt-in.jsonl.lock").unlink()
    with pytest.raises(CodingWorkerOptInJournalError, match="lock_missing"):
        journal.change(
            plugin_id="plugin-a",
            operation_id="revoke-a5",
            expected_generation=4,
            action="revoke",
            opt_in=None,
        )
    assert not (tmp_path / "worker-opt-in.jsonl").exists()
