"""Read-only Worker retention joins and proof projections, without IO authority."""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar, Generic, Literal, Protocol, TypeVar, cast

from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationSnapshotV1,
)
from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
from loushang.harness.worker.journal import WorkerAttemptRecordV1
from loushang.harness.worker.payload._records import PayloadPlan

from ._activation import _RetainedAttemptFields
from ._no_effect import is_no_effect_closure
from ._opt_in import _OptInDecisionMethods
from ._receipts import _ReceiptRecordMethods
from ._snapshot import _SnapshotMethods
from ._start_gate import _StartGateRecordMethods

GroupStatus = Literal[
    "unobserved", "absent", "present", "prior_boot_absent", "context_stale", "unknown"
]


class AttemptReference(Protocol):
    @property
    def plugin_id(self) -> str: ...
    @property
    def selected_package_revision_digest(self) -> str: ...


class BackupObservation(Protocol):
    @property
    def attempt_id(self) -> str: ...
    @property
    def worker_backup_supported(self) -> Literal[False]: ...
    @property
    def references(self) -> tuple[()]: ...


class RegisteredRepairReference(Protocol):
    @property
    def plan(self) -> PayloadPlan: ...
    @property
    def attempt_id(self) -> str: ...
    @property
    def gate_record_digest(self) -> str: ...
    @property
    def receipt_record_digest(self) -> str: ...
    @property
    def policy_fingerprint(self) -> str: ...
    @property
    def host_identity(self) -> str: ...
    @property
    def boot_identity(self) -> str: ...
    @property
    def owner_generation(self) -> int: ...
    def to_dict(self) -> dict[str, object]: ...


ReferenceT = TypeVar("ReferenceT", bound=AttemptReference)


def attempt_reference(
    gate: _StartGateRecordMethods | None,
    receipt: _ReceiptRecordMethods | None,
    *,
    product_id: str,
    reference_type: Callable[..., ReferenceT],
) -> ReferenceT | None:
    if gate is None or receipt is None:
        return None
    policy = receipt.receipt.policy
    if (
        gate.receipt_fingerprint != receipt.receipt.fingerprint
        or gate.policy_fingerprint != policy.fingerprint
        or gate.scope_id != policy.product_scope_id
        or policy.product_id != product_id
    ):
        return None
    return reference_type(
        attempt_id=gate.attempt_id,
        plugin_id=policy.plugin_id,
        receipt_fingerprint=gate.receipt_fingerprint,
        selected_package_revision_digest=policy.plugin_revision_digest,
        selected_locator_revision=policy.selected_locator_revision,
        native_platform="linux",
        gate_revision=gate.journal_revision,
        gate_phase=gate.phase,
    )


def gc_revision_refs(
    snapshot: PluginPackageGcReservationSnapshotV1,
) -> frozenset[PluginPackageRevisionRefV1]:
    """Extract Package revision pins from a versioned owner snapshot."""

    return frozenset(
        item.candidate.package_revision
        for item in snapshot.active
        if item.candidate is not None
    )


def matching_gc_revision_refs(
    *,
    plugin_id: str,
    package_content_digest: str,
    reservations: frozenset[PluginPackageRevisionRefV1],
) -> tuple[PluginPackageRevisionRefV1, ...]:
    """Keep every active reservation for the exact Plugin and Wheel artifact.

    The dependency lock may differ across retained Package revisions. This
    observation is not an attempt-level absence proof or prune authorization.
    """

    return tuple(
        sorted(
            (
                item
                for item in reservations
                if item.plugin_id == plugin_id
                and item.package_content_digest == package_content_digest
            ),
            key=lambda item: (
                item.dependency_lock_digest,
                item.package_source_identity,
                item.plugin_version or "",
            ),
        )
    )


def matching_attempt_gc_refs(
    reference: AttemptReference | None,
    reservations: frozenset[PluginPackageRevisionRefV1],
) -> tuple[PluginPackageRevisionRefV1, ...]:
    if reference is None:
        return ()
    return matching_gc_revision_refs(
        plugin_id=reference.plugin_id,
        package_content_digest=reference.selected_package_revision_digest,
        reservations=reservations,
    )


