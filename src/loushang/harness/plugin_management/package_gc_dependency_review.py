"""Durable review evidence for terminal dependency GC debt.

A review neither clears a terminal attempt nor authorizes a Store operation.
The Product must bind it to current references and a separate repair policy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal

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

from .package_gc_dependency_journal import (
    PackageDependencyGcAttemptV1,
    PackageDependencyGcStartV1,
)


def _text(value: object, *, name: str) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 256
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(f"Dependency GC {name} is invalid")
    return value


def _review_id(value: Mapping[str, object], *, version: int = 1) -> str:
    return sha256(
        f"package-dependency-gc-repair-review-v{version}\0".encode()
        + canonical_json_bytes(value)
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PackageDependencyGcRepairReviewV1:
    record_revision: int
    review_id: str
    start_id: str
    terminal_attempt_id: str
    store_id: str
    settlement_id: str
    reviewed_error_code: str
    actor_id: str
    policy_revision: str
    remediation_reference: str
    prior_repair_result_id: str | None = None
    record_kind: Literal["dependency_gc_repair_review"] = "dependency_gc_repair_review"
    record_version: int = 1

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Dependency GC repair review revision is invalid")
        for value, name in (
            (self.start_id, "start id"),
            (self.terminal_attempt_id, "terminal attempt id"),
            (self.store_id, "Store id"),
            (self.settlement_id, "settlement id"),
            (self.reviewed_error_code, "reviewed error code"),
            (self.actor_id, "actor id"),
            (self.policy_revision, "policy revision"),
            (self.remediation_reference, "remediation reference"),
        ):
            _text(value, name=name)
        if type(self.record_version) is not int:
            raise ValueError("Unsupported dependency GC repair review version")
        if self.record_version == 1:
            if self.prior_repair_result_id is not None:
                raise ValueError("Initial repair review cannot supersede a result")
        elif self.record_version == 2:
            if self.prior_repair_result_id is None:
                raise ValueError("Subsequent repair review needs the prior result")
            _text(self.prior_repair_result_id, name="prior repair result id")
            if len(self.prior_repair_result_id) != 64 or any(
                char not in "0123456789abcdef" for char in self.prior_repair_result_id
            ):
                raise ValueError("Prior dependency GC repair result ID is invalid")
        else:
            raise ValueError("Unsupported dependency GC repair review version")
        if (
            self.record_kind != "dependency_gc_repair_review"
            or self.review_id
            != _review_id(self._identity(), version=self.record_version)
        ):
            raise ValueError("Dependency GC repair review identity is invalid")

    @classmethod
    def create(
        cls,
        start: PackageDependencyGcStartV1,
        terminal_attempt: PackageDependencyGcAttemptV1,
        *,
        record_revision: int,
        actor_id: str,
        policy_revision: str,
        remediation_reference: str,
        prior_repair_result_id: str | None = None,
    ) -> PackageDependencyGcRepairReviewV1:
        if (
            not isinstance(start, PackageDependencyGcStartV1)
            or not isinstance(terminal_attempt, PackageDependencyGcAttemptV1)
            or terminal_attempt.start_id != start.start_id
            or terminal_attempt.disposition != "terminal_failure"
            or terminal_attempt.error_code is None
        ):
            raise ValueError("Exact terminal dependency GC attempt is required")
        identity = {
            "startId": start.start_id,
            "terminalAttemptId": terminal_attempt.attempt_id,
            "storeId": start.store_id,
            "settlementId": start.settlement_id,
            "reviewedErrorCode": terminal_attempt.error_code,
            "actorId": actor_id,
            "policyRevision": policy_revision,
            "remediationReference": remediation_reference,
        }
        record_version = 1 if prior_repair_result_id is None else 2
        if prior_repair_result_id is not None:
            identity["priorRepairResultId"] = prior_repair_result_id
        return cls(
            record_revision=record_revision,
            review_id=_review_id(identity, version=record_version),
            start_id=start.start_id,
            terminal_attempt_id=terminal_attempt.attempt_id,
            store_id=start.store_id,
            settlement_id=start.settlement_id,
            reviewed_error_code=terminal_attempt.error_code,
            actor_id=actor_id,
            policy_revision=policy_revision,
            remediation_reference=remediation_reference,
            prior_repair_result_id=prior_repair_result_id,
            record_version=record_version,
        )

    def _identity(self) -> dict[str, object]:
        identity: dict[str, object] = {
            "startId": self.start_id,
            "terminalAttemptId": self.terminal_attempt_id,
            "storeId": self.store_id,
            "settlementId": self.settlement_id,
            "reviewedErrorCode": self.reviewed_error_code,
            "actorId": self.actor_id,
            "policyRevision": self.policy_revision,
            "remediationReference": self.remediation_reference,
        }
        if self.record_version == 2:
            identity["priorRepairResultId"] = self.prior_repair_result_id
        return identity

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity(),
            "recordRevision": self.record_revision,
            "reviewId": self.review_id,
            "recordKind": self.record_kind,
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageDependencyGcRepairReviewV1:
        fields = {
            "recordRevision",
            "reviewId",
            "startId",
            "terminalAttemptId",
            "storeId",
            "settlementId",
            "reviewedErrorCode",
            "actorId",
            "policyRevision",
            "remediationReference",
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
            raise JournalCodecError(
                "Dependency GC repair review fields are invalid",
                code="invalid_package_dependency_gc_repair_review",
            )
        try:
            return cls(
                record_revision=value["recordRevision"],
                review_id=value["reviewId"],
                start_id=value["startId"],
                terminal_attempt_id=value["terminalAttemptId"],
                store_id=value["storeId"],
                settlement_id=value["settlementId"],
                reviewed_error_code=value["reviewedErrorCode"],
                actor_id=value["actorId"],
                policy_revision=value["policyRevision"],
                remediation_reference=value["remediationReference"],
                prior_repair_result_id=value.get("priorRepairResultId"),
                record_kind=value["recordKind"],
                record_version=value["recordVersion"],
            )
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Dependency GC repair review is invalid",
                code="invalid_package_dependency_gc_repair_review",
            ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=PackageDependencyGcRepairReviewV1.to_dict,
    decoder=PackageDependencyGcRepairReviewV1.from_dict,
)


class PackageDependencyGcRepairReviewJournal:
    """Append immutable reviews, linking each new review to prior repair debt."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    def records(self) -> tuple[PackageDependencyGcRepairReviewV1, ...]:
        with journal_file_lock(self._path, "exclusive"):
            return self._load()

    def record(
        self,
        start: PackageDependencyGcStartV1,
        terminal_attempt: PackageDependencyGcAttemptV1,
        *,
        actor_id: str,
        policy_revision: str,
        remediation_reference: str,
        prior_repair_result_id: str | None = None,
    ) -> PackageDependencyGcRepairReviewV1:
        with journal_file_lock(self._path, "exclusive"):
            records = self._load()
            proposed = PackageDependencyGcRepairReviewV1.create(
                start,
                terminal_attempt,
                record_revision=len(records) + 1,
                actor_id=actor_id,
                policy_revision=policy_revision,
                remediation_reference=remediation_reference,
                prior_repair_result_id=prior_repair_result_id,
            )
            prior = next(
                (item for item in records if item.review_id == proposed.review_id), None
            )
            if prior is not None:
                return prior
            existing = tuple(
                item for item in records if item.start_id == start.start_id
            )
            if (
                (not existing and prior_repair_result_id is not None)
                or (existing and prior_repair_result_id is None)
            ):
                raise ValueError("Dependency GC repair review changed")
            append_jsonl_record(
                self._path,
                proposed,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
            )
            return proposed

    def _load(self) -> tuple[PackageDependencyGcRepairReviewV1, ...]:
        if not self._path.exists():
            return ()
        snapshot: JsonlSnapshot[None, PackageDependencyGcRepairReviewV1] = load_jsonl(
            self._path,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            load_policy=self._load_policy,
        )
        records = snapshot.records
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line, object_pairs_hook=_unique_json_object)
        latest: dict[str, PackageDependencyGcRepairReviewV1] = {}
        seen_ids: set[str] = set()
        for revision, item in enumerate(records, 1):
            prior = latest.get(item.start_id)
            if (
                item.record_revision != revision
                or item.review_id in seen_ids
                or (prior is None and item.record_version != 1)
                or (prior is not None and item.record_version != 2)
                or (
                    prior is not None
                    and prior.prior_repair_result_id == item.prior_repair_result_id
                )
            ):
                raise ValueError("Dependency GC repair review journal is inconsistent")
            latest[item.start_id] = item
            seen_ids.add(item.review_id)
        return records


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Dependency GC repair review has a duplicate JSON key")
        result[key] = value
    return result


__all__ = [
    "PackageDependencyGcRepairReviewJournal",
    "PackageDependencyGcRepairReviewV1",
]
