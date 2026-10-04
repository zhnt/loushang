"""Durable state machine for an exact Arch Installation backup expiry."""

from __future__ import annotations

import os
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.package_private_data_backup_expiry import (
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from loushang.coding.package_private_data_backup_expiry_journal import (
    CodingArchPrivateDataBackupExpiryJournal,
    CodingArchPrivateDataBackupExpiryReceiptV1,
)
from loushang.coding.package_private_data_deletion_preview import (
    _capture_target_snapshot,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


@pytest.mark.skipif(os.name != "posix", reason="POSIX Arch backup expiry")
def test_backup_expiry_journal_requires_exact_order_and_reopens_receipt(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "product-state"
    state_root.mkdir(mode=0o700)
    archive = tmp_path / "archive"
    archive.mkdir(mode=0o700)
    (archive / "manifest.json").write_bytes(b"retained")
    snapshot = _capture_target_snapshot(archive, private_base=tmp_path)
    assert snapshot.root_identity is not None
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-test",
        plugin_id="coding.arch.default",
    )
    backup_id = sha256(b"backup").hexdigest()
    plan = CodingArchPrivateDataBackupExpiryPlanV1(
        installation_key=key,
        backup_id=backup_id,
        backup_receipt_id="arch-backup:" + backup_id,
        source_target_id="present:" + sha256(b"source").hexdigest(),
        confirmation_id="arch-restore-confirm:" + sha256(b"restore").hexdigest(),
        restore_completion_digest=sha256(b"completion").hexdigest(),
        restored_target_id="present:" + sha256(b"target").hexdigest(),
        desired_inventory_revision=2,
        archive_root_identity=snapshot.root_identity,
        archive_target_id=snapshot.target_id,
    )
    journal = CodingArchPrivateDataBackupExpiryJournal(state_root)
    confirmation = journal.confirm(
        plan, actor_id="operator:uid-1000", policy_revision="test:1"
    )
    assert (
        journal.confirm(plan, actor_id="operator:uid-1000", policy_revision="test:1")
        == confirmation
    )
    with pytest.raises(ValueError, match="unfinished"):
        journal.confirm(plan, actor_id="other", policy_revision="test:1")
    started = journal.begin(plan, confirmation, snapshot)
    assert started.phase == "started"
    assert journal.begin(plan, confirmation, snapshot) == started
    with pytest.raises(ValueError, match="out of order"):
        journal.advance(started, "completed")
    renamed = journal.advance(started, "renamed")
    assert journal.advance(renamed, "renamed") == renamed
    completed = journal.advance(renamed, "completed")
    assert completed.receipt == CodingArchPrivateDataBackupExpiryReceiptV1.create(
        plan, confirmation
    )
    assert journal.begin(plan, confirmation, snapshot) == completed
    assert tuple(
        item.phase
        for item in CodingArchPrivateDataBackupExpiryJournal(state_root).events()
    ) == ("confirmed", "started", "renamed", "completed")
    assert (
        CodingArchPrivateDataBackupExpiryReceiptV1.from_dict(
            completed.receipt.to_dict()
        )
        == completed.receipt
    )
    with pytest.raises(ValueError, match="already completed"):
        journal.confirm(plan, actor_id="other", policy_revision="test:1")
    with pytest.raises(ValueError, match="already completed"):
        journal.confirm(
            replace(plan, desired_inventory_revision=3),
            actor_id="operator:uid-1000",
            policy_revision="test:1",
        )
    journal.path.write_bytes(journal.path.read_bytes() + b'{"partial":')
    with pytest.raises(ValueError):
        journal.events()