def receipt_gate_reference_issue(
    gate: _StartGateRecordMethods,
    receipt: _ReceiptRecordMethods | None,
    supervisor: WorkerAttemptRecordV1 | None,
    group_status: GroupStatus,
    activation: _RetainedAttemptFields | None = None,
    *,
    product_id: str,
) -> str | None:
    if receipt is None:
        return "receipt_reference_receipt_absent"
    if (
        gate.receipt_fingerprint != receipt.receipt.fingerprint
        or gate.policy_fingerprint != receipt.receipt.policy.fingerprint
        or gate.scope_id != receipt.receipt.policy.product_scope_id
    ):
        return "receipt_reference_binding_changed"
    if is_no_effect_closure(
        product_id=product_id,
        gate=gate,
        activation=activation,
        supervisor=supervisor,
        receipt=receipt,
    ):
        return None
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


def registered_repair_matches_no_effect_closure(
    intent: RegisteredRepairReference,
    *,
    product_id: str,
    gate: _StartGateRecordMethods | None,
    receipt: _ReceiptRecordMethods | None,
    activation: _RetainedAttemptFields | None,
    supervisor: WorkerAttemptRecordV1 | None,
) -> bool:
    if gate is None or receipt is None or activation is None:
        return False
    return bool(
        is_no_effect_closure(
            product_id=product_id,
            gate=gate,
            activation=activation,
            supervisor=supervisor,
            receipt=receipt,
        )
        and intent.attempt_id == gate.attempt_id
        and intent.plan.receipt_fingerprint == receipt.receipt.fingerprint
        and intent.gate_record_digest == gate.record_digest
        and intent.receipt_record_digest == receipt.record_digest
        and intent.policy_fingerprint == activation.policy_fingerprint
        and intent.host_identity == activation.host_identity
        and intent.boot_identity == activation.boot_identity
        and intent.owner_generation == activation.owner_generation
    )


