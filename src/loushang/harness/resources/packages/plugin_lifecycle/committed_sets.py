"""Atomic committed-set evidence owned by the dark PLC9B Package transaction."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeAlias, cast

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    CommittedPackageSetRefV1,
    DependencyClosureLockV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

PACKAGE_COMMITTED_SET_RECORD_VERSION = 1

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PackageCommittedSetJournalError(RuntimeError):
    """Fail-closed atomic committed-set journal refusal."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageCommittedSetRecordV1:
    """One atomic graph lock plus its sole logical committed-set ref."""

    record_revision: int
    closure_lock: DependencyClosureLockV2
    committed_set: CommittedPackageSetRefV1
    record_version: int = PACKAGE_COMMITTED_SET_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_positive(self.record_revision, name="committed-set record revision")
        if not isinstance(self.closure_lock, DependencyClosureLockV2):
            raise TypeError("Dependency closure lock is required")
        if not isinstance(self.committed_set, CommittedPackageSetRefV1):
            raise TypeError("Committed Package set ref is required")
        if self.committed_set.commit_revision != self.record_revision:
            raise ValueError("Committed Package set revision changed")
        expected = CommittedPackageSetRefV1.create(
            self.closure_lock,
            request_fingerprint=self.committed_set.request_fingerprint,
            product_id=self.committed_set.product_id,
            scope_id=self.committed_set.scope_id,
            installation_id=self.committed_set.installation_id,
            plugin_id=self.committed_set.plugin_id,
            classification_fingerprint=(self.committed_set.classification_fingerprint),
            commit_revision=self.record_revision,
        )
        if expected != self.committed_set:
            raise ValueError("Committed Package set does not match its closure lock")
        if self.record_version != PACKAGE_COMMITTED_SET_RECORD_VERSION:
            raise ValueError("Unsupported Package committed-set record")

    @property
    def operation_id(self) -> str:
        return self.committed_set.operation_id

    def to_dict(self) -> dict[str, object]:
        return {
            "closureLock": self.closure_lock.to_dict(),
            "closureLockDigest": self.closure_lock.lock_digest,
            "committedSet": self.committed_set.to_dict(),
            "operationId": self.operation_id,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "setId": self.committed_set.set_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageCommittedSetRecordV1:
        document = _exact_dict(
            value,
            fields={
                "closureLock",
                "closureLockDigest",
                "committedSet",
                "operationId",
                "recordRevision",
                "recordVersion",
                "setId",
            },
            name="Package committed-set record",
        )
        record = cls(
            record_revision=_wire_int(
                document["recordRevision"], name="record revision"
            ),
            closure_lock=DependencyClosureLockV2.from_dict(document["closureLock"]),
            committed_set=CommittedPackageSetRefV1.from_dict(document["committedSet"]),
            record_version=_wire_int(document["recordVersion"], name="record version"),
        )
        if (
            document["closureLockDigest"] != record.closure_lock.lock_digest
            or document["operationId"] != record.operation_id
            or document["setId"] != record.committed_set.set_id
        ):
            raise ValueError("Package committed-set record projection changed")
        return record


def _encode_record(record: PackageCommittedSetRecordV1) -> dict[str, object]:
    if not isinstance(record, PackageCommittedSetRecordV1):
        raise TypeError("Package committed-set record is required")
    return record.to_dict()


def _decode_record(value: object) -> PackageCommittedSetRecordV1:
    try:
        return PackageCommittedSetRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package committed-set record is invalid",
            code="invalid_package_committed_set_record",
        ) from exc


PACKAGE_COMMITTED_SET_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


