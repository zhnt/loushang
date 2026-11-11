"""Bounded native snapshot of one immutable Windows Arch backup archive."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_private_data_backup_records import (
    CodingArchPrivateDataBackupReceiptV1,
    _digest,
    backup_parent,
)
from .package_private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
    _valid_identity,
)
from .package_private_data_windows_backup import (
    _archive_io,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsArchBackupArchiveSnapshotV1:
    """Archive root plus a full 4096-member files snapshot and manifest."""

    root_path_digest: str
    root_identity: tuple[int, int, int, int, int]
    files: CodingArchPrivateDataTargetSnapshotV1
    manifest: CodingArchPrivateDataMemberV1

    def __post_init__(self) -> None:
        if (
            not _digest(self.root_path_digest)
            or not _valid_identity(self.root_identity)
            or not stat.S_ISDIR(self.root_identity[2])
            or not isinstance(self.files, CodingArchPrivateDataTargetSnapshotV1)
            or self.files.root_identity is None
            or not isinstance(self.manifest, CodingArchPrivateDataMemberV1)
            or self.manifest.relative_path != "manifest.json"
            or self.manifest.kind != "file"
        ):
            raise ValueError("Windows Coding Arch archive snapshot is invalid")

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
        if type(value) is not dict or set(value) != {
            "files",
            "manifest",
            "rootIdentity",
            "rootPathDigest",
        }:
            raise ValueError("Windows Coding Arch archive snapshot fields changed")
        identity = value["rootIdentity"]
        if type(identity) is not list or len(identity) != 5:
            raise ValueError("Windows Coding Arch archive identity changed")
        return cls(
            root_path_digest=value["rootPathDigest"],
            root_identity=tuple(identity),
            files=CodingArchPrivateDataTargetSnapshotV1.from_dict(value["files"]),
            manifest=CodingArchPrivateDataMemberV1.from_dict(value["manifest"]),
        )


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
