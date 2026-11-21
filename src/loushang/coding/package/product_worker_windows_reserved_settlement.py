"""Settle a reviewed Windows Worker reservation before any native effect.

The native bridge commits ``profile_effect`` before it invokes profile
creation. A retained revision-one ``reserved`` record therefore proves that
no native profile operation began, provided the exact Product attempt, launch
intent, payload, and absent Supervisor history still match. This operation
only advances that native journal; payload retirement is separate.
"""

from __future__ import annotations

import os
from functools import partial

from loushang.coding.harness.worker.windows_admission import is_windows_product
from loushang.harness.package_product._windows_worker_recovery import (
    settle_windows_product_worker_reserved_no_effect,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    windows_worker_reserved_settled_document,
)

from .product_worker_windows_launch_intent import _read_intent_under_gc_guard
from .product_worker_windows_reserved_review import (
    CodingWindowsWorkerReservedNoEffectReviewV1,
    _review_reserved_under_gc_guard,
)
from .product_worker_windows_stage_review import _inspection


class CodingWindowsWorkerReservedSettlementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_settled_document = partial(
    windows_worker_reserved_settled_document,
    error_type=CodingWindowsWorkerReservedSettlementError,
    history_error="coding_worker_reserved_settlement_history_changed",
)


def settle_coding_windows_product_worker_reserved_no_effect(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerReservedNoEffectReviewV1,
) -> None:
    """Durably close an exact no-effect reservation under Product custody."""
    if not is_windows_product(product, "coding", os.name) or (
        type(expected_review) is not CodingWindowsWorkerReservedNoEffectReviewV1
    ):
        raise OSError("Windows Worker reserved settlement requires a Product review")
    settle_windows_product_worker_reserved_no_effect(
        product,
        expected_review=expected_review,
        review_reserved=_review_reserved_under_gc_guard,
        read_intent=_read_intent_under_gc_guard,
        inspection=_inspection,
        error_type=CodingWindowsWorkerReservedSettlementError,
        error_prefix="coding_worker_reserved_settlement",
    )


__all__ = [
    "CodingWindowsWorkerReservedSettlementError",
    "settle_coding_windows_product_worker_reserved_no_effect",
]
