"""Independent retained backup owner for one Coding Arch Installation.

The archive is a private immutable file tree with its own manifest. It never
deletes source data or expires backups, and Package removal/GC cannot infer
retention from their own receipts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loushang.coding.harness.plugin_management import private_data_backup as _programs
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
)
from loushang.coding.plugin_manager.lifecycle import (
    prepare_coding_plugin_private_tree as _prepare_private_tree,  # noqa: F401
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management._private_data_records import (
    _valid_digest as _digest,
)
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionRecordV1 as PluginBackupRetentionRecordV1,
)
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionSnapshotV1,
)
from loushang.harness.plugin_management.application import (
    PluginBackupRetentionStatus as PluginBackupRetentionStatus,
)
from loushang.harness.plugin_management.private_data_backup import (
    enumerate_private_archives,
    read_private_archive,
    verify_private_archive,
)
from loushang.harness.plugin_management.private_data_backup import (
    retain_private_archive as retain_private_archive,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages._file_consumption import (
    closing_descriptor as closing_descriptor,
)
from loushang.harness.resources.packages._private_tree_posix import (
    PrivatePosixTreeIO,
    verify_private_tree,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .epoch_layout import resolve_coding_package_epoch_layout
from .installation_private_data import (
    coding_arch_installation_private_data_root as coding_arch_installation_private_data_root,
)
from .private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    _ArchBackupCodec,
)
from .private_data_backup_records import (
    _backup_retention_revision as _backup_retention_revision,
)
from .private_data_backup_records import backup_parent as _backup_parent
from .private_data_deletion_preview import _MAX_TOTAL_BYTES as _MAX_READ_BYTES
from .private_data_deletion_preview import (
    CodingArchPrivateDataDeletionPreview,
    CodingArchPrivateDataTargetSnapshotV1,
)
from .private_data_deletion_preview import (
    _capture_target_snapshot as _capture_target_snapshot,
)
from .product_backup_types import require_coding_arch_backup_writer

_PLUGIN_ID = "coding.arch.default"
_private_io = PrivatePosixTreeIO("Coding Arch", _MAX_READ_BYTES)
_open_chain = _private_io.open_chain
_mkdir_at = _private_io.mkdir
_open_private_dir = _private_io.open_directory
_open_private_path = _private_io.open_path
_write_or_verify_file = _private_io.write_file


_archive_codec = _ArchBackupCodec()


_PRIVATE_DATA_PROGRAM_VALUES = {
    "value_01": "Coding Arch backup Installation has no Product history",
    "value_02": "Coding Arch private-data source is absent",
    "value_03": "Coding Arch backup ID is invalid",
    "value_04": "Coding Arch backup Installation changed",
    "value_05": "coding",
    "value_06": "Coding Arch expired backup reappeared",
    "value_07": "coding-arch-backup:",
    "value_08": "Coding Arch backup expiry receipt changed",
}


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupOwner:
    layout: CodingPluginLifecycleStateLayout
    product: PosixLocalWheelProductSessionOwner

    def __post_init__(self) -> None:
        if os.name != "posix":
            raise RuntimeError("Coding Arch POSIX backup owner is unavailable")
        require_coding_arch_backup_writer(self.product)
        CodingArchPrivateDataDeletionPreview(self.layout, self.product)

    def retain(
        self, key: PluginInstallationKeyV1
    ) -> CodingArchPrivateDataBackupReceiptV1:
        return _programs.retain(self, key)

    def snapshot(self) -> PluginBackupRetentionSnapshotV1:
        preview = CodingArchPrivateDataDeletionPreview(self.layout, self.product)
        with preview._offline():
            return CodingArchPrivateDataBackupReadSource(
                self.layout, self.product.epoch_runtime
            ).snapshot()

    def verify(
        self, key: PluginInstallationKeyV1, backup_id: str
    ) -> CodingArchPrivateDataBackupReceiptV1:
        """Reopen one exact archive without requiring its source to survive."""

        return _programs.verify(self, key, backup_id)


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupReadSource:
    """Read-only Product projection of verified per-Installation backups."""

    layout: CodingPluginLifecycleStateLayout
    epoch_runtime: PackageProductPosixFencedRuntimeOwner

    def __post_init__(self) -> None:
        if os.name != "posix":
            raise RuntimeError("Coding Arch POSIX backup source is unavailable")
        epoch = resolve_coding_package_epoch_layout(self.layout)
        if (
            not isinstance(self.epoch_runtime, PackageProductPosixFencedRuntimeOwner)
            or self.epoch_runtime.registry.store_id != epoch.store_id
            or self.epoch_runtime.control_root != epoch.control_root
        ):
            raise ValueError("Coding Arch backup Product authority changed")

    def snapshot(self) -> PluginBackupRetentionSnapshotV1:
        return _programs.retention_snapshot(self)


def _retained_receipts(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    *,
    allowed_tombstone: str | None = None,
) -> tuple[CodingArchPrivateDataBackupReceiptV1, ...]:
    parent = _backup_parent(layout, key)
    return enumerate_private_archives(
        layout.private_data_base,
        parent,
        key,
        io=_private_io,
        codec=_archive_codec,
        is_archive_name=_digest,
        staging_suffix=".staging",
        allowed_tombstone=allowed_tombstone,
    )


def _verify_archive(
    parent_fd: int,
    name: str,
    key: PluginInstallationKeyV1,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
) -> None:
    verify_private_archive(
        parent_fd, name, key, source, receipt, io=_private_io, codec=_archive_codec
    )


def _read_manifest(
    parent_fd: int, name: str
) -> tuple[CodingArchPrivateDataBackupReceiptV1, CodingArchPrivateDataTargetSnapshotV1]:
    return read_private_archive(parent_fd, name, io=_private_io, codec=_archive_codec)


def _verify_files(root_fd: int, source: CodingArchPrivateDataTargetSnapshotV1) -> None:
    verify_private_tree(
        root_fd, source.members, label="Coding Arch", max_read_bytes=_MAX_READ_BYTES
    )


__all__ = [
    "CodingArchPrivateDataBackupOwner",
    "CodingArchPrivateDataBackupReadSource",
    "CodingArchPrivateDataBackupReceiptV1",
]
