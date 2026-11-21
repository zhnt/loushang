"""Receipt-backed retirement of a settled, never-launched Windows Worker stage."""

from __future__ import annotations

from loushang.harness.package_product._windows_worker_retirement import (
    WindowsProductWorkerUnlaunchedStageRetirement,
)

from .legacy_windows_receipt import _receipt_io
from .product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .product_worker_windows_reserved_review import (
    CodingWindowsWorkerReservedNoEffectReviewV1,
    _capture_reserved_stage,
)
from .product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementReceiptV1,
    WindowsWorkerRetirementRecords,
    _read_retirement_bytes,
    _retirement,
)
from .product_worker_windows_stage_review import _inspection


class CodingWindowsWorkerUnlaunchedRetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_records = WindowsWorkerRetirementRecords(
    stem="worker-unlaunched-stage",
    review_type=CodingWindowsWorkerReservedNoEffectReviewV1,
    receipt_type=CodingWindowsWorkerStageRetirementReceiptV1,
    read_bytes=_read_retirement_bytes,
    error_type=CodingWindowsWorkerUnlaunchedRetirementError,
    start_invalid="coding_worker_unlaunched_retirement_start_invalid",
    root_intent_invalid="coding_worker_unlaunched_retirement_receipt_invalid",
    receipt_invalid="coding_worker_unlaunched_retirement_receipt_invalid",
)


_root_intent_path = _records.root_intent_path
_read_receipt = _records.read_receipt
_read_root_intent = _records.read_root_intent


__all__ = [
    "CodingWindowsWorkerUnlaunchedRetirementError",
    "retire_coding_windows_product_worker_settled_unlaunched_stage",
]


_operations = WindowsProductWorkerUnlaunchedStageRetirement(
    records=_records,
    io=_receipt_io,
    inspection=_inspection,
    inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
    read_intent=_read_intent_under_gc_guard,
    capture_reserved=_capture_reserved_stage,
    physical=_retirement,
    error_prefix="coding_worker_unlaunched_retirement",
    entry_product_id="coding",
    entry_required_message="Windows Worker unlaunched retirement requires a Product review",
)
_require_completed_unlaunched_retirement_under_gc_guard = _operations.require_completed
_require_intent = _operations.require_intent
_remove_remaining_stage = _operations.remove_remaining
_read_start = _operations.read_start
_start_path = _operations.start_path


retire_coding_windows_product_worker_settled_unlaunched_stage = _operations.retire
