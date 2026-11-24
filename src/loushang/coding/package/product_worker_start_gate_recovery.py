"""Read-only Product recovery review for one gated Linux Worker attempt.

The review correlates durable Product and Supervisor histories with the exact
installed native closure and a fresh Hosting group observation. It never
changes attempt state or grants payload-deletion authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from loushang.harness.package_product._linux_worker_history import HistoryProofBindings
from loushang.harness.package_product._linux_worker_recovery import (
    repair_gated_orphan_runtime,
    review_gated_orphan_runtime,
    review_gated_recovery,
    settle_gated_attempt,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.worker.history._start_gate import (
    GatedRecoveryReviewMethods,
    OrphanGatedRecoveryReviewMethods,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1

from .product_worker_native_release import (
    CodingWorkerNativeReleaseError as CodingWorkerNativeReleaseError,
)
from .product_worker_payload import (
    _PAYLOAD_CUSTODY,
    _STORAGE,
    CodingWorkerPayloadDebtPlanV1,
)
from .product_worker_receipt import CodingWorkerReceiptRecordV1
from .product_worker_start_gate_journal import CodingWorkerStartGateRecordV1

GatedGroupStatus = Literal[
    "unobserved", "absent", "present", "prior_boot_absent", "context_stale", "unknown"
]


_ABANDONED_FAILURE_CODE = "coding_worker_host_lost"


class CodingWorkerGatedRecoveryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerGatedRecoveryReviewV1(GatedRecoveryReviewMethods):
    attempt_id: str
    gate_record: CodingWorkerStartGateRecordV1 | None
    attempt_record: WorkerAttemptRecordV1 | None
    native_closure_current: bool
    group_status: GatedGroupStatus


@dataclass(frozen=True, slots=True)
class CodingWorkerOrphanRuntimeReviewV1(OrphanGatedRecoveryReviewMethods):
    """Pre-quiescence join for one crashed Product Worker runtime lease."""

    gated_review: CodingWorkerGatedRecoveryReviewV1
    receipt_record: CodingWorkerReceiptRecordV1 | None
    orphan_lease: PackageEpochRuntimeLeaseV1 | None
    payload_plan: CodingWorkerPayloadDebtPlanV1 | None
    current_runtime_epoch: int
    current_store_root_identity: str
    _product_id = "coding"


def review_coding_product_worker_orphan_runtime(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerOrphanRuntimeReviewV1:
    """Join an orphan epoch lease to a bound Worker without repairing either."""
    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker Product owner is required")
    return review_gated_orphan_runtime(
        product,
        attempt_id=attempt_id,
        history=_history_bindings,
        storage=_STORAGE,
        record_type=CodingWorkerOrphanRuntimeReviewV1,
        product_required_message="Coding Worker Product owner is required",
        receipt_invalid_message="Coding Worker receipt fingerprint is invalid",
    )


def repair_coding_product_worker_orphan_runtime(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerOrphanRuntimeReviewV1,
) -> PackageEpochRuntimeLeaseV1:
    """Repair only the exact orphan lease after current Worker absence proof.

    This does not settle the Supervisor attempt or delete its payload. Both
    effects still require the separate offline Product reviews and CAS checks.
    """
    if type(expected_review) is not CodingWorkerOrphanRuntimeReviewV1:
        raise TypeError("Worker orphan runtime repair requires an exact review")
    return repair_gated_orphan_runtime(
        product,
        expected_review=expected_review,
        history=_history_bindings,
        storage=_STORAGE,
        record_type=CodingWorkerOrphanRuntimeReviewV1,
        product_required_message="Coding Worker Product owner is required",
        receipt_invalid_message="Coding Worker receipt fingerprint is invalid",
        error_type=CodingWorkerGatedRecoveryError,
        error_prefix="coding_worker",
    )


def review_coding_product_worker_gated_recovery(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerGatedRecoveryReviewV1:
    """Reopen exact histories while Product runtimes are quiescent."""
    return cast(
        CodingWorkerGatedRecoveryReviewV1,
        review_gated_recovery(
            product,
            attempt_id=attempt_id,
            history=_history_bindings,
            custody=_PAYLOAD_CUSTODY,
        ),
    )


def settle_coding_product_worker_gated_attempt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerGatedRecoveryReviewV1,
    expected_plan: CodingWorkerPayloadDebtPlanV1,
) -> WorkerAttemptRecordV1:
    """Record proven local process settlement for one exact abandoned payload.

    This never deletes the payload. The separate debt repair must recheck its
    own plan and the newly settled Supervisor record before removing bytes.
    """
    if (
        type(expected_review) is not CodingWorkerGatedRecoveryReviewV1
        or type(expected_plan) is not CodingWorkerPayloadDebtPlanV1
    ):
        raise TypeError("Worker gated recovery requires exact review and debt plan")
    return settle_gated_attempt(
        product,
        expected_review=expected_review,
        expected_plan=expected_plan,
        history=_history_bindings,
        custody=_PAYLOAD_CUSTODY,
        storage=_STORAGE,
        error_type=CodingWorkerGatedRecoveryError,
        error_prefix="coding_worker",
        failure_code=_ABANDONED_FAILURE_CODE,
    )


__all__ = [
    "CodingWorkerGatedRecoveryError",
    "CodingWorkerGatedRecoveryReviewV1",
    "CodingWorkerOrphanRuntimeReviewV1",
    "repair_coding_product_worker_orphan_runtime",
    "review_coding_product_worker_gated_recovery",
    "review_coding_product_worker_orphan_runtime",
    "settle_coding_product_worker_gated_attempt",
]


def _history_bindings() -> HistoryProofBindings[object]:
    from .product_worker_history_retention import _history_proof_bindings

    return cast(HistoryProofBindings[object], _history_proof_bindings())
