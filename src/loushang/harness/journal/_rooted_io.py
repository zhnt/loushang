"""Linux descriptor-relative file operations borrowing an existing root owner.

The caller retains the root and this adapter before admitting any operation,
drains native calls, then settles this adapter's cleanup ledger before closing
the root. Path values are lexical labels, never native path authorities.
"""

from __future__ import annotations

import os
import secrets
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, RLock, get_ident
from typing import Protocol

DirectoryBinding = tuple[tuple[int, int], str, tuple[int, int]]


class _DirectoryEntries(Protocol):
    def __iter__(self) -> Iterator[os.DirEntry[str]]: ...
    def close(self) -> None: ...


@dataclass(eq=False)
class _Operation:
    pid: int = field(default_factory=os.getpid)
    descriptors: dict[int, bool] = field(default_factory=dict)  # True: close outcome unknown.
    temporaries: dict[tuple[int, str], tuple[int, int] | None] = field(default_factory=dict)
    sync_pending: set[int] = field(default_factory=set)
    iterators: list[tuple[_DirectoryEntries, bool]] = field(default_factory=list)
    deletions: list[tuple[int, str, tuple[int, int], bool]] = field(default_factory=list)
    deletion_registered: bool = False
    recoveries: list[tuple[int, Callable[[RootedDirectory], None]]] = field(default_factory=list)
    directory_fds: set[int] = field(default_factory=set)
    lock_fds: set[int] = field(default_factory=set)
    cleanup_thread: int | None = None
    cleanup_token: object | None = None
    durable: bool = True
    active: bool = True
    borrow_active: bool = True
    settlements: list[Event] = field(default_factory=list)
    expected_directories: dict[tuple[int, int, str], tuple[int, int]] = field(default_factory=dict)

    def opened(self, fd: int) -> int:
        self.descriptors[fd] = False
        return fd

    def finish_deletions(self) -> None:
        if os.getpid() != self.pid:
            raise OSError("rooted IO cannot be used after fork")
        for parent in tuple(self.sync_pending):
            os.fsync(parent)
            self.sync_pending.remove(parent)
        while self.deletions:
            parent, name, identity, is_directory = self.deletions[0]
            try:
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if (current.st_dev, current.st_ino) != identity:
                    raise OSError("rooted deletion identity changed")
                if is_directory:
                    _directory(current)
                    os.rmdir(name, dir_fd=parent)
                else:
                    _regular(current)
                    os.unlink(name, dir_fd=parent)
            self.deletions.pop(0)
            self.sync_pending.add(parent)
            os.fsync(parent)
            self.sync_pending.remove(parent)

    def cleanup(self) -> None:
        if os.getpid() != self.pid:
            raise OSError("rooted IO cannot be used after fork")
        failures: list[BaseException] = []
        if self.recoveries and not any(self.descriptors.values()):
            self.cleanup_thread = get_ident()
            try:
                while self.recoveries:
                    parent, recover = self.recoveries[0]
                    self.cleanup_token = object()
                    try:
                        recover(_CleanupDirectory(self, parent, self.cleanup_token))
                    finally:
                        self.cleanup_token = None
                    self.recoveries.pop(0)
            except BaseException as exc:
                failures.append(exc)
            finally:
                self.cleanup_thread = None
        if self.deletions and any(self.descriptors.values()):
            failures.append(OSError("rooted deletion descriptor outcome unknown"))
        else:
            try:
                self.finish_deletions()
            except BaseException as exc:
                failures.append(exc)
        for iterator, unknown in tuple(self.iterators):
            if unknown:
                continue
            self.iterators.remove((iterator, False))
            self.iterators.append((iterator, True))
            try:
                iterator.close()
            except BaseException as exc:
                failures.append(exc)
            else:
                self.iterators.remove((iterator, True))
        for (parent, name), identity in tuple(self.temporaries.items()):
            try:
                if identity is None:
                    raise OSError("rooted IO temporary identity is unknown")
                try:
                    current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    if (current.st_dev, current.st_ino) != identity:
                        raise OSError("rooted IO temporary identity changed")
                    os.unlink(name, dir_fd=parent)
                if self.durable:
                    self.sync_pending.add(parent)
                del self.temporaries[parent, name]
            except BaseException as exc:
                failures.append(exc)
        for parent in tuple(self.sync_pending):
            try:
                os.fsync(parent)
            except BaseException as exc:
                failures.append(exc)
            else:
                self.sync_pending.remove(parent)
        retained_parents = ({parent for parent, _ in self.temporaries} | self.sync_pending
                            | {parent for parent, _, _, _ in self.deletions})
        if self.recoveries:
            retained_parents |= self.directory_fds
        for fd, unknown in tuple(reversed(self.descriptors.items())):
            if fd in self.lock_fds and (failures or self.recoveries or self.deletions
                                       or self.temporaries or self.sync_pending or any(self.descriptors.values())):
                continue
            if unknown or fd in retained_parents:
                continue
            # Publish the fence before close; even interruption cannot retry a
            # number whose native close may already have allowed descriptor reuse.
            self.descriptors[fd] = True
            try:
                os.close(fd)
            except BaseException as exc:
                failures.append(exc)
            else:
                del self.descriptors[fd]
        if failures:
            primary = failures[0]
            for _ in failures[1:]:
                primary.add_note("additional rooted IO cleanup failure")
            raise primary
        if self.descriptors or self.iterators:
            raise OSError("rooted IO descriptor cleanup outcome unknown")
        while self.settlements:
            self.settlements[0].set()
            self.settlements.pop(0)


