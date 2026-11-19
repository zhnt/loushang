"""Read-only Windows Worker history source inventory for a future cutover.

This captures byte identities under Product quiescence. It grants no history
retirement, new Worker attempt, or Package GC authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_history import (
    WindowsProductWorkerHistorySources,
    _WindowsHistorySemanticReadMethods,
)
from loushang.harness.package_product._windows_worker_references import (
    windows_worker_desired_history_digest,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.worker.history._windows_sources import (
    WINDOWS_WORKER_BASE_STAGE_NAMES as WINDOWS_WORKER_BASE_STAGE_NAMES,
)
from loushang.harness.worker.history._windows_sources import (
    _WindowsHistorySettlementMethods,
    _WindowsHistorySourceFileMethods,
    _WindowsHistorySourceSnapshotMethods,
)

from .package_product_worker_windows_gc_history import (
    CodingWindowsWorkerGcHistoryAuthority,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerOfflineRecoverySnapshotV1,
    _inspect_coding_windows_product_worker_offline_recovery_under_gc_guard,
)

_coding_windows_worker_desired_history_digest = windows_worker_desired_history_digest

_MAX_FILES = 8192
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySourceFileV1(_WindowsHistorySourceFileMethods):
    @staticmethod
    def _file_limit() -> int:
        return _MAX_FILE_BYTES

    name: str
    size: int
    sha256_digest: str

    @classmethod
    def from_dict(cls, value: object) -> CodingWindowsWorkerHistorySourceFileV1:
        return cls._from_file_dict(value)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySourceSnapshotV1(_WindowsHistorySourceSnapshotMethods):
    _source_file_type = CodingWindowsWorkerHistorySourceFileV1

    @staticmethod
    def _source_limits() -> tuple[int, int, int]:
        return _MAX_FILES, _MAX_FILE_BYTES, _MAX_TOTAL_BYTES

    scope_id: str
    store_id: str
    lease_owner_revision: int
    files: tuple[CodingWindowsWorkerHistorySourceFileV1, ...]
    snapshot_digest: str

    @classmethod
    def from_dict(cls, value: object) -> CodingWindowsWorkerHistorySourceSnapshotV1:
        return cls._from_source_dict(value)

    @classmethod
    def create(
        cls,
        *,
        scope_id: str,
        store_id: str,
        lease_owner_revision: int,
        files: tuple[CodingWindowsWorkerHistorySourceFileV1, ...],
    ) -> CodingWindowsWorkerHistorySourceSnapshotV1:
        return cls._from_files(
            scope_id=scope_id,
            store_id=store_id,
            lease_owner_revision=lease_owner_revision,
            files=files,
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySettlementReviewV1(_WindowsHistorySettlementMethods):
    """Momentary source and settled-attempt proof; grants no cutover."""

    _source_snapshot_type = CodingWindowsWorkerHistorySourceSnapshotV1
    _review_kind = "coding-windows-worker-settled-history/v1"

    source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    review_digest: str

    @classmethod
    def create(
        cls, source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    ) -> CodingWindowsWorkerHistorySettlementReviewV1:
        return cls._from_snapshot(source_snapshot)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerHistorySemanticReadV1(_WindowsHistorySemanticReadMethods):
    """One source/semantic read under shared Product locks, without cutover."""

    _source_snapshot_type = CodingWindowsWorkerHistorySourceSnapshotV1
    _recovery_snapshot_type = CodingWindowsWorkerOfflineRecoverySnapshotV1

    source_snapshot: CodingWindowsWorkerHistorySourceSnapshotV1
    offline_recovery: CodingWindowsWorkerOfflineRecoverySnapshotV1
    desired_inventory_revision: int | None = None
    desired_history_digest: str | None = None
    desired_snapshot: PluginDesiredStateSnapshotV1 | None = None
    desired_transitions: tuple[PluginDesiredStateJournalTransition, ...] | None = None


__all__ = [
    "CodingWindowsWorkerHistorySourceFileV1",
    "CodingWindowsWorkerHistorySourceSnapshotV1",
    "CodingWindowsWorkerHistorySettlementReviewV1",
    "CodingWindowsWorkerHistorySemanticReadV1",
    "capture_coding_windows_worker_history_sources",
    "read_coding_windows_worker_history_semantics",
    "review_coding_windows_worker_settled_history_sources",
]


_HISTORY_SOURCES: WindowsProductWorkerHistorySources[
    CodingWindowsWorkerHistorySourceSnapshotV1,
    CodingWindowsWorkerHistorySemanticReadV1,
    CodingWindowsWorkerHistorySettlementReviewV1,
] = WindowsProductWorkerHistorySources(
    product_id="coding",
    snapshot_type=CodingWindowsWorkerHistorySourceSnapshotV1,
    semantic_type=CodingWindowsWorkerHistorySemanticReadV1,
    settlement_review=CodingWindowsWorkerHistorySettlementReviewV1.create,
    settlement_type=CodingWindowsWorkerGcHistoryAuthority,
    recovery_reader=_inspect_coding_windows_product_worker_offline_recovery_under_gc_guard,
)

capture_coding_windows_worker_history_sources = _HISTORY_SOURCES.capture_sources
review_coding_windows_worker_settled_history_sources = (
    _HISTORY_SOURCES.review_settled_sources
)
read_coding_windows_worker_history_semantics = _HISTORY_SOURCES.read_semantics
_capture_coding_windows_worker_history_sources = (
    _HISTORY_SOURCES.capture_sources_with_settlement
)
_capture_coding_windows_worker_history_sources_under_gc_guard = (
    _HISTORY_SOURCES.capture_sources_under_guard
)
_capture_coding_windows_worker_semantics_under_gc_guard = (
    _HISTORY_SOURCES.capture_semantics_under_guard
)
