"""Seal low-volume V1 Worker streams under Product custody for V2 cutover.

This only creates durable empty successor generations. A later Product
checkpoint and cutover preflight still decide whether any source may retire.
"""

from __future__ import annotations

import sys

from loushang.harness.package_product._linux_worker_history import (
    seal_product_history_v1,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .product_worker_history_retention import _history_proof_bindings

_MAX_SEGMENT_BYTES = 32 * 1024 * 1024


class CodingWorkerV2SealError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def seal_coding_product_worker_v1_history_for_v2(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[int, ...]:
    """Seal five V1 streams and return their minimal first-retained cutoffs."""

    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 sealing requires its Linux Product")
    return seal_product_history_v1(
        _history_proof_bindings(),
        product,
        error_type=CodingWorkerV2SealError,
        segment_limit=lambda: _MAX_SEGMENT_BYTES,
    )


__all__ = [
    "CodingWorkerV2SealError",
    "seal_coding_product_worker_v1_history_for_v2",
]
