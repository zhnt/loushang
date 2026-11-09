"""Durable cleanup-domain tombstones for rejected PLC9B quarantine roots."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Literal

from loushang.foundation.json import _unique_json_object_hook
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
    journal_file_read_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
    decode_nullable,
)
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    PackageQuarantineCleanupTargetV1,
    PackageQuarantineStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecyclePhase,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    _nonempty_string as _wire_string,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    _versioned_dict as _exact_dict,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    _wire_int as _wire_int,
)

PACKAGE_QUARANTINE_CLEANUP_STATUS_VERSION = 1
PACKAGE_QUARANTINE_CLEANUP_RECORD_VERSION = 1

CleanupDisposition = Literal["cleanup_retryable", "cleanup_complete"]
_READ_ONLY_LOAD_POLICY = JournalLoadPolicy(partial_tail="raise", create_lock=False)


class PackageQuarantineCleanupJournalError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageQuarantineCleanupStatusV1:
    target: PackageQuarantineCleanupTargetV1
    rejection_code: str
    rejection_stage: PackageLifecyclePhase
    disposition: CleanupDisposition
    cleanup_revision: int
    failure: PackageLifecycleFailureV1 | None
    status_version: int = PACKAGE_QUARANTINE_CLEANUP_STATUS_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.target, PackageQuarantineCleanupTargetV1):
            raise TypeError("Package quarantine cleanup target is required")
        if not self.rejection_code:
            raise ValueError("Cleanup rejection code is required")
        if (
            len(self.rejection_code) > 96
            or re.fullmatch(r"[a-z0-9_]+", self.rejection_code) is None
        ):
            raise ValueError("Cleanup rejection code must be a bounded safe code")
        if not isinstance(self.cleanup_revision, int) or self.cleanup_revision < 1:
            raise ValueError("Cleanup revision must be positive")
        if self.disposition == "cleanup_retryable":
            expected = _cleanup_failure(self.target, stage=self.rejection_stage)
            if self.failure != expected:
                raise ValueError("Retryable cleanup status requires cleanup failure")
        elif self.disposition == "cleanup_complete":
            if self.failure is not None:
                raise ValueError("Complete cleanup status cannot carry a failure")
        else:
            raise ValueError("Unsupported cleanup disposition")
        if self.status_version != PACKAGE_QUARANTINE_CLEANUP_STATUS_VERSION:
            raise ValueError("Unsupported Package quarantine cleanup status")

    def to_dict(self) -> dict[str, object]:
        return {
            "cleanupRevision": self.cleanup_revision,
            "disposition": self.disposition,
            "failure": None if self.failure is None else self.failure.to_dict(),
            "rejectionCode": self.rejection_code,
            "rejectionStage": self.rejection_stage,
            "statusVersion": self.status_version,
            "target": self.target.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageQuarantineCleanupStatusV1:
        document = _exact_dict(
            value,
            fields=_QUARANTINE_CLEANUP_STATUS_V1_SCHEMA.keys,
            name="Package quarantine cleanup status",
        )
        return _QUARANTINE_CLEANUP_STATUS_V1_SCHEMA.decode(cls, document)


@dataclass(frozen=True, slots=True)
class PackageQuarantineCleanupRecordV1:
    record_revision: int
    prior_cleanup_revision: int
    status: PackageQuarantineCleanupStatusV1
    record_version: int = PACKAGE_QUARANTINE_CLEANUP_RECORD_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.record_revision, int) or self.record_revision < 1:
            raise ValueError("Cleanup record revision must be positive")
        if (
            not isinstance(self.prior_cleanup_revision, int)
            or self.prior_cleanup_revision < 0
        ):
            raise ValueError("Prior cleanup revision must be non-negative")
        if self.status.cleanup_revision != self.record_revision:
            raise ValueError("Cleanup status must own its record revision")
        if self.record_version != PACKAGE_QUARANTINE_CLEANUP_RECORD_VERSION:
            raise ValueError("Unsupported Package quarantine cleanup record")

    def to_dict(self) -> dict[str, object]:
        return {
            "priorCleanupRevision": self.prior_cleanup_revision,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "status": self.status.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageQuarantineCleanupRecordV1:
        document = _exact_dict(
            value,
            fields=_QUARANTINE_CLEANUP_RECORD_V1_SCHEMA.keys,
            name="Package quarantine cleanup record",
        )
        return _QUARANTINE_CLEANUP_RECORD_V1_SCHEMA.decode(cls, document)


def _encode_record(record: PackageQuarantineCleanupRecordV1) -> dict[str, object]:
    return record.to_dict()


def _decode_record(value: object) -> PackageQuarantineCleanupRecordV1:
    try:
        return PackageQuarantineCleanupRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package quarantine cleanup record is invalid",
            code="invalid_package_quarantine_cleanup_record",
        ) from exc


PACKAGE_QUARANTINE_CLEANUP_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


class PackageQuarantineCleanupJournal:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def append_pending(
        self,
        target: PackageQuarantineCleanupTargetV1,
        *,
        rejection_code: str,
        rejection_stage: PackageLifecyclePhase,
    ) -> PackageQuarantineCleanupStatusV1:
        with self._exclusive():
            records = self._load_unlocked()
            current = _project(records).get(target.cleanup_id)
            if current is not None:
                if (
                    current.target == target
                    and current.rejection_code == rejection_code
                    and current.rejection_stage == rejection_stage
                ):
                    return current
                raise self._error(
                    "Package cleanup identity conflict",
                    code="package_operation_identity_conflict",
                )
            revision = len(records) + 1
            status = PackageQuarantineCleanupStatusV1(
                target=target,
                rejection_code=rejection_code,
                rejection_stage=rejection_stage,
                disposition="cleanup_retryable",
                cleanup_revision=revision,
                failure=_cleanup_failure(target, stage=rejection_stage),
            )
            self._append_unlocked(
                PackageQuarantineCleanupRecordV1(
                    record_revision=revision,
                    prior_cleanup_revision=0,
                    status=status,
                )
            )
            return status

    def repair(
        self,
        cleanup_id: str,
        *,
        expected_cleanup_revision: int,
        store: PackageQuarantineStore,
    ) -> PackageQuarantineCleanupStatusV1:
        if not isinstance(store, PackageQuarantineStore):
            raise TypeError("Package quarantine store is required")
        with self._exclusive():
            records = self._load_unlocked()
            current = _project(records).get(cleanup_id)
            if current is None:
                raise self._error(
                    "Package cleanup tombstone does not exist",
                    code="package_cleanup_not_found",
                )
            if current.disposition == "cleanup_complete":
                return current
            if current.cleanup_revision != expected_cleanup_revision:
                raise self._error(
                    "Package cleanup compare-and-swap failed",
                    code="package_cleanup_revision_conflict",
                )
            store._repair(current.target)
            revision = len(records) + 1
            completed = PackageQuarantineCleanupStatusV1(
                target=current.target,
                rejection_code=current.rejection_code,
                rejection_stage=current.rejection_stage,
                disposition="cleanup_complete",
                cleanup_revision=revision,
                failure=None,
            )
            self._append_unlocked(
                PackageQuarantineCleanupRecordV1(
                    record_revision=revision,
                    prior_cleanup_revision=current.cleanup_revision,
                    status=completed,
                )
            )
            return completed

    def status(self, cleanup_id: str) -> PackageQuarantineCleanupStatusV1 | None:
        with self._exclusive():
            return _project(self._load_unlocked()).get(cleanup_id)

    def read_operation_tombstones(
        self, operation_id: str
    ) -> tuple[PackageQuarantineCleanupStatusV1, ...]:
        """Read exact cleanup-domain facts without creating or repairing state."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package cleanup operation id is required")
        with journal_file_read_lock(
            self._path,
            "shared",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
            create_lock=False,
        ):
            statuses = _project(self._load_unlocked(load_policy=_READ_ONLY_LOAD_POLICY))
        return tuple(
            statuses[cleanup_id]
            for cleanup_id in sorted(statuses)
            if statuses[cleanup_id].target.operation_id == operation_id
        )

    def records(self) -> tuple[PackageQuarantineCleanupRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def _append_unlocked(self, record: PackageQuarantineCleanupRecordV1) -> None:
        append_jsonl_record(
            self._path,
            record,
            record_codec=PACKAGE_QUARANTINE_CLEANUP_JOURNAL_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
        )

    def _load_unlocked(
        self, *, load_policy: JournalLoadPolicy | None = None
    ) -> tuple[PackageQuarantineCleanupRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageQuarantineCleanupRecordV1] = (
                load_jsonl(
                    self._path,
                    record_codec=PACKAGE_QUARANTINE_CLEANUP_JOURNAL_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._durability,
                    load_policy=load_policy or self._load_policy,
                )
            )
            _assert_no_duplicate_json_keys(self._path)
            _project(snapshot.records)
            return snapshot.records
        except (JournalCodecError, JournalFileError, TypeError, ValueError) as exc:
            raise self._error(
                "Package quarantine cleanup journal is corrupt",
                code="package_cleanup_journal_corrupt",
            ) from exc

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _error(
        self, message: str, *, code: str
    ) -> PackageQuarantineCleanupJournalError:
        return PackageQuarantineCleanupJournalError(
            message,
            code=code,
            path=self._path,
        )


class PackageQuarantineCleanupOwner:
    """Sole cleanup-domain writer over one fixed quarantine store."""

    def __init__(
        self,
        *,
        journal: PackageQuarantineCleanupJournal,
        store: PackageQuarantineStore,
    ) -> None:
        if not isinstance(journal, PackageQuarantineCleanupJournal):
            raise TypeError("Package quarantine cleanup journal is required")
        if not isinstance(store, PackageQuarantineStore):
            raise TypeError("Package quarantine store is required")
        self._journal = journal
        self._store = store

    @property
    def journal(self) -> PackageQuarantineCleanupJournal:
        return self._journal

    def read_operation_tombstones(
        self, operation_id: str
    ) -> tuple[PackageQuarantineCleanupStatusV1, ...]:
        return self._journal.read_operation_tombstones(operation_id)

    def record_pending(
        self,
        target: PackageQuarantineCleanupTargetV1,
        *,
        rejection_code: str,
        rejection_stage: PackageLifecyclePhase,
    ) -> PackageQuarantineCleanupStatusV1:
        return self._journal.append_pending(
            target,
            rejection_code=rejection_code,
            rejection_stage=rejection_stage,
        )

    def repair(
        self,
        cleanup_id: str,
        *,
        expected_cleanup_revision: int,
    ) -> PackageQuarantineCleanupStatusV1:
        return self._journal.repair(
            cleanup_id,
            expected_cleanup_revision=expected_cleanup_revision,
            store=self._store,
        )

    def status(self, cleanup_id: str) -> PackageQuarantineCleanupStatusV1 | None:
        return self._journal.status(cleanup_id)


def _project(
    records: tuple[PackageQuarantineCleanupRecordV1, ...],
) -> dict[str, PackageQuarantineCleanupStatusV1]:
    statuses: dict[str, PackageQuarantineCleanupStatusV1] = {}
    for revision, record in enumerate(records, start=1):
        if record.record_revision != revision:
            raise ValueError("Package cleanup revisions are not contiguous")
        cleanup_id = record.status.target.cleanup_id
        current = statuses.get(cleanup_id)
        if current is None:
            if (
                record.prior_cleanup_revision != 0
                or record.status.disposition != "cleanup_retryable"
            ):
                raise ValueError("First cleanup record must be retryable")
        elif (
            current.disposition != "cleanup_retryable"
            or record.prior_cleanup_revision != current.cleanup_revision
            or record.status.target != current.target
            or record.status.rejection_code != current.rejection_code
            or record.status.rejection_stage != current.rejection_stage
            or record.status.disposition != "cleanup_complete"
        ):
            raise ValueError("Unsupported Package cleanup transition")
        statuses[cleanup_id] = record.status
    return statuses


def _cleanup_failure(
    target: PackageQuarantineCleanupTargetV1,
    *,
    stage: PackageLifecyclePhase,
) -> PackageLifecycleFailureV1:
    return PackageLifecycleFailureV1(
        code="package_quarantine_cleanup_retryable",
        stage=stage,
        retryable=True,
        retry_domain="cleanup",
        operator_action="repair",
        subject_kind="cleanup",
        subject_id=target.cleanup_id,
        operation_id=target.operation_id,
        evidence_ref=target.cleanup_id,
    )


def _assert_no_duplicate_json_keys(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            json.loads(line, object_pairs_hook=_unique_json_object)


_unique_json_object = _unique_json_object_hook(
    lambda: "Package cleanup journal contains duplicate JSON keys",
)


__all__ = [
    "PACKAGE_QUARANTINE_CLEANUP_JOURNAL_CODEC",
    "PackageQuarantineCleanupJournal",
    "PackageQuarantineCleanupJournalError",
    "PackageQuarantineCleanupOwner",
    "PackageQuarantineCleanupRecordV1",
    "PackageQuarantineCleanupStatusV1",
]


_QUARANTINE_CLEANUP_STATUS_V1_SCHEMA = RecordSchema.for_dataclass(
    PackageQuarantineCleanupStatusV1,
    _wire_string,
    RecordField("target", decoder=PackageQuarantineCleanupTargetV1.from_dict),
    RecordField("disposition", "cleanup disposition"),
    RecordField("cleanup_revision", "cleanup revision", _wire_int),
    RecordField(
        "failure",
        decoder=partial(decode_nullable, decoder=PackageLifecycleFailureV1.from_dict),
    ),
    RecordField("status_version", "cleanup status version", _wire_int),
    derive_labels=True,
)


_QUARANTINE_CLEANUP_RECORD_V1_SCHEMA = RecordSchema(
    text_decoder=_wire_string,
    fields=(
        RecordField("record_revision", "cleanup record revision", _wire_int),
        RecordField("prior_cleanup_revision", "prior cleanup revision", _wire_int),
        RecordField("status", decoder=PackageQuarantineCleanupStatusV1.from_dict),
        RecordField("record_version", "cleanup record version", _wire_int),
    ),
)
