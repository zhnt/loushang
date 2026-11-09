"""Coding policy and access binding for the shared rooted Worker Supervisor."""

from __future__ import annotations

import os

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._rooted_supervisor import RootedSupervisorJournal
from loushang.harness.worker.history._supervisor import _MAX_BYTES, _MAX_RECORDS

from ._worker_history_access import _CodingHistoryAccess as _CodingHistoryAccess


class CodingProductWorkerSupervisorJournal(RootedSupervisorJournal):
    """Keep original Coding admission while the Worker owns history mechanics."""

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        if os.name != "posix":
            raise RuntimeError("Coding Worker POSIX Supervisor journal is unavailable")
        if (
            not isinstance(product, PosixLocalWheelProductSessionOwner)
            or product.policy.product_id != "coding"
        ):
            raise TypeError("Coding Worker Product owner is required")
        # Resolve the original path before loading the pure, fixed value family.
        path = product.state_root / "worker-supervisor.jsonl"
        from .package_product_worker_history_read_v2 import _HISTORY_READER

        super().__init__(
            path, access=_CodingHistoryAccess(product), history_reader=_HISTORY_READER
        )

    def _max_history_bytes(self) -> int:
        return _MAX_BYTES

    def _max_history_records(self) -> int:
        return _MAX_RECORDS


__all__ = ["CodingProductWorkerSupervisorJournal"]
