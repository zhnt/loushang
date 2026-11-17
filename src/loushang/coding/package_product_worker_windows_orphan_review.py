"""Read-only Windows Product join for one crashed Worker runtime lease.

This review does not prove the original Job is empty or authorize a lease
repair, native cleanup, payload retirement, or another Worker launch.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_recovery import (
    read_windows_product_worker_orphan_runtime,
    repair_windows_product_worker_clean_exit_orphan,
)
from loushang.harness.package_product._worker_windows_attempt import (
    capture_windows_product_worker_orphan_runtime,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.worker.history._windows_recovery import (
    _WindowsOrphanRuntimeReviewMethods,
)
from loushang.hosting import observe_windows_worker_job_absent

from .package_product_worker_receipt import CodingWorkerReceiptRecordV1
from .package_product_worker_windows_receipt_journal import (
    CodingWindowsWorkerReceiptJournal,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerOrphanRuntimeReviewV1(_WindowsOrphanRuntimeReviewMethods):
    """Observed identities only; every writeback needs a fresh native proof."""

    attempt_id: str
    attempt: CodingWindowsWorkerRecoveryAttemptV1 | None
    receipt_record: CodingWorkerReceiptRecordV1 | None
    orphan_leases: tuple[PackageEpochRuntimeLeaseV1, ...]
    runtime_epoch: int
    store_root_identity: str
    native_job_absent: bool | None = None


def review_coding_windows_product_worker_orphan_runtime(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerOrphanRuntimeReviewV1:
    """Join strict persisted facts without creating or settling Worker state."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Windows Worker orphan review requires an exact Product")
    return read_windows_product_worker_orphan_runtime(
        product,
        attempt_id=attempt_id,
        review_runtime=_review_under_gc_guard,
    )


def repair_coding_windows_product_worker_clean_exit_orphan_runtime(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerOrphanRuntimeReviewV1,
) -> PackageEpochRuntimeLeaseV1:
    """Repair only a fully settled Worker whose Product runtime died later."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerOrphanRuntimeReviewV1
    ):
        raise ValueError(
            "Windows Worker clean-exit repair requires exact Product proof"
        )
    if not expected_review.clean_exit_repair_candidate:
        raise ValueError("Windows Worker clean-exit repair is unproven")
    return repair_windows_product_worker_clean_exit_orphan(
        product,
        expected_review=expected_review,
        review_runtime=_review_under_gc_guard,
    )


def _review_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    orphans: tuple[PackageEpochRuntimeLeaseV1, ...],
) -> CodingWindowsWorkerOrphanRuntimeReviewV1:
    """Read Product facts with the caller's Package-before-GC lock order."""
    return capture_windows_product_worker_orphan_runtime(
        product,
        attempt_id=attempt_id,
        orphans=orphans,
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
        receipt_journal=CodingWindowsWorkerReceiptJournal,
        observe_job_absent=observe_windows_worker_job_absent,
        review_type=CodingWindowsWorkerOrphanRuntimeReviewV1,
    )


__all__ = [
    "CodingWindowsWorkerOrphanRuntimeReviewV1",
    "repair_coding_windows_product_worker_clean_exit_orphan_runtime",
    "review_coding_windows_product_worker_orphan_runtime",
]
