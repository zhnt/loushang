"""Read-only Product proof for restoring a Windows Arch private-data backup.

An archive being readable does not grant write authority. This preview binds
the exact retained bytes to the latest completed deletion and an absent target.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_deletion_windows import (
    read_windows_deletion_history,
)
from loushang.harness.plugin_management._private_data_restore_windows import (
    preview_windows_restore,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
)

from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .installation_private_data import (
    inspect_coding_windows_arch_installation_root as inspect_coding_windows_arch_installation_root,
)
from .private_data_backup_records import backup_parent as backup_parent
from .private_data_restore_records import CodingArchPrivateDataRestorePlanV1
from .private_data_windows_backup import _archive_io
from .private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction as CodingWindowsArchPrivateDataDeletionTransaction,
)
from .private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _native_io,
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

        def require_absent_target(acl: WindowsPrivateDirectoryAcl) -> None:
            if (
                inspect_coding_windows_arch_installation_root(
                    self.layout, key, state_root=self.product.state_root
                )
                is not None
            ):
                raise ValueError("Windows Coding Arch restore target is present")
            _require_no_restore_stage(root, acl)

        preview = CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)
        with preview._offline():
            return preview_windows_restore(
                key,
                backup_id,
                desired_state=self.product.desired_state,
                borrow_state=self.product.epoch_runtime.borrow_product_state_root_descriptor,
                read_deletions=lambda fd: read_windows_deletion_history(
                    CodingWindowsArchPrivateDataDeletionTransaction(
                        self.product.state_root, fd
                    )
                ),
                archive_io=_archive_io,
                backup_parent=lambda: backup_parent(self.layout, key),
                require_absent_target=require_absent_target,
                plan_type=CodingArchPrivateDataRestorePlanV1,
                label="Windows Coding Arch",
            )


def _require_no_restore_stage(root: Path, acl: WindowsPrivateDirectoryAcl) -> None:
    parent_identity = inspect_windows_product_private_directory_identity(root.parent)
    _native_io.require_restore_target_absent(
        root,
        parent_identity,
        acl,
        stage_prefix=".arch-restore-",
        parent_changed="Windows Coding Arch restore parent changed",
        state_debt="Windows Coding Arch restore target has state debt",
    )


__all__ = ["CodingWindowsArchPrivateDataRestorePreview"]
