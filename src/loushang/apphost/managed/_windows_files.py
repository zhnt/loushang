"""Windows IO for the managed directory's shared record and data protocols."""

from __future__ import annotations

import errno
import os
import stat
from importlib import import_module

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
    windows_directory_stream_names,
    windows_regular_file_stream_names,
)


def create_directory(parent: int, name: str, *, inherit_children: bool) -> None:
    with WindowsPrivateDirectoryAcl(inherit_children=inherit_children) as acl:
        fd = open_windows_directory(
            name, dir_fd=parent, create_new=True, security_descriptor=acl.security_descriptor,
        )
    os.close(fd)


def validate(fd: int, info: os.stat_result, *, directory: bool, inherit_children: bool) -> tuple[int, int]:
    with WindowsPrivateDirectoryAcl(inherit_children=inherit_children or not directory) as acl:
        acl.validate(fd, inherited_file=not directory)
    streams = windows_directory_stream_names if directory else windows_regular_file_stream_names
    if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or (not directory and info.st_nlink != 1) or set(streams(fd)) - {"::$DATA"}):
        raise OSError("Windows managed entry is not an admitted private file")
    return info.st_dev, info.st_ino


def open_file(parent: int, name: str, flags: int, *, share_delete: bool = False) -> int:
    write = bool(flags & (os.O_RDWR | os.O_WRONLY))
    if flags & os.O_CREAT:
        with WindowsPrivateDirectoryAcl() as acl:
            try:
                return open_windows_regular_file_at(
                    parent, name, create_new=True, write=write, read_control=True,
                    share_delete=share_delete, security_descriptor=acl.security_descriptor,
                )
            except FileExistsError:
                if flags & os.O_EXCL:
                    raise
    return open_windows_regular_file_at(
        parent, name, create_new=False, write=write, read_control=True, share_delete=share_delete,
    )


def lock_file(fd: int) -> None:
    crt = import_module("msvcrt")
    try:
        crt.locking(fd, crt.LK_NBLCK, 1)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN}:
            raise BlockingIOError from None
        raise


def read_at(fd: int, length: int, offset: int) -> bytes:
    # The shared directory mutex serializes access to this private descriptor.
    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, offset, os.SEEK_SET)
        return os.read(fd, length)
    finally:
        os.lseek(fd, position, os.SEEK_SET)
