"""Original private JSONL pathname checks, before the caller's existing IO.

These checks do not pin identity, acquire locks, create paths or claim a root.
Owners keep their original admission points and any stronger native binding.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


def _private_metadata(metadata: os.stat_result, *, posix_only: bool) -> bool:
    if posix_only:
        return os.name != "posix" or (
            not metadata.st_mode & 0o077 and metadata.st_uid == os.geteuid()
        )
    return metadata.st_uid == os.geteuid() and not metadata.st_mode & 0o077


def require_private_journal_parent(
    path: Path, *, message: str, posix_only: bool
) -> None:
    metadata = path.parent.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or not _private_metadata(
        metadata, posix_only=posix_only
    ):
        raise ValueError(message)


def private_journal_exists(
    path: Path, *, message: str, posix_only: bool, max_bytes: int | None = None
) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not _private_metadata(metadata, posix_only=posix_only)
        or (max_bytes is not None and metadata.st_size > max_bytes)
    ):
        raise ValueError(message)
    return True
