"""Read-only Product recovery review for one gated Linux Worker attempt.

The review correlates durable Product and Supervisor histories with the exact
installed native closure and a fresh Hosting group observation. It never
changes attempt state or grants payload-deletion authority.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Literal

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeLeaseV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.gated_start import (
    WorkerNativeGroupStatus,
    worker_native_group_status_after_restart,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1

from .package_product_worker_installed_native import (
    open_coding_product_installed_worker_release_reader,
)
from .package_product_worker_native_release import CodingWorkerNativeReleaseError
from .package_product_worker_payload import (
    _DIR_FLAGS,
    CodingWorkerPayloadDebtPlanV1,
    _offline,
    _require_private_visible_root,
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

GatedGroupStatus = Literal[
    "unobserved", "absent", "present", "prior_boot_absent", "context_stale", "unknown"
]
_ABANDONED_ACTIVE_PHASES = frozenset(
    {"claimed", "launching", "handshaking", "healthy", "draining"}
)
_RECOVERABLE_PHASES = _ABANDONED_ACTIVE_PHASES | {"failed", "fenced"}
_ABANDONED_FAILURE_CODE = "coding_worker_host_lost"


class CodingWorkerGatedRecoveryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerGatedRecoveryReviewV1:
    attempt_id: str
    gate_record: CodingWorkerStartGateRecordV1 | None
    attempt_record: WorkerAttemptRecordV1 | None
    native_closure_current: bool
    group_status: GatedGroupStatus

    @property
    def same_boot_settlement_candidate(self) -> bool:
        return (
            self.gate_record is not None
            and self.gate_record.phase == "bound"
            and self.attempt_record is not None
            and self.attempt_record.phase in _RECOVERABLE_PHASES
            and self.native_closure_current
            and self.group_status == "absent"
        )

    @property
    def prior_boot_settlement_candidate(self) -> bool:
        return (
            self.gate_record is not None
            and self.gate_record.phase == "bound"
            and self.attempt_record is not None
            and self.attempt_record.phase in _RECOVERABLE_PHASES
            and self.native_closure_current
            and self.group_status == "prior_boot_absent"
        )

    @property
    def settlement_candidate(self) -> bool:
        return (
            self.same_boot_settlement_candidate
            or self.prior_boot_settlement_candidate
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerOrphanRuntimeReviewV1:
    """Pre-quiescence join for one crashed Product Worker runtime lease."""

    gated_review: CodingWorkerGatedRecoveryReviewV1
    receipt_record: CodingWorkerReceiptRecordV1 | None
    orphan_lease: PackageEpochRuntimeLeaseV1 | None
    payload_plan: CodingWorkerPayloadDebtPlanV1 | None
    current_runtime_epoch: int
    current_store_root_identity: str

    @property
    def review_id(self) -> str:
        gated = self.gated_review
        return sha256(
            canonical_json_bytes(
                {
                    "reviewVersion": 1,
                    "attemptId": gated.attempt_id,
                    "gateRecord": (
                        None if gated.gate_record is None else gated.gate_record.to_dict()
                    ),
                    "attemptRecord": (
                        None
                        if gated.attempt_record is None
                        else gated.attempt_record.to_dict()
                    ),
                    "nativeClosureCurrent": gated.native_closure_current,
                    "groupStatus": gated.group_status,
                    "receiptRecord": (
                        None
                        if self.receipt_record is None
                        else self.receipt_record.to_dict()
                    ),
                    "orphanLease": (
                        None
                        if self.orphan_lease is None
                        else self.orphan_lease.to_dict()
                    ),
                    "payloadPlan": (
                        None if self.payload_plan is None else asdict(self.payload_plan)
                    ),
                    "runtimeEpoch": self.current_runtime_epoch,
                    "storeRootIdentity": self.current_store_root_identity,
                }
            )
        ).hexdigest()

    @property
    def repair_candidate(self) -> bool:
        gate = self.gated_review.gate_record
        receipt = self.receipt_record
        lease = self.orphan_lease
        plan = self.payload_plan
        return (
            self.gated_review.settlement_candidate
            and gate is not None
            and receipt is not None
            and lease is not None
            and plan is not None
            and receipt.receipt.fingerprint == gate.receipt_fingerprint
            and receipt.receipt.policy.product_id == "coding"
            and receipt.receipt.policy.fingerprint == gate.policy_fingerprint
            and receipt.receipt.policy.product_scope_id == gate.scope_id
            and lease.runtime_id == receipt.receipt.policy.product_runtime_id
            and lease.runtime_epoch == self.current_runtime_epoch
            and lease.store_root_identity == self.current_store_root_identity
            and plan.attempt_id == gate.attempt_id
            and plan.receipt_fingerprint == gate.receipt_fingerprint
        )


def review_coding_product_worker_orphan_runtime(
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> CodingWorkerOrphanRuntimeReviewV1:
    """Join an orphan epoch lease to a bound Worker without repairing either."""

    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Coding Worker Product owner is required")
    registry = product.epoch_runtime.registry
    orphans = registry.review_orphans(store_id=registry.store_id)
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        gated = _review_offline(product, attempt_id=attempt_id)
        gate = gated.gate_record
        receipt = (
            None
            if gate is None
            else read_coding_product_worker_receipt_record(
                product, receipt_fingerprint=gate.receipt_fingerprint
            )
        )
        matching = (
            ()
            if receipt is None
            else tuple(
                lease
                for lease in orphans
                if lease.runtime_id == receipt.receipt.policy.product_runtime_id
            )
        )
        plan = None
        if gate is not None:
            root_fd = os.open(product.state_root, _DIR_FLAGS)
            try:
                _require_private_visible_root(product.state_root, root_fd)
                plan = _verify_debt(root_fd, gate.attempt_id)
            finally:
                os.close(root_fd)
        fence = product.epoch_runtime.cutover_result.fence
        assert fence is not None
        return CodingWorkerOrphanRuntimeReviewV1(
            gated_review=gated,
            receipt_record=receipt,
            orphan_lease=matching[0] if len(matching) == 1 else None,
            payload_plan=plan,
            current_runtime_epoch=fence.epoch,
            current_store_root_identity=fence.fenced_root_identity,
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
    current = review_coding_product_worker_orphan_runtime(
        product, attempt_id=expected_review.gated_review.attempt_id
    )
    if current != expected_review:
        raise CodingWorkerGatedRecoveryError(
            "coding_worker_orphan_runtime_review_stale"
        )
    if not current.repair_candidate or current.orphan_lease is None:
        raise CodingWorkerGatedRecoveryError(
            "coding_worker_orphan_runtime_unproven"
        )
    product.epoch_runtime.registry.repair_orphan(current.orphan_lease.lease_id)
    return current.orphan_lease


def review_coding_product_worker_gated_recovery(
    product: PosixLocalWheelProductSessionOwner,
    *,
    attempt_id: str,
) -> CodingWorkerGatedRecoveryReviewV1:
    """Reopen exact histories while Product runtimes are quiescent."""

    with _offline(product):
        return _review_offline(product, attempt_id=attempt_id)


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

    if type(expected_review) is not CodingWorkerGatedRecoveryReviewV1 or type(
        expected_plan
    ) is not CodingWorkerPayloadDebtPlanV1:
        raise TypeError("Worker gated recovery requires exact review and debt plan")
    with _offline(product):
        current = _review_offline(product, attempt_id=expected_review.attempt_id)
        if current != expected_review:
            raise CodingWorkerGatedRecoveryError(
                "coding_worker_gated_recovery_review_stale"
            )
        if not current.settlement_candidate:
            raise CodingWorkerGatedRecoveryError(
                "coding_worker_gated_recovery_unproven"
            )
        gate = current.gate_record
        attempt = current.attempt_record
        assert gate is not None and attempt is not None
        if expected_plan.attempt_id != gate.attempt_id:
            raise CodingWorkerGatedRecoveryError(
                "coding_worker_gated_recovery_attempt_mismatch"
            )
        root_fd = os.open(product.state_root, _DIR_FLAGS)
        try:
            _require_private_visible_root(product.state_root, root_fd)
            plan = _verify_debt(root_fd, gate.attempt_id)
            if (
                plan != expected_plan
                or plan.receipt_fingerprint != gate.receipt_fingerprint
            ):
                raise CodingWorkerGatedRecoveryError(
                    "coding_worker_gated_recovery_payload_mismatch"
                )
            journal = open_coding_product_worker_supervisor_journal(product)
            if attempt.phase in _ABANDONED_ACTIVE_PHASES:
                attempt = journal.transition(
                    gate.attempt_id,
                    expected_phase=attempt.phase,
                    next_phase="failed",
                    expected_record_revision=attempt.record_revision,
                    expected_supervisor_epoch=attempt.supervisor_epoch,
                    failure_code=_ABANDONED_FAILURE_CODE,
                )
            return journal.transition(
                gate.attempt_id,
                expected_phase=attempt.phase,
                next_phase="process_settled",
                expected_record_revision=attempt.record_revision,
                expected_supervisor_epoch=attempt.supervisor_epoch,
                failure_code=attempt.failure_code,
            )
        finally:
            os.close(root_fd)


def _review_offline(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerGatedRecoveryReviewV1:
    gate = CodingWorkerStartGateJournal(product).current(attempt_id)
    attempt = open_coding_product_worker_supervisor_journal(product).status(attempt_id)
    if (
        gate is not None
        and attempt is not None
        and gate.worker_identity_fingerprint != attempt.identity_fingerprint
    ):
        raise CodingWorkerGatedRecoveryError(
            "coding_worker_start_gate_supervisor_mismatch"
        )
    native_current = False
    if gate is not None:
        try:
            closure = open_coding_product_installed_worker_release_reader(
                product
            ).current_closure()
        except CodingWorkerNativeReleaseError:
            pass
        else:
            native_current = (
                sha256(canonical_json_bytes(closure.to_dict())).hexdigest()
                == gate.native_closure_digest
            )
    group_status: GatedGroupStatus = "unobserved"
    if gate is not None and gate.identity is not None:
        observed: WorkerNativeGroupStatus = worker_native_group_status_after_restart(
            gate.identity
        )
        group_status = observed
    return CodingWorkerGatedRecoveryReviewV1(
        attempt_id=attempt_id,
        gate_record=gate,
        attempt_record=attempt,
        native_closure_current=native_current,
        group_status=group_status,
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
