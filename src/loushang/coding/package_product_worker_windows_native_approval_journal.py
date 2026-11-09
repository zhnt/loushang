"""Inert Windows custody for Worker native-release approval decisions.

The Product caller pins the private state-root descriptor and holds its GC
gate. This journal records decisions only; it never identifies backend bytes,
installs a release, or grants launch authority.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from loushang.harness.worker.history._windows_record_journals import (
    WindowsNativeApprovalRecords,
)

from .package_product_worker_native_approval import (
    CodingWorkerNativeApprovalDecisionV1,
    CodingWorkerNativeApprovalError,
    CodingWorkerNativeReleaseApprovalV1,
    _decode_coding_worker_native_approval_history,
)

_NAME = "worker-native-release-approvals.jsonl"
_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?\Z")
_MAX_EVENTS = 256
_MAX_BYTES = 4 * 1024 * 1024


class CodingWindowsWorkerNativeApprovalJournal(
    WindowsNativeApprovalRecords[
        CodingWorkerNativeReleaseApprovalV1, CodingWorkerNativeApprovalDecisionV1
    ]
):
    """Strict append-only native approval history under one pinned root."""

    _name = _NAME
    _label = "Windows Worker native approval"
    _scope_pattern = _OPAQUE
    _failure = staticmethod(
        lambda code: CodingWorkerNativeApprovalError(
            "coding_worker_native_approval_" + code
        )
    )
    _decoder = staticmethod(
        lambda raw, *, path, scope_id: _decode_coding_worker_native_approval_history(
            raw, path=path, scope_id=scope_id
        )
    )
    _max_bytes = staticmethod(lambda: _MAX_BYTES)
    _max_events = staticmethod(lambda: _MAX_EVENTS)
    _append_error = "Windows Worker native approval append stalled"
    _create_decision = staticmethod(CodingWorkerNativeApprovalDecisionV1.create)
    _approval_type = CodingWorkerNativeReleaseApprovalV1

    @property
    def path(self) -> Path:
        return self._path

    def current(
        self, *, directory_fd: int
    ) -> CodingWorkerNativeApprovalDecisionV1 | None:
        events = self.history_read_only(directory_fd=directory_fd)
        return events[-1] if events else None

    def history_read_only(
        self, *, directory_fd: int
    ) -> tuple[CodingWorkerNativeApprovalDecisionV1, ...]:
        "Replay the complete exact approval history without changing custody."
        return self._read_records(directory_fd=directory_fd)

    def change(
        self,
        *,
        directory_fd: int,
        operation_id: str,
        expected_generation: int,
        action: Literal["approve", "revoke"],
        approval: CodingWorkerNativeReleaseApprovalV1 | None,
    ) -> CodingWorkerNativeApprovalDecisionV1:
        return self._change(
            directory_fd=directory_fd,
            operation_id=operation_id,
            expected_generation=expected_generation,
            action=action,
            approval=approval,
        )

    @staticmethod
    def _require_root(directory_fd: int) -> None:
        if os.name != "nt" or type(directory_fd) is not int or directory_fd < 0:
            raise OSError("Windows Worker approval requires a pinned Product root")


__all__ = ["CodingWindowsWorkerNativeApprovalJournal"]
