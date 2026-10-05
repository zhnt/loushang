"""Portable chain validation for native Windows deletion receipts."""

from __future__ import annotations

import json
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package_private_data_windows_deletion_journal as journal_module
from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.coding.package_private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction,
    _decode_event,
    _validate_sequence,
    windows_arch_deletion_receipt_id,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)


def _events(*, present: bool) -> tuple[CodingArchPrivateDataDeletionEventV1, ...]:
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "a" * 64,
        plugin_id="coding.arch.default",
    )
    target = CodingArchPrivateDataTargetSnapshotV1(
        root_path_digest="b" * 64,
        root_identity=(1, 2, stat.S_IFDIR | 0o700, 0, 3) if present else None,
        members=(),
    )
    plan = PluginPrivateDataDeletionPlanV1(
        key, "coding.arch.private-data:windows-v1", target.target_id
    )
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint,
        confirmation_id="arch-private-data:portable-deletion",
    )
    start = CodingArchPrivateDataDeletionEventV1(
        1, "started", plan, confirmation, target
    )
    receipt = PluginPrivateDataDeletionReceiptV1(
        installation_key=key,
        owner_id=plan.owner_id,
        target_id=plan.target_id,
        plan_fingerprint=plan.fingerprint,
        confirmation_id=confirmation.confirmation_id,
        receipt_id=windows_arch_deletion_receipt_id(plan, confirmation),
        disposition="deleted" if present else "already_absent",
    )
    if present:
        renamed = CodingArchPrivateDataDeletionEventV1(
            2, "renamed", plan, confirmation, target
        )
        completed = CodingArchPrivateDataDeletionEventV1(
            3, "completed", plan, confirmation, target, receipt
        )
        return start, renamed, completed
    completed = CodingArchPrivateDataDeletionEventV1(
        2, "completed", plan, confirmation, target, receipt
    )
    return start, completed


@pytest.mark.parametrize("present", [False, True])
def test_windows_deletion_event_chain_requires_exact_phases(present: bool) -> None:
    events = _events(present=present)
    _validate_sequence(events)
    for event in events:
        assert _decode_event(canonical_json_bytes(event.to_dict()) + b"\n") == event
    with pytest.raises(ValueError, match="completion has no start"):
        _validate_sequence(
            (events[0], replace(events[-1], revision=2))
            if present
            else (replace(events[-1], revision=1),)
        )
    with pytest.raises(ValueError, match="starts conflict"):
        _validate_sequence((events[0], replace(events[0], revision=2)))
    with pytest.raises(ValueError, match="noncanonical"):
        _decode_event(json.dumps(events[0].to_dict(), indent=2).encode("utf-8"))
    with pytest.raises(ValueError, match="invalid"):
        _decode_event(b'{"revision":1,"revision":1}')


def test_windows_deletion_transaction_cannot_escape_offline_gate() -> None:
    transaction = CodingWindowsArchPrivateDataDeletionTransaction(
        Path("/unused-product-state"), -1
    )
    transaction._close()
    with pytest.raises(ValueError, match="transaction is closed"):
        transaction.events()


def test_windows_present_deletion_completes_after_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, renamed, completed = _events(present=True)
    transaction = CodingWindowsArchPrivateDataDeletionTransaction(
        tmp_path,
        -1,
        SimpleNamespace(layout=object(), product=object()),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(transaction.__class__, "_scan", lambda _self: ((started, renamed), None))
    monkeypatch.setattr(
        transaction.__class__, "_require_confirmation", lambda _self, _plan, _confirmation: None
    )
    monkeypatch.setattr(transaction.__class__, "_append", lambda _self, _before, _staged, event: event)
    monkeypatch.setattr(
        journal_module,
        "coding_arch_installation_private_data_root",
        lambda _layout, _key: tmp_path / "absent-root",
    )
    monkeypatch.setattr(
        journal_module, "_require_windows_tombstone", lambda _owner, _started, *, present: None
    )
    assert completed.receipt is not None
    assert transaction.record_completion(started, completed.receipt) == completed
    monkeypatch.setattr(
        transaction.__class__,
        "_scan",
        lambda _self: ((started, renamed, completed), None),
    )
    assert transaction.record_completion(started, completed.receipt) == completed
