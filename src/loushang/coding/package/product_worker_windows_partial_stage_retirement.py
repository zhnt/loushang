"""Receipt-backed offline retirement for an unlaunched Windows Worker stage."""

from __future__ import annotations

from loushang.harness.package_product._windows_worker_retirement import (
    WindowsProductWorkerPartialStageRetirement,
)

from .legacy_windows_receipt import _receipt_io
from .product_worker_windows_partial_stage_review import (
    CodingWindowsWorkerPartialStageReviewV1,
    _review_partial_tree,
)
from .product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementReceiptV1,
    WindowsWorkerRetirementRecords,
    _read_retirement_bytes,
    _retirement,
)
from .product_worker_windows_stage_review import _inspection

_MAX_REVIEW_BYTES = 32768
_MAX_RECEIPT_BYTES = 1024


class CodingWindowsWorkerPartialStageRetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_records = WindowsWorkerRetirementRecords(
    stem="worker-partial-stage",
    review_type=CodingWindowsWorkerPartialStageReviewV1,
    receipt_type=CodingWindowsWorkerStageRetirementReceiptV1,
    review_maximum_bytes=_MAX_REVIEW_BYTES,
    receipt_maximum_bytes=_MAX_RECEIPT_BYTES,
    read_bytes=_read_retirement_bytes,
    error_type=CodingWindowsWorkerPartialStageRetirementError,
    start_invalid="coding_worker_partial_retirement_start_invalid",
    root_intent_invalid="coding_worker_partial_retirement_receipt_invalid",
    receipt_invalid="coding_worker_partial_retirement_receipt_invalid",
)
_start_path = _records.start_path
_read_start = _records.read_start
_root_intent_path = _records.root_intent_path
_read_receipt = _records.read_receipt
_read_root_intent = _records.read_root_intent


__all__ = [
    "CodingWindowsWorkerPartialStageRetirementError",
    "retire_coding_windows_product_worker_partial_stage",
]


def _review_maximum() -> int:
    return _MAX_REVIEW_BYTES


_operations = WindowsProductWorkerPartialStageRetirement(
    records=_records,
    io=_receipt_io,
    inspection=_inspection,
    review_maximum=_review_maximum,
    inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
    capture_partial=_review_partial_tree,
    physical=_retirement,
    error_prefix="coding_worker_partial_retirement",
    entry_product_id="coding",
    entry_required_message="Windows Worker partial retirement requires a Product review",
)
_require_partial_history = _operations.require_history
_require_completed_partial_retirement_under_gc_guard = _operations.require_completed
_remove_remaining_stage = _operations.remove_remaining
_full_retirement_artifact_present = _operations.other_artifact


retire_coding_windows_product_worker_partial_stage = _operations.retire
