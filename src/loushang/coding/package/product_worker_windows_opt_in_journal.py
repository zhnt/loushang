"""Native Windows custody for inert Coding Worker opt-in decisions.

The caller supplies the Product-pinned state-root descriptor and holds its GC
gate. This journal persists decisions; it cannot derive selection or issue a
Worker activation receipt.
"""

from __future__ import annotations

from loushang.harness.worker.history._windows_record_journals import WindowsOptInRecords

from .product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournalError,
    _decode_coding_worker_opt_in_history,
)
from .product_worker_policy import CodingWorkerOptInV1


class CodingWindowsWorkerOptInJournal(
    WindowsOptInRecords[CodingWorkerOptInDecisionV1, CodingWorkerOptInV1]
):
    """Strict append-only decisions under one Product-pinned Windows root."""

    _failure = staticmethod(
        lambda code: CodingWorkerOptInJournalError("coding_worker_opt_in_" + code)
    )
    _decoder = staticmethod(
        lambda raw, *, path, scope_id: _decode_coding_worker_opt_in_history(
            raw, path=path, scope_id=scope_id
        )
    )
    _record_type = CodingWorkerOptInDecisionV1
    _opt_in_type = CodingWorkerOptInV1


__all__ = ["CodingWindowsWorkerOptInJournal"]
