"""Settle one Linux Worker C5 attempt after exact offline crash recovery."""

from __future__ import annotations

from typing import cast

from loushang.harness.package_product._linux_worker_recovery import (
    ClosedLinuxCrashRecoveryAuthority,
    UnderGuardCleanupEvidenceAuthority,
    settle_crash_c5,
)
from loushang.harness.package_product._linux_worker_recovery import (
    _settle_crash_c5_under_guard as _core_settle_crash_c5_under_guard,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.worker.product_activation import (
    ActivationWitness,
)

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_cleanup_evidence import (
    CodingPosixWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_history_retention import (
    CodingWorkerHistoryRetentionReviewV1,
)
from .package_product_worker_registered_recovery import _recovery_bindings

_STALE_WITNESS: ActivationWitness = ("0" * 64, "0" * 64, "stale", 0, 0)


class CodingWorkerCrashC5SettlementError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_ClosedLinuxCrashRecoveryAuthority = ClosedLinuxCrashRecoveryAuthority


class _UnderGuardCleanupEvidenceAuthority(
    UnderGuardCleanupEvidenceAuthority[CodingWorkerHistoryRetentionReviewV1],
    CodingPosixWorkerCleanupEvidenceAuthority,
):
    """Read fresh C5 evidence inside the caller's runtime and GC locks."""

    def __init__(
        self,
        product: PosixLocalWheelProductSessionOwner,
        *,
        active_runtime_lease_ids: tuple[str, ...],
        gc_snapshot: PluginPackageGcReservationSnapshotV1,
    ) -> None:
        UnderGuardCleanupEvidenceAuthority.__init__(
            self,
            product,
            bindings=_recovery_bindings(),
            active_runtime_lease_ids=active_runtime_lease_ids,
            gc_snapshot=gc_snapshot,
        )


def settle_coding_product_worker_crash_c5(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Retire and settle C5 under one offline runtime and GC transaction."""
    return cast(
        CodingProductWorkerRetainedAttemptV1,
        settle_crash_c5(_recovery_bindings(), product, attempt_id=attempt_id),
    )


def _settle_crash_c5_under_guard(
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
    active_runtime_lease_ids: tuple[str, ...],
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
) -> CodingProductWorkerRetainedAttemptV1:
    return cast(
        CodingProductWorkerRetainedAttemptV1,
        _core_settle_crash_c5_under_guard(
            _recovery_bindings(),
            product,
            attempt_id=attempt_id,
            active_runtime_lease_ids=active_runtime_lease_ids,
            gc_snapshot=gc_snapshot,
        ),
    )


__all__ = [
    "CodingWorkerCrashC5SettlementError",
    "settle_coding_product_worker_crash_c5",
]