@dataclass(frozen=True, slots=True)
class PackageCommittedSetGcTombstoneV1:
    """Incompatible durable refusal to commit the same physical root ref."""

    journal_revision: int
    set_id: str
    root_ref_id: str
    tombstone_id: str
    record_kind: Literal["committed_set_gc_tombstone"] = (
        "committed_set_gc_tombstone"
    )
    record_version: int = 2

    def __post_init__(self) -> None:
        _require_positive(self.journal_revision, name="GC journal revision")
        if (
            _SHA256.fullmatch(self.set_id) is None
            or _SHA256.fullmatch(self.root_ref_id) is None
            or self.record_kind != "committed_set_gc_tombstone"
            or self.record_version != 2
            or self.tombstone_id != _fingerprint(self._identity_dict())
        ):
            raise ValueError("Committed-set GC tombstone identity is invalid")

    @classmethod
    def create(
        cls, record: PackageCommittedSetRecordV1, *, journal_revision: int
    ) -> PackageCommittedSetGcTombstoneV1:
        identity = {
            "recordKind": "committed_set_gc_tombstone",
            "recordVersion": 2,
            "rootRefId": record.committed_set.root_ref.ref_id,
            "setId": record.committed_set.set_id,
        }
        return cls(
            journal_revision=journal_revision,
            set_id=record.committed_set.set_id,
            root_ref_id=record.committed_set.root_ref.ref_id,
            tombstone_id=_fingerprint(identity),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "recordKind": self.record_kind,
            "recordVersion": self.record_version,
            "rootRefId": self.root_ref_id,
            "setId": self.set_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_dict(),
            "journalRevision": self.journal_revision,
            "tombstoneId": self.tombstone_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageCommittedSetGcTombstoneV1:
        document = _exact_dict(
            value,
            fields={
                "journalRevision", "recordKind", "recordVersion", "rootRefId",
                "setId", "tombstoneId",
            },
            name="Committed-set GC tombstone",
        )
        return cls(
            journal_revision=_wire_int(document["journalRevision"], name="journal revision"),
            set_id=_wire_string(document["setId"], name="committed set id"),
            root_ref_id=_wire_string(document["rootRefId"], name="root ref id"),
            tombstone_id=_wire_string(document["tombstoneId"], name="tombstone id"),
            record_kind=cast(
                Literal["committed_set_gc_tombstone"], document["recordKind"]
            ),
            record_version=_wire_int(document["recordVersion"], name="record version"),
        )


CommittedSetJournalEvent: TypeAlias = (
    PackageCommittedSetRecordV1 | PackageCommittedSetGcTombstoneV1
)


def _decode_event(value: object) -> CommittedSetJournalEvent:
    try:
        if type(value) is dict and value.get("recordKind") == "committed_set_gc_tombstone":
            return PackageCommittedSetGcTombstoneV1.from_dict(value)
        return PackageCommittedSetRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package committed-set event is invalid",
            code="invalid_package_committed_set_record",
        ) from exc


_EVENT_CODEC = FunctionalJournalRecordCodec(
    encoder=lambda event: event.to_dict(),
    decoder=_decode_event,
)


