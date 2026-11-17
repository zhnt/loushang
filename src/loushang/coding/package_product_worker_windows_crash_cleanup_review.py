"""Read-only Product proof for a retained Windows LPAC crash cleanup attempt.

This review never carries a native spec or grants a cleanup effect. A writer
must repeat every observation while holding its Package and Product locks.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from loushang.harness.package_product._windows_worker_recovery import (
    review_windows_product_worker_crash_cleanup,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_recovery import (
    _valid_crash_effect_history as _worker_crash_effect_history,
)
from loushang.harness.worker.history._windows_recovery import (
    windows_worker_crash_cleanup_history_matches,
    windows_worker_crash_settled_history_matches,
)

from .package_product_worker_windows_orphan_review import (
    CodingWindowsWorkerOrphanRuntimeReviewV1,
    _review_under_gc_guard,
)
from .package_product_worker_windows_provisioning import (
    inspect_coding_windows_product_worker_provisioning_attempts,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


class CodingWindowsWorkerCrashCleanupReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerCrashCleanupReviewV1:
    """One time-bound observation; it grants no native cleanup authority."""

    orphan_review: CodingWindowsWorkerOrphanRuntimeReviewV1
    native_revision: int
    native_spec_fingerprint: str
    payload_directory_identity: tuple[int, int]


def _valid_crash_cleanup_history(
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> bool:
    return _valid_crash_effect_history(attempt, settled=False)


def _valid_crash_native_settlement_history(
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> bool:
    return _valid_crash_effect_history(attempt, settled=True)


def _valid_crash_effect_history(
    attempt: CodingWindowsWorkerRecoveryAttemptV1, *, settled: bool
) -> bool:
    return _worker_crash_effect_history(attempt, settled=settled)


def _crash_cleanup_history_matches(
    review: CodingWindowsWorkerOrphanRuntimeReviewV1,
) -> bool:
    return windows_worker_crash_cleanup_history_matches(review)


def _crash_settled_history_matches(
    review: CodingWindowsWorkerOrphanRuntimeReviewV1,
    *,
    repaired_lease: bool = False,
) -> bool:
    return windows_worker_crash_settled_history_matches(
        review, repaired_lease=repaired_lease
    )


def review_coding_windows_product_worker_crash_cleanup(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWindowsWorkerCrashCleanupReviewV1:
    """Join an orphan, exact stage and current LPAC spec without an effect."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError("Windows Worker crash cleanup review requires a Product")
    return review_windows_product_worker_crash_cleanup(
        product,
        attempt_id=attempt_id,
        record_type=CodingWindowsWorkerCrashCleanupReviewV1,
        review_runtime=_review_under_gc_guard,
        inspect_native=inspect_coding_windows_product_worker_provisioning_attempts,
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
        error_type=CodingWindowsWorkerCrashCleanupReviewError,
        error_prefix="coding_worker_crash_cleanup",
    )


__all__ = [
    "CodingWindowsWorkerCrashCleanupReviewError",
    "CodingWindowsWorkerCrashCleanupReviewV1",
    "review_coding_windows_product_worker_crash_cleanup",
]
