"""Seal low-volume V1 Worker streams under Product custody for V2 cutover.

This only creates durable empty successor generations. A later Product
checkpoint and cutover preflight still decide whether any source may retire.
"""

from __future__ import annotations

from loushang.harness.package_product._linux_worker_history import (
    seal_product_history_v1,
)
from loushang.harness.package_product._worker_history_access import (
    is_exact_posix_worker_history_product,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .product_worker_history_retention import _history_proof_bindings


class CodingWorkerV2SealError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def seal_coding_product_worker_v1_history_for_v2(
    product: PosixLocalWheelProductSessionOwner,
) -> tuple[int, ...]:
    """Seal five V1 streams and return their minimal first-retained cutoffs."""

    if not is_exact_posix_worker_history_product(
        product, product_id="coding", linux_only=True
    ):
        raise ValueError("Coding Worker V2 sealing requires its Linux Product")
    return seal_product_history_v1(
        _history_proof_bindings(),
        product,
        error_type=CodingWorkerV2SealError,
    )


__all__ = [
    "CodingWorkerV2SealError",
    "seal_coding_product_worker_v1_history_for_v2",
]
