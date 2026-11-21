"""Product-owned Linux cleanup evidence for a C5 Worker attempt.

This owner reopens the settled Supervisor, start gate, native group and Product
state under the retention review's locks. It also verifies an exact prior-boot
absence for the offline crash-recovery path. Registered-lease recovery remains
closed.
"""

from __future__ import annotations

from hashlib import sha256

from loushang.harness.package_product._linux_worker_recovery import (
    CleanupEvidenceAuthority,
    RegisteredCleanupEvidenceAuthority,
    UnderGuardCleanupEvidenceAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .product_worker_history_retention import CodingWorkerHistoryRetentionReviewV1
from .product_worker_registered_recovery import _recovery_bindings

_HOST_DOMAIN = "loushang.coding.worker.cleanup/v1"
_AUTHORITY_ID = "coding.posix-worker.cleanup-evidence.v1"
_AUTHORITY_FINGERPRINT = sha256(
    b"loushang.coding.posix-worker.cleanup-evidence/v1"
).hexdigest()


class CodingPosixWorkerCleanupEvidenceAuthority(
    CleanupEvidenceAuthority[CodingWorkerHistoryRetentionReviewV1]
):
    """Revalidate one original Linux attempt before C5 tree settlement."""

    authority_id = _AUTHORITY_ID
    authority_fingerprint = _AUTHORITY_FINGERPRINT

    def __init__(self, product: PosixLocalWheelProductSessionOwner) -> None:
        super().__init__(product, _recovery_bindings())


class _UnderGuardCleanupEvidenceAuthority(
    UnderGuardCleanupEvidenceAuthority[CodingWorkerHistoryRetentionReviewV1],
    CodingPosixWorkerCleanupEvidenceAuthority,
):
    """Keep the Product's static evidence identity under Harness custody."""


class _UnderGuardRegisteredCleanupEvidenceAuthority(
    RegisteredCleanupEvidenceAuthority[CodingWorkerHistoryRetentionReviewV1],
    _UnderGuardCleanupEvidenceAuthority,
):
    """Keep the same evidence identity for registered-lease settlement."""


__all__ = ["CodingPosixWorkerCleanupEvidenceAuthority"]
