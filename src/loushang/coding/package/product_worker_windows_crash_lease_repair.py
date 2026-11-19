"""Repair a crashed Windows Worker lease after both native and process settlement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)

from .product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashLeaseRepairReviewV1:
    """Time-bound evidence; Package rechecks it before appending repair."""

    orphan_review: CodingWindowsWorkerOrphanRuntimeReviewV1
    native_revision: int
    native_spec_fingerprint: str
    payload_directory_identity: tuple[int, int]


def review_coding_windows_product_worker_crash_lease_repair(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerCrashLeaseRepairReviewV1:
    """Observe an orphan with complete native and Supervisor settlement."""
    from .product_worker_windows_crash_recovery import _recovery_program

    return cast(
        "CodingWindowsWorkerCrashLeaseRepairReviewV1",
        _recovery_program().review_lease(product, attempt_id=attempt_id),
    )


def repair_coding_windows_product_worker_crash_orphan_runtime(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashLeaseRepairReviewV1,
) -> PackageEpochRuntimeLeaseV1:
    """Recheck settlement under Package→Product locks before lease repair."""
    from .product_worker_windows_crash_recovery import _recovery_program

    return cast(
        "PackageEpochRuntimeLeaseV1",
        _recovery_program().repair_lease(product, expected_review=expected_review),
    )


__all__ = [
    "CodingWindowsWorkerCrashLeaseRepairReviewV1",
    "repair_coding_windows_product_worker_crash_orphan_runtime",
    "review_coding_windows_product_worker_crash_lease_repair",
]
