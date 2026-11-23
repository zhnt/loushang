"""Read-only Windows candidate for independently confirmed Arch backup expiry."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_restore_windows import (
    preview_windows_backup_expiry,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .private_data_backup_expiry_records import CodingArchPrivateDataBackupExpiryPlanV1
from .private_data_backup_records import _digest as _digest
from .private_data_windows_archive_snapshot import (
    capture_windows_arch_backup_archive as capture_windows_arch_backup_archive,
)
from .private_data_windows_backup import _archive_io as _archive_io
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
        return preview_windows_backup_expiry(
            transaction,
            key,
            backup_id,
            confirmation_id,
            archive_io=_archive_io,
            capture_archive=lambda source, receipt: capture_windows_arch_backup_archive(
                self.layout, key, backup_id, source, receipt
            ),
            create_plan=CodingArchPrivateDataBackupExpiryPlanV1,
        )


__all__ = ["CodingWindowsArchPrivateDataBackupExpiryPreview"]
