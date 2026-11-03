"""Reprove a Windows Worker cutover candidate without publishing an owner."""

from __future__ import annotations

import os

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

from .package_product_worker_windows_checkpoint import (
    _current_checkpoint_under_guard,
)
from .package_product_worker_windows_history_cutover_record import (
    CodingWindowsWorkerHistoryCutoverRecordV1,
)
from .package_product_worker_windows_persisted_bases import (
    _read_coding_windows_worker_persisted_bases_under_gc_guard,
)


def review_coding_windows_worker_history_cutover_candidate(
    product: WindowsLocalWheelProductSessionOwner,
) -> CodingWindowsWorkerHistoryCutoverRecordV1:
    """Return exact marker bytes only while old sources still prove the bases.

    The caller receives an inert value. This method has no marker writer and
    cannot grant retirement or new-Session authority.
    """

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Windows Worker cutover review requires its Product")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise ValueError("Windows Worker cutover runtime remains active")
        product.assert_root_gc_authority_current()
        with product.gc_gate.guard(require_write=True):
            gc_snapshot = product.gc_gate.snapshot()
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                persisted, marker = (
                    _read_coding_windows_worker_persisted_bases_under_gc_guard(
                        product, root, require_cutover=False
                    )
                )
            if marker is not None:
                raise ValueError("Windows Worker cutover marker is already present")
            current = _current_checkpoint_under_guard(
                product,
                quiescence=quiescence,
                gc_snapshot=gc_snapshot,
                allow_checkpoint_stage=False,
            )
            if current != persisted.checkpoint:
                raise ValueError("Windows Worker cutover source changed")
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                reread, marker = (
                    _read_coding_windows_worker_persisted_bases_under_gc_guard(
                        product, root, require_cutover=False
                    )
                )
            if marker is not None or reread != persisted:
                raise ValueError("Windows Worker cutover bases changed")
            product.assert_root_gc_authority_current()
            return CodingWindowsWorkerHistoryCutoverRecordV1.from_persisted_bases(
                persisted
            )


__all__ = ["review_coding_windows_worker_history_cutover_candidate"]
