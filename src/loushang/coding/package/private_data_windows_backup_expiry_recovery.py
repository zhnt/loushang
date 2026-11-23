"""Archive-free Product authority for resuming a Windows Arch backup expiry."""

from __future__ import annotations

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_deletion_windows import (
    read_windows_deletion_history,
)
from loushang.harness.plugin_management._private_data_restore_windows import (
    require_windows_expiry_recovery_authority,
)

from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .installation_private_data import inspect_coding_windows_arch_installation_root
from .private_data_backup_expiry_records import CodingArchPrivateDataBackupExpiryPlanV1
from .private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction as CodingWindowsArchPrivateDataDeletionTransaction,
)
from .private_data_windows_preview import _capture_windows_target_snapshot, _native_io
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
    key = plan.installation_key
    root = coding_arch_installation_private_data_root(layout, key)
    require_windows_expiry_recovery_authority(
        restore,
        plan,
        root,
        desired_state=product.desired_state,
        deletion_history=lambda: read_windows_deletion_history(
            CodingWindowsArchPrivateDataDeletionTransaction(
                product.state_root, restore.state_fd
            )
        ),
        observe_bound_root=lambda: inspect_coding_windows_arch_installation_root(
            layout, key, state_root=product.state_root
        ),
        capture_restored=lambda expected: _capture_windows_target_snapshot(
            root, expected_root=expected
        ),
        tree_io=_native_io,
        stage_prefix=".arch-restore-",
        label="Windows Coding Arch",
    )


__all__ = ["require_windows_arch_backup_expiry_recovery_authority"]
