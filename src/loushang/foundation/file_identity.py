"""File identity from an already captured native stat observation."""

from __future__ import annotations

import os
import re
import stat

_STATUS_FINGERPRINT = re.compile(r"stat-v1:(?:[0-9]+:){4}[0-9]+\Z")


def _file_status_identity(
    metadata: os.stat_result,
) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def same_file_status(left: os.stat_result, right: os.stat_result) -> bool:
    return _file_status_identity(left) == _file_status_identity(right)


def file_status_fingerprint(metadata: os.stat_result) -> str:
    """Encode the same five fields carried by stable discovery identities."""
    return "stat-v1:" + ":".join(str(field) for field in _file_status_identity(metadata))


def is_file_status_fingerprint(value: object) -> bool:
    return type(value) is str and _STATUS_FINGERPRINT.fullmatch(value) is not None


def status_is_link_or_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def regular_file_status_no_follow(metadata: os.stat_result) -> bool:
    return stat.S_ISREG(metadata.st_mode) and not status_is_link_or_reparse(metadata)
