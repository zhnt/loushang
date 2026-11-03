"""Private Linux retained directory writer mechanism shared by storage owners."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from contextlib import suppress
from pathlib import Path
from threading import RLock, current_thread, main_thread
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._rooted_io import RootedFileIO


class DirectoryWriterError(RuntimeError):
    """Bounded failure without logical identities or paths in its message."""

    prefix = "directory_writer"

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"{self.prefix}:{code}")


class DirectoryWriterLease:
    """Retained one-shot writer admission; no destructor or automatic release.

    The owner identity validates borrowing, but does not partition the physical
    lock. Subsystems select a fixed directory/hash domain and error projection.
    Root creation is explicit and opt-in; no destructor or task ownership.
    """

    _error_type = DirectoryWriterError
    _lock_directory = ".directory-writers"
    _hash_domain = "directory-writer/v1"

    def __init__(self, root: Path, owner_id: str, authority_id: str, *, create_root: bool = False,
                 expected_root_identity: tuple[int, int] | None = None,
                 expected_parent_identity: tuple[int, int] | None = None,
                 exclusive_root: bool = False, create_lock: bool = True) -> None:
        root = Path(root)
        if not root.is_absolute() or len(str(root)) > 4096 or "\0" in str(root):
            raise self._error_type("invalid")
        if type(create_root) is not bool:
            raise self._error_type("invalid")
        if (type(exclusive_root) is not bool or type(create_lock) is not bool
                or (exclusive_root and not create_root)):
            raise self._error_type("invalid")
        for identity in (expected_root_identity, expected_parent_identity):
            if identity is not None and (
                type(identity) is not tuple or len(identity) != 2
                or any(type(item) is not int or not 0 <= item < 2**64 for item in identity)
                or identity[1] == 0
            ):
                raise self._error_type("invalid")
        if ((expected_parent_identity is not None and expected_root_identity is None)
                or (create_root and expected_root_identity is not None)):
            raise self._error_type("invalid")
        if create_root:
            try:
                if (root == root.parent or ".." in root.parts or str(root).startswith("//")
                        or len(root.parts) > 64 or len(str(root).encode("utf-8")) > 4096):
                    raise self._error_type("invalid")
            except UnicodeError:
                raise self._error_type("invalid") from None
        for value in (owner_id, authority_id):
            if type(value) is not str or not value.strip() or len(value) > 65536:
                raise self._error_type("invalid")
            try:
                if len(value.encode("utf-8")) > 65536:
                    raise self._error_type("invalid")
            except UnicodeError:
                raise self._error_type("invalid") from None
        self._root, self._owner_id, self._authority_id = root, owner_id, authority_id
        payload = json.dumps([self._hash_domain, authority_id], ensure_ascii=True).encode()
        self._name = hashlib.sha256(payload).hexdigest() + ".lock"
        self._canonical: Path | None = None
        self._fds: dict[str, int] = {}
        self._unknown: set[str] = set()
        self._create_root = create_root
        self._exclusive_root = exclusive_root
        self._create_lock = create_lock
        self._expected_root_identity = expected_root_identity
        self._expected_parent_identity = expected_parent_identity
        self._expected_directory_identity: tuple[int, int] | None = None
        self._sync_pending: set[str] = set()
        self._root_edges: list[tuple[str, str, str, tuple[int, int]]] = []
        self._mutex = RLock()
        self._pid = os.getpid()
        self._inherited_disposal_pid: int | None = None
        self._claim_owner: object | None = None
        self._attempted = self._held = self._closing = False

    @property
    def cleanup_pending(self) -> bool:
        return bool(self._fds or self._unknown or self._sync_pending)

    @property
    def claimed_owner(self) -> object | None:
        """Recover the exact owner after a claimed preparation's lost delivery."""
        return self._claim_owner

    def _claim_binding(self, owner: object, *, root: Path, owner_id: str, authority_id: str) -> None:
        self._enter()
        try:
            if self._closing or not self._held or self._claim_owner is not None:
                raise self._error_type("closed")
            if (self._canonical != root or self._owner_id != owner_id
                    or self._authority_id != authority_id):
                raise self._error_type("conflict")
            self._claim_owner = owner  # Final commit; recovery reference retained.
        finally:
            self._mutex.release()

    def _borrow_root_io(self, *, root: Path, owner_id: str, authority_id: str,
                        directory_bindings: tuple[tuple[tuple[int, int], str, tuple[int, int]], ...] = ()) -> RootedFileIO:
        """Construct a no-open projection before the preparation's final claim."""
        from loushang.harness.journal._rooted_io import RootedFileIO

        self._enter()
        try:
            if self._closing or not self._held or self._claim_owner is not None:
                raise self._error_type("closed")
            if (self._canonical != root or self._owner_id != owner_id
                    or self._authority_id != authority_id):
                raise self._error_type("conflict")
            return RootedFileIO(root, self._fds["root"], directory_bindings=directory_bindings)
        finally:
            self._mutex.release()

    def _close_claimed(self, owner: object) -> None:
        self._enter()
        try:
            if self._claim_owner is not owner:
                raise self._error_type("conflict")
            self._close_fds()
        finally:
            self._mutex.release()

    def acquire(self) -> None:
        """Attempt once without queuing; caller closes even failed admissions."""
        self._enter()
        try:
            if self._attempted or self._closing:
                raise self._error_type("closed")
            self._attempted = True
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
            if self._create_root:
                self._prepare_root(flags)
            else:
                self._canonical = self._resolve_root()
                if self._expected_root_identity is not None and self._canonical != self._root:
                    raise self._error_type("conflict")
                if self._expected_parent_identity is not None:
                    self._fds["parent"] = os.open(self._canonical.parent, flags)
                    self._check_expected_parent()
                    self._fds["root"] = os.open(self._canonical.name, flags, dir_fd=self._fds["parent"])
                else:
                    self._fds["root"] = os.open(self._canonical, flags)
            self._check_expected_root()
            self._validate_directory(self._fds["root"], private=False)
            if self._create_lock and self._expected_directory_identity is None:
                with suppress(FileExistsError):
                    os.mkdir(self._lock_directory, mode=0o700, dir_fd=self._fds["root"])
            self._fds["directory"] = os.open(self._lock_directory, flags, dir_fd=self._fds["root"])
            if self._expected_directory_identity is not None:
                status = os.fstat(self._fds["directory"])
                if (status.st_dev, status.st_ino) != self._expected_directory_identity:
                    raise self._error_type("conflict")
            self._validate_directory(self._fds["directory"], private=True)
            self._fds["lock"] = os.open(
                self._name, os.O_RDWR | (os.O_CREAT if self._create_lock else 0)
                | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600, dir_fd=self._fds["directory"],
            )
            self._validate_binding()
            import fcntl

            try:
                fcntl.flock(self._fds["lock"], fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise self._error_type("busy") from None
            self._validate_binding()
            self._held = True
        except OSError:
            raise self._error_type("unavailable") from None
        finally:
            self._mutex.release()

    def check_binding(self, *, owner_id: str, authority_id: str) -> None:
        """Revalidate a held owner's binding; this never acquires another lock."""
        self._enter()
        try:
            if self._closing or not self._held or self._unknown:
                raise self._error_type("closed")
            if (type(owner_id) is not str or type(authority_id) is not str
                    or owner_id != self._owner_id or authority_id != self._authority_id):
                raise self._error_type("conflict")
            self._validate_binding()
        except OSError:
            raise self._error_type("unavailable") from None
        finally:
            self._mutex.release()

    def close(self) -> None:
        """Permanently fence this owner, then close each retained fd once."""
        self._enter()
        try:
            if self._claim_owner is not None:
                raise self._error_type("busy")
            self._close_fds()
        finally:
            self._mutex.release()

    def close_inherited(self) -> None:
        """Fork-child main-thread disposal, never LOCK_UN on a shared OFD.

        Normal methods refuse the fork child. Do not enter an inherited mutex:
        another parent thread may have held it at fork and no longer exists here.
        Only this child's main thread may dispose its inherited copies.
        """
        pid = os.getpid()
        if pid == self._pid or current_thread() is not main_thread():
            raise self._error_type("unsupported")
        if self._inherited_disposal_pid != pid:
            if not self._held or self._closing:
                # Fork may have captured an open before publication, or a close
                # after fd reuse but before removal. No inherited-number retry.
                self._unknown.add("fork_snapshot")
                self._closing = True
                raise self._error_type("unavailable")
            self._inherited_disposal_pid = pid
        self._close_fds()

    def _enter(self) -> None:
        if sys.platform != "linux" or os.getpid() != self._pid:
            raise self._error_type("unsupported")
        if not self._mutex.acquire(blocking=False):
            raise self._error_type("busy")

    def _close_fds(self) -> None:
        self._closing = True
        self._sync_root_parents()
        self._release_fds(tuple(dict.fromkeys(("lock", "directory", "root", *self._fds))))

    def _release_fds(self, keys: tuple[str, ...]) -> None:
        for key in keys:
            if key not in self._fds or key in self._unknown:
                continue
            self._unknown.add(key)
            try:
                os.close(self._fds[key])
            except BaseException:
                pass  # fd may already be closed/reused; never retry.
            else:
                del self._fds[key]
                self._unknown.remove(key)
        if self._unknown:
            raise self._error_type("unavailable")

    def _sync_root_parents(self) -> None:
        for key in tuple(self._sync_pending):
            try:
                os.fsync(self._fds[key])
            except OSError:
                raise self._error_type("unavailable") from None
            self._sync_pending.remove(key)

    def _prepare_root(self, flags: int) -> None:
        """Bind each edge before sync; retain failures in the original ledger."""
        self._canonical = self._root
        self._fds["ancestor:0"] = os.open("/", flags)
        parent = "ancestor:0"
        parts = self._root.parts[1:]
        for index, part in enumerate(parts):
            self._check_root_edges()
            self._validate_root_parent(self._fds[parent])
            self._sync_pending.add(parent)  # mkdir may succeed without a receipt.
            try:
                os.mkdir(part, mode=0o700, dir_fd=self._fds[parent])
            except FileExistsError:
                if self._exclusive_root and index == len(parts) - 1:
                    raise self._error_type("conflict") from None
            key = "root" if index == len(parts) - 1 else f"ancestor:{index + 1}"
            self._fds[key] = os.open(part, flags, dir_fd=self._fds[parent])
            if key == "root":
                self._validate_directory(self._fds[key], private=False)
            else:
                self._validate_root_parent(self._fds[key])
            info = os.fstat(self._fds[key])
            self._root_edges.append((parent, part, key, (info.st_dev, info.st_ino)))
            self._check_root_edges()
            self._sync_root_parents()
            self._check_root_edges()
            parent = key
        # Root is never reopened by pathname. Settle temporary ancestors before
        # lock acquisition; successful admission retains only the original 3 fds.
        self._release_fds(tuple(key for key in self._fds if key != "root"))
        self._root_edges.clear()
        if self._resolve_root() != self._canonical or not os.path.samestat(
            os.stat(self._canonical, follow_symlinks=False), os.fstat(self._fds["root"]),
        ):
            raise self._error_type("conflict")

    def _check_root_edges(self) -> None:
        for parent, name, key, identity in self._root_edges:
            self._validate_root_parent(self._fds[parent])
            current = os.stat(name, dir_fd=self._fds[parent], follow_symlinks=False)
            opened = os.fstat(self._fds[key])
            if (not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != identity
                    or not os.path.samestat(current, opened)):
                raise self._error_type("conflict")
            if key == "root":
                self._validate_directory(self._fds[key], private=False)
            else:
                self._validate_root_parent(self._fds[key])

    def _validate_root_parent(self, fd: int) -> None:
        info = os.fstat(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
            raise self._error_type("unsafe")

    @classmethod
    def _validate_directory(cls, fd: int, *, private: bool) -> None:
        opened = os.fstat(fd)
        mode = stat.S_IMODE(opened.st_mode)
        if (not stat.S_ISDIR(opened.st_mode) or opened.st_uid != os.geteuid()
                or (mode != 0o700 if private else bool(mode & 0o022))):
            raise cls._error_type("unsafe")

    def _validate_binding(self) -> None:
        assert self._canonical is not None
        if self._resolve_root() != self._canonical:
            raise self._error_type("conflict")
        self._check_expected_parent()
        self._check_expected_root()
        self._validate_directory(self._fds["root"], private=False)
        self._validate_directory(self._fds["directory"], private=True)
        paths = (
            ("root", os.stat(self._canonical, follow_symlinks=False)),
            ("directory", os.stat(self._lock_directory, dir_fd=self._fds["root"], follow_symlinks=False)),
            ("lock", os.stat(self._name, dir_fd=self._fds["directory"], follow_symlinks=False)),
        )
        for key, path_stat in paths:
            if not os.path.samestat(path_stat, os.fstat(self._fds[key])):
                raise self._error_type("conflict")
        opened = os.fstat(self._fds["lock"])
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) != 0o600 or opened.st_nlink != 1):
            raise self._error_type("unsafe")

    def _check_expected_root(self) -> None:
        if self._expected_root_identity is None:
            return
        opened = os.fstat(self._fds["root"])
        if (opened.st_dev, opened.st_ino) != self._expected_root_identity:
            raise self._error_type("conflict")
        self._check_expected_parent()

    def _check_expected_parent(self) -> None:
        if self._expected_parent_identity is None:
            return
        assert self._canonical is not None
        self._validate_root_parent(self._fds["parent"])
        opened = os.fstat(self._fds["parent"])
        named = os.stat(self._canonical.parent, follow_symlinks=False)
        if ((opened.st_dev, opened.st_ino) != self._expected_parent_identity
                or not os.path.samestat(opened, named)):
            raise self._error_type("conflict")

    def _resolve_root(self) -> Path:
        try:
            return self._root.resolve(strict=True)
        except (OSError, RuntimeError):
            raise self._error_type("unavailable") from None
