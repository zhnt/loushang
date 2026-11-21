"""Read-only Windows candidate for independently confirmed Arch backup expiry."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_deletion_windows import (
    read_windows_deletion_history,
    require_finished_windows_deletion,
)
from loushang.harness.plugin_management._private_data_restore_windows import (
    read_windows_expiry_restore_proof,
    require_windows_restore_product_state,
)
from loushang.harness.plugin_management.private_data_deletion import (
    latest_deleted_target_receipt as latest_deleted_target_receipt,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .private_data_backup_expiry_records import CodingArchPrivateDataBackupExpiryPlanV1
from .private_data_backup_records import _digest as _digest
from .private_data_backup_records import backup_parent as backup_parent
from .private_data_restore_records import (
    CodingArchPrivateDataRestorePlanV1 as CodingArchPrivateDataRestorePlanV1,
)
from .private_data_windows_archive_snapshot import (
    capture_windows_arch_backup_archive as capture_windows_arch_backup_archive,
)
from .private_data_windows_backup import _archive_io as _archive_io
from .private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction as CodingWindowsArchPrivateDataDeletionTransaction,
)
from .private_data_windows_preview import CodingWindowsArchPrivateDataReadPreview
from .private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreJournal,
    CodingWindowsArchPrivateDataRestoreTransaction,
)


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
        require_windows_restore_product_state(
            desired, key, error="Windows Coding Arch backup expiry requires removal"
        )
        receipt, source = _archive_io.read_expiry_manifest(
            backup_parent(self.layout, key), backup_id, key, label="Windows Coding Arch"
        )
        events = read_windows_deletion_history(
            CodingWindowsArchPrivateDataDeletionTransaction(
                self.product.state_root, transaction.state_fd
            )
        )
        require_finished_windows_deletion(events, label="Windows Coding Arch")
        deletion = latest_deleted_target_receipt(events, key, receipt.source_target_id)
        if deletion is None:
            raise ValueError("Windows Coding Arch backup expiry lacks deletion")
        restore_plan = CodingArchPrivateDataRestorePlanV1(
            installation_key=key,
            backup_id=backup_id,
            deletion_receipt_id=deletion.receipt_id,
            source_target_id=source.target_id,
            desired_inventory_revision=desired.inventory_revision,
            target_state="absent",
        )
        confirmation, completion, restored, archive = read_windows_expiry_restore_proof(
            transaction,
            restore_plan,
            confirmation_id,
            capture_archive=lambda: capture_windows_arch_backup_archive(
                self.layout, key, backup_id, source, receipt
            ),
            label="Windows Coding Arch",
        )
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
