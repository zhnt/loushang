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
from loushang.harness.worker.journal import WorkerAttemptRecordV1

from .package_product_worker_activation_history import (
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_history_retention import (
    CodingWorkerHistoryRetentionReviewV1,
)
from .package_product_worker_payload import (
    CodingWorkerPayloadDebtPlanV1,
)
from .package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1,
)
from .package_product_worker_start_gate_journal import (
    CodingWorkerStartGateRecordV1,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


class CodingWorkerRegisteredRecoveryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerRegisteredOrphanReviewV1:
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

    @property
    def registered_candidate(self) -> bool:
        gate = self.gate_record
        c5 = self.activation_attempt
        receipt = self.receipt_record
        lease = self.orphan_lease or self.repaired_orphan_lease
        plan = self.payload_plan
        if (
            gate is None
            or c5 is None
            or receipt is None
            or lease is None
            or plan is None
        ):
            return False
        policy = receipt.receipt.policy
        return bool(
            c5.phase == "registered"
            and c5.current
            and not c5.no_effect
            and c5.attempt_id == self.attempt_id == gate.attempt_id == plan.attempt_id
            and c5.receipt_fingerprint
            == gate.receipt_fingerprint
            == plan.receipt_fingerprint
            == receipt.receipt.fingerprint
            and c5.policy_fingerprint == gate.policy_fingerprint == policy.fingerprint
            and c5.owner_generation == policy.owner_selection_generation
            and c5.cleanup_contract_version == 1
            and c5.host_identity == self.host_identity
            and c5.boot_identity != self.current_boot_identity
            and gate.phase == "intent"
            and gate.identity is None
            and self.supervisor_attempt is None
            and policy.product_id == "coding"
            and policy.product_scope_id == gate.scope_id
            and lease.runtime_id == policy.product_runtime_id
            and lease.runtime_epoch == self.runtime_epoch
            and lease.store_root_identity == self.store_root_identity
            and not self.unrecognized_worker_state_names
        )

    @property
    def repair_candidate(self) -> bool:
        return self.registered_candidate and self.orphan_lease is not None

    @property
    def payload_repair_candidate(self) -> bool:
        return bool(
            self.registered_candidate
            and self.orphan_lease is None
            and self.repaired_orphan_lease is not None
            and self.repaired_owner_revision is not None
        )


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
    from .package_product_worker_activation_state import (
        CodingProductWorkerActivationStateStore,
    )
    from .package_product_worker_cleanup_evidence import (
        _HOST_DOMAIN,
        CodingPosixWorkerCleanupEvidenceAuthority,
    )
    from .package_product_worker_crash_c5_settlement import (
        CodingWorkerCrashC5SettlementError,
        _UnderGuardCleanupEvidenceAuthority,
    )
    from .package_product_worker_history_retention import _history_proof_bindings
    from .package_product_worker_registered_c5_settlement import (
        CodingWorkerRegisteredC5SettlementError,
        _UnderGuardRegisteredCleanupEvidenceAuthority,
    )
    from .package_product_worker_registered_payload_repair import (
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
