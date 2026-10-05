"""Portable proof that expiry recovery no longer needs an archive path."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import loushang.coding.package_private_data_windows_backup_expiry_recovery as recovery
from loushang.coding._plugin_lifecycle import CodingPluginLifecycleStateLayout
from loushang.coding.package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from loushang.coding.package_private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreTransaction,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1


def _plan() -> CodingArchPrivateDataBackupExpiryPlanV1:
    return CodingArchPrivateDataBackupExpiryPlanV1(
        installation_key=PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id="workspace:" + "a" * 64,
            plugin_id="coding.arch.default",
        ),
        backup_id="b" * 64,
        backup_receipt_id="arch-backup:" + "b" * 64,
        source_target_id="present:" + "c" * 64,
        confirmation_id="arch-restore-confirm:" + "d" * 64,
        restore_completion_digest="e" * 64,
        restored_target_id="present:" + "f" * 64,
        desired_inventory_revision=3,
        archive_root_identity=(1, 2, stat.S_IFDIR | 0o700, 0, 1),
        archive_target_id="present:" + "1" * 64,
    )


def test_windows_expiry_recovery_checks_restored_bytes_without_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    root = tmp_path / "restored"
    root.mkdir()
    deletion_receipt = SimpleNamespace(
        receipt_id="arch-deletion:test", disposition="deleted"
    )
    deletion = SimpleNamespace(
        phase="completed",
        plan=SimpleNamespace(installation_key=plan.installation_key),
        target=SimpleNamespace(target_id=plan.source_target_id),
        receipt=deletion_receipt,
    )
    confirmation = SimpleNamespace(
        confirmation_id=plan.confirmation_id,
        installation_key=plan.installation_key,
        backup_id=plan.backup_id,
        deletion_receipt_id=deletion_receipt.receipt_id,
        restore_completion_digest=plan.restore_completion_digest,
        restored_target_id=plan.restored_target_id,
        restore_id="arch-restore:test",
    )
    started = SimpleNamespace(phase="started", restore_id=confirmation.restore_id)
    completed = SimpleNamespace(
        phase="completed",
        installation_key=plan.installation_key,
        backup_id=plan.backup_id,
        deletion_receipt_id=deletion_receipt.receipt_id,
        restore_id=confirmation.restore_id,
        record_digest=plan.restore_completion_digest,
    )
    restored_identity = (1, 5, stat.S_IFDIR | 0o700, 0, 1)
    publication = SimpleNamespace(
        parent_identity=(1, 4), stage_identity=restored_identity
    )
    restore = SimpleNamespace(
        state_fd=9,
        _require_active=lambda: None,
        _scan_confirmations=lambda: ((confirmation,), None),
        events=lambda: (started, completed),
        publication_for=lambda event, restore_plan: publication,
    )
    desired = SimpleNamespace(
        inventory_revision=3,
        installation=lambda key: SimpleNamespace(
            latest_instance_revision_ref="present",
            selection=SimpleNamespace(desired_state="absent"),
        ),
    )
    product = SimpleNamespace(
        state_root=tmp_path,
        desired_state=SimpleNamespace(snapshot=lambda: desired),
    )

    class FakeAcl:
        def __enter__(self) -> FakeAcl:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def validate(self, descriptor: int) -> None:
            return None

    monkeypatch.setattr(
        recovery, "coding_arch_installation_private_data_root", lambda layout, key: root
    )
    monkeypatch.setattr(recovery, "WindowsPrivateDirectoryAcl", FakeAcl)
    monkeypatch.setattr(
        recovery,
        "CodingWindowsArchPrivateDataDeletionTransaction",
        lambda state_root, state_fd: SimpleNamespace(
            events=lambda: (deletion,), _close=lambda: None
        ),
    )
    monkeypatch.setattr(
        recovery,
        "inspect_windows_product_private_directory_identity",
        lambda path: (1, 4),
    )
    native_open_directory = recovery.open_windows_directory
    monkeypatch.setattr(
        recovery,
        "open_windows_directory",
        lambda path, **kwargs: (
            native_open_directory(path, **kwargs)
            if os.name == "nt"
            else os.open(path, os.O_RDONLY)
        ),
    )
    monkeypatch.setattr(recovery, "_directory_identity", lambda descriptor: (1, 4))
    monkeypatch.setattr(
        recovery, "windows_listdir_at", lambda descriptor: ("restored",)
    )
    monkeypatch.setattr(
        recovery,
        "inspect_coding_windows_arch_installation_root",
        lambda layout, key, state_root: restored_identity[:2],
    )
    current = SimpleNamespace(
        root_identity=restored_identity, target_id=plan.restored_target_id
    )
    monkeypatch.setattr(
        recovery,
        "_capture_windows_target_snapshot",
        lambda path, expected_root: current,
    )
    layout_mock = cast(CodingPluginLifecycleStateLayout, SimpleNamespace())
    product_mock = cast(WindowsLocalWheelProductSessionOwner, product)
    restore_mock = cast(CodingWindowsArchPrivateDataRestoreTransaction, restore)

    recovery.require_windows_arch_backup_expiry_recovery_authority(
        layout_mock, product_mock, restore_mock, plan
    )
    current.target_id = "present:" + "0" * 64
    with pytest.raises(ValueError, match="restored bytes changed"):
        recovery.require_windows_arch_backup_expiry_recovery_authority(
            layout_mock, product_mock, restore_mock, plan
        )
    current.target_id = plan.restored_target_id
    desired.inventory_revision = 4
    with pytest.raises(ValueError, match="Desired State changed"):
        recovery.require_windows_arch_backup_expiry_recovery_authority(
            layout_mock, product_mock, restore_mock, plan
        )
    desired.inventory_revision = 3
    deletion_receipt.receipt_id = "arch-deletion:foreign"
    with pytest.raises(ValueError, match="confirmation changed"):
        recovery.require_windows_arch_backup_expiry_recovery_authority(
            layout_mock, product_mock, restore_mock, plan
        )
    deletion_receipt.receipt_id = confirmation.deletion_receipt_id
    publication.stage_identity = (1, 6, stat.S_IFDIR | 0o700, 0, 1)
    with pytest.raises(ValueError, match="root binding changed"):
        recovery.require_windows_arch_backup_expiry_recovery_authority(
            layout_mock, product_mock, restore_mock, plan
        )
