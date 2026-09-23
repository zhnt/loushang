"""Internal Product coordinator for one exact PLC9D Package root deletion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
    PluginPackageGcBindingV1,
    PluginPackageGcClaimV1,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcDeletionStartV2,
    PluginPackageGcReservationEventV1,
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_gc_results import (
    PluginPackageGcAttemptV1,
    PluginPackageGcResultJournal,
)
from loushang.harness.plugin_management.package_gc_target import (
    PluginPackageGcRootTargetV1,
    PluginPackageGcTargetError,
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageGcCandidateV1,
    PluginPackageLifecycleLedger,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
    PackageCommittedSetRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_gc import (
    PackageStoreGcResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
    PackageStoreSettlementRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
)


class PackageProductGcExecutionError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageProductGcRootStorePort(Protocol):
    def delete_settlement(
        self, settlement: PackageStoreSettlementRecordV1
    ) -> PackageStoreGcResultV1: ...


@dataclass(frozen=True, slots=True)
class PackageProductRootGcCommandV1:
    """An exact operator candidate, separate from Plugin removal."""

    candidate: PluginPackageGcCandidateV1
    reservation_operation_id: str
    reservation_idempotency_key: str
    attempt_operation_id: str
    attempt_idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, PluginPackageGcCandidateV1):
            raise TypeError("Exact Package GC candidate is required")
        for value in (
            self.reservation_operation_id,
            self.reservation_idempotency_key,
            self.attempt_operation_id,
            self.attempt_idempotency_key,
        ):
            if type(value) is not str or not value:
                raise ValueError("Package GC command identities are required")


@dataclass(frozen=True, slots=True)
class PackageProductRootGcExecutor:
    """Keep Product reference exclusion through exact Store settlement."""

    gate: PluginPackageGcReservationJournal
    lifecycle: PluginPackageLifecycleLedger
    bindings: PluginPackageGcBindingJournal
    committed_sets: PackageCommittedSetJournal
    root_settlements: PackageStoreSettlementJournal
    root_store: PackageProductGcRootStorePort
    results: PluginPackageGcResultJournal

    def __post_init__(self) -> None:
        if not self.lifecycle.gc_reservation_graph_bound_to(self.gate):
            raise ValueError("Package GC executor requires the bound reference graph")
        if not callable(getattr(self.root_store, "delete_settlement", None)):
            raise TypeError("Package GC executor requires the exact Store owner")

    def execute(
        self,
        reservation_id: str,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> PluginPackageGcAttemptV1:
        """Settle one reserved root; a crash leaves a retryable exact start."""

        if (
            type(operation_id) is not str
            or not operation_id
            or type(idempotency_key) is not str
            or not idempotency_key
        ):
            raise ValueError("Package GC attempt identity is required")
        with self.gate.guard():
            reservation = next(
                (
                    item
                    for item in self.gate.snapshot().active
                    if item.reservation_id == reservation_id
                ),
                None,
            )
            if reservation is None or reservation.candidate is None:
                raise PackageProductGcExecutionError(
                    "Package GC reservation is not active",
                    code="plugin_package_gc_stale",
                )
            if not self.lifecycle.gc_writer_epoch_sealed():
                raise PackageProductGcExecutionError(
                    "Package GC writer epoch is not sealed",
                    code="plugin_package_gc_writer_epoch_unsealed",
                )
            target = resolve_plugin_package_gc_root_target(
                reservation.candidate.package_revision,
                bindings=self.bindings.records(),
                claims=self.bindings.claims(),
                committed_sets=self.committed_sets.records(),
                settlements=self.root_settlements.records(),
            )
            start = self.gate.begin_delete(
                reservation_id,
                lifecycle=self.lifecycle,
                target_settlement_ids=(target.settlement_id,),
                operation_id=f"gc-start:{reservation_id}",
                idempotency_key=f"gc-start:{reservation_id}",
            )
            attempts = self.results.attempts(start)
            for prior in attempts:
                if prior.settlement_id != target.settlement_id:
                    continue
                if prior.disposition in {"succeeded", "terminal_failure"}:
                    if prior.disposition == "succeeded":
                        self._require_completed_fences(target)
                    return prior
                if (
                    prior.operation_id == operation_id
                    or prior.idempotency_key == idempotency_key
                ):
                    if (
                        prior.operation_id == operation_id
                        and prior.idempotency_key == idempotency_key
                    ):
                        return prior
                    raise PackageProductGcExecutionError(
                        "Package GC attempt identity was reused",
                        code="plugin_package_gc_result_conflict",
                    )
            self.results.preflight(
                start,
                settlement=target.settlement,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
            )
            self.committed_sets.tombstone(target.committed_set)
            try:
                result = self.root_store.delete_settlement(target.settlement)
            except PackagePhysicalStagingError as exc:
                return self.results.record(
                    start,
                    settlement=target.settlement,
                    operation_id=operation_id,
                    idempotency_key=idempotency_key,
                    error_code=exc.code,
                    terminal=True,
                )
            self._require_completed_fences(target)
            return self.results.record(
                start,
                settlement=target.settlement,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                store_result=result,
            )

    def _require_completed_fences(self, target: PluginPackageGcRootTargetV1) -> None:
        root_ref_id = target.settlement.receipt.stable_ref.ref_id
        if not (
            self.committed_sets.is_tombstoned(root_ref_id)
            and self.root_settlements.is_tombstoned(root_ref_id)
        ):
            raise PackageProductGcExecutionError(
                "Package GC success lacks durable root fences",
                code="plugin_package_gc_fence_missing",
            )


@dataclass(frozen=True, slots=True)
class PackageProductRootGcApplication:
    """Product command over the exact candidate/reservation/Store owners."""

    gate: PluginPackageGcReservationJournal
    lifecycle: PluginPackageLifecycleLedger
    executor: PackageProductRootGcExecutor

    def __post_init__(self) -> None:
        if (
            not isinstance(self.gate, PluginPackageGcReservationJournal)
            or not isinstance(self.lifecycle, PluginPackageLifecycleLedger)
            or not isinstance(self.executor, PackageProductRootGcExecutor)
            or self.executor.gate is not self.gate
            or self.executor.lifecycle is not self.lifecycle
            or not self.lifecycle.gc_reservation_graph_bound_to(self.gate)
        ):
            raise ValueError("Package GC Product command requires one bound owner graph")

    def execute(
        self, command: PackageProductRootGcCommandV1
    ) -> PluginPackageGcAttemptV1:
        if not isinstance(command, PackageProductRootGcCommandV1):
            raise TypeError("Exact Package GC Product command is required")
        with self.gate.guard():
            if not self.lifecycle.gc_writer_epoch_sealed():
                raise PackageProductGcExecutionError(
                    "Package GC writer epoch is not sealed",
                    code="plugin_package_gc_writer_epoch_unsealed",
                )
            reservation = self.gate.reserve(
                command.candidate,
                lifecycle=self.lifecycle,
                operation_id=command.reservation_operation_id,
                idempotency_key=command.reservation_idempotency_key,
            )
            return self.executor.execute(
                reservation.reservation_id,
                operation_id=command.attempt_operation_id,
                idempotency_key=command.attempt_idempotency_key,
            )


PackageProductRootGcState = Literal[
    "reserved",
    "deletion_started",
    "retryable_failure",
    "terminal_failure",
    "succeeded",
    "evidence_conflict",
]


@dataclass(frozen=True, slots=True)
class PackageProductRootGcStatusV1:
    """Read-only status; success requires its durable Product and Store fences."""

    reservation: PluginPackageGcReservationEventV1
    deletion_start: PluginPackageGcDeletionStartV2 | None
    latest_attempt: PluginPackageGcAttemptV1 | None
    settlement_id: str | None
    state: PackageProductRootGcState
    reason_code: str | None = None
    status_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.status_version != 1
            or self.state not in {
                "reserved",
                "deletion_started",
                "retryable_failure",
                "terminal_failure",
                "succeeded",
                "evidence_conflict",
            }
            or self.reservation.kind != "reserved"
            or self.reservation.candidate is None
        ):
            raise ValueError("Package GC operator status is invalid")

    def to_dict(self) -> dict[str, object]:
        candidate = self.reservation.candidate
        return {
            "candidateId": None if candidate is None else candidate.candidate_id,
            "deletionStartOperationId": (
                None if self.deletion_start is None else self.deletion_start.operation_id
            ),
            "latestAttemptId": (
                None if self.latest_attempt is None else self.latest_attempt.attempt_id
            ),
            "reasonCode": self.reason_code,
            "reservationId": self.reservation.reservation_id,
            "settlementId": self.settlement_id,
            "state": self.state,
            "statusVersion": self.status_version,
        }


@dataclass(frozen=True, slots=True)
class PackageProductRootGcReadModel:
    """Join exact owner evidence without granting a deletion capability."""

    executor: PackageProductRootGcExecutor

    def __post_init__(self) -> None:
        if not isinstance(self.executor, PackageProductRootGcExecutor):
            raise TypeError("Package GC Product executor is required")

    def snapshot(self) -> tuple[PackageProductRootGcStatusV1, ...]:
        owner = self.executor
        with owner.gate.guard():
            reservations = owner.gate.snapshot().active
            attempts = owner.results.records()
            bindings = owner.bindings.records()
            claims = owner.bindings.claims()
            committed_sets = owner.committed_sets.records()
            settlements = owner.root_settlements.records()
            return tuple(
                _project_root_gc_status(
                    owner,
                    reservation,
                    start=owner.gate.deletion_start(reservation.reservation_id),
                    attempts=attempts,
                    bindings=bindings,
                    claims=claims,
                    committed_sets=committed_sets,
                    settlements=settlements,
                )
                for reservation in reservations
            )


def _project_root_gc_status(
    owner: PackageProductRootGcExecutor,
    reservation: PluginPackageGcReservationEventV1,
    *,
    start: PluginPackageGcDeletionStartV2 | None,
    attempts: tuple[PluginPackageGcAttemptV1, ...],
    bindings: tuple[PluginPackageGcBindingV1, ...],
    claims: tuple[PluginPackageGcClaimV1, ...],
    committed_sets: tuple[PackageCommittedSetRecordV1, ...],
    settlements: tuple[PackageStoreSettlementRecordV1, ...],
) -> PackageProductRootGcStatusV1:
    candidate = reservation.candidate
    if candidate is None:
        raise PackageProductGcExecutionError(
            "Active GC reservation has no candidate",
            code="plugin_package_gc_journal_corrupt",
        )
    owned_attempts = tuple(
        item for item in attempts if item.reservation_id == reservation.reservation_id
    )
    latest = owned_attempts[-1] if owned_attempts else None

    def row(
        state: PackageProductRootGcState,
        settlement_id: str | None,
        reason_code: str | None = None,
    ) -> PackageProductRootGcStatusV1:
        return PackageProductRootGcStatusV1(
            reservation=reservation,
            deletion_start=start,
            latest_attempt=latest,
            settlement_id=settlement_id,
            state=state,
            reason_code=reason_code,
        )

    try:
        target = resolve_plugin_package_gc_root_target(
            candidate.package_revision,
            bindings=bindings,
            claims=claims,
            committed_sets=committed_sets,
            settlements=settlements,
        )
    except PluginPackageGcTargetError as exc:
        return row("evidence_conflict", None, exc.code)
    settlement_id = target.settlement_id
    if start is None:
        if owned_attempts or any(
            item.settlement_id == settlement_id for item in attempts
        ):
            return row(
                "evidence_conflict",
                settlement_id,
                "plugin_package_gc_result_conflict",
            )
        return row("reserved", settlement_id)
    if (
        start.target_settlement_ids != (settlement_id,)
        or any(
            item.settlement_id == settlement_id
            and item.reservation_id != reservation.reservation_id
            for item in attempts
        )
        or any(
            item.settlement_id != settlement_id
            or item.deletion_start_operation_id != start.operation_id
            for item in owned_attempts
        )
    ):
        return row(
            "evidence_conflict",
            settlement_id,
            "plugin_package_gc_result_conflict",
        )
    if latest is None:
        return row("deletion_started", settlement_id)
    if latest.disposition != "succeeded":
        return row(latest.disposition, settlement_id, latest.error_code)
    result = latest.store_result
    if (
        result is None
        or result
        != PackageStoreGcResultV1.create(
            target.settlement, disposition=result.disposition
        )
    ):
        return row(
            "evidence_conflict",
            settlement_id,
            "plugin_package_gc_result_mismatch",
        )
    root_ref_id = target.settlement.receipt.stable_ref.ref_id
    if not (
        owner.committed_sets.is_tombstoned(root_ref_id)
        and owner.root_settlements.is_tombstoned(root_ref_id)
    ):
        return row(
            "evidence_conflict",
            settlement_id,
            "plugin_package_gc_fence_missing",
        )
    return row("succeeded", settlement_id)


__all__ = [
    "PackageProductGcExecutionError",
    "PackageProductGcRootStorePort",
    "PackageProductRootGcApplication",
    "PackageProductRootGcCommandV1",
    "PackageProductRootGcExecutor",
    "PackageProductRootGcReadModel",
    "PackageProductRootGcState",
    "PackageProductRootGcStatusV1",
]
