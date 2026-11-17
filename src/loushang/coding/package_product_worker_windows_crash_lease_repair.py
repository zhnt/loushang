"""Repair a crashed Windows Worker lease after both native and process settlement."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_recovery import (
    WindowsProductWorkerCrashLeaseRepair,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)

from .package_product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
    _review_under_gc_guard,
)
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


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
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or (type(attempt_id) is not str)
        or (_ATTEMPT.fullmatch(attempt_id) is None)
    ):
        raise ValueError("Windows Worker crash lease review requires exact Product")
    return WindowsProductWorkerCrashLeaseRepair(
        record_type=CodingWindowsWorkerCrashLeaseRepairReviewV1,
        review_runtime=_review_under_gc_guard,
        inspect_native=inspect_coding_windows_product_worker_provisioning_attempts,
    ).review(product, attempt_id=attempt_id)


def repair_coding_windows_product_worker_crash_orphan_runtime(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashLeaseRepairReviewV1,
) -> PackageEpochRuntimeLeaseV1:
    """Recheck settlement under Package→Product locks before lease repair."""
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or (type(expected_review) is not CodingWindowsWorkerCrashLeaseRepairReviewV1)
        or (len(expected_review.orphan_review.orphan_leases) != 1)
    ):
        raise ValueError(
            "Windows Worker crash lease repair requires exact Product proof"
        )
    return WindowsProductWorkerCrashLeaseRepair(
        record_type=CodingWindowsWorkerCrashLeaseRepairReviewV1,
        review_runtime=_review_under_gc_guard,
        inspect_native=inspect_coding_windows_product_worker_provisioning_attempts,
    ).repair(product, expected_review=expected_review)


__all__ = [
    "CodingWindowsWorkerCrashLeaseRepairReviewV1",
    "repair_coding_windows_product_worker_crash_orphan_runtime",
    "review_coding_windows_product_worker_crash_lease_repair",
]
