"""Bounded record IO and retained file-lease ownership over native file ports."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex
from typing import Literal

from ._local_record_values import (
    MAX_LOCAL_RECORD_BYTES,
    LocalRecordError,
    LocalRecordErrorCodeV1,
)

FileIdentity = tuple[int, int]
FileMode = Literal["read", "lock", "new", "delete"]


@dataclass(frozen=True, slots=True)
class _Snapshot:
    payload: bytes = field(repr=False)
    identity: FileIdentity


@dataclass(slots=True)
class _CreatedFile:
    name: str
    descriptor: int | None = None
    identity: FileIdentity | None = None


class _RecordFiles(ABC):
    def __init__(self, root: Path) -> None:
        self.root = root
        self._descriptors: set[int] = set()
        self._uncertain_close = False

    @abstractmethod
    def prepare(self, *, create: bool) -> None: ...

    @abstractmethod
    def check_root(self) -> None: ...

    @abstractmethod
    def _open(self, name: str, mode: FileMode) -> int: ...

    @abstractmethod
    def identity(self, descriptor: int) -> FileIdentity: ...

    @abstractmethod
    def replace(self, source: str, target: str) -> None: ...

    @abstractmethod
    def remove(self, name: str, expected: FileIdentity) -> None: ...

    @abstractmethod
    def lock(self, descriptor: int) -> None: ...

    @abstractmethod
    def unlock(self, descriptor: int) -> None: ...

    @abstractmethod
    def _close_root(self) -> None: ...

    def open(self, name: str, mode: FileMode, *, created: _CreatedFile | None = None) -> int:
        self.check_root()
        descriptor = self._open(name, mode)
        self._descriptors.add(descriptor)
        if created is not None:
            created.descriptor = descriptor
        try:
            os.set_inheritable(descriptor, False)
            identity = self.identity(descriptor)
            if created is not None:
                created.identity = identity
            return descriptor
        except BaseException:
            if created is None:
                self.close_descriptor(descriptor)
            raise

    def discard_unopened(self, name: str) -> None:
        # A failed create with no acquired descriptor grants no deletion right.
        if self.named_identity(name) is not None:
            raise LocalRecordError(LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE)

    def close_descriptor(self, descriptor: int) -> None:
        if descriptor not in self._descriptors:
            return
        self._descriptors.remove(descriptor)
        try:
            os.close(descriptor)
        except OSError:
            # Never retry close on a possibly recycled integer descriptor.
            self._uncertain_close = True
            raise LocalRecordError(LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE) from None

    def named_identity(self, name: str) -> FileIdentity | None:
        try:
            descriptor = self.open(name, "read")
        except FileNotFoundError:
            return None
        try:
            return self.identity(descriptor)
        finally:
            self.close_descriptor(descriptor)

    def read(self, name: str) -> _Snapshot | None:
        try:
            descriptor = self.open(name, "read")
        except FileNotFoundError:
            return None
        try:
            identity = self.identity(descriptor)
            before = os.fstat(descriptor)
            if before.st_size > MAX_LOCAL_RECORD_BYTES:
                raise LocalRecordError(LocalRecordErrorCodeV1.CORRUPT)
            payload = bytearray()
            while len(payload) <= MAX_LOCAL_RECORD_BYTES:
                chunk = os.read(descriptor, MAX_LOCAL_RECORD_BYTES + 1 - len(payload))
                if not chunk:
                    break
                payload.extend(chunk)
            after = os.fstat(descriptor)
            if (
                len(payload) > MAX_LOCAL_RECORD_BYTES
                or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                or self.named_identity(name) != identity
                or self.identity(descriptor) != identity
            ):
                raise LocalRecordError(LocalRecordErrorCodeV1.CONFLICT)
            return _Snapshot(bytes(payload), identity)
        finally:
            self.close_descriptor(descriptor)

    def close(self) -> None:
        failed = False
        for descriptor in tuple(self._descriptors):
            try:
                self.close_descriptor(descriptor)
            except (OSError, LocalRecordError):
                failed = True
        try:
            self._close_root()
        except (OSError, LocalRecordError):
            failed = True
        if failed or self._uncertain_close:
            raise LocalRecordError(LocalRecordErrorCodeV1.CLEANUP_INCOMPLETE)


class _RecordLeaseFiles:
    def __init__(self, files: _RecordFiles, stem: str) -> None:
        self.files = files
        self.record_name = stem + ".json"
        self._lock_name = stem + ".lock"
        self._lock_descriptor: int | None = None
        self._lock_identity: FileIdentity | None = None
        self._locked = False
        self._temporary: _CreatedFile | None = None
        self._published_identity: FileIdentity | None = None

    def acquire(self) -> None:
        self._lock_descriptor = self.files.open(self._lock_name, "lock")
        self._lock_identity = self.files.identity(self._lock_descriptor)
        self.files.lock(self._lock_descriptor)
        self._locked = True
        self._require_lock()

    def _require_lock(self) -> None:
        if (
            not self._locked or self._lock_descriptor is None
            or self.files.named_identity(self._lock_name) != self._lock_identity
            or self.files.identity(self._lock_descriptor) != self._lock_identity
        ):
            raise LocalRecordError(LocalRecordErrorCodeV1.CONFLICT)

    def publish(self, payload: bytes, expected: FileIdentity | None) -> None:
        self._require_lock()
        self._discard_temporary()
        if self.files.named_identity(self.record_name) != expected:
            raise LocalRecordError(LocalRecordErrorCodeV1.CONFLICT)
        name = "." + token_hex(16) + ".tmp"
        created = self._temporary = _CreatedFile(name)
        try:
            descriptor = self.files.open(name, "new", created=created)
        except FileExistsError:
            self._temporary = None
            raise
        identity = created.identity
        assert identity is not None
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("incomplete record write")
            written += count
        os.fsync(descriptor)
        self._require_lock()
        if self.files.named_identity(self.record_name) != expected:
            raise LocalRecordError(LocalRecordErrorCodeV1.CONFLICT)
        # Install the exact identity before the rename effect. It also owns a
        # publication whose rename succeeded but durability acknowledgment failed.
        self._published_identity = identity
        self.files.replace(name, self.record_name)
        if self.files.named_identity(self.record_name) != identity:
            raise LocalRecordError(LocalRecordErrorCodeV1.CONFLICT)
        self._discard_temporary()

    def _discard_temporary(self) -> None:
        temporary = self._temporary
        if temporary is None:
            return
        descriptor = temporary.descriptor
        if descriptor is None:
            self.files.discard_unopened(temporary.name)
        else:
            if temporary.identity is None:
                temporary.identity = self.files.identity(descriptor)
            self.files.remove(temporary.name, temporary.identity)
            self.files.close_descriptor(descriptor)
        self._temporary = None

    def close(self) -> None:
        if self._published_identity is not None:
            self.files.remove(self.record_name, self._published_identity)
            self._published_identity = None
        self._discard_temporary()
        descriptor = self._lock_descriptor
        if descriptor is not None:
            if self._locked:
                self.files.unlock(descriptor)
                self._locked = False
            self.files.close_descriptor(descriptor)
            self._lock_descriptor = None
