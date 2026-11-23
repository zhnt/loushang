"""Reprove a Windows Worker cutover candidate without publishing an owner."""

from __future__ import annotations

from loushang.harness.package_product._windows_worker_history import (
    review_windows_product_worker_history_cutover_candidate,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .product_worker_windows_checkpoint import _current_checkpoint_under_guard
from .product_worker_windows_history_cutover_record import (
    CodingWindowsWorkerHistoryCutoverRecordV1,
)
from .product_worker_windows_persisted_bases import (
    _read_coding_windows_worker_persisted_bases_under_gc_guard,
)


def review_coding_windows_worker_history_cutover_candidate(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCutoverRecordV1:
    """Return exact marker bytes only while old sources still prove the bases.

    The caller receives an inert value. This method has no marker writer and
    cannot grant retirement or new-Session authority.
    """

    return review_windows_product_worker_history_cutover_candidate(
        product,
        product_id="coding",
        record_type=CodingWindowsWorkerHistoryCutoverRecordV1,
        read_persisted=_read_coding_windows_worker_persisted_bases_under_gc_guard,
        review_checkpoint=_current_checkpoint_under_guard,
    )


__all__ = ["review_coding_windows_worker_history_cutover_candidate"]
