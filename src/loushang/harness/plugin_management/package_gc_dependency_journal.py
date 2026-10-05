"""Durable exact-start and result evidence for dependency Store GC.

Only a Product owner may decide that a dependency has no live holders. This
journal records that owner's exact deletion target before Store effects and
the Store's result afterward; it grants no deletion authority by itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeAlias

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_gc import (
    PackageStoreGcResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementRecordV1,
)

from .package_gc_dependencies import PackageDependencyGcTargetV1


class PackageDependencyGcJournalError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageDependencyGcStartV1:
    journal_revision: int
    start_id: str
    store_id: str
    dependency_ref_id: str
    settlement_id: str
    publisher_set_id: str
    holder_root_ref_ids: tuple[str, ...]
    record_kind: Literal["dependency_gc_start"] = "dependency_gc_start"
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or not self.store_id
            or not self.publisher_set_id
            or not self.holder_root_ref_ids
            or self.holder_root_ref_ids != tuple(sorted(set(self.holder_root_ref_ids)))
            or self.record_kind != "dependency_gc_start"
            or self.record_version != 1
            or self.start_id != _start_id(self)
        ):
            raise ValueError("Dependency GC start is invalid")

    @classmethod
    def create(
        cls,
        target: PackageDependencyGcTargetV1,
        *,
        store_id: str,
        journal_revision: int,
    ) -> PackageDependencyGcStartV1:
        values = {
            "storeId": store_id,
            "dependencyRefId": target.retention.dependency_ref.ref_id,
            "settlementId": target.settlement_id,
            "publisherSetId": target.publisher_set_id,
            "holderRootRefIds": list(target.retention.holder_root_ref_ids),
        }
        return cls(
            journal_revision=journal_revision,
            start_id=_fingerprint("package-dependency-gc-start-v1", values),
            store_id=store_id,
            dependency_ref_id=target.retention.dependency_ref.ref_id,
            settlement_id=target.settlement_id,
            publisher_set_id=target.publisher_set_id,
            holder_root_ref_ids=target.retention.holder_root_ref_ids,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "journalRevision": self.journal_revision,
            "startId": self.start_id,
            "storeId": self.store_id,
            "dependencyRefId": self.dependency_ref_id,
            "settlementId": self.settlement_id,
            "publisherSetId": self.publisher_set_id,
            "holderRootRefIds": list(self.holder_root_ref_ids),
            "recordKind": self.record_kind,
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageDependencyGcStartV1:
        item = _exact(
            value,
            {
                "journalRevision",
                "startId",
                "storeId",
                "dependencyRefId",
                "settlementId",
                "publisherSetId",
                "holderRootRefIds",
                "recordKind",
                "recordVersion",
            },
        )
        holders = item["holderRootRefIds"]
        if type(holders) is not list:
            raise ValueError("Dependency GC holders are invalid")
        return cls(
            journal_revision=_int(item["journalRevision"]),
            start_id=_str(item["startId"]),
            store_id=_str(item["storeId"]),
            dependency_ref_id=_str(item["dependencyRefId"]),
            settlement_id=_str(item["settlementId"]),
            publisher_set_id=_str(item["publisherSetId"]),
            holder_root_ref_ids=tuple(_str(holder) for holder in holders),
            record_kind=item["recordKind"],  # type: ignore[arg-type]
            record_version=_int(item["recordVersion"]),
        )


@dataclass(frozen=True, slots=True)
class PackageDependencyGcAttemptV1:
    journal_revision: int
    attempt_id: str
    start_id: str
    operation_id: str
    idempotency_key: str
    disposition: Literal["succeeded", "retryable_failure", "terminal_failure"]
    store_result: PackageStoreGcResultV1 | None
    error_code: str | None
    record_kind: Literal["dependency_gc_attempt"] = "dependency_gc_attempt"
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 2
            or not self.operation_id
            or not self.idempotency_key
            or self.record_kind != "dependency_gc_attempt"
            or self.record_version != 1
            or self.disposition
            not in {"succeeded", "retryable_failure", "terminal_failure"}
            or self.attempt_id != _attempt_id(self)
        ):
            raise ValueError("Dependency GC attempt is invalid")
        if self.disposition == "succeeded":
            if self.store_result is None or self.error_code is not None:
                raise ValueError("Dependency GC success requires a Store result")
        elif self.store_result is not None or not self.error_code:
            raise ValueError("Dependency GC failure requires an error code")

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        start: PackageDependencyGcStartV1,
        operation_id: str,
        idempotency_key: str,
        store_result: PackageStoreGcResultV1 | None = None,
        error_code: str | None = None,
        terminal: bool = False,
    ) -> PackageDependencyGcAttemptV1:
        if type(terminal) is not bool or (terminal and store_result is not None):
            raise ValueError("Dependency GC terminal disposition is invalid")
        disposition: Literal["succeeded", "retryable_failure", "terminal_failure"] = (
            "succeeded"
            if store_result is not None
            else "terminal_failure"
            if terminal
            else "retryable_failure"
        )
        values = {
            "startId": start.start_id,
            "operationId": operation_id,
            "idempotencyKey": idempotency_key,
            "disposition": disposition,
            "storeResult": None if store_result is None else store_result.to_dict(),
            "errorCode": error_code,
        }
        return cls(
            journal_revision=journal_revision,
            attempt_id=_fingerprint("package-dependency-gc-attempt-v1", values),
            start_id=start.start_id,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            disposition=disposition,
            store_result=store_result,
            error_code=error_code,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "journalRevision": self.journal_revision,
            "attemptId": self.attempt_id,
            "startId": self.start_id,
            "operationId": self.operation_id,
            "idempotencyKey": self.idempotency_key,
            "disposition": self.disposition,
            "storeResult": None
            if self.store_result is None
            else self.store_result.to_dict(),
            "errorCode": self.error_code,
            "recordKind": self.record_kind,
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageDependencyGcAttemptV1:
        item = _exact(
            value,
            {
                "journalRevision",
                "attemptId",
                "startId",
                "operationId",
                "idempotencyKey",
                "disposition",
                "storeResult",
                "errorCode",
                "recordKind",
                "recordVersion",
            },
        )
        result = item["storeResult"]
        return cls(
            journal_revision=_int(item["journalRevision"]),
            attempt_id=_str(item["attemptId"]),
            start_id=_str(item["startId"]),
            operation_id=_str(item["operationId"]),
            idempotency_key=_str(item["idempotencyKey"]),
            disposition=item["disposition"],  # type: ignore[arg-type]
            store_result=None
            if result is None
            else PackageStoreGcResultV1.from_dict(result),
            error_code=None if item["errorCode"] is None else _str(item["errorCode"]),
            record_kind=item["recordKind"],  # type: ignore[arg-type]
            record_version=_int(item["recordVersion"]),
        )


DependencyGcEvent: TypeAlias = PackageDependencyGcStartV1 | PackageDependencyGcAttemptV1


def _decode(value: object) -> DependencyGcEvent:
    try:
        if type(value) is not dict:
            raise ValueError("Dependency GC record is not an object")
        if value.get("recordKind") == "dependency_gc_start":
            return PackageDependencyGcStartV1.from_dict(value)
        if value.get("recordKind") == "dependency_gc_attempt":
            return PackageDependencyGcAttemptV1.from_dict(value)
        raise ValueError("Dependency GC record kind is invalid")
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Dependency GC journal record is invalid",
            code="invalid_package_dependency_gc_record",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=lambda item: item.to_dict(), decoder=_decode
)


class PackageDependencyGcJournal:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    def events(self) -> tuple[DependencyGcEvent, ...]:
        with journal_file_lock(self._path, "exclusive"):
            return self._load()

    def begin(
        self, target: PackageDependencyGcTargetV1, *, store_id: str
    ) -> PackageDependencyGcStartV1:
        if not isinstance(target, PackageDependencyGcTargetV1):
            raise TypeError("Exact dependency GC target is required")
        if not isinstance(store_id, str) or not store_id:
            raise ValueError("Package Store identity is required")
        with journal_file_lock(self._path, "exclusive"):
            events = self._load()
            proposed = PackageDependencyGcStartV1.create(
                target, store_id=store_id, journal_revision=len(events) + 1
            )
            prior = tuple(
                item
                for item in events
                if isinstance(item, PackageDependencyGcStartV1)
                and item.dependency_ref_id == proposed.dependency_ref_id
            )
            if prior:
                if len(prior) != 1 or prior[0].start_id != proposed.start_id:
                    raise PackageDependencyGcJournalError(
                        "Dependency GC target changed after start",
                        code="plugin_package_gc_dependency_start_conflict",
                    )
                return prior[0]
            self._append(proposed)
            return proposed

    def preflight(
        self,
        start: PackageDependencyGcStartV1,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> PackageDependencyGcAttemptV1 | None:
        with journal_file_lock(self._path, "exclusive"):
            events = self._load()
            self._require_start(events, start)
            attempts = tuple(
                item
                for item in events
                if isinstance(item, PackageDependencyGcAttemptV1)
            )
            by_operation = next(
                (item for item in attempts if item.operation_id == operation_id), None
            )
            by_key = next(
                (item for item in attempts if item.idempotency_key == idempotency_key),
                None,
            )
            if by_operation != by_key or (
                by_operation is not None and by_operation.start_id != start.start_id
            ):
                raise PackageDependencyGcJournalError(
                    "Dependency GC attempt identity was reused",
                    code="plugin_package_gc_dependency_attempt_conflict",
                )
            if by_operation is not None:
                return by_operation
            completed = next(
                (
                    item
                    for item in attempts
                    if item.start_id == start.start_id
                    and item.disposition in {"succeeded", "terminal_failure"}
                ),
                None,
            )
            return completed

    def record(
        self,
        start: PackageDependencyGcStartV1,
        *,
        settlement: PackageStoreSettlementRecordV1,
        operation_id: str,
        idempotency_key: str,
        store_result: PackageStoreGcResultV1 | None = None,
        error_code: str | None = None,
        terminal: bool = False,
    ) -> PackageDependencyGcAttemptV1:
        if (
            settlement.settlement_id != start.settlement_id
            or settlement.receipt.stable_ref.ref_id != start.dependency_ref_id
            or (
                store_result is not None
                and store_result
                != PackageStoreGcResultV1.create(
                    settlement, disposition=store_result.disposition
                )
            )
        ):
            raise PackageDependencyGcJournalError(
                "Dependency GC result changed its exact Store target",
                code="plugin_package_gc_dependency_result_mismatch",
            )
        with journal_file_lock(self._path, "exclusive"):
            events = self._load()
            self._require_start(events, start)
            proposed = PackageDependencyGcAttemptV1.create(
                journal_revision=len(events) + 1,
                start=start,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                store_result=store_result,
                error_code=error_code,
                terminal=terminal,
            )
            attempts = tuple(
                item
                for item in events
                if isinstance(item, PackageDependencyGcAttemptV1)
            )
            by_operation = next(
                (item for item in attempts if item.operation_id == operation_id), None
            )
            by_key = next(
                (item for item in attempts if item.idempotency_key == idempotency_key),
                None,
            )
            if by_operation != by_key:
                raise PackageDependencyGcJournalError(
                    "Dependency GC attempt identities diverge",
                    code="plugin_package_gc_dependency_attempt_conflict",
                )
            if by_operation is not None:
                if (
                    by_operation.attempt_id != proposed.attempt_id
                    or by_operation.start_id != start.start_id
                ):
                    raise PackageDependencyGcJournalError(
                        "Dependency GC attempt identity was reused",
                        code="plugin_package_gc_dependency_attempt_conflict",
                    )
                return by_operation
            if any(
                item.start_id == start.start_id
                and item.disposition in {"succeeded", "terminal_failure"}
                for item in attempts
            ):
                raise PackageDependencyGcJournalError(
                    "Dependency GC already has a terminal disposition",
                    code="plugin_package_gc_dependency_already_settled",
                )
            self._append(proposed)
            return proposed

    def _load(self) -> tuple[DependencyGcEvent, ...]:
        if not self._path.exists():
            return ()
        snapshot: JsonlSnapshot[None, DependencyGcEvent] = load_jsonl(
            self._path,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            load_policy=self._load_policy,
        )
        events: tuple[DependencyGcEvent, ...] = snapshot.records
        starts: dict[str, PackageDependencyGcStartV1] = {}
        attempts: set[str] = set()
        operation_ids: set[str] = set()
        idempotency_keys: set[str] = set()
        completed_starts: set[str] = set()
        for index, event in enumerate(events, 1):
            if event.journal_revision != index:
                raise PackageDependencyGcJournalError(
                    "Dependency GC journal revision changed",
                    code="plugin_package_gc_dependency_journal_corrupt",
                )
            if isinstance(event, PackageDependencyGcStartV1):
                if event.start_id in starts or any(
                    prior.dependency_ref_id == event.dependency_ref_id
                    for prior in starts.values()
                ):
                    raise PackageDependencyGcJournalError(
                        "Dependency GC start is duplicated",
                        code="plugin_package_gc_dependency_journal_corrupt",
                    )
                starts[event.start_id] = event
            else:
                start = starts.get(event.start_id)
                if (
                    start is None
                    or event.attempt_id in attempts
                    or event.operation_id in operation_ids
                    or event.idempotency_key in idempotency_keys
                    or event.start_id in completed_starts
                    or (
                        event.store_result is not None
                        and (
                            event.store_result.settlement_id != start.settlement_id
                            or event.store_result.stable_ref_id
                            != start.dependency_ref_id
                        )
                    )
                ):
                    raise PackageDependencyGcJournalError(
                        "Dependency GC attempt changed its exact start",
                        code="plugin_package_gc_dependency_journal_corrupt",
                    )
                attempts.add(event.attempt_id)
                operation_ids.add(event.operation_id)
                idempotency_keys.add(event.idempotency_key)
                if event.disposition in {"succeeded", "terminal_failure"}:
                    completed_starts.add(event.start_id)
        return events

    def _require_start(
        self, events: tuple[DependencyGcEvent, ...], start: PackageDependencyGcStartV1
    ) -> None:
        if start not in events:
            raise PackageDependencyGcJournalError(
                "Dependency GC start is unavailable",
                code="plugin_package_gc_dependency_start_unavailable",
            )

    def _append(self, event: DependencyGcEvent) -> None:
        append_jsonl_record(
            self._path,
            event,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
        )


def _start_id(value: PackageDependencyGcStartV1) -> str:
    return _fingerprint(
        "package-dependency-gc-start-v1",
        {
            "storeId": value.store_id,
            "dependencyRefId": value.dependency_ref_id,
            "settlementId": value.settlement_id,
            "publisherSetId": value.publisher_set_id,
            "holderRootRefIds": list(value.holder_root_ref_ids),
        },
    )


def _attempt_id(value: PackageDependencyGcAttemptV1) -> str:
    return _fingerprint(
        "package-dependency-gc-attempt-v1",
        {
            "startId": value.start_id,
            "operationId": value.operation_id,
            "idempotencyKey": value.idempotency_key,
            "disposition": value.disposition,
            "storeResult": None
            if value.store_result is None
            else value.store_result.to_dict(),
            "errorCode": value.error_code,
        },
    )


def _fingerprint(namespace: str, value: Mapping[str, object]) -> str:
    return sha256(
        namespace.encode("ascii") + b"\0" + canonical_json_bytes(value)
    ).hexdigest()


def _exact(value: object, fields: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Dependency GC record fields are invalid")
    return value


def _str(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Dependency GC record identity is invalid")
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Dependency GC record revision is invalid")
    return value


__all__ = [
    "PackageDependencyGcAttemptV1",
    "PackageDependencyGcJournal",
    "PackageDependencyGcJournalError",
    "PackageDependencyGcStartV1",
]
