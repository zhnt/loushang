"""Archive-free Product authority for resuming a Windows Arch backup expiry."""

from __future__ import annotations

from loushang.coding.harness.plugin_management import (
    private_data_windows_expiry_recovery as _programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.private_data_deletion import (
    latest_deleted_target_receipt as latest_deleted_target_receipt,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity as inspect_windows_product_private_directory_identity,
)

from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .installation_private_data import (
    inspect_coding_windows_arch_installation_root as inspect_coding_windows_arch_installation_root,
)
from .private_data_backup_expiry_records import CodingArchPrivateDataBackupExpiryPlanV1
from .private_data_restore_records import (
    CodingArchPrivateDataRestorePlanV1 as CodingArchPrivateDataRestorePlanV1,
)
from .private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction as CodingWindowsArchPrivateDataDeletionTransaction,
)
from .private_data_windows_preview import (
    _capture_windows_target_snapshot as _capture_windows_target_snapshot,
)
from .private_data_windows_preview import _native_io as _native_io
from .private_data_windows_restore_journal import (
    CodingWindowsArchPrivateDataRestoreTransaction,
)

_PRIVATE_DATA_FLOW_VALUES = {
    "message_01": "Windows Coding Arch backup expiry plan is invalid",
    "message_02": "Windows Coding Arch backup expiry Desired State changed",
    "message_03": "Windows Coding Arch backup expiry deletion changed",
    "message_04": "Windows Coding Arch backup expiry confirmation changed",
    "message_05": "Windows Coding Arch backup expiry restore changed",
    "message_06": "Windows Coding Arch backup expiry publication is missing",
    "message_07": "Windows Coding Arch backup expiry restore parent changed",
    "message_08": ".arch-restore-",
    "message_09": "Windows Coding Arch backup expiry restore has debt",
    "message_10": "Windows Coding Arch backup expiry root binding changed",
    "message_11": "Windows Coding Arch backup expiry restored bytes changed",
}


def require_windows_arch_backup_expiry_recovery_authority(
    layout: CodingPluginLifecycleStateLayout,
    product: WindowsLocalWheelProductSessionOwner,
    restore: CodingWindowsArchPrivateDataRestoreTransaction,
    plan: CodingArchPrivateDataBackupExpiryPlanV1,
) -> None:
    """Verify immutable history and current restored bytes after archive rename."""

    return _programs.require_expiry_recovery_authority(layout, product, restore, plan)


__all__ = ["require_windows_arch_backup_expiry_recovery_authority"]
