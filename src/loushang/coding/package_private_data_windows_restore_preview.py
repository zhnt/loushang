"""Read-only Product proof for restoring a Windows Arch private-data backup.

An archive being readable does not grant write authority. This preview binds
the exact retained bytes to the latest completed deletion and an absent target.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionReceiptV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_listdir_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_installation_private_data import (
    coding_arch_installation_private_data_root,
    inspect_coding_windows_arch_installation_root,
)
from .package_private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    backup_parent,
)
from .package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from .package_private_data_restore_records import CodingArchPrivateDataRestorePlanV1
from .package_private_data_windows_backup import (
    _directory_identity,
    _read_archive_manifest,
    _verify_archive,
)
from .package_private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataRestorePreview:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)

    def preview(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataRestorePlanV1:
        root = coding_arch_installation_private_data_root(self.layout, key)
        if len(backup_id) != 64 or any(
            character not in "0123456789abcdef" for character in backup_id
        ):
            raise ValueError("Windows Coding Arch restore backup ID is invalid")
        preview = CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        with preview._offline(), WindowsPrivateDirectoryAcl() as acl:
            desired = self.product.desired_state.snapshot()
            state = desired.installation(key)
            if (
                state.latest_instance_revision_ref is None
                or state.selection.desired_state != "absent"
            ):
                raise ValueError("Windows Coding Arch restore requires Product removal")
            with (
                self.product.epoch_runtime.borrow_product_state_root_descriptor() as fd
            ):
                acl.validate(fd)
                transaction = CodingWindowsArchPrivateDataDeletionTransaction(
                    self.product.state_root, fd
                )
                try:
                    events = transaction.events()
                finally:
                    transaction._close()
            if events and events[-1].phase != "completed":
                raise ValueError("Windows Coding Arch deletion is unfinished")
            parent_path = backup_parent(self.layout, key)
            parent_identity = inspect_windows_product_private_directory_identity(
                parent_path
            )
            parent_fd = open_windows_directory(
                parent_path, share_delete=False, read_control=True
            )
            try:
                acl.validate(parent_fd)
                if _directory_identity(parent_fd) != parent_identity:
                    raise ValueError("Windows Coding Arch backup parent changed")
                if any(
                    name.endswith(".staging") for name in windows_listdir_at(parent_fd)
                ):
                    raise ValueError("Windows Coding Arch backup stage needs recovery")
                receipt, source = _read_archive_manifest(parent_fd, backup_id, acl)
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Windows Coding Arch backup Installation changed")
                deletion_receipt = _matching_latest_deletion(events, key, receipt)
                if deletion_receipt is None:
                    raise ValueError("Windows Coding Arch restore lacks deletion")
                _verify_archive(
                    parent_fd, parent_path, backup_id, key, source, receipt, acl
                )
            finally:
                os.close(parent_fd)
                if (
                    inspect_windows_product_private_directory_identity(parent_path)
                    != parent_identity
                ):
                    raise ValueError("Windows Coding Arch backup parent changed")
            if (
                inspect_coding_windows_arch_installation_root(
                    self.layout, key, state_root=self.product.state_root
                )
                is not None
            ):
                raise ValueError("Windows Coding Arch restore target is present")
            _require_no_restore_stage(root, acl)
            return CodingArchPrivateDataRestorePlanV1(
                installation_key=key,
                backup_id=backup_id,
                deletion_receipt_id=deletion_receipt.receipt_id,
                source_target_id=source.target_id,
                desired_inventory_revision=desired.inventory_revision,
                target_state="absent",
            )


def _matching_latest_deletion(
    events: tuple[CodingArchPrivateDataDeletionEventV1, ...],
    key: PluginInstallationKeyV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
) -> PluginPrivateDataDeletionReceiptV1 | None:
    for event in reversed(events):
        if event.plan.installation_key != key:
            continue
        if (
            event.phase == "completed"
            and event.target.target_id == receipt.source_target_id
            and event.receipt is not None
            and event.receipt.disposition == "deleted"
        ):
            return event.receipt
        return None
    return None


def _require_no_restore_stage(root: Path, acl: WindowsPrivateDirectoryAcl) -> None:
    parent_identity = inspect_windows_product_private_directory_identity(root.parent)
    descriptor = open_windows_directory(
        root.parent, share_delete=False, read_control=True
    )
    try:
        acl.validate(descriptor)
        if _directory_identity(descriptor) != parent_identity:
            raise ValueError("Windows Coding Arch restore parent changed")
        names = windows_listdir_at(descriptor)
        if root.name in names or any(
            name.startswith(".arch-restore-") for name in names
        ):
            raise ValueError("Windows Coding Arch restore target has state debt")
        acl.validate(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["CodingWindowsArchPrivateDataRestorePreview"]
