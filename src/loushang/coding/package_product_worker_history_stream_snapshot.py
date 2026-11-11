"""Authenticated Linux Product Worker snapshots for retention checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.coding._worker_history_access import _CodingHistoryAccess
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS as CODING_WORKER_HISTORY_STREAM_STEMS,
)
from loushang.harness.worker.history._snapshot import (
    _is_v2_authenticated_prefix as _is_v2_authenticated_prefix,
)
from loushang.harness.worker.history._snapshot import (
    _SnapshotMethods,
)
from loushang.harness.worker.history._snapshot import (
    _stream_fingerprint as _stream_fingerprint,
)
from loushang.harness.worker.history._snapshot_io import (
    RetainedSnapshotReader,
    SnapshotHistory,
)

from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)

_MAX_SEGMENT_BYTES = 32 * 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerHistoryStreamSnapshotV1(_SnapshotMethods):
    stem: str
    active_generation: int
    last_sealed_revision: int
    total_revision: int
    segment_byte_counts: tuple[int, ...]
    segment_digests: tuple[str, ...]
    fingerprint: str


CodingWorkerHistoryStreamSnapshotV1._snapshot_type = CodingWorkerHistoryStreamSnapshotV1


def read_coding_worker_histories_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerSegmentedHistoryV1, ...]:
    """Read all five strict V1 streams under Product GC admission."""
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker history streams require their Product")
    return _snapshot_source().read_histories(_CodingHistoryAccess(product))


def capture_coding_worker_history_streams_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[CodingWorkerHistoryStreamSnapshotV1, ...]:
    """Capture all five strict streams while Product GC admission is held."""
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker history streams require their Product")
    return cast(
        tuple[CodingWorkerHistoryStreamSnapshotV1, ...],
        _snapshot_source().capture(_CodingHistoryAccess(product)),
    )


def verify_coding_worker_history_stream_extensions_under_gc_guard(
    product: PosixLocalWheelProductSessionOwner,
    *,
    previous: tuple[CodingWorkerHistoryStreamSnapshotV1, ...],
    current: tuple[CodingWorkerHistoryStreamSnapshotV1, ...],
) -> bool:
    """Reopen all five exact streams and prove their checkpointed byte prefixes."""
    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or tuple((item.stem for item in previous)) != CODING_WORKER_HISTORY_STREAM_STEMS
        or (
            tuple((item.stem for item in current)) != CODING_WORKER_HISTORY_STREAM_STEMS
        )
    ):
        raise ValueError("Coding Worker stream extension requires its Product")
    return _snapshot_source().verify_extensions(
        _CodingHistoryAccess(product), previous=previous, current=current
    )


__all__ = [
    "CODING_WORKER_HISTORY_STREAM_STEMS",
    "CodingWorkerHistoryStreamSnapshotV1",
    "capture_coding_worker_history_streams_under_gc_guard",
    "read_coding_worker_histories_under_gc_guard",
    "verify_coding_worker_history_stream_extensions_under_gc_guard",
]


def _snapshot_source() -> SnapshotHistory:
    return SnapshotHistory(
        CodingWorkerHistoryStreamSnapshotV1,
        _retained_snapshot_reader,
        _MAX_SEGMENT_BYTES,
        _MAX_MANIFEST_BYTES,
    )


def _retained_snapshot_reader() -> RetainedSnapshotReader:
    from .package_product_worker_history_read_v2 import _HISTORY_READER

    return _HISTORY_READER
