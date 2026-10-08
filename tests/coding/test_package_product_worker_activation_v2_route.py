"""Product C5 CAS stays anchored after a retired V1 segment is removed."""

from __future__ import annotations

from pathlib import Path

import pytest

import loushang.coding.package_product_worker_activation_state_journal as activation_module
from loushang.coding.package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
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
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournalError,
)
from loushang.harness.worker.product_activation import _AttemptKey
from tests.coding.test_package_product_worker_activation_base_v2 import _states
from tests.coding.test_package_product_worker_activation_segments import (
    _next_state,
    _registered_attempt,
)
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted


def test_activation_v2_cas_after_retired_segment_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stem = "worker-activation-state"
    with _rooted(tmp_path) as rooted:
        prepared = _write_sources(rooted)
        rooted.sibling(stem + ".jsonl.lock").create_new(b"")
        rooted.sibling(PRODUCT_OWNER_INDEX_NAME).create_new(prepared.index.to_bytes())
        rooted.sibling(DELETION_LEDGER_NAME).create_new(
            CodingWorkerV2DeletionLedger.from_prepared(prepared).to_bytes()
        )
        rooted.sibling(_segment_name(stem, 0)).unlink()
        rooted.sibling(_head_name(stem, 0)).unlink()

    path = tmp_path / (stem + ".jsonl")
    journal = CodingProductWorkerActivationStateJournal(
        path, scope_id="scope", store_id="store"
    )
    prior = _states()[-1]
    assert journal.initialized_read_only()
    assert journal.load() == prior
    assert journal.load_read_only() == prior
    assert journal.load_with_presence_read_only() == (True, prior)
    assert not journal.compare_and_swap(expected_revision=4, document=prior)
    retained = journal.retained_attempts_read_only()
    assert len(retained) == 1
    assert retained[0].attempt_id == "b" * 32
    assert retained[0].phase == "settled"
    assert not retained[0].current
    next_state = _next_state(prior)
    assert journal.compare_and_swap(expected_revision=5, document=next_state)
    assert journal.load_read_only() == next_state
    assert journal.retained_attempts_read_only() == retained

    reused = _next_state(next_state)
    key = _AttemptKey("a" * 64, "b" * 32, 1).encoded
    reused["attempts"] = {
        key: _registered_attempt(receipt="a" * 64, attempt_id="b" * 32)
    }
    with pytest.raises(WorkerActivationStateJournalError, match="history_conflict"):
        journal.compare_and_swap(expected_revision=6, document=reused)

    monkeypatch.setattr(activation_module, "_MAX_REVISIONS", 1)
    rotated = _next_state(next_state)
    assert journal.compare_and_swap(expected_revision=6, document=rotated)
    assert journal.load_read_only() == rotated
    assert not path.exists()
    with _rooted(tmp_path) as rooted:
        assert (
            read_coding_worker_v2_retained_history(rooted, stem=stem).last_revision == 7
        )

    ownerless = CodingProductWorkerActivationStateJournal(path)
    assert ownerless.load_read_only() == rotated
    with pytest.raises(
        WorkerActivationStateJournalError, match="checkpoint_owner_required"
    ):
        ownerless.compare_and_swap(expected_revision=7, document=_next_state(rotated))
    wrong_owner = CodingProductWorkerActivationStateJournal(
        path, scope_id="other", store_id="store"
    )
    with pytest.raises(WorkerActivationStateJournalError, match="v2_owner_changed"):
        wrong_owner.load_read_only()
    path.with_name(stem + ".jsonl.lock").unlink()
    with pytest.raises(WorkerActivationStateJournalError, match="lock_missing"):
        journal.load_read_only()
    assert not path.exists()
