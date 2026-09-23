"""PLC9A2 composition root for the accepted Package Product owners."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionOwner,
    PackageEpochRuntimeAdmissionReceiptV1,
    PackageEpochRuntimeAdmissionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleIngressRequestV2,
    PackageLifecycleRequestV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
    PackageRetentionHandoffOwner,
    PackageRetentionHandoffReceiptV1,
)
from loushang.harness.resources.packages.product_activation import (
    PackageProductActivationError,
    PackageProductAdmittedRecoveryPort,
    PackageProductEpochTransactionGuardPort,
    PackageProductIngressFactoryPort,
    PackageProductLifecycleActivation,
    PackageProductRecoveryPort,
)
from loushang.harness.resources.packages.product_handoff import (
    PackageProductHandoffFinalizer,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductLifecycleExecutionBinding,
    PackageProductLifecycleRouter,
    PackageProductLifecycleTransactionPort,
    PackageProductRouteRequestV1,
)


@dataclass(frozen=True, slots=True)
class PackageRetentionHandoffRecovery:
    """Resume every nonterminal retention handoff before Product activation."""

    journal: PackageRetentionHandoffJournal
    owner: PackageRetentionHandoffOwner

    def __post_init__(self) -> None:
        if not isinstance(self.journal, PackageRetentionHandoffJournal):
            raise TypeError("Package retention handoff journal is required")
        if not isinstance(self.owner, PackageRetentionHandoffOwner):
            raise TypeError("Package retention handoff owner is required")

    def recover(self) -> tuple[str, ...]:
        latest: dict[str, PackageRetentionHandoffReceiptV1] = {}
        for record in self.journal.records():
            if record.receipt is not None:
                latest[record.handoff_id] = record.receipt
        recovered: list[str] = []
        for handoff_id in sorted(latest):
            receipt = latest[handoff_id]
            if receipt.state in {"settled", "aborted"}:
                continue
            result = self.owner.execute(receipt.request, expected_receipt=receipt)
            if result.disposition == "retryable_failure" or (
                result.disposition == "rejected"
                and result.code == "package_retention_handoff_stale"
            ):
                raise PackageProductActivationError(
                    "Package retention handoff recovery remains incomplete",
                    code="package_product_recovery_incomplete",
                )
            recovered.append(handoff_id)
        return tuple(recovered)


@dataclass(frozen=True, slots=True)
class PackageCommittedProductHandoffRecovery:
    """Close the post-commit, pre-handoff-journal crash window at startup."""

    product_id: str
    kernel: PackageLifecycleOwner
    journal: PackageRetentionHandoffJournal
    finalizer: PackageProductHandoffFinalizer

    def __post_init__(self) -> None:
        if not isinstance(self.product_id, str) or not self.product_id:
            raise ValueError("Package Product identity is required")
        if not isinstance(self.kernel, PackageLifecycleOwner):
            raise TypeError("Package lifecycle owner is required")
        if not isinstance(self.journal, PackageRetentionHandoffJournal):
            raise TypeError("Package handoff journal is required")
        if not isinstance(self.finalizer, PackageProductHandoffFinalizer):
            raise TypeError("Package Product handoff finalizer is required")

    def recover(
        self, admission: PackageEpochRuntimeAdmissionReceiptV1
    ) -> tuple[str, ...]:
        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Admitted Package runtime receipt is required")
        latest = {
            record.status.operation_id: record
            for record in self.kernel.journal.records()
        }
        handoffs: dict[str, dict[str, PackageRetentionHandoffReceiptV1]] = {}
        for handoff_record in self.journal.records():
            receipt = handoff_record.receipt
            if receipt is not None:
                operation_id = receipt.request.operation_id
                handoffs.setdefault(operation_id, {})[handoff_record.handoff_id] = receipt
        recovered: list[str] = []
        for operation_id, record in sorted(latest.items()):
            request = record.request
            status = record.status
            if (
                request.product_id != self.product_id
                or not isinstance(request, PackageLifecycleRequestV2)
                or status.phase != "committed"
                or status.disposition != "committed"
                or status.classification is None
                or status.classification.decision != "plugin_bound"
            ):
                continue
            prior = tuple(handoffs.get(operation_id, {}).values())
            if len(prior) > 1:
                raise self._incomplete("Package handoff has multiple identities")
            if prior and prior[0].state == "settled":
                publication = prior[0].request.admission_request.publication_receipt
                if (
                    publication is None
                    or publication.operation_id != operation_id
                    or publication.request_fingerprint != status.request_fingerprint
                    or publication.attempt_epoch != status.attempt_epoch
                    or publication.commit_status_revision != status.journal_revision
                    or publication.product_id != request.product_id
                    or publication.scope_id != request.scope_id
                    or publication.plugin_id != request.requested_plugin_id
                    or prior[0].desired_receipt is None
                    or prior[0].dependency_pin_receipt is None
                    or prior[0].dependency_pin_receipt.state != "settled"
                ):
                    raise self._incomplete("Settled Package handoff changed owner")
                continue
            if request.runtime_admission_request_id != (
                admission.request.admission_request_id
            ):
                raise self._incomplete("Committed Package belongs to another epoch")
            ingress = PackageLifecycleIngressRequestV2(
                operation_id=request.operation_id,
                action=request.action,
                product_id=request.product_id,
                scope_id=request.scope_id,
                requested_package=request.requested_package,
                requested_plugin_id=request.requested_plugin_id,
                source_locator=request.canonical_source_identity,
                policy_revision=request.policy_revision,
                quota_profile_revision=request.quota_profile_revision,
                resolution_environment_fingerprint=(
                    request.resolution_environment_fingerprint
                ),
                runtime_admission_request_id=(
                    request.runtime_admission_request_id
                ),
            )
            route = PackageProductRouteRequestV1(
                entrypoint="operations", ingress=ingress, admission=admission
            )
            try:
                self.finalizer.finalize(route, current=status)
            except Exception as exc:
                raise self._incomplete(
                    "Committed Package Product handoff recovery failed"
                ) from exc
            recovered.append(operation_id)
        return tuple(recovered)

    @staticmethod
    def _incomplete(message: str) -> PackageProductActivationError:
        return PackageProductActivationError(
            message, code="package_product_recovery_incomplete"
        )


def compose_package_product_lifecycle(
    *,
    product_id: str,
    owner: PackageLifecycleOwner,
    transaction: PackageProductLifecycleTransactionPort,
    ingress_factory: PackageProductIngressFactoryPort,
    runtime_admission: PackageEpochRuntimeAdmissionOwner,
    admission_request: PackageEpochRuntimeAdmissionRequestV1,
    transaction_guard: PackageProductEpochTransactionGuardPort,
    recoveries: tuple[PackageProductRecoveryPort, ...] = (),
    admitted_recoveries: tuple[PackageProductAdmittedRecoveryPort, ...] = (),
) -> PackageProductLifecycleActivation:
    """Build the sole Product router; the caller explicitly activates it."""

    execution = PackageProductLifecycleExecutionBinding(
        owner=owner,
        transaction=transaction,
    )
    return PackageProductLifecycleActivation(
        product_id=product_id,
        binding_id=execution.owner.binding_id,
        router=PackageProductLifecycleRouter(
            execution=execution,
        ),
        ingress_factory=ingress_factory,
        runtime_admission=runtime_admission,
        admission_request=admission_request,
        transaction_guard=transaction_guard,
        recoveries=recoveries,
        admitted_recoveries=admitted_recoveries,
    )


__all__ = [
    "PackageCommittedProductHandoffRecovery",
    "PackageRetentionHandoffRecovery",
    "compose_package_product_lifecycle",
]