class PackageCommittedSetJournal:
    """Atomically publish one immutable complete graph per Package operation."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def publish(
        self,
        closure_lock: DependencyClosureLockV2,
        *,
        request_fingerprint: str,
        product_id: str,
        scope_id: str,
        installation_id: str,
        plugin_id: str,
        classification_fingerprint: str,
    ) -> CommittedPackageSetRefV1:
        if not isinstance(closure_lock, DependencyClosureLockV2):
            raise TypeError("Dependency closure lock is required")
        with self._exclusive():
            events = self._load_events_unlocked()
            records = tuple(
                item for item in events if isinstance(item, PackageCommittedSetRecordV1)
            )
            existing = next(
                (
                    record
                    for record in records
                    if record.operation_id == closure_lock.operation_id
                ),
                None,
            )
            revision = (
                len(records) + 1 if existing is None else existing.record_revision
            )
            committed_set = CommittedPackageSetRefV1.create(
                closure_lock,
                request_fingerprint=request_fingerprint,
                product_id=product_id,
                scope_id=scope_id,
                installation_id=installation_id,
                plugin_id=plugin_id,
                classification_fingerprint=classification_fingerprint,
                commit_revision=revision,
            )
            if _tombstoned(events, committed_set.root_ref.ref_id):
                raise self._error(
                    "Committed Package root ref was retired by GC",
                    code="package_committed_set_gc_tombstoned",
                )
            if existing is not None:
                if (
                    existing.closure_lock == closure_lock
                    and existing.committed_set == committed_set
                ):
                    return existing.committed_set
                raise self._error(
                    "Package committed-set identity changed",
                    code="package_operation_identity_conflict",
                )
            record = PackageCommittedSetRecordV1(
                record_revision=revision,
                closure_lock=closure_lock,
                committed_set=committed_set,
            )
            append_jsonl_record(
                self._path,
                record,
                record_codec=_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return committed_set

    def tombstone(
        self, record: PackageCommittedSetRecordV1
    ) -> PackageCommittedSetGcTombstoneV1:
        """Fence later committed-set aliases before physical root deletion."""

        if not isinstance(record, PackageCommittedSetRecordV1):
            raise TypeError("Exact committed Package set is required")
        with self._exclusive():
            events = self._load_events_unlocked()
            if record not in events:
                raise self._error(
                    "GC committed set is unknown",
                    code="package_committed_set_gc_unknown",
                )
            if sum(
                isinstance(item, PackageCommittedSetRecordV1)
                and item.committed_set.root_ref.ref_id
                == record.committed_set.root_ref.ref_id
                for item in events
            ) != 1:
                raise self._error(
                    "GC committed root ref is aliased",
                    code="package_committed_set_gc_aliased",
                )
            existing = next(
                (
                    item for item in events
                    if isinstance(item, PackageCommittedSetGcTombstoneV1)
                    and item.set_id == record.committed_set.set_id
                ),
                None,
            )
            if existing is not None:
                return existing
            tombstone = PackageCommittedSetGcTombstoneV1.create(
                record, journal_revision=len(events) + 1
            )
            append_jsonl_record(
                self._path,
                tombstone,
                record_codec=_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return tombstone

    def is_tombstoned(self, root_ref_id: str) -> bool:
        if type(root_ref_id) is not str or _SHA256.fullmatch(root_ref_id) is None:
            raise ValueError("Exact Package root ref is required")
        with self._exclusive():
            return _tombstoned(self._load_events_unlocked(), root_ref_id)

    def current(self, operation_id: str) -> PackageCommittedSetRecordV1 | None:
        _require_safe_id(operation_id, name="Package operation identity")
        with self._exclusive():
            return next(
                (
                    record
                    for record in self._load_unlocked()
                    if record.operation_id == operation_id
                ),
                None,
            )

    def records(self) -> tuple[PackageCommittedSetRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _load_unlocked(self) -> tuple[PackageCommittedSetRecordV1, ...]:
        return tuple(
            item
            for item in self._load_events_unlocked()
            if isinstance(item, PackageCommittedSetRecordV1)
        )

    def _load_events_unlocked(self) -> tuple[CommittedSetJournalEvent, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, CommittedSetJournalEvent] = load_jsonl(
                self._path,
                record_codec=_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            events = snapshot.records
            _assert_no_duplicate_json_keys(self._path)
            _validate_events(events)
            return events
        except (JournalCodecError, JournalFileError, TypeError, ValueError) as exc:
            raise self._error(
                "Package committed-set journal is corrupt",
                code="package_committed_set_journal_corrupt",
            ) from exc

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _error(
        self,
        message: str,
        *,
        code: str,
    ) -> PackageCommittedSetJournalError:
        return PackageCommittedSetJournalError(
            message,
            code=code,
            path=self._path,
        )


def _validate_records(records: tuple[PackageCommittedSetRecordV1, ...]) -> None:
    operations: set[str] = set()
    for revision, record in enumerate(records, start=1):
        if record.record_revision != revision:
            raise ValueError("Package committed-set revisions are not contiguous")
        if record.operation_id in operations:
            raise ValueError("Package operation has multiple committed sets")
        operations.add(record.operation_id)


def _validate_events(events: tuple[CommittedSetJournalEvent, ...]) -> None:
    records: list[PackageCommittedSetRecordV1] = []
    retired_refs: set[str] = set()
    for journal_revision, event in enumerate(events, start=1):
        if isinstance(event, PackageCommittedSetRecordV1):
            if event.committed_set.root_ref.ref_id in retired_refs:
                raise ValueError("Committed Package root ref was republished after GC")
            records.append(event)
            continue
        matching = [
            item for item in records
            if item.committed_set.set_id == event.set_id
            and item.committed_set.root_ref.ref_id == event.root_ref_id
        ]
        if (
            event.journal_revision != journal_revision
            or len(matching) != 1
            or event.root_ref_id in retired_refs
            or sum(
                item.committed_set.root_ref.ref_id == event.root_ref_id
                for item in records
            ) != 1
        ):
            raise ValueError("Committed-set GC tombstone lacks one exact root")
        retired_refs.add(event.root_ref_id)
    _validate_records(tuple(records))


def _tombstoned(events: tuple[CommittedSetJournalEvent, ...], root_ref_id: str) -> bool:
    return any(
        isinstance(item, PackageCommittedSetGcTombstoneV1)
        and item.root_ref_id == root_ref_id
        for item in events
    )


def _fingerprint(value: object) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _require_safe_id(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_positive(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be positive")


def _exact_dict(value: object, *, fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} does not match its versioned schema")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if type(value) is not str or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _assert_no_duplicate_json_keys(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            json.loads(line, object_pairs_hook=_unique_json_object)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Package committed set has duplicate JSON keys")
        document[key] = value
    return document


__all__ = [
    "PACKAGE_COMMITTED_SET_JOURNAL_CODEC",
    "PackageCommittedSetJournal",
    "PackageCommittedSetJournalError",
    "PackageCommittedSetGcTombstoneV1",
    "PackageCommittedSetRecordV1",
]
