"""PLC9A2 composition root for the accepted Package Product owners."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal

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
    PackageProductAdmissionBindingPort,
    PackageProductLifecycleExecutionBinding,
    PackageProductLifecycleRouter,
    PackageProductLifecycleTransactionPort,
    PackageProductPinnedAdoptedRouteRequestV1,
    PackageProductReboundRouteRequestV1,
    PackageProductRouteRequestV1,
    PackageProductStagingAdoptedRouteRequestV1,
    PackageProductTransactionRoute,
)
from loushang.harness.resources.packages.product_pinned_adoption_binding import (
    PackageProductPinnedAdoptionBindingJournal,
)
from loushang.harness.resources.packages.product_rebind_admission_binding import (
    PackageProductRebindAdmissionBindingJournal,
)
from loushang.harness.resources.packages.product_staging_adoption_binding import (
    PackageProductStagingAdoptionBindingJournal,
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
        return self._recover(operation_id=None)

    def recover_exact(self, operation_id: str) -> tuple[str, ...]:
        """Resume only one Package operation's retained handoff."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package recovery operation ID is required")
        return self._recover(operation_id=operation_id)

    def _recover(self, *, operation_id: str | None) -> tuple[str, ...]:
        latest: dict[str, PackageRetentionHandoffReceiptV1] = {}
        for record in self.journal.records():
            if record.receipt is not None and (
                operation_id is None
                or record.receipt.request.operation_id == operation_id
            ):
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
    rebind_bindings: PackageProductRebindAdmissionBindingJournal | None = None
    pinned_bindings: PackageProductPinnedAdoptionBindingJournal | None = None
    staging_bindings: PackageProductStagingAdoptionBindingJournal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.product_id, str) or not self.product_id:
            raise ValueError("Package Product identity is required")
        if not isinstance(self.kernel, PackageLifecycleOwner):
            raise TypeError("Package lifecycle owner is required")
        if not isinstance(self.journal, PackageRetentionHandoffJournal):
            raise TypeError("Package handoff journal is required")
        if not isinstance(self.finalizer, PackageProductHandoffFinalizer):
            raise TypeError("Package Product handoff finalizer is required")
        if self.rebind_bindings is not None and not isinstance(
            self.rebind_bindings, PackageProductRebindAdmissionBindingJournal
        ):
            raise TypeError("Product rebind admission bindings are invalid")
        if self.pinned_bindings is not None and not isinstance(
            self.pinned_bindings, PackageProductPinnedAdoptionBindingJournal
        ):
            raise TypeError("Product pinned admission bindings are invalid")
        if self.staging_bindings is not None and not isinstance(
            self.staging_bindings, PackageProductStagingAdoptionBindingJournal
        ):
            raise TypeError("Product staging admission bindings are invalid")

    def recover(
        self, admission: PackageEpochRuntimeAdmissionReceiptV1
    ) -> tuple[str, ...]:
        return self._recover(admission, operation_id=None)

    def recover_exact(
        self, admission: PackageEpochRuntimeAdmissionReceiptV1, operation_id: str
    ) -> tuple[str, ...]:
        """Finalize only one committed operation under the admitted epoch."""

        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Package recovery operation ID is required")
        return self._recover(admission, operation_id=operation_id)

    def terminal_state(self, operation_id: str) -> Literal["settled", "aborted"] | None:
        """Read one exact committed Product handoff after recovery."""

        if type(operation_id) is not str or not operation_id:
            raise ValueError("Package recovery operation ID is required")
        records = tuple(
            record
            for record in self.kernel.journal.records()
            if record.status.operation_id == operation_id
        )
        if not records:
            return None
        record = records[-1]
        request, status = record.request, record.status
        if (
            request.product_id != self.product_id
            or not isinstance(request, PackageLifecycleRequestV2)
            or status.phase != "committed"
            or status.disposition != "committed"
            or status.classification is None
            or status.classification.decision != "plugin_bound"
        ):
            return None
        handoffs: dict[str, PackageRetentionHandoffReceiptV1] = {}
        for handoff_record in self.journal.records():
            receipt = handoff_record.receipt
            if receipt is not None and receipt.request.operation_id == operation_id:
                handoffs[handoff_record.handoff_id] = receipt
        if len(handoffs) > 1:
            raise self._incomplete("Package handoff has multiple identities")
        if not handoffs:
            return None
        receipt = next(iter(handoffs.values()))
        if receipt.state not in {"settled", "aborted"}:
            return None
        publication = receipt.request.admission_request.publication_receipt
        if (
            publication is None
            or publication.operation_id != operation_id
            or publication.request_fingerprint != status.request_fingerprint
            or publication.attempt_epoch != status.attempt_epoch
            or publication.commit_status_revision != status.journal_revision
            or publication.product_id != request.product_id
            or publication.scope_id != request.scope_id
            or publication.plugin_id != request.requested_plugin_id
            or receipt.dependency_pin_receipt is None
        ):
            raise self._incomplete("Terminal Package handoff changed owner")
        if receipt.state == "settled" and (
            receipt.desired_receipt is None
            or receipt.dependency_pin_receipt.state != "settled"
        ):
            raise self._incomplete("Settled Package handoff changed owner")
        if receipt.state == "aborted" and (
            receipt.desired_failure is None
            or receipt.desired_receipt is not None
            or receipt.dependency_pin_receipt.state != "aborted"
        ):
            raise self._incomplete("Aborted Package handoff changed owner")
        return "settled" if receipt.state == "settled" else "aborted"

    def _recover(
        self,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
        *,
        operation_id: str | None,
    ) -> tuple[str, ...]:
        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Admitted Package runtime receipt is required")
        latest = {
            record.status.operation_id: record
            for record in self.kernel.journal.records()
            if operation_id is None or record.status.operation_id == operation_id
        }
        handoffs: dict[str, dict[str, PackageRetentionHandoffReceiptV1]] = {}
        for handoff_record in self.journal.records():
            receipt = handoff_record.receipt
            if receipt is not None and (
                operation_id is None or receipt.request.operation_id == operation_id
            ):
                handoffs.setdefault(receipt.request.operation_id, {})[
                    handoff_record.handoff_id
                ] = receipt
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
            if prior and prior[0].state in {"settled", "aborted"}:
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
                    or prior[0].dependency_pin_receipt is None
                ):
                    raise self._incomplete("Terminal Package handoff changed owner")
                if prior[0].state == "settled" and (
                    prior[0].desired_receipt is None
                    or prior[0].dependency_pin_receipt.state != "settled"
                ):
                    raise self._incomplete("Settled Package handoff changed owner")
                if prior[0].state == "aborted" and (
                    prior[0].desired_failure is None
                    or prior[0].desired_receipt is not None
                    or prior[0].dependency_pin_receipt.state != "aborted"
                ):
                    raise self._incomplete("Aborted Package handoff changed owner")
                continue
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
                runtime_admission_request_id=(request.runtime_admission_request_id),
            )
            if request.runtime_admission_request_id == (
                admission.request.admission_request_id
            ):
                route: PackageProductTransactionRoute = PackageProductRouteRequestV1(
                    entrypoint="operations", ingress=ingress, admission=admission
                )
            else:
                selected_stage = self.kernel.journal.latest_staging_adoption(
                    operation_id
                )
                selected_pin = self.kernel.journal.latest_pinned_adoption(operation_id)
                if (
                    selected_stage is not None
                    and selected_stage.status.attempt_epoch == status.attempt_epoch
                    and selected_stage.record_revision <= status.attempt_revision
                ):
                    stage_proposal = (
                        None
                        if self.staging_bindings is None
                        else self.staging_bindings.read_decision(
                            selected_stage.decision.decision_id
                        )
                    )
                    if (
                        stage_proposal is None
                        or stage_proposal.decision != selected_stage.decision
                        or stage_proposal.admission.request.store_id
                        != admission.request.store_id
                        or stage_proposal.admission.request.fence_id
                        != admission.request.fence_id
                        or stage_proposal.admission.request.runtime_epoch
                        != admission.request.runtime_epoch
                        or stage_proposal.admission.request.store_root_identity
                        != admission.request.store_root_identity
                    ):
                        raise self._incomplete(
                            "Committed staging Package lacks Product admission"
                        )
                    route = PackageProductStagingAdoptedRouteRequestV1(
                        entrypoint="operations",
                        ingress=ingress,
                        admission=stage_proposal.admission,
                        decision=selected_stage.decision,
                    )
                elif (
                    selected_pin is not None
                    and selected_pin.status.attempt_epoch == status.attempt_epoch
                    and selected_pin.record_revision <= status.attempt_revision
                ):
                    pinned_proposal = (
                        None
                        if self.pinned_bindings is None
                        else self.pinned_bindings.read_decision(
                            selected_pin.decision.decision_id
                        )
                    )
                    if (
                        pinned_proposal is None
                        or pinned_proposal.decision != selected_pin.decision
                        or pinned_proposal.admission.request.store_id
                        != admission.request.store_id
                        or pinned_proposal.admission.request.fence_id
                        != admission.request.fence_id
                        or pinned_proposal.admission.request.runtime_epoch
                        != admission.request.runtime_epoch
                        or pinned_proposal.admission.request.store_root_identity
                        != admission.request.store_root_identity
                    ):
                        raise self._incomplete(
                            "Committed pinned Package lacks Product admission"
                        )
                    route = PackageProductPinnedAdoptedRouteRequestV1(
                        entrypoint="operations",
                        ingress=ingress,
                        admission=pinned_proposal.admission,
                        decision=selected_pin.decision,
                    )
                else:
                    selected = self.kernel.journal.latest_rebind(operation_id)
                    proposal = (
                        None
                        if selected is None or self.rebind_bindings is None
                        else self.rebind_bindings.read_decision(
                            selected.decision.decision_id
                        )
                    )
                    if (
                        selected is None
                        or proposal is None
                        or proposal.decision != selected.decision
                        or proposal.admission.request.store_id
                        != admission.request.store_id
                        or proposal.admission.request.fence_id
                        != admission.request.fence_id
                        or proposal.admission.request.runtime_epoch
                        != admission.request.runtime_epoch
                        or proposal.admission.request.store_root_identity
                        != admission.request.store_root_identity
                    ):
                        raise self._incomplete(
                            "Committed rebound Package lacks Product admission"
                        )
                    route = PackageProductReboundRouteRequestV1(
                        entrypoint="operations",
                        ingress=ingress,
                        admission=proposal.admission,
                        decision=selected.decision,
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
    reference_guard: Callable[[], AbstractContextManager[object]] | None = None,
    update_preflight: Callable[[PackageProductRouteRequestV1], None] | None = None,
    admission_binding: PackageProductAdmissionBindingPort | None = None,
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
            reference_guard=reference_guard,
            update_preflight=update_preflight,
            admission_binding=admission_binding,
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
