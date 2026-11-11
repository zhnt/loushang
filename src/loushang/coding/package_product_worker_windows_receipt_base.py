"""Typed Windows Worker receipt sequence and tombstones at a cutover boundary.

This projection preserves historical allow joins. It does not commit a
Product cutover, replace the receipt journal, or authorize source deletion.
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
from loushang.harness.worker.history._windows_receipt_base import (
    _WindowsReceiptBaseMethods,
)

from ._product_worker_canary import CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID
from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_policy import coding_worker_session_scope_id
from .package_product_worker_receipt import CodingWorkerReceiptRecordV1
from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)

_MAX_BASE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerReceiptReplayV1:
    last_issue_sequence: int
    retained_records: tuple[CodingWorkerReceiptRecordV1, ...]
    receipt_fingerprints: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerReceiptSemanticBaseV1(_WindowsReceiptBaseMethods):
    _decision_type = CodingWorkerOptInDecisionV1
    _record_type = CodingWorkerReceiptRecordV1
    _replay_type = CodingWindowsWorkerReceiptReplayV1
    _native_profile_id = CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID
    _session_scope_id = staticmethod(coding_worker_session_scope_id)
    _product_id = "coding"
    _native_platform = "windows-amd64"

    scope_id: str
    store_id: str
    source_snapshot_digest: str
    last_issue_sequence: int
    retired_receipt_fingerprints: tuple[str, ...]
    record_digest: str
    version: int = 1

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerReceiptSemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker receipt preparation is invalid")
        prepared.require_semantic_read(semantic)
        return cls._from_source_read(
            semantic.source_snapshot, semantic.offline_recovery
        )

    def replay(
        self, records: tuple[CodingWorkerReceiptRecordV1, ...]
    ) -> CodingWindowsWorkerReceiptReplayV1:
        return cast(CodingWindowsWorkerReceiptReplayV1, self._replay_retained(records))

    _wire_label = "Windows Worker receipt semantic base"
    _wire_lists = ("retiredReceiptFingerprints",)
    _wire_errors = (TypeError, UnicodeError, ValueError)

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_BASE_BYTES


__all__ = [
    "CodingWindowsWorkerReceiptReplayV1",
    "CodingWindowsWorkerReceiptSemanticBaseV1",
]


CodingWindowsWorkerReceiptSemanticBaseV1._bind_wire_schema(
    RecordSchema.for_dataclass(
        CodingWindowsWorkerReceiptSemanticBaseV1,
        _unchanged,
        RecordField("retired_receipt_fingerprints", decoder=tuple, encoder=list),
    )
)
