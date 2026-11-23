"""Coding-owned proof that retained Windows Worker history has no GC debt.

The Product GC owner keeps audit history in place. This reader only permits
Package root deletion after every observed attempt has a complete retirement
proof; unknown, partial, or changed history fails closed.
"""

from __future__ import annotations

import os

from loushang.harness.package_product._windows_worker_recovery import (
    require_windows_product_worker_settled_history,
)
from loushang.harness.package_product._worker_windows_attempt import is_windows_product
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.worker.history._windows_recovery import (
    require_windows_worker_c5_gc_history,
)
from loushang.harness.worker.history._windows_sources import (
    WindowsHistoryNames as WindowsHistoryNames,
)
from loushang.harness.worker.history._windows_sources import (
    windows_worker_history_names,
)

from .product_worker_windows_recovery_inventory import (
    _current_after_verified_retirements_under_gc_guard,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
    _observe_native_job_absence,
    _windows_history_journals,
)


def _require_known_windows_worker_state_names(names: tuple[str, ...]) -> None:
    _history_names().require_known(names)


_require_c5_gc_history = require_windows_worker_c5_gc_history


class CodingWindowsWorkerGcHistoryAuthority:
    """Read-only Coding proof consumed by the Product Package GC owner."""

    def __init__(self, product: WindowsLocalWheelProductSessionOwner) -> None:
        if not is_windows_product(product, "coding", os.name):
            raise ValueError("Coding Windows Worker GC requires its Product owner")
        self._product = product

    @property
    def product_owner(self) -> WindowsLocalWheelProductSessionOwner:
        return self._product

    def require_settled(
        self,
        *,
        observed_names: tuple[str, ...],
        allow_preparation_stage: bool = False,
        allow_checkpoint_stage: bool = False,
        allow_base_stage: bool = False,
    ) -> None:
        """Verify every retained attempt without mutating Worker or Package state.

        The caller holds runtime quiescence and the Product GC guard. Names are
        compared before and after the owner reads to catch a changed inventory.
        """

        return require_windows_product_worker_settled_history(
            self._product,
            journals=_windows_history_journals(),
            inspect_inventory=_inspect_windows_worker_recovery_inventory_under_gc_guard,
            current_attempts=_current_after_verified_retirements_under_gc_guard,
            observe_job_absence=_observe_native_job_absence,
            observed_names=observed_names,
            allow_preparation_stage=allow_preparation_stage,
            allow_checkpoint_stage=allow_checkpoint_stage,
            allow_base_stage=allow_base_stage,
        )


__all__ = ["CodingWindowsWorkerGcHistoryAuthority"]


_history_names = windows_worker_history_names
