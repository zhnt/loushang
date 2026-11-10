"""Windows-private append-only custody for Product Worker receipts."""

from __future__ import annotations

from loushang.harness.journal import JournalLoadPolicy
from loushang.harness.worker.history._windows_record_journals import (
    WindowsReceiptRecords,
)
from loushang.harness.worker.product_activation import (
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)

from .package_product_worker_receipt import (
    CodingWorkerReceiptError,
    CodingWorkerReceiptRecordV1,
    _decode_coding_worker_receipt_history,
)

_NAME = "worker-activation-receipts.jsonl"
_MAX_RECEIPTS = 4096
_MAX_BYTES = 32 * 1024 * 1024


class CodingWindowsWorkerReceiptJournal(
    WindowsReceiptRecords[CodingWorkerReceiptRecordV1]
):
    """Keep one Product scope's issued receipts under a pinned Windows root."""

    _name = _NAME
    _label = "Windows Worker receipt"
    _scope_pattern = None
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
    _max_bytes = staticmethod(lambda: _MAX_BYTES)
    _max_events = staticmethod(lambda: _MAX_RECEIPTS)
    _append_error = "Windows Worker receipt append made no progress"
    _root_error = "Windows Worker receipt requires a pinned Product root"
    _record_type = CodingWorkerReceiptRecordV1

    def records(self, *, directory_fd: int) -> tuple[CodingWorkerReceiptRecordV1, ...]:
        "Read without creating any journal or lock state."
        return self._read_records(directory_fd=directory_fd)

    def issue(
        self,
        *,
        directory_fd: int,
        policy: ProductWorkerActivationPolicyV1,
        opt_in_decision_digest: str,
    ) -> ProductWorkerActivationReceiptV1:
        "Append or return an exact current policy receipt under one lock."
        return self._issue(
            directory_fd=directory_fd,
            policy=policy,
            opt_in_decision_digest=opt_in_decision_digest,
        )


__all__ = ["CodingWindowsWorkerReceiptJournal"]
