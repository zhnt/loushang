"""Product-only preparation of one durable A2 cross-runtime rebind decision.

The caller must hold the current Product epoch mutation guard. This owner
records the decision and authorizes only the exact attempt it resumes.
"""

from __future__ import annotations

from threading import Lock
from typing import Literal

from loushang.harness.package_product.product_rebind_cleanup import (
    PackageProductRebindCleanupReader,
)
from loushang.harness.package_product.product_rebind_lease import (
    PackageProductRebindLeaseObservationV1,
    PackageProductRebindLeaseReader,
)
from loushang.harness.package_product.product_rebind_preflight import (
    PackageProductAcquiredRebindPreflightV1,
    PackageProductRebindPreflightV1,
    PackageProductResolvingRebindPreflightV1,
)
from loushang.harness.package_product.product_rebind_source import (
    PackageProductRebindSourceReader,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochRuntimeAdmissionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleIngressRequestV2,
    PackageLifecycleRebindRecordV1,
    PackageLifecycleRebindRequestV1,
    PackageLifecycleRequestV2,
    PackageLifecycleRestartRecordV1,
    PackageLifecycleRestartRequestV1,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.product_lifecycle import (
    PackageProductReboundRouteRequestV1,
    PackageProductRouteContractError,
)
from loushang.harness.resources.packages.product_rebind_admission_binding import (
    PackageProductRebindAdmissionBindingJournal,
)


class PackageProductRebindDecisionError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PackageProductRebindDecisionOwner:
    """Recheck independent owner evidence before proposing and selecting a lease."""

    def __init__(
        self,
        *,
        lifecycle: PackageLifecycleJournal,
        source: PackageProductRebindSourceReader,
        lease: PackageProductRebindLeaseReader,
        cleanup: PackageProductRebindCleanupReader,
        quarantine_cleanup: PackageQuarantineCleanupOwner,
        proposals: PackageProductRebindAdmissionBindingJournal,
    ) -> None:
        if not isinstance(lifecycle, PackageLifecycleJournal):
            raise TypeError("Package lifecycle journal is required")
        if not isinstance(source, PackageProductRebindSourceReader):
            raise TypeError("Product rebind Source reader is required")
        if not isinstance(lease, PackageProductRebindLeaseReader):
            raise TypeError("Product rebind lease reader is required")
        if not isinstance(cleanup, PackageProductRebindCleanupReader):
            raise TypeError("Product rebind cleanup reader is required")
        if not isinstance(quarantine_cleanup, PackageQuarantineCleanupOwner):
            raise TypeError("Product quarantine cleanup owner is required")
        if not isinstance(proposals, PackageProductRebindAdmissionBindingJournal):
            raise TypeError("Product proposed admission journal is required")
        self._lifecycle = lifecycle
        self._source = source
        self._lease = lease
        self._cleanup = cleanup
        self._quarantine_cleanup = quarantine_cleanup
        self._proposals = proposals
        self._authorization_lock = Lock()
        self._authorized: set[tuple[str, str, str, int]] = set()

    def prepare(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageLifecycleRebindRecordV1:
        """Write proposal first, then exact Package CAS; postcheck pending facts."""

        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Current Product admission receipt is required")
        observed = self._observe(operation_id, max_bytes=max_bytes)
        if (
            observed.lease.new_admission_request_id
            != admission.request.admission_request_id
            or observed.lease.new_lease_id != admission.request.lease_id
            or observed.lease.store_id != admission.request.store_id
        ):
            raise PackageProductRebindDecisionError(
                "Rebind observation changed current Product admission",
                code="package_rebind_decision_admission_changed",
            )
        previous = self._lifecycle.latest_rebind(operation_id)
        pending = observed.lease.pending_decision_id
        if pending is not None:
            if previous is None or previous.decision.decision_id != pending:
                raise PackageProductRebindDecisionError(
                    "Rebind observation changed pending Package decision",
                    code="package_rebind_decision_pending_changed",
                )
            if (
                previous.decision.new_runtime_admission_request_id
                == admission.request.admission_request_id
            ):
                if not self._matches(previous.decision, observed):
                    raise PackageProductRebindDecisionError(
                        "Pending Package decision no longer matches owner evidence",
                        code="package_rebind_decision_evidence_changed",
                    )
                self._postcheck(
                    operation_id,
                    max_bytes=max_bytes,
                    decision=previous.decision,
                    record=previous,
                )
                return previous
        elif previous is not None and previous.status.attempt_revision == (
            observed.source.attempt_revision
        ):
            raise PackageProductRebindDecisionError(
                "Package decision changed during rebind observation",
                code="package_rebind_decision_pending_changed",
            )

        decision = PackageLifecycleRebindRequestV1(
            operation_id=operation_id,
            request_fingerprint=observed.source.request_fingerprint,
            expected_attempt_epoch=observed.source.attempt_epoch,
            expected_attempt_revision=observed.source.attempt_revision,
            new_runtime_admission_request_id=admission.request.admission_request_id,
            source_proof_ref=observed.source.source_proof_ref,
            cleanup_evidence_ref=observed.cleanup.known_cleanup_ref,
            lease_snapshot_id=observed.lease.lease_snapshot_id,
        )
        self._proposals.bind(decision, admission)
        if pending is None:
            record = self._lifecycle.record_rebind(decision)
        else:
            assert previous is not None
            record = self._lifecycle.supersede_rebind(
                decision,
                supersedes_decision_id=pending,
                expected_prior_rebind_record_revision=previous.record_revision,
            )
        self._postcheck(
            operation_id, max_bytes=max_bytes, decision=decision, record=record
        )
        return record

    def resume(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> tuple[
        PackageLifecycleRebindRecordV1,
        PackageLifecycleStatusV1,
        PackageProductReboundRouteRequestV1,
    ]:
        """Recheck the selected pending decision, then claim its next attempt."""

        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Current Product admission receipt is required")
        record = self._lifecycle.latest_rebind(operation_id)
        if record is None:
            raise PackageProductRebindDecisionError(
                "Package operation has no selected rebind decision",
                code="package_rebind_decision_missing",
            )
        observed = self._observe(operation_id, max_bytes=max_bytes)
        proposal = self._proposals.read_decision(record.decision.decision_id)
        if (
            observed.lease.pending_decision_id != record.decision.decision_id
            or observed.source.attempt_revision != record.record_revision
            or observed.lease.new_admission_request_id
            != admission.request.admission_request_id
            or observed.lease.new_lease_id != admission.request.lease_id
            or proposal is None
            or proposal.decision != record.decision
            or proposal.admission.request != admission.request
            or not self._matches(record.decision, observed)
        ):
            raise PackageProductRebindDecisionError(
                "Pending Package decision changed Product owner evidence",
                code="package_rebind_decision_evidence_changed",
            )
        self._postcheck(
            operation_id, max_bytes=max_bytes, decision=record.decision, record=record
        )
        route = self.route(record, admission)
        resumed = self._lifecycle.resume_rebind(
            record.decision, expected_rebind_record_revision=record.record_revision
        )
        if (
            resumed.disposition != "active"
            or resumed.attempt_epoch != record.decision.expected_attempt_epoch + 1
        ):
            raise PackageProductRebindDecisionError(
                "Package rebind did not claim the selected attempt",
                code="package_rebind_attempt_changed",
            )
        with self._authorization_lock:
            self._authorized.add(
                (
                    operation_id,
                    record.decision.decision_id,
                    admission.request.admission_request_id,
                    resumed.attempt_epoch,
                )
            )
        return record, resumed, route

    def authorize(
        self,
        request: PackageProductReboundRouteRequestV1,
        current: PackageLifecycleStatusV1,
    ) -> None:
        """Gate transaction effects to this owner's admitted resumed attempt."""

        if not isinstance(request, PackageProductReboundRouteRequestV1):
            raise TypeError("Rebound Package Product route is required")
        key = (
            request.ingress.operation_id,
            request.decision.decision_id,
            request.admission.request.admission_request_id,
            current.attempt_epoch,
        )
        with self._authorization_lock:
            authorized = key in self._authorized
            if authorized:
                self._authorized.remove(key)
        if not authorized:
            raise PackageProductRouteContractError(
                "Rebound Package transaction has no Product authorization",
                code="package_rebind_execution_not_available",
            )

    def revoke(
        self,
        request: PackageProductReboundRouteRequestV1,
        current: PackageLifecycleStatusV1,
    ) -> None:
        """Drop an unused execution permit when the guarded route exits."""

        if not isinstance(request, PackageProductReboundRouteRequestV1):
            raise TypeError("Rebound Package Product route is required")
        key = (
            request.ingress.operation_id,
            request.decision.decision_id,
            request.admission.request.admission_request_id,
            current.attempt_epoch,
        )
        with self._authorization_lock:
            self._authorized.discard(key)

    def recover_unstarted_claim(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageLifecycleStatusV1:
        """Interrupt a prior claim only before durable or Store effects."""

        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Current Product admission receipt is required")
        observed = self._lease.observe_abandoned_claim(operation_id)
        source = self._source.observe_unstarted_claim(
            operation_id, max_bytes=max_bytes
        )
        status = self._cleanup.prove_unstarted_attempt(operation_id)
        if (
            status.operation_id != source.operation_id
            or status.request_fingerprint != source.request_fingerprint
            or status.attempt_epoch != source.attempt_epoch
            or status.attempt_revision != source.attempt_revision
            or status.operation_id != observed.operation_id
            or status.request_fingerprint != observed.request_fingerprint
            or status.attempt_epoch != observed.attempt_epoch
            or status.attempt_revision != observed.attempt_revision
            or observed.new_admission_request_id
            != admission.request.admission_request_id
            or observed.new_lease_id != admission.request.lease_id
            or observed.store_id != admission.request.store_id
        ):
            raise PackageProductRebindDecisionError(
                "Abandoned Package attempt changed Product owner evidence",
                code="package_rebind_claim_evidence_changed",
            )
        interrupted = self._lifecycle.interrupt(
            operation_id,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
            expected_attempt_revision=status.attempt_revision,
        )
        if interrupted.disposition != "retryable_failure":
            raise PackageProductRebindDecisionError(
                "Abandoned Package attempt did not become retryable",
                code="package_rebind_claim_interrupt_changed",
            )
        return interrupted

    def recover_acquired_claim(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageLifecycleRestartRecordV1:
        """Settle one selected root-stage claim before restarting.

        The caller must hold the admitted Product mutation guard. The cleanup
        tombstone is recorded before its exact physical target is removed, so
        each crash boundary can replay from strict owner evidence.
        """

        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Current Product admission receipt is required")
        original = self._lifecycle.read_operation(operation_id)
        if original is None:
            raise PackageProductRebindDecisionError(
                "Package operation is absent", code="package_rebind_operation_missing"
            )
        _request, current = original
        prior_restart = self._lifecycle.latest_restart(operation_id)
        if (
            prior_restart is not None
            and prior_restart.restart.expected_attempt_epoch == current.attempt_epoch
            and prior_restart.restart.expected_phase
            in {"acquired", "inspecting", "extracted"}
            and current.phase == "classified"
            and current.disposition == "retryable_failure"
        ):
            if current != prior_restart.status:
                raise PackageProductRebindDecisionError(
                    "Package restart has already advanced",
                    code="package_rebind_restart_advanced",
                )
            observed = self._observe(operation_id, max_bytes=max_bytes)
            if (
                observed.source.source_proof_ref
                != prior_restart.restart.source_proof_ref
                or observed.cleanup.known_cleanup_ref
                != prior_restart.restart.cleanup_evidence_ref
                or observed.lease.lease_snapshot_id
                != prior_restart.restart.lease_snapshot_id
                or not self._admission_matches(observed.lease, admission)
            ):
                raise PackageProductRebindDecisionError(
                    "Package restart owner evidence changed on replay",
                    code="package_rebind_restart_evidence_changed",
                )
            return prior_restart

        if current.disposition == "active" and current.phase in {
            "acquired", "inspecting", "extracted"
        }:
            preflight = PackageProductAcquiredRebindPreflightV1(
                source=self._source.observe_acquired_claim(
                    operation_id, max_bytes=max_bytes
                ),
                lease=self._lease.observe_acquired_claim(operation_id),
                cleanup=self._cleanup.observe_acquired_claim(operation_id),
            )
            if not self._admission_matches(preflight.lease, admission):
                raise PackageProductRebindDecisionError(
                    "Root-claim recovery changed current admission",
                    code="package_rebind_decision_admission_changed",
                )
            status = preflight.cleanup.status
            self._lifecycle.interrupt(
                operation_id,
                expected_phase=status.phase,
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
                expected_attempt_revision=status.attempt_revision,
            )

        # Every step after interruption is replayable from the Package and
        # cleanup journals, including a pending tombstone whose physical target
        # was removed before the completion record was appended.
        source = self._source.observe(operation_id, max_bytes=max_bytes)
        lease = self._lease.observe(operation_id)
        interrupted = self._cleanup.observe_interrupted_acquired_attempt(operation_id)
        status = interrupted.status
        if (
            not self._admission_matches(lease, admission)
            or len(
                {
                    (
                        item.operation_id,
                        item.request_fingerprint,
                        item.attempt_epoch,
                        item.attempt_revision,
                    )
                    for item in (source, lease, status)
                }
            )
            != 1
            or source.resolution_evidence_refs
            != interrupted.resolution_evidence_refs
        ):
            raise PackageProductRebindDecisionError(
                "Interrupted root-claim evidence changed",
                code="package_rebind_claim_evidence_changed",
            )
        tombstone = interrupted.tombstone
        if tombstone is None:
            tombstone = self._quarantine_cleanup.record_pending(
                interrupted.target,
                rejection_code="package_rebind_restart",
                rejection_stage=status.phase,
            )
        if tombstone.target != interrupted.target:
            raise PackageProductRebindDecisionError(
                "Package cleanup target changed during recovery",
                code="package_rebind_cleanup_target_changed",
            )
        if tombstone.disposition != "cleanup_complete":
            self._quarantine_cleanup.repair(
                tombstone.target.cleanup_id,
                expected_cleanup_revision=tombstone.cleanup_revision,
            )
        settled_attempt = self._cleanup.observe_interrupted_acquired_attempt(
            operation_id
        )
        if (
            settled_attempt.status != status
            or settled_attempt.target != interrupted.target
            or settled_attempt.tombstone is None
            or settled_attempt.tombstone.disposition != "cleanup_complete"
        ):
            raise PackageProductRebindDecisionError(
                "Package cleanup did not settle the root attempt",
                code="package_rebind_cleanup_not_settled",
            )
        observed = self._observe(operation_id, max_bytes=max_bytes)
        if (
            observed.source.source_proof_ref != source.source_proof_ref
            or observed.lease != lease
            or observed.cleanup.attempt_epoch != status.attempt_epoch
            or interrupted.target.cleanup_id not in observed.cleanup.cleanup_ids
            or not self._admission_matches(observed.lease, admission)
        ):
            raise PackageProductRebindDecisionError(
                "Package recovery evidence changed after cleanup",
                code="package_rebind_claim_evidence_changed",
            )
        restart = PackageLifecycleRestartRequestV1(
            operation_id=operation_id,
            request_fingerprint=status.request_fingerprint,
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
            expected_attempt_revision=status.attempt_revision,
            source_proof_ref=observed.source.source_proof_ref,
            cleanup_evidence_ref=observed.cleanup.known_cleanup_ref,
            lease_snapshot_id=observed.lease.lease_snapshot_id,
        )
        return self._lifecycle.restart_after_cleanup(restart)

    def recover_resolving_claim(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageLifecycleRestartRecordV1:
        """Settle exact selected closure nodes before a fresh classified claim."""

        return self._recover_closure_claim(
            operation_id,
            max_bytes=max_bytes,
            admission=admission,
            phase="resolving_closure",
        )

    def recover_verified_claim(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageLifecycleRestartRecordV1:
        """Settle a complete verified closure before fresh acquisition."""

        return self._recover_closure_claim(
            operation_id,
            max_bytes=max_bytes,
            admission=admission,
            phase="closure_verified",
        )

    def _recover_closure_claim(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
        phase: Literal["resolving_closure", "closure_verified"],
    ) -> PackageLifecycleRestartRecordV1:
        if phase not in {"resolving_closure", "closure_verified"}:
            raise ValueError("Unsupported Package closure recovery phase")

        if not isinstance(admission, PackageEpochRuntimeAdmissionReceiptV1):
            raise TypeError("Current Product admission receipt is required")
        original = self._lifecycle.read_operation(operation_id)
        if original is None:
            raise PackageProductRebindDecisionError(
                "Package operation is absent", code="package_rebind_operation_missing"
            )
        _request, current = original
        prior_restart = self._lifecycle.latest_restart(operation_id)
        if (
            prior_restart is not None
            and prior_restart.restart.expected_attempt_epoch == current.attempt_epoch
            and prior_restart.restart.expected_phase == phase
            and current.phase == "classified"
            and current.disposition == "retryable_failure"
        ):
            if current != prior_restart.status:
                raise PackageProductRebindDecisionError(
                    "Package restart has already advanced",
                    code="package_rebind_restart_advanced",
                )
            observed = self._observe(operation_id, max_bytes=max_bytes)
            if (
                observed.source.source_proof_ref
                != prior_restart.restart.source_proof_ref
                or observed.cleanup.known_cleanup_ref
                != prior_restart.restart.cleanup_evidence_ref
                or observed.lease.lease_snapshot_id
                != prior_restart.restart.lease_snapshot_id
                or not self._admission_matches(observed.lease, admission)
            ):
                raise PackageProductRebindDecisionError(
                    "Package restart owner evidence changed on replay",
                    code="package_rebind_restart_evidence_changed",
                )
            return prior_restart

        preflight: PackageProductResolvingRebindPreflightV1 | None = None
        if current.disposition == "active" and current.phase == phase:
            preflight = PackageProductResolvingRebindPreflightV1(
                source=(
                    self._source.observe_verified_claim(
                        operation_id, max_bytes=max_bytes
                    )
                    if phase == "closure_verified"
                    else self._source.observe_resolving_claim(
                        operation_id, max_bytes=max_bytes
                    )
                ),
                lease=(
                    self._lease.observe_verified_claim(operation_id)
                    if phase == "closure_verified"
                    else self._lease.observe_resolving_claim(operation_id)
                ),
                cleanup=(
                    self._cleanup.observe_verified_claim(operation_id)
                    if phase == "closure_verified"
                    else self._cleanup.observe_resolving_claim(operation_id)
                ),
            )
            if not self._admission_matches(preflight.lease, admission):
                raise PackageProductRebindDecisionError(
                    "Resolving Package recovery changed current admission",
                    code="package_rebind_decision_admission_changed",
                )
            status = preflight.cleanup.status
            self._lifecycle.interrupt(
                operation_id,
                expected_phase=status.phase,
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
                expected_attempt_revision=status.attempt_revision,
            )

        source = self._source.observe(operation_id, max_bytes=max_bytes)
        lease = self._lease.observe(operation_id)
        interrupted_reader = (
            self._cleanup.observe_interrupted_verified_attempt
            if phase == "closure_verified"
            else self._cleanup.observe_interrupted_resolving_attempt
        )
        interrupted = interrupted_reader(operation_id)
        status = interrupted.status
        if (
            not self._admission_matches(lease, admission)
            or len(
                {
                    (
                        item.operation_id,
                        item.request_fingerprint,
                        item.attempt_epoch,
                        item.attempt_revision,
                    )
                    for item in (source, lease, status)
                }
            )
            != 1
            or source.resolution_evidence_refs
            != interrupted.resolution_evidence_refs
            or (
                preflight is not None
                and (
                    source.artifact_digests != preflight.source.artifact_digests
                    or interrupted.artifact_evidence_refs
                    != preflight.cleanup.artifact_evidence_refs
                    or interrupted.resolution_evidence_refs
                    != preflight.cleanup.resolution_evidence_refs
                    or interrupted.store_identity != preflight.cleanup.store_identity
                    or tuple(
                        (
                            node.node.attempt.node_id,
                            node.node.attempt.attempt_identity,
                        )
                        for node in interrupted.nodes
                    )
                    != tuple(
                        (node.attempt.node_id, node.attempt.attempt_identity)
                        for node in preflight.cleanup.nodes
                    )
                )
            )
        ):
            raise PackageProductRebindDecisionError(
                "Interrupted resolving Package evidence changed",
                code="package_rebind_claim_evidence_changed",
            )
        targets = tuple(
            node.target for node in interrupted.nodes if node.target is not None
        )
        for target in targets:
            replay = interrupted_reader(operation_id)
            if (
                replay.status != status
                or replay.artifact_evidence_refs
                != interrupted.artifact_evidence_refs
                or replay.resolution_evidence_refs
                != interrupted.resolution_evidence_refs
            ):
                raise PackageProductRebindDecisionError(
                    "Resolving Package changed during node cleanup",
                    code="package_rebind_claim_evidence_changed",
                )
            matched = tuple(
                node for node in replay.nodes if node.node.attempt.node_id == target.node_id
            )
            if len(matched) != 1 or matched[0].target != target:
                raise PackageProductRebindDecisionError(
                    "Resolving Package cleanup target changed",
                    code="package_rebind_cleanup_target_changed",
                )
            tombstone = matched[0].tombstone
            if tombstone is None:
                tombstone = self._quarantine_cleanup.record_pending(
                    target,
                    rejection_code="package_rebind_restart",
                    rejection_stage=phase,
                )
            if tombstone.target != target:
                raise PackageProductRebindDecisionError(
                    "Resolving Package cleanup tombstone changed target",
                    code="package_rebind_cleanup_target_changed",
                )
            if tombstone.disposition != "cleanup_complete":
                self._quarantine_cleanup.repair(
                    target.cleanup_id,
                    expected_cleanup_revision=tombstone.cleanup_revision,
                )
        settled = interrupted_reader(operation_id)
        if (
            settled.status != status
            or settled.artifact_evidence_refs != interrupted.artifact_evidence_refs
            or settled.resolution_evidence_refs
            != interrupted.resolution_evidence_refs
            or any(node.node.attempt.attempt_identity is not None for node in settled.nodes)
            or any(
                node.target is not None
                and (
                    node.tombstone is None
                    or node.tombstone.disposition != "cleanup_complete"
                )
                for node in settled.nodes
            )
        ):
            raise PackageProductRebindDecisionError(
                "Package cleanup did not settle resolving nodes",
                code="package_rebind_cleanup_not_settled",
            )
        observed = self._observe(operation_id, max_bytes=max_bytes)
        if (
            observed.source.source_proof_ref != source.source_proof_ref
            or observed.lease != lease
            or observed.cleanup.attempt_epoch != status.attempt_epoch
            or observed.cleanup.artifact_evidence_refs
            != interrupted.artifact_evidence_refs
            or observed.cleanup.resolution_evidence_refs
            != interrupted.resolution_evidence_refs
            or not all(
                target.cleanup_id in observed.cleanup.cleanup_ids for target in targets
            )
            or not self._admission_matches(observed.lease, admission)
        ):
            raise PackageProductRebindDecisionError(
                "Resolving Package recovery evidence changed after cleanup",
                code="package_rebind_claim_evidence_changed",
            )
        restart = PackageLifecycleRestartRequestV1(
            operation_id=operation_id,
            request_fingerprint=status.request_fingerprint,
            expected_phase=phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
            expected_attempt_revision=status.attempt_revision,
            source_proof_ref=observed.source.source_proof_ref,
            cleanup_evidence_ref=observed.cleanup.known_cleanup_ref,
            lease_snapshot_id=observed.lease.lease_snapshot_id,
        )
        return self._lifecycle.restart_after_cleanup(restart)

    @staticmethod
    def _admission_matches(
        lease: object, admission: PackageEpochRuntimeAdmissionReceiptV1
    ) -> bool:
        return (
            isinstance(lease, PackageProductRebindLeaseObservationV1)
            and lease.new_admission_request_id
            == admission.request.admission_request_id
            and lease.new_lease_id == admission.request.lease_id
            and lease.store_id == admission.request.store_id
        )

    def route(
        self,
        record: PackageLifecycleRebindRecordV1,
        admission: PackageEpochRuntimeAdmissionReceiptV1,
    ) -> PackageProductReboundRouteRequestV1:
        """Reconstruct the immutable ingress for the selected new admission."""

        if not isinstance(record, PackageLifecycleRebindRecordV1):
            raise TypeError("Selected Package rebind record is required")
        original = self._lifecycle.read_operation(record.decision.operation_id)
        if (
            original is None
            or not isinstance(original[0], PackageLifecycleRequestV2)
            or original[0] != record.request
        ):
            raise PackageProductRebindDecisionError(
                "Original Package ingress changed after rebind",
                code="package_rebind_original_request_changed",
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
        return PackageProductReboundRouteRequestV1(
            entrypoint="operations",
            ingress=ingress,
            admission=admission,
            decision=record.decision,
        )

    def _observe(
        self, operation_id: str, *, max_bytes: int
    ) -> PackageProductRebindPreflightV1:
        return PackageProductRebindPreflightV1(
            source=self._source.observe(operation_id, max_bytes=max_bytes),
            lease=self._lease.observe(operation_id),
            cleanup=self._cleanup.observe(operation_id),
        )

    @staticmethod
    def _matches(
        decision: PackageLifecycleRebindRequestV1,
        observed: PackageProductRebindPreflightV1,
    ) -> bool:
        return (
            decision.request_fingerprint == observed.source.request_fingerprint
            and decision.expected_attempt_epoch == observed.source.attempt_epoch
            and decision.new_runtime_admission_request_id
            == observed.lease.new_admission_request_id
            and decision.source_proof_ref == observed.source.source_proof_ref
            and decision.cleanup_evidence_ref == observed.cleanup.known_cleanup_ref
            and decision.lease_snapshot_id == observed.lease.lease_snapshot_id
        )

    def _postcheck(
        self,
        operation_id: str,
        *,
        max_bytes: int,
        decision: PackageLifecycleRebindRequestV1,
        record: PackageLifecycleRebindRecordV1,
    ) -> None:
        observed = self._observe(operation_id, max_bytes=max_bytes)
        if (
            observed.source.attempt_revision != record.record_revision
            or observed.lease.pending_decision_id != decision.decision_id
            or not self._matches(decision, observed)
            or self._lifecycle.latest_rebind(operation_id) != record
        ):
            raise PackageProductRebindDecisionError(
                "Owner evidence changed after durable rebind decision",
                code="package_rebind_decision_evidence_changed",
            )
