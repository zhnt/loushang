"""Archive-free Product authority for resuming a Windows Arch backup expiry."""

from __future__ import annotations

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .private_data_backup_expiry_records import CodingArchPrivateDataBackupExpiryPlanV1
from .private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreTransaction,
)


def require_windows_arch_backup_expiry_recovery_authority(
    layout: CodingPluginLifecycleStateLayout,
    product: WindowsLocalWheelProductSessionOwner,
    restore: CodingWindowsArchPrivateDataRestoreTransaction,
    plan: CodingArchPrivateDataBackupExpiryPlanV1,
) -> None:
    """Verify immutable history and current restored bytes after archive rename."""

    if not isinstance(plan, CodingArchPrivateDataBackupExpiryPlanV1):
        raise ValueError("Windows Coding Arch backup expiry plan is invalid")
    if restore.layout != layout or restore.product is not product:
        raise ValueError("Windows Coding Arch backup expiry restore owner changed")
    restore.require_expiry_recovery(plan)


__all__ = ["require_windows_arch_backup_expiry_recovery_authority"]
