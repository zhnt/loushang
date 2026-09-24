"""Offline root GC composed from one fenced local-Wheel Product owner."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

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
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
)
from loushang.harness.plugin_management.package_gc_results import (
    PluginPackageGcAttemptV1,
    PluginPackageGcResultJournal,
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
    PosixPackagePluginRootMaterializationStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
)


@dataclass(frozen=True, slots=True)
class PosixLocalWheelProductRootGcOwner:
    """Keep Product references and runtime quiescence through exact deletion."""

    product: PosixLocalWheelProductSessionOwner
    instances: PluginInstanceRuntimeLedger
    packages: PluginPackageLifecycleLedger
    transaction_pins: PackageTransactionPinJournal
    application: PackageProductRootGcApplication
    read_model: PackageProductRootGcReadModel

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
        ):
            raise ValueError("Package Product root GC owners are not bound")

    @contextmanager
    def _offline(self) -> Iterator[None]:
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
            with self.product.gc_gate.guard():
                yield
            self.product.assert_root_gc_authority_current()

    def prepare(self) -> None:
        """Explicitly recover and seal the complete B Product reference graph."""

        with self._offline():
            pass
        self._recover_product_transactions()
        store_id = self.product.epoch_runtime.registry.store_id
        with self._offline():
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
        with self._offline():
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

        with self._offline():
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
) -> PosixLocalWheelProductRootGcOwner:
    """Open persisted B owners; opening alone grants no deletion or seal."""

    if not isinstance(product, PosixLocalWheelProductSessionOwner):
        raise TypeError("Fenced local-Wheel Product owner is required")
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
    executor = PackageProductRootGcExecutor(
        gate=product.gc_gate,
        lifecycle=packages,
        bindings=product.gc_bindings,
        committed_sets=PackageCommittedSetJournal(state_root / "committed-sets.jsonl"),
        root_settlements=settlements,
        root_store=PosixPackagePluginRootMaterializationStore(
            product.plugin_store_root,
            store_identity=product.root_store_identity,
            package_store_id=store_id,
            settlement_journal=settlements,
        ),
        results=PluginPackageGcResultJournal(state_root / "gc-results.jsonl"),
    )
    product.assert_root_gc_authority_current()
    return PosixLocalWheelProductRootGcOwner(
        product=product,
        instances=instances,
        packages=packages,
        transaction_pins=PackageTransactionPinJournal(
            state_root / "transaction-pins.jsonl"
        ),
        application=PackageProductRootGcApplication(
            gate=product.gc_gate, lifecycle=packages, executor=executor
        ),
        read_model=PackageProductRootGcReadModel(executor),
    )


__all__ = [
    "PosixLocalWheelProductRootGcOwner",
    "open_posix_local_wheel_product_root_gc",
]
