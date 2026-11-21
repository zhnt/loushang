"""Receipt-backed deletion of a fully settled Windows Worker crash stage."""

from __future__ import annotations

from typing import cast

from loushang.harness.package_product._windows_worker_retirement import (
    WindowsProductWorkerCrashStageRetirement,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .legacy_windows_receipt import _receipt_io
from .product_worker_windows_crash_stage_review import (
    CodingWindowsWorkerCrashStageReviewV1,
    _review_crash_stage_under_gc_guard,
)
from .product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .product_worker_windows_orphan_review import _review_under_gc_guard
from .product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementReceiptV1,
    WindowsWorkerRetirementRecords,
    _read_retirement_bytes,
    _remove_remaining_stage,
)
from .product_worker_windows_stage_review import _inspection


def retire_coding_windows_product_worker_crash_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashStageReviewV1,
) -> CodingWindowsWorkerStageRetirementReceiptV1:
    """Recheck durable crash proof, then delete only reviewed stage members."""
    from .product_worker_windows_crash_recovery import _recovery_program

    return cast(
        "CodingWindowsWorkerStageRetirementReceiptV1",
        _recovery_program().retire_stage(product, expected_review=expected_review),
    )


_records = WindowsWorkerRetirementRecords(
    stem="worker-crash-stage",
    review_type=CodingWindowsWorkerCrashStageReviewV1,
    receipt_type=CodingWindowsWorkerStageRetirementReceiptV1,
    read_bytes=_read_retirement_bytes,
    error_type=ValueError,
    start_invalid="Windows Worker crash stage start changed",
    root_intent_invalid="Windows Worker crash stage root intent changed",
    receipt_invalid="Windows Worker crash stage receipt changed",
)
_start_path = _records.start_path
_read_start = _records.read_start
_receipt_path = _records.receipt_path
_root_intent_path = _records.root_intent_path
_read_receipt = _records.read_receipt
_read_root_intent = _records.read_root_intent


__all__ = ["retire_coding_windows_product_worker_crash_stage"]


_operations = WindowsProductWorkerCrashStageRetirement(
    records=_records,
    io=_receipt_io,
    inspection=_inspection,
    review_stage=_review_crash_stage_under_gc_guard,
    review_runtime=_review_under_gc_guard,
    inspect_native=inspect_coding_windows_product_worker_provisioning_attempts,
    read_intent=_read_intent_under_gc_guard,
    remove_complete=_remove_remaining_stage,
)
_require_crash_history = _operations.require_history
_require_completed_crash_retirement_under_gc_guard = _operations.require_completed
