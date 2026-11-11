"""Settle one registered Linux Worker only after its no-effect repair closes."""

from __future__ import annotations

from typing import cast

from loushang.harness.package_product._linux_worker_recovery import (
    RegisteredCleanupEvidenceAuthority,
    settle_registered_c5,
)
from loushang.harness.package_product._linux_worker_recovery import (
    _reopen_settled_registered_c5 as _core_reopen_settled_registered_c5,
)
from loushang.harness.package_product._linux_worker_recovery import (
    _require_registered_witness as _core_require_registered_witness,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_crash_c5_settlement import (
    _UnderGuardCleanupEvidenceAuthority,
)
from .package_product_worker_history_retention import (
    CodingWorkerHistoryRetentionReviewV1,
)
from .package_product_worker_registered_recovery import (
    CodingWorkerRegisteredOrphanReviewV1,
    _recovery_bindings,
)


class CodingWorkerRegisteredC5SettlementError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _require_registered_witness(
    product: PosixLocalWheelProductSessionOwner,
    *,
    review: CodingWorkerRegisteredOrphanReviewV1,
    witness: CodingWorkerHistoryRetentionReviewV1,
) -> None:
    """Accept the one expected transient unbound-gate shape and no other debt."""
    return _core_require_registered_witness(
        _recovery_bindings(), product, review=review, witness=witness
    )


class _UnderGuardRegisteredCleanupEvidenceAuthority(
    RegisteredCleanupEvidenceAuthority[CodingWorkerHistoryRetentionReviewV1],
    _UnderGuardCleanupEvidenceAuthority,
):
    def __init__(
        self,
        product: PosixLocalWheelProductSessionOwner,
        *,
        review: CodingWorkerRegisteredOrphanReviewV1,
        active_runtime_lease_ids: tuple[str, ...],
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
    ) -> None:
        RegisteredCleanupEvidenceAuthority.__init__(
            self,
            product,
            bindings=_recovery_bindings(),
            review=review,
            active_runtime_lease_ids=active_runtime_lease_ids,
            gc_snapshot=gc_snapshot,
        )


def _reopen_settled_registered_c5(
    product: PosixLocalWheelProductSessionOwner,
    review: CodingWorkerRegisteredOrphanReviewV1,
) -> CodingProductWorkerRetainedAttemptV1:
    return cast(
        CodingProductWorkerRetainedAttemptV1,
        _core_reopen_settled_registered_c5(_recovery_bindings(), product, review),
    )


def settle_coding_product_worker_registered_c5(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Reopen exact no-effect evidence under runtime and GC locks, then CAS C5."""
    return cast(
        CodingProductWorkerRetainedAttemptV1,
        settle_registered_c5(_recovery_bindings(), product, attempt_id=attempt_id),
    )


__all__ = [
    "CodingWorkerRegisteredC5SettlementError",
    "settle_coding_product_worker_registered_c5",
]
