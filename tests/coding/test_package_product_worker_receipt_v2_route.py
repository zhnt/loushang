"""Receipt issue and retained reads use V2 after the old segment is removed."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_product_worker_receipt as receipt_module
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
from loushang.coding.package_product_worker_receipt import (
    CodingWorkerProductReceiptOwner,
    CodingWorkerReceiptError,
    read_coding_product_worker_receipt_record,
    read_coding_product_worker_receipt_records,
)
from loushang.harness.journal import DURABLE_LOCKED_JOURNAL, JournalLoadPolicy
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from tests.coding.test_package_product_worker_history_read_v2 import _write_sources
from tests.coding.test_package_product_worker_history_stage_v2 import _rooted
from tests.harness.worker.test_product_activation import _policy


def _product(root: Path) -> PosixLocalWheelProductSessionOwner:
    # A Product shell allows the real receipt IO path without a Wheel runtime.
    product = object.__new__(PosixLocalWheelProductSessionOwner)
    object.__setattr__(product, "state_root", root)
    object.__setattr__(
        product,
        "gc_gate",
        PluginPackageGcReservationJournal(root / "gc-reservations.jsonl"),
    )
    object.__setattr__(product, "policy", SimpleNamespace(project_scope_id="scope"))
    object.__setattr__(
        product,
        "epoch_runtime",
        SimpleNamespace(registry=SimpleNamespace(store_id="store")),
    )
    return product


def test_receipt_v2_issue_and_retained_read_after_retired_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stem = "worker-activation-receipts"
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
    product = _product(tmp_path)
    with pytest.raises(CodingWorkerReceiptError, match="v2_full_history_unavailable"):
        read_coding_product_worker_receipt_records(product)
    assert read_coding_product_worker_receipt_records(product, retained_only=True) == ()
    policy = replace(_policy(), product_scope_id="scope")
    decision = SimpleNamespace(
        action="allow", opt_in=object(), decision_digest="a" * 64
    )
    owner = object.__new__(CodingWorkerProductReceiptOwner)
    owner._product = product
    owner._selected = SimpleNamespace(  # type: ignore[assignment]
        snapshot=SimpleNamespace(
            installation_key=SimpleNamespace(plugin_id=policy.plugin_id)
        )
    )
    owner._opt_in = SimpleNamespace(current=lambda _plugin: decision)  # type: ignore[assignment]
    owner._runtime = SimpleNamespace(  # type: ignore[assignment]
        session_id=policy.session_id,
        product_runtime_id=policy.product_runtime_id,
    )
    owner._path = tmp_path / (stem + ".jsonl")
    owner._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
    owner._load_policy = JournalLoadPolicy(partial_tail="raise", create_lock=False)
    owner._derive = lambda _opt_in: policy  # type: ignore[method-assign]

    first = owner.issue()
    assert first is not None and first.issue_sequence == 2
    assert owner.issue() == first
    decision.decision_digest = "b" * 64
    monkeypatch.setattr(receipt_module, "_MAX_RECEIPTS", 1)
    second = owner.issue()
    assert second is not None and second.issue_sequence == 3
    assert second.fingerprint != first.fingerprint
    assert not owner.path.exists()
    records = read_coding_product_worker_receipt_records(product, retained_only=True)
    assert tuple(record.receipt for record in records) == (first, second)
    assert owner.current_witness(second) == second.authority_witness
    assert owner.current_witness(first) != first.authority_witness
    assert (
        read_coding_product_worker_receipt_record(
            product, receipt_fingerprint=first.fingerprint
        )
        == records[0]
    )
    with _rooted(tmp_path) as rooted:
        assert (
            read_coding_worker_v2_retained_history(rooted, stem=stem).last_revision == 3
        )

    product.policy.project_scope_id = "other"
    with pytest.raises(CodingWorkerReceiptError, match="v2_owner_changed"):
        read_coding_product_worker_receipt_records(product, retained_only=True)
    product.policy.project_scope_id = "scope"
    (tmp_path / (stem + ".jsonl.lock")).unlink()
    with pytest.raises(CodingWorkerReceiptError, match="lock_missing"):
        owner.issue()
    assert not owner.path.exists()
