"""Typed Windows Worker opt-in base for a future Product history cutover.

This projects a guarded V1 source and can validate later records. It does not
publish a cutover, replace the current journal, or authorize deletion.
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
from loushang.harness.worker.history._windows_opt_in_base import (
    _WindowsOptInBaseMethods,
)

from .package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournalError,
)
from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOptInReplayV1:
    last_revision: int
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    operation_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOptInSemanticBaseV1(_WindowsOptInBaseMethods):
    _decision_type = CodingWorkerOptInDecisionV1
    _error_type = CodingWorkerOptInJournalError
    _replay_type = CodingWindowsWorkerOptInReplayV1

    scope_id: str
    store_id: str
    source_snapshot_digest: str
    cutoff_revision: int
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    retired_operation_ids: tuple[str, ...]
    record_digest: str
    version: int = 1

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerOptInSemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker opt-in preparation is invalid")
        prepared.require_semantic_read(semantic)
        return cls._from_source_read(
            semantic.source_snapshot, semantic.offline_recovery
        )

    def replay(
        self, events: tuple[CodingWorkerOptInDecisionV1, ...]
    ) -> CodingWindowsWorkerOptInReplayV1:
        return cast(CodingWindowsWorkerOptInReplayV1, self._replay_retained(events))

    _wire_label = "Windows Worker opt-in semantic base"
    _wire_lists = ("latestDecisions", "retiredOperationIds")
    _wire_errors = (TypeError, UnicodeError, ValueError)

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_BASE_BYTES


__all__ = [
    "CodingWindowsWorkerOptInReplayV1",
    "CodingWindowsWorkerOptInSemanticBaseV1",
]


CodingWindowsWorkerOptInSemanticBaseV1._bind_wire_schema(
    RecordSchema.for_dataclass(
        CodingWindowsWorkerOptInSemanticBaseV1,
        _unchanged,
        RecordField(
            "latest_decisions",
            decoder=lambda xs: tuple(
                (CodingWorkerOptInDecisionV1.from_dict(item) for item in xs)
            ),
            encoder=lambda values: [value.to_dict() for value in values],
        ),
        RecordField("retired_operation_ids", decoder=tuple, encoder=list),
    )
)
