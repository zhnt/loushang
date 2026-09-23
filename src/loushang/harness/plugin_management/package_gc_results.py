"""Durable PLC9D Store-deletion attempt results and retryable debt.

This ledger records evidence returned by a Store owner. It does not perform
deletion or authorize a caller to invent a successful Store result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import sha256
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
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcDeletionStartV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_gc import (
    PackageStoreGcResultV1,
)

GcAttemptDisposition = Literal["succeeded", "retryable_failure"]


class PluginPackageGcResultError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PluginPackageGcAttemptV1:
    record_revision: int
    attempt_id: str
    reservation_id: str
    deletion_start_operation_id: str
    settlement_id: str
    operation_id: str
    idempotency_key: str
    disposition: GcAttemptDisposition
    store_result: PackageStoreGcResultV1 | None
    error_code: str | None
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.record_revision) is not int
            or self.record_revision < 1
            or not _sha256(self.reservation_id)
            or not _sha256(self.settlement_id)
            or not self.deletion_start_operation_id
            or not self.operation_id
            or not self.idempotency_key
            or self.disposition not in {"succeeded", "retryable_failure"}
            or self.record_version != 1
        ):
            raise ValueError("Package GC attempt identity is invalid")
        if self.disposition == "succeeded":
            if (
                not isinstance(self.store_result, PackageStoreGcResultV1)
                or self.store_result.settlement_id != self.settlement_id
                or self.error_code is not None
            ):
                raise ValueError("Successful Package GC requires one Store result")
        elif self.store_result is not None or not self.error_code:
            raise ValueError("Retryable Package GC failure requires one error code")
        if self.attempt_id != _attempt_id(self):
            raise ValueError("Package GC attempt identity does not match")

    @classmethod
    def create(
        cls,
        *,
        record_revision: int,
        start: PluginPackageGcDeletionStartV2,
        settlement_id: str,
        operation_id: str,
        idempotency_key: str,
        store_result: PackageStoreGcResultV1 | None,
        error_code: str | None,
    ) -> PluginPackageGcAttemptV1:
        if settlement_id not in start.target_settlement_ids:
            raise ValueError("GC attempt is outside the deletion start")
        disposition: GcAttemptDisposition = (
            "succeeded" if store_result is not None else "retryable_failure"
        )
        values = [
            start.reservation_id,
            start.operation_id,
            settlement_id,
            operation_id,
            idempotency_key,
            disposition,
            None if store_result is None else store_result.to_dict(),
            error_code,
        ]
        attempt_id = sha256(
            b"plugin-package-gc-attempt-v1\0"
            + json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(
            record_revision=record_revision,
            attempt_id=attempt_id,
            reservation_id=start.reservation_id,
            deletion_start_operation_id=start.operation_id,
            settlement_id=settlement_id,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            disposition=disposition,
            store_result=store_result,
            error_code=error_code,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "attemptId": self.attempt_id,
            "deletionStartOperationId": self.deletion_start_operation_id,
            "disposition": self.disposition,
            "errorCode": self.error_code,
            "idempotencyKey": self.idempotency_key,
            "operationId": self.operation_id,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "reservationId": self.reservation_id,
            "settlementId": self.settlement_id,
            "storeResult": (
                None if self.store_result is None else self.store_result.to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackageGcAttemptV1:
        if type(value) is not dict or set(value) != {
            "attemptId", "deletionStartOperationId", "disposition", "errorCode",
            "idempotencyKey", "operationId", "recordRevision", "recordVersion",
            "reservationId", "settlementId", "storeResult",
        }:
            raise JournalCodecError(
                "Package GC attempt fields are invalid",
                code="invalid_plugin_package_gc_attempt_record",
            )
        try:
            store_value = value["storeResult"]
            return cls(
                record_revision=_integer(value["recordRevision"]),
                attempt_id=_string(value["attemptId"]),
                reservation_id=_string(value["reservationId"]),
                deletion_start_operation_id=_string(value["deletionStartOperationId"]),
                settlement_id=_string(value["settlementId"]),
                operation_id=_string(value["operationId"]),
                idempotency_key=_string(value["idempotencyKey"]),
                disposition=cast(GcAttemptDisposition, value["disposition"]),
                store_result=(
                    None if store_value is None else PackageStoreGcResultV1.from_dict(store_value)
                ),
                error_code=(
                    None if value["errorCode"] is None else _string(value["errorCode"])
                ),
                record_version=_integer(value["recordVersion"]),
            )
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Package GC attempt record is invalid",
                code="invalid_plugin_package_gc_attempt_record",
            ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginPackageGcAttemptV1.to_dict,
    decoder=PluginPackageGcAttemptV1.from_dict,
)


class PluginPackageGcResultJournal:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def attempts(
        self, start: PluginPackageGcDeletionStartV2
    ) -> tuple[PluginPackageGcAttemptV1, ...]:
        if not isinstance(start, PluginPackageGcDeletionStartV2):
            raise TypeError("Exact GC deletion start is required")
        with journal_file_lock(self._path, "exclusive"):
            records = self._load_unlocked()
            self._validate_start_records(records, start)
            return tuple(
                item for item in records
                if item.reservation_id == start.reservation_id
            )

    def record(
        self,
        start: PluginPackageGcDeletionStartV2,
        *,
        settlement_id: str,
        operation_id: str,
        idempotency_key: str,
        store_result: PackageStoreGcResultV1 | None = None,
        error_code: str | None = None,
    ) -> PluginPackageGcAttemptV1:
        if not isinstance(start, PluginPackageGcDeletionStartV2):
            raise TypeError("Exact GC deletion start is required")
        with journal_file_lock(self._path, "exclusive"):
            records = self._load_unlocked()
            self._validate_start_records(records, start)
            proposed = PluginPackageGcAttemptV1.create(
                record_revision=len(records) + 1,
                start=start,
                settlement_id=settlement_id,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                store_result=store_result,
                error_code=error_code,
            )
            by_operation = next(
                (item for item in records if item.operation_id == operation_id), None
            )
            by_key = next(
                (item for item in records if item.idempotency_key == idempotency_key),
                None,
            )
            if by_operation != by_key:
                raise self._error(
                    "GC attempt identities diverge", "plugin_package_gc_result_conflict"
                )
            if by_operation is not None:
                if by_operation.attempt_id != proposed.attempt_id:
                    raise self._error(
                        "GC attempt identity was reused",
                        "plugin_package_gc_result_conflict",
                    )
                return by_operation
            if any(
                item.disposition == "succeeded"
                and item.reservation_id == start.reservation_id
                and item.settlement_id == settlement_id
                for item in records
            ):
                raise self._error(
                    "GC settlement already succeeded",
                    "plugin_package_gc_result_terminal",
                )
            if any(
                item.settlement_id == settlement_id
                and item.reservation_id != start.reservation_id
                for item in records
            ):
                raise self._error(
                    "GC physical settlement has another reservation",
                    "plugin_package_gc_result_conflict",
                )
            try:
                append_jsonl_record(
                    self._path,
                    proposed,
                    record_codec=_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                )
            except JournalFileError as exc:
                raise self._error(
                    "GC result append failed", "plugin_package_gc_result_corrupt"
                ) from exc
            return proposed

    def _load_unlocked(self) -> tuple[PluginPackageGcAttemptV1, ...]:
        if not self._path.exists():
            return ()
        try:
            loaded: JsonlSnapshot[None, PluginPackageGcAttemptV1] = load_jsonl(
                self._path,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = loaded.records
            _assert_no_duplicate_json_keys(self._path)
            operations: set[str] = set()
            keys: set[str] = set()
            settled: set[tuple[str, str]] = set()
            settlement_owners: dict[str, str] = {}
            for revision, item in enumerate(records, start=1):
                target = (item.reservation_id, item.settlement_id)
                if (
                    item.record_revision != revision
                    or item.operation_id in operations
                    or item.idempotency_key in keys
                    or target in settled
                    or settlement_owners.setdefault(
                        item.settlement_id, item.reservation_id
                    ) != item.reservation_id
                ):
                    raise ValueError("GC result journal chain is invalid")
                operations.add(item.operation_id)
                keys.add(item.idempotency_key)
                if item.disposition == "succeeded":
                    settled.add(target)
            return records
        except (JournalCodecError, JournalFileError, TypeError, ValueError) as exc:
            raise self._error(
                "GC result journal is corrupt", "plugin_package_gc_result_corrupt"
            ) from exc

    def _error(self, message: str, code: str) -> PluginPackageGcResultError:
        return PluginPackageGcResultError(message, code=code, path=self._path)

    def _validate_start_records(
        self,
        records: tuple[PluginPackageGcAttemptV1, ...],
        start: PluginPackageGcDeletionStartV2,
    ) -> None:
        if any(
            item.reservation_id == start.reservation_id
            and (
                item.deletion_start_operation_id != start.operation_id
                or item.settlement_id not in start.target_settlement_ids
            )
            for item in records
        ):
            raise self._error(
                "GC result history disagrees with the deletion start",
                "plugin_package_gc_result_conflict",
            )


def _attempt_id(attempt: PluginPackageGcAttemptV1) -> str:
    values = [
        attempt.reservation_id,
        attempt.deletion_start_operation_id,
        attempt.settlement_id,
        attempt.operation_id,
        attempt.idempotency_key,
        attempt.disposition,
        None if attempt.store_result is None else attempt.store_result.to_dict(),
        attempt.error_code,
    ]
    return sha256(
        b"plugin-package-gc-attempt-v1\0"
        + json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Package GC integer is invalid")
    return value


def _string(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("Package GC string is invalid")
    return value


def _sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _assert_no_duplicate_json_keys(path: Path) -> None:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                json.loads(line, object_pairs_hook=_unique_json_object)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Package GC result has a duplicate JSON key")
        document[key] = value
    return document


__all__ = [
    "PluginPackageGcAttemptV1",
    "PluginPackageGcResultError",
    "PluginPackageGcResultJournal",
]
