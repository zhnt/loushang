"""Durable Package epoch runtime leases paired with OS liveness locks."""

from __future__ import annotations

import errno
import json
import secrets
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Literal, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JsonlSnapshot,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochLeaseSnapshotV1,
    PackageEpochRuntimeLeaseV1,
)

LeaseEventKind = Literal["registered", "released", "orphan_repaired"]


class PackageEpochRuntimeLeaseRegistryError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageEpochRuntimeLeaseRecordV1:
    record_revision: int
    store_id: str
    kind: LeaseEventKind
    lease: PackageEpochRuntimeLeaseV1
    record_version: int = 1

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Package runtime lease revision is invalid")
        if not isinstance(self.store_id, str) or not self.store_id:
            raise ValueError("Package runtime lease store is invalid")
        if self.kind not in {"registered", "released", "orphan_repaired"}:
            raise ValueError("Package runtime lease event is invalid")
        if not isinstance(self.lease, PackageEpochRuntimeLeaseV1):
            raise TypeError("Package runtime lease event requires an exact lease")
        if self.record_version != 1:
            raise ValueError("Unsupported Package runtime lease event")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "lease": self.lease.to_dict(),
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "storeId": self.store_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageEpochRuntimeLeaseRecordV1:
        if not isinstance(value, dict) or set(value) != {
            "kind", "lease", "recordRevision", "recordVersion", "storeId"
        }:
            raise ValueError("Package runtime lease record has an invalid schema")
        if (
            type(value["recordRevision"]) is not int
            or type(value["recordVersion"]) is not int
            or not isinstance(value["kind"], str)
            or not isinstance(value["storeId"], str)
        ):
            raise TypeError("Package runtime lease record has invalid fields")
        return cls(
            record_revision=cast(int, value["recordRevision"]),
            store_id=cast(str, value["storeId"]),
            kind=cast(LeaseEventKind, value["kind"]),
            lease=PackageEpochRuntimeLeaseV1.from_dict(value["lease"]),
            record_version=cast(int, value["recordVersion"]),
        )


def _decode_record(value: object) -> PackageEpochRuntimeLeaseRecordV1:
    try:
        return PackageEpochRuntimeLeaseRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package runtime lease record is invalid",
            code="invalid_package_runtime_lease_record",
        ) from exc


_RECORD_CODEC = FunctionalJournalRecordCodec(
    encoder=lambda record: record.to_dict(), decoder=_decode_record
)


