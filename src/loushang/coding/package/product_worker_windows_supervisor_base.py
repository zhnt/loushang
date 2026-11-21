"""Typed Windows Worker Supervisor state and tombstones at a cutover boundary.

This source-bound projection cannot commit a Product cutover, replace the
Supervisor journal, or authorize history deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.worker.history._windows_supervisor_base import (
    _WindowsSupervisorBaseMethods,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
)

from .product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1 as CodingWindowsWorkerHistorySemanticReadV1,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerSupervisorReplayV1:
    last_revision: int
    latest_attempts: tuple[WorkerAttemptRecordV1, ...]
    attempt_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerSupervisorSemanticBaseV1(_WindowsSupervisorBaseMethods):
    _preparation_type = CodingWindowsWorkerHistoryPreparationV1
    _preparation_label = "Supervisor"
    _replay_type = CodingWindowsWorkerSupervisorReplayV1

    def replay(
        self, records: tuple[WorkerAttemptRecordV1, ...]
    ) -> CodingWindowsWorkerSupervisorReplayV1:
        return cast(
            CodingWindowsWorkerSupervisorReplayV1, self._replay_retained(records)
        )


__all__ = [
    "CodingWindowsWorkerSupervisorReplayV1",
    "CodingWindowsWorkerSupervisorSemanticBaseV1",
]


CodingWindowsWorkerSupervisorSemanticBaseV1._bind_record_schema()
