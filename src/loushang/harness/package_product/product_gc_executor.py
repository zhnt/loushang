"""Internal Product coordinator for one exact PLC9D Package root deletion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_gc_results import (
    PluginPackageGcAttemptV1,
    PluginPackageGcResultJournal,
)
from loushang.harness.plugin_management.package_gc_target import (
    PluginPackageGcRootTargetV1,
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageLifecycleLedger,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
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


__all__ = [
    "PackageProductGcExecutionError",
    "PackageProductGcRootStorePort",
    "PackageProductRootGcExecutor",
]
