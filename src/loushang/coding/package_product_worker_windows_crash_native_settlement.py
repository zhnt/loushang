"""Product-guarded native cleanup for one orphaned Windows Worker attempt.

This settles only LPAC profile and grant debt. Supervisor, Package lease and
payload retirement remain separate Product decisions and cannot be inferred
from this native settlement alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_product_worker_windows_crash_cleanup_review import (
    CodingWindowsWorkerCrashCleanupReviewV1,
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
    from .package_product_worker_windows_crash_recovery import _recovery_program

    return cast(
        "CodingWindowsWorkerCrashNativeSettlementV1",
        _recovery_program().settle_native(product, expected_review=expected_review),
    )


__all__ = [
    "CodingWindowsWorkerCrashNativeSettlementV1",
    "settle_coding_windows_product_worker_crash_native",
]
