"""Bounded native snapshot of one immutable Windows Arch backup archive."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from hashlib import sha256

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_listdir_at,
    windows_regular_file_stream_names,
    windows_stat_at,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    inspect_windows_product_private_directory_identity,
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
    _identity,
    _valid_identity,
)
from .package_private_data_windows_backup import (
    _MAX_MANIFEST_BYTES,
    _directory_identity,
    _logical_members,
    _verify_archive,
)
from .package_private_data_windows_preview import (
    _capture_windows_target_snapshot,
    _require_no_named_directory_streams,
    _require_same_windows_metadata,
    _require_simple_windows_metadata,
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
        return "present:" + sha256(
            b"loushang.coding-arch-windows-backup-archive/v1\0"
            + canonical_json_bytes(self.to_dict())
        ).hexdigest()

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
            "files", "manifest", "rootIdentity", "rootPathDigest"
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
    """Recheck the archive and bind every direct member to its native identity."""

    parent_path = backup_parent(layout, key)
    archive_path = parent_path / backup_id
    parent_identity = inspect_windows_product_private_directory_identity(parent_path)
    with WindowsPrivateDirectoryAcl() as acl:
        parent_fd = open_windows_directory(
            parent_path, share_delete=False, read_control=True
        )
        try:
            acl.validate(parent_fd)
            if _directory_identity(parent_fd) != parent_identity:
                raise ValueError("Windows Coding Arch archive parent changed")
            _verify_archive(
                parent_fd, parent_path, backup_id, key, source, receipt, acl
            )
            archive_fd = open_windows_directory(
                backup_id, dir_fd=parent_fd, share_delete=False, read_control=True
            )
            try:
                acl.validate(archive_fd)
                _require_no_named_directory_streams(archive_fd)
                before = os.fstat(archive_fd)
                _require_simple_windows_metadata(before, directory=True)
                if set(windows_listdir_at(archive_fd)) != {"files", "manifest.json"}:
                    raise ValueError("Windows Coding Arch archive members changed")
                files_fd = open_windows_directory(
                    "files", dir_fd=archive_fd, share_delete=False, read_control=True
                )
                try:
                    acl.validate(files_fd)
                    files_metadata = os.fstat(files_fd)
                    files = _capture_windows_target_snapshot(
                        archive_path / "files",
                        expected_root=_directory_identity(files_fd),
                    )
                    if (
                        files.root_identity != _identity(files_metadata)
                        or _logical_members(files) != _logical_members(source)
                    ):
                        raise ValueError("Windows Coding Arch archive files changed")
                    after_files = os.fstat(files_fd)
                    visible_files = windows_stat_at(archive_fd, "files")
                    _require_same_windows_metadata(
                        after_files, files_metadata, directory=True
                    )
                    _require_same_windows_metadata(
                        visible_files, files_metadata, directory=True
                    )
                    if (
                        _identity(after_files) != _identity(files_metadata)
                        or _identity(visible_files) != _identity(files_metadata)
                    ):
                        raise ValueError("Windows Coding Arch archive files changed")
                finally:
                    os.close(files_fd)
                manifest = _capture_manifest_member(archive_fd, source, receipt, acl)
                _verify_archive(
                    parent_fd, parent_path, backup_id, key, source, receipt, acl
                )
                after = os.fstat(archive_fd)
                visible = windows_stat_at(parent_fd, backup_id)
                _require_same_windows_metadata(after, before, directory=True)
                _require_same_windows_metadata(visible, before, directory=True)
                if (
                    _identity(after) != _identity(before)
                    or _identity(visible) != _identity(before)
                    or _directory_identity(parent_fd) != parent_identity
                ):
                    raise ValueError("Windows Coding Arch archive root changed")
                return CodingWindowsArchBackupArchiveSnapshotV1(
                    root_path_digest=sha256(os.fsencode(str(archive_path))).hexdigest(),
                    root_identity=_identity(before),
                    files=files,
                    manifest=manifest,
                )
            finally:
                os.close(archive_fd)
        finally:
            os.close(parent_fd)
            if (
                inspect_windows_product_private_directory_identity(parent_path)
                != parent_identity
            ):
                raise ValueError("Windows Coding Arch archive parent changed")


def _capture_manifest_member(
    archive_fd: int,
    source: CodingArchPrivateDataTargetSnapshotV1,
    receipt: CodingArchPrivateDataBackupReceiptV1,
    acl: WindowsPrivateDirectoryAcl,
) -> CodingArchPrivateDataMemberV1:
    descriptor = open_windows_regular_file_at(
        archive_fd, "manifest.json", create_new=False, write=False, read_control=True
    )
    try:
        acl.validate(descriptor)
        before = os.fstat(descriptor)
        _require_simple_windows_metadata(before, directory=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > _MAX_MANIFEST_BYTES
            or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
        ):
            raise ValueError("Windows Coding Arch archive manifest is unsafe")
        raw = bytearray()
        while len(raw) <= _MAX_MANIFEST_BYTES:
            chunk = os.read(
                descriptor, min(65536, _MAX_MANIFEST_BYTES + 1 - len(raw))
            )
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(descriptor)
        visible = windows_stat_at(archive_fd, "manifest.json")
        _require_same_windows_metadata(after, before, directory=False)
        _require_same_windows_metadata(visible, before, directory=False)
        expected = (
            canonical_json_bytes({"receipt": receipt.to_dict(), "source": source.to_dict()})
            + b"\n"
        )
        if (
            bytes(raw) != expected
            or len(raw) != before.st_size
            or _identity(after) != _identity(before)
            or _identity(visible) != _identity(before)
            or windows_regular_file_stream_names(descriptor) != ("::$DATA",)
        ):
            raise ValueError("Windows Coding Arch archive manifest changed")
        return CodingArchPrivateDataMemberV1(
            "manifest.json", "file", _identity(before), sha256(raw).hexdigest()
        )
    finally:
        os.close(descriptor)


__all__ = [
    "CodingWindowsArchBackupArchiveSnapshotV1",
    "capture_windows_arch_backup_archive",
]
