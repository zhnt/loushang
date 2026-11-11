"""Public Coding record names over the shared Worker history mechanisms."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._supervisor import (
    _parse_supervisor_segment as _parse_supervisor_segment,
)
from loushang.harness.worker.history._supervisor import (
    _SupervisorBaseMethods,
    _SupervisorKeyMethods,
    _SupervisorReplayFields,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1


@dataclass(frozen=True, slots=True)
class CodingWorkerSupervisorKeyBaseV2(_SupervisorKeyMethods):
    supervisor_key: str
    last_record: WorkerAttemptRecordV1
    last_clean_stop_revision: int
    claims_since_stop: int


@dataclass(frozen=True, slots=True)
class CodingWorkerSupervisorReplayV2(_SupervisorReplayFields):
    last_revision: int
    current_attempts: tuple[WorkerAttemptRecordV1, ...]
    key_states: tuple[CodingWorkerSupervisorKeyBaseV2, ...]
    retired_attempt_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWorkerSupervisorSemanticBaseV2(_SupervisorBaseMethods):
    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    current_attempts: tuple[WorkerAttemptRecordV1, ...]
    key_states: tuple[CodingWorkerSupervisorKeyBaseV2, ...]
    retired_attempt_ids: tuple[str, ...]
    version: int = 2

    _key_type = CodingWorkerSupervisorKeyBaseV2
    _replay_type = CodingWorkerSupervisorReplayV2


CodingWorkerSupervisorSemanticBaseV2._wire_schema = (
    CodingWorkerSupervisorSemanticBaseV2._make_wire_schema()
)

__all__ = [
    "CodingWorkerSupervisorKeyBaseV2",
    "CodingWorkerSupervisorReplayV2",
    "CodingWorkerSupervisorSemanticBaseV2",
]
