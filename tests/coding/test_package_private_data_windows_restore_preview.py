"""Portable evidence selection for Windows Arch restore preview."""

from __future__ import annotations

import stat

from loushang.coding.package_private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    backup_id,
)
from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.coding.package_private_data_windows_restore_preview import (
    _matching_latest_deletion,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


def _deletion_event(
    key: PluginInstallationKeyV1,
    target: CodingArchPrivateDataTargetSnapshotV1,
    *,
    revision: int,
    completed: bool,
) -> CodingArchPrivateDataDeletionEventV1:
    plan = PluginPrivateDataDeletionPlanV1(
        key, "coding.arch.private-data:windows-v1", target.target_id
    )
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan_fingerprint=plan.fingerprint,
        confirmation_id=f"windows-restore-preview:{revision}",
    )
    receipt = (
        PluginPrivateDataDeletionReceiptV1(
            installation_key=key,
            owner_id=plan.owner_id,
            target_id=plan.target_id,
            plan_fingerprint=plan.fingerprint,
            confirmation_id=confirmation.confirmation_id,
            receipt_id=f"windows-restore-deletion:{revision}",
            disposition="deleted",
        )
        if completed
        else None
    )
    return CodingArchPrivateDataDeletionEventV1(
        revision,
        "completed" if completed else "started",
        plan,
        confirmation,
        target,
        receipt,
    )


def test_windows_restore_requires_latest_matching_completed_deletion() -> None:
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace:" + "a" * 64,
        plugin_id="coding.arch.default",
    )
    target = CodingArchPrivateDataTargetSnapshotV1(
        "b" * 64, (1, 2, stat.S_IFDIR | 0o700, 0, 3), ()
    )
    backup_identifier = backup_id(key, target)
    backup = CodingArchPrivateDataBackupReceiptV1(
        installation_key=key,
        source_target_id=target.target_id,
        backup_id=backup_identifier,
        file_count=0,
        byte_count=0,
        receipt_id="arch-backup:" + backup_identifier,
    )
    completed = _deletion_event(key, target, revision=3, completed=True)
    assert _matching_latest_deletion((completed,), key, backup) == completed.receipt

    pending = _deletion_event(key, target, revision=4, completed=False)
    assert _matching_latest_deletion((completed, pending), key, backup) is None

    later_target = CodingArchPrivateDataTargetSnapshotV1(
        "b" * 64, (1, 99, stat.S_IFDIR | 0o700, 0, 4), ()
    )
    later = _deletion_event(key, later_target, revision=6, completed=True)
    assert _matching_latest_deletion((completed, later), key, backup) is None
