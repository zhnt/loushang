from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionJournal,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


def _sample() -> tuple[
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionConfirmationV1,
    CodingArchPrivateDataTargetSnapshotV1,
    PluginPrivateDataDeletionReceiptV1,
]:
    target = CodingArchPrivateDataTargetSnapshotV1("a" * 64, None, ())
    plan = PluginPrivateDataDeletionPlanV1(
        installation_key=PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id="workspace:" + "b" * 64,
            plugin_id="coding.arch.default",
        ),
        owner_id="coding.arch.private-data:posix-v1",
        target_id=target.target_id,
    )
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint,
        confirmation_id="operator:confirmed-1",
    )
    receipt = PluginPrivateDataDeletionReceiptV1(
        installation_key=plan.installation_key,
        owner_id=plan.owner_id,
        target_id=plan.target_id,
        plan_fingerprint=plan.fingerprint,
        confirmation_id=confirmation.confirmation_id,
        receipt_id="arch-data-deletion:1",
        disposition="already_absent",
    )
    return plan, confirmation, target, receipt


@pytest.mark.skipif(os.name != "posix", reason="POSIX private journal")
def test_private_data_deletion_journal_replays_exact_start_and_receipt(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "product-state"
    state_root.mkdir(mode=0o700)
    journal = CodingArchPrivateDataDeletionJournal(state_root)
    plan, confirmation, target, receipt = _sample()
    started = journal.record_start(plan, confirmation, target)
    assert started.revision == 1
    assert journal.record_start(plan, confirmation, target) == started
    assert journal.started_for(plan) == started
    assert journal.receipt_for(plan, confirmation) is None

    completed = journal.record_completion(started, receipt)
    assert completed.revision == 2
    assert journal.record_completion(started, receipt) == completed
    reopened = CodingArchPrivateDataDeletionJournal(state_root)
    assert reopened.started_for(plan) is None
    assert reopened.receipt_for(plan, confirmation) == receipt
    assert tuple(event.revision for event in reopened.events()) == (1, 2)
    with pytest.raises(ValueError, match="already consumed"):
        reopened.record_start(plan, confirmation, target)


@pytest.mark.skipif(os.name != "posix", reason="POSIX private journal")
def test_private_data_deletion_journal_refuses_conflict_and_corruption(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "product-state"
    state_root.mkdir(mode=0o700)
    journal = CodingArchPrivateDataDeletionJournal(state_root)
    plan, confirmation, target, receipt = _sample()
    started = journal.record_start(plan, confirmation, target)
    conflicting = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint,
        confirmation_id="operator:changed",
    )
    with pytest.raises(ValueError, match="unfinished"):
        journal.record_start(plan, conflicting, target)
    with pytest.raises(ValueError, match="receipt changed"):
        journal.record_completion(
            started,
            PluginPrivateDataDeletionReceiptV1(
                installation_key=receipt.installation_key,
                owner_id=receipt.owner_id,
                target_id=receipt.target_id,
                plan_fingerprint=receipt.plan_fingerprint,
                confirmation_id="operator:foreign",
                receipt_id=receipt.receipt_id,
                disposition=receipt.disposition,
            ),
        )
    assert journal.started_for(plan) == started
    original = journal.path.read_text(encoding="utf-8")
    first = json.loads(original)
    assert first["revision"] == 1
    journal.path.write_text(
        original.replace('"revision": 1,', '"revision": 1, "revision": 2,'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        journal.events()


@pytest.mark.skipif(os.name != "posix", reason="POSIX private journal")
def test_present_private_data_requires_durable_rename_before_completion(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "product-state"
    state_root.mkdir(mode=0o700)
    journal = CodingArchPrivateDataDeletionJournal(state_root)
    _, _, absent, _ = _sample()
    target = CodingArchPrivateDataTargetSnapshotV1(
        absent.root_path_digest,
        (1, 2, stat.S_IFDIR | 0o700, 4096, 3),
        (),
    )
    sample_plan, _, _, _ = _sample()
    plan = PluginPrivateDataDeletionPlanV1(
        installation_key=sample_plan.installation_key,
        owner_id=sample_plan.owner_id,
        target_id=target.target_id,
    )
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint, confirmation_id="operator:present"
    )
    receipt = PluginPrivateDataDeletionReceiptV1(
        installation_key=plan.installation_key,
        owner_id=plan.owner_id,
        target_id=plan.target_id,
        plan_fingerprint=plan.fingerprint,
        confirmation_id=confirmation.confirmation_id,
        receipt_id="arch-data-deletion:present",
        disposition="deleted",
    )
    started = journal.record_start(plan, confirmation, target)
    with pytest.raises(ValueError, match="rename evidence"):
        journal.record_completion(started, receipt)
    renamed = journal.record_renamed(started)
    assert journal.record_renamed(started) == renamed
    assert journal.current_start() == renamed
    completed = journal.record_completion(renamed, receipt)
    assert completed.revision == 3
    assert (
        CodingArchPrivateDataDeletionJournal(state_root).receipt_for(plan, confirmation)
        == receipt
    )
