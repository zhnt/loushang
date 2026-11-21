"""Settle one registered Linux Worker only after its no-effect repair closes."""

from __future__ import annotations

from typing import cast

from loushang.harness.package_product._linux_worker_recovery import (
    settle_registered_c5,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .product_worker_activation_history import CodingProductWorkerRetainedAttemptV1
from .product_worker_registered_recovery import _recovery_bindings


class CodingWorkerRegisteredC5SettlementError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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
