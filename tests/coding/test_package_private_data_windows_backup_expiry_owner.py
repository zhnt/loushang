"""Portable archive-member checks before native Windows expiry deletion."""

from __future__ import annotations

import os
import stat
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest

import loushang.coding.package_private_data_windows_backup_expiry_owner as owner
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
    _identity,
)
from loushang.coding.package_private_data_windows_archive_snapshot import (
    CodingWindowsArchBackupArchiveSnapshotV1,
)
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl


def test_expiry_manifest_must_keep_original_identity_and_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b'{"receipt":"bounded"}\n'
    path = tmp_path / "manifest.json"
    path.write_bytes(raw)
    member = CodingArchPrivateDataMemberV1(
        "manifest.json", "file", _identity(path.stat()), sha256(raw).hexdigest()
    )
    archive = CodingWindowsArchBackupArchiveSnapshotV1(
        root_path_digest=sha256(b"archive").hexdigest(),
        root_identity=(1, 3, stat.S_IFDIR | 0o700, 0, 1),
        files=CodingArchPrivateDataTargetSnapshotV1(
            root_path_digest=sha256(b"archive/files").hexdigest(),
            root_identity=(1, 2, stat.S_IFDIR | 0o700, 0, 1),
            members=(),
        ),
        manifest=member,
    )

    class FakeAcl:
        def validate(self, descriptor: int) -> None:
            return None

    monkeypatch.setattr(owner, "_require_simple_windows_metadata", lambda *a, **k: None)
    monkeypatch.setattr(
        owner, "windows_regular_file_stream_names", lambda fd: ("::$DATA",)
    )
    monkeypatch.setattr(owner, "windows_stat_at", lambda fd, name: path.stat())
    acl = cast(WindowsPrivateDirectoryAcl, FakeAcl())
    original = path.stat()
    parent_fd = os.open(tmp_path, os.O_RDONLY)
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            owner._require_manifest(descriptor, parent_fd, archive, acl)
        finally:
            os.close(descriptor)
        path.write_bytes(b'{"receipt":"changed"}\n')
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        assert _identity(path.stat()) == member.identity
        descriptor = os.open(path, os.O_RDONLY)
        try:
            with pytest.raises(ValueError, match="manifest changed"):
                owner._require_manifest(descriptor, parent_fd, archive, acl)
        finally:
            os.close(descriptor)
        replacement = tmp_path / "replacement"
        replacement.write_bytes(raw)
        os.replace(replacement, path)
        assert _identity(path.stat()) != member.identity
        descriptor = os.open(path, os.O_RDONLY)
        try:
            with pytest.raises(ValueError, match="manifest changed"):
                owner._require_manifest(descriptor, parent_fd, archive, acl)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)
