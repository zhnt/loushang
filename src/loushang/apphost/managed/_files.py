"""Linux private-file owner for managed deployment storage, with no domain policy.

The caller injects a narrow canonical directory. Parents must exist unless
explicit parent creation is requested for new deployment initialization.
Stable lock files are never unlinked. All IO is relative to a retained directory
descriptor, with path/descriptor identity checked around admitted operations.
"""

from __future__ import annotations

import errno
import os
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from hashlib import sha256
from importlib import import_module
from math import isfinite
from pathlib import Path
from secrets import token_hex
from threading import RLock
from time import monotonic, sleep
from typing import Protocol

_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")
MAX_RECORD_BYTES = 16 * 1024
FileIdentity = tuple[int, int]


class _DirectoryScan(Protocol):
    def __iter__(self) -> Iterator[os.DirEntry[str]]: ...
    def close(self) -> None: ...


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


@dataclass(frozen=True, slots=True)
class ManagedDataFileSnapshot:
    """Bounded tail and change stamp; neither allocation nor write authority."""

    identity: FileIdentity
    size: int
    mtime_ns: int
    ctime_ns: int
    tail: bytes = field(repr=False)


@dataclass(eq=False, slots=True)
class _DataRemoval:
    owner: PrivateManagedDirectory = field(repr=False)
    name: str
    isolated_name: str
    expected: ManagedDataFileSnapshot
    capacity: int
    root_identity: FileIdentity
    target: ManagedRemovalTarget
    phase: str = "new"
    fd: int | None = None
    isolated: ManagedDataFileSnapshot | None = None
    abandoned: bool = False
    binding: object | None = field(default=None, repr=False)
    _completion: object | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ManagedRemovalTarget:
    """Native owner's frozen facts; not a caller-supplied accounting permit."""

    root_key: str
    root_identity: FileIdentity
    file_identity: FileIdentity
    capacity: int


@dataclass(eq=False, slots=True)
class _DataCreation:
    owner: PrivateManagedDirectory = field(repr=False)
    allocation_id: str
    name: str
    capacity: int
    binding: object = field(repr=False)
    target: ManagedCreationTarget
    phase: str = "new"
    snapshot: ManagedDataFileSnapshot | None = None
    _completion: object | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ManagedCreationTarget:
    """Original native destination, independent of unbound accounting rows."""

    root_key: str
    root_identity: FileIdentity
    allocation_id: str
    name: str
    capacity: int


