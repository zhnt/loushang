"""Portable recovery constraints for the native Windows deletion owner."""

from __future__ import annotations

import stat
from dataclasses import replace

import pytest

from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataMemberV1,
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.coding.package_private_data_windows_deletion_owner import (
    _require_remaining_subset,
)


def test_windows_deletion_resume_accepts_only_original_remaining_members() -> None:
    sessions = CodingArchPrivateDataMemberV1(
        "sessions", "directory", (1, 2, stat.S_IFDIR | 0o700, 0, 3)
    )
    session = CodingArchPrivateDataMemberV1(
        "sessions/" + "a" * 64,
        "directory",
        (1, 4, stat.S_IFDIR | 0o700, 0, 5),
    )
    cache = CodingArchPrivateDataMemberV1(
        session.relative_path + "/import-facts-v1.json",
        "file",
        (1, 6, stat.S_IFREG | 0o600, 4, 7),
        "b" * 64,
    )
    original = CodingArchPrivateDataTargetSnapshotV1(
        "c" * 64,
        (1, 8, stat.S_IFDIR | 0o700, 0, 9),
        (sessions, session, cache),
    )
    partial = replace(original, members=(sessions, session))
    _require_remaining_subset(partial, original)
    with pytest.raises(ValueError, match="tombstone member changed"):
        _require_remaining_subset(
            replace(
                original,
                members=(
                    sessions,
                    session,
                    replace(cache, identity=(1, 99, *cache.identity[2:])),
                ),
            ),
            original,
        )
    with pytest.raises(ValueError, match="tombstone member changed"):
        _require_remaining_subset(
            replace(
                original,
                members=(sessions, session, replace(cache, content_sha256="d" * 64)),
            ),
            original,
        )
