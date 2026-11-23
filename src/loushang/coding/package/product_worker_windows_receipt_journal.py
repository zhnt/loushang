"""Windows-private append-only custody for Product Worker receipts."""

from __future__ import annotations

from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.worker.history._windows_record_journals import (
    WindowsReceiptRecords,
)

from .product_worker_receipt import (
    CodingWorkerReceiptError,
    CodingWorkerReceiptRecordV1,
    _decode_coding_worker_receipt_history,
)


class CodingWindowsWorkerReceiptJournal(
    WindowsReceiptRecords[CodingWorkerReceiptRecordV1]
):
    """Keep one Product scope's issued receipts under a pinned Windows root."""

    _failure = staticmethod(
        lambda code: CodingWorkerReceiptError("coding_worker_receipt_" + code)
    )
    _decoder = staticmethod(
        lambda raw, *, path, scope_id: _decode_coding_worker_receipt_history(
            raw,
            path=path,
            scope_id=scope_id,
            load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
        )
    )
    _record_type = CodingWorkerReceiptRecordV1


__all__ = ["CodingWindowsWorkerReceiptJournal"]