class PackageEpochRuntimeLeaseHandle:
    """Process-held liveness capability for one registered runtime lease."""

    def __init__(
        self,
        *,
        registry: PackageEpochRuntimeLeaseRegistry,
        lease: PackageEpochRuntimeLeaseV1,
        lock: AbstractContextManager[RootedFile],
    ) -> None:
        self.lease = lease
        self._registry = registry
        self._lock = lock
        self._released = False
        self._mutex = Lock()

    def release(self) -> None:
        with self._mutex:
            if not self._released:
                self._registry._release(self)

    def __enter__(self) -> PackageEpochRuntimeLeaseHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class PackageEpochRuntimeLeaseRegistry:
    """Complete active lease snapshot under the Product cutover lock."""

    def __init__(
        self,
        *,
        path: Path,
        coordination_lock: Path,
        file_io: RootedFileIO,
        fences: PackageEpochFenceJournal,
        store_id: str,
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("Package runtime lease journal must be absolute")
        if not isinstance(coordination_lock, Path) or not coordination_lock.is_absolute():
            raise ValueError("Package coordination lock must be absolute")
        if ".." in path.parts or ".." in coordination_lock.parts:
            raise ValueError("Package runtime lease paths cannot traverse parents")
        if not isinstance(fences, PackageEpochFenceJournal):
            raise TypeError("Package epoch fence journal is required")
        if not isinstance(file_io, RootedFileIO) or file_io.root != path.parent:
            raise TypeError("Package runtime lease requires admitted rooted IO")
        if not isinstance(store_id, str) or not store_id:
            raise ValueError("Package runtime lease store is required")
        if path == coordination_lock or path.parent != coordination_lock.parent:
            raise ValueError("Package lease journal and coordination must share a root")
        self.path = path
        self.coordination_lock = coordination_lock
        self.fences = fences
        self.store_id = store_id
        self._io = file_io
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)

    def register(
        self, *, runtime_id: str, runtime_protocol_epoch: int
    ) -> PackageEpochRuntimeLeaseHandle:
        if not isinstance(runtime_id, str) or not runtime_id:
            raise ValueError("Package runtime identity is required")
        if type(runtime_protocol_epoch) is not int or runtime_protocol_epoch < 1:
            raise ValueError("Package runtime protocol epoch is invalid")
        with self._coordination("exclusive"):
            records, active = self._load_unlocked()
            fence = self.fences.current(self.store_id)
            if fence is None:
                raise self._error("Package Store has no current epoch fence", "package_epoch_unfenced")
            if runtime_protocol_epoch < fence.minimum_runtime_protocol_epoch:
                raise self._error("Package runtime protocol is too old", "package_runtime_protocol_unsupported")
            self._require_live(active)
            if any(
                lease.runtime_epoch != fence.epoch
                or lease.store_root_identity != fence.fenced_root_identity
                for lease in active.values()
            ):
                raise self._error("Package Store has mixed runtime epochs", "package_epoch_leases_mixed")
            if any(lease.runtime_id == runtime_id for lease in active.values()):
                raise self._error(
                    "Package runtime identity is already registered",
                    "package_epoch_lease_identity_conflict",
                )
            receipt_id = sha256(secrets.token_bytes(32)).hexdigest()
            lease = PackageEpochRuntimeLeaseV1.create(
                runtime_id=runtime_id,
                runtime_epoch=fence.epoch,
                store_root_identity=fence.fenced_root_identity,
                registration_receipt_id=receipt_id,
            )
            lock = self._io.bind(self._lease_lock_path(lease.lease_id))
            rooted = lock.__enter__()
            try:
                rooted.acquire_lock(exclusive=True)
                if self.fences.current(self.store_id) != fence:
                    raise self._error("Package epoch advanced during registration", "package_epoch_fence_stale")
                self._append_unlocked(
                    PackageEpochRuntimeLeaseRecordV1(
                        record_revision=len(records) + 1,
                        store_id=self.store_id,
                        kind="registered",
                        lease=lease,
                    )
                )
            except BaseException:
                lock.__exit__(None, None, None)
                raise
            return PackageEpochRuntimeLeaseHandle(registry=self, lease=lease, lock=lock)

    def snapshot(self, *, store_id: str) -> PackageEpochLeaseSnapshotV1:
        if store_id != self.store_id:
            raise self._error("Package runtime lease store changed", "package_epoch_lease_store_changed")
        with self._coordination("shared"):
            records, active = self._load_unlocked()
            self._require_live(active)
            if not active:
                raise self._error("Package Store has no active runtime", "package_epoch_lease_absent")
            return PackageEpochLeaseSnapshotV1.create(
                store_id=self.store_id,
                owner_revision=len(records),
                active_leases=tuple(active.values()),
            )

    def repair_orphan(self, lease_id: str) -> None:
        with self._coordination("exclusive"):
            records, active = self._load_unlocked()
            lease = active.get(lease_id)
            if lease is None:
                raise self._error("Package runtime lease is not active", "package_epoch_lease_absent")
            try:
                with self._io.bind(self._lease_lock_path(lease_id)) as rooted:
                    rooted.stat()
                    try:
                        rooted.acquire_lock(exclusive=True)
                    except OSError as exc:
                        if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES}:
                            raise self._error(
                                "Package runtime lease remains live", "package_epoch_lease_live"
                            ) from exc
                        raise
                    self._append_unlocked(
                        PackageEpochRuntimeLeaseRecordV1(
                            record_revision=len(records) + 1,
                            store_id=self.store_id,
                            kind="orphan_repaired",
                            lease=lease,
                        )
                    )
            except OSError as exc:
                raise self._error("Package runtime lease liveness is unknown", "package_epoch_lease_liveness_unknown") from exc

    def _release(self, handle: PackageEpochRuntimeLeaseHandle) -> None:
        with self._coordination("exclusive"):
            records, active = self._load_unlocked()
            if active.get(handle.lease.lease_id) != handle.lease:
                raise self._error("Package runtime lease changed", "package_epoch_lease_stale")
            self._append_unlocked(
                PackageEpochRuntimeLeaseRecordV1(
                    record_revision=len(records) + 1,
                    store_id=self.store_id,
                    kind="released",
                    lease=handle.lease,
                )
            )
            try:
                handle._lock.__exit__(None, None, None)
            finally:
                handle._released = True

    def _load_unlocked(
        self,
    ) -> tuple[
        tuple[PackageEpochRuntimeLeaseRecordV1, ...],
        dict[str, PackageEpochRuntimeLeaseV1],
    ]:
        try:
            raw = self._io.read_bytes(self.path).decode("utf-8")
        except FileNotFoundError:
            return (), {}
        except (OSError, UnicodeError) as exc:
            raise self._error("Package runtime lease journal is unsafe", "package_epoch_lease_journal_corrupt") from exc
        try:
            _assert_no_duplicate_keys(raw)
            loaded: JsonlSnapshot[None, PackageEpochRuntimeLeaseRecordV1] = decode_jsonl(
                raw,
                target=self.path,
                record_codec=_RECORD_CODEC,
            )
            records = loaded.records
        except (JournalFileError, OSError, UnicodeError, ValueError) as exc:
            raise self._error("Package runtime lease journal is corrupt", "package_epoch_lease_journal_corrupt") from exc
        active: dict[str, PackageEpochRuntimeLeaseV1] = {}
        seen: set[str] = set()
        for revision, record in enumerate(records, start=1):
            lease_id = record.lease.lease_id
            if record.record_revision != revision or record.store_id != self.store_id:
                raise self._error("Package runtime lease history changed", "package_epoch_lease_journal_corrupt")
            if record.kind == "registered":
                if lease_id in seen:
                    raise self._error("Package runtime lease was reused", "package_epoch_lease_journal_corrupt")
                active[lease_id] = record.lease
                seen.add(lease_id)
            elif active.get(lease_id) != record.lease:
                raise self._error("Package runtime lease release changed", "package_epoch_lease_journal_corrupt")
            else:
                del active[lease_id]
        return records, active

    def _require_live(self, active: dict[str, PackageEpochRuntimeLeaseV1]) -> None:
        for lease_id in active:
            try:
                with self._io.bind(self._lease_lock_path(lease_id)) as rooted:
                    rooted.stat()
                    try:
                        rooted.acquire_lock(exclusive=True)
                    except OSError as exc:
                        if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES}:
                            continue
                        raise
                    raise self._error("Package runtime lease is orphaned", "package_epoch_lease_orphaned")
            except OSError as exc:
                raise self._error("Package runtime lease liveness is unknown", "package_epoch_lease_liveness_unknown") from exc

    def _append_unlocked(self, record: PackageEpochRuntimeLeaseRecordV1) -> None:
        try:
            append_jsonl_record(
                self.path,
                record,
                record_codec=_RECORD_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
                file_io=self._io,
            )
        except (JournalFileError, OSError) as exc:
            raise self._error("Package runtime lease append failed", "package_epoch_lease_journal_corrupt") from exc

    def _lease_lock_path(self, lease_id: str) -> Path:
        if len(lease_id) != 64 or any(c not in "0123456789abcdef" for c in lease_id):
            raise ValueError("Package runtime lease identity is invalid")
        return self.path.with_name(f"{self.path.name}.{lease_id}.lease")

    @contextmanager
    def _coordination(self, mode: Literal["shared", "exclusive"]) -> Iterator[None]:
        with self._io.bind(self.coordination_lock) as rooted:
            try:
                rooted.acquire_lock(exclusive=mode == "exclusive", suffix=".lock")
            except OSError as exc:
                if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES}:
                    raise self._error(
                        "Package epoch coordination lock is busy", "package_epoch_lease_busy"
                    ) from exc
                raise
            yield

    @staticmethod
    def _error(message: str, code: str) -> PackageEpochRuntimeLeaseRegistryError:
        return PackageEpochRuntimeLeaseRegistryError(message, code=code)


def _assert_no_duplicate_keys(raw: str) -> None:
    def decode(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate Package runtime lease JSON key")
            result[key] = value
        return result

    for line in raw.splitlines():
        if line.strip():
            json.loads(line, object_pairs_hook=decode)


__all__ = [
    "PackageEpochRuntimeLeaseHandle",
    "PackageEpochRuntimeLeaseRecordV1",
    "PackageEpochRuntimeLeaseRegistry",
    "PackageEpochRuntimeLeaseRegistryError",
]