class RetentionReviewMethods(Generic[ReferenceT]):
    __slots__ = ()

    _product_id: ClassVar[str]
    _reference_type: ClassVar[Callable[..., AttemptReference]]

    attempt_id: str
    gate_record: _StartGateRecordMethods | None
    attempt_record: WorkerAttemptRecordV1 | None
    receipt_record: _ReceiptRecordMethods | None
    current_opt_in: _OptInDecisionMethods | None
    historical_opt_in_verified: bool
    group_status: GroupStatus
    opt_in_history_revision: int
    retained_opt_in_operation_ids: tuple[str, ...]
    opt_in_generation_high_water: tuple[tuple[str, int, int, str, str], ...]
    start_gate_history_revision: int
    supervisor_history_revision: int
    receipt_history_revision: int
    retained_start_gate_attempt_ids: tuple[str, ...]
    retained_supervisor_attempt_ids: tuple[str, ...]
    retained_receipt_fingerprints: tuple[str, ...]
    history_stream_snapshots: tuple[_SnapshotMethods, ...]
    history_stream_revisions_match: bool
    supervisor_epoch_high_water: tuple[tuple[str, int], ...]
    unbound_supervisor_attempt_ids: tuple[str, ...]
    activation_state_revision: int | None
    active_activation_references: tuple[tuple[str, str], ...]
    retained_activation_references: tuple[_RetainedAttemptFields, ...]
    global_activation_reference_ids_match: bool
    unverified_activation_references: tuple[tuple[str, str], ...]
    global_unverified_activation_references: tuple[tuple[str, str], ...]
    global_unverified_opt_in_references: tuple[tuple[str, str], ...]
    receipt_gate_references: tuple[str, ...]
    unsettled_receipt_gate_references: tuple[str, ...]
    unverified_receipt_gate_references: tuple[tuple[str, str], ...]
    global_unverified_receipt_gate_references: tuple[tuple[str, str], ...]
    receipt_references_verified: bool
    payload_stage_names: tuple[str, ...]
    retained_payload_repair_reference_names: tuple[str, ...]
    registered_repair_reference_verified: bool
    unrecognized_worker_state_names: tuple[str, ...]
    active_runtime_lease_ids: tuple[str, ...]
    active_gc_reservation_count: int
    gc_reservation_revision: int
    gc_matching_revision_refs: tuple[PluginPackageRevisionRefV1, ...]
    worker_backup_references: BackupObservation | None

    @property
    def attempt_reference(self) -> ReferenceT | None:
        """Project a retained gate reference without claiming it is closed."""

        return attempt_reference(
            self.gate_record,
            self.receipt_record,
            product_id=self._product_id,
            reference_type=cast(Callable[..., ReferenceT], type(self)._reference_type),
        )

    @property
    def no_effect_closure(self) -> bool:
        gate = self.gate_record
        if gate is None:
            return False
        matching = tuple(
            item
            for item in self.retained_activation_references
            if item.attempt_id == self.attempt_id
        )
        return len(matching) == 1 and is_no_effect_closure(
            product_id=self._product_id,
            gate=gate,
            activation=matching[0],
            supervisor=self.attempt_record,
            receipt=self.receipt_record,
        )

    @property
    def missing_proofs(self) -> tuple[str, ...]:
        """Conservative observations; this is never a prune authorization."""

        missing: list[str] = []
        gate = self.gate_record
        attempt = self.attempt_record
        receipt = self.receipt_record
        no_effect = self.no_effect_closure
        if gate is None:
            missing.append("start_gate_absent")
        elif gate.phase != "bound" and not no_effect:
            missing.append("start_gate_unbound")
        if attempt is None and not no_effect:
            missing.append("supervisor_attempt_absent")
        elif attempt is not None and not attempt.process_settled:
            missing.append("supervisor_process_unsettled")
        if not no_effect and self.group_status not in {
            "absent",
            "prior_boot_absent",
        }:
            missing.append("native_group_absence_unverified")
        if receipt is None:
            missing.append("activation_receipt_absent")
        elif gate is not None and (
            receipt.receipt.fingerprint != gate.receipt_fingerprint
            or receipt.receipt.policy.product_id != self._product_id
            or receipt.receipt.policy.fingerprint != gate.policy_fingerprint
            or receipt.receipt.policy.product_scope_id != gate.scope_id
        ):
            missing.append("activation_receipt_binding_changed")
        if receipt is not None and not self.historical_opt_in_verified:
            missing.append("historical_opt_in_unverified")
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
        if self.global_unverified_activation_references:
            missing.append("global_activation_reference_unverified")
        if not self.global_activation_reference_ids_match:
            missing.append("global_activation_attempt_ids_unmatched")
        if self.global_unverified_opt_in_references:
            missing.append("global_opt_in_reference_unverified")
        if self.unbound_supervisor_attempt_ids:
            missing.append("supervisor_gate_reference_unverified")
        if self.unsettled_receipt_gate_references:
            missing.append("receipt_gate_attempt_unsettled")
        if self.unverified_receipt_gate_references:
            missing.append("receipt_gate_reference_unverified")
        if self.global_unverified_receipt_gate_references:
            missing.append("global_receipt_gate_reference_unverified")
        if self.payload_stage_names:
            missing.append("payload_stage_retained")
        if (
            self.retained_payload_repair_reference_names
            and not self.registered_repair_reference_verified
        ):
            missing.append("payload_repair_reference_retained")
        if self.unrecognized_worker_state_names:
            missing.append("worker_reference_owner_unrecognized")
        if not self.history_stream_revisions_match:
            missing.append("history_stream_revision_changed")
        if self.active_runtime_lease_ids:
            missing.append("runtime_lease_active")
        if self.active_gc_reservation_count:
            missing.append("gc_reservation_scope_unverified")
        if self.gc_matching_revision_refs:
            missing.append("gc_attempt_package_revision_active")
        if not self.receipt_references_verified:
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
