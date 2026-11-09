"""Coding public C5 records over the shared Worker replay mechanism."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.activation_state_journal import _StateRecord
from loushang.harness.worker.history._activation_base import (
    _ActivationBaseMethods,
    _ActivationReplayFields,
)
from loushang.harness.worker.history._activation_base import (
    _parse_c5_segment as _parse_c5_segment,
)


@dataclass(frozen=True, slots=True)
class CodingWorkerActivationReplayV2(_ActivationReplayFields):
    last_record: _StateRecord
    retired_attempt_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWorkerActivationSemanticBaseV2(_ActivationBaseMethods):
    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    last_record: _StateRecord
    retired_attempt_ids: tuple[str, ...]
    version: int = 2

    _replay_type = CodingWorkerActivationReplayV2


CodingWorkerActivationSemanticBaseV2._wire_schema = (
    CodingWorkerActivationSemanticBaseV2._make_wire_schema()
)

__all__ = ["CodingWorkerActivationReplayV2", "CodingWorkerActivationSemanticBaseV2"]
