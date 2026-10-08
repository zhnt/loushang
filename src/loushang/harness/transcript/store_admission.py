"""Lazy, process-independent admission of one shared transcript store on Linux.

Products select the store and state roots. Discovery uses only ``inspect``;
it cannot register or initialize storage. A writer retains this owner before native work, then transfers
the returned physical identities to its original writer preparation. Closing
does not delete histories, attachments, witnesses or stable lock files.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex
from threading import Event

from loushang.harness.journal._directory_lease import DirectoryWriterLease
from loushang.harness.journal._rooted_io import RootedFileIO

from .writer_lease import TranscriptWriterError

Identity = tuple[int, int]
_VERSION = "transcript-store-admission/v1"


@dataclass(frozen=True)
class TranscriptStoreBinding:
    root_identity: Identity
    parent_identity: Identity
    family_id: str | None = None
    member_id: str | None = None
    shared_identities: tuple[Identity, Identity, Identity] | None = None


class _WitnessLease(DirectoryWriterLease):
    _error_type = TranscriptWriterError
    _lock_directory = ".store-admission-locks"
    _hash_domain = _VERSION


class _StoreRoot(DirectoryWriterLease):
    """Only a directory handle; reuse the native creation and cleanup ledger."""

    _error_type = TranscriptWriterError

    def acquire_child(self, parent: _StoreRoot, *, create: bool = False) -> None:
        """Bind/create one child through the already retained original parent."""
        self._enter()
        try:
            if self._attempted or self._closing or self._root.parent != parent._root:
                raise self._error_type("closed")
            self._attempted = True
            parent.binding()
            self._canonical = self._root
            self._fds["parent"] = os.dup(parent._fds["root"])
            if create:
                self._sync_pending.add("parent")
                os.mkdir(self._root.name, mode=0o700, dir_fd=self._fds["parent"])
            self._fds["root"] = os.open(self._root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=self._fds["parent"])
            self._sync_root_parents()
            self.binding()
            parent.binding()
        except FileExistsError:
            raise self._error_type("conflict") from None
        except OSError:
            raise self._error_type("unavailable") from None
        finally:
            self._mutex.release()

    def acquire(self) -> None:
        self._enter()
        try:
            if self._attempted or self._closing:
                raise self._error_type("closed")
            self._attempted = True
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            if self._create_root:
                self._prepare_root(flags)
            else:
                self._canonical = self._resolve_root()
                if self._canonical != self._root:
                    raise self._error_type("conflict")
                self._fds["root"] = os.open(self._canonical, flags)
            self._fds["parent"] = os.open(self._root.parent, flags)
            self.binding()
            self._release_fds(tuple(name for name in self._fds if name.startswith("ancestor:")))
        except OSError:
            raise self._error_type("unavailable") from None
        finally:
            self._mutex.release()

    def binding(self) -> TranscriptStoreBinding:
        self._validate_directory(self._fds["root"], private=False)
        self._validate_root_parent(self._fds["parent"])
        root, parent = os.fstat(self._fds["root"]), os.fstat(self._fds["parent"])
        if (self._resolve_root() != self._root
                or not os.path.samestat(parent, os.stat(self._root.parent, follow_symlinks=False))
                or not os.path.samestat(root, os.stat(self._root.name, dir_fd=self._fds["parent"],
                                                     follow_symlinks=False))):
            raise self._error_type("conflict")
        return TranscriptStoreBinding((root.st_dev, root.st_ino), (parent.st_dev, parent.st_ino))


class TranscriptStoreAdmission:
    """One-shot, short initialization lock, independent of Sessions/Products.

    ``create_if_missing`` belongs to an actual new persistent write, never
    service startup or restore. Existing legacy stores are registered without
    modifying their contents. Missing or incomplete durable facts are not
    permission to recreate an already admitted store.
    """

    def __init__(self, root: Path, *, state_root: Path, create_if_missing: bool = False,
                 root_observed: Event | None = None,
                 enroll_legacy_shared_store: bool = False) -> None:
        root, state_root = Path(root), Path(state_root)
        if (type(create_if_missing) is not bool
                or type(enroll_legacy_shared_store) is not bool
                or (root_observed is not None and type(root_observed) is not Event)):
            raise TranscriptWriterError("invalid")
        for path in (root, state_root):
            if (not path.is_absolute() or path == path.parent or ".." in path.parts
                    or str(path).startswith("//")):
                raise TranscriptWriterError("invalid")
        # All store/attachment writers and temporary cleaners must keep out of
        # the selected state domain; callers also isolate it from runtime roots.
        if state_root.is_relative_to(root.parent) or root.parent.is_relative_to(state_root):
            raise TranscriptWriterError("invalid")
        key = hashlib.sha256(f"{_VERSION}\0{os.geteuid()}\0{root}".encode()).hexdigest()
        self.root, self.witness_root = root, state_root / key
        self._key, self._create = key, create_if_missing
        self._enroll_legacy_shared_store = enroll_legacy_shared_store
        self._root_observed = root_observed
        self._existing = _WitnessLease(self.witness_root, _VERSION, key, create_lock=False)
        self._fresh = _WitnessLease(self.witness_root, _VERSION, key,
                                    create_root=True, exclusive_root=True)
        self._root_existing = _StoreRoot(root, _VERSION, key)
        self._root_fresh = _StoreRoot(root, _VERSION, key, create_root=True, exclusive_root=True)
        self._witness: _WitnessLease | None = None
        self._store: _StoreRoot | None = None
        self._io: RootedFileIO | None = None
        self._binding: TranscriptStoreBinding | None = None
        self._attempted = self._closed = False
        from ._store_family import _SharedFamily

        self._family = _SharedFamily(self, state_root)

    @property
    def cleanup_pending(self) -> bool:
        return (any(owner.cleanup_pending for owner in self._owners)
                or (self._io is not None and self._io.cleanup_pending) or self._family.cleanup_pending)

    @property
    def _owners(self) -> tuple[DirectoryWriterLease, ...]:
        return self._root_existing, self._root_fresh, self._existing, self._fresh

    def open(self) -> TranscriptStoreBinding:
        self._existing._enter()
        try:
            binding = self._open()
            assert binding is not None
            return binding
        finally:
            self._existing._mutex.release()

    def inspect(self) -> TranscriptStoreBinding | None:
        """Open only known durable facts; unknown stores remain unregistered.

        The caller retains this owner before entering native IO, closes it
        after the short observation, and keeps any failed cleanup for retry.
        ``None`` is an unknown store, not permission to initialize one.
        """
        self._existing._enter()
        try:
            return self._open(inspect_only=True)
        finally:
            self._existing._mutex.release()

    def _open(self, *, inspect_only: bool = False) -> TranscriptStoreBinding | None:
        if self._attempted or self._closed:
            raise TranscriptWriterError("closed")
        self._attempted = True
        try:
            existing = not _missing(self.witness_root)
            root_missing = _missing(self.root)
            if self._family.present or (not existing and root_missing and not inspect_only and self._may_create()):
                if not self._family.present:
                    self._reject_residue()
                binding = self._family.open(inspect_only=inspect_only)
                self._binding = binding
                return binding
            if existing:
                # Negative precheck only: do not steal a creator's new lock
                # before its first flock. Positive data is re-read under lock.
                if _missing(self.witness_root / "admission.json"):
                    raise TranscriptWriterError("incomplete")
                self._witness = self._existing
            else:
                if inspect_only:
                    if root_missing:
                        if self._root_observed is not None and self._root_observed.is_set():
                            raise TranscriptWriterError("unavailable")
                        self._reject_residue()
                    return None
                if root_missing:
                    if not self._may_create():
                        raise TranscriptWriterError("unavailable")
                    self._reject_residue()
                else:
                    # An unrecorded root beside shared writer/artifact residue
                    # is not evidence for silently adopting a lost family as v1.
                    self._reject_residue()
                    if not _missing(self.root / ".transcript-writers"):
                        raise TranscriptWriterError("conflict")
                    if not self._enroll_legacy_shared_store:
                        self._family.inspect_state_evidence(allow_legacy=True)
                self._witness = self._fresh
            self._witness.acquire()
            if self._witness._canonical != self.witness_root:
                raise TranscriptWriterError("conflict")
            self._io = RootedFileIO(self.witness_root, self._witness._fds["root"])
            if existing:
                record = self._read()
                if record["phase"] != "initialized":
                    raise TranscriptWriterError("incomplete")
                self._open_store(create=False)
                assert self._store is not None
                binding = self._store.binding()
                if (record["root"] != list(binding.root_identity)
                        or record["parent"] != list(binding.parent_identity)):
                    raise TranscriptWriterError("conflict")
            else:
                if not root_missing:
                    # Pin legacy identity before publishing intent. A root or
                    # data-parent replacement is not a new legacy adoption.
                    self._open_store(create=False)
                # Durable lock and intent precede every Session-root creation.
                self._witness._sync_pending.update(("root", "directory", "lock"))
                self._witness._sync_root_parents()
                record = self._record()
                self._write(record)
                # Freeze the initial observation: a legacy root disappearing
                # while intent is published never becomes a creation grant.
                create = root_missing
                if create:
                    if not self._may_create():
                        raise TranscriptWriterError("unavailable")
                    self._reject_residue()
                if create:
                    self._open_store(create=True)
                assert self._store is not None
                binding = self._store.binding()
                record.update(phase="initialized", root=list(binding.root_identity),
                              parent=list(binding.parent_identity))
                self._write(record)
                if self._read() != record:
                    raise TranscriptWriterError("conflict")
            self._binding = binding
            return binding
        except (OSError, ValueError, RecursionError):
            raise TranscriptWriterError("unavailable") from None

    def _reject_residue(self) -> None:
        assets = self.root.parent / "session-assets"
        writers = self.root.parent / ".session-blob-writers"
        if not self._enroll_legacy_shared_store:
            if any(os.path.lexists(path) for path in (assets, writers)):
                raise TranscriptWriterError("conflict")
            return
        # This explicit compatibility grant is only for the pre-family layout.
        # A blob-writer root is evidence that family-era initialization ran.
        if os.path.lexists(writers):
            raise TranscriptWriterError("conflict")
        for path in (assets, assets / ".locks"):
            if not os.path.lexists(path):
                continue
            fd = os.open(
                path,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                info = os.fstat(fd)
                current = os.stat(path, follow_symlinks=False)
                if (not os.path.samestat(info, current)
                        or not stat.S_ISDIR(info.st_mode)
                        or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) != 0o700):
                    raise TranscriptWriterError("conflict")
            finally:
                os.close(fd)

    def check(self) -> None:
        """Revalidate the original known observation, granting no write rights."""
        self._existing._enter()
        try:
            if self._closed or self._binding is None or self._store is None:
                raise TranscriptWriterError("closed")
            if self._binding.family_id is not None:
                self._family.check()
                return
            record = self._read()
            if (record["phase"] != "initialized" or self._store.binding() != self._binding
                    or record["root"] != list(self._binding.root_identity)
                    or record["parent"] != list(self._binding.parent_identity)):
                raise TranscriptWriterError("conflict")
        except (OSError, ValueError, RecursionError):
            raise TranscriptWriterError("unavailable") from None
        finally:
            self._existing._mutex.release()

    def _may_create(self) -> bool:
        return self._create and not (self._root_observed is not None and self._root_observed.is_set())

    def _open_store(self, *, create: bool) -> None:
        self._store = self._root_fresh if create else self._root_existing
        if self._family._data is not None:
            self._store.acquire_child(self._family._data, create=create)
        else:
            self._store.acquire()

    def _record(self) -> dict[str, object]:
        assert self._witness is not None
        return dict(version=_VERSION, store=self._key, operation=token_hex(16), phase="initializing",
                    witness=list(_identity(self._witness._fds["root"])),
                    lock=list(_identity(self._witness._fds["lock"])), root=None, parent=None)

    def _write(self, record: dict[str, object]) -> None:
        assert self._io is not None and self._witness is not None
        self._witness.check_binding(owner_id=_VERSION, authority_id=self._key)
        self._io.atomic_write(self.witness_root / "admission.json", json.dumps(record).encode())
        self._witness.check_binding(owner_id=_VERSION, authority_id=self._key)

    def _read(self) -> dict[str, object]:
        assert self._io is not None and self._witness is not None
        self._witness.check_binding(owner_id=_VERSION, authority_id=self._key)
        record = json.loads(self._io.read_bytes(self.witness_root / "admission.json", max_bytes=4096),
                            object_pairs_hook=_unique)
        if type(record) is dict and record.get("version") == "transcript-store-admission/v2":
            return self._family.validate_member(record)
        if (type(record) is not dict
                or set(record) != {"version", "store", "operation", "phase", "witness", "lock", "root", "parent"}
                or record["version"] != _VERSION or record["store"] != self._key
                or type(record["operation"]) is not str or len(record["operation"]) != 32
                or any(c not in "0123456789abcdef" for c in record["operation"])
                or record["phase"] not in ("initializing", "initialized")
                or record["witness"] != list(_identity(self._witness._fds["root"]))
                or record["lock"] != list(_identity(self._witness._fds["lock"]))):
            raise TranscriptWriterError("conflict")
        for name in ("witness", "lock", "root", "parent"):
            value = record[name]
            if record["phase"] == "initializing" and name in ("root", "parent"):
                if value is not None:
                    raise TranscriptWriterError("conflict")
            elif (type(value) is not list or len(value) != 2
                  or any(type(item) is not int or not 0 <= item < 2**64 for item in value) or value[1] == 0):
                raise TranscriptWriterError("conflict")
        return record

    def close(self) -> None:
        self._existing._enter()
        try:
            self._close()
        finally:
            self._existing._mutex.release()

    def release_locks(self) -> None:
        """Release short admission locks but keep root pins with this owner."""
        if self._io is not None:
            self._io.cleanup()
        for owner in (self._existing, self._fresh):
            owner.close()
        self._family.release_locks()

    def _close(self) -> None:
        self._closed = True
        failures: list[Exception] = []
        if self._io is not None:
            try:
                self._io.cleanup()
            except Exception as error:
                failures.append(error)
        try:
            self._family.close()
        except Exception as error:
            failures.append(error)
        for owner in self._owners:
            if owner in (self._existing, self._fresh) and self._io is not None and self._io.cleanup_pending:
                continue  # Rooted IO must settle before releasing its borrowed fd.
            try:
                owner.close()
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]


def _identity(fd: int) -> Identity:
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _missing(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    return False  # Permission/IO failures never become evidence of absence.


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    record: dict[str, object] = {}
    for key, value in pairs:
        if key in record:
            raise ValueError("duplicate field")
        record[key] = value
    return record
