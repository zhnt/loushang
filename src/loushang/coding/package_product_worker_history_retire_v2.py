"""Durably retire only Worker V2 generations named by the Product owner."""

from __future__ import annotations

import sys

from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._publication import HistoryPublication
from loushang.harness.worker.history._read_v2 import (
    _MAX_HEAD_BYTES as _MAX_HEAD_BYTES,
)
from loushang.harness.worker.history._read_v2 import (
    _MAX_LEDGER_BYTES as _MAX_LEDGER_BYTES,
)
from loushang.harness.worker.history._read_v2 import (
    _MAX_SEGMENT_BYTES as _MAX_SEGMENT_BYTES,
)

from .package_product_worker_history_read_v2 import (
    _HISTORY_READER,
)
from .package_product_worker_history_v2_names import (
    DELETION_LEDGER_NAME,
)

_HISTORY_PUBLICATION = HistoryPublication(_HISTORY_READER)


class CodingWorkerV2RetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def retire_coding_worker_v2_history_under_guard(rooted: RootedFile) -> bool:
    """Write exact deletion debt before unlinking any retired source bytes."""
    from . import package_product_worker_history_stage_v2 as preparation

    return _HISTORY_PUBLICATION.retire_under_guard(
        rooted,
        error_type=CodingWorkerV2RetirementError,
        max_segment_bytes=_MAX_SEGMENT_BYTES,
        max_head_bytes=_MAX_HEAD_BYTES,
        max_ledger_bytes=_MAX_LEDGER_BYTES,
        max_intent_bytes=preparation._MAX_INTENT_BYTES,
        max_base_bytes=preparation._MAX_BASE_BYTES,
        max_stream_bytes=preparation._MAX_STREAM_BYTES,
        max_index_bytes=preparation._MAX_INDEX_BYTES,
    )


def retire_coding_product_worker_v2_history(
    product: PosixLocalWheelProductSessionOwner,
) -> bool:
    """Retire owner-authorized bytes under Product runtime and GC custody."""

    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 retirement requires its Linux Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWorkerV2RetirementError("coding_worker_v2_runtime_active")
        with product.gc_gate.guard(require_write=True):
            product.assert_root_gc_authority_current()
            with product.pinned_state_root_gc_read() as root_fd:
                with RootedFileIO(product.state_root, root_fd) as file_io:
                    with file_io.bind(
                        product.state_root / DELETION_LEDGER_NAME, durable=True
                    ) as rooted:
                        result = retire_coding_worker_v2_history_under_guard(rooted)
            product.assert_root_gc_authority_current()
            return result


__all__ = [
    "CodingWorkerV2RetirementError",
    "retire_coding_product_worker_v2_history",
    "retire_coding_worker_v2_history_under_guard",
]
