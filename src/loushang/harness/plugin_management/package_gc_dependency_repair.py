"""Separate durable attempt lineage for reviewed terminal dependency GC debt."""

from __future__ import annotations

import json
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

from .package_gc_dependency_review import PackageDependencyGcRepairReviewV1


class PackageDependencyGcRepairJournalError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _fingerprint(namespace: bytes, value: Mapping[str, object]) -> str:
    return sha256(namespace + b"\0" + canonical_json_bytes(value)).hexdigest()


def _text(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 256
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Dependency GC repair identity is invalid")
    return value


@dataclass(frozen=True, slots=True)
class PackageDependencyGcRepairStartV1:
    journal_revision: int
    repair_start_id: str
    review_id: str
    dependency_start_id: str
    terminal_attempt_id: str
    store_id: str
    settlement_id: str
    operation_id: str
    idempotency_key: str
    prior_repair_result_id: str | None = None
    record_kind: Literal["dependency_gc_repair_start"] = "dependency_gc_repair_start"
    record_version: int = 1

    def __post_init__(self) -> None:
        if type(self.journal_revision) is not int or self.journal_revision < 1:
            raise ValueError("Dependency GC repair start revision is invalid")
        for value in self._identity().values():
            if value is not None:
                _text(value)
        if (
            type(self.record_version) is not int
            or (self.record_version == 1 and self.prior_repair_result_id is not None)
            or (self.record_version == 2 and self.prior_repair_result_id is None)
            or self.record_version not in {1, 2}
        ):
            raise ValueError("Dependency GC repair start version is invalid")
        if (
            self.record_kind != "dependency_gc_repair_start"
            or self.repair_start_id
            != _fingerprint(
                f"package-dependency-gc-repair-start-v{self.record_version}".encode(),
                self._identity(),
            )
        ):
            raise ValueError("Dependency GC repair start is invalid")

    @classmethod
    def create(
        cls,
        review: PackageDependencyGcRepairReviewV1,
        *,
        journal_revision: int,
        operation_id: str,
        idempotency_key: str,
    ) -> PackageDependencyGcRepairStartV1:
        if not isinstance(review, PackageDependencyGcRepairReviewV1):
            raise TypeError("Exact dependency GC repair review is required")
        identity = {
            "reviewId": review.review_id,
            "dependencyStartId": review.start_id,
            "terminalAttemptId": review.terminal_attempt_id,
            "storeId": review.store_id,
            "settlementId": review.settlement_id,
            "operationId": operation_id,
            "idempotencyKey": idempotency_key,
        }
        if review.prior_repair_result_id is not None:
            identity["priorRepairResultId"] = review.prior_repair_result_id
        record_version = review.record_version
        return cls(
            journal_revision=journal_revision,
            repair_start_id=_fingerprint(
                f"package-dependency-gc-repair-start-v{record_version}".encode(),
                identity,
            ),
            review_id=review.review_id,
            dependency_start_id=review.start_id,
            terminal_attempt_id=review.terminal_attempt_id,
            store_id=review.store_id,
            settlement_id=review.settlement_id,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            prior_repair_result_id=review.prior_repair_result_id,
            record_version=record_version,
        )

    def _identity(self) -> dict[str, object]:
        identity: dict[str, object] = {
            "reviewId": self.review_id,
            "dependencyStartId": self.dependency_start_id,
            "terminalAttemptId": self.terminal_attempt_id,
            "storeId": self.store_id,
            "settlementId": self.settlement_id,
            "operationId": self.operation_id,
            "idempotencyKey": self.idempotency_key,
        }
        if self.record_version == 2:
            identity["priorRepairResultId"] = self.prior_repair_result_id
        return identity

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity(),
            "journalRevision": self.journal_revision,
            "repairStartId": self.repair_start_id,
            "recordKind": self.record_kind,
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageDependencyGcRepairStartV1:
        fields = {
            "journalRevision",
            "repairStartId",
            "reviewId",
            "dependencyStartId",
            "terminalAttemptId",
            "storeId",
            "settlementId",
            "operationId",
            "idempotencyKey",
            "recordKind",
            "recordVersion",
        }
        if type(value) is not dict or (
            (value.get("recordVersion") == 1 and set(value) != fields)
            or (
                value.get("recordVersion") == 2
                and set(value) != fields | {"priorRepairResultId"}
            )
            or value.get("recordVersion") not in {1, 2}
        ):
            raise ValueError("Dependency GC repair start fields are invalid")
        return cls(
            journal_revision=value["journalRevision"],
            repair_start_id=value["repairStartId"],
            review_id=value["reviewId"],
            dependency_start_id=value["dependencyStartId"],
            terminal_attempt_id=value["terminalAttemptId"],
            store_id=value["storeId"],
            settlement_id=value["settlementId"],
            operation_id=value["operationId"],
            idempotency_key=value["idempotencyKey"],
            prior_repair_result_id=value.get("priorRepairResultId"),
            record_kind=value["recordKind"],
            record_version=value["recordVersion"],
        )


@dataclass(frozen=True, slots=True)
class PackageDependencyGcRepairResultV1:
    journal_revision: int
    repair_result_id: str
    repair_start_id: str
    disposition: Literal["succeeded", "terminal_failure"]
    store_result: PackageStoreGcResultV1 | None
    error_code: str | None
    record_kind: Literal["dependency_gc_repair_result"] = "dependency_gc_repair_result"
    record_version: int = 1

    def __post_init__(self) -> None:
        if type(self.journal_revision) is not int or self.journal_revision < 2:
            raise ValueError("Dependency GC repair result revision is invalid")
        _text(self.repair_start_id)
        if self.disposition == "succeeded":
            if self.store_result is None or self.error_code is not None:
                raise ValueError("Dependency GC repair success needs Store proof")
        elif self.disposition == "terminal_failure":
            if self.store_result is not None or self.error_code is None:
                raise ValueError("Dependency GC repair failure needs an error code")
            _text(self.error_code)
        else:
            raise ValueError("Dependency GC repair disposition is invalid")
        if (
            self.record_kind != "dependency_gc_repair_result"
            or self.record_version != 1
            or self.repair_result_id
            != _fingerprint(b"package-dependency-gc-repair-result-v1", self._identity())
        ):
            raise ValueError("Dependency GC repair result is invalid")

    @classmethod
    def create(
        cls,
        start: PackageDependencyGcRepairStartV1,
        *,
        journal_revision: int,
        store_result: PackageStoreGcResultV1 | None = None,
        error_code: str | None = None,
    ) -> PackageDependencyGcRepairResultV1:
        if not isinstance(start, PackageDependencyGcRepairStartV1):
            raise TypeError("Exact dependency GC repair start is required")
        disposition: Literal["succeeded", "terminal_failure"] = (
            "succeeded" if store_result is not None else "terminal_failure"
        )
        identity = {
            "repairStartId": start.repair_start_id,
            "disposition": disposition,
            "storeResult": None if store_result is None else store_result.to_dict(),
            "errorCode": error_code,
        }
        return cls(
            journal_revision=journal_revision,
            repair_result_id=_fingerprint(
                b"package-dependency-gc-repair-result-v1", identity
            ),
            repair_start_id=start.repair_start_id,
            disposition=disposition,
            store_result=store_result,
            error_code=error_code,
        )

    def _identity(self) -> dict[str, object]:
        return {
            "repairStartId": self.repair_start_id,
            "disposition": self.disposition,
            "storeResult": None
            if self.store_result is None
            else self.store_result.to_dict(),
            "errorCode": self.error_code,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity(),
            "journalRevision": self.journal_revision,
            "repairResultId": self.repair_result_id,
            "recordKind": self.record_kind,
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageDependencyGcRepairResultV1:
        if type(value) is not dict or set(value) != {
            "journalRevision",
            "repairResultId",
            "repairStartId",
            "disposition",
            "storeResult",
            "errorCode",
            "recordKind",
            "recordVersion",
        }:
            raise ValueError("Dependency GC repair result fields are invalid")
        result = value["storeResult"]
        return cls(
            journal_revision=value["journalRevision"],
            repair_result_id=value["repairResultId"],
            repair_start_id=value["repairStartId"],
            disposition=value["disposition"],
            store_result=None
            if result is None
            else PackageStoreGcResultV1.from_dict(result),
            error_code=value["errorCode"],
            record_kind=value["recordKind"],
            record_version=value["recordVersion"],
        )


RepairEvent: TypeAlias = (
    PackageDependencyGcRepairStartV1 | PackageDependencyGcRepairResultV1
)


def _decode(value: object) -> RepairEvent:
    try:
        if type(value) is not dict:
            raise ValueError("Dependency GC repair record is invalid")
        if value.get("recordKind") == "dependency_gc_repair_start":
            return PackageDependencyGcRepairStartV1.from_dict(value)
        if value.get("recordKind") == "dependency_gc_repair_result":
            return PackageDependencyGcRepairResultV1.from_dict(value)
        raise ValueError("Dependency GC repair record kind is invalid")
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Dependency GC repair record is invalid",
            code="invalid_package_dependency_gc_repair_record",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=lambda item: item.to_dict(), decoder=_decode
)


class PackageDependencyGcRepairJournal:
    """Replay each reviewed Store attempt without rewriting earlier debt."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    def events(self) -> tuple[RepairEvent, ...]:
        with journal_file_lock(self._path, "exclusive"):
            return self._load()

    def begin(
        self,
        review: PackageDependencyGcRepairReviewV1,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> PackageDependencyGcRepairStartV1:
        if not isinstance(review, PackageDependencyGcRepairReviewV1):
            raise TypeError("Exact dependency GC repair review is required")
        with journal_file_lock(self._path, "exclusive"):
            events = self._load()
            same_review = next(
                (
                    item
                    for item in events
                    if isinstance(item, PackageDependencyGcRepairStartV1)
                    and item.review_id == review.review_id
                ),
                None,
            )
            previous = next(
                (
                    item
                    for item in reversed(events)
                    if isinstance(item, PackageDependencyGcRepairStartV1)
                    and item.dependency_start_id == review.start_id
                ),
                None,
            )
            proposed = PackageDependencyGcRepairStartV1.create(
                review,
                journal_revision=(
                    len(events) + 1
                    if same_review is None
                    else same_review.journal_revision
                ),
                operation_id=operation_id,
                idempotency_key=idempotency_key,
            )
            if same_review is not None:
                if same_review != proposed:
                    raise PackageDependencyGcRepairJournalError(
                        "Dependency GC repair start changed",
                        code="plugin_package_gc_dependency_repair_start_conflict",
                    )
                return same_review
            previous_result = next(
                (
                    item
                    for item in events
                    if isinstance(item, PackageDependencyGcRepairResultV1)
                    and previous is not None
                    and item.repair_start_id == previous.repair_start_id
                ),
                None,
            )
            if (previous is None and review.prior_repair_result_id is not None) or (
                previous is not None
                and (
                    previous_result is None
                    or previous_result.disposition != "terminal_failure"
                    or review.prior_repair_result_id != previous_result.repair_result_id
                    or previous.settlement_id != review.settlement_id
                    or previous.store_id != review.store_id
                )
            ):
                raise PackageDependencyGcRepairJournalError(
                    "Dependency GC repair review has no terminal predecessor",
                    code="plugin_package_gc_dependency_repair_start_conflict",
                )
            append_jsonl_record(
                self._path,
                proposed,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
            )
            return proposed

    def result_for(
        self, start: PackageDependencyGcRepairStartV1
    ) -> PackageDependencyGcRepairResultV1 | None:
        with journal_file_lock(self._path, "exclusive"):
            events = self._load()
            self._require_start(events, start)
            return next(
                (
                    item
                    for item in events
                    if isinstance(item, PackageDependencyGcRepairResultV1)
                    and item.repair_start_id == start.repair_start_id
                ),
                None,
            )

    def record(
        self,
        start: PackageDependencyGcRepairStartV1,
        *,
        settlement: PackageStoreSettlementRecordV1,
        store_result: PackageStoreGcResultV1 | None = None,
        error_code: str | None = None,
    ) -> PackageDependencyGcRepairResultV1:
        if settlement.settlement_id != start.settlement_id or (
            store_result is not None
            and store_result
            != PackageStoreGcResultV1.create(
                settlement, disposition=store_result.disposition
            )
        ):
            raise PackageDependencyGcRepairJournalError(
                "Dependency GC repair changed its Store target",
                code="plugin_package_gc_dependency_repair_result_mismatch",
            )
        with journal_file_lock(self._path, "exclusive"):
            events = self._load()
            self._require_start(events, start)
            prior = next(
                (
                    item
                    for item in events
                    if isinstance(item, PackageDependencyGcRepairResultV1)
                    and item.repair_start_id == start.repair_start_id
                ),
                None,
            )
            proposed = PackageDependencyGcRepairResultV1.create(
                start,
                journal_revision=(
                    len(events) + 1 if prior is None else prior.journal_revision
                ),
                store_result=store_result,
                error_code=error_code,
            )
            if prior is not None:
                if prior != proposed:
                    raise PackageDependencyGcRepairJournalError(
                        "Dependency GC repair result changed",
                        code="plugin_package_gc_dependency_repair_result_conflict",
                    )
                return prior
            append_jsonl_record(
                self._path,
                proposed,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
            )
            return proposed

    def _load(self) -> tuple[RepairEvent, ...]:
        if not self._path.exists():
            return ()
        snapshot: JsonlSnapshot[None, RepairEvent] = load_jsonl(
            self._path,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            load_policy=self._load_policy,
        )
        events = snapshot.records
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line, object_pairs_hook=_unique_json_object)
        starts: dict[str, PackageDependencyGcRepairStartV1] = {}
        starts_by_id: dict[str, PackageDependencyGcRepairStartV1] = {}
        starts_by_review: set[str] = set()
        operation_ids: set[str] = set()
        idempotency_keys: set[str] = set()
        results: set[str] = set()
        results_by_start: dict[str, PackageDependencyGcRepairResultV1] = {}
        for revision, event in enumerate(events, 1):
            if event.journal_revision != revision:
                raise PackageDependencyGcRepairJournalError(
                    "Dependency GC repair revision changed",
                    code="plugin_package_gc_dependency_repair_journal_corrupt",
                )
            if isinstance(event, PackageDependencyGcRepairStartV1):
                prior_start = starts.get(event.dependency_start_id)
                prior_result = (
                    None
                    if prior_start is None
                    else results_by_start.get(prior_start.repair_start_id)
                )
                if (
                    event.repair_start_id in starts_by_id
                    or event.review_id in starts_by_review
                    or event.operation_id in operation_ids
                    or event.idempotency_key in idempotency_keys
                    or (
                        prior_start is None and event.prior_repair_result_id is not None
                    )
                    or (
                        prior_start is not None
                        and (
                            prior_result is None
                            or prior_result.disposition != "terminal_failure"
                            or event.prior_repair_result_id
                            != prior_result.repair_result_id
                            or event.settlement_id != prior_start.settlement_id
                            or event.store_id != prior_start.store_id
                        )
                    )
                ):
                    raise PackageDependencyGcRepairJournalError(
                        "Dependency GC repair start was duplicated",
                        code="plugin_package_gc_dependency_repair_journal_corrupt",
                    )
                starts[event.dependency_start_id] = event
                starts_by_id[event.repair_start_id] = event
                starts_by_review.add(event.review_id)
                operation_ids.add(event.operation_id)
                idempotency_keys.add(event.idempotency_key)
            elif (
                event.repair_start_id not in starts_by_id
                or event.repair_start_id in results
                or (
                    event.store_result is not None
                    and (
                        event.store_result.settlement_id
                        != starts_by_id[event.repair_start_id].settlement_id
                    )
                )
            ):
                raise PackageDependencyGcRepairJournalError(
                    "Dependency GC repair result has no unique start",
                    code="plugin_package_gc_dependency_repair_journal_corrupt",
                )
            else:
                results.add(event.repair_start_id)
                results_by_start[event.repair_start_id] = event
        return events

    @staticmethod
    def _require_start(
        events: tuple[RepairEvent, ...], start: PackageDependencyGcRepairStartV1
    ) -> None:
        if start not in events:
            raise PackageDependencyGcRepairJournalError(
                "Dependency GC repair start is unavailable",
                code="plugin_package_gc_dependency_repair_start_unavailable",
            )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Dependency GC repair has a duplicate JSON key")
        result[key] = value
    return result


__all__ = [
    "PackageDependencyGcRepairJournal",
    "PackageDependencyGcRepairJournalError",
    "PackageDependencyGcRepairResultV1",
    "PackageDependencyGcRepairStartV1",
]
