"""Durable cleanup-domain tombstones for rejected PLC9B quarantine roots."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

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
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    PackageQuarantineCleanupTargetV1,
    PackageQuarantineStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecyclePhase,
)

PACKAGE_QUARANTINE_CLEANUP_STATUS_VERSION = 1
PACKAGE_QUARANTINE_CLEANUP_RECORD_VERSION = 1

CleanupDisposition = Literal["cleanup_retryable", "cleanup_complete"]


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
            fields={
                "cleanupRevision",
                "disposition",
                "failure",
                "rejectionCode",
                "rejectionStage",
                "statusVersion",
                "target",
            },
            name="Package quarantine cleanup status",
        )
        return cls(
            target=PackageQuarantineCleanupTargetV1.from_dict(document["target"]),
            rejection_code=_wire_string(
                document["rejectionCode"], name="rejection code"
            ),
            rejection_stage=cast(
                PackageLifecyclePhase,
                _wire_string(document["rejectionStage"], name="rejection stage"),
            ),
            disposition=cast(
                CleanupDisposition,
                _wire_string(document["disposition"], name="cleanup disposition"),
            ),
            cleanup_revision=_wire_int(
                document["cleanupRevision"], name="cleanup revision"
            ),
            failure=(
                None
                if document["failure"] is None
                else PackageLifecycleFailureV1.from_dict(document["failure"])
            ),
            status_version=_wire_int(
                document["statusVersion"], name="cleanup status version"
            ),
        )


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
            fields={
                "priorCleanupRevision",
                "recordRevision",
                "recordVersion",
                "status",
            },
            name="Package quarantine cleanup record",
        )
        return cls(
            record_revision=_wire_int(
                document["recordRevision"], name="cleanup record revision"
            ),
            prior_cleanup_revision=_wire_int(
                document["priorCleanupRevision"], name="prior cleanup revision"
            ),
            status=PackageQuarantineCleanupStatusV1.from_dict(document["status"]),
            record_version=_wire_int(
                document["recordVersion"], name="cleanup record version"
            ),
        )


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

    def _load_unlocked(self) -> tuple[PackageQuarantineCleanupRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageQuarantineCleanupRecordV1] = (
                load_jsonl(
                    self._path,
                    record_codec=PACKAGE_QUARANTINE_CLEANUP_JOURNAL_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._durability,
                    load_policy=self._load_policy,
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


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Package cleanup journal contains duplicate JSON keys")
        result[key] = value
    return result


def _exact_dict(value: object, *, fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} does not match its versioned schema")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return value


__all__ = [
    "PACKAGE_QUARANTINE_CLEANUP_JOURNAL_CODEC",
    "PackageQuarantineCleanupJournal",
    "PackageQuarantineCleanupJournalError",
    "PackageQuarantineCleanupOwner",
    "PackageQuarantineCleanupRecordV1",
    "PackageQuarantineCleanupStatusV1",
]
