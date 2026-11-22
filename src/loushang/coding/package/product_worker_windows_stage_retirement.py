"""Offline, receipt-backed retirement of a clean Windows Worker stage.

Only a complete stage with settled native provisioning and a clean Supervisor
stop is accepted. A durable exact review precedes every deletion. Interrupted
member deletion is resumed from that review and never broadens its file set.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loushang.harness.package_product._windows_worker_retirement import (
    WindowsProductWorkerCompleteStageRetirement,
    has_other_windows_worker_retirement_artifact,
    windows_worker_stage_exists,
)
from loushang.harness.package_product._worker_windows_attempt import (
    WindowsWorkerRetirementRecords,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.worker.history._base_codec import _unchanged
from loushang.harness.worker.history._windows_recovery import (
    _WindowsStageRetirementReceiptMethods,
)

from .legacy_windows_receipt import _receipt_io, read_windows_private_receipt
from .product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .product_worker_windows_stage_review import (
    CodingWindowsWorkerStageReviewV1,
    _inspection,
    _review_complete_stage_under_gc_guard,
)


class CodingWindowsWorkerStageRetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerStageRetirementReceiptV1(
    _WindowsStageRetirementReceiptMethods
):
    _wire_label = "Worker stage retirement receipt"
    _wire_lists = ("stageIdentity",)
    _wire_error_type = CodingWindowsWorkerStageRetirementError
    _wire_error_code = "coding_worker_stage_retirement_receipt_invalid"
    _wire_invalid_encoding = "bytes changed"

    attempt_id: str
    review_fingerprint: str
    stage_identity: tuple[int, int]
    receipt_version: int = 1


CodingWindowsWorkerStageRetirementReceiptV1._wire_schema = RecordSchema.for_dataclass(
    CodingWindowsWorkerStageRetirementReceiptV1,
    _unchanged,
    RecordField("stage_identity", decoder=tuple),
)


def _read_retirement_bytes(path: Path, maximum_bytes: int) -> bytes | None:
    return read_windows_private_receipt(
        path, maximum_bytes=maximum_bytes, allow_unpublished_stage=True
    )


_records = WindowsWorkerRetirementRecords(
    stem="worker-stage",
    review_type=CodingWindowsWorkerStageReviewV1,
    receipt_type=CodingWindowsWorkerStageRetirementReceiptV1,
    read_bytes=_read_retirement_bytes,
    error_type=CodingWindowsWorkerStageRetirementError,
    start_invalid="coding_worker_stage_retirement_start_invalid",
    root_intent_invalid="coding_worker_stage_retirement_root_intent_invalid",
    receipt_invalid="coding_worker_stage_retirement_receipt_invalid",
)
_start_path = _records.start_path
_read_review = _records.read_start
_read_receipt = _records.read_receipt


__all__ = [
    "CodingWindowsWorkerStageRetirementError",
    "CodingWindowsWorkerStageRetirementReceiptV1",
    "retire_coding_windows_product_worker_complete_stage",
]


_operations = WindowsProductWorkerCompleteStageRetirement(
    records=_records,
    io=_receipt_io,
    inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
    read_intent=_read_intent_under_gc_guard,
    review_stage=_review_complete_stage_under_gc_guard,
    inspection=_inspection,
    error_prefix="coding_worker_stage_retirement",
    entry_product_id="coding",
    entry_required_message="Windows Worker stage retirement requires a Product review",
)


_require_completed_retirement_under_gc_guard = _operations.require_completed
_review_for_retry = _operations.review_for_retry
_remove_remaining_stage = _operations.remove_remaining
_retirement = _operations.physical
_inspect_retirement_attempt_ids_under_gc_guard = _operations.inspect_attempt_ids
_retirement_attempt_ids_from_names = _operations.attempt_ids_from_names
_stage_exists = windows_worker_stage_exists
_has_other_retirement_artifact = has_other_windows_worker_retirement_artifact


retire_coding_windows_product_worker_complete_stage = _operations.retire
