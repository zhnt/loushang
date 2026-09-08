"""POSIX owner-only, no-follow file admission for local connection records."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from importlib import import_module

from ._local_record_files import FileIdentity, FileMode, _RecordFiles
from ._local_record_values import LocalRecordError, LocalRecordErrorCodeV1


class _PosixRecordFiles(_RecordFiles):
    _directory: int | None = None
    _directory_identity: FileIdentity | None = None

    def prepare(self, *, create: bool) -> None:
        if self._directory is not None:
            self.check_root()
            return
        if create:
            with suppress(FileExistsError):
                self.root.mkdir(mode=0o700)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY") | getattr(os, "O_NOFOLLOW") | getattr(os, "O_CLOEXEC")
        self._directory = os.open(self.root, flags)
        self._directory_identity = self._validate(os.fstat(self._directory), directory=True)
        self.check_root()

    def check_root(self) -> None:
        if self._directory is None:
            raise LocalRecordError(LocalRecordErrorCodeV1.CLOSED)
        opened = self._validate(os.fstat(self._directory), directory=True)
        current = self._validate(self.root.lstat(), directory=True)
        if opened != current or opened != self._directory_identity:
            raise LocalRecordError(LocalRecordErrorCodeV1.CONFLICT)

    @staticmethod
    def _validate(info: os.stat_result, *, directory: bool = False) -> FileIdentity:
        if (
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or info.st_uid != getattr(os, "geteuid")() or info.st_mode & 0o077
            or (not directory and info.st_nlink != 1)
        ):
            raise LocalRecordError(LocalRecordErrorCodeV1.UNAVAILABLE)
        return info.st_dev, info.st_ino

    def _open(self, name: str, mode: FileMode) -> int:
        flags = getattr(os, "O_NOFOLLOW") | getattr(os, "O_CLOEXEC") | getattr(os, "O_NONBLOCK")
        flags |= os.O_RDONLY if mode in {"read", "delete"} else os.O_RDWR | os.O_CREAT
        if mode == "new":
            flags |= os.O_EXCL
        return os.open(name, flags, 0o600, dir_fd=self._directory)

    def identity(self, descriptor: int) -> FileIdentity:
        return self._validate(os.fstat(descriptor))

    def replace(self, source: str, target: str) -> None:
        self.check_root()
        os.replace(source, target, src_dir_fd=self._directory, dst_dir_fd=self._directory)
        assert self._directory is not None
        os.fsync(self._directory)

    def remove(self, name: str, expected: FileIdentity) -> None:
        self.check_root()
        if self.named_identity(name) == expected:
            os.unlink(name, dir_fd=self._directory)
            assert self._directory is not None
            os.fsync(self._directory)

    def lock(self, descriptor: int) -> None:
        module = import_module("fcntl")
        try:
            module.flock(descriptor, module.LOCK_EX | module.LOCK_NB)
        except BlockingIOError:
            raise LocalRecordError(LocalRecordErrorCodeV1.LOCKED) from None

    def unlock(self, descriptor: int) -> None:
        module = import_module("fcntl")
        module.flock(descriptor, module.LOCK_UN)

    def _close_root(self) -> None:
        descriptor = self._directory
        if descriptor is not None:
            self._directory = None
            try:
                os.close(descriptor)
            except OSError:
                self._uncertain_close = True
                raise
