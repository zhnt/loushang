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
    PosixWorkerGatedRecovery,
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
    return _GATED_RECOVERY.review_orphan(product, attempt_id=attempt_id)


def repair_coding_product_worker_orphan_runtime(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerOrphanRuntimeReviewV1,
) -> PackageEpochRuntimeLeaseV1:
    return _GATED_RECOVERY.repair_orphan(product, expected_review=expected_review)


def review_coding_product_worker_gated_recovery(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerGatedRecoveryReviewV1:
    return _GATED_RECOVERY.review(product, attempt_id=attempt_id)


def settle_coding_product_worker_gated_attempt(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerGatedRecoveryReviewV1,
    expected_plan: CodingWorkerPayloadDebtPlanV1,
) -> WorkerAttemptRecordV1:
    return _GATED_RECOVERY.settle(
        product, expected_review=expected_review, expected_plan=expected_plan
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


_GATED_RECOVERY: PosixWorkerGatedRecovery[
    object, CodingWorkerGatedRecoveryReviewV1, CodingWorkerOrphanRuntimeReviewV1
] = PosixWorkerGatedRecovery(
    history=_history_bindings,
    custody=_PAYLOAD_CUSTODY,
    gated_review_type=CodingWorkerGatedRecoveryReviewV1,
    orphan_type=CodingWorkerOrphanRuntimeReviewV1,
    payload_plan_type=CodingWorkerPayloadDebtPlanV1,
    error_type=CodingWorkerGatedRecoveryError,
    error_prefix="coding_worker",
    abandoned_failure_code=_ABANDONED_FAILURE_CODE,
    receipt_invalid_message="Coding Worker receipt fingerprint is invalid",
)
