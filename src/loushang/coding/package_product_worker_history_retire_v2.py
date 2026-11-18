"""Durably retire only Worker V2 generations named by the Product owner."""

from __future__ import annotations

import sys

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.package_product._linux_worker_history import (
    retire_product_history,
)
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

_HISTORY_PUBLICATION = HistoryPublication(_HISTORY_READER)


class CodingWorkerV2RetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _retirement_limits() -> dict[str, int]:
    from . import package_product_worker_history_stage_v2 as preparation

    return dict(
        max_segment_bytes=_MAX_SEGMENT_BYTES,
        max_head_bytes=_MAX_HEAD_BYTES,
        max_ledger_bytes=_MAX_LEDGER_BYTES,
        max_intent_bytes=preparation._MAX_INTENT_BYTES,
        max_base_bytes=preparation._MAX_BASE_BYTES,
        max_stream_bytes=preparation._MAX_STREAM_BYTES,
        max_index_bytes=preparation._MAX_INDEX_BYTES,
    )


def retire_coding_worker_v2_history_under_guard(rooted: RootedFile) -> bool:
    """Write exact deletion debt before unlinking any retired source bytes."""
    return _HISTORY_PUBLICATION.retire_under_guard(
        rooted, error_type=CodingWorkerV2RetirementError, **_retirement_limits()
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
    return retire_product_history(
        product,
        publication=_HISTORY_PUBLICATION,
        error_type=CodingWorkerV2RetirementError,
        limits=_retirement_limits,
    )


__all__ = [
    "CodingWorkerV2RetirementError",
    "retire_coding_product_worker_v2_history",
    "retire_coding_worker_v2_history_under_guard",
]
