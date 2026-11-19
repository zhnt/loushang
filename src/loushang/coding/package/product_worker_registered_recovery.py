"""Read-only Product preflight for a Linux Worker stranded before effect start."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from loushang.harness.package_product._linux_worker_recovery import (
    RecoveryBindings,
    recover_registered_no_effect,
    repair_registered_orphan,
    review_registered_orphan,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.worker.history._retention import RegisteredOrphanReviewMethods
from loushang.harness.worker.journal import WorkerAttemptRecordV1

from .product_worker_activation_history import CodingProductWorkerRetainedAttemptV1
from .product_worker_history_retention import CodingWorkerHistoryRetentionReviewV1
from .product_worker_payload import CodingWorkerPayloadDebtPlanV1
from .product_worker_receipt import CodingWorkerReceiptRecordV1
from .product_worker_start_gate_journal import CodingWorkerStartGateRecordV1

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


class CodingWorkerRegisteredRecoveryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerRegisteredOrphanReviewV1(RegisteredOrphanReviewMethods):
    _product_id = "coding"
    attempt_id: str
    gate_record: CodingWorkerStartGateRecordV1 | None
    activation_attempt: CodingProductWorkerRetainedAttemptV1 | None
    supervisor_attempt: WorkerAttemptRecordV1 | None
    receipt_record: CodingWorkerReceiptRecordV1 | None
    orphan_lease: PackageEpochRuntimeLeaseV1 | None
    payload_plan: CodingWorkerPayloadDebtPlanV1 | None
    host_identity: str
    current_boot_identity: str
    runtime_epoch: int
    store_root_identity: str
    unrecognized_worker_state_names: tuple[str, ...]
    repaired_orphan_lease: PackageEpochRuntimeLeaseV1 | None = None
    repaired_owner_revision: int | None = None


def review_coding_product_worker_registered_orphan(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerRegisteredOrphanReviewV1:
    """Join exact C5, gate, payload, and orphan lease without changing them."""
    return cast(
        CodingWorkerRegisteredOrphanReviewV1,
        review_registered_orphan(_recovery_bindings(), product, attempt_id=attempt_id),
    )


def repair_coding_product_worker_registered_orphan(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerRegisteredOrphanReviewV1,
) -> PackageEpochRuntimeLeaseV1:
    """Repair only the dead runtime lease; payload and C5 remain separate."""
    return repair_registered_orphan(
        _recovery_bindings(), product, expected_review=expected_review
    )


def recover_coding_product_worker_registered_no_effect(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingProductWorkerRetainedAttemptV1:
    """Run exact, independently retryable lease, payload, and C5 owners."""
    return cast(
        CodingProductWorkerRetainedAttemptV1,
        recover_registered_no_effect(
            _recovery_bindings(), product, attempt_id=attempt_id
        ),
    )


__all__ = [
    "CodingWorkerRegisteredOrphanReviewV1",
    "CodingWorkerRegisteredRecoveryError",
    "repair_coding_product_worker_registered_orphan",
    "recover_coding_product_worker_registered_no_effect",
    "review_coding_product_worker_registered_orphan",
]


def _recovery_bindings() -> RecoveryBindings[CodingWorkerHistoryRetentionReviewV1]:
    """Bind actual owner/DTO classes and product data; perform no IO."""
    from .product_worker_activation_state import CodingProductWorkerActivationStateStore
    from .product_worker_cleanup_evidence import (
        _HOST_DOMAIN,
        CodingPosixWorkerCleanupEvidenceAuthority,
    )
    from .product_worker_crash_c5_settlement import (
        CodingWorkerCrashC5SettlementError,
        _UnderGuardCleanupEvidenceAuthority,
    )
    from .product_worker_history_retention import _history_proof_bindings
    from .product_worker_registered_c5_settlement import (
        CodingWorkerRegisteredC5SettlementError,
        _UnderGuardRegisteredCleanupEvidenceAuthority,
    )
    from .product_worker_registered_payload_repair import (
        CodingWorkerRegisteredPayloadRepairError,
        CodingWorkerRegisteredPayloadRepairIntentV1,
    )

    return RecoveryBindings(
        history=_history_proof_bindings(),
        registered_review=CodingWorkerRegisteredOrphanReviewV1,
        intent=CodingWorkerRegisteredPayloadRepairIntentV1,
        recovery_error=CodingWorkerRegisteredRecoveryError,
        payload_error=CodingWorkerRegisteredPayloadRepairError,
        registered_c5_error=CodingWorkerRegisteredC5SettlementError,
        crash_c5_error=CodingWorkerCrashC5SettlementError,
        cleanup_type=CodingPosixWorkerCleanupEvidenceAuthority,
        under_guard_type=_UnderGuardCleanupEvidenceAuthority,
        registered_cleanup_type=_UnderGuardRegisteredCleanupEvidenceAuthority,
        state_store_type=CodingProductWorkerActivationStateStore,
        host_domain=_HOST_DOMAIN,
        cleanup_owner_message="Coding Worker cleanup requires its Linux Product owner",
    )
