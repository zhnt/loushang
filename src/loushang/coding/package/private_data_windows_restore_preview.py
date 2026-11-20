"""Read-only Product proof for restoring a Windows Arch private-data backup.

An archive being readable does not grant write authority. This preview binds
the exact retained bytes to the latest completed deletion and an absent target.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.coding.harness.plugin_management import (
    private_data_windows_restore_preview as _programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
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
from .private_data_windows_backup import (
    _archive_io as _archive_io,
)
from .private_data_windows_backup import (
    _read_archive_manifest as _read_archive_manifest,
)
from .private_data_windows_backup import (
    _verify_archive as _verify_archive,
)
from .private_data_windows_deletion_journal import (
    CodingWindowsArchPrivateDataDeletionTransaction as CodingWindowsArchPrivateDataDeletionTransaction,
)
from .private_data_windows_preview import (
    CodingWindowsArchPrivateDataReadPreview,
    _native_io,
)

_PRIVATE_DATA_FLOW_VALUES = {
    "message_01": "Windows Coding Arch restore backup ID is invalid",
    "message_02": "Windows Coding Arch restore requires Product removal",
    "message_03": "Windows Coding Arch deletion is unfinished",
    "message_04": "Windows Coding Arch restore target is present",
    "message_05": "Windows Coding Arch backup parent changed",
    "message_06": "Windows Coding Arch backup stage needs recovery",
    "message_07": "Windows Coding Arch backup Installation changed",
    "message_08": "Windows Coding Arch restore lacks deletion",
}


@dataclass(frozen=True, slots=True)
class CodingWindowsArchPrivateDataRestorePreview:
    layout: CodingPluginLifecycleStateLayout
    product: WindowsLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        CodingWindowsArchPrivateDataReadPreview(self.layout, self.product)

    def preview(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataRestorePlanV1:
        return _programs.preview(self, key, backup_id)


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
