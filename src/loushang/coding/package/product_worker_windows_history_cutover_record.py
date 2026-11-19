"""Canonical Windows Worker Product history-cutover record, without authority.

The record names one persisted checkpoint and its six semantic bases. It is
inert until a separate Product owner can atomically switch every reader and
writer and publish it under runtime quiescence and the GC write gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.worker.history._base_codec import _unchanged
from loushang.harness.worker.history._windows_persisted import (
    _WindowsHistoryCutoverMethods,
)

from .product_worker_windows_base_files import (
    WINDOWS_WORKER_BASE_FILES as WINDOWS_WORKER_BASE_FILES,
)
from .product_worker_windows_base_files import WINDOWS_WORKER_HISTORY_CUTOVER_NAME
from .product_worker_windows_persisted_bases import CodingWindowsWorkerPersistedBasesV1

_MAX_BYTES = 4096


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistoryCutoverRecordV1(_WindowsHistoryCutoverMethods):
    _persisted_type = CodingWindowsWorkerPersistedBasesV1
    _wire_label = "Windows Worker history cutover record"
    _wire_lists = ("baseDigests",)
    _wire_invalid_bytes = _wire_invalid_fields = _wire_invalid_encoding = "is invalid"
    _wire_errors = (KeyError, RecursionError, TypeError, UnicodeError, ValueError)
    _wire_nested_lists = ("baseDigests",)

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_BYTES

    scope_id: str
    store_id: str
    checkpoint_digest: str
    source_snapshot_digest: str
    base_digests: tuple[tuple[str, str], ...]
    record_digest: str
    cutover_version: int = 1

    @classmethod
    def from_persisted_bases(
        cls, persisted: CodingWindowsWorkerPersistedBasesV1
    ) -> CodingWindowsWorkerHistoryCutoverRecordV1:
        return cls._from_persisted_bases(persisted)

    def require_persisted_bases(
        self, persisted: CodingWindowsWorkerPersistedBasesV1
    ) -> None:
        if self != self.from_persisted_bases(persisted):
            raise ValueError("Windows Worker history cutover bases changed")


CodingWindowsWorkerHistoryCutoverRecordV1._wire_schema = RecordSchema.for_dataclass(
    CodingWindowsWorkerHistoryCutoverRecordV1,
    _unchanged,
    RecordField(
        "base_digests", decoder=lambda value: tuple(tuple(item) for item in value)
    ),
)


__all__ = [
    "WINDOWS_WORKER_HISTORY_CUTOVER_NAME",
    "CodingWindowsWorkerHistoryCutoverRecordV1",
]