@dataclass(eq=False)
class _PublicationWitness:
    """One bounded data receipt; its descriptors belong to the original port."""

    operation: _Operation = field(default_factory=lambda: _Operation(active=False, borrow_active=False))
    attempted: bool = False
    published: bool = False
    _identity: tuple[int, int] | None = None

    @property
    def identity(self) -> tuple[int, int]:
        if os.getpid() != self.operation.pid:
            raise OSError("rooted publication cannot be used after fork")
        if (not self.published or self._identity is None or len(self.operation.descriptors) != 1
                or any(self.operation.descriptors.values())):
            raise OSError("rooted publication has no retained completion witness")
        return self._identity


class RootedFileIO:
    """Borrowed Linux root with an explicit ledger for native cleanup debt.

    No destructor, root close, automatic admission, or pathname fallback. The
    owning operation scope is the authority for borrowing, not dev/ino alone.
    cleanup() is called by that existing owner only after all calls have drained.
    """

    def __init__(self, root: Path, directory_fd: int, *, directory_bindings: tuple[DirectoryBinding, ...] = ()) -> None:
        root = Path(root)
        if sys.platform != "linux":
            raise OSError("rooted IO requires Linux")
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("rooted IO requires an absolute lexical root")
        opened = os.fstat(directory_fd)
        _directory(opened)
        self.root, self._root_fd = root, directory_fd
        self._identity = (opened.st_dev, opened.st_ino)
        if type(directory_bindings) is not tuple or len(directory_bindings) > 16:
            raise ValueError("rooted directory bindings must be a bounded tuple")
        self._expected_directories: dict[tuple[int, int, str], tuple[int, int]] = {}
        for parent, name, child in directory_bindings:
            if (type(name) is not str or not name or name in {".", ".."}
                    or any(char in name for char in ("/", "\\", "\0"))
                    or any(type(identity) is not tuple or len(identity) != 2
                           or any(type(value) is not int or value < 0 for value in identity)
                           for identity in (parent, child))):
                raise ValueError("invalid rooted directory binding")
            key = (*parent, name)
            if key in self._expected_directories:
                raise ValueError("duplicate rooted directory binding")
            self._expected_directories[key] = child
        self._pid = os.getpid()
        self._operations: list[_Operation] = []
        self._publication: tuple[tuple[str, ...], _PublicationWitness] | None = None
        self._mutex = RLock()

    @property
    def cleanup_pending(self) -> bool:
        self._same_process()
        with self._mutex:
            return bool(self._operations or (self._publication is not None
                        and self._publication[1].operation.descriptors))

    def retain_next_publication(self, path: Path) -> _PublicationWitness:
        """Purely register at most one inode pin, released by this port's cleanup.

        This is not a write authority. The original caller must admit the write
        and retain this port throughout the receipt's entire useful lifetime.
        """
        self._same_process()
        parts = self._parts(path)
        with self._mutex:
            if self._publication is not None:
                raise OSError("rooted publication witness is already registered")
            witness = _PublicationWitness()
            self._publication = parts, witness
            return witness

    def cleanup(self) -> None:
        """Retry known temporary debt; never retry an uncertain descriptor close."""
        self._same_process()
        with self._mutex:
            if any(operation.active for operation in self._operations):
                raise OSError("rooted IO has active operations")
            failures = []
            for operation in tuple(self._operations):
                try:
                    operation.cleanup()
                except BaseException as exc:
                    failures.append(exc)
                else:
                    self._operations.remove(operation)
            if self._publication is not None and not failures:
                try:
                    self._publication[1].operation.cleanup()
                except BaseException as exc:
                    failures.append(exc)
            if failures:
                raise failures[0]

    def _same_process(self) -> None:
        if os.getpid() != self._pid:
            raise OSError("rooted IO cannot be used after fork")

    def _parts(self, path: Path) -> tuple[str, ...]:
        path = Path(path)
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            raise ValueError("rooted IO path is outside the borrowed root") from None
        if not parts or any(part in {"", ".", ".."} or "\0" in part or "\\" in part for part in parts):
            raise ValueError("rooted IO requires safe relative child components")
        return parts

    @contextmanager
    def _operation(
        self, path: Path, *, create_parent: bool = False, durable: bool = True,
    ) -> Iterator[tuple[_Operation, int, str]]:
        parts = self._parts(path)
        self._same_process()
        operation = _Operation(durable=durable, expected_directories=dict(self._expected_directories))
        with self._mutex:
            if (any(not item.active for item in self._operations)
                    or (self._publication is not None and any(self._publication[1].operation.descriptors.values()))):
                raise OSError("rooted IO has unsettled cleanup debt")
            self._operations.append(operation)
        primary: BaseException | None = None
        try:
            opened = os.fstat(self._root_fd)
            _directory(opened)
            if (opened.st_dev, opened.st_ino) != self._identity:
                raise OSError("rooted IO borrowed root identity changed")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
            parent = operation.opened(os.open(".", flags, dir_fd=self._root_fd))
            operation.directory_fds.add(parent)
            for part in parts[:-1]:
                status = os.fstat(parent)
                expected = operation.expected_directories.get((status.st_dev, status.st_ino, part))
                if create_parent and expected is None:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=parent)
                    except FileExistsError:
                        pass
                    else:
                        os.fsync(parent)
                parent = operation.opened(os.open(part, flags, dir_fd=parent))
                operation.directory_fds.add(parent)
                _directory(os.fstat(parent))
                if expected is not None and (os.fstat(parent).st_dev, os.fstat(parent).st_ino) != expected:
                    raise OSError("rooted enrolled directory identity changed")
            yield operation, parent, parts[-1]
        except BaseException as exc:
            primary = exc
            raise
        finally:
            operation.borrow_active = False
            if os.getpid() != operation.pid:
                # Do not touch inherited locks or the parent's temporary names.
                raise OSError("rooted IO cannot be used after fork")
            try:
                operation.cleanup()
            except BaseException:
                if primary is None:
                    raise
                primary.add_note("rooted IO cleanup debt retained")
            finally:
                with self._mutex:
                    operation.active = False
                    if (not operation.descriptors and not operation.temporaries
                            and not operation.sync_pending and not operation.iterators
                            and not operation.deletions and not operation.recoveries
                            and not operation.settlements):
                        self._operations.remove(operation)

    @staticmethod
    def _open(operation: _Operation, parent: int, name: str, flags: int) -> int:
        fd = operation.opened(os.open(
            name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=parent,
        ))
        _regular(os.fstat(fd))
        return fd

    @contextmanager
    def bind(
        self, path: Path, *, create_parent: bool = False, durable: bool = True,
    ) -> Iterator[RootedFile]:
        """Borrow one pinned parent for an entire synchronous transaction.

        The yielded reference is valid only within this context. In particular,
        Journal locks, JSONL and repair must all use this one reference.
        """
        with self._operation(path, create_parent=create_parent, durable=durable) as values:
            witness = (self._publication[1] if self._publication is not None
                       and self._parts(path) == self._publication[0] else None)
            yield RootedFile(*values, _publication=witness)

    def read_bytes(self, path: Path, *, max_bytes: int | None = None) -> bytes:
        with self.bind(path) as target:
            return target.read_bytes(max_bytes=max_bytes)

    @contextmanager
    def directory(self) -> Iterator[RootedDirectory]:
        """Borrow the root and any child directories for one transaction."""
        with self.bind(self.root / ".directory") as target:
            yield RootedDirectory(target._operation, target._parent)

    def read_prefix(self, path: Path, limit: int) -> bytes:
        with self.bind(path) as target:
            return target.read_bytes(prefix_bytes=limit)

    def stat(self, path: Path) -> os.stat_result:
        with self.bind(path) as target:
            return target.stat()

    def scan_names(self, *, limit: int) -> tuple[tuple[str, ...], bool]:
        """Bounded direct-child names from the borrowed root, without Path IO."""
        if type(limit) is not int or limit < 1:
            raise ValueError("rooted IO scan limit must be positive")
        with self.bind(self.root / ".scan") as target:
            names: list[str] = []
            entries = os.scandir(target._parent)
            target._operation.iterators.append((entries, False))
            for entry in entries:
                if len(names) == limit:
                    return tuple(names), False
                names.append(entry.name)
            return tuple(names), True

    def append_bytes(self, path: Path, data: bytes, *, fsync: bool = True) -> None:
        with self.bind(path, create_parent=True, durable=fsync) as target:
            target.append_bytes(data, fsync=fsync)

    def atomic_write(self, path: Path, data: bytes, *, fsync: bool = True) -> None:
        with self.bind(path, create_parent=True, durable=fsync) as target:
            target.atomic_write(data, fsync=fsync)

    def unlink(self, path: Path, *, missing_ok: bool = False, fsync: bool = True) -> None:
        with self.bind(path, durable=fsync) as target:
            target.unlink(missing_ok=missing_ok, fsync=fsync)

    @contextmanager
    def lock(self, path: Path, *, exclusive: bool, blocking: bool = True) -> Iterator[None]:
        with self.bind(path, create_parent=True) as target:
            target.acquire_lock(exclusive=exclusive, blocking=blocking)
            yield


