"""Read-only Product preflight for a Linux Worker stranded before effect start."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

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
from .package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
)
from .package_product_worker_cleanup_evidence import (
    CodingPosixWorkerCleanupEvidenceAuthority,
)
from .package_product_worker_history_retention import _known_worker_state_name
from .package_product_worker_payload import (
    CodingWorkerPayloadDebtPlanV1,
    _require_private_visible_root,
    _stage_exists,
    _verify_debt,
    open_coding_product_worker_supervisor_journal,
)
from .package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1,
    read_coding_product_worker_receipt_record,
)
from .package_product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
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

    @property
    def repair_candidate(self) -> bool:
        gate = self.gate_record
        c5 = self.activation_attempt
        receipt = self.receipt_record
        lease = self.orphan_lease
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


def review_coding_product_worker_registered_orphan(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerRegisteredOrphanReviewV1:
    """Join exact C5, gate, payload, and orphan lease without changing them."""

    if (
        not sys.platform.startswith("linux")
        or type(product) is not PosixLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise CodingWorkerRegisteredRecoveryError(
            "coding_worker_registered_product_unsupported"
        )
    registry = product.epoch_runtime.registry
    orphans = registry.review_orphans(store_id=registry.store_id)
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        gate = CodingWorkerStartGateJournal(product).current(attempt_id)
        supervisor = open_coding_product_worker_supervisor_journal(product).status(
            attempt_id
        )
        journal = CodingProductWorkerActivationStateJournal(
            product.state_root / "worker-activation-state.jsonl",
            scope_id=product.policy.project_scope_id,
            store_id=registry.store_id,
        )
        matching = tuple(
            item
            for item in journal.retained_attempts_read_only()
            if item.attempt_id == attempt_id
        )
        c5 = matching[0] if len(matching) == 1 else None
        receipt = (
            None
            if gate is None
            else read_coding_product_worker_receipt_record(
                product, receipt_fingerprint=gate.receipt_fingerprint
            )
        )
        matching_orphans = (
            ()
            if receipt is None
            else tuple(
                item
                for item in orphans
                if item.runtime_id == receipt.receipt.policy.product_runtime_id
            )
        )
        with product.pinned_state_root_gc_read() as root_fd:
            _require_private_visible_root(product.state_root, root_fd)
            state_names = tuple(os.listdir(root_fd))
            unrecognized = tuple(
                sorted(
                    name
                    for name in state_names
                    if name.casefold().startswith(("worker-", ".worker-"))
                    and not _known_worker_state_name(name)
                )
            )
            plan = (
                _verify_debt(root_fd, attempt_id)
                if _stage_exists(root_fd, attempt_id)
                else None
            )
        fence = product.epoch_runtime.cutover_result.fence
        if fence is None:
            raise CodingWorkerRegisteredRecoveryError(
                "coding_worker_registered_fence_unavailable"
            )
        evidence = CodingPosixWorkerCleanupEvidenceAuthority(product)
        product.assert_root_gc_authority_current()
        return CodingWorkerRegisteredOrphanReviewV1(
            attempt_id=attempt_id,
            gate_record=gate,
            activation_attempt=c5,
            supervisor_attempt=supervisor,
            receipt_record=receipt,
            orphan_lease=(matching_orphans[0] if len(matching_orphans) == 1 else None),
            payload_plan=plan,
            host_identity=evidence.host_identity,
            current_boot_identity=evidence.boot_identity,
            runtime_epoch=fence.epoch,
            store_root_identity=fence.fenced_root_identity,
            unrecognized_worker_state_names=unrecognized,
        )


def repair_coding_product_worker_registered_orphan(
    product: PosixLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWorkerRegisteredOrphanReviewV1,
) -> PackageEpochRuntimeLeaseV1:
    """Repair only the dead runtime lease; payload and C5 remain separate."""

    if type(expected_review) is not CodingWorkerRegisteredOrphanReviewV1:
        raise TypeError("Registered Worker orphan review must be exact")
    current = review_coding_product_worker_registered_orphan(
        product, attempt_id=expected_review.attempt_id
    )
    if current != expected_review:
        raise CodingWorkerRegisteredRecoveryError(
            "coding_worker_registered_review_stale"
        )
    if not current.repair_candidate or current.orphan_lease is None:
        raise CodingWorkerRegisteredRecoveryError(
            "coding_worker_registered_orphan_unproven"
        )
    product.epoch_runtime.registry.repair_orphan(current.orphan_lease.lease_id)
    return current.orphan_lease


__all__ = [
    "CodingWorkerRegisteredOrphanReviewV1",
    "CodingWorkerRegisteredRecoveryError",
    "repair_coding_product_worker_registered_orphan",
    "review_coding_product_worker_registered_orphan",
]
