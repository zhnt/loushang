"""Ports and stable commit values for the semantic fact authority."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from loushang.ontology.facts.model import FactBatch, FactRecord, FactValidationError


class FactBatchConflictError(FactValidationError):
    """Raised when an idempotency key is reused with different fact content."""


class FactWatermarkConflictError(FactValidationError):
    """Raised when a new guarded batch was planned from stale Fact state."""

    def __init__(self, expected_watermark: int, actual_watermark: int) -> None:
        self.expected_watermark = expected_watermark
        self.actual_watermark = actual_watermark
        super().__init__(
            "Fact watermark changed from "
            f"{expected_watermark} to {actual_watermark} before guarded commit"
        )


@dataclass(frozen=True, slots=True)
class StoredFact:
    """One committed semantic fact and its contiguous store sequence."""

    sequence: int
    fact: FactRecord


@dataclass(frozen=True, slots=True)
class FactCommit:
    """Stable result of one atomic fact-batch commit."""

    batch_id: str
    first_sequence: int
    last_sequence: int
    fact_count: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class FactSelection:
    """One immutable bitemporal Fact selection and its captured watermark."""

    facts: tuple[StoredFact, ...]
    fact_watermark: int
    valid_at: float
    recorded_at: float

    def __post_init__(self) -> None:
        if not isinstance(self.facts, tuple) or any(
            not isinstance(item, StoredFact) for item in self.facts
        ):
            raise TypeError("facts must be a tuple of StoredFact values")
        if type(self.fact_watermark) is not int or self.fact_watermark < 0:
            raise ValueError("fact_watermark must be a non-negative integer")
        sequences = [item.sequence for item in self.facts]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("selected facts must have unique ascending sequences")
        if any(sequence > self.fact_watermark for sequence in sequences):
            raise ValueError("selected facts cannot exceed the captured watermark")
        for name in ("valid_at", "recorded_at"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")
            object.__setattr__(self, name, float(value))


@runtime_checkable
class FactReadStore(Protocol):
    """Bitemporal read side of the semantic fact authority."""

    @property
    def fact_watermark(self) -> int: ...

    def get_fact(self, fact_id: UUID) -> StoredFact: ...

    def read_facts(self, *, after_sequence: int = 0) -> tuple[StoredFact, ...]: ...

    def select_facts(
        self,
        *,
        valid_at: float,
        recorded_at: float,
    ) -> FactSelection: ...


@runtime_checkable
class FactStore(FactReadStore, Protocol):
    """Atomic append side of the semantic fact authority."""

    def commit_fact_batch(self, batch: FactBatch) -> FactCommit: ...

    def commit_fact_batch_guarded(
        self,
        batch: FactBatch,
        *,
        expected_watermark: int,
    ) -> FactCommit: ...


__all__ = [
    "FactBatchConflictError",
    "FactCommit",
    "FactReadStore",
    "FactSelection",
    "FactStore",
    "FactWatermarkConflictError",
    "StoredFact",
]
