"""Product selection of a replacement admission for one staged prefix.

The Product proposal precedes the Package CAS. Selection alone has no
transaction execution authority.
"""

from __future__ import annotations

from threading import Lock

from loushang.harness.package_product.product_rebind_lease import (
    PackageProductRebindLeaseReader,
)
from loushang.harness.package_product.product_rebind_preflight import (
    PackageProductPublishedSetPreflightV1,
    PackageProductStagingRebindPreflightV1,
)
from loushang.harness.package_product.product_rebind_source import (
    PackageProductRebindSourceReader,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleIngressRequestV2,
    PackageLifecycleRequestV2,
    PackageLifecycleStagingAdoptionRecordV1,
    PackageLifecycleStagingAdoptionRequestV1,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackageStagingSetLifecycleOwner,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductRouteContractError,
    PackageProductStagingAdoptedRouteRequestV1,
)
from loushang.harness.resources.packages.product_staging_adoption_binding import (
    PackageProductStagingAdoptionBindingJournal,
)


class PackageProductStagingAdoptionError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageProductStagingAdoptionOwner:
    """Select a new lease after exact Source and Store checkpoint rechecks."""

    def __init__(
        self,
        *,
        lifecycle: PackageLifecycleJournal,
        source: PackageProductRebindSourceReader,
        lease: PackageProductRebindLeaseReader,
        checkpoint: PackageStagingSetLifecycleOwner,
        proposals: PackageProductStagingAdoptionBindingJournal,
    ) -> None:
        if not isinstance(lifecycle, PackageLifecycleJournal):
            raise TypeError("Package lifecycle journal is required")
        if not isinstance(source, PackageProductRebindSourceReader):
            raise TypeError("Staging Source reader is required")
        if not isinstance(lease, PackageProductRebindLeaseReader):
            raise TypeError("Staging lease reader is required")
        if not isinstance(checkpoint, PackageStagingSetLifecycleOwner):
            raise TypeError("Package staging checkpoint owner is required")
        if not isinstance(proposals, PackageProductStagingAdoptionBindingJournal):
            raise TypeError("Staging admission proposal journal is required")
        self._lifecycle = lifecycle
        self._source = source
        self._lease = lease
        self._checkpoint = checkpoint
        self._proposals = proposals
        self._authorization_lock = Lock()
        self._authorized: set[
            tuple[PackageProductStagingAdoptedRouteRequestV1, PackageLifecycleStatusV1]
        ] = set()

    def prepare(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageLifecycleStagingAdoptionRecordV1:
        """Persist an inert proposal, select it, and recheck all owner facts."""

        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Current Product admission receipt is required")
        observed = self._observe(operation_id, max_bytes=max_bytes)
        if not self._admission_matches(observed, admission):
            raise PackageProductStagingAdoptionError(
                "Staging admission changed current lease",
                code="package_staging_adoption_admission_changed",
            )
        status = observed.checkpoint.status
        prior_stage = self._lifecycle.latest_staging_adoption(operation_id)
        pending_stage = observed.lease.pending_staging_decision_id
        pending_pin = observed.lease.pending_pinned_decision_id
        if pending_stage is not None:
            if (
                prior_stage is None
                or prior_stage.status != status
                or prior_stage.decision.decision_id != pending_stage
            ):
                raise PackageProductStagingAdoptionError(
                    "Staging adoption changed selected proposal",
                    code="package_staging_adoption_selection_changed",
                )
            if (
                prior_stage.decision.new_runtime_admission_request_id
                == admission.request.admission_request_id
            ):
                if not self._matches(prior_stage.decision, observed):
                    raise PackageProductStagingAdoptionError(
                        "Selected staging evidence changed on replay",
                        code="package_staging_adoption_evidence_changed",
                    )
                self._require_proposal(prior_stage.decision, admission)
                return prior_stage
        elif prior_stage is not None and prior_stage.status == status:
            raise PackageProductStagingAdoptionError(
                "Staging adoption lost selected proposal",
                code="package_staging_adoption_selection_changed",
            )
        if pending_stage is None and pending_pin is not None:
            prior_pin = self._lifecycle.latest_pinned_adoption(operation_id)
            if (
                prior_pin is None
                or prior_pin.status != status
                or prior_pin.decision.decision_id != pending_pin
            ):
                raise PackageProductStagingAdoptionError(
                    "Pinned predecessor changed before staging adoption",
                    code="package_staging_adoption_selection_changed",
                )
        predecessor = pending_stage or pending_pin
        decision = PackageLifecycleStagingAdoptionRequestV1(
            operation_id=operation_id,
            request_fingerprint=status.request_fingerprint,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
            expected_attempt_revision=status.attempt_revision,
            new_runtime_admission_request_id=admission.request.admission_request_id,
            source_proof_ref=observed.source.source_proof_ref,
            closure_plan_fingerprint=observed.checkpoint.plan_fingerprint,
            pin_receipt_id=observed.checkpoint.pin_receipt_id,
            staging_checkpoint_id=observed.checkpoint.checkpoint_id,
            lease_snapshot_id=observed.lease.lease_snapshot_id,
            previous_selected_decision_id=predecessor,
        )
        self._proposals.bind(decision, admission)
        record = self._lifecycle.record_staging_adoption(decision)
        after = self._observe(operation_id, max_bytes=max_bytes)
        if (
            after.checkpoint.status != record.status
            or after.lease.pending_staging_decision_id != decision.decision_id
            or not self._admission_matches(after, admission)
            or not self._matches(decision, after)
            or self._lifecycle.latest_staging_adoption(operation_id) != record
        ):
            raise PackageProductStagingAdoptionError(
                "Staging adoption changed after durable selection",
                code="package_staging_adoption_evidence_changed",
            )
        self._require_proposal(decision, admission)
        return record

    def claim(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> tuple[
        PackageLifecycleStagingAdoptionRecordV1,
        PackageLifecycleStatusV1,
        PackageProductStagingAdoptedRouteRequestV1,
    ]:
        """Recheck the staged prefix and issue one exact execution permit."""

        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Current Product admission receipt is required")
        record = self._lifecycle.latest_staging_adoption(operation_id)
        if record is None:
            raise PackageProductStagingAdoptionError(
                "Staging Package has no selected adoption",
                code="package_staging_adoption_selection_missing",
            )
        observed = self._observe(operation_id, max_bytes=max_bytes)
        status = observed.checkpoint.status
        if (
            status != record.status
            or observed.lease.pending_staging_decision_id
            != record.decision.decision_id
            or not self._admission_matches(observed, admission)
            or not self._matches(record.decision, observed)
            or self._lifecycle.latest_staging_adoption(operation_id) != record
        ):
            raise PackageProductStagingAdoptionError(
                "Staging execution changed complete checkpoint evidence",
                code="package_staging_adoption_evidence_changed",
            )
        self._require_proposal(record.decision, admission)
        route = self.route(
            record,
            admission,
            missing_node_ids=(
                observed.checkpoint.missing_node_ids
                if isinstance(observed, PackageProductStagingRebindPreflightV1)
                else ()
            ),
        )
        with self._authorization_lock:
            self._authorized.add((route, status))
        return record, status, route

    def authorize(
        self,
        request: PackageProductStagingAdoptedRouteRequestV1,
        current: PackageLifecycleStatusV1,
    ) -> None:
        """Consume the exact in-memory permit before staging resume."""

        if not isinstance(request, PackageProductStagingAdoptedRouteRequestV1):
            raise TypeError("Staging Package Product route is required")
        with self._authorization_lock:
            authorized = (request, current) in self._authorized
            if authorized:
                self._authorized.remove((request, current))
        if not authorized:
            raise PackageProductRouteContractError(
                "Staging Package transaction has no Product authorization",
                code="package_staging_adoption_execution_not_available",
            )

    def revoke(
        self,
        request: PackageProductStagingAdoptedRouteRequestV1,
        current: PackageLifecycleStatusV1,
    ) -> None:
        if not isinstance(request, PackageProductStagingAdoptedRouteRequestV1):
            raise TypeError("Staging Package Product route is required")
        with self._authorization_lock:
            self._authorized.discard((request, current))

    def route(
        self,
        record: PackageLifecycleStagingAdoptionRecordV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
        *,
        missing_node_ids: tuple[str, ...] = (),
    ) -> PackageProductStagingAdoptedRouteRequestV1:
        """Reconstruct original ingress without replacing the owner request."""

        original = self._lifecycle.read_operation(record.decision.operation_id)
        if (
            original is None
            or not isinstance(original[0], PackageLifecycleRequestV2)
            or original[0] != record.request
        ):
            raise PackageProductStagingAdoptionError(
                "Staging Package original ingress changed",
                code="package_staging_adoption_original_request_changed",
            )
        request = original[0]
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
            runtime_admission_request_id=request.runtime_admission_request_id,
        )
        return PackageProductStagingAdoptedRouteRequestV1(
            entrypoint="operations",
            ingress=ingress,
            admission=admission,
            decision=record.decision,
            missing_node_ids=missing_node_ids,
        )

    def _observe(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductStagingRebindPreflightV1 | PackageProductPublishedSetPreflightV1:
        current = self._lifecycle.read_operation(operation_id)
        if current is not None and current[1].phase == "set_published":
            return PackageProductPublishedSetPreflightV1(
                source=self._source.observe_published_claim(
                    operation_id, max_bytes=max_bytes
                ),
                lease=self._lease.observe_published_claim(operation_id),
                checkpoint=self._checkpoint.inspect_published_checkpoint(operation_id),
            )
        return PackageProductStagingRebindPreflightV1(
            source=self._source.observe_pinned_claim(
                operation_id, max_bytes=max_bytes
            ),
            lease=self._lease.observe_pinned_claim(operation_id),
            checkpoint=self._checkpoint.inspect_checkpoint(operation_id),
        )

    @staticmethod
    def _admission_matches(
        observed: PackageProductStagingRebindPreflightV1 | PackageProductPublishedSetPreflightV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> bool:
        lease = observed.lease
        return (
            lease.new_admission_request_id == admission.request.admission_request_id
            and lease.new_lease_id == admission.request.lease_id
            and lease.store_id == admission.request.store_id
            and lease.lease_snapshot_id == admission.lease_snapshot_id
        )

    @staticmethod
    def _matches(
        decision: PackageLifecycleStagingAdoptionRequestV1,
        observed: PackageProductStagingRebindPreflightV1 | PackageProductPublishedSetPreflightV1,
    ) -> bool:
        status = observed.checkpoint.status
        return (
            decision.operation_id == status.operation_id
            and decision.request_fingerprint == status.request_fingerprint
            and decision.expected_journal_revision == status.journal_revision
            and decision.expected_attempt_epoch == status.attempt_epoch
            and decision.new_runtime_admission_request_id
            == observed.lease.new_admission_request_id
            and decision.source_proof_ref == observed.source.source_proof_ref
            and decision.closure_plan_fingerprint
            == observed.checkpoint.plan_fingerprint
            and decision.pin_receipt_id == observed.checkpoint.pin_receipt_id
            and decision.staging_checkpoint_id == observed.checkpoint.checkpoint_id
            and decision.lease_snapshot_id == observed.lease.lease_snapshot_id
        )

    def _require_proposal(
        self,
        decision: PackageLifecycleStagingAdoptionRequestV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> None:
        proposal = self._proposals.read_decision(decision.decision_id)
        if (
            proposal is None
            or proposal.decision != decision
            or proposal.admission != admission
        ):
            raise PackageProductStagingAdoptionError(
                "Staging admission proposal changed",
                code="package_staging_adoption_proposal_changed",
            )
