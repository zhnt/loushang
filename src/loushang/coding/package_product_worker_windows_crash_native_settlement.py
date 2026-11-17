"""Product-guarded native cleanup for one orphaned Windows Worker attempt.

This settles only LPAC profile and grant debt. Supervisor, Package lease and
payload retirement remain separate Product decisions and cannot be inferred
from this native settlement alone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_recovery import (
    settle_windows_product_worker_crash_native,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_product_worker_windows_crash_cleanup_review import (
    CodingWindowsWorkerCrashCleanupReviewV1,
)
from .package_product_worker_windows_installed_backend import (
    read_coding_windows_worker_installed_backend_release,
)
from .package_product_worker_windows_orphan_review import _review_under_gc_guard
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashNativeSettlementV1:
    attempt_id: str
    native_revision: int
    spec_fingerprint: str


def settle_coding_windows_product_worker_crash_native(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashCleanupReviewV1,
) -> CodingWindowsWorkerCrashNativeSettlementV1:
    """Recheck exact Product evidence under Package→GC locks before effects."""
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or (type(expected_review) is not CodingWindowsWorkerCrashCleanupReviewV1)
        or (len(expected_review.orphan_review.orphan_leases) != 1)
    ):
        raise ValueError("Windows Worker crash settlement requires exact Product proof")
    return settle_windows_product_worker_crash_native(
        product,
        expected_review=expected_review,
        review_runtime=_review_under_gc_guard,
        inspect_native=inspect_coding_windows_product_worker_provisioning_attempts,
        read_backend=read_coding_windows_worker_installed_backend_release,
        settlement_type=CodingWindowsWorkerCrashNativeSettlementV1,
    )


__all__ = [
    "CodingWindowsWorkerCrashNativeSettlementV1",
    "settle_coding_windows_product_worker_crash_native",
]
