"""Settle a crashed Windows Worker C5 attempt after Product recovery closes it."""

from __future__ import annotations

from typing import cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .product_worker_activation_history import CodingProductWorkerRetainedAttemptV1


def settle_coding_windows_product_worker_crash_c5(
    product: WindowsLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Recheck a repaired crash, then retire and settle its exact C5 record."""
    from .product_worker_windows_crash_recovery import _recovery_program

    return cast(
        "CodingProductWorkerRetainedAttemptV1",
        _recovery_program().settle_c5(product, attempt_id=attempt_id),
    )


__all__ = ["settle_coding_windows_product_worker_crash_c5"]
