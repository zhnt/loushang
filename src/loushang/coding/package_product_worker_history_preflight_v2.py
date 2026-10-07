"""Read-only Product custody check before Worker history V2 publication.

No cutover file is written here. A publisher must retain the same lock order,
reopen this evidence, and durably commit all five streams together.
"""

from __future__ import annotations

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)

from .package_product_worker_history_checkpoint import (
    read_coding_product_worker_history_checkpoints_under_gc_guard,
)
from .package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
)
from .package_product_worker_history_prepared_v2 import (
    CodingWorkerPreparedProductCutoverV2,
)
from .package_product_worker_history_retention import (
    _review_coding_product_worker_history_under_guard,
)
from .package_product_worker_history_stream_snapshot import (
    read_coding_worker_histories_under_gc_guard,
)


class CodingWorkerCutoverPreflightError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def prepare_coding_product_worker_history_cutover_v2(
    product: PosixLocalWheelProductSessionOwner,
    *,
    first_retained_generations: tuple[int, ...],
) -> CodingWorkerPreparedProductCutoverV2:
    """Reopen all Product references and V1 bytes under one custody period."""

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(first_retained_generations) is not tuple
        or len(first_retained_generations) != 5
        or any(type(item) is not int or item < 1 for item in first_retained_generations)
    ):
        raise ValueError("Coding Worker V2 preflight requires its Product and cutoffs")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        with product.gc_gate.guard(require_write=True):
            checkpoints = read_coding_product_worker_history_checkpoints_under_gc_guard(
                product
            )
            if not checkpoints:
                raise CodingWorkerCutoverPreflightError(
                    "coding_worker_v2_checkpoint_absent"
                )
            checkpoint = checkpoints[-1]
            attempt_ids = tuple(
                sorted(
                    {
                        attempt_id
                        for item in checkpoints
                        for attempt_id in item.new_attempt_ids
                    }
                )
            )
            if not attempt_ids:
                raise CodingWorkerCutoverPreflightError(
                    "coding_worker_v2_attempt_closure_absent"
                )
            gc_snapshot = product.gc_gate.snapshot()
            for attempt_id in attempt_ids:
                review = _review_coding_product_worker_history_under_guard(
                    product,
                    attempt_id=attempt_id,
                    active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                    gc_snapshot=gc_snapshot,
                )
                if (
                    review.missing_proofs
                    or review.history_stream_snapshots != checkpoint.stream_snapshots
                    or review.gc_reservation_revision
                    != checkpoint.gc_reservation_revision
                    or review.worker_backup_references is None
                    or review.worker_backup_references.owner_revision
                    != checkpoint.backup_topology_revision
                ):
                    raise CodingWorkerCutoverPreflightError(
                        "coding_worker_v2_product_closure_unproven"
                    )
            histories = read_coding_worker_histories_under_gc_guard(product)
            anchor = CodingWorkerCheckpointAnchorV1.create(
                scope_id=checkpoint.scope_id,
                store_id=checkpoint.store_id,
                latest_revision=checkpoint.journal_revision,
                latest_digest=checkpoint.record_digest,
            )
            return CodingWorkerPreparedProductCutoverV2.from_v1_histories(
                checkpoints=checkpoints,
                anchor=anchor,
                histories=histories,
                first_retained_generations=first_retained_generations,
            )


__all__ = [
    "CodingWorkerCutoverPreflightError",
    "prepare_coding_product_worker_history_cutover_v2",
]
