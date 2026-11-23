"""Disposable Product state for authoring checks."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from loushang.harness.resources.packages._file_consumption import (
    borrowed_binary_stream,
    closing_descriptor,
)


def capture_authoring_input(
    path: Path,
    *,
    maximum_bytes: int,
    invalid_input: str,
    changed_before_read: str,
    changed_during_read: str,
    require_visible_source: bool = False,
) -> bytes:
    """Capture one bounded regular file before opening a disposable workspace."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum_bytes:
        raise ValueError(invalid_input)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with (
        closing_descriptor(os.open(path, flags)) as descriptor,
        borrowed_binary_stream(descriptor, "rb") as stream,
    ):
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ) != (before.st_dev, before.st_ino, before.st_size):
            raise ValueError(changed_before_read)
        body = stream.read(maximum_bytes + 1)
        after = os.fstat(descriptor)
    if (
        not 0 < len(body) <= maximum_bytes
        or _file_revision(opened) != _file_revision(after)
    ):
        raise ValueError(changed_during_read)
    if require_visible_source and (
        len(body) != before.st_size or path.stat().st_ino != before.st_ino
    ):
        raise ValueError(changed_during_read)
    return body


def _file_revision(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


@contextmanager
def hold_authoring_home(path: Path) -> Iterator[None]:
    previous = os.environ.get("LOUSHANG_HOME")
    path.mkdir(mode=0o700)
    os.environ["LOUSHANG_HOME"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LOUSHANG_HOME", None)
        else:
            os.environ["LOUSHANG_HOME"] = previous