@dataclass(frozen=True)
class RootedFile:
    """One transaction's borrowed parent and lexical leaf, never retained."""

    _operation: _Operation
    _parent: int
    _name: str
    _publication: _PublicationWitness | None = field(default=None, kw_only=True)

    def _require_active(self) -> None:
        if os.getpid() != self._operation.pid:
            raise OSError("rooted IO cannot be used after fork")
        if not self._operation.borrow_active:
            raise OSError("rooted IO file borrow has ended")

    def sibling(self, name: str) -> RootedFile:
        self._require_active()
        if not name or name in {".", ".."} or any(char in name for char in ("/", "\\", "\0")):
            raise ValueError("rooted IO requires one direct child name")
        return self._project(name)

    def _project(self, name: str) -> RootedFile:
        return RootedFile(self._operation, self._parent, name)

    def stat(self) -> os.stat_result:
        self._require_active()
        value = os.stat(self._name, dir_fd=self._parent, follow_symlinks=False)
        _regular(value)
        return value

    def read_bytes(self, *, max_bytes: int | None = None, prefix_bytes: int | None = None) -> bytes:
        self._require_active()
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 1):
            raise ValueError("rooted IO read limit must be positive")
        if prefix_bytes is not None and (type(prefix_bytes) is not int or prefix_bytes < 1):
            raise ValueError("rooted IO prefix limit must be positive")
        fd = RootedFileIO._open(self._operation, self._parent, self._name, os.O_RDONLY)
        before = os.fstat(fd)
        if max_bytes is not None and before.st_size > max_bytes:
            raise OSError("rooted IO read limit exceeded")
        chunks = []
        remaining = before.st_size if prefix_bytes is None else min(before.st_size, prefix_bytes)
        while remaining:
            data = os.read(fd, min(remaining, 1024 * 1024))
            if not data:
                raise OSError("rooted IO file truncated during read")
            chunks.append(data)
            remaining -= len(data)
        after = os.fstat(fd)
        named = os.stat(self._name, dir_fd=self._parent, follow_symlinks=False)
        if _version(before) != _version(after) or _version(after) != _version(named):
            raise OSError("rooted IO file changed during read")
        return b"".join(chunks)

    def append_bytes(self, data: bytes, *, fsync: bool = True) -> None:
        self._require_active()
        fd = RootedFileIO._open(self._operation, self._parent, self._name, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        os.fchmod(fd, 0o600)
        _write_all(fd, data)
        if fsync:
            os.fsync(fd)
            self.sync_directory()

    def create_new(self, data: bytes) -> tuple[int, int]:
        """Create an unpublished object exclusively; failures retain cleanup."""
        self._require_active()
        operation, parent, name = self._operation, self._parent, self._name
        fd = operation.opened(os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=parent,
        ))
        operation.temporaries[parent, name] = None
        metadata = os.fstat(fd)
        identity = metadata.st_dev, metadata.st_ino
        operation.temporaries[parent, name] = identity
        _regular(metadata)
        _write_all(fd, data)
        os.fsync(fd)
        self.sync_directory()
        del operation.temporaries[parent, name]
        return identity

    def atomic_write(self, data: bytes, *, fsync: bool = True, exclusive: bool = False) -> None:
        self._require_active()
        operation, parent, name = self._operation, self._parent, self._name
        temporary = f".{name}.{secrets.token_hex(12)}.tmp"
        # Only a successful exclusive creation acquires cleanup authority.
        fd = operation.opened(os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=parent,
        ))
        operation.temporaries[parent, temporary] = None
        opened = os.fstat(fd)
        operation.temporaries[parent, temporary] = (opened.st_dev, opened.st_ino)
        _regular(opened)
        witness = self._publication
        capturing = witness is not None and not witness.attempted
        if capturing:
            assert witness is not None
            witness.attempted = True
            # Duplicate the actual new inode before publication, never reopen
            # its pathname. This separate ledger is not this call's finally
            # ledger; the original port alone releases the bounded pin.
            witness.operation.opened(os.dup(fd))
            witness._identity = opened.st_dev, opened.st_ino
        _write_all(fd, data)
        if fsync:
            os.fsync(fd)
        current = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError("rooted IO temporary identity changed")
        if exclusive:
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            os.unlink(temporary, dir_fd=parent)
        else:
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        del operation.temporaries[parent, temporary]  # Consumed, even if fsync fails.
        if fsync:
            self.sync_directory()
        if capturing:
            assert witness is not None
            witness.published = True

    def sync_directory(self) -> None:
        self._require_active()
        self._operation.sync_pending.add(self._parent)
        os.fsync(self._parent)
        self._operation.sync_pending.remove(self._parent)

    def unlink(self, *, missing_ok: bool = False, fsync: bool = True) -> None:
        self._require_active()
        try:
            _regular(os.stat(self._name, dir_fd=self._parent, follow_symlinks=False))
            os.unlink(self._name, dir_fd=self._parent)
        except FileNotFoundError:
            if not missing_ok:
                raise
        else:
            if fsync:
                self.sync_directory()

    def unlink_owned(self, identity: tuple[int, int]) -> None:
        """Retain an authorized cleanup until its exact name and sync settle."""
        self._require_active()
        self._operation.deletions.append((self._parent, self._name, identity, False))
        self._operation.finish_deletions()

    def acquire_lock(self, *, exclusive: bool, blocking: bool = True, suffix: str = "") -> None:
        import fcntl

        self._require_active()
        if any(char in suffix for char in ("/", "\\", "\0")):
            raise ValueError("rooted IO lock suffix must be one child component")
        fd = RootedFileIO._open(self._operation, self._parent, self._name + suffix, os.O_RDWR | os.O_CREAT)
        self._operation.lock_fds.add(fd)
        os.fchmod(fd, 0o600)
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        # Retained recovery may keep this lock after the call exits. Waiting
        # here would keep another operation active and prevent owner cleanup
        # from releasing that lock. Rooted admission is always fail-fast;
        # blocking remains accepted for the generic Journal lock interface.
        fcntl.flock(fd, mode | fcntl.LOCK_NB)
        # Closing this independent OFD releases the lock, never LOCK_UN.


