"""Guarded Product selection of a new admission for one retained pin.

The proposal is durable before the Package CAS. Neither record grants a
transaction permit; execution has a separate Product route and owner check.
"""

from __future__ import annotations

from hashlib import sha256
from threading import Lock

from loushang.harness.package_product.product_rebind_cleanup import (
    PackageProductRebindCleanupReader,
)
from loushang.harness.package_product.product_rebind_lease import (
    PackageProductRebindLeaseReader,
)
from loushang.harness.package_product.product_rebind_preflight import (
    PackageProductPinnedRebindPreflightV1,
)
from loushang.harness.package_product.product_rebind_source import (
    PackageProductRebindSourceReader,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleIngressRequestV2,
    PackageLifecyclePinnedAdoptionRecordV1,
    PackageLifecyclePinnedAdoptionRequestV1,
    PackageLifecycleRequestV2,
    PackageLifecycleStatusV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductPinnedAdoptedRouteRequestV1,
    PackageProductRouteContractError,
)
from loushang.harness.resources.packages.product_pinned_adoption_binding import (
    PackageProductPinnedAdoptionBindingJournal,
)


class PackageProductPinnedAdoptionError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageProductPinnedAdoptionOwner:
    """Recheck Source, lease, verified closure, and acquired pin under guard."""

    def __init__(
        self,
        *,
        lifecycle: PackageLifecycleJournal,
        source: PackageProductRebindSourceReader,
        lease: PackageProductRebindLeaseReader,
        cleanup: PackageProductRebindCleanupReader,
        resolution: PackageClosureResolutionJournal,
        proposals: PackageProductPinnedAdoptionBindingJournal,
    ) -> None:
        if not isinstance(lifecycle, PackageLifecycleJournal):
            raise TypeError("Package lifecycle journal is required")
        if not isinstance(source, PackageProductRebindSourceReader):
            raise TypeError("Pinned Source reader is required")
        if not isinstance(lease, PackageProductRebindLeaseReader):
            raise TypeError("Pinned lease reader is required")
        if not isinstance(cleanup, PackageProductRebindCleanupReader):
            raise TypeError("Pinned cleanup reader is required")
        if not isinstance(resolution, PackageClosureResolutionJournal):
            raise TypeError("Verified closure journal is required")
        if not isinstance(proposals, PackageProductPinnedAdoptionBindingJournal):
            raise TypeError("Pinned admission proposal journal is required")
        self._lifecycle = lifecycle
        self._source = source
        self._lease = lease
        self._cleanup = cleanup
        self._resolution = resolution
        self._proposals = proposals
        self._authorization_lock = Lock()
        self._authorized: set[
            tuple[
                PackageProductPinnedAdoptedRouteRequestV1,
                PackageLifecycleStatusV1,
            ]
        ] = set()

    def prepare(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageLifecyclePinnedAdoptionRecordV1:
        """Persist a proposal, select it by CAS, then recheck owner evidence."""

        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Current Product admission receipt is required")
        observed, plan_fingerprint = self._observe(
            operation_id, max_bytes=max_bytes
        )
        if not self._admission_matches(observed, admission):
            raise PackageProductPinnedAdoptionError(
                "Pinned admission changed current lease",
                code="package_pinned_adoption_admission_changed",
            )
        status = observed.cleanup.closure.status
        prior = self._lifecycle.latest_pinned_adoption(operation_id)
        pending = observed.lease.pending_pinned_decision_id
        if pending is not None:
            if prior is None or prior.status != status or (
                prior.decision.decision_id != pending
            ):
                raise PackageProductPinnedAdoptionError(
                    "Pinned adoption changed selected proposal",
                    code="package_pinned_adoption_selection_changed",
                )
            if (
                prior.decision.new_runtime_admission_request_id
                == admission.request.admission_request_id
            ):
                if not self._matches(prior.decision, observed, plan_fingerprint):
                    raise PackageProductPinnedAdoptionError(
                        "Selected pinned evidence changed on replay",
                        code="package_pinned_adoption_evidence_changed",
                    )
                self._require_proposal(prior.decision, admission)
                return prior
        elif prior is not None and prior.status == status:
            raise PackageProductPinnedAdoptionError(
                "Pinned adoption lost selected proposal",
                code="package_pinned_adoption_selection_changed",
            )

        decision = PackageLifecyclePinnedAdoptionRequestV1(
            operation_id=operation_id,
            request_fingerprint=status.request_fingerprint,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
            expected_attempt_revision=status.attempt_revision,
            new_runtime_admission_request_id=(
                admission.request.admission_request_id
            ),
            source_proof_ref=observed.source.source_proof_ref,
            closure_plan_fingerprint=plan_fingerprint,
            pin_receipt_id=observed.cleanup.pin.receipt_id,
            lease_snapshot_id=observed.lease.lease_snapshot_id,
        )
        self._proposals.bind(decision, admission)
        if pending is None:
            record = self._lifecycle.record_pinned_adoption(decision)
        else:
            assert prior is not None
            record = self._lifecycle.supersede_pinned_adoption(
                decision,
                supersedes_decision_id=pending,
                expected_prior_record_revision=prior.record_revision,
            )
        after, after_plan = self._observe(operation_id, max_bytes=max_bytes)
        if (
            after.cleanup.closure.status != record.status
            or after.lease.pending_pinned_decision_id != decision.decision_id
            or not self._admission_matches(after, admission)
            or not self._matches(decision, after, after_plan)
            or self._lifecycle.latest_pinned_adoption(operation_id) != record
        ):
            raise PackageProductPinnedAdoptionError(
                "Pinned adoption changed after durable selection",
                code="package_pinned_adoption_evidence_changed",
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
        PackageLifecyclePinnedAdoptionRecordV1,
        PackageLifecycleStatusV1,
        PackageProductPinnedAdoptedRouteRequestV1,
    ]:
        """Recheck the selected pinned proposal and issue one execution permit."""

        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Current Product admission receipt is required")
        record = self._lifecycle.latest_pinned_adoption(operation_id)
        if record is None:
            raise PackageProductPinnedAdoptionError(
                "Pinned Package has no selected adoption",
                code="package_pinned_adoption_selection_missing",
            )
        observed, plan_fingerprint = self._observe(
            operation_id, max_bytes=max_bytes
        )
        status = observed.cleanup.closure.status
        if (
            status != record.status
            or observed.lease.pending_pinned_decision_id
            != record.decision.decision_id
            or not self._admission_matches(observed, admission)
            or not self._matches(record.decision, observed, plan_fingerprint)
            or self._lifecycle.latest_pinned_adoption(operation_id) != record
        ):
            raise PackageProductPinnedAdoptionError(
                "Pinned Package execution changed owner evidence",
                code="package_pinned_adoption_evidence_changed",
            )
        self._require_proposal(record.decision, admission)
        route = self.route(record, admission)
        key = self._permit_key(route, status)
        with self._authorization_lock:
            self._authorized.add(key)
        return record, status, route

    def authorize(
        self,
        request: PackageProductPinnedAdoptedRouteRequestV1,
        current: PackageLifecycleStatusV1,
    ) -> None:
        """Consume the exact in-memory permit before transaction effects."""

        if not isinstance(request, PackageProductPinnedAdoptedRouteRequestV1):
            raise TypeError("Pinned Package Product route is required")
        key = self._permit_key(request, current)
        with self._authorization_lock:
            authorized = key in self._authorized
            if authorized:
                self._authorized.remove(key)
        if not authorized:
            raise PackageProductRouteContractError(
                "Pinned Package transaction has no Product authorization",
                code="package_pinned_adoption_execution_not_available",
            )

    def revoke(
        self,
        request: PackageProductPinnedAdoptedRouteRequestV1,
        current: PackageLifecycleStatusV1,
    ) -> None:
        if not isinstance(request, PackageProductPinnedAdoptedRouteRequestV1):
            raise TypeError("Pinned Package Product route is required")
        with self._authorization_lock:
            self._authorized.discard(self._permit_key(request, current))

    @staticmethod
    def _permit_key(
        request: PackageProductPinnedAdoptedRouteRequestV1,
        status: PackageLifecycleStatusV1,
    ) -> tuple[
        PackageProductPinnedAdoptedRouteRequestV1,
        PackageLifecycleStatusV1,
    ]:
        return request, status

    def route(
        self,
        record: PackageLifecyclePinnedAdoptionRecordV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageProductPinnedAdoptedRouteRequestV1:
        """Reconstruct original ingress without replacing the owner request."""

        original = self._lifecycle.read_operation(record.decision.operation_id)
        if (
            original is None
            or not isinstance(original[0], PackageLifecycleRequestV2)
            or original[0] != record.request
        ):
            raise PackageProductPinnedAdoptionError(
                "Pinned Package original ingress changed",
                code="package_pinned_adoption_original_request_changed",
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
        return PackageProductPinnedAdoptedRouteRequestV1(
            entrypoint="operations",
            ingress=ingress,
            admission=admission,
            decision=record.decision,
        )

    def _observe(
        self, operation_id: str, *, max_bytes: int
    ) -> tuple[PackageProductPinnedRebindPreflightV1, str]:
        observed = PackageProductPinnedRebindPreflightV1(
            source=self._source.observe_pinned_claim(
                operation_id, max_bytes=max_bytes
            ),
            lease=self._lease.observe_pinned_claim(operation_id),
            cleanup=self._cleanup.observe_pinned_claim(operation_id),
        )
        status = observed.cleanup.closure.status
        plan = self._resolution.read_plan(
            operation_id=operation_id, attempt_epoch=status.attempt_epoch
        )
        if (
            plan is None
            or plan.graph_digest
            != observed.cleanup.pin.pin_request.prepublication_graph_digest
        ):
            raise PackageProductPinnedAdoptionError(
                "Pinned adoption lost verified closure plan",
                code="package_pinned_adoption_plan_changed",
            )
        return observed, sha256(canonical_json_bytes(plan.to_dict())).hexdigest()

    @staticmethod
    def _admission_matches(
        observed: PackageProductPinnedRebindPreflightV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> bool:
        lease = observed.lease
        return (
            lease.new_admission_request_id
            == admission.request.admission_request_id
            and lease.new_lease_id == admission.request.lease_id
            and lease.store_id == admission.request.store_id
            and lease.lease_snapshot_id == admission.lease_snapshot_id
        )

    @staticmethod
    def _matches(
        decision: PackageLifecyclePinnedAdoptionRequestV1,
        observed: PackageProductPinnedRebindPreflightV1,
        plan_fingerprint: str,
    ) -> bool:
        status = observed.cleanup.closure.status
        return (
            decision.operation_id == status.operation_id
            and decision.request_fingerprint == status.request_fingerprint
            and decision.expected_journal_revision == status.journal_revision
            and decision.expected_attempt_epoch == status.attempt_epoch
            and decision.new_runtime_admission_request_id
            == observed.lease.new_admission_request_id
            and decision.source_proof_ref == observed.source.source_proof_ref
            and decision.closure_plan_fingerprint == plan_fingerprint
            and decision.pin_receipt_id == observed.cleanup.pin.receipt_id
            and decision.lease_snapshot_id == observed.lease.lease_snapshot_id
        )

    def _require_proposal(
        self,
        decision: PackageLifecyclePinnedAdoptionRequestV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> None:
        proposal = self._proposals.read_decision(decision.decision_id)
        if (
            proposal is None
            or proposal.decision != decision
            or proposal.admission != admission
        ):
            raise PackageProductPinnedAdoptionError(
                "Pinned admission proposal changed",
                code="package_pinned_adoption_proposal_changed",
            )
