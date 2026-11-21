"""Bounded native snapshot of one immutable Windows Arch backup archive."""

from __future__ import annotations

import os
import stat as stat
from dataclasses import dataclass
from hashlib import sha256

from loushang.coding.harness.plugin_management import (
    private_data_windows_archive_records as _record_programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    backup_parent,
)
from .private_data_backup_records import (
    _digest as _digest,
)
from .private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
)
from .private_data_deletion_preview import (
    _valid_identity as _valid_identity,
)
from .private_data_windows_backup import _archive_io

_PRIVATE_DATA_RECORD_VALUES = {
    "value_01": "Windows Coding Arch archive snapshot is invalid",
    "value_02": "Windows Coding Arch archive snapshot fields changed",
    "value_03": "Windows Coding Arch archive identity changed",
}


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupArchiveSnapshotV1:
    """Archive root plus a full 4096-member files snapshot and manifest."""

    root_path_digest: str
    root_identity: tuple[int, int, int, int, int]
    files: CodingArchPrivateDataTargetSnapshotV1
    manifest: CodingArchPrivateDataMemberV1

    def __post_init__(self) -> None:
        return _record_programs.validate_archive(self)

    @property
    def target_id(self) -> str:
        return (
            "present:"
            + sha256(
                b"loushang.coding-arch-windows-backup-archive/v1\0"
                + canonical_json_bytes(self.to_dict())
            ).hexdigest()
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "files": self.files.to_dict(),
            "manifest": self.manifest.to_dict(),
            "rootIdentity": list(self.root_identity),
            "rootPathDigest": self.root_path_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWindowsArchBackupArchiveSnapshotV1:
        return _record_programs.decode_archive(cls, value)


def capture_windows_arch_backup_archive(
    layout: CodingPluginLifecycleStateLayout,
    key: PluginInstallationKeyV1,
    backup_id: str,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
) -> CodingWindowsArchBackupArchiveSnapshotV1:
    parent_path = backup_parent(layout, key)
    archive_path = parent_path / backup_id
    return _archive_io.capture_archive(
        parent_path,
        backup_id,
        key,
        source,
        receipt,
        project_manifest=lambda identity, digest: CodingArchPrivateDataMemberV1(
            "manifest.json", "file", identity, digest
        ),
        project=lambda identity, files, manifest: (
            CodingWindowsArchBackupArchiveSnapshotV1(
                root_path_digest=sha256(os.fsencode(str(archive_path))).hexdigest(),
                root_identity=identity,
                files=files,
                manifest=manifest,
            )
        ),
    )


__all__ = [
    "CodingWindowsArchBackupArchiveSnapshotV1",
    "capture_windows_arch_backup_archive",
]
