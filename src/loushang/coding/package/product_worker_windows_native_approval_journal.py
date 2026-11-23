"""Inert Windows custody for Worker native-release approval decisions.

The Product caller pins the private state-root descriptor and holds its GC
gate. This journal records decisions only; it never identifies backend bytes,
installs a release, or grants launch authority.
"""

from __future__ import annotations

from loushang.harness.worker.history._windows_record_journals import (
    WindowsNativeApprovalRecords,
)

from .product_worker_native_approval import (
    CodingWorkerNativeApprovalDecisionV1,
    CodingWorkerNativeReleaseApprovalV1,
    _decode_coding_worker_native_approval_history,
    _native_approval_failure,
)


class CodingWindowsWorkerNativeApprovalJournal(
    WindowsNativeApprovalRecords[
        CodingWorkerNativeReleaseApprovalV1, CodingWorkerNativeApprovalDecisionV1
    ]
):
    """Strict append-only native approval history under one pinned root."""

    _failure = staticmethod(_native_approval_failure)
    _decoder = staticmethod(
        lambda raw, *, path, scope_id: _decode_coding_worker_native_approval_history(
            raw, path=path, scope_id=scope_id
        )
    )
    _create_decision = staticmethod(CodingWorkerNativeApprovalDecisionV1.create)
    _approval_type = CodingWorkerNativeReleaseApprovalV1


__all__ = ["CodingWindowsWorkerNativeApprovalJournal"]
