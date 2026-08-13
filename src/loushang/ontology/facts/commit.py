"""Pure planning and selection services shared by FactStore adapters."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from loushang.ontology.facts.model import FactBatch, FactRecord, FactValidationError
from loushang.ontology.facts.ports import (
    FactBatchConflictError,
    FactCommit,
    FactWatermarkConflictError,
    StoredFact,
)


@dataclass(frozen=True, slots=True)
class CommittedFactBatch:
    """Persistable idempotency metadata for one committed fact batch."""

    digest: str
    commit: FactCommit


@dataclass(frozen=True, slots=True)
class PreparedFactCommit:
    """Validated adapter-neutral instructions for one atomic commit."""

    batch: FactBatch
    digest: str
    entries: tuple[StoredFact, ...]
    commit: FactCommit


def prepare_fact_commit(
    batch: FactBatch,
    *,
    current_facts: Iterable[StoredFact],
    committed_batches: Mapping[str, CommittedFactBatch],
) -> PreparedFactCommit:
    """Validate a batch against a snapshot without changing adapter state."""

    if not isinstance(batch, FactBatch):
        raise FactValidationError("commit_fact_batch requires a FactBatch")
    existing_entries = tuple(current_facts)
    validate_fact_journal(existing_entries, committed_batches)
    existing_identities = {item.fact.schema_identity for item in existing_entries}
    if existing_identities and batch.schema_identity not in existing_identities:
        raise FactValidationError(
            "FactStore cannot mix complete schema identities in one journal"
        )
    digest = batch.content_digest
    existing_batch = committed_batches.get(batch.batch_id)
    if existing_batch is not None:
        if existing_batch.digest != digest:
            raise FactBatchConflictError(
                f"Fact batch '{batch.batch_id}' was already committed with other content"
            )
        commit = existing_batch.commit
        return PreparedFactCommit(
            batch=batch,
            digest=digest,
            entries=(),
            commit=FactCommit(
                batch_id=commit.batch_id,
                first_sequence=commit.first_sequence,
                last_sequence=commit.last_sequence,
                fact_count=commit.fact_count,
                replayed=True,
            ),
        )

    known = {entry.fact.fact_id: entry for entry in existing_entries}
    successors = {
        predecessor_id: entry.fact.fact_id
        for entry in existing_entries
        if (predecessor_id := entry.fact.predecessor_id) is not None
    }
    first_sequence = len(existing_entries) + 1
    entries: list[StoredFact] = []
    for offset, fact in enumerate(batch.facts):
        if fact.fact_id in known:
            raise FactValidationError(
                f"ontology fact_id {fact.fact_id} is already committed"
            )
        predecessor_id = fact.predecessor_id
        if predecessor_id is not None:
            predecessor = known.get(predecessor_id)
            if predecessor is None:
                raise FactValidationError(
                    f"ontology fact {fact.fact_id} references unknown predecessor "
                    f"{predecessor_id}"
                )
            validate_fact_lineage(predecessor.fact, fact)
            if predecessor_id in successors:
                raise FactValidationError(
                    f"ontology fact {predecessor_id} already has a successor"
                )
            successors[predecessor_id] = fact.fact_id
        entry = StoredFact(sequence=first_sequence + offset, fact=fact)
        entries.append(entry)
        known[fact.fact_id] = entry

    commit = FactCommit(
        batch_id=batch.batch_id,
        first_sequence=entries[0].sequence,
        last_sequence=entries[-1].sequence,
        fact_count=len(entries),
    )
    return PreparedFactCommit(
        batch=batch,
        digest=digest,
        entries=tuple(entries),
        commit=commit,
    )


def prepare_guarded_fact_commit(
    batch: FactBatch,
    *,
    expected_watermark: int,
    current_facts: Iterable[StoredFact],
    committed_batches: Mapping[str, CommittedFactBatch],
) -> PreparedFactCommit:
    """Plan one conditional commit with idempotent replay before the guard."""

    expected_watermark = require_sequence(
        "expected_watermark",
        expected_watermark,
    )
    if not isinstance(batch, FactBatch):
        raise FactValidationError("commit_fact_batch_guarded requires a FactBatch")
    existing_entries = tuple(current_facts)
    validate_fact_journal(existing_entries, committed_batches)
    if batch.batch_id in committed_batches:
        return prepare_fact_commit(
            batch,
            current_facts=existing_entries,
            committed_batches=committed_batches,
        )
    actual_watermark = len(existing_entries)
    if expected_watermark != actual_watermark:
        raise FactWatermarkConflictError(expected_watermark, actual_watermark)
    return prepare_fact_commit(
        batch,
        current_facts=existing_entries,
        committed_batches=committed_batches,
    )


def select_facts_as_of(
    facts: Iterable[StoredFact],
    *,
    valid_at: float,
    recorded_at: float,
) -> tuple[StoredFact, ...]:
    """Apply the common bitemporal and lineage selection semantics."""

    valid_at = require_timestamp("valid_at", valid_at)
    recorded_at = require_timestamp("recorded_at", recorded_at)
    entries = tuple(facts)
    if len({entry.fact.schema_identity for entry in entries}) > 1:
        raise FactValidationError(
            "stored Fact journal mixes complete schema identities"
        )
    retired = {
        predecessor
        for item in entries
        if item.fact.recorded_at <= recorded_at
        if (predecessor := item.fact.predecessor_id) is not None
    }
    return tuple(
        item
        for item in entries
        if item.fact.recorded_at <= recorded_at
        and item.fact.is_valid_at(valid_at)
        and item.fact.fact_id not in retired
    )


def validate_fact_journal(
    facts: Iterable[StoredFact],
    committed_batches: Mapping[str, CommittedFactBatch],
) -> None:
    """Validate persisted journal continuity, lineage, and batch coverage."""

    entries = tuple(facts)
    if len({entry.fact.schema_identity for entry in entries}) > 1:
        raise FactValidationError(
            "stored Fact journal mixes complete schema identities"
        )
    known: dict[UUID, StoredFact] = {}
    successors: dict[UUID, UUID] = {}
    for expected_sequence, entry in enumerate(entries, start=1):
        if entry.sequence != expected_sequence:
            raise FactValidationError("stored fact sequence is not contiguous")
        if entry.fact.fact_id in known:
            raise FactValidationError("stored ontology fact_id is duplicated")
        predecessor_id = entry.fact.predecessor_id
        if predecessor_id is not None:
            predecessor = known.get(predecessor_id)
            if predecessor is None:
                raise FactValidationError("stored fact lineage is not append-only")
            validate_fact_lineage(predecessor.fact, entry.fact)
            if predecessor_id in successors:
                raise FactValidationError("stored fact has multiple successors")
            successors[predecessor_id] = entry.fact.fact_id
        known[entry.fact.fact_id] = entry

    covered_sequences: list[int] = []
    entries_by_sequence = {entry.sequence: entry for entry in entries}
    for batch_id, committed in sorted(
        committed_batches.items(),
        key=lambda item: item[1].commit.first_sequence,
    ):
        commit = committed.commit
        if batch_id != commit.batch_id or commit.replayed:
            raise FactValidationError("stored fact batch metadata is invalid")
        if commit.fact_count <= 0:
            raise FactValidationError("stored fact batch is empty")
        if commit.last_sequence - commit.first_sequence + 1 != commit.fact_count:
            raise FactValidationError("stored fact batch range is invalid")
        try:
            batch = FactBatch(
                batch_id,
                [
                    entries_by_sequence[sequence].fact
                    for sequence in range(
                        commit.first_sequence,
                        commit.last_sequence + 1,
                    )
                ],
            )
        except KeyError as exc:
            raise FactValidationError(
                "stored fact batch range is outside the fact journal"
            ) from exc
        if batch.content_digest != committed.digest:
            raise FactValidationError(
                "stored fact batch digest does not match its semantic facts"
            )
        covered_sequences.extend(range(commit.first_sequence, commit.last_sequence + 1))
    if covered_sequences != list(range(1, len(entries) + 1)):
        raise FactValidationError(
            "stored fact batches do not cover the semantic fact journal"
        )


def validate_fact_lineage(predecessor: FactRecord, successor: FactRecord) -> None:
    if predecessor.schema_identity != successor.schema_identity:
        raise FactValidationError("fact lineage must preserve its schema identity")
    predecessor_coordinate = predecessor.lineage_coordinate
    successor_coordinate = successor.lineage_coordinate
    if predecessor_coordinate[:4] != successor_coordinate[:4]:
        raise FactValidationError("fact lineage must preserve its assertion coordinate")
    if predecessor_coordinate[4:] != successor_coordinate[4:]:
        raise FactValidationError("fact lineage must preserve its source lineage")
    if successor.recorded_at < predecessor.recorded_at:
        raise FactValidationError(
            "fact lineage successor recorded_at cannot precede its predecessor"
        )


def require_sequence(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def require_timestamp(name: str, value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    number = cast(int | float, value)
    if not math.isfinite(float(number)):
        raise ValueError(f"{name} must be a finite number")
    return float(number)


__all__ = [
    "CommittedFactBatch",
    "PreparedFactCommit",
    "prepare_fact_commit",
    "prepare_guarded_fact_commit",
    "require_sequence",
    "require_timestamp",
    "select_facts_as_of",
    "validate_fact_journal",
    "validate_fact_lineage",
]
