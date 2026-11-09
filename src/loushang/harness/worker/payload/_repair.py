"""Named Worker repair publication; no payload deletion or Product authority."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harness.journal._io_loops import write_all
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

_FILE_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    if os.name == "posix"
    else -1
)
_ValueT = TypeVar("_ValueT")


def read_repair_file(
    root_fd: int,
    name: str,
    *,
    maximum_bytes: int,
    error_code: str,
    error_type: type[Exception],
) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd
    )
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_uid != os.geteuid()
            or opened.st_nlink not in {1, 2}
            or not 0 < opened.st_size <= maximum_bytes
        ):
            raise error_type(error_code)
        body = os.read(descriptor, maximum_bytes + 1)
        after = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if (
            len(body) != opened.st_size
            or os.read(descriptor, 1)
            or (visible.st_dev, visible.st_ino) != (opened.st_dev, opened.st_ino)
            or (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_uid,
                opened.st_nlink,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
        ):
            raise error_type(error_code)
        return body, opened
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class RepairJournal(Generic[_ValueT]):
    names: Callable[[str], tuple[str, str]]
    decode: Callable[[bytes, str], _ValueT]
    encode: Callable[[_ValueT], dict[str, object]]
    maximum_bytes: int
    error_type: type[Exception]
    raw_error_type: type[Exception]
    error_code: str
    stale_code: str
    publication_changed: str
    write_message: str
    write_maximum: int | None = None
    single_link_staging_error: str | None = None

    def _read_file(self, root_fd: int, name: str) -> tuple[bytes, os.stat_result]:
        return read_repair_file(
            root_fd,
            name,
            maximum_bytes=self.maximum_bytes,
            error_code=self.error_code,
            error_type=self.raw_error_type,
        )

    def read(self, root_fd: int, attempt_id: str) -> _ValueT | None:
        name, staging = self.names(attempt_id)
        try:
            body, opened = self._read_file(root_fd, name)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise self.error_type(self.error_code) from exc
        try:
            value = self.decode(body, attempt_id)
            if opened.st_nlink == 2:
                sibling = os.stat(staging, dir_fd=root_fd, follow_symlinks=False)
                if not stat.S_ISREG(sibling.st_mode) or (
                    sibling.st_dev,
                    sibling.st_ino,
                ) != (opened.st_dev, opened.st_ino):
                    raise ValueError(self.publication_changed)
            elif self.single_link_staging_error is not None:
                try:
                    os.stat(staging, dir_fd=root_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise ValueError(self.single_link_staging_error)
            return value
        except (OSError, TypeError, ValueError, UnicodeError) as exc:
            raise self.error_type(self.error_code) from exc

    def publish(self, root_fd: int, attempt_id: str, value: _ValueT) -> None:
        name, staging = self.names(attempt_id)
        existing = self.read(root_fd, attempt_id)
        if existing is not None:
            if existing != value:
                raise self.error_type(self.stale_code)
            self.settle(root_fd, attempt_id, value)
            return
        body = canonical_json_bytes(self.encode(value)) + b"\n"
        if self.write_maximum is not None and len(body) > self.write_maximum:
            raise self.error_type(self.error_code)
        try:
            staged, metadata = self._read_file(root_fd, staging)
        except FileNotFoundError:
            descriptor = os.open(staging, _FILE_FLAGS, 0o600, dir_fd=root_fd)
            try:
                write_all(
                    lambda view: os.write(descriptor, view),
                    body,
                    message=self.write_message,
                )
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        else:
            if staged != body or metadata.st_nlink != 1:
                raise self.error_type(self.error_code)
        with suppress(FileExistsError):
            os.link(
                staging,
                name,
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
                follow_symlinks=False,
            )
        os.fsync(root_fd)
        if self.read(root_fd, attempt_id) != value:
            raise self.error_type(self.error_code)
        self.settle(root_fd, attempt_id, value)

    def settle(self, root_fd: int, attempt_id: str, value: _ValueT) -> None:
        name, staging = self.names(attempt_id)
        if self.read(root_fd, attempt_id) != value:
            raise self.error_type(self.error_code)
        metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if metadata.st_nlink == 2:
            os.unlink(staging, dir_fd=root_fd)
            os.fsync(root_fd)
