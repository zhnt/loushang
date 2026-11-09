"""Physical IO for already admitted, private local Package Sources.

Callers own directory admission, the publication lock, record identity and
post-publication verification. These functions grant no Source authorization.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from contextlib import suppress
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from loushang.harness.journal._io_loops import write_all
from loushang.harness.resources.packages._file_consumption import (
    DescriptorReader,
    closing_descriptor,
    consume_file,
)

from .local_source import open_regular_no_follow


def file_identity(
    value: os.stat_result, *, include_link_count: bool = False
) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        *((value.st_nlink,) if include_link_count else ()),
        value.st_uid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def publish_controlled_source(
    directory: int, name: str, body: bytes, *, write_error: str
) -> None:
    """Borrow an admitted directory; the caller verifies any existing target."""
    staging = f".{name}.staging"
    with suppress(FileNotFoundError):
        os.unlink(staging, dir_fd=directory)
    descriptor = os.open(
        staging,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory,
    )
    try:
        os.fchmod(descriptor, 0o600)
        write_all(
            lambda pending: os.write(descriptor, pending), body, message=write_error
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    # A failure before this point intentionally leaves the original staging debt.
    try:
        with suppress(FileExistsError):
            os.link(
                staging,
                name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        os.fsync(directory)
    finally:
        os.unlink(staging, dir_fd=directory)
        os.fsync(directory)


def read_controlled_source(
    path: Path,
    *,
    digest: str,
    max_bytes: int,
    label: str,
    error_factory: Callable[[str], Exception],
) -> bytes:
    """Observe existing private bytes; policy and Wheel validation stay outside."""
    with closing_descriptor(open_regular_no_follow(path)) as descriptor:
        # Retain native ownership if constructing the Python wrapper fails.
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            before = os.fstat(handle.fileno())
            if (
                before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) & 0o077
                or before.st_size > max_bytes
            ):
                raise error_factory(f"{label} bytes are unsafe")
            body = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
    if (
        file_identity(before) != file_identity(after)
        or sha256(body).hexdigest() != digest
    ):
        raise error_factory(f"{label} bytes changed")
    return body


def verify_private_controlled_source(
    root: Path,
    filename: str,
    expected_digest: str,
    *,
    label: str,
    error_factory: Callable[[str], Exception],
    filename_pattern: re.Pattern[str],
    max_bytes: Callable[[], int],
) -> None:
    if os.name != "posix" or filename_pattern.fullmatch(filename) is None:
        raise error_factory(f"{label} Wheel identity is invalid")
    try:
        directory = os.open(
            root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
    except OSError as exc:
        raise error_factory(f"{label} Source root is unavailable") from exc
    try:
        metadata = os.fstat(directory)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 63
            or metadata.st_uid != os.geteuid()
        ):
            raise error_factory(f"{label} Source root is not private")
        try:
            member = os.open(
                filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory
            )
        except OSError as exc:
            raise error_factory(f"{label} Wheel is unavailable") from exc
        try:
            before = os.fstat(member)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) & 63
                or (before.st_size > max_bytes())
            ):
                raise error_factory(f"{label} Wheel is unsafe")
            buffer = BytesIO()
            consume_file(
                DescriptorReader(member),
                max_bytes=max_bytes,
                destination=buffer,
                hash_content=False,
                size_error=lambda: error_factory(f"{label} Wheel exceeds budget"),
            )
            body = buffer.getvalue()
            after = os.fstat(member)
            try:
                visible = os.stat(filename, dir_fd=directory, follow_symlinks=False)
            except OSError as exc:
                raise error_factory(f"{label} Wheel changed on disk") from exc
            if (
                file_identity(before, include_link_count=True)
                != file_identity(after, include_link_count=True)
                or file_identity(before, include_link_count=True)
                != file_identity(visible, include_link_count=True)
                or sha256(body).hexdigest() != expected_digest
            ):
                raise error_factory(f"{label} Wheel changed on disk")
        finally:
            os.close(member)
    finally:
        os.close(directory)
