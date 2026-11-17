"""Settle a crashed Windows Worker C5 attempt after Product recovery closes it."""

from __future__ import annotations

import os

from loushang.harness.package_product._windows_worker_recovery import (
    settle_windows_product_worker_crash_c5,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_activation_state import (
    open_coding_windows_product_worker_activation_state_store,
)
from .package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from .package_product_worker_windows_cleanup_evidence import (
    CodingWindowsWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_windows_orphan_review import (
    review_coding_windows_product_worker_orphan_runtime,
)


def settle_coding_windows_product_worker_crash_c5(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Recheck a repaired crash, then retire and settle its exact C5 record."""
    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows crash C5 settlement requires its Coding Product")
    return settle_windows_product_worker_crash_c5(
        product,
        attempt_id=attempt_id,
        review_runtime=review_coding_windows_product_worker_orphan_runtime,
        activation_journal=CodingWindowsWorkerActivationStateJournal,
        evidence_factory=CodingWindowsWorkerCleanupEvidenceAuthority.for_crash_recovery,
        state_store=open_coding_windows_product_worker_activation_state_store,
    )


__all__ = ["settle_coding_windows_product_worker_crash_c5"]
