"""Read-only Windows candidate for independently confirmed Arch backup expiry."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
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
)
from .package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from .package_private_data_backup_records import _digest, backup_parent
from .package_private_data_restore_records import CodingArchPrivateDataRestorePlanV1
from .package_private_data_windows_archive_snapshot import (
    capture_windows_arch_backup_archive,
)
from .package_private_data_windows_backup import (
    _directory_identity,
    _read_archive_manifest,
)
from .package_private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction,
)
from .package_private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
)
from .package_private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreJournal,
    CodingWindowsArchPrivateDataRestoreTransaction,
)
from .package_private_data_windows_restore_preview import _matching_latest_deletion


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataBackupExpiryPreview:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)

    def preview(
        self,
        key: PluginInstallationKeyV1,
        backup_id: str,
        confirmation_id: str,
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        """Bind exact Product, restore, archive, and independent confirmation."""

        with CodingWindowsArchPrivateDataRestoreJournal(
            self.layout, self.product
        ).transaction() as transaction:
            return self._preview_locked(transaction, key, backup_id, confirmation_id)

    def _preview_locked(
        self,
        transaction: CodingWindowsArchPrivateDataRestoreTransaction,
        key: PluginInstallationKeyV1,
        backup_id: str,
        confirmation_id: str,
    ) -> CodingArchPrivateDataBackupExpiryPlanV1:
        coding_arch_installation_private_data_root(self.layout, key)
        if (
            not _digest(backup_id)
            or not isinstance(confirmation_id, str)
            or not confirmation_id.startswith("arch-restore-confirm:")
        ):
            raise ValueError("Windows Coding Arch backup expiry request is invalid")
        desired = self.product.desired_state.snapshot()
        state = desired.installation(key)
        if (
            state.latest_instance_revision_ref is None
            or state.selection.desired_state != "absent"
        ):
            raise ValueError("Windows Coding Arch backup expiry requires removal")
        parent_path = backup_parent(self.layout, key)
        parent_identity = inspect_windows_product_private_directory_identity(
            parent_path
        )
        with WindowsPrivateDirectoryAcl() as acl:
            parent_fd = open_windows_directory(
                parent_path, share_delete=False, read_control=True
            )
            try:
                acl.validate(parent_fd)
                if (
                    _directory_identity(parent_fd) != parent_identity
                    or any(
                        name.endswith(".staging")
                        for name in windows_listdir_at(parent_fd)
                    )
                ):
                    raise ValueError("Windows Coding Arch backup parent changed")
                receipt, source = _read_archive_manifest(
                    parent_fd, backup_id, acl
                )
                if receipt.installation_key != key or receipt.backup_id != backup_id:
                    raise ValueError("Windows Coding Arch backup Installation changed")
            finally:
                os.close(parent_fd)
                if (
                    inspect_windows_product_private_directory_identity(
                        parent_path
                    )
                    != parent_identity
                ):
                    raise ValueError("Windows Coding Arch backup parent changed")
        deletion = CodingWindowsArchPrivateDataDeletionTransaction(
            self.product.state_root, transaction.state_fd
        )
        try:
            events = deletion.events()
        finally:
            deletion._close()
        if events and events[-1].phase != "completed":
            raise ValueError("Windows Coding Arch deletion is unfinished")
        deletion_receipt = _matching_latest_deletion(events, key, receipt)
        if deletion_receipt is None:
            raise ValueError("Windows Coding Arch backup expiry lacks deletion")
        restore_plan = CodingArchPrivateDataRestorePlanV1(
            installation_key=key,
            backup_id=backup_id,
            deletion_receipt_id=deletion_receipt.receipt_id,
            source_target_id=source.target_id,
            desired_inventory_revision=desired.inventory_revision,
            target_state="absent",
        )
        restore_plan = replace(
            restore_plan,
            desired_inventory_revision=(
                transaction.completed_plan_revision_for(restore_plan)
            ),
        )
        confirmation = transaction.verify_confirmation(
            restore_plan, confirmation_id
        )
        completion, restored = transaction._completed_restore(restore_plan)
        archive = capture_windows_arch_backup_archive(
            self.layout, key, backup_id, source, receipt
        )
        if archive.root_identity is None:
            raise ValueError("Windows Coding Arch backup archive disappeared")
        if (
            transaction.verify_confirmation(restore_plan, confirmation_id)
            != confirmation
        ):
            raise ValueError("Windows Coding Arch restore confirmation changed")
        return CodingArchPrivateDataBackupExpiryPlanV1(
            installation_key=key,
            backup_id=backup_id,
            backup_receipt_id=receipt.receipt_id,
            source_target_id=source.target_id,
            confirmation_id=confirmation.confirmation_id,
            restore_completion_digest=completion.record_digest,
            restored_target_id=restored.target_id,
            desired_inventory_revision=desired.inventory_revision,
            archive_root_identity=archive.root_identity,
            archive_target_id=archive.target_id,
        )


__all__ = ["CodingWindowsArchPrivateDataBackupExpiryPreview"]
