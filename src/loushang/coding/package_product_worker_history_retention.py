"""Read-only Product evidence for one Linux Worker history-retention decision.

This inventory grants no journal deletion authority. In particular, the
existing backup and GC owners do not attest to attempt-level references.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1

from .package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_opt_in_owner import CodingWorkerProductOptInOwner
from .package_product_worker_payload import (
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
from .package_product_worker_start_gate_recovery import (
    GatedGroupStatus,
    _review_offline,
)

_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class CodingWorkerAttemptReferenceV1:
    """One retained Linux gate intent joined to its exact Product receipt.

    The start-gate journal supplies a durable reference for the ordinary
    pending Host and the explicit operator query. C5 attempt state remains a
    separate authority. This projection grants no closure or pruning power.
    """

    attempt_id: str
    receipt_fingerprint: str
    selected_package_revision_digest: str
    selected_locator_revision: str
    native_platform: Literal["linux"]
    gate_revision: int
    gate_phase: Literal["intent", "bound"]


def _attempt_reference(
    gate: CodingWorkerStartGateRecordV1 | None,
    receipt: CodingWorkerReceiptRecordV1 | None,
) -> CodingWorkerAttemptReferenceV1 | None:
    if gate is None or receipt is None:
        return None
    policy = receipt.receipt.policy
    if (
        gate.receipt_fingerprint != receipt.receipt.fingerprint
        or gate.policy_fingerprint != policy.fingerprint
        or gate.scope_id != policy.product_scope_id
        or policy.product_id != "coding"
    ):
        return None
    return CodingWorkerAttemptReferenceV1(
        attempt_id=gate.attempt_id,
        receipt_fingerprint=gate.receipt_fingerprint,
        selected_package_revision_digest=policy.plugin_revision_digest,
        selected_locator_revision=policy.selected_locator_revision,
        native_platform="linux",
        gate_revision=gate.journal_revision,
        gate_phase=gate.phase,
    )


@dataclass(frozen=True, slots=True)
class CodingWorkerHistoryRetentionReviewV1:
    attempt_id: str
    gate_record: CodingWorkerStartGateRecordV1 | None
    attempt_record: WorkerAttemptRecordV1 | None
    receipt_record: CodingWorkerReceiptRecordV1 | None
    current_opt_in: CodingWorkerOptInDecisionV1 | None
    group_status: GatedGroupStatus
    activation_state_revision: int | None
    active_activation_references: tuple[tuple[str, str], ...]
    retained_activation_references: tuple[CodingProductWorkerRetainedAttemptV1, ...]
    receipt_gate_references: tuple[str, ...]
    unsettled_receipt_gate_references: tuple[str, ...]
    payload_stage_names: tuple[str, ...]
    active_runtime_lease_ids: tuple[str, ...]
    active_gc_reservation_count: int

    @property
    def attempt_reference(self) -> CodingWorkerAttemptReferenceV1 | None:
        """Project a retained gate reference without claiming it is closed."""

        return _attempt_reference(self.gate_record, self.receipt_record)

    @property
    def missing_proofs(self) -> tuple[str, ...]:
        """Conservative observations; this is never a prune authorization."""

        missing: list[str] = []
        gate = self.gate_record
        attempt = self.attempt_record
        receipt = self.receipt_record
        if gate is None:
            missing.append("start_gate_absent")
        elif gate.phase != "bound":
            missing.append("start_gate_unbound")
        if attempt is None:
            missing.append("supervisor_attempt_absent")
        elif not attempt.process_settled:
            missing.append("supervisor_process_unsettled")
        if self.group_status not in {"absent", "prior_boot_absent"}:
            missing.append("native_group_absence_unverified")
        if receipt is None:
            missing.append("activation_receipt_absent")
        elif gate is not None and (
            receipt.receipt.fingerprint != gate.receipt_fingerprint
            or receipt.receipt.policy.product_id != "coding"
            or receipt.receipt.policy.fingerprint != gate.policy_fingerprint
            or receipt.receipt.policy.product_scope_id != gate.scope_id
        ):
            missing.append("activation_receipt_binding_changed")
        if (
            receipt is not None
            and self.current_opt_in is not None
            and self.current_opt_in.decision_digest == receipt.opt_in_decision_digest
        ):
            missing.append("opt_in_decision_still_current")
        if gate is not None and self.activation_state_revision is None:
            missing.append("activation_state_absent")
        if receipt is not None and any(
            fingerprint == receipt.receipt.fingerprint
            for fingerprint, _ in self.active_activation_references
        ):
            missing.append("activation_receipt_active")
        for reference in self.retained_activation_references:
            if reference.attempt_id != self.attempt_id:
                continue
            if reference.phase != "settled":
                missing.append("activation_attempt_unsettled")
            if gate is not None and (
                reference.receipt_fingerprint != gate.receipt_fingerprint
                or reference.policy_fingerprint != gate.policy_fingerprint
            ):
                missing.append("activation_attempt_binding_changed")
        if self.unsettled_receipt_gate_references:
            missing.append("receipt_gate_attempt_unsettled")
        if self.payload_stage_names:
            missing.append("payload_stage_retained")
        if self.active_runtime_lease_ids:
            missing.append("runtime_lease_active")
        if self.active_gc_reservation_count:
            missing.append("gc_reservation_scope_unverified")
        missing.extend(
            (
                "receipt_references_unverified",
                "worker_backup_references_unverified",
            )
        )
        return tuple(missing)


def review_coding_product_worker_history_retention(
    product: PosixLocalWheelProductSessionOwner, *, attempt_id: str
) -> CodingWorkerHistoryRetentionReviewV1:
    """Join fresh Product facts while runtime and GC owner locks are held."""

    if (
        not isinstance(product, PosixLocalWheelProductSessionOwner)
        or product.policy.product_id != "coding"
        or type(attempt_id) is not str
        or _ATTEMPT.fullmatch(attempt_id) is None
    ):
        raise ValueError(
            "Coding Worker history review requires an exact Product attempt"
        )
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id, read_only=True
    ) as quiescence:
        with product.gc_gate.read_guard() as gc_reservations:
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
            opt_in = (
                None
                if receipt is None
                else CodingWorkerProductOptInOwner(product).current(
                    receipt.receipt.policy.plugin_id
                )
            )
            activation_journal = CodingProductWorkerActivationStateJournal(
                product.state_root / "worker-activation-state.jsonl"
            )
            activation_state = activation_journal.load_read_only()
            retained_activation_references = (
                activation_journal.retained_attempts_read_only()
            )
            active_references: tuple[tuple[str, str], ...] = ()
            if activation_state is not None:
                attempts = cast(
                    dict[str, dict[str, object]], activation_state["attempts"]
                )
                active_references = tuple(
                    sorted(
                        (
                            cast(str, item["receiptFingerprint"]),
                            cast(str, item["attemptId"]),
                        )
                        for item in attempts.values()
                        if item["phase"] != "settled"
                    )
                )
            receipt_gate_references: tuple[str, ...] = ()
            unsettled_gate_references: tuple[str, ...] = ()
            if gate is not None:
                matching_gates = tuple(
                    item
                    for item in CodingWorkerStartGateJournal(product).attempts()
                    if item.receipt_fingerprint == gate.receipt_fingerprint
                )
                receipt_gate_references = tuple(
                    item.attempt_id for item in matching_gates
                )
                supervisor = open_coding_product_worker_supervisor_journal(product)
                unsettled: list[str] = []
                for item in matching_gates:
                    status = supervisor.status(item.attempt_id)
                    if (
                        item.phase != "bound"
                        or status is None
                        or not status.process_settled
                    ):
                        unsettled.append(item.attempt_id)
                unsettled_gate_references = tuple(unsettled)
            with product.pinned_state_root_gc_read() as root_fd:
                payloads = tuple(
                    sorted(
                        name
                        for name in os.listdir(root_fd)
                        if name.startswith("worker-payload-")
                    )
                )
            product.assert_root_gc_authority_current()
            return CodingWorkerHistoryRetentionReviewV1(
                attempt_id=attempt_id,
                gate_record=gate,
                attempt_record=gated.attempt_record,
                receipt_record=receipt,
                current_opt_in=opt_in,
                group_status=gated.group_status,
                activation_state_revision=(
                    None
                    if activation_state is None
                    else cast(int, activation_state["stateRevision"])
                ),
                active_activation_references=active_references,
                retained_activation_references=retained_activation_references,
                receipt_gate_references=receipt_gate_references,
                unsettled_receipt_gate_references=unsettled_gate_references,
                payload_stage_names=payloads,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                active_gc_reservation_count=len(gc_reservations),
            )


__all__ = [
    "CodingWorkerAttemptReferenceV1",
    "CodingWorkerHistoryRetentionReviewV1",
    "review_coding_product_worker_history_retention",
]
