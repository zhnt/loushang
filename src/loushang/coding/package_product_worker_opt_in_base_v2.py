"""Coding public opt-in bases over the shared Worker history mechanisms."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._opt_in import (
    _OptInBaseMethods,
    _OptInReplayFields,
    parse_opt_in_segment,
)

from .package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournalError,
)


def _parse_opt_in_segment(raw: bytes) -> tuple[CodingWorkerOptInDecisionV1, ...]:
    return parse_opt_in_segment(raw, decision_type=CodingWorkerOptInDecisionV1)


@dataclass(frozen=True, slots=True)
class CodingWorkerOptInReplayV2(_OptInReplayFields):
    last_revision: int
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    operation_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWorkerOptInSemanticBaseV2(_OptInBaseMethods):
    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    retired_operation_ids: tuple[str, ...]
    version: int = 2

    _decision_type = CodingWorkerOptInDecisionV1
    _error_type = CodingWorkerOptInJournalError
    _replay_type = CodingWorkerOptInReplayV2


CodingWorkerOptInSemanticBaseV2._wire_schema = (
    CodingWorkerOptInSemanticBaseV2._make_wire_schema()
)

__all__ = ["CodingWorkerOptInReplayV2", "CodingWorkerOptInSemanticBaseV2"]
