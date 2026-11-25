"""Bounded native snapshot of one immutable Windows Arch backup archive."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.plugin_management._private_data_records import (
    WindowsPrivateArchiveSnapshotRecord,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

from .private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    backup_parent,
)
from .private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
)
from .private_data_windows_backup import _archive_io


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupArchiveSnapshotV1(
    WindowsPrivateArchiveSnapshotRecord[CodingArchPrivateDataMemberV1]
):
    """Archive root plus a full 4096-member files snapshot and manifest."""

    label: ClassVar[str] = "Windows Coding Arch"
    fingerprint_domain: ClassVar[bytes] = (
        b"loushang.coding-arch-windows-backup-archive/v1\0"
    )
    root_path_digest: str
    root_identity: tuple[int, int, int, int, int]
    files: CodingArchPrivateDataTargetSnapshotV1
    manifest: CodingArchPrivateDataMemberV1

    @classmethod
    def _archive_files_type(cls) -> type[CodingArchPrivateDataTargetSnapshotV1]:
        return CodingArchPrivateDataTargetSnapshotV1

    @classmethod
    def _archive_manifest_type(cls) -> type[CodingArchPrivateDataMemberV1]:
        return CodingArchPrivateDataMemberV1


def capture_windows_arch_backup_archive(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    backup_id: str,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
) -> CodingWindowsArchBackupArchiveSnapshotV1:
    parent_path = backup_parent(layout, key)
    return _archive_io.capture_archive(
        parent_path,
        backup_id,
        key,
        source,
        receipt,
        manifest_type=CodingArchPrivateDataMemberV1,
        snapshot_type=CodingWindowsArchBackupArchiveSnapshotV1,
    )


__all__ = [
    "CodingWindowsArchBackupArchiveSnapshotV1",
    "capture_windows_arch_backup_archive",
]
