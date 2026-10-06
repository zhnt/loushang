"""Read-only Product evidence for one Linux Worker history-retention decision.

This inventory grants no journal deletion authority. The current Product
backup type authority attests that Worker backups are unsupported; GC still
lacks an attempt-level closure decision.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.worker.gated_start import (
    worker_native_group_status_after_restart,
)
from loushang.harness.worker.journal import WorkerAttemptRecordV1

from .package_product_backup_types import (
    CodingWorkerBackupReferenceObservationV1,
    observe_coding_worker_backup_references_under_gc_guard,
)
from .package_product_worker_activation_state_journal import (
    CodingProductWorkerActivationStateJournal,
    CodingProductWorkerRetainedAttemptV1,
)
from .package_product_worker_gc_references import (
    coding_worker_gc_revision_refs,
    matching_coding_worker_gc_revision_refs,
)
from .package_product_worker_opt_in import (
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournal,
)
from .package_product_worker_opt_in_owner import CodingWorkerProductOptInOwner
from .package_product_worker_payload import (
    open_coding_product_worker_supervisor_journal,
)
from .package_product_worker_receipt import (
    CodingWorkerReceiptRecordV1,
    read_coding_product_worker_receipt_records,
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
_SEGMENTED_STEMS = (
    "worker-opt-in",
    "worker-activation-receipts",
    "worker-activation-state",
    "worker-start-gates",
    "worker-supervisor",
)
_SEGMENTED_SUFFIX = re.compile(
    r"(?:\.jsonl(?:\.lock)?|\.segments\.json|\.head\.json|"
    r"\.g[0-9]{8}\.(?:jsonl|head\.json))\Z"
)
_PAYLOAD_STAGE = re.compile(r"worker-payload-[0-9a-f]{32}\Z")
_PAYLOAD_REPAIR = re.compile(
    r"worker-(?P<kind>empty|complete|unmarked)-repair-"
    r"(?P<attempt>[0-9a-f]{32})\.json\Z"
)


def _known_worker_state_name(name: str) -> bool:
    if name in {
        "worker-native-release-v1",
        "worker-native-release-approvals.jsonl",
        "worker-native-release-approvals.jsonl.lock",
    }:
        return True
    if _PAYLOAD_STAGE.fullmatch(name) or _PAYLOAD_REPAIR.fullmatch(name):
        return True
    return any(
        _SEGMENTED_SUFFIX.fullmatch(name[len(stem) :]) is not None
        for stem in _SEGMENTED_STEMS
        if name.startswith(stem)
    )


@dataclass(frozen=True, slots=True)
class CodingWorkerAttemptReferenceV1:
    """One retained Linux gate intent joined to its exact Product receipt.

    The start-gate journal supplies a durable reference for the ordinary
    pending Host and the explicit operator query. C5 attempt state remains a
    separate authority. This projection grants no closure or pruning power.
    """

    attempt_id: str
    plugin_id: str
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
        plugin_id=policy.plugin_id,
        receipt_fingerprint=gate.receipt_fingerprint,
        selected_package_revision_digest=policy.plugin_revision_digest,
        selected_locator_revision=policy.selected_locator_revision,
        native_platform="linux",
        gate_revision=gate.journal_revision,
        gate_phase=gate.phase,
    )


def _matching_gc_revision_refs(
    reference: CodingWorkerAttemptReferenceV1 | None,
    reservations: frozenset[PluginPackageRevisionRefV1],
) -> tuple[PluginPackageRevisionRefV1, ...]:
    if reference is None:
        return ()
    return matching_coding_worker_gc_revision_refs(
        plugin_id=reference.plugin_id,
        package_content_digest=reference.selected_package_revision_digest,
        reservations=reservations,
    )


def _receipt_gate_reference_issue(
    gate: CodingWorkerStartGateRecordV1,
    receipt: CodingWorkerReceiptRecordV1 | None,
    supervisor: WorkerAttemptRecordV1 | None,
    group_status: GatedGroupStatus,
) -> str | None:
    """Require every attempt naming a receipt to have settled native custody."""

    if receipt is None:
        return "receipt_reference_receipt_absent"
    if (
        gate.receipt_fingerprint != receipt.receipt.fingerprint
        or gate.policy_fingerprint != receipt.receipt.policy.fingerprint
        or gate.scope_id != receipt.receipt.policy.product_scope_id
    ):
        return "receipt_reference_binding_changed"
    if gate.phase != "bound":
        return "receipt_reference_gate_unbound"
    if supervisor is None:
        return "receipt_reference_supervisor_absent"
    if supervisor.identity_fingerprint != gate.worker_identity_fingerprint:
        return "receipt_reference_supervisor_binding_changed"
    if not supervisor.process_settled:
        return "receipt_reference_supervisor_unsettled"
    if group_status not in {"absent", "prior_boot_absent"}:
        return "receipt_reference_native_absence_unverified"
    return None


@dataclass(frozen=True, slots=True)
class CodingWorkerHistoryRetentionReviewV1:
    attempt_id: str
    gate_record: CodingWorkerStartGateRecordV1 | None
    attempt_record: WorkerAttemptRecordV1 | None
    receipt_record: CodingWorkerReceiptRecordV1 | None
    current_opt_in: CodingWorkerOptInDecisionV1 | None
    group_status: GatedGroupStatus
    opt_in_history_revision: int
    retained_opt_in_operation_ids: tuple[str, ...]
    start_gate_history_revision: int
    supervisor_history_revision: int
    receipt_history_revision: int
    retained_start_gate_attempt_ids: tuple[str, ...]
    retained_supervisor_attempt_ids: tuple[str, ...]
    retained_receipt_fingerprints: tuple[str, ...]
    supervisor_epoch_high_water: tuple[tuple[str, int], ...]
    unbound_supervisor_attempt_ids: tuple[str, ...]
    activation_state_revision: int | None
    active_activation_references: tuple[tuple[str, str], ...]
    retained_activation_references: tuple[CodingProductWorkerRetainedAttemptV1, ...]
    unverified_activation_references: tuple[tuple[str, str], ...]
    receipt_gate_references: tuple[str, ...]
    unsettled_receipt_gate_references: tuple[str, ...]
    unverified_receipt_gate_references: tuple[tuple[str, str], ...]
    payload_stage_names: tuple[str, ...]
    retained_payload_repair_reference_names: tuple[str, ...]
    unrecognized_worker_state_names: tuple[str, ...]
    active_runtime_lease_ids: tuple[str, ...]
    active_gc_reservation_count: int
    gc_reservation_revision: int
    gc_matching_revision_refs: tuple[PluginPackageRevisionRefV1, ...]
    worker_backup_references: CodingWorkerBackupReferenceObservationV1 | None

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
        if self.unverified_activation_references:
            missing.append("activation_receipt_reference_unverified")
        if self.unbound_supervisor_attempt_ids:
            missing.append("supervisor_gate_reference_unverified")
        if self.unsettled_receipt_gate_references:
            missing.append("receipt_gate_attempt_unsettled")
        if self.unverified_receipt_gate_references:
            missing.append("receipt_gate_reference_unverified")
        if self.payload_stage_names:
            missing.append("payload_stage_retained")
        if self.retained_payload_repair_reference_names:
            missing.append("payload_repair_reference_retained")
        if self.unrecognized_worker_state_names:
            missing.append("worker_reference_owner_unrecognized")
        if self.active_runtime_lease_ids:
            missing.append("runtime_lease_active")
        if self.active_gc_reservation_count:
            missing.append("gc_reservation_scope_unverified")
        if self.gc_matching_revision_refs:
            missing.append("gc_attempt_package_revision_active")
        missing.append("receipt_references_unverified")
        backup = self.worker_backup_references
        if (
            backup is None
            or backup.attempt_id != self.attempt_id
            or backup.worker_backup_supported is not False
        ):
            missing.append("worker_backup_references_unverified")
        elif backup.references:
            missing.append("worker_backup_reference_active")
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
        with product.gc_gate.read_snapshot_guard() as gc_snapshot:
            gc_reservations = coding_worker_gc_revision_refs(gc_snapshot)
            product.assert_root_gc_authority_current()
            gated = _review_offline(product, attempt_id=attempt_id)
            gate = gated.gate_record
            receipts = read_coding_product_worker_receipt_records(product)
            receipt = (
                None
                if gate is None
                else next(
                    (
                        record
                        for record in receipts
                        if record.receipt.fingerprint == gate.receipt_fingerprint
                    ),
                    None,
                )
            )
            opt_in = (
                None
                if receipt is None
                else CodingWorkerProductOptInOwner(product).current(
                    receipt.receipt.policy.plugin_id
                )
            )
            opt_in_history = CodingWorkerOptInJournal(
                product.state_root / "worker-opt-in.jsonl",
                scope_id=product.policy.project_scope_id,
                gc_gate=product.gc_gate,
            )._history_under_gc_guard()
            activation_journal = CodingProductWorkerActivationStateJournal(
                product.state_root / "worker-activation-state.jsonl"
            )
            activation_initialized, activation_state = (
                activation_journal.load_with_presence_read_only()
            )
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
            gates = CodingWorkerStartGateJournal(product).attempts()
            gate_by_id = {item.attempt_id: item for item in gates}
            supervisor = open_coding_product_worker_supervisor_journal(product)
            supervisor_by_id = {
                item.attempt_id: item for item in supervisor.attempts()
            }
            supervisor_epoch_by_key: dict[str, int] = {}
            for record in supervisor_by_id.values():
                supervisor_epoch_by_key[record.supervisor_key] = max(
                    supervisor_epoch_by_key.get(record.supervisor_key, 0),
                    record.supervisor_epoch,
                )
            unbound_supervisor_attempt_ids = tuple(
                sorted(supervisor_by_id.keys() - gate_by_id.keys())
            )
            unverified_activation: list[tuple[str, str]] = []
            for reference in retained_activation_references:
                if reference.attempt_id != attempt_id and (
                    receipt is None
                    or reference.receipt_fingerprint != receipt.receipt.fingerprint
                ):
                    continue
                referenced_gate = gate_by_id.get(reference.attempt_id)
                code: str | None
                if referenced_gate is None:
                    code = "activation_reference_gate_absent"
                elif (
                    referenced_gate.receipt_fingerprint
                    != reference.receipt_fingerprint
                    or referenced_gate.policy_fingerprint
                    != reference.policy_fingerprint
                ):
                    code = "activation_reference_binding_changed"
                elif referenced_gate.phase != "bound":
                    code = "activation_reference_gate_unbound"
                elif reference.phase != "settled":
                    code = "activation_reference_unsettled"
                else:
                    status = supervisor_by_id.get(reference.attempt_id)
                    code = (
                        "activation_reference_supervisor_unsettled"
                        if status is None
                        or not status.process_settled
                        or status.identity_fingerprint
                        != referenced_gate.worker_identity_fingerprint
                        else None
                    )
                if code is not None:
                    unverified_activation.append((reference.attempt_id, code))
            receipt_gate_references: tuple[str, ...] = ()
            unsettled_gate_references: tuple[str, ...] = ()
            unverified_gate_references: tuple[tuple[str, str], ...] = ()
            if gate is not None:
                matching_gates = tuple(
                    item
                    for item in gates
                    if item.receipt_fingerprint == gate.receipt_fingerprint
                )
                receipt_gate_references = tuple(
                    item.attempt_id for item in matching_gates
                )
                unsettled: list[str] = []
                unverified: list[tuple[str, str]] = []
                for item in matching_gates:
                    status = supervisor_by_id.get(item.attempt_id)
                    group_status: GatedGroupStatus = (
                        gated.group_status
                        if item.attempt_id == attempt_id
                        else (
                            "unobserved"
                            if item.identity is None
                            else worker_native_group_status_after_restart(item.identity)
                        )
                    )
                    issue = _receipt_gate_reference_issue(
                        item, receipt, status, group_status
                    )
                    if issue is not None:
                        if issue in {
                            "receipt_reference_gate_unbound",
                            "receipt_reference_supervisor_absent",
                            "receipt_reference_supervisor_unsettled",
                        }:
                            unsettled.append(item.attempt_id)
                        unverified.append((item.attempt_id, issue))
                unsettled_gate_references = tuple(unsettled)
                unverified_gate_references = tuple(unverified)
            with product.pinned_state_root_gc_read() as root_fd:
                state_names = tuple(os.listdir(root_fd))
                payloads = tuple(
                    sorted(
                        name
                        for name in state_names
                        if name.startswith("worker-payload-")
                    )
                )
                repair_references = tuple(
                    sorted(
                        name
                        for name in state_names
                        if _PAYLOAD_REPAIR.fullmatch(name) is not None
                    )
                )
                unrecognized_worker_state = tuple(
                    sorted(
                        name
                        for name in state_names
                        if name.casefold().startswith(("worker-", ".worker-"))
                        and not _known_worker_state_name(name)
                    )
                )
            product.assert_root_gc_authority_current()
            attempt_reference = _attempt_reference(gate, receipt)
            return CodingWorkerHistoryRetentionReviewV1(
                attempt_id=attempt_id,
                gate_record=gate,
                attempt_record=gated.attempt_record,
                receipt_record=receipt,
                current_opt_in=opt_in,
                group_status=gated.group_status,
                opt_in_history_revision=len(opt_in_history),
                retained_opt_in_operation_ids=tuple(
                    item.operation_id for item in opt_in_history
                ),
                start_gate_history_revision=max(
                    (item.journal_revision for item in gates), default=0
                ),
                supervisor_history_revision=max(
                    (item.record_revision for item in supervisor_by_id.values()),
                    default=0,
                ),
                receipt_history_revision=len(receipts),
                retained_start_gate_attempt_ids=tuple(sorted(gate_by_id)),
                retained_supervisor_attempt_ids=tuple(sorted(supervisor_by_id)),
                retained_receipt_fingerprints=tuple(
                    sorted(item.receipt.fingerprint for item in receipts)
                ),
                supervisor_epoch_high_water=tuple(
                    sorted(supervisor_epoch_by_key.items())
                ),
                unbound_supervisor_attempt_ids=unbound_supervisor_attempt_ids,
                activation_state_revision=(
                    None
                    if not activation_initialized
                    else (
                        0
                        if activation_state is None
                        else cast(int, activation_state["stateRevision"])
                    )
                ),
                active_activation_references=active_references,
                retained_activation_references=retained_activation_references,
                unverified_activation_references=tuple(unverified_activation),
                receipt_gate_references=receipt_gate_references,
                unsettled_receipt_gate_references=unsettled_gate_references,
                unverified_receipt_gate_references=unverified_gate_references,
                payload_stage_names=payloads,
                retained_payload_repair_reference_names=repair_references,
                unrecognized_worker_state_names=unrecognized_worker_state,
                active_runtime_lease_ids=quiescence.active_runtime_lease_ids,
                active_gc_reservation_count=len(gc_reservations),
                gc_reservation_revision=gc_snapshot.journal_revision,
                gc_matching_revision_refs=_matching_gc_revision_refs(
                    attempt_reference, gc_reservations
                ),
                worker_backup_references=(
                    observe_coding_worker_backup_references_under_gc_guard(
                        product, attempt_id=attempt_id
                    )
                ),
            )


__all__ = [
    "CodingWorkerAttemptReferenceV1",
    "CodingWorkerHistoryRetentionReviewV1",
    "review_coding_product_worker_history_retention",
]
