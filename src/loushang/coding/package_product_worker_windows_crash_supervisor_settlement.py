"""Settle a crashed Windows Worker Supervisor after exact Job absence proof."""

from __future__ import annotations

import os

from loushang.harness.package_product._windows_worker_recovery import (
    settle_windows_product_worker_crash_supervisor,
)
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
from .package_product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .package_product_worker_windows_orphan_review import _review_under_gc_guard
from .package_product_worker_windows_recovery_inventory import (
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .package_product_worker_windows_supervisor_journal import (
    open_coding_windows_product_worker_supervisor_journal,
)

_settle_crashed_supervisor_record = settle_windows_crashed_supervisor_record


def settle_coding_windows_product_worker_crash_supervisor(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerCrashCleanupReviewV1,
) -> WorkerAttemptRecordV1 | None:
    """Write only the process-side settlement under Package→Product locks."""
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or (type(expected_review) is not CodingWindowsWorkerCrashCleanupReviewV1)
        or (len(expected_review.orphan_review.orphan_leases) != 1)
    ):
        raise ValueError("Windows Worker crash Supervisor requires exact Product proof")
    return settle_windows_product_worker_crash_supervisor(
        product,
        expected_review=expected_review,
        review_runtime=_review_under_gc_guard,
        read_intent=_read_intent_under_gc_guard,
        supervisor_journal=open_coding_windows_product_worker_supervisor_journal,
        inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
    )


__all__ = ["settle_coding_windows_product_worker_crash_supervisor"]