@dataclass(frozen=True)
class RootedDirectory:
    """A directory projection borrowing the same operation, never an owner."""

    _operation: _Operation
    _fd: int

    def file(self, name: str) -> RootedFile:
        return RootedFile(self._operation, self._fd, ".directory").sibling(name)

    def stat(self) -> os.stat_result:
        self.file(".directory")._require_active()
        result = os.fstat(self._fd)
        _directory(result)
        return result

    def child(self, name: str, *, create: bool = False) -> RootedDirectory:
        target = self.file(name)
        status = self.stat()
        expected = self._operation.expected_directories.get((status.st_dev, status.st_ino, name))
        if create and expected is None:
            try:
                os.mkdir(name, mode=0o700, dir_fd=self._fd)
            except FileExistsError:
                pass
            else:
                target.sync_directory()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        fd = self._operation.opened(os.open(name, flags, dir_fd=self._fd))
        self._operation.directory_fds.add(fd)
        result = self._project(fd)
        current = result.stat()
        if expected is not None and (current.st_dev, current.st_ino) != expected:
            raise OSError("rooted enrolled directory identity changed")
        return result

    def _project(self, fd: int) -> RootedDirectory:
        return RootedDirectory(self._operation, fd)

    def retain_cleanup(self, action: Callable[[RootedDirectory], None]) -> None:
        """Retain a domain recovery in this operation, with its original locks."""
        self.stat()
        self._operation.recoveries.append((self._fd, action))

    def track_settlement(self) -> Event:
        """Receipt for full settlement of this original operation, including close."""
        self.stat()
        receipt = Event()
        self._operation.settlements.append(receipt)
        return receipt

    def reborrow(self, retained: RootedDirectory) -> RootedDirectory:
        self.stat()
        if retained._operation is not self._operation or retained._fd not in self._operation.directory_fds:
            raise ValueError("directory reborrow requires the same retained operation")
        return self._project(retained._fd)

    @property
    def deletion_registered(self) -> bool:
        self.stat()
        return self._operation.deletion_registered

    def queue_files(self, files: list[tuple[str, tuple[int, int]]]) -> None:
        plan = []
        for name, identity in files:
            self.file(name)
            plan.append((self._fd, name, identity, False))
        self._operation.deletions.extend(plan)
        self._operation.deletion_registered |= bool(plan)

    def remove_files(self, files: list[tuple[str, tuple[int, int]]]) -> None:
        self.queue_files(files)
        self._operation.finish_deletions()

    def check_child(self, name: str, expected: RootedDirectory) -> None:
        self.file(name)
        if expected._operation is not self._operation:
            raise ValueError("directory check requires the same transaction")
        named = os.stat(name, dir_fd=self._fd, follow_symlinks=False)
        if not os.path.samestat(named, expected.stat()):
            raise OSError("rooted child directory identity changed")

    def names(self, *, limit: int) -> tuple[str, ...]:
        self.stat()
        if type(limit) is not int or limit < 1:
            raise ValueError("rooted directory scan limit must be positive")
        entries = os.scandir(self._fd)
        self._operation.iterators.append((entries, False))
        names: list[str] = []
        for entry in entries:
            if len(names) == limit:
                raise OSError("rooted directory traversal budget exceeded")
            names.append(entry.name)
        return tuple(names)

    def remove_tree(self, name: str, *, expected: RootedDirectory, limit: int, defer: bool = False) -> None:
        """Preflight a bounded owned tree, then delete only its pinned members."""
        if expected._operation is not self._operation:
            raise ValueError("directory deletion requires the same transaction")
        self.file(name)
        if type(limit) is not int or limit < 1:
            raise ValueError("rooted directory traversal limit must be positive")
        root = expected.stat()
        named = os.stat(name, dir_fd=self._fd, follow_symlinks=False)
        if not os.path.samestat(root, named):
            raise OSError("rooted directory deletion identity changed")
        remaining = limit
        files: list[tuple[RootedFile, os.stat_result]] = []
        directories: list[tuple[RootedDirectory, str, os.stat_result]] = []

        def scan(directory: RootedDirectory, depth: int) -> None:
            nonlocal remaining
            if depth > 16:
                raise OSError("rooted directory traversal depth exceeded")
            for child in directory.names(limit=max(1, remaining)):
                remaining -= 1
                if remaining < 0:
                    raise OSError("rooted directory traversal budget exceeded")
                metadata = os.stat(child, dir_fd=directory._fd, follow_symlinks=False)
                if stat.S_ISDIR(metadata.st_mode):
                    opened = directory.child(child)
                    if not os.path.samestat(metadata, opened.stat()):
                        raise OSError("rooted child directory identity changed")
                    scan(opened, depth + 1)
                    directories.append((directory, child, metadata))
                else:
                    _regular(metadata)
                    files.append((directory.file(child), metadata))

        scan(expected, 0)
        for leaf, metadata in files:
            if not os.path.samestat(metadata, leaf.stat()):
                raise OSError("rooted file deletion identity changed")
        plan = [
            (leaf._parent, leaf._name, (metadata.st_dev, metadata.st_ino), False)
            for leaf, metadata in files
        ]
        for parent, child, metadata in (*directories, (self, name, root)):
            current = os.stat(child, dir_fd=parent._fd, follow_symlinks=False)
            if not os.path.samestat(metadata, current):
                raise OSError("rooted directory deletion identity changed")
            plan.append((parent._fd, child, (metadata.st_dev, metadata.st_ino), True))
        # Keep the exact preflight plan in the original IO ledger before the
        # first unlink. A partial deletion must remain recoverable without a
        # still-readable manifest or a new pathname traversal.
        self._operation.deletions.extend(plan)
        self._operation.deletion_registered = True
        if not defer:
            self._operation.finish_deletions()


