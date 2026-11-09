"""Typed Windows Worker C5 state and attempt tombstones at a cutover boundary.

This source-bound projection cannot commit a Product cutover, replace the C5
journal, or authorize source deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.worker.activation_state_journal import (
    _StateRecord,
)
from loushang.harness.worker.history._base_codec import (
    _unchanged,
)
from loushang.harness.worker.history._windows_c5_base import (
    _WindowsC5BaseMethods,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerC5ReplayV1:
    last_record: _StateRecord | None
    retired_attempt_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerC5SemanticBaseV1(_WindowsC5BaseMethods):
    _replay_type = CodingWindowsWorkerC5ReplayV1
    _retained_attempt_type = CodingProductWorkerRetainedAttemptV1

    scope_id: str
    store_id: str
    source_snapshot_digest: str
    owner_present: bool
    cutoff_revision: int
    last_record: _StateRecord | None
    retired_attempt_ids: tuple[str, ...]
    record_digest: str
    version: int = 1

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerC5SemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker C5 preparation is invalid")
        prepared.require_semantic_read(semantic)
        return cls._from_source_read(
            semantic.source_snapshot, semantic.offline_recovery
        )

    def replay(
        self, records: tuple[_StateRecord, ...]
    ) -> CodingWindowsWorkerC5ReplayV1:
        return cast(CodingWindowsWorkerC5ReplayV1, self._replay_retained(records))

    _wire_label = "Windows Worker C5 semantic base"
    _wire_lists = ("retiredAttemptIds",)
    _wire_errors = (KeyError, RecursionError, TypeError, UnicodeError, ValueError)

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_BASE_BYTES


__all__ = ["CodingWindowsWorkerC5ReplayV1", "CodingWindowsWorkerC5SemanticBaseV1"]


CodingWindowsWorkerC5SemanticBaseV1._bind_wire_schema(
    RecordSchema.for_dataclass(
        CodingWindowsWorkerC5SemanticBaseV1,
        _unchanged,
        RecordField(
            "last_record",
            decoder=lambda xs: None if xs is None else _StateRecord.from_dict(xs),
            encoder=lambda value: None if value is None else value.to_dict(),
        ),
        RecordField("retired_attempt_ids", decoder=tuple, encoder=list),
    )
)
