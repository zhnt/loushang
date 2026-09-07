"""Exact-root private JSON continuity store for G13."""

from __future__ import annotations

import os
import stat
import sys
from hashlib import sha256
from importlib import import_module
from pathlib import Path

from .continuity import (
    MAX_APPLICATION_RECORDS,
    MAX_CONTINUITY_RECORD_BYTES,
    ApplicationContinuityError,
    ApplicationContinuityErrorCodeV1,
    ApplicationContinuityRecordV1,
    ApplicationContinuitySummaryV1,
    continuity_summary,
    decode_application_continuity_record,
    encode_application_continuity_record,
    require_application_id,
    require_exact_continuity_root,
    require_owner_epoch,
)

_WINDOWS_LOCK_OFFSET = 1 << 30


class JsonFileApplicationContinuityStoreV1:
    """One private local record directory with per-application OS locks."""

    __slots__ = ("_active", "_root")

    def __init__(self, root: Path) -> None:
        self._root = require_exact_continuity_root(root)
        self._active: set[str] = set()

    @property
    def root(self) -> Path:
        return self._root

    async def acquire(
        self,
        *,
        application_id: str,
        owner_epoch: str,
    ) -> _JsonFileApplicationContinuityLeaseV1:
        application_id = require_application_id(application_id)
        owner_epoch = require_owner_epoch(owner_epoch)
        self._prepare_root()
        if application_id in self._active:
            raise _error(ApplicationContinuityErrorCodeV1.LOCKED)
        lock_path = self._path(application_id, ".lock")
        _reject_symlink(lock_path)
        descriptor = _open_private(lock_path, create=True)
        try:
            _lock_descriptor(descriptor)
        except BaseException:
            os.close(descriptor)
            raise _error(ApplicationContinuityErrorCodeV1.LOCKED) from None
        self._active.add(application_id)
        return _JsonFileApplicationContinuityLeaseV1(
            store=self,
            application_id=application_id,
            owner_epoch=owner_epoch,
            descriptor=descriptor,
        )

    async def list_applications(
        self,
        *,
        limit: int = MAX_APPLICATION_RECORDS,
    ) -> tuple[ApplicationContinuitySummaryV1, ...]:
        if type(limit) is not int or not 1 <= limit <= MAX_APPLICATION_RECORDS:
            raise ValueError("invalid continuity listing limit")
        self._prepare_root()
        try:
            paths = sorted(self._root.glob("*.json"))
        except OSError:
            raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE) from None
        if len(paths) > limit:
            raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE)
        records = tuple(self._read_path(path) for path in paths)
        if len({item.application_id for item in records}) != len(records):
            raise _error(ApplicationContinuityErrorCodeV1.CORRUPT)
        return tuple(continuity_summary(item) for item in records)

    def _prepare_root(self) -> None:
        try:
            if self._root.exists() or self._root.is_symlink():
                info = self._root.lstat()
                if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE)
            else:
                self._root.mkdir(mode=0o700, parents=False)
            if os.name != "nt" and self._root.stat().st_mode & 0o077:
                raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE)
        except ApplicationContinuityError:
            raise
        except OSError:
            raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE) from None

    def _read(self, application_id: str) -> ApplicationContinuityRecordV1 | None:
        path = self._path(application_id, ".json")
        try:
            if not path.exists() and not path.is_symlink():
                return None
        except OSError:
            raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE) from None
        record = self._read_path(path)
        if record.application_id != application_id:
            raise _error(ApplicationContinuityErrorCodeV1.CORRUPT)
        return record

    def _read_path(self, path: Path) -> ApplicationContinuityRecordV1:
        descriptor: int | None = None
        try:
            _reject_symlink(path)
            descriptor = _open_private(path, create=False)
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_size > MAX_CONTINUITY_RECORD_BYTES
                or (os.name != "nt" and info.st_mode & 0o077)
            ):
                raise _error(ApplicationContinuityErrorCodeV1.CORRUPT)
            chunks: list[bytes] = []
            remaining = MAX_CONTINUITY_RECORD_BYTES + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(65_536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > MAX_CONTINUITY_RECORD_BYTES:
                raise _error(ApplicationContinuityErrorCodeV1.CORRUPT)
            return decode_application_continuity_record(payload)
        except ApplicationContinuityError:
            raise
        except OSError:
            raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _write(self, record: ApplicationContinuityRecordV1, owner_epoch: str) -> None:
        path = self._path(record.application_id, ".json")
        owner_digest = sha256(owner_epoch.encode("utf-8")).hexdigest()
        temporary = self._path(record.application_id, f".{owner_digest}.tmp")
        descriptor: int | None = None
        try:
            if path.is_symlink() or temporary.is_symlink():
                raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE)
            payload = encode_application_continuity_record(record)
            descriptor = _open_private(temporary, create=True, exclusive=True)
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short continuity write")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            os.replace(temporary, path)
            _fsync_directory(self._root)
        except ApplicationContinuityError:
            raise
        except OSError:
            raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                if temporary.exists() or temporary.is_symlink():
                    temporary.unlink()
            except OSError:
                pass

    def _delete(self, application_id: str) -> None:
        path = self._path(application_id, ".json")
        try:
            if path.is_symlink():
                raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE)
            path.unlink()
            _fsync_directory(self._root)
        except ApplicationContinuityError:
            raise
        except OSError:
            raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE) from None

    def _release(self, application_id: str, descriptor: int) -> None:
        try:
            _unlock_descriptor(descriptor)
        finally:
            try:
                os.close(descriptor)
            finally:
                self._active.discard(application_id)

    def _path(self, application_id: str, suffix: str) -> Path:
        return self._root / f"{application_id}{suffix}"