class PrivateManagedDirectory:
    """One retained directory; not an authority to recursively clean its parent."""

    def __init__(self, root: Path, *, create: bool = False, defer_open: bool = False,
                 create_parents: bool = False, exclusive_create: bool = False) -> None:
        self._fd: int | None = None
        self._parents: list[tuple[int, str, int, FileIdentity]] = []
        self._anchor: int | None = None
        self._parent: int | None = None
        self._locks: dict[str, tuple[int, FileIdentity]] = {}
        self._pending: dict[str, FileIdentity | None] = {}
        self._unlinked: set[str] = set()
        self._mutex = RLock()
        self._root = root
        self._create = create
        self._opening_fd: int | None = None
        self._uncertain_closes: set[int] = set()
        self._close_pending: set[int] = set()
        self._sync_pending: set[int] = set()
        self._data_sync_pending: set[int] = set()
        self._data_failed = False
        self._removals: list[_DataRemoval] = []
        self._creations: list[_DataCreation] = []
        self._creation_high_water = ""
        self._scan: _DirectoryScan | None = None
        self._scan_close_unknown = False
        self._create_parents = create_parents
        self._exclusive_create = exclusive_create
        self._attempted = self._opened = self._closing = False
        if sys.platform != "linux":
            raise ManagedStorageError("unsupported")
        if (type(create) is not bool or type(defer_open) is not bool or not isinstance(root, Path)
                or type(create_parents) is not bool or (create_parents and not create)
                or type(exclusive_create) is not bool or (exclusive_create and not create)):
            raise ManagedStorageError("unavailable")
        if create_parents:
            try:
                if len(root.parts) > 64 or len(str(root).encode("utf-8")) > 4096:
                    raise ManagedStorageError("capacity")
            except UnicodeError:
                raise ManagedStorageError("unavailable") from None
        if (
            not root.is_absolute() or root == root.parent
            or ".." in root.parts or str(root).startswith("//") or "\0" in str(root)
        ):
            raise ManagedStorageError("unavailable")
        if defer_open:
            return
        try:
            self.open()
        except BaseException as error:
            try:
                self.close()
            except BaseException:
                error.add_note("managed_directory_cleanup_incomplete")
            raise

    def open(self, *, deadline: float | None = None) -> None:
        """One admission attempt on a previously retained container.

        Failure retains all acquired descriptors. Explicit close is required;
        neither a failed admission nor a partial close permits reopening.
        """
        _check_deadline(deadline)
        acquired = (self._mutex.acquire() if deadline is None else
                    self._mutex.acquire(timeout=max(0.0, min(30.0, deadline - monotonic()))))
        if not acquired:
            raise ManagedStorageError("busy")
        try:
            if self._attempted or self._closing:
                raise ManagedStorageError("closed")
            _check_deadline(deadline)
            self._attempted = True
            root = self._root
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            self._anchor = os.open("/", flags)
            parent = self._anchor
            for part in root.parts[1:-1]:
                _check_deadline(deadline)
                if self._create_parents:
                    self._prepare_entry(parent, part, deadline=deadline)
                fd = os.open(part, flags, dir_fd=parent)
                self._opening_fd = fd
                identity = self._validate_parent(os.fstat(fd))
                self._parents.append((parent, part, fd, identity))
                self._opening_fd = None
                if self._create_parents:
                    self._check_parents()
                    _check_deadline(deadline)
                    self._sync_parent(parent)
                    self._check_parents()
                parent = fd
            self._parent = parent
            self._check_parents()
            _check_deadline(deadline)
            if self._create:
                if self._exclusive_create:
                    # Record possible publication debt before mkdir. A lost
                    # receipt must not authorize adopting or deleting the leaf.
                    self._sync_pending.add(parent)
                    os.mkdir(root.name, mode=0o700, dir_fd=parent)
                elif self._create_parents:
                    self._prepare_entry(parent, root.name, deadline=deadline)
                else:
                    try:
                        os.mkdir(root.name, mode=0o700, dir_fd=parent)
                    except FileExistsError:
                        pass
                    else:
                        self._sync_pending.add(parent)
                        os.fsync(parent)
                        self._sync_pending.discard(parent)
            self._check_parents()
            _check_deadline(deadline)
            fd = os.open(root.name, flags, dir_fd=parent)
            self._fd = fd
            self._identity = self._validate(os.fstat(fd), directory=True)
            self._check()
            if self._create_parents or self._exclusive_create:
                _check_deadline(deadline)
                self._sync_parent(parent)
                self._check()
            _check_deadline(deadline)
            self._opened = True
        except FileExistsError as error:
            raise _storage_error("conflict", error) from None
        except FileNotFoundError as error:
            raise _storage_error("not_found", error) from None
        except OSError as error:
            raise _storage_error("unavailable", error) from None
        finally:
            self._mutex.release()

    def _prepare_entry(self, parent: int, name: str, *, deadline: float | None) -> None:
        self._check_parents()
        _check_deadline(deadline)
        # EEXIST may be another initializer's not-yet-synced mkdir. Each
        # successful admission obtains its own durability evidence.
        self._sync_pending.add(parent)
        with suppress(FileExistsError):
            os.mkdir(name, mode=0o700, dir_fd=parent)
        self._check_parents()
        _check_deadline(deadline)

    def _sync_parent(self, parent: int) -> None:
        # Bind the child inode before collecting durability evidence, and
        # recheck it afterwards. Pre-open fsync could cover a replaced edge.
        os.fsync(parent)
        self._sync_pending.discard(parent)

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
    def _operation(self, *, deadline: float | None = None, _cleanup: bool = False) -> Iterator[int]:
        _check_deadline(deadline)
        if _on_event_loop():
            acquired = self._mutex.acquire(blocking=False)
        else:
            acquired = (self._mutex.acquire() if deadline is None else
                        self._mutex.acquire(timeout=max(0.0, min(30.0, deadline - monotonic()))))
        if not acquired:
            raise ManagedStorageError("busy")
        try:
            _check_deadline(deadline)
            if not self._opened:
                raise ManagedStorageError("closed")
            if not _cleanup:
                if self._closing:
                    raise ManagedStorageError("closed")
                if self._uncertain_closes or self._scan_close_unknown:
                    raise ManagedStorageError("busy")
            try:
                fd = self._check()
                yield fd
                self._check()
            except FileNotFoundError as error:
                raise _storage_error("not_found", error) from None
            except OSError as error:
                raise _storage_error("unavailable", error) from None
        finally:
            self._mutex.release()

    def _open(self, name: str, flags: int, *, create: bool = False, retain: bool = False) -> int:
        _name(name)
        parent = self._check()
        if create:
            self._sync_pending.add(parent)
        fd = os.open(
            name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            0o600, dir_fd=parent,
        )
        if retain:
            self._close_pending.add(fd)
        try:
            identity = self._validate(os.fstat(fd))
            self._check_named(name, identity)
            if create:
                os.fsync(parent)
                self._sync_pending.discard(parent)
                self._check_named(name, identity)
            return fd
        except BaseException as error:
            self._close_preserving_primary(fd, primary=error)
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
            primary = None
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
            except BaseException as error:
                primary = error
                raise
            finally:
                self._close_preserving_primary(fd, primary=primary)

    def _data_snapshot(self, name: str, fd: int, capacity: int) -> ManagedDataFileSnapshot:
        before = os.fstat(fd)
        identity = self._validate(before)
        if before.st_size > capacity:
            raise ManagedStorageError("capacity")
        start = max(0, before.st_size - MAX_RECORD_BYTES)
        tail = bytearray()
        while len(tail) < before.st_size - start:
            block = os.pread(fd, before.st_size - start - len(tail), start + len(tail))
            if not block:
                raise ManagedStorageError("conflict")
            tail.extend(block)
        after = os.fstat(fd)
        self._check_named(name, identity)
        if (self._validate(after) != identity or
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ManagedStorageError("conflict")
        return ManagedDataFileSnapshot(identity, after.st_size, after.st_mtime_ns,
                                       after.st_ctime_ns, bytes(tail))

    def data_snapshot(self, name: str, *, capacity: int) -> ManagedDataFileSnapshot | None:
        """Read at most one record-sized tail, without creating or repairing."""
        _data_arguments(name, capacity)
        with self._operation():
            try:
                fd = self._open(name, os.O_RDONLY, retain=True)
            except FileNotFoundError:
                return None
            primary = None
            try:
                return self._data_snapshot(name, fd, capacity)
            except BaseException as error:
                primary = error
                raise
            finally:
                self._close_preserving_primary(fd, primary=primary)

    def read_data(self, name: str, *, expected: ManagedDataFileSnapshot,
                  capacity: int, max_bytes: int) -> bytes:
        """Read one sealed identity within a hard limit, without adopting a path.

        The original worker owns this entire operation, including fd close.
        A cancelled async waiter must retain that worker before cleanup begins.
        """
        _data_arguments(name, capacity)
        if (type(expected) is not ManagedDataFileSnapshot or type(max_bytes) is not int
                or max_bytes < 0 or type(expected.size) is not int or expected.size < 0):
            raise ManagedStorageError("invalid_record")
        if expected.size > min(capacity, max_bytes):
            raise ManagedStorageError("capacity")
        with self._operation():
            if self._data_cleanup_pending or self._data_failed:
                raise ManagedStorageError("busy")
            fd = self._open(name, os.O_RDONLY, retain=True)
            primary = None
            try:
                if self._data_snapshot(name, fd, capacity) != expected:
                    raise ManagedStorageError("conflict")
                result = bytearray()
                while len(result) < expected.size:
                    block = os.pread(fd, min(MAX_RECORD_BYTES, expected.size - len(result)), len(result))
                    if not block:
                        raise ManagedStorageError("conflict")
                    result.extend(block)
                if self._data_snapshot(name, fd, capacity) != expected:
                    raise ManagedStorageError("conflict")
                return bytes(result)
            except BaseException as error:
                primary = error
                raise
            finally:
                self._close_preserving_primary(fd, primary=primary)

    def isolate_data(self, name: str, isolated_name: str, *, expected: ManagedDataFileSnapshot,
                     capacity: int) -> ManagedDataFileSnapshot:
        """Move an exact data file without overwriting a quarantine destination.

        Caller retains both names before entry. This is not deletion or refund
        proof. Unknown rename/sync/close seals data writes; close settles only
        original descriptors and sync debt, never repeats the rename.
        """
        _data_arguments(name, capacity)
        _data_arguments(isolated_name, capacity)
        if (type(expected) is not ManagedDataFileSnapshot or name == isolated_name
                or not isolated_name.startswith("removed-")):
            raise ManagedStorageError("invalid_record")
        effect = False
        try:
            with self._operation() as parent:
                if not self._locks or self.cleanup_pending or self._data_failed:
                    raise ManagedStorageError("busy")
                fd = self._open(name, os.O_RDONLY, retain=True)
                primary = None
                try:
                    if self._data_snapshot(name, fd, capacity) != expected:
                        raise ManagedStorageError("conflict")
                    effect = True
                    self._sync_pending.add(parent)
                    _rename_data_noreplace(parent, name, isolated_name)
                    after = self._data_snapshot(isolated_name, fd, capacity)
                    if (after.identity, after.size, after.mtime_ns, after.tail) != (
                            expected.identity, expected.size, expected.mtime_ns, expected.tail):
                        raise ManagedStorageError("conflict")
                    self._sync_parent(parent)
                    if self._data_snapshot(isolated_name, fd, capacity) != after:
                        raise ManagedStorageError("conflict")
                    return after
                except BaseException as error:
                    primary = error
                    raise
                finally:
                    self._close_preserving_primary(fd, primary=primary)
        except BaseException:
            if effect:
                self._data_failed = True
            raise

    def prepare_data_removal(self, name: str, isolated_name: str, *,
                             expected: ManagedDataFileSnapshot, capacity: int) -> _DataRemoval:
        """Enroll the original removal before native effects; perform no IO."""
        if _on_event_loop():
            raise ManagedStorageError("busy")
        _data_arguments(name, capacity)
        _data_arguments(isolated_name, capacity)
        if (type(expected) is not ManagedDataFileSnapshot or name == isolated_name
                or not isolated_name.startswith("removed-") or name.endswith(".lock")):
            raise ManagedStorageError("invalid_record")
        with self._mutex:
            if not self._opened or self._closing:
                raise ManagedStorageError("closed")
            if len(self._removals) >= 8:
                raise ManagedStorageError("capacity")
            if any({name, isolated_name} & {item.name, item.isolated_name} for item in self._removals):
                raise ManagedStorageError("conflict")
            target = ManagedRemovalTarget(sha256(os.fsencode(self._root)).hexdigest(),
                                          self._identity, expected.identity, capacity)
            removal = _DataRemoval(self, name, isolated_name, expected, capacity, self._identity, target)
            self._removals.append(removal)
            return removal

    def removal_target(self, removal: _DataRemoval) -> ManagedRemovalTarget:
        if _on_event_loop():
            raise ManagedStorageError("busy")
        with self._mutex:
            if (type(removal) is not _DataRemoval or removal.owner is not self
                    or removal not in self._removals or removal.phase != "new" or removal.abandoned):
                raise ManagedStorageError("conflict")
            return removal.target

    def bind_data_removal(self, removal: _DataRemoval, binding: object) -> None:
        """Attach opaque original accounting context before native deletion."""
        self.removal_target(removal)
        with self._mutex:
            if removal.phase != "new" or removal.abandoned or binding is None:
                raise ManagedStorageError("conflict")
            if removal.binding is not None and removal.binding is not binding:
                raise ManagedStorageError("conflict")
            removal.binding = binding

    def completed_removal_target(self, removal: _DataRemoval, binding: object, *,
                                 deadline: float | None = None) -> ManagedRemovalTarget:
        """Verify the original completion marker, not merely a phase string."""
        _check_deadline(deadline)
        if _on_event_loop():
            raise ManagedStorageError("busy")
        acquired = (self._mutex.acquire() if deadline is None else
                    self._mutex.acquire(timeout=max(0.0, min(30.0, deadline - monotonic()))))
        if not acquired:
            raise ManagedStorageError("busy")
        try:
            _check_deadline(deadline)
            if (type(removal) is not _DataRemoval or removal.owner is not self
                    or removal._completion is None or removal.phase != "complete"
                    or removal.abandoned or binding is None or removal.binding is not binding):
                raise ManagedStorageError("unavailable")
            return removal.target
        finally:
            self._mutex.release()

    def remove_data(self, removal: _DataRemoval) -> None:
        """Continue original removal; unknown rename/unlink/close is never replayed.

        Caller fences all writers/readers before entry. Completion covers this
        owner's file descriptors only and is not itself an allocation refund.
        """
        if _on_event_loop():
            raise ManagedStorageError("busy")
        with self._mutex:
            self._remove_data(removal)

    def abandon_data_removal(self, removal: _DataRemoval) -> None:
        """Fence further removal, without claiming deletion or refund.

        The original directory close may now settle known descriptors/sync debt.
        Keep the original phase and object as evidence that deletion was not
        proven. No file is opened, removed or adopted by this operation.
        """
        if _on_event_loop():
            raise ManagedStorageError("busy")
        with self._mutex:
            if (type(removal) is not _DataRemoval or removal.owner is not self
                    or removal not in self._removals):
                raise ManagedStorageError("conflict")
            removal.abandoned = True

    def _remove_data(self, removal: _DataRemoval) -> None:
        if type(removal) is not _DataRemoval or removal.owner is not self:
            raise ManagedStorageError("conflict")
        if removal.abandoned:
            raise ManagedStorageError("unavailable")
        if removal.phase == "complete":
            return
        with self._operation() as parent:
            if (removal not in self._removals or not self._locks
                    or removal.root_identity != self._identity):
                raise ManagedStorageError("conflict")
            if removal.target != ManagedRemovalTarget(
                sha256(os.fsencode(self._root)).hexdigest(), self._identity,
                removal.expected.identity, removal.capacity,
            ):
                raise ManagedStorageError("conflict")
            if removal.phase in {"rename_unknown", "unlink_unknown", "close_unknown"}:
                raise ManagedStorageError("unavailable")
            if removal.phase == "new":
                if self._io_cleanup_pending or self._data_failed:
                    raise ManagedStorageError("busy")
                removal.fd = self._open(removal.name, os.O_RDONLY, retain=True)
                removal.phase = "opened"
            fd = removal.fd
            if fd is None:
                raise ManagedStorageError("unavailable")
            if removal.phase == "opened":
                if self._data_snapshot(removal.name, fd, removal.capacity) != removal.expected:
                    raise ManagedStorageError("conflict")
                removal.phase = "rename_unknown"
                self._sync_pending.add(parent)
                _rename_data_noreplace(parent, removal.name, removal.isolated_name)
                after = self._data_snapshot(removal.isolated_name, fd, removal.capacity)
                if (after.identity, after.size, after.mtime_ns, after.tail) != (
                        removal.expected.identity, removal.expected.size,
                        removal.expected.mtime_ns, removal.expected.tail):
                    raise ManagedStorageError("conflict")
                removal.isolated = after
                removal.phase = "isolated"
            if removal.phase == "isolated":
                if self._data_snapshot(removal.isolated_name, fd, removal.capacity) != removal.isolated:
                    raise ManagedStorageError("conflict")
                self._check_named(removal.isolated_name, removal.expected.identity)
                if self._validate(os.fstat(fd)) != removal.expected.identity:
                    raise ManagedStorageError("conflict")
                removal.phase = "unlink_unknown"
                os.unlink(removal.isolated_name, dir_fd=parent)
                after_unlink = os.fstat(fd)
                if ((after_unlink.st_dev, after_unlink.st_ino) != removal.expected.identity
                        or after_unlink.st_nlink != 0):
                    raise ManagedStorageError("conflict")
                removal.phase = "unlinked"
            if removal.phase == "unlinked":
                self._sync_parent(parent)
                removal.phase = "synced"
            if removal.phase == "synced":
                removal.phase = "close_unknown"
                self._close_preserving_primary(fd, primary=None)
                removal.phase = "closed"
            if self._io_cleanup_pending:
                raise ManagedStorageError("busy")
        removal.phase = "complete"
        removal._completion = object()
        self._removals.remove(removal)

    def names(self, *, limit: int) -> tuple[str, ...]:
        """Bounded directory discovery, never following entries or reading data."""
        if type(limit) is not int or not 0 < limit <= 32:
            raise ManagedStorageError("invalid_record")
        with self._operation() as parent:
            if self._scan is not None:
                raise ManagedStorageError("busy")
            names: list[str] = []
            self._scan = os.scandir(parent)
            primary = None
            try:
                for entry in self._scan:
                    if len(names) == limit:
                        raise ManagedStorageError("capacity")
                    names.append(entry.name)
            except BaseException as error:
                primary = error
                raise
            finally:
                self._scan_close_unknown = True
                try:
                    self._scan.close()
                except BaseException:
                    if primary is not None:
                        primary.add_note("managed_directory_cleanup_incomplete")
                    else:
                        raise ManagedStorageError("unavailable") from None
                else:
                    self._scan = None
                    self._scan_close_unknown = False
            return tuple(names)

    def prepare_data_creation_pair(self, allocation_ids: tuple[str, str], *,
                                   capacity: int, binding: object, deadline: float | None = None
                                   ) -> tuple[_DataCreation, _DataCreation]:
        """Register a fresh pair atomically, before enqueueing any native create.

        The caller binds the original reservation attempt, not recovered rows.
        A lifetime high-water prevents reissuing zero-effect facts after removal
        of settled trackers, without retaining unbounded per-file tombstones.
        """
        if _on_event_loop():
            raise ManagedStorageError("busy")
        if (type(allocation_ids) is not tuple or len(allocation_ids) != 2
                or any(type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None
                       for value in allocation_ids) or binding is None):
            raise ManagedStorageError("invalid_record")
        first, second = allocation_ids
        _data_arguments("capture-" + first, capacity)
        with self._creation_lock(deadline=deadline):
            if not self._opened or self._closing:
                raise ManagedStorageError("closed")
            if not self._creation_high_water < first < second:
                raise ManagedStorageError("conflict")
            if len(self._creations) > 6:
                raise ManagedStorageError("capacity")
            root_key = sha256(os.fsencode(self._root)).hexdigest()
            def tracker(allocation_id: str) -> _DataCreation:
                name = "capture-" + allocation_id
                target = ManagedCreationTarget(root_key, self._identity, allocation_id, name, capacity)
                return _DataCreation(self, allocation_id, name, capacity, binding, target)
            pair = (tracker(first), tracker(second))
            self._creations.extend(pair)
            self._creation_high_water = second
            return pair

    @contextmanager
    def _creation_lock(self, *, deadline: float | None = None) -> Iterator[None]:
        _check_deadline(deadline)
        if _on_event_loop():
            raise ManagedStorageError("busy")
        acquired = (self._mutex.acquire() if deadline is None else
                    self._mutex.acquire(timeout=max(0.0, min(30.0, deadline - monotonic()))))
        if not acquired:
            raise ManagedStorageError("busy")
        try:
            _check_deadline(deadline)
            yield
        finally:
            self._mutex.release()

    def creation_high_water(self, *, deadline: float | None = None) -> str | None:
        with self._creation_lock(deadline=deadline):
            return self._creation_high_water or None

    def pending_creation_pair(self, *, binding: object) -> tuple[_DataCreation, _DataCreation] | None:
        """Recover only original in-memory enrollment after a lost return."""
        with self._creation_lock():
            found = [creation for creation in self._creations if creation.binding is binding]
            if not found:
                return None
            if len(found) != 2:
                raise ManagedStorageError("unavailable")
            return found[0], found[1]

    def creation_target(self, creation: _DataCreation, *, binding: object,
                        require_fenced: bool = False, deadline: float | None = None
                        ) -> ManagedCreationTarget:
        """Read original native facts, optionally requiring zero-effect completion."""
        _check_deadline(deadline)
        if _on_event_loop():
            raise ManagedStorageError("busy")
        acquired = (self._mutex.acquire() if deadline is None else
                    self._mutex.acquire(timeout=max(0.0, min(30.0, deadline - monotonic()))))
        if not acquired:
            raise ManagedStorageError("busy")
        try:
            _check_deadline(deadline)
            if (type(creation) is not _DataCreation or creation.owner is not self
                    or binding is None or creation.binding is not binding
                    or type(require_fenced) is not bool):
                raise ManagedStorageError("conflict")
            if require_fenced:
                if creation.phase != "fenced" or creation._completion is None:
                    raise ManagedStorageError("unavailable")
            elif creation not in self._creations or creation.phase != "new":
                raise ManagedStorageError("conflict")
            target = creation.target
            if (target.root_key != sha256(os.fsencode(self._root)).hexdigest()
                    or target.root_identity != self._identity
                    or (target.allocation_id, target.name, target.capacity)
                    != (creation.allocation_id, creation.name, creation.capacity)):
                raise ManagedStorageError("conflict")
            return target
        finally:
            self._mutex.release()

    def fence_data_creation(self, creation: _DataCreation, *, binding: object) -> bool:
        """Fence queued work; only the original never-admitted attempt succeeds."""
        if _on_event_loop():
            raise ManagedStorageError("busy")
        with self._mutex:
            if (type(creation) is not _DataCreation or creation.owner is not self
                    or creation.binding is not binding):
                raise ManagedStorageError("conflict")
            if creation.phase == "fenced" and creation._completion is not None:
                return True
            if creation not in self._creations or creation.phase != "new":
                return False
            self.creation_target(creation, binding=binding)
            creation.phase = "fenced"
            creation._completion = object()
            self._creations.remove(creation)
            return True

    def create_data(self, creation: _DataCreation, *, binding: object) -> ManagedDataFileSnapshot:
        """Admit once under the fence mutex; an unknown result is never replayed."""
        if _on_event_loop():
            raise ManagedStorageError("busy")
        with self._mutex:
            if (type(creation) is not _DataCreation or creation.owner is not self
                    or creation.binding is not binding or creation not in self._creations
                    or creation.phase != "new"):
                raise ManagedStorageError("conflict")
            self.creation_target(creation, binding=binding)
            creation.phase = "admitted"
            try:
                snapshot = self.append_data(creation.name, b"", expected=None,
                                            capacity=creation.capacity)
            except BaseException:
                creation.phase = "unknown"
                raise
            creation.snapshot = snapshot
            creation.phase = "created"
            self._creations.remove(creation)
            return snapshot

    def append_data(self, name: str, content: bytes, *, expected: ManagedDataFileSnapshot | None,
                    capacity: int, truncate: bool = False) -> ManagedDataFileSnapshot:
        """Bounded append or explicit same-inode rotation under the caller's lock.

        Caller proves charged capacity and instance authorization separately.
        None means exclusive creation. Rotation discards old bytes, with no
        temporary copy. Any uncertain effect seals this owner's data writer;
        close only syncs/closes original fds, never replays or repairs a record.
        """
        _data_arguments(name, capacity)
        if (type(content) is not bytes or len(content) > MAX_RECORD_BYTES
                or type(truncate) is not bool
                or (expected is not None and type(expected) is not ManagedDataFileSnapshot)
                or (truncate and expected is None)):
            raise ManagedStorageError("invalid_record")
        if len(content) > capacity:
            raise ManagedStorageError("capacity")
        effect = False
        try:
            with self._operation() as parent:
                if (not self._locks or self._data_cleanup_pending or self._data_failed):
                    raise ManagedStorageError("busy")
                flags = os.O_RDWR | os.O_APPEND
                if expected is None:
                    flags |= os.O_CREAT | os.O_EXCL
                    effect = True
                try:
                    fd = self._open(name, flags, create=expected is None, retain=True)
                except FileExistsError:
                    raise ManagedStorageError("conflict") from None
                primary = None
                try:
                    before = self._data_snapshot(name, fd, capacity)
                    if expected is not None and before != expected:
                        raise ManagedStorageError("conflict")
                    size = 0 if truncate else before.size
                    if size + len(content) > capacity:
                        raise ManagedStorageError("capacity")
                    effect = True
                    self._data_sync_pending.add(fd)
                    if expected is None:
                        self._sync_pending.add(parent)
                    if truncate:
                        os.ftruncate(fd, 0)
                    remaining = memoryview(content)
                    while remaining:
                        written = os.write(fd, remaining)
                        if written <= 0 or written > len(remaining):
                            raise ManagedStorageError("unavailable")
                        remaining = remaining[written:]
                    after = self._data_snapshot(name, fd, capacity)
                    tail = ((b"" if truncate else before.tail) + content)[-MAX_RECORD_BYTES:]
                    if after.size != size + len(content) or after.tail != tail:
                        raise ManagedStorageError("conflict")
                    os.fsync(fd)
                    self._data_sync_pending.remove(fd)
                    if expected is None:
                        self._sync_parent(parent)
                    if self._data_snapshot(name, fd, capacity) != after:
                        raise ManagedStorageError("conflict")
                    return after
                except BaseException as error:
                    primary = error
                    raise
                finally:
                    if fd not in self._data_sync_pending:
                        self._close_preserving_primary(fd, primary=primary)
        except BaseException:
            if effect:
                self._data_failed = True
            raise

    @contextmanager
    def lock(self, name: str, *, create: bool = False, deadline: float | None = None,
             exclusive_create: bool = False, wait_for_lock: bool = False) -> Iterator[None]:
        """Stable flock, optionally waiting on the original fd off the event loop.

        A deadline alone never enables blocking. No caller gains an unlink right.
        """
        _check_lock_wait(wait_for_lock, deadline)
        _name(name)
        if (type(create) is not bool or not name.endswith(".lock")
                or type(exclusive_create) is not bool or (exclusive_create and not create)):
            raise ManagedStorageError("invalid_record")
        with self._operation(deadline=deadline):
            if name in self._locks:
                raise ManagedStorageError("busy")
            try:
                fd = self._open(name, os.O_RDWR | (os.O_CREAT if create else 0)
                                | (os.O_EXCL if exclusive_create else 0), create=create)
            except FileExistsError as error:
                raise _storage_error("conflict", error) from None
            fcntl = import_module("fcntl")
            primary = None
            try:
                identity = self._validate(os.fstat(fd))
                if os.fstat(fd).st_size != 0:
                    raise ManagedStorageError("invalid_record")
                while True:
                    _check_deadline(deadline)
                    self._check_named(name, identity)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if not wait_for_lock:
                            raise ManagedStorageError("busy") from None
                        assert deadline is not None
                        _check_deadline(deadline)
                        sleep(max(0.0, min(0.01, deadline - monotonic())))
                _check_deadline(deadline)
                self._check_named(name, identity)
                self._locks[name] = (fd, identity)
                yield
                self._check_named(name, identity)
            except BaseException as error:
                primary = error
                raise
            finally:
                # Closing this exact descriptor releases only this flock. Never
                # unlink a lock on release or retry close after an uncertain error.
                self._locks.pop(name, None)
                self._close_preserving_primary(fd, primary=primary)
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
                self._sync_pending.add(parent)
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                published = True
                self._pending.pop(temporary)
                os.fsync(parent)
                self._sync_pending.discard(parent)
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
                    self._uncertain_closes.add(fd)
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
        return bool(self._creations) or self._data_cleanup_pending

    @property
    def _data_cleanup_pending(self) -> bool:
        return (bool(self._removals) or any(item.phase == "unknown" for item in self._creations)
                or self._io_cleanup_pending)

    @property
    def _io_cleanup_pending(self) -> bool:
        return bool(self._pending or self._uncertain_closes or self._sync_pending
                    or self._data_sync_pending or self._close_pending or self._scan is not None)

    def _close_preserving_primary(self, fd: int, *, primary: BaseException | None) -> None:
        self._uncertain_closes.add(fd)
        try:
            os.close(fd)
        except BaseException:
            if primary is not None:
                primary.add_note("managed_file_close_incomplete")
            else:
                raise ManagedStorageError("unavailable") from None
        else:
            self._uncertain_closes.discard(fd)
            self._close_pending.discard(fd)

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
            self._sync_pending.discard(parent)
            del self._pending[name]
            self._unlinked.discard(name)

    def close(self) -> None:
        with self._mutex:
            if self._locks:
                raise ManagedStorageError("busy")
            if any(not item.abandoned and item.phase not in {"rename_unknown", "unlink_unknown", "close_unknown"}
                   for item in self._removals):
                raise ManagedStorageError("busy")
            if any(item.phase == "new" for item in self._creations):
                raise ManagedStorageError("busy")
            self._closing = True
            try:
                # Data durability precedes directory publication durability.
                # These fds have never entered a close attempt.
                for fd in tuple(self._data_sync_pending):
                    os.fsync(fd)
                    self._data_sync_pending.remove(fd)
                for parent in tuple(self._sync_pending):
                    os.fsync(parent)
                    self._sync_pending.remove(parent)
            except OSError:
                # Keep the original parent fd alive; retry sync, never mkdir
                # or deletion. Unknown close still follows the existing ledger.
                raise ManagedStorageError("unavailable") from None
            if self._pending:
                with self._operation(_cleanup=True):
                    self._cleanup_pending()
            # Stage all receipts before clearing any old references. A signal
            # cannot strand the remaining fds in a local-only list.
            if self._opening_fd is not None:
                self._close_pending.add(self._opening_fd)
            if self._fd is not None:
                self._close_pending.add(self._fd)
            self._close_pending.update(item[2] for item in self._parents)
            if self._anchor is not None:
                self._close_pending.add(self._anchor)
            self._opening_fd = self._fd = self._anchor = None
            self._parents.clear()
            failures: list[BaseException] = []
            for fd in tuple(self._close_pending):
                if fd in self._uncertain_closes:
                    continue
                self._uncertain_closes.add(fd)
                try:
                    os.close(fd)
                except BaseException as error:
                    failures.append(error)
                else:
                    self._close_pending.remove(fd)
                    self._uncertain_closes.discard(fd)
            if failures and not isinstance(failures[0], OSError):
                raise failures[0]
            if self._uncertain_closes or self._scan is not None or self._removals or self._creations:
                raise ManagedStorageError("unavailable") from None


def _rename_data_noreplace(parent: int, source: str, target: str) -> None:
    # Same Linux primitive already used by package materialization. No fallback
    # to rename/replace: absence checks cannot prevent destination overwrite.
    import ctypes

    function = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if function is None:
        raise ManagedStorageError("unsupported")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    ctypes.set_errno(0)
    if function(parent, os.fsencode(source), parent, os.fsencode(target), 1) != 0:
        raise ManagedStorageError("conflict" if ctypes.get_errno() == errno.EEXIST else "unavailable")


def _data_arguments(name: str, capacity: int) -> None:
    _name(name)
    if name.endswith(".lock") or type(capacity) is not int or not 0 < capacity <= 128 * 1024**2:
        raise ManagedStorageError("invalid_record")


def _name(name: str) -> None:
    if type(name) is not str or _NAME.fullmatch(name) is None:
        raise ManagedStorageError("invalid_record")


def _check_lock_wait(wait_for_lock: bool, deadline: float | None) -> None:
    if type(wait_for_lock) is not bool or (wait_for_lock and deadline is None):
        raise ManagedStorageError("invalid_record")
    if not wait_for_lock:
        return
    _check_deadline(deadline)
    # A different task on this loop may own the fence across an await. Never
    # block the thread which must resume that task to release its original lock.
    if _on_event_loop():
        raise ManagedStorageError("busy")


def _on_event_loop() -> bool:
    from asyncio import get_running_loop

    try:
        get_running_loop()
    except RuntimeError:
        return False
    return True


def _check_deadline(deadline: float | None) -> None:
    if deadline is None:
        return
    if type(deadline) not in (int, float) or not 0 <= deadline <= 1e12 or not isfinite(deadline):
        raise ManagedStorageError("invalid_record")
    if monotonic() >= deadline:
        raise ManagedStorageError("busy")


def _storage_error(code: str, original: BaseException) -> ManagedStorageError:
    error = ManagedStorageError(code)
    # Preserve only our bounded cleanup signal, never native text or notes.
    if any(note in {
        "managed_file_close_incomplete", "managed_record_cleanup_incomplete",
        "managed_directory_cleanup_incomplete",
    } for note in getattr(original, "__notes__", ())):
        error.add_note("managed_storage_cleanup_incomplete")
    return error
