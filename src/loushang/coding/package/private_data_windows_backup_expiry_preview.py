"""Read-only Windows candidate for independently confirmed Arch backup expiry."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as replace

from loushang.coding.harness.plugin_management import (
    private_data_windows_expiry_preview as _programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.foundation.windows_private_acl import (
    WindowsPrivateDirectoryAcl as WindowsPrivateDirectoryAcl,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_deletion import (
    latest_deleted_target_receipt as latest_deleted_target_receipt,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at as windows_listdir_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity as inspect_windows_product_private_directory_identity,
)

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
from .private_data_windows_backup import (
    _read_archive_manifest as _read_archive_manifest,
)
from .private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction as CodingWindowsArchPrivateDataDeletionTransaction,
)
from .private_data_windows_preview import CodingWindowsArchPrivateDataReadPreview
from .private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreJournal,
    CodingWindowsArchPrivateDataRestoreTransaction,
)

_PRIVATE_DATA_FLOW_VALUES = {
    "message_01": "Windows Coding Arch backup expiry request is invalid",
    "message_02": "Windows Coding Arch backup expiry requires removal",
    "message_03": "Windows Coding Arch deletion is unfinished",
    "message_04": "Windows Coding Arch backup expiry lacks deletion",
    "message_05": "Windows Coding Arch backup archive disappeared",
    "message_06": "Windows Coding Arch restore confirmation changed",
    "message_07": "arch-restore-confirm:",
    "message_08": "Windows Coding Arch backup parent changed",
    "message_09": "Windows Coding Arch backup Installation changed",
}


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
        return _programs.preview_locked(
            self, transaction, key, backup_id, confirmation_id
        )


__all__ = ["CodingWindowsArchPrivateDataBackupExpiryPreview"]