class _JsonFileApplicationContinuityLeaseV1:
    __slots__ = (
        "_application_id",
        "_closed",
        "_descriptor",
        "_owner_epoch",
        "_store",
    )

    def __init__(
        self,
        *,
        store: JsonFileApplicationContinuityStoreV1,
        application_id: str,
        owner_epoch: str,
        descriptor: int,
    ) -> None:
        self._store = store
        self._application_id = application_id
        self._owner_epoch = owner_epoch
        self._descriptor = descriptor
        self._closed = False

    @property
    def application_id(self) -> str:
        return self._application_id

    @property
    def owner_epoch(self) -> str:
        return self._owner_epoch

    async def load(self) -> ApplicationContinuityRecordV1 | None:
        self._require_open()
        return self._store._read(self._application_id)

    async def commit(
        self,
        *,
        expected_revision: int | None,
        record: ApplicationContinuityRecordV1,
    ) -> None:
        self._require_open()
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise ValueError("invalid expected continuity revision")
        if (
            type(record) is not ApplicationContinuityRecordV1
            or record.application_id != self._application_id
        ):
            raise ValueError("continuity lease record mismatch")
        current = self._store._read(self._application_id)
        current_revision = None if current is None else current.record_revision
        if current_revision != expected_revision:
            raise _error(ApplicationContinuityErrorCodeV1.CONFLICT)
        next_revision = 1 if expected_revision is None else expected_revision + 1
        if record.record_revision != next_revision:
            raise ValueError("continuity record revision is not the next revision")
        self._store._write(record, self._owner_epoch)

    async def delete(self, *, expected_revision: int) -> None:
        self._require_open()
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("invalid expected continuity revision")
        current = self._store._read(self._application_id)
        if current is None or current.record_revision != expected_revision:
            raise _error(ApplicationContinuityErrorCodeV1.CONFLICT)
        self._store._delete(self._application_id)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._store._release(self._application_id, self._descriptor)

    def _require_open(self) -> None:
        if self._closed:
            raise _error(ApplicationContinuityErrorCodeV1.CLOSED)


def _open_private(path: Path, *, create: bool, exclusive: bool = False) -> int:
    flags = os.O_RDWR
    if create:
        flags |= os.O_CREAT
    if exclusive:
        flags |= os.O_EXCL
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    flags |= no_follow
    descriptor = os.open(path, flags, 0o600)
    if os.name != "nt":
        try:
            fchmod = getattr(os, "fchmod", None)
            if not callable(fchmod):
                raise OSError("continuity storage requires fchmod")
            fchmod(descriptor, 0o600)
        except BaseException:
            os.close(descriptor)
            raise
    return descriptor


def _reject_symlink(path: Path) -> None:
    try:
        if path.is_symlink():
            raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE)
    except ApplicationContinuityError:
        raise
    except OSError:
        raise _error(ApplicationContinuityErrorCodeV1.UNAVAILABLE) from None


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        msvcrt = import_module("msvcrt")
        # Windows byte-range locks are mandatory.  Keep the lock outside file
        # content so another contender can open the lock file and fail the
        # non-blocking lock attempt instead of blocking on byte-zero access.
        os.lseek(descriptor, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        locking = getattr(msvcrt, "locking")
        locking(descriptor, getattr(msvcrt, "LK_NBLCK"), 1)
        return
    fcntl = import_module("fcntl")
    flock = getattr(fcntl, "flock")
    flock(
        descriptor,
        getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB"),
    )


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        msvcrt = import_module("msvcrt")
        os.lseek(descriptor, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        locking = getattr(msvcrt, "locking")
        locking(descriptor, getattr(msvcrt, "LK_UNLCK"), 1)
        return
    fcntl = import_module("fcntl")
    flock = getattr(fcntl, "flock")
    flock(descriptor, getattr(fcntl, "LOCK_UN"))


def _fsync_directory(path: Path) -> None:
    if sys.platform == "win32":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _error(code: ApplicationContinuityErrorCodeV1) -> ApplicationContinuityError:
    return ApplicationContinuityError(code)


__all__ = ["JsonFileApplicationContinuityStoreV1"]