@dataclass(frozen=True)
class _CleanupFile(RootedFile):
    _token: object

    def _require_active(self) -> None:
        if (os.getpid() != self._operation.pid or self._operation.cleanup_thread != get_ident()
                or self._operation.cleanup_token is not self._token):
            raise OSError("rooted cleanup borrow has ended")

    def _project(self, name: str) -> RootedFile:
        return _CleanupFile(self._operation, self._parent, name, self._token)


@dataclass(frozen=True)
class _CleanupDirectory(RootedDirectory):
    _token: object

    def file(self, name: str) -> RootedFile:
        return _CleanupFile(self._operation, self._fd, ".directory", self._token).sibling(name)

    def _project(self, fd: int) -> RootedDirectory:
        return _CleanupDirectory(self._operation, fd, self._token)


def _directory(value: os.stat_result) -> None:
    if (not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or value.st_mode & 0o022):
        raise OSError("rooted IO requires an owned non-writable directory")


def _regular(value: os.stat_result) -> None:
    if (not stat.S_ISREG(value.st_mode) or value.st_uid != os.geteuid()
            or value.st_mode & 0o022 or value.st_nlink != 1):
        raise OSError("rooted IO requires an owned single-link regular file")


def _version(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _write_all(fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise OSError("rooted IO write made no progress")
        remaining = remaining[written:]
