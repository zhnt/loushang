"""Portable bounds for the Windows archive identity used by expiry."""

from __future__ import annotations

import stat
from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.coding.package_private_data_windows_archive_snapshot import (
    CodingWindowsArchBackupArchiveSnapshotV1,
)


def test_windows_archive_snapshot_keeps_full_source_limit() -> None:
    session = "a" * 64
    directories = (
        CodingArchPrivateDataMemberV1(
            "sessions", "directory", (1, 2, stat.S_IFDIR | 0o700, 0, 1)
        ),
        CodingArchPrivateDataMemberV1(
            "sessions/" + session,
            "directory",
            (1, 3, stat.S_IFDIR | 0o700, 0, 1),
        ),
    )
    content_digest = sha256(b"x").hexdigest()
    files = tuple(
        CodingArchPrivateDataMemberV1(
            f"sessions/{session}/f{index:04d}",
            "file",
            (1, index + 4, stat.S_IFREG | 0o600, 1, 1),
            content_digest,
        )
        for index in range(4094)
    )
    source = CodingArchPrivateDataTargetSnapshotV1(
        root_path_digest=sha256(b"archive/files").hexdigest(),
        root_identity=(1, 1, stat.S_IFDIR | 0o700, 0, 1),
        members=tuple(sorted((*directories, *files), key=lambda item: item.relative_path)),
    )
    assert len(source.members) == 4096
    manifest = CodingArchPrivateDataMemberV1(
        "manifest.json",
        "file",
        (1, 4099, stat.S_IFREG | 0o600, 1, 1),
        content_digest,
    )
    archive = CodingWindowsArchBackupArchiveSnapshotV1(
        root_path_digest=sha256(b"archive").hexdigest(),
        root_identity=(1, 4098, stat.S_IFDIR | 0o700, 0, 1),
        files=source,
        manifest=manifest,
    )
    assert archive.target_id.startswith("present:")
    assert CodingWindowsArchBackupArchiveSnapshotV1.from_dict(archive.to_dict()) == archive
    changed = replace(manifest, identity=(1, 5000, stat.S_IFREG | 0o600, 1, 1))
    assert replace(archive, manifest=changed).target_id != archive.target_id
    with pytest.raises(ValueError, match="archive snapshot is invalid"):
        replace(archive, manifest=replace(manifest, relative_path="foreign.json"))
