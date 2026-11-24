"""Offline, read-only review of a cleanly stopped Windows Worker payload.

This captures exact retained bytes and identities for a later retirement
transaction. It does not claim that deletion, Job recovery, or rotation has
occurred, and it grants no filesystem mutation authority by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from loushang.foundation.windows_private_acl import (
    WindowsPrivateDirectoryAcl as WindowsPrivateDirectoryAcl,
)
from loushang.harness.package_product._windows_worker_recovery import (
    review_windows_product_worker_complete_stage_under_guard,
    review_windows_product_worker_stage_offline,
)
from loushang.harness.package_product._worker_windows_attempt import (
    CapturedWindowsWorkerStage as _CapturedStageBytesV1,  # noqa: F401
)
from loushang.harness.package_product._worker_windows_attempt import (
    capture_windows_product_worker_stage,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsCompleteStageReviewMethods,
)
from loushang.harness.worker.payload._windows_stage_io import WindowsStageInspection

from .product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentV1,
    _read_intent_under_gc_guard,
)
from .product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)

FileIdentity = tuple[int, int, int, int, int]


class CodingWindowsWorkerStageReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerStageReviewV1(_WindowsCompleteStageReviewMethods):
    _fingerprint_domain = b"loushang.coding-windows-worker-stage-review/v1\x00"
    _record_kind = "full"
    _record_error = CodingWindowsWorkerStageReviewError
    _record_error_code = "coding_worker_stage_review_record_invalid"

    attempt_id: str
    intent_fingerprint: str
    lease_owner_revision: int
    native_revision: int
    supervisor_revision: int
    entrypoint: str
    stage_identity: FileIdentity
    directory_identities: tuple[tuple[str, FileIdentity], ...]
    marker_identity: FileIdentity
    executable_identity: FileIdentity
    executable_digest: str


def review_coding_windows_product_worker_complete_stage(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerStageReviewV1:
    """Review one retained, cleanly stopped stage under offline Product locks."""

    return review_windows_product_worker_stage_offline(
        product,
        product_id="coding",
        attempt_id=attempt_id,
        role="stage",
        error_type=CodingWindowsWorkerStageReviewError,
        error_prefix="coding_worker_stage_review",
        review=lambda quiescence: _review_complete_stage_under_gc_guard(
            product,
            attempt_id=attempt_id,
            lease_owner_revision=quiescence.owner_revision,
        ),
    )


def _review_complete_stage_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    lease_owner_revision: int,
) -> CodingWindowsWorkerStageReviewV1:
    """Reuse an already-held offline Package lease and Product GC gate."""

    return review_windows_product_worker_complete_stage_under_guard(
        product,
        attempt_id=attempt_id,
        lease_owner_revision=lease_owner_revision,
        record_type=CodingWindowsWorkerStageReviewV1,
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
        read_intent=_read_intent_under_gc_guard,
        capture_stage=_capture_stage_bytes,
        error_prefix="coding_worker_stage_review",
    )


__all__ = [
    "CodingWindowsWorkerStageReviewError",
    "CodingWindowsWorkerStageReviewV1",
    "review_coding_windows_product_worker_complete_stage",
]


def _inspection() -> WindowsStageInspection:
    return WindowsStageInspection(
        CodingWindowsWorkerLaunchIntentV1,
        CodingWindowsWorkerStageReviewError,
        "coding_worker_stage_review",
        CodingWindowsWorkerStageReviewV1._payload_maximum(),
    )


_capture_stage_bytes = partial(capture_windows_product_worker_stage, inspect=_inspection)
CodingWindowsWorkerStageReviewV1._bind_record_schema()
