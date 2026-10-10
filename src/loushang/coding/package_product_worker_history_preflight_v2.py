"""Read-only Product custody check before Worker history V2 publication.

No cutover file is written here. A publisher must retain the same lock order,
reopen this evidence, and durably commit all five streams together.
"""

from __future__ import annotations

from hashlib import sha256

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
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
    CodingWorkerHistoryRetentionReviewV1,
    _review_coding_product_worker_history_under_guard,
)
from .package_product_worker_history_stream_snapshot import (
    read_coding_worker_histories_under_gc_guard,
)
from .package_product_worker_no_effect_archive_v2 import (
    CodingWorkerNoEffectArchiveV2,
    CodingWorkerNoEffectProofV2,
)
from .package_product_worker_opt_in import CodingWorkerOptInJournal
from .package_product_worker_registered_payload_repair import (
    _read_intent,
    registered_payload_repair_matches_no_effect_closure,
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

    if (
        type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(first_retained_generations) is not tuple
        or len(first_retained_generations) != 5
        or any(
            type(item) is not int or item < 1 for item in first_retained_generations[:4]
        )
        or type(first_retained_generations[4]) is not int
        or first_retained_generations[4] < 0
    ):
        raise ValueError("Coding Worker V2 preflight requires its Product and cutoffs")
    checkpoints = read_coding_product_worker_history_checkpoints_under_gc_guard(product)
    if not checkpoints:
        raise CodingWorkerCutoverPreflightError("coding_worker_v2_checkpoint_absent")
    checkpoint = checkpoints[-1]
    attempt_ids = tuple(
        sorted(
            {attempt_id for item in checkpoints for attempt_id in item.new_attempt_ids}
        )
    )
    if not attempt_ids:
        raise CodingWorkerCutoverPreflightError(
            "coding_worker_v2_attempt_closure_absent"
        )
    no_effect_reviews: list[CodingWorkerHistoryRetentionReviewV1] = []
    for attempt_id in attempt_ids:
        review = _review_coding_product_worker_history_under_guard(
            product,
            attempt_id=attempt_id,
            active_runtime_lease_ids=active_runtime_lease_ids,
            gc_snapshot=gc_snapshot,
        )
        if (
            review.missing_proofs
            or review.history_stream_snapshots != checkpoint.stream_snapshots
            or review.gc_reservation_revision != checkpoint.gc_reservation_revision
            or review.worker_backup_references is None
            or review.worker_backup_references.owner_revision
            != checkpoint.backup_topology_revision
        ):
            raise CodingWorkerCutoverPreflightError(
                "coding_worker_v2_product_closure_unproven"
            )
        if review.no_effect_closure:
            no_effect_reviews.append(review)
    histories = read_coding_worker_histories_under_gc_guard(product)
    no_effect_archive = None
    if no_effect_reviews:
        opt_in_projection = CodingWorkerOptInJournal(
            product.state_root / "worker-opt-in.jsonl",
            scope_id=product.policy.project_scope_id,
            gc_gate=product.gc_gate,
            store_id=product.epoch_runtime.registry.store_id,
        ).retention_projection_under_gc_guard()
        decisions = {
            item.decision_digest: item for item in opt_in_projection.reference_decisions
        }
        proofs: list[CodingWorkerNoEffectProofV2] = []
        with product.pinned_state_root_gc_read() as root_fd:
            for review in no_effect_reviews:
                gate = review.gate_record
                receipt = review.receipt_record
                activation = tuple(
                    item
                    for item in review.retained_activation_references
                    if item.attempt_id == review.attempt_id
                )
                intent = _read_intent(root_fd, review.attempt_id)
                if (
                    gate is None
                    or receipt is None
                    or len(activation) != 1
                    or intent is None
                    or not review.registered_repair_reference_verified
                    or not registered_payload_repair_matches_no_effect_closure(
                        intent,
                        gate=gate,
                        receipt=receipt,
                        activation=activation[0],
                        supervisor=review.attempt_record,
                    )
                ):
                    raise CodingWorkerCutoverPreflightError(
                        "coding_worker_v2_no_effect_archive_unproven"
                    )
                allow = decisions.get(receipt.opt_in_decision_digest)
                if allow is None:
                    raise CodingWorkerCutoverPreflightError(
                        "coding_worker_v2_no_effect_archive_unproven"
                    )
                proofs.append(
                    CodingWorkerNoEffectProofV2(
                        gate=gate,
                        receipt=receipt,
                        activation=activation[0],
                        historical_allow=allow,
                        repair_intent_digest=sha256(
                            canonical_json_bytes(intent.to_dict()) + b"\n"
                        ).hexdigest(),
                    )
                )
        no_effect_archive = CodingWorkerNoEffectArchiveV2(
            scope_id=checkpoint.scope_id,
            store_id=checkpoint.store_id,
            checkpoint_digest=checkpoint.record_digest,
            proofs=tuple(sorted(proofs, key=lambda item: item.attempt_id)),
        )
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
        no_effect_archive=no_effect_archive,
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
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        with product.gc_gate.guard(require_write=True):
            return _prepare_coding_product_worker_history_cutover_under_guard(
                product,
                first_retained_generations=first_retained_generations,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                gc_snapshot=product.gc_gate.snapshot(),
            )


__all__ = [
    "CodingWorkerCutoverPreflightError",
    "prepare_coding_product_worker_history_cutover_v2",
]
