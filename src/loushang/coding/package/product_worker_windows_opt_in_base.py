"""Typed Windows Worker opt-in base for a future Product history cutover.

This projects a guarded V1 source and can validate later records. It does not
publish a cutover, replace the current journal, or authorize deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.worker.history._windows_opt_in_base import (
    _WindowsOptInBaseMethods,
)

from .product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournalError,
)
from .product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1 as CodingWindowsWorkerHistorySemanticReadV1,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOptInReplayV1:
    last_revision: int
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    operation_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOptInSemanticBaseV1(_WindowsOptInBaseMethods):
    _preparation_type = CodingWindowsWorkerHistoryPreparationV1
    _preparation_label = "opt-in"
    _decision_type = CodingWorkerOptInDecisionV1
    _error_type = CodingWorkerOptInJournalError
    _replay_type = CodingWindowsWorkerOptInReplayV1

    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]

    def replay(
        self, events: tuple[CodingWorkerOptInDecisionV1, ...]
    ) -> CodingWindowsWorkerOptInReplayV1:
        return cast(CodingWindowsWorkerOptInReplayV1, self._replay_retained(events))


__all__ = [
    "CodingWindowsWorkerOptInReplayV1",
    "CodingWindowsWorkerOptInSemanticBaseV1",
]


CodingWindowsWorkerOptInSemanticBaseV1._bind_record_schema()
