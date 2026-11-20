"""Offline review of one unlaunched, marker-absent Windows Worker stage.

This is a read-only recovery input. A retained payload directory alone is not
deletion authority; the review refuses any launch, native, or Supervisor
history and captures every direct member through Product-pinned handles.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loushang.coding.harness.worker.windows_admission import (
    is_attempt_id,
    is_windows_product,
)
from loushang.harness.package_product._windows_worker_recovery import (
    review_windows_product_worker_partial_stage,
)
from loushang.harness.package_product._worker_windows_attempt import (
    capture_windows_product_worker_partial_stage,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsPartialStageReviewMethods,
)

from .product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .product_worker_windows_stage_retirement import (
    _inspect_retirement_attempt_ids_under_gc_guard,
)
from .product_worker_windows_stage_review import FileIdentity, _inspection

_MAX_REVIEW_BYTES = 32768
_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
_MAX_DEPTH = 16
_PARTIAL_DEBTS = (
    "payload_retained",
    "launch_intent_missing",
    "native_history_missing",
    "supervisor_history_missing",
)


class CodingWindowsWorkerPartialStageReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerPartialStageReviewV1(_WindowsPartialStageReviewMethods):
    _fingerprint_domain = b"loushang.coding-windows-worker-partial-stage-review/v1\x00"
    _record_kind = "partial"
    _record_error = CodingWindowsWorkerPartialStageReviewError
    _record_error_code = "coding_worker_partial_stage_review_invalid"

    @classmethod
    def _record_maximum(cls) -> int:
        return _MAX_REVIEW_BYTES

    attempt_id: str
    lease_owner_revision: int
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    entrypoint: str | None
    executable_identity: FileIdentity | None
    executable_digest: str | None

    @classmethod
    def _payload_maximum(cls) -> int:
        return _MAX_PAYLOAD_BYTES

    @classmethod
    def _depth_maximum(cls) -> int:
        return _MAX_DEPTH


def review_coding_windows_product_worker_partial_stage(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerPartialStageReviewV1:
    """Review a marker-absent stage under exclusive Package quiescence."""

    if not is_windows_product(product, "coding", os.name) or not is_attempt_id(
        attempt_id
    ):
        raise OSError("Windows Worker partial-stage review requires a Product owner")

    return review_windows_product_worker_partial_stage(
        product,
        attempt_id=attempt_id,
        record_type=CodingWindowsWorkerPartialStageReviewV1,
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
        inspect_retirements=_inspect_retirement_attempt_ids_under_gc_guard,
        capture_partial=_review_partial_tree,
        partial_debts=_PARTIAL_DEBTS,
        error_prefix="coding_worker_partial_stage",
    )


def _review_partial_tree(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    expected_stage: tuple[int, int] | None,
    lease_owner_revision: int,
) -> CodingWindowsWorkerPartialStageReviewV1:
    return capture_windows_product_worker_partial_stage(
        product,
        attempt_id=attempt_id,
        expected_stage=expected_stage,
        inspection=_inspection(),
        max_payload_bytes=_MAX_PAYLOAD_BYTES,
        max_depth=_MAX_DEPTH,
        marker_name="worker-payload.json",
        error_type=CodingWindowsWorkerPartialStageReviewError,
        error_prefix="coding_worker_partial_stage",
        result_factory=lambda captured: CodingWindowsWorkerPartialStageReviewV1(
            attempt_id=attempt_id,
            lease_owner_revision=lease_owner_revision,
            stage_identity=captured.stage_identity,
            directory_identities=captured.directory_identities,
            entrypoint=captured.entrypoint,
            executable_identity=captured.executable_identity,
            executable_digest=captured.executable_digest,
        ),
    )


__all__ = [
    "CodingWindowsWorkerPartialStageReviewError",
    "CodingWindowsWorkerPartialStageReviewV1",
    "review_coding_windows_product_worker_partial_stage",
]


CodingWindowsWorkerPartialStageReviewV1._bind_record_schema()
