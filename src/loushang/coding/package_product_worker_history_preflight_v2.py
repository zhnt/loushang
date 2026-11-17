"""Read-only Product custody check before Worker history V2 publication.

No cutover file is written here. A publisher must retain the same lock order,
reopen this evidence, and durably commit all five streams together.
"""

from __future__ import annotations

from loushang.harness.package_product._linux_worker_history import (
    prepare_history_cutover_under_guard,
    prepare_product_history_cutover,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)

from .package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)
from .package_product_worker_history_retention import (
    _history_proof_bindings,
)


class CodingWorkerCutoverPreflightError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _prepare_coding_product_worker_history_cutover_under_guard(
    product: PosixLocalWheelProductSessionOwner,
    *,
    first_retained_generations: tuple[int, ...],
    active_runtime_lease_ids: tuple[str, ...],
    gc_snapshot: PluginPackageGcReservationSnapshotV1,
) -> CodingWorkerPreparedProductCutoverV2:
    """Join exact Product evidence while caller retains runtime and GC locks."""

    return prepare_history_cutover_under_guard(
        _history_proof_bindings(),
        product,
        prepared_type=CodingWorkerPreparedProductCutoverV2,
        error_type=CodingWorkerCutoverPreflightError,
        first_retained_generations=first_retained_generations,
        active_runtime_lease_ids=active_runtime_lease_ids,
        gc_snapshot=gc_snapshot,
    )


def prepare_coding_product_worker_history_cutover_v2(
    product: PosixLocalWheelProductSessionOwner,
    *,
    first_retained_generations: tuple[int, ...],
) -> CodingWorkerPreparedProductCutoverV2:
    """Reopen all Product references and V1 bytes under one custody period."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
    ):
        raise ValueError("Coding Worker V2 preflight requires its Product and cutoffs")
    return prepare_product_history_cutover(
        _history_proof_bindings(),
        product,
        prepared_type=CodingWorkerPreparedProductCutoverV2,
        error_type=CodingWorkerCutoverPreflightError,
        first_retained_generations=first_retained_generations,
    )


__all__ = [
    "CodingWorkerCutoverPreflightError",
    "prepare_coding_product_worker_history_cutover_v2",
]
