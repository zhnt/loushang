"""Read-only Windows Worker history source inventory for a future cutover.

This captures byte identities under Product quiescence. It grants no history
retirement, new Worker attempt, or Package GC authority.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_history import (
    _WindowsHistorySemanticReadMethods,
    capture_windows_product_worker_history_semantics_under_guard,
    capture_windows_product_worker_history_sources,
    capture_windows_product_worker_sources_under_guard,
    read_windows_product_worker_history_semantics,
)
from loushang.harness.package_product._windows_worker_references import (
    capture_windows_product_worker_desired_history,
    windows_worker_desired_history_digest,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsEpochRuntimeLeaseRegistry,
    PackageWindowsRuntimeQuiescenceV1,
)
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

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
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


def capture_coding_windows_worker_history_sources(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistorySourceSnapshotV1:
    """Hash all recognized Worker-owned files without changing Product state."""

    return _capture_coding_windows_worker_history_sources(
        product, require_settled_history=False
    )


def review_coding_windows_worker_settled_history_sources(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistorySettlementReviewV1:
    """Join source bytes to GC's complete-attempt retirement proof."""

    return CodingWindowsWorkerHistorySettlementReviewV1.create(
        _capture_coding_windows_worker_history_sources(
            product, require_settled_history=True
        )
    )


def read_coding_windows_worker_history_semantics(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistorySemanticReadV1:
    """Join settled source bytes and retained semantics without publication."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker history requires its Product owner")
    return read_windows_product_worker_history_semantics(
        product,
        capture_semantic=_capture_coding_windows_worker_semantics_under_gc_guard,
    )


def _coding_windows_worker_desired_history_digest(
    snapshot: PluginDesiredStateSnapshotV1,
    transitions: tuple[PluginDesiredStateJournalTransition, ...],
) -> str:
    """Hash one complete Desired selection and transition capture."""
    return windows_worker_desired_history_digest(snapshot, transitions)


def _capture_coding_windows_worker_desired_history_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
) -> tuple[
    PluginDesiredStateSnapshotV1,
    tuple[PluginDesiredStateJournalTransition, ...],
    str,
]:
    """Bind current Desired selection and its complete transition provenance."""
    return capture_windows_product_worker_desired_history(product)


def _capture_coding_windows_worker_history_sources(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    require_settled_history: bool,
) -> CodingWindowsWorkerHistorySourceSnapshotV1:
    """Capture source bytes and optionally verify GC's settlement proof."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker history requires its Product owner")
    return capture_windows_product_worker_history_sources(
        product,
        snapshot_type=CodingWindowsWorkerHistorySourceSnapshotV1,
        settlement_type=CodingWindowsWorkerGcHistoryAuthority,
        require_settled_history=require_settled_history,
    )


def _capture_coding_windows_worker_history_sources_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    store_id: str,
    lease_owner_revision: int,
    require_settled_history: bool,
    allow_preparation_stage: bool = False,
    allow_checkpoint_stage: bool = False,
    allow_base_stage: bool = False,
) -> CodingWindowsWorkerHistorySourceSnapshotV1:
    """Pin original Product roots through the shared source owner."""
    return capture_windows_product_worker_sources_under_guard(
        product,
        snapshot_type=CodingWindowsWorkerHistorySourceSnapshotV1,
        settlement_type=CodingWindowsWorkerGcHistoryAuthority,
        store_id=store_id,
        lease_owner_revision=lease_owner_revision,
        require_settled_history=require_settled_history,
        allow_preparation_stage=allow_preparation_stage,
        allow_checkpoint_stage=allow_checkpoint_stage,
        allow_base_stage=allow_base_stage,
    )


__all__ = [
    "CodingWindowsWorkerHistorySourceFileV1",
    "CodingWindowsWorkerHistorySourceSnapshotV1",
    "CodingWindowsWorkerHistorySettlementReviewV1",
    "CodingWindowsWorkerHistorySemanticReadV1",
    "capture_coding_windows_worker_history_sources",
    "read_coding_windows_worker_history_semantics",
    "review_coding_windows_worker_settled_history_sources",
]


def _capture_coding_windows_worker_semantics_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    store: PackageWindowsEpochRuntimeLeaseRegistry | PackageWindowsRuntimeQuiescenceV1,
    quiescence: PackageWindowsRuntimeQuiescenceV1,
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
    allow_preparation_stage: bool = False,
    allow_checkpoint_stage: bool = False,
    allow_base_stage: bool = False,
) -> Callable[[], CodingWindowsWorkerHistorySemanticReadV1]:
    """Bind nominal record/recovery families to the shared capture owner."""
    return capture_windows_product_worker_history_semantics_under_guard(
        product,
        semantic_type=CodingWindowsWorkerHistorySemanticReadV1,
        settlement_type=CodingWindowsWorkerGcHistoryAuthority,
        recovery_reader=_inspect_coding_windows_product_worker_offline_recovery_under_gc_guard,
        store=store,
        quiescence=quiescence,
        gc_snapshot=gc_snapshot,
        allow_preparation_stage=allow_preparation_stage,
        allow_checkpoint_stage=allow_checkpoint_stage,
        allow_base_stage=allow_base_stage,
    )
