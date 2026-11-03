"""Read-only PLC9D audit of precommit root claims and their owner evidence.

Rows are diagnostic only. Even a terminal failed operation is not proof that
the claim can be released from a different Product or owner composition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.harness.plugin_management.gc_fence import (
    PluginPackageGcReferenceGatePort,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
    PluginManagementOperationEvent,
)
from loushang.harness.plugin_management.operations import (
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
    PluginPackageGcBindingV1,
    PluginPackageGcClaimV1,
)

ClaimAuditState = Literal[
    "unsubmitted",
    "in_flight",
    "failed_unproven",
    "binding_missing",
    "confirmed",
    "evidence_conflict",
]


class PackageGcClaimManagementPort(Protocol):
    @property
    def gc_gate(self) -> PluginPackageGcReferenceGatePort | None: ...

    def operations(self) -> tuple[PluginManagementOperationEvent, ...]: ...


class PackageGcClaimDesiredPort(Protocol):
    @property
    def gc_gate(self) -> PluginPackageGcReferenceGatePort | None: ...

    def transitions(self) -> tuple[PluginDesiredStateJournalTransition, ...]: ...


@dataclass(frozen=True, slots=True)
class PluginPackageGcClaimAuditRowV1:
    claim: PluginPackageGcClaimV1
    state: ClaimAuditState
    operation_error_code: str | None


class PluginPackageGcClaimAudit:
    """Capture current claim, operation, and desired evidence under one gate."""

    def __init__(
        self,
        *,
        bindings: PluginPackageGcBindingJournal,
        management: PackageGcClaimManagementPort,
        desired: PackageGcClaimDesiredPort,
        gate: PluginPackageGcReferenceGatePort,
    ) -> None:
        if not isinstance(bindings, PluginPackageGcBindingJournal):
            raise TypeError("Package GC binding journal is required")
        if not callable(getattr(gate, "guard", None)):
            raise TypeError("Package GC reference gate is required")
        if management.gc_gate is not gate or desired.gc_gate is not gate:
            raise ValueError("Package GC claim audit owner gates differ")
        if not callable(getattr(management, "operations", None)) or not callable(
            getattr(desired, "transitions", None)
        ):
            raise TypeError("Package GC claim audit owners are required")
        self._bindings = bindings
        self._management = management
        self._desired = desired
        self._gate = gate

    def snapshot(self) -> tuple[PluginPackageGcClaimAuditRowV1, ...]:
        with self._gate.guard():
            claims = self._bindings.claims()
            bindings = self._bindings.records()
            operations = self._management.operations()
            transitions = self._desired.transitions()
            return tuple(
                _review(claim, bindings, operations, transitions)
                for claim in claims
            )


def _review(
    claim: PluginPackageGcClaimV1,
    bindings: tuple[PluginPackageGcBindingV1, ...],
    operations: tuple[PluginManagementOperationEvent, ...],
    transitions: tuple[PluginDesiredStateJournalTransition, ...],
) -> PluginPackageGcClaimAuditRowV1:
    request = claim.request
    matches = tuple(
        item
        for item in bindings
        if item.request.desired_request_id == request.desired_request_id
    )
    op_matches = tuple(
        item
        for item in operations
        if item.command.operation_id == request.command_id
        or item.command.idempotency_key == request.desired_request_id
    )
    transition_matches = tuple(
        item
        for item in transitions
        if item.mutation.operation_id == request.command_id
        or item.mutation.idempotency_key == request.desired_request_id
    )
    if (
        len(matches) > 1
        or any(
            item.request != request or item.package_revision != claim.package_revision
            for item in matches
        )
        or len(op_matches) > 1
        or len(transition_matches) > 1
    ):
        return _row(claim, "evidence_conflict")
    if not op_matches:
        return _row(
            claim,
            "evidence_conflict" if matches or transition_matches else "unsubmitted",
        )
    operation = op_matches[0]
    if not isinstance(operation, PluginManagementOperationEventV1) or not _matches_claim(
        operation, claim
    ):
        return _row(claim, "evidence_conflict")
    transition = transition_matches[0] if transition_matches else None
    if transition is not None and transition.mutation != operation.command.mutation:
        return _row(claim, "evidence_conflict")
    if operation.status != "terminal":
        return _row(
            claim,
            "evidence_conflict" if matches or transition is not None else "in_flight",
        )
    result = operation.result
    if result is None:
        return _row(claim, "evidence_conflict")
    if result.disposition == "failed":
        return _row(
            claim,
            "evidence_conflict" if matches or transition is not None else "failed_unproven",
            error_code=result.error_code,
        )
    if result.transition != transition or transition is None:
        return _row(claim, "evidence_conflict")
    if not matches:
        return _row(claim, "binding_missing")
    if matches[0].desired_transition_revision != transition.inventory_revision:
        return _row(claim, "evidence_conflict")
    return _row(claim, "confirmed")


def _matches_claim(
    operation: PluginManagementOperationEventV1,
    claim: PluginPackageGcClaimV1,
) -> bool:
    request = claim.request
    command = operation.command
    mutation = command.mutation
    key = mutation.installation_key
    return (
        command.action == "install"
        and mutation.operation_id == request.command_id
        and mutation.idempotency_key == request.desired_request_id
        and mutation.expected_inventory_revision == request.expected_inventory_revision
        and mutation.package_revision == claim.package_revision
        and mutation.desired_state == "installed_disabled"
        and key.product_id == request.product_id
        and key.scope_id == request.scope_id
        and key.plugin_id == request.plugin_id
    )


def _row(
    claim: PluginPackageGcClaimV1,
    state: ClaimAuditState,
    *,
    error_code: str | None = None,
) -> PluginPackageGcClaimAuditRowV1:
    return PluginPackageGcClaimAuditRowV1(
        claim=claim,
        state=state,
        operation_error_code=error_code,
    )


__all__ = [
    "ClaimAuditState",
    "PackageGcClaimDesiredPort",
    "PackageGcClaimManagementPort",
    "PluginPackageGcClaimAudit",
    "PluginPackageGcClaimAuditRowV1",
]
