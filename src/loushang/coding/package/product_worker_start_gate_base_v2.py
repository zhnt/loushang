"""Coding public start-gate bases over the existing Worker identity facts."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._start_gate import (
    _StartGateBaseMethods,
    _StartGateReplayFields,
)

from .product_worker_start_gate_journal import CodingWorkerStartGateRecordV1


@dataclass(frozen=True, slots=True)
class CodingWorkerStartGateReplayV2(_StartGateReplayFields):
    last_revision: int
    current_records: tuple[CodingWorkerStartGateRecordV1, ...]
    retired_attempt_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWorkerStartGateSemanticBaseV2(_StartGateBaseMethods):
    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    current_records: tuple[CodingWorkerStartGateRecordV1, ...]
    retired_attempt_ids: tuple[str, ...]
    version: int = 2

    _record_type = CodingWorkerStartGateRecordV1
    _replay_type = CodingWorkerStartGateReplayV2


CodingWorkerStartGateSemanticBaseV2._wire_schema = (
    CodingWorkerStartGateSemanticBaseV2._make_wire_schema()
)

__all__ = ["CodingWorkerStartGateReplayV2", "CodingWorkerStartGateSemanticBaseV2"]
