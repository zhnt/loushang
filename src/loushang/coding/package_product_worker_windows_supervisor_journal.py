"""Coding admission and limits for shared Windows Supervisor custody."""

from __future__ import annotations

import os

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_product_journals import (
    WindowsSupervisorJournal,
)

from ._worker_history_access import _CodingWindowsHistoryAccess

_NAME = "worker-supervisor.jsonl"
_LOCK = _NAME + ".lock"
_MAX_RECORDS = 4096
_MAX_BYTES = 16 * 1024 * 1024


class CodingWindowsProductWorkerSupervisorJournal(WindowsSupervisorJournal):
    """Reuse the Supervisor state machine with Product-pinned native I/O."""

    _max_bytes = staticmethod(lambda: _MAX_BYTES)
    _max_records = staticmethod(lambda: _MAX_RECORDS)

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or product.policy.product_id != "coding"
        ):
            raise ValueError("Windows Worker Supervisor Product owner is invalid")
        product.assert_root_gc_authority_current()
        super().__init__(
            product.state_root / _NAME, access=_CodingWindowsHistoryAccess(product)
        )


def open_coding_windows_product_worker_supervisor_journal(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsProductWorkerSupervisorJournal:
    return CodingWindowsProductWorkerSupervisorJournal(product)


__all__ = [
    "CodingWindowsProductWorkerSupervisorJournal",
    "open_coding_windows_product_worker_supervisor_journal",
]
