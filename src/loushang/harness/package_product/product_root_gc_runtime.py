"""Offline root GC composed from one fenced local-Wheel Product owner."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from loushang.harness.package_product.product_gc_executor import (
    PackageProductGcExecutionError,
    PackageProductRootGcApplication,
    PackageProductRootGcCommandV1,
    PackageProductRootGcExecutor,
    PackageProductRootGcReadModel,
    PackageProductRootGcStatusV1,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
)
from loushang.harness.plugin_management.package_gc_dependencies import (
    PackageDependencyGcInspectionV1,
    PackageDependencyGcTargetError,
    PackageDependencyGcTargetV1,
    PackageDependencyRetentionV1,
    project_package_dependency_retention,
    resolve_package_dependency_gc_target,
)
from loushang.harness.plugin_management.package_gc_dependency_journal import (
    PackageDependencyGcAttemptV1,
    PackageDependencyGcJournal,
    PackageDependencyGcStartV1,
)
from loushang.harness.plugin_management.package_gc_dependency_repair import (
    PackageDependencyGcRepairJournal,
    PackageDependencyGcRepairResultV1,
    PackageDependencyGcRepairStartV1,
)
from loushang.harness.plugin_management.package_gc_dependency_review import (
    PackageDependencyGcRepairReviewJournal,
    PackageDependencyGcRepairReviewV1,
)
from loushang.harness.plugin_management.package_gc_results import (
    PluginPackageGcAttemptV1,
    PluginPackageGcResultJournal,
)
from loushang.harness.plugin_management.package_gc_target import (
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.package_lifecycle import (
    PluginPackageGcCandidateV1,
    PluginPackageLifecycleLedger,
)
from loushang.harness.plugin_management.retirement import PluginRetirementIntentLedger
from loushang.harness.plugin_management.retirement_sets import PluginRetirementSetLedger
from loushang.harness.plugin_management.security_acceptance import (
    PluginInstanceSecurityRetirementJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PosixPackageDependencyMaterializationStore,
    PosixPackagePluginRootMaterializationStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_gc import (
    PackageStoreGcResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
    PackageStoreSettlementRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_materialization import (
    WindowsPackageDependencyMaterializationStore,
    WindowsPackagePluginRootMaterializationStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)


@dataclass(frozen=True, slots=True)
class PackageProductRootGcOperatorSnapshotV1:
    candidates: tuple[PluginPackageGcCandidateV1, ...]
    statuses: tuple[PackageProductRootGcStatusV1, ...]
    dependency_inspections: tuple[PackageDependencyGcInspectionV1, ...]
    dependency_repairs: tuple[PackageProductGcDependencyRepairStatusV1, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageProductGcDependencyRepairStatusV1:
    review_id: str
    terminal_attempt_id: str
    repair_start_id: str | None
    repair_result_id: str | None
    state: Literal["reviewed", "started", "terminal_failure", "succeeded"]
    error_code: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.review_id, str)
            or not self.review_id
            or not isinstance(self.terminal_attempt_id, str)
            or not self.terminal_attempt_id
            or self.state
            not in {"reviewed", "started", "terminal_failure", "succeeded"}
            or (
                self.state == "reviewed"
                and (
                    self.repair_start_id is not None
                    or self.repair_result_id is not None
                    or self.error_code is not None
                )
            )
            or (
                self.state == "started"
                and (
                    not self.repair_start_id
                    or self.repair_result_id is not None
                    or self.error_code is not None
                )
            )
            or (
                self.state in {"succeeded", "terminal_failure"}
                and (not self.repair_start_id or not self.repair_result_id)
            )
            or (self.state == "succeeded" and self.error_code is not None)
            or (self.state == "terminal_failure" and not self.error_code)
        ):
            raise ValueError("Dependency GC repair status is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "reviewId": self.review_id,
            "terminalAttemptId": self.terminal_attempt_id,
            "repairStartId": self.repair_start_id,
            "repairResultId": self.repair_result_id,
            "state": self.state,
            "errorCode": self.error_code,
        }


class PackageProductGcDependencyStorePort(Protocol):
    """Role-specific physical deletion after Product reference admission."""

    def delete_settlement(
        self, settlement: PackageStoreSettlementRecordV1
    ) -> PackageStoreGcResultV1: ...


class PackageProductGcDependencyRepairAuthorityPort(Protocol):
    """Product-injected authorization for one reviewed terminal debt."""

    def authorizes(
        self,
        review: PackageDependencyGcRepairReviewV1,
        target: PackageDependencyGcTargetV1,
    ) -> bool: ...


class PackageProductGcWorkerHistoryAuthorityPort(Protocol):
    """Product-specific proof that retained Worker history has no GC debt."""

    @property
    def product_owner(
        self,
    ) -> PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner: ...

    def require_settled(self, *, observed_names: tuple[str, ...]) -> None: ...


@dataclass(frozen=True, slots=True)
class LocalWheelProductRootGcOwner:
    """Keep Product references and runtime quiescence through exact deletion."""

    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner
    instances: PluginInstanceRuntimeLedger
    packages: PluginPackageLifecycleLedger
    transaction_pins: PackageTransactionPinJournal
    dependency_settlements: PackageStoreSettlementJournal
    dependency_store_factory: Callable[[], PackageProductGcDependencyStorePort]
    application: PackageProductRootGcApplication
    read_model: PackageProductRootGcReadModel
    repair_authority: PackageProductGcDependencyRepairAuthorityPort | None = None
    worker_history_authority: PackageProductGcWorkerHistoryAuthorityPort | None = None

    def __post_init__(self) -> None:
        executor = self.application.executor
        if (
            self.application.gate is not self.product.gc_gate
            or self.application.lifecycle is not self.packages
            or executor.bindings is not self.product.gc_bindings
            or self.read_model.executor is not executor
            or self.instances.gc_gate is not self.product.gc_gate
            or self.packages.instance_runtime_journal_path != self.instances.path
            or self.transaction_pins.path
            != self.product.state_root / "transaction-pins.jsonl"
            or self.dependency_settlements.path
            != self.product.state_root / "dependency-settlements.jsonl"
            or not callable(self.dependency_store_factory)
            or (
                self.repair_authority is not None
                and not callable(getattr(self.repair_authority, "authorizes", None))
            )
            or (
                self.worker_history_authority is not None
                and (
                    self.worker_history_authority.product_owner is not self.product
                    or not callable(
                        getattr(self.worker_history_authority, "require_settled", None)
                    )
                )
            )
        ):
            raise ValueError("Package Product root GC owners are not bound")

    @contextmanager
    def _offline(
        self, *, require_no_worker_payload_debt: bool = False
    ) -> Iterator[None]:
        registry = self.product.epoch_runtime.registry
        with registry.exclusive_runtime_quiescence(
            store_id=registry.store_id
        ) as quiescence:
            if quiescence.active_runtime_lease_ids:
                raise PackageProductGcExecutionError(
                    "Package Product runtime leases remain active",
                    code="plugin_package_gc_runtime_active",
                )
            self.product.assert_root_gc_authority_current()
            with self.product.gc_gate.guard(require_write=True):
                if require_no_worker_payload_debt:
                    self._require_no_worker_payload_debt()
                yield
            self.product.assert_root_gc_authority_current()

    def _require_no_worker_payload_debt(self) -> None:
        """Retain every Package root while an attempt-scoped payload is unsettled."""

        try:
            if isinstance(self.product, PosixLocalWheelProductSessionOwner):
                with self.product.pinned_state_root_gc_read() as descriptor:
                    names = tuple(os.listdir(descriptor))
            else:
                with (
                    self.product.epoch_runtime.borrow_product_state_root_descriptor() as descriptor
                ):
                    names = windows_listdir_at(descriptor)
        except (OSError, ValueError) as exc:
            raise PackageProductGcExecutionError(
                "Worker payload state cannot be inspected before Package GC",
                code="plugin_package_gc_worker_payload_unavailable",
            ) from exc
        if any(name.casefold().startswith("worker-payload-") for name in names):
            raise PackageProductGcExecutionError(
                "Worker payload attempt must settle before Package GC",
                code="plugin_package_gc_worker_payload_unsettled",
            )
        has_worker_state = any(
            name.casefold().startswith(("worker-", ".worker-")) for name in names
        )
        if has_worker_state:
            try:
                if self.worker_history_authority is None:
                    raise ValueError("Worker history authority is absent")
                self.worker_history_authority.require_settled(observed_names=names)
            except (OSError, RuntimeError, ValueError) as exc:
                raise PackageProductGcExecutionError(
                    "Worker attempt history requires recovery before Package GC",
                    code="plugin_package_gc_worker_history_unsettled",
                ) from exc

    def prepare(self) -> None:
        """Explicitly recover and seal the complete B Product reference graph."""

        with self._offline(require_no_worker_payload_debt=True):
            pass
        self._recover_product_transactions()
        store_id = self.product.epoch_runtime.registry.store_id
        with self._offline(require_no_worker_payload_debt=True):
            self._require_no_open_transaction_pins()
            self.product.management.recover()
            self.packages.complete_startup_recovery(
                operation_id=f"product-gc-recovery:{store_id}",
                idempotency_key=f"product-gc-recovery:{store_id}",
                recovery_reference=f"product-gc:{store_id}",
            )
            self.product.desired_state.seal_gc_writer_epoch()
            self.instances.seal_gc_writer_epoch()
            self.packages.seal_gc_writer_epoch()

    def candidates(self) -> tuple[PluginPackageGcCandidateV1, ...]:
        with self._offline():
            self._require_no_open_transaction_pins()
            if not self.packages.gc_writer_epoch_sealed():
                raise PackageProductGcExecutionError(
                    "Package GC writer epoch is not sealed",
                    code="plugin_package_gc_writer_epoch_unsealed",
                )
            return self.packages.gc_candidates()

    def execute(
        self, command: PackageProductRootGcCommandV1
    ) -> PluginPackageGcAttemptV1:
        with self._offline(require_no_worker_payload_debt=True):
            self._require_no_open_transaction_pins()
            return self.application.execute(command)

    def retry_started(
        self,
        reservation_id: str,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> PluginPackageGcAttemptV1:
        """Retry one durable deletion start without recapturing a candidate."""

        with self._offline(require_no_worker_payload_debt=True):
            self._require_no_open_transaction_pins()
            if self.product.gc_gate.deletion_start(reservation_id) is None:
                raise PackageProductGcExecutionError(
                    "Package GC deletion has not started",
                    code="plugin_package_gc_deletion_not_started",
                )
            return self.application.executor.execute(
                reservation_id,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
            )

    def statuses(self) -> tuple[PackageProductRootGcStatusV1, ...]:
        with self._offline():
            return self.read_model.snapshot()

    def dependency_retention(self) -> tuple[PackageDependencyRetentionV1, ...]:
        """Project shared holders after the same offline Product GC fence."""

        with self._offline():
            return self._dependency_retention_under_offline()

    def dependency_inspections(self) -> tuple[PackageDependencyGcInspectionV1, ...]:
        """Join released references to exact dependency Store evidence."""

        with self._offline():
            return self._dependency_inspections_under_offline()

    def inspect_terminal_dependency_debt(
        self, start_id: str
    ) -> tuple[PackageDependencyGcInspectionV1, PackageDependencyGcAttemptV1]:
        """Read one terminal debt and its current exact Product target."""

        with self._offline():
            return self._terminal_dependency_debt_under_offline(start_id)

    def record_terminal_dependency_review(
        self,
        start_id: str,
        *,
        expected_terminal_attempt_id: str,
        expected_settlement_id: str,
        expected_error_code: str,
        actor_id: str,
        policy_revision: str,
        remediation_reference: str,
        prior_repair_result_id: str | None = None,
    ) -> PackageDependencyGcRepairReviewV1:
        """Bind an explicit operator review to current Product debt evidence."""

        with self._offline(require_no_worker_payload_debt=True):
            inspection, terminal = self._terminal_dependency_debt_under_offline(
                start_id
            )
            target = inspection.target
            if (
                target is None
                or terminal.attempt_id != expected_terminal_attempt_id
                or target.settlement_id != expected_settlement_id
                or terminal.error_code != expected_error_code
            ):
                raise PackageProductGcExecutionError(
                    "Dependency GC repair review changed its Product evidence",
                    code="plugin_package_gc_dependency_repair_review_refused",
                )
            starts = tuple(
                item
                for item in self._dependency_gc_journal().events()
                if isinstance(item, PackageDependencyGcStartV1)
                and item.start_id == start_id
            )
            if len(starts) != 1:
                raise PackageProductGcExecutionError(
                    "Dependency GC repair start is unavailable",
                    code="plugin_package_gc_dependency_start_unavailable",
                )
            existing = tuple(
                item
                for item in self._dependency_repair_reviews().records()
                if item.start_id == start_id
            )
            if prior_repair_result_id is not None:
                replay = next(
                    (
                        item
                        for item in existing
                        if item.prior_repair_result_id == prior_repair_result_id
                        and item.terminal_attempt_id == terminal.attempt_id
                        and item.settlement_id == target.settlement_id
                        and item.actor_id == actor_id
                        and item.policy_revision == policy_revision
                        and item.remediation_reference == remediation_reference
                    ),
                    None,
                )
                if replay is not None:
                    return replay
                if not existing:
                    raise PackageProductGcExecutionError(
                        "Dependency GC repair has no prior review",
                        code="plugin_package_gc_dependency_repair_review_refused",
                    )
                prior_status = self._inspect_dependency_repair_under_offline(
                    existing[-1].review_id
                )
                if (
                    prior_status.state != "terminal_failure"
                    or prior_status.repair_result_id != prior_repair_result_id
                ):
                    raise PackageProductGcExecutionError(
                        "Dependency GC repair has no matching terminal result",
                        code="plugin_package_gc_dependency_repair_review_refused",
                    )
            return self._dependency_repair_reviews().record(
                starts[0],
                terminal,
                actor_id=actor_id,
                policy_revision=policy_revision,
                remediation_reference=remediation_reference,
                prior_repair_result_id=prior_repair_result_id,
            )

    def repair_terminal_dependency_debt(
        self,
        review_id: str,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> PackageDependencyGcRepairResultV1:
        """Run one separately authorized repair without changing original debt."""

        with self._offline(require_no_worker_payload_debt=True):
            authority = self.repair_authority
            if authority is None:
                raise PackageProductGcExecutionError(
                    "Dependency GC repair has no Product authorization",
                    code="plugin_package_gc_dependency_repair_unavailable",
                )
            review, target = self._selected_dependency_repair_review_under_offline(
                review_id
            )
            if authority.authorizes(review, target) is not True:
                raise PackageProductGcExecutionError(
                    "Dependency GC repair review has no current Product authority",
                    code="plugin_package_gc_dependency_repair_review_refused",
                )
            repairs = self._dependency_repair_journal()
            start = repairs.begin(
                review,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
            )
            prior = repairs.result_for(start)
            if prior is not None:
                if prior.disposition == "succeeded" and (
                    not self.dependency_settlements.is_tombstoned(
                        target.retention.dependency_ref.ref_id
                    )
                    or prior.store_result is None
                    or prior.store_result
                    != PackageStoreGcResultV1.create(
                        target.settlement,
                        disposition=prior.store_result.disposition,
                    )
                ):
                    raise PackageProductGcExecutionError(
                        "Dependency GC repair success lost its Store proof",
                        code="plugin_package_gc_dependency_repair_fence_missing",
                    )
                return prior
            try:
                store = self.dependency_store_factory()
                if not callable(getattr(store, "delete_settlement", None)):
                    raise TypeError(
                        "Package Product dependency Store owner is required"
                    )
                result = store.delete_settlement(target.settlement)
            except PackagePhysicalStagingError as exc:
                return repairs.record(
                    start, settlement=target.settlement, error_code=exc.code
                )
            if not self.dependency_settlements.is_tombstoned(
                target.retention.dependency_ref.ref_id
            ):
                raise PackageProductGcExecutionError(
                    "Dependency GC repair Store result lacks its tombstone",
                    code="plugin_package_gc_dependency_repair_fence_missing",
                )
            return repairs.record(
                start, settlement=target.settlement, store_result=result
            )

    def inspect_dependency_repair(
        self, review_id: str
    ) -> PackageProductGcDependencyRepairStatusV1:
        """Reopen one repair lineage without granting Store authority."""

        with self._offline():
            return self._inspect_dependency_repair_under_offline(review_id)

    def _inspect_dependency_repair_under_offline(
        self, review_id: str
    ) -> PackageProductGcDependencyRepairStatusV1:
        review, target = self._selected_dependency_repair_review_under_offline(
            review_id
        )
        repairs = self._dependency_repair_journal()
        starts = tuple(
            item
            for item in repairs.events()
            if isinstance(item, PackageDependencyGcRepairStartV1)
            and item.review_id == review_id
        )
        if not starts:
            return PackageProductGcDependencyRepairStatusV1(
                review_id, review.terminal_attempt_id, None, None, "reviewed", None
            )
        if len(starts) != 1:
            raise PackageProductGcExecutionError(
                "Dependency GC repair start is ambiguous",
                code="plugin_package_gc_dependency_repair_start_conflict",
            )
        start = starts[0]
        if start != PackageDependencyGcRepairStartV1.create(
            review,
            journal_revision=start.journal_revision,
            operation_id=start.operation_id,
            idempotency_key=start.idempotency_key,
        ):
            raise PackageProductGcExecutionError(
                "Dependency GC repair start changed its review",
                code="plugin_package_gc_dependency_repair_start_conflict",
            )
        result = repairs.result_for(start)
        if result is None:
            return PackageProductGcDependencyRepairStatusV1(
                review_id,
                review.terminal_attempt_id,
                start.repair_start_id,
                None,
                "started",
                None,
            )
        if result.disposition == "succeeded" and (
            not self.dependency_settlements.is_tombstoned(
                target.retention.dependency_ref.ref_id
            )
            or result.store_result is None
            or result.store_result
            != PackageStoreGcResultV1.create(
                target.settlement,
                disposition=result.store_result.disposition,
            )
        ):
            raise PackageProductGcExecutionError(
                "Dependency GC repair success lost its Store proof",
                code="plugin_package_gc_dependency_repair_fence_missing",
            )
        return PackageProductGcDependencyRepairStatusV1(
            review_id,
            review.terminal_attempt_id,
            start.repair_start_id,
            result.repair_result_id,
            result.disposition,
            result.error_code,
        )

    def _selected_dependency_repair_review_under_offline(
        self, review_id: str
    ) -> tuple[PackageDependencyGcRepairReviewV1, PackageDependencyGcTargetV1]:
        all_reviews = self._dependency_repair_reviews().records()
        reviews = tuple(item for item in all_reviews if item.review_id == review_id)
        if len(reviews) != 1:
            raise PackageProductGcExecutionError(
                "Exact dependency GC repair review is unavailable",
                code="plugin_package_gc_dependency_repair_review_unavailable",
            )
        review = reviews[0]
        if review.prior_repair_result_id is not None:
            previous = tuple(
                item
                for item in all_reviews
                if item.start_id == review.start_id
                and item.record_revision < review.record_revision
            )
            repair_events = self._dependency_repair_journal().events()
            previous_starts = tuple(
                item
                for item in repair_events
                if isinstance(item, PackageDependencyGcRepairStartV1)
                and previous
                and item.review_id == previous[-1].review_id
            )
            previous_results = tuple(
                item
                for item in repair_events
                if isinstance(item, PackageDependencyGcRepairResultV1)
                and previous_starts
                and item.repair_start_id == previous_starts[0].repair_start_id
            )
            if (
                len(previous_starts) != 1
                or len(previous_results) != 1
                or previous_results[0].disposition != "terminal_failure"
                or previous_results[0].repair_result_id != review.prior_repair_result_id
            ):
                raise PackageProductGcExecutionError(
                    "Dependency GC repair review lacks its terminal predecessor",
                    code="plugin_package_gc_dependency_repair_review_refused",
                )
        inspection, terminal = self._terminal_dependency_debt_under_offline(
            review.start_id
        )
        target = inspection.target
        if (
            target is None
            or review.terminal_attempt_id != terminal.attempt_id
            or review.reviewed_error_code != terminal.error_code
            or review.store_id != self.product.epoch_runtime.registry.store_id
            or review.settlement_id != target.settlement_id
        ):
            raise PackageProductGcExecutionError(
                "Dependency GC repair review changed its Product target",
                code="plugin_package_gc_dependency_repair_review_refused",
            )
        return review, target

    def _terminal_dependency_debt_under_offline(
        self, start_id: str
    ) -> tuple[PackageDependencyGcInspectionV1, PackageDependencyGcAttemptV1]:
        events = self._dependency_gc_journal().events()
        starts = tuple(
            item
            for item in events
            if isinstance(item, PackageDependencyGcStartV1)
            and item.start_id == start_id
        )
        attempts = tuple(
            item
            for item in events
            if isinstance(item, PackageDependencyGcAttemptV1)
            and item.start_id == start_id
            and item.disposition == "terminal_failure"
        )
        inspections = tuple(
            item
            for item in self._dependency_inspections_under_offline()
            if item.deletion_start_id == start_id
            and item.deletion_state == "terminal_failure"
        )
        if (
            len(starts) != 1
            or len(attempts) != 1
            or len(inspections) != 1
            or inspections[0].latest_attempt_id != attempts[0].attempt_id
            or inspections[0].target is None
            or inspections[0].target.settlement_id != starts[0].settlement_id
        ):
            raise PackageProductGcExecutionError(
                "Exact terminal dependency GC debt is unavailable",
                code="plugin_package_gc_dependency_terminal_debt_unavailable",
            )
        return inspections[0], attempts[0]

    def operator_snapshot(self) -> PackageProductRootGcOperatorSnapshotV1:
        """Capture root and dependency status under one offline Product hold."""

        with self._offline():
            self._require_no_open_transaction_pins()
            if not self.packages.gc_writer_epoch_sealed():
                raise PackageProductGcExecutionError(
                    "Package GC writer epoch is not sealed",
                    code="plugin_package_gc_writer_epoch_unsealed",
                )
            statuses = self.read_model.snapshot()
            return PackageProductRootGcOperatorSnapshotV1(
                candidates=self.packages.gc_candidates(),
                statuses=statuses,
                dependency_inspections=self._dependency_inspections_under_offline(
                    statuses=statuses
                ),
                dependency_repairs=tuple(
                    self._inspect_dependency_repair_under_offline(item.review_id)
                    for item in self._dependency_repair_reviews().records()
                ),
            )

    def delete_dependency(
        self,
        dependency_ref_id: str,
        *,
        expected_settlement_id: str,
        operation_id: str,
        idempotency_key: str,
    ) -> PackageDependencyGcAttemptV1:
        """Delete one orphan dependency after exact Product/Store rechecks."""

        with self._offline(require_no_worker_payload_debt=True):
            target = self._selected_dependency_target_under_offline(
                dependency_ref_id, expected_settlement_id=expected_settlement_id
            )
            return self._execute_dependency_under_offline(
                target,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
            )

    def retry_dependency(
        self,
        start_id: str,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> PackageDependencyGcAttemptV1:
        """Replay only an existing durable dependency deletion start."""

        with self._offline(require_no_worker_payload_debt=True):
            journal = self._dependency_gc_journal()
            starts = tuple(
                item
                for item in journal.events()
                if isinstance(item, PackageDependencyGcStartV1)
                and item.start_id == start_id
            )
            if len(starts) != 1:
                raise PackageProductGcExecutionError(
                    "Dependency GC start is unavailable",
                    code="plugin_package_gc_dependency_start_unavailable",
                )
            start = starts[0]
            target = self._selected_dependency_target_under_offline(
                start.dependency_ref_id,
                expected_settlement_id=start.settlement_id,
            )
            if (
                PackageDependencyGcStartV1.create(
                    target,
                    store_id=self.product.epoch_runtime.registry.store_id,
                    journal_revision=start.journal_revision,
                )
                != start
            ):
                raise PackageProductGcExecutionError(
                    "Dependency GC start changed its Product target",
                    code="plugin_package_gc_dependency_start_conflict",
                )
            return self._execute_dependency_under_offline(
                target,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
            )

    def _selected_dependency_target_under_offline(
        self, dependency_ref_id: str, *, expected_settlement_id: str
    ) -> PackageDependencyGcTargetV1:
        matches = tuple(
            item
            for item in self._dependency_inspections_under_offline()
            if item.retention.dependency_ref.ref_id == dependency_ref_id
        )
        if (
            len(matches) != 1
            or matches[0].target is None
            or matches[0].target.settlement_id != expected_settlement_id
        ):
            raise PackageProductGcExecutionError(
                "Dependency GC exact Product target is unavailable",
                code="plugin_package_gc_dependency_target_unavailable",
            )
        return matches[0].target

    def _execute_dependency_under_offline(
        self,
        target: PackageDependencyGcTargetV1,
        *,
        operation_id: str,
        idempotency_key: str,
    ) -> PackageDependencyGcAttemptV1:
        if (
            not isinstance(operation_id, str)
            or not operation_id
            or not isinstance(idempotency_key, str)
            or not idempotency_key
        ):
            raise ValueError("Dependency GC attempt identity is required")
        journal = self._dependency_gc_journal()
        start = journal.begin(
            target, store_id=self.product.epoch_runtime.registry.store_id
        )
        prior = journal.preflight(
            start, operation_id=operation_id, idempotency_key=idempotency_key
        )
        if prior is not None:
            if prior.disposition == "succeeded" and (
                not self.dependency_settlements.is_tombstoned(
                    target.retention.dependency_ref.ref_id
                )
                or prior.store_result is None
                or prior.store_result
                != PackageStoreGcResultV1.create(
                    target.settlement,
                    disposition=prior.store_result.disposition,
                )
            ):
                raise PackageProductGcExecutionError(
                    "Dependency GC success lost its exact Store proof",
                    code="plugin_package_gc_dependency_fence_missing",
                )
            return prior
        try:
            store = self.dependency_store_factory()
            if not callable(getattr(store, "delete_settlement", None)):
                raise TypeError("Package Product dependency Store owner is required")
            result = store.delete_settlement(target.settlement)
        except PackagePhysicalStagingError as exc:
            return journal.record(
                start,
                settlement=target.settlement,
                operation_id=operation_id,
                idempotency_key=idempotency_key,
                error_code=exc.code,
                terminal=True,
            )
        if not self.dependency_settlements.is_tombstoned(
            target.retention.dependency_ref.ref_id
        ):
            raise PackageProductGcExecutionError(
                "Dependency GC Store result lacks its tombstone",
                code="plugin_package_gc_dependency_fence_missing",
            )
        return journal.record(
            start,
            settlement=target.settlement,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            store_result=result,
        )

    def _dependency_gc_journal(self) -> PackageDependencyGcJournal:
        return PackageDependencyGcJournal(
            self.product.state_root / "dependency-gc.jsonl"
        )

    def _dependency_repair_reviews(self) -> PackageDependencyGcRepairReviewJournal:
        return PackageDependencyGcRepairReviewJournal(
            self.product.state_root / "dependency-gc-reviews.jsonl"
        )

    def _dependency_repair_journal(self) -> PackageDependencyGcRepairJournal:
        return PackageDependencyGcRepairJournal(
            self.product.state_root / "dependency-gc-repairs.jsonl"
        )

    def _dependency_inspections_under_offline(
        self, *, statuses: tuple[PackageProductRootGcStatusV1, ...] | None = None
    ) -> tuple[PackageDependencyGcInspectionV1, ...]:
        retention = self._dependency_retention_under_offline(statuses=statuses)
        committed_sets = self.application.executor.committed_sets.records()
        settlement_records = self.dependency_settlements.records()
        events = self._dependency_gc_journal().events()
        starts = {
            event.dependency_ref_id: event
            for event in events
            if isinstance(event, PackageDependencyGcStartV1)
        }
        attempts_by_start: dict[str, PackageDependencyGcAttemptV1] = {}
        for event in events:
            if isinstance(event, PackageDependencyGcAttemptV1):
                attempts_by_start[event.start_id] = event
        rows: list[PackageDependencyGcInspectionV1] = []
        for item in retention:
            if item.disposition == "retained":
                rows.append(PackageDependencyGcInspectionV1(item))
                continue
            if (
                item.dependency_ref.store_identity
                != self.product.dependency_store_identity
            ):
                rows.append(
                    PackageDependencyGcInspectionV1(
                        item, reason_code="plugin_package_gc_dependency_store_changed"
                    )
                )
                continue
            try:
                target = resolve_package_dependency_gc_target(
                    item, committed_sets=committed_sets, settlements=settlement_records
                )
            except PackageDependencyGcTargetError as exc:
                rows.append(PackageDependencyGcInspectionV1(item, reason_code=exc.code))
            else:
                start = starts.get(item.dependency_ref.ref_id)
                if start is not None and start != PackageDependencyGcStartV1.create(
                    target,
                    store_id=self.product.epoch_runtime.registry.store_id,
                    journal_revision=start.journal_revision,
                ):
                    rows.append(
                        PackageDependencyGcInspectionV1(
                            item,
                            reason_code="plugin_package_gc_dependency_start_conflict",
                        )
                    )
                    continue
                tombstoned = self.dependency_settlements.is_tombstoned(
                    item.dependency_ref.ref_id
                )
                if start is None and tombstoned:
                    rows.append(
                        PackageDependencyGcInspectionV1(
                            item,
                            reason_code="plugin_package_gc_dependency_fence_unattributed",
                        )
                    )
                    continue
                latest = (
                    None if start is None else attempts_by_start.get(start.start_id)
                )
                deletion_state: Literal[
                    "not_started",
                    "started",
                    "retryable_failure",
                    "terminal_failure",
                    "succeeded",
                ]
                if latest is not None and latest.disposition == "succeeded":
                    if (
                        not tombstoned
                        or latest.store_result is None
                        or latest.store_result
                        != PackageStoreGcResultV1.create(
                            target.settlement,
                            disposition=latest.store_result.disposition,
                        )
                    ):
                        rows.append(
                            PackageDependencyGcInspectionV1(
                                item,
                                reason_code="plugin_package_gc_dependency_fence_missing",
                            )
                        )
                        continue
                    deletion_state = "succeeded"
                elif latest is not None:
                    deletion_state = latest.disposition
                elif start is not None:
                    deletion_state = "started"
                else:
                    deletion_state = "not_started"
                rows.append(
                    PackageDependencyGcInspectionV1(
                        item,
                        target=target,
                        deletion_state=deletion_state,
                        deletion_start_id=None if start is None else start.start_id,
                        latest_attempt_id=None if latest is None else latest.attempt_id,
                    )
                )
        return tuple(rows)

    def _dependency_retention_under_offline(
        self,
        *,
        statuses: tuple[PackageProductRootGcStatusV1, ...] | None = None,
    ) -> tuple[PackageDependencyRetentionV1, ...]:
        self._require_no_open_transaction_pins()
        if not self.packages.gc_writer_epoch_sealed():
            raise PackageProductGcExecutionError(
                "Package GC writer epoch is not sealed",
                code="plugin_package_gc_writer_epoch_unsealed",
            )
        executor = self.application.executor
        committed_sets = executor.committed_sets.records()
        bindings = executor.bindings.records()
        claims = executor.bindings.claims()
        settlements = executor.root_settlements.records()
        deleted_root_ids: set[str] = set()
        for status in statuses if statuses is not None else self.read_model.snapshot():
            if status.state != "succeeded":
                continue
            candidate = status.reservation.candidate
            assert candidate is not None
            target = resolve_plugin_package_gc_root_target(
                candidate.package_revision,
                bindings=bindings,
                claims=claims,
                committed_sets=committed_sets,
                settlements=settlements,
            )
            if status.settlement_id != target.settlement_id:
                raise PackageProductGcExecutionError(
                    "Package GC root proof changed",
                    code="plugin_package_gc_result_conflict",
                )
            deleted_root_ids.add(target.committed_set.committed_set.root_ref.ref_id)
        return project_package_dependency_retention(
            committed_sets,
            successfully_deleted_root_ref_ids=frozenset(deleted_root_ids),
        )

    def _recover_product_transactions(self) -> None:
        recovery_id = f"product-gc-recovery:{secrets.token_hex(16)}"
        factory = self.product.factory_for_session(
            session_id=recovery_id,
            cwd=self.product.workspace,
            runtime_id=recovery_id,
        )
        binding: PackageProductRuntimeBindingV1 | None = None
        try:
            binding = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id=self.product.policy.product_id,
                    session_id=recovery_id,
                    cwd=str(self.product.workspace),
                )
            )
            binding.activate()
        finally:
            if binding is None:
                factory.dispose_unbound_runtime()
            else:
                binding.dispose_runtime()

    def _require_no_open_transaction_pins(self) -> None:
        latest = {
            record.operation_id: record.receipt
            for record in self.transaction_pins.records()
        }
        if any(receipt.state == "acquired" for receipt in latest.values()):
            raise PackageProductGcExecutionError(
                "Package Product transaction pin is still acquired",
                code="plugin_package_gc_transaction_pin_active",
            )


def open_posix_local_wheel_product_root_gc(
    product: PosixLocalWheelProductSessionOwner,
    *,
    repair_authority: PackageProductGcDependencyRepairAuthorityPort | None = None,
    worker_history_authority: PackageProductGcWorkerHistoryAuthorityPort | None = None,
) -> LocalWheelProductRootGcOwner:
    """Open persisted B owners; opening alone grants no deletion or seal."""

    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Fenced local-Wheel Product owner is required")
    return _open_local_wheel_product_root_gc(
        product,
        repair_authority=repair_authority,
        worker_history_authority=worker_history_authority,
    )


def open_windows_local_wheel_product_root_gc(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    repair_authority: PackageProductGcDependencyRepairAuthorityPort | None = None,
    worker_history_authority: PackageProductGcWorkerHistoryAuthorityPort | None = None,
) -> LocalWheelProductRootGcOwner:
    """Open the exact Windows Product and Store owners for offline GC."""

    if not isinstance(product, WindowsLocalWheelProductSessionOwner):
        raise TypeError("Fenced Windows local-Wheel Product owner is required")
    return _open_local_wheel_product_root_gc(
        product,
        repair_authority=repair_authority,
        worker_history_authority=worker_history_authority,
    )


def _open_local_wheel_product_root_gc(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    *,
    repair_authority: PackageProductGcDependencyRepairAuthorityPort | None,
    worker_history_authority: PackageProductGcWorkerHistoryAuthorityPort | None = None,
) -> LocalWheelProductRootGcOwner:
    product.assert_root_gc_authority_current()
    state_root: Path = product.state_root
    intents = PluginRetirementIntentLedger(
        product.management.retirement_intent_journal_path
    )
    retirement_sets = PluginRetirementSetLedger(
        product.management.retirement_set_journal_path,
        retirement_intents=intents,
    )
    instance_path = state_root / "instance-runtime.jsonl"
    instances = PluginInstanceRuntimeLedger(
        instance_path,
        management_operation_journal_path=product.management.operation_journal_path,
        desired_state=product.desired_state,
        retirement_intents=intents,
        retirement_sets=retirement_sets,
        security_acceptances=(
            PluginInstanceSecurityRetirementJournal.for_instance_runtime(instance_path)
        ),
        gc_gate=product.gc_gate,
    )
    store_id = product.epoch_runtime.registry.store_id
    packages = PluginPackageLifecycleLedger(
        state_root / "package-lifecycle.jsonl",
        startup_id=f"product-gc:{store_id}",
        desired_state=product.desired_state,
        instance_runtime=instances,
        retirement_sets=retirement_sets,
        gc_gate=product.gc_gate,
    )
    settlements = PackageStoreSettlementJournal(state_root / "root-settlements.jsonl")
    root_store = (
        WindowsPackagePluginRootMaterializationStore(
            product.plugin_store_root,
            store_identity=product.root_store_identity,
            package_store_id=store_id,
            settlement_journal=settlements,
        )
        if isinstance(product, WindowsLocalWheelProductSessionOwner)
        else PosixPackagePluginRootMaterializationStore(
            product.plugin_store_root,
            store_identity=product.root_store_identity,
            package_store_id=store_id,
            settlement_journal=settlements,
        )
    )
    executor = PackageProductRootGcExecutor(
        gate=product.gc_gate,
        lifecycle=packages,
        bindings=product.gc_bindings,
        committed_sets=PackageCommittedSetJournal(state_root / "committed-sets.jsonl"),
        root_settlements=settlements,
        root_store=root_store,
        results=PluginPackageGcResultJournal(state_root / "gc-results.jsonl"),
    )
    product.assert_root_gc_authority_current()
    dependency_settlements = PackageStoreSettlementJournal(
        state_root / "dependency-settlements.jsonl"
    )

    def dependency_store() -> PackageProductGcDependencyStorePort:
        if isinstance(product, WindowsLocalWheelProductSessionOwner):
            return WindowsPackageDependencyMaterializationStore(
                product.dependency_store_root,
                store_identity=product.dependency_store_identity,
                settlement_journal=dependency_settlements,
            )
        return PosixPackageDependencyMaterializationStore(
            product.dependency_store_root,
            store_identity=product.dependency_store_identity,
            settlement_journal=dependency_settlements,
        )

    return LocalWheelProductRootGcOwner(
        product=product,
        instances=instances,
        packages=packages,
        transaction_pins=PackageTransactionPinJournal(
            state_root / "transaction-pins.jsonl"
        ),
        dependency_settlements=dependency_settlements,
        dependency_store_factory=dependency_store,
        application=PackageProductRootGcApplication(
            gate=product.gc_gate, lifecycle=packages, executor=executor
        ),
        read_model=PackageProductRootGcReadModel(executor),
        repair_authority=repair_authority,
        worker_history_authority=worker_history_authority,
    )


PosixLocalWheelProductRootGcOwner = LocalWheelProductRootGcOwner


__all__ = [
    "PackageProductGcDependencyStorePort",
    "PackageProductGcDependencyRepairAuthorityPort",
    "PackageProductGcDependencyRepairStatusV1",
    "LocalWheelProductRootGcOwner",
    "PosixLocalWheelProductRootGcOwner",
    "open_posix_local_wheel_product_root_gc",
    "open_windows_local_wheel_product_root_gc",
]
