"""Durably retire only Worker V2 generations named by the Product owner."""

from __future__ import annotations

import sys

from loushang.harness.journal._rooted_io import RootedFile
from loushang.harness.package_product._linux_worker_history import (
    retire_product_history,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .product_worker_history_read_v2 import _HISTORY_PUBLICATION


class CodingWorkerV2RetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def retire_coding_worker_v2_history_under_guard(rooted: RootedFile) -> bool:
    """Write exact deletion debt before unlinking any retired source bytes."""
    return _HISTORY_PUBLICATION.retire_under_guard(
        rooted, error_type=CodingWorkerV2RetirementError
    )


def retire_coding_product_worker_v2_history(
    product: PosixLocalWheelProductSessionOwner,
) -> bool:
    """Retire owner-authorized bytes under Product runtime and GC custody."""

    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 retirement requires its Linux Product")
    return retire_product_history(
        product,
        publication=_HISTORY_PUBLICATION,
        error_type=CodingWorkerV2RetirementError,
    )


__all__ = [
    "CodingWorkerV2RetirementError",
    "retire_coding_product_worker_v2_history",
    "retire_coding_worker_v2_history_under_guard",
]
