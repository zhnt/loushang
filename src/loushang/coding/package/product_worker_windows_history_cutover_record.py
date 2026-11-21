"""Canonical Windows Worker Product history-cutover record, without authority.

The record names one persisted checkpoint and its six semantic bases. It is
inert until a separate Product owner can atomically switch every reader and
writer and publish it under runtime quiescence and the GC write gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.worker.history._windows_persisted import (
    _WindowsHistoryCutoverMethods,
)

from .product_worker_windows_base_files import (
    WINDOWS_WORKER_BASE_FILES as WINDOWS_WORKER_BASE_FILES,
)
from .product_worker_windows_base_files import WINDOWS_WORKER_HISTORY_CUTOVER_NAME
from .product_worker_windows_persisted_bases import CodingWindowsWorkerPersistedBasesV1


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistoryCutoverRecordV1(_WindowsHistoryCutoverMethods):
    _persisted_type = CodingWindowsWorkerPersistedBasesV1
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


CodingWindowsWorkerHistoryCutoverRecordV1._bind_record_schema()


__all__ = [
    "WINDOWS_WORKER_HISTORY_CUTOVER_NAME",
    "CodingWindowsWorkerHistoryCutoverRecordV1",
]
