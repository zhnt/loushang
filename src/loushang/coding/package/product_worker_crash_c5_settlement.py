"""Settle one Linux Worker C5 attempt after exact offline crash recovery."""

from __future__ import annotations

from typing import cast

from loushang.harness.package_product._linux_worker_recovery import (
    settle_crash_c5,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .product_worker_activation_history import CodingProductWorkerRetainedAttemptV1
from .product_worker_registered_recovery import _recovery_bindings


class CodingWorkerCrashC5SettlementError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def settle_coding_product_worker_crash_c5(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Retire and settle C5 under one offline runtime and GC transaction."""
    return cast(
        CodingProductWorkerRetainedAttemptV1,
        settle_crash_c5(_recovery_bindings(), product, attempt_id=attempt_id),
    )


__all__ = [
    "CodingWorkerCrashC5SettlementError",
    "settle_coding_product_worker_crash_c5",
]
