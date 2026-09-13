"""Linux private-file owner for managed deployment storage, with no domain policy.

The caller injects a narrow canonical directory whose parent already exists.
Stable lock files are never unlinked. All IO is relative to a retained directory
descriptor, with path/descriptor identity checked around admitted operations.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from secrets import token_hex
from threading import RLock

_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")
MAX_RECORD_BYTES = 16 * 1024
FileIdentity = tuple[int, int]


class ManagedStorageError(RuntimeError):
    """Closed error codes, never native paths or file content."""

    def __init__(self, code: str) -> None:
        if code not in {"unsupported", "unavailable", "not_found", "conflict",
                        "busy", "closed", "invalid_record", "capacity"}:
            raise ValueError("invalid managed storage error")
        self.code = code
        super().__init__("managed_storage_" + code)


@dataclass(frozen=True, slots=True)
class ManagedFileSnapshot:
    content: bytes = field(repr=False)
    identity: FileIdentity


class PrivateManagedDirectory:
    """One retained directory; not an authority to recursively clean its parent."""

    def __init__(self, root: Path, *, create: bool = False) -> None:
        self._fd: int | None = None
        self._parents: list[tuple[int, str, int, FileIdentity]] = []
        self._anchor: int | None = None
        self._parent: int | None = None
        self._locks: dict[str, tuple[int, FileIdentity]] = {}
        self._pending: dict[str, FileIdentity | None] = {}
        self._unlinked: set[str] = set()
        self._mutex = RLock()
        self._root = root
        if sys.platform != "linux":
            raise ManagedStorageError("unsupported")
        if type(create) is not bool or not isinstance(root, Path):
            raise ManagedStorageError("unavailable")
        try:
            if (
                not root.is_absolute() or root == root.parent
                or ".." in root.parts or str(root).startswith("//")
                or "\0" in str(root)
            ):
                raise ManagedStorageError("unavailable")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            self._anchor = os.open("/", flags)
            parent = self._anchor
            for part in root.parts[1:-1]:
                fd = os.open(part, flags, dir_fd=parent)
                try:
                    identity = self._validate_parent(os.fstat(fd))
                except BaseException:
                    _close_preserving_primary(fd)
                    raise
                self._parents.append((parent, part, fd, identity))
                parent = fd
            self._parent = parent
            self._check_parents()
            if create:
                try:
                    os.mkdir(root.name, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                else:
                    os.fsync(parent)
            self._check_parents()
            fd = os.open(root.name, flags, dir_fd=parent)
            self._fd = fd
            self._identity = self._validate(os.fstat(fd), directory=True)
            self._check()
        except BaseException as error:
            try:
                self.close()
            except BaseException:
                error.add_note("managed_directory_cleanup_incomplete")
            if isinstance(error, FileNotFoundError):
                raise _storage_error("not_found", error) from None
            if isinstance(error, OSError):
                raise _storage_error("unavailable", error) from None
            raise

    @staticmethod
    def _validate_parent(info: os.stat_result) -> FileIdentity:
        # Trusted root-owned sticky ancestors such as /tmp are allowed, but
        # the retained final root itself must still be owner-private.
        if (
            not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.geteuid()}
            or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))
        ):
            raise ManagedStorageError("unavailable")
        return info.st_dev, info.st_ino

    def _check_parents(self) -> None:
        for parent, name, fd, identity in self._parents:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                self._validate_parent(current) != identity
                or self._validate_parent(os.fstat(fd)) != identity
            ):
                raise ManagedStorageError("conflict")

    @staticmethod
    def _validate(info: os.stat_result, *, directory: bool = False) -> FileIdentity:
        if (
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or (not directory and info.st_nlink != 1)
        ):
            raise ManagedStorageError("unavailable")
        return info.st_dev, info.st_ino

    def _check(self) -> int:
        if self._fd is None:
            raise ManagedStorageError("closed")
        self._check_parents()
        if (
            self._validate(os.fstat(self._fd), directory=True) != self._identity
            or self._validate(os.stat(self._root.name, dir_fd=self._parent, follow_symlinks=False),
                              directory=True) != self._identity
        ):
            raise ManagedStorageError("conflict")
        for name, (fd, identity) in self._locks.items():
            info = os.stat(name, dir_fd=self._fd, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != identity:
                raise ManagedStorageError("conflict")
            self._validate(info)
            self._validate(os.fstat(fd))
        return self._fd

    @contextmanager
    def _operation(self) -> Iterator[int]:
        with self._mutex:
            try:
                fd = self._check()
                yield fd
                self._check()
            except FileNotFoundError as error:
                raise _storage_error("not_found", error) from None
            except OSError as error:
                raise _storage_error("unavailable", error) from None

    def _open(self, name: str, flags: int, *, create: bool = False) -> int:
        _name(name)
        parent = self._check()
        fd = os.open(
            name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            0o600, dir_fd=parent,
        )
        try:
            identity = self._validate(os.fstat(fd))
            self._check_named(name, identity)
            if create:
                os.fsync(parent)
            return fd
        except BaseException:
            _close_preserving_primary(fd)
            raise

    def _check_named(self, name: str, expected: FileIdentity) -> None:
        parent = self._check()
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if self._validate(info) != expected:
            raise ManagedStorageError("conflict")

    def read(self, name: str) -> ManagedFileSnapshot | None:
        _name(name)
        with self._operation():
            try:
                fd = self._open(name, os.O_RDONLY)
            except FileNotFoundError:
                return None
            try:
                before = os.fstat(fd)
                if before.st_size > MAX_RECORD_BYTES:
                    raise ManagedStorageError("invalid_record")
                chunks = bytearray()
                while len(chunks) <= MAX_RECORD_BYTES:
                    block = os.read(fd, MAX_RECORD_BYTES + 1 - len(chunks))
                    if not block:
                        break
                    chunks.extend(block)
                after = os.fstat(fd)
                if len(chunks) > MAX_RECORD_BYTES:
                    raise ManagedStorageError("invalid_record")
                identity = self._validate(after)
                self._check_named(name, identity)
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns
                ):
                    raise ManagedStorageError("conflict")
                return ManagedFileSnapshot(bytes(chunks), identity)
            finally:
                _close_preserving_primary(fd)

    @contextmanager
    def lock(self, name: str, *, create: bool = False) -> Iterator[None]:
        """Nonblocking stable flock; the caller never gains an unlink right."""
        _name(name)
        if type(create) is not bool or not name.endswith(".lock"):
            raise ManagedStorageError("invalid_record")
        with self._operation():
            if name in self._locks:
                raise ManagedStorageError("busy")
            fd = self._open(name, os.O_RDWR | (os.O_CREAT if create else 0), create=create)
            fcntl = import_module("fcntl")
            try:
                identity = self._validate(os.fstat(fd))
                if os.fstat(fd).st_size != 0:
                    raise ManagedStorageError("invalid_record")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ManagedStorageError("busy") from None
                self._check_named(name, identity)
                self._locks[name] = (fd, identity)
                yield
                self._check_named(name, identity)
            finally:
                # Closing this exact descriptor releases only this flock. Never
                # unlink a lock on release or retry close after an uncertain error.
                self._locks.pop(name, None)
                _close_preserving_primary(fd)

    def write(self, name: str, content: bytes, *, expected: ManagedFileSnapshot | None) -> None:
        """Publish under a caller-held stable lock; fsync failure remains unknown.

        `expected=None` requires no previous record. Replacement needs both the
        old file identity and its bounded bytes, preventing stale replacement.
        The caller must serialize cooperating writers via lock().
        """
        _name(name)
        if name.endswith(".lock") or type(content) is not bytes or len(content) > MAX_RECORD_BYTES:
            raise ManagedStorageError("invalid_record")
        if expected is not None and type(expected) is not ManagedFileSnapshot:
            raise ManagedStorageError("invalid_record")
        with self._operation() as parent:
            if not self._locks or self._pending:
                raise ManagedStorageError("busy")
            if self.read(name) != expected:
                raise ManagedStorageError("conflict")
            temporary = "pending-" + token_hex(16)
            fd = os.open(
                temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                | os.O_CLOEXEC | os.O_NONBLOCK, 0o600, dir_fd=parent,
            )
            self._pending[temporary] = None
            published = False
            try:
                identity = self._validate(os.fstat(fd))
                self._pending[temporary] = identity
                self._check_named(temporary, identity)
                os.fsync(parent)
                remaining = memoryview(content)
                while remaining:
                    written = os.write(fd, remaining)
                    if written <= 0:
                        raise ManagedStorageError("unavailable")
                    remaining = remaining[written:]
                os.fsync(fd)
                self._check_named(temporary, identity)
                if self.read(name) != expected:
                    raise ManagedStorageError("conflict")
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                published = True
                self._pending.pop(temporary)
                os.fsync(parent)
            finally:
                primary = sys.exception()
                failures = []
                if not published and self._pending[temporary] is None:
                    try:
                        self._pending[temporary] = self._validate(os.fstat(fd))
                    except BaseException as error:
                        failures.append(error)
                try:
                    os.close(fd)
                except OSError as error:
                    failures.append(error)
                if not published:
                    try:
                        self._cleanup_pending()
                    except BaseException as error:
                        failures.append(error)
                if failures:
                    if primary is not None:
                        primary.add_note("managed_record_cleanup_incomplete")
                    else:
                        raise ManagedStorageError("unavailable") from None

    @property
    def cleanup_pending(self) -> bool:
        return bool(self._pending)

    def _cleanup_pending(self) -> None:
        parent = self._check()
        for name, identity in tuple(self._pending.items()):
            if identity is None:
                raise ManagedStorageError("unavailable")
            if name not in self._unlinked:
                try:
                    self._check_named(name, identity)
                except FileNotFoundError:
                    pass
                else:
                    os.unlink(name, dir_fd=parent)
                self._unlinked.add(name)
            # A failed sync retains debt. Retrying only syncs the directory;
            # it must never unlink a subsequently created same-name file.
            os.fsync(parent)
            del self._pending[name]
            self._unlinked.discard(name)

    def close(self) -> None:
        with self._mutex:
            if self._locks:
                raise ManagedStorageError("busy")
            if self._pending:
                with self._operation():
                    self._cleanup_pending()
            descriptors = []
            if self._fd is not None:
                descriptors.append(self._fd)
                self._fd = None
            descriptors.extend(item[2] for item in reversed(self._parents))
            self._parents.clear()
            if self._anchor is not None:
                descriptors.append(self._anchor)
                self._anchor = None
            failed = False
            for fd in descriptors:
                try:
                    os.close(fd)
                except OSError:
                    failed = True
            if failed:
                raise ManagedStorageError("unavailable") from None


def _name(name: str) -> None:
    if type(name) is not str or _NAME.fullmatch(name) is None:
        raise ManagedStorageError("invalid_record")


def _close_preserving_primary(fd: int) -> None:
    primary = sys.exception()
    try:
        os.close(fd)
    except OSError:
        if primary is not None:
            primary.add_note("managed_file_close_incomplete")
        else:
            raise ManagedStorageError("unavailable") from None


def _storage_error(code: str, original: BaseException) -> ManagedStorageError:
    error = ManagedStorageError(code)
    # Preserve only our bounded cleanup signal, never native text or notes.
    if any(note in {
        "managed_file_close_incomplete", "managed_record_cleanup_incomplete",
        "managed_directory_cleanup_incomplete",
    } for note in getattr(original, "__notes__", ())):
        error.add_note("managed_storage_cleanup_incomplete")
    return error
