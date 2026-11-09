"""Typed Windows Worker Supervisor state and tombstones at a cutover boundary.

This source-bound projection cannot commit a Product cutover, replace the
Supervisor journal, or authorize history deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.worker.history._base_codec import (
    _unchanged,
)
from loushang.harness.worker.history._windows_supervisor_base import (
    _WindowsSupervisorBaseMethods,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
)

from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerSupervisorReplayV1:
    last_revision: int
    latest_attempts: tuple[WorkerAttemptRecordV1, ...]
    attempt_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerSupervisorSemanticBaseV1(_WindowsSupervisorBaseMethods):
    _replay_type = CodingWindowsWorkerSupervisorReplayV1

    scope_id: str
    store_id: str
    source_snapshot_digest: str
    cutoff_revision: int
    latest_attempts: tuple[WorkerAttemptRecordV1, ...]
    retired_attempt_ids: tuple[str, ...]
    record_digest: str
    version: int = 1

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerSupervisorSemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker Supervisor preparation is invalid")
        prepared.require_semantic_read(semantic)
        return cls._from_source_read(
            semantic.source_snapshot, semantic.offline_recovery
        )

    def replay(
        self, records: tuple[WorkerAttemptRecordV1, ...]
    ) -> CodingWindowsWorkerSupervisorReplayV1:
        return cast(
            CodingWindowsWorkerSupervisorReplayV1, self._replay_retained(records)
        )

    _wire_label = "Windows Worker Supervisor semantic base"
    _wire_lists = ("latestAttempts", "retiredAttemptIds")
    _wire_errors = (TypeError, UnicodeError, ValueError)

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_BASE_BYTES


__all__ = [
    "CodingWindowsWorkerSupervisorReplayV1",
    "CodingWindowsWorkerSupervisorSemanticBaseV1",
]


CodingWindowsWorkerSupervisorSemanticBaseV1._bind_wire_schema(
    RecordSchema.for_dataclass(
        CodingWindowsWorkerSupervisorSemanticBaseV1,
        _unchanged,
        RecordField(
            "latest_attempts",
            decoder=lambda xs: tuple(
                (WorkerAttemptRecordV1.from_dict(item) for item in xs)
            ),
            encoder=lambda values: [value.to_dict() for value in values],
        ),
        RecordField("retired_attempt_ids", decoder=tuple, encoder=list),
    )
)
