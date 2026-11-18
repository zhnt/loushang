"""Settle a crashed Windows Worker Supervisor after exact Job absence proof."""

from __future__ import annotations

from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_product_journals import (
    settle_windows_crashed_supervisor_record,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
)

from .package_product_worker_windows_crash_cleanup_review import (
    CodingWindowsWorkerCrashCleanupReviewV1,
)

_settle_crashed_supervisor_record = settle_windows_crashed_supervisor_record


def settle_coding_windows_product_worker_crash_supervisor(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashCleanupReviewV1,
) -> WorkerAttemptRecordV1 | None:
    """Write only the process-side settlement under Package→Product locks."""
    from .package_product_worker_windows_crash_recovery import _recovery_program

    return cast(
        "WorkerAttemptRecordV1 | None",
        _recovery_program().settle_supervisor(product, expected_review=expected_review),
    )


__all__ = ["settle_coding_windows_product_worker_crash_supervisor"]
