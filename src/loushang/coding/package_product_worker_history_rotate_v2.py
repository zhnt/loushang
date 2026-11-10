"""Seal low-volume V1 Worker streams under Product custody for V2 cutover.

This only creates durable empty successor generations. A later Product
checkpoint and cutover preflight still decide whether any source may retire.
"""

from __future__ import annotations

import sys
from hashlib import sha256

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._publication import HistoryPublication

from ._worker_history_access import _CodingHistoryAccess
from .package_product_worker_history_checkpoint import (
    read_coding_product_worker_history_checkpoints_under_gc_guard,
)

_MAX_SEGMENT_BYTES = 32 * 1024 * 1024


class CodingWorkerV2SealError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _seal_under_guard(
    rooted: RootedFile,
    *,
    empty_supervisor_checkpointed: bool,
) -> tuple[int, ...]:
    return HistoryPublication.seal_v1_under_guard(
        rooted,
        empty_supervisor_checkpointed=empty_supervisor_checkpointed,
        error_type=CodingWorkerV2SealError,
        max_segment_bytes=_MAX_SEGMENT_BYTES,
    )


def seal_coding_product_worker_v1_history_for_v2(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[int, ...]:
    """Seal five V1 streams and return their minimal first-retained cutoffs."""

    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 sealing requires its Linux Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWorkerV2SealError("coding_worker_v2_runtime_active")
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            checkpoints = read_coding_product_worker_history_checkpoints_under_gc_guard(
                product
            )
            supervisor_snapshot = (
                None if not checkpoints else checkpoints[-1].stream_snapshots[4]
            )
            empty_supervisor_checkpointed = bool(
                supervisor_snapshot is not None
                and supervisor_snapshot.stem == "worker-supervisor"
                and supervisor_snapshot.total_revision == 0
                and supervisor_snapshot.active_generation == 0
                and supervisor_snapshot.segment_byte_counts == (0,)
                and supervisor_snapshot.segment_digests == (sha256(b"").hexdigest(),)
            )
            return HistoryPublication.seal_v1(
                _CodingHistoryAccess(product),
                empty_supervisor_checkpointed=empty_supervisor_checkpointed,
                error_type=CodingWorkerV2SealError,
                max_segment_bytes=_MAX_SEGMENT_BYTES,
            )


__all__ = [
    "CodingWorkerV2SealError",
    "seal_coding_product_worker_v1_history_for_v2",
]
