"""Dark PLC9B staging and atomic committed-set lifecycle composition."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    CommittedPackageSetRefV1,
    DependencyClosureLockV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
    PackageCommittedSetJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournalError,
)
from loushang.harness.resources.packages.plugin_lifecycle.owner import (
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleFailureV1,
    PackageLifecyclePhase,
    PackageLifecycleRequestV1,
    PackageLifecycleStatusV1,
    PluginBoundPackageClassificationV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.runtime import (
    PackageClassificationRecheckPort,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingJournal,
    PackageArtifactStagingJournalError,
    PackageArtifactStagingReceiptV1,
    PackageArtifactStagingRequestV1,
    PackageDependencyStagingPort,
    PackagePluginRootStagingPort,
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinJournalError,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
    VerifiedWheelCandidate,
)


class PackageStagingClosurePlanEvidencePort(Protocol):
    """Read-only durable closure plan evidence for current and prior attempts."""

    def plan(
        self,
        *,
        operation_id: str,
        attempt_epoch: int,
    ) -> VerifiedClosurePlanV2 | None: ...


class PackagePluginRootTargetAuthorityPort(Protocol):
    """Issue the logical Plugin-root target without granting store authority."""

    def issue_target(
        self,
        request: PackageLifecycleRequestV1,
        classification: PluginBoundPackageClassificationV1,
    ) -> PackagePluginRootTargetV1: ...


@dataclass(frozen=True, slots=True)
class PackageStagingSetExecutionResult:
    status: PackageLifecycleStatusV1
    staging_receipts: tuple[PackageArtifactStagingReceiptV1, ...] = ()
    committed_set: CommittedPackageSetRefV1 | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, PackageLifecycleStatusV1):
            raise TypeError("Package lifecycle status is required")
        if self.staging_receipts != tuple(
            sorted(self.staging_receipts, key=lambda receipt: receipt.node_id)
        ):
            raise ValueError("Package staging receipts must be canonical")
        if len({receipt.node_id for receipt in self.staging_receipts}) != len(
            self.staging_receipts
        ):
            raise ValueError("Package staging receipt nodes must be unique")
        if any(
            receipt.operation_id != self.status.operation_id
            for receipt in self.staging_receipts
        ):
            raise ValueError("Package staging receipt operation changed")
        if self.committed_set is not None and (
            not isinstance(self.committed_set, CommittedPackageSetRefV1)
            or self.committed_set.operation_id != self.status.operation_id
        ):
            raise ValueError("Committed Package set operation changed")


class PackageStagingSetLifecycleOwner:
    """Stage exact pinned nodes, record one complete set, then advance phase CAS."""

    def __init__(
        self,
        *,
        kernel: PackageLifecycleOwner,
        classification_recheck: PackageClassificationRecheckPort,
        closure_plans: PackageStagingClosurePlanEvidencePort,
        pin_journal: PackageTransactionPinJournal,
        root_targets: PackagePluginRootTargetAuthorityPort,
        dependency_staging: PackageDependencyStagingPort,
        root_staging: PackagePluginRootStagingPort,
        staging_journal: PackageArtifactStagingJournal,
        committed_sets: PackageCommittedSetJournal,
    ) -> None:
        if not isinstance(kernel, PackageLifecycleOwner):
            raise TypeError("Package lifecycle owner is required")
        if not callable(getattr(classification_recheck, "recheck", None)):
            raise TypeError("Package classification recheck port is required")
        if not callable(getattr(closure_plans, "plan", None)):
            raise TypeError("Verified Package closure plan evidence is required")
        if not isinstance(pin_journal, PackageTransactionPinJournal):
            raise TypeError("Package transaction pin journal is required")
        if not callable(getattr(root_targets, "issue_target", None)):
            raise TypeError("Package Plugin root target authority is required")
        if not callable(getattr(dependency_staging, "stage_dependency", None)):
            raise TypeError("Package dependency staging owner is required")
        if not callable(getattr(root_staging, "stage_root", None)):
            raise TypeError("Package Plugin root staging owner is required")
        if not isinstance(staging_journal, PackageArtifactStagingJournal):
            raise TypeError("Package artifact staging journal is required")
        if not isinstance(committed_sets, PackageCommittedSetJournal):
            raise TypeError("Package committed-set journal is required")
        self._kernel = kernel
        self._classification_recheck = classification_recheck
        self._closure_plans = closure_plans
        self._pin_journal = pin_journal
        self._root_targets = root_targets
        self._dependency_staging = dependency_staging
        self._root_staging = root_staging
        self._staging_journal = staging_journal
        self._committed_sets = committed_sets

    def stage_and_publish(
        self,
        candidate: VerifiedPackageClosureCandidate,
    ) -> PackageStagingSetExecutionResult:
        if not isinstance(candidate, VerifiedPackageClosureCandidate):
            raise TypeError("Verified Package closure candidate is required")
        plan = candidate.plan
        status = self._kernel.status(plan.operation_id)
        request = self._kernel.journal.request(plan.operation_id)
        if status is None or request is None:
            candidate.suspend_for_recovery()
            raise PackageLifecycleJournalError(
                "Package operation does not exist",
                code="package_operation_not_found",
                path=self._kernel.journal.path,
            )
        if not self._can_stage(status, plan):
            candidate.suspend_for_recovery()
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if status.phase == "set_published":
            candidate.suspend_for_recovery()
            return self.recover(status.operation_id)
        durable_plan = self._plan(status.operation_id, status.attempt_epoch)
        if durable_plan != plan or not self._live_candidates_match(candidate, plan):
            candidate.suspend_for_recovery()
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        pin = self._current_pin(status, plan)
        if pin is None:
            candidate.suspend_for_recovery()
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        assert status.classification is not None
        target = self._root_targets.issue_target(request, status.classification)
        if not self._target_matches(target, request, status):
            candidate.suspend_for_recovery()
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        candidates = {item.evidence.node_id: item for item in candidate.candidates}
        receipts: list[PackageArtifactStagingReceiptV1] = []
        try:
            stage_order = tuple(
                node for node in plan.nodes if node.role == "dependency"
            )
            stage_order += tuple(node for node in plan.nodes if node.role == "root")
            for node in stage_order:
                existing = self._staging_journal.current(
                    operation_id=plan.operation_id,
                    node_id=node.node_id,
                )
                if existing is not None:
                    if not self._receipt_covers_current_plan(
                        existing,
                        plan=plan,
                        pin=pin,
                        target=target,
                    ):
                        candidate.suspend_for_recovery()
                        return PackageStagingSetExecutionResult(
                            status=_local_refusal(
                                status,
                                code="package_operation_identity_conflict",
                            )
                        )
                    receipts.append(existing)
                    continue
                staging_request = PackageArtifactStagingRequestV1.create(
                    plan,
                    node_id=node.node_id,
                    request_fingerprint=status.request_fingerprint,
                    classification_fingerprint=status.classification.evidence_ref,
                    pin_receipt=pin,
                    root_target=target if node.role == "root" else None,
                )
                if node.role == "root":
                    receipt = self._root_staging.stage_root(
                        staging_request,
                        candidates[node.node_id],
                    )
                else:
                    receipt = self._dependency_staging.stage_dependency(
                        staging_request,
                        candidates[node.node_id],
                    )
                if (
                    not isinstance(receipt, PackageArtifactStagingReceiptV1)
                    or receipt.staging_request != staging_request
                ):
                    candidate.suspend_for_recovery()
                    return PackageStagingSetExecutionResult(
                        status=_local_refusal(
                            status,
                            code="package_operation_identity_conflict",
                        )
                    )
                receipts.append(self._staging_journal.append(receipt))
        except PackageArtifactStagingJournalError:
            candidate.suspend_for_recovery()
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        except Exception:
            candidate.suspend_for_recovery()
            raise
        candidate.suspend_for_recovery()
        canonical = tuple(sorted(receipts, key=lambda receipt: receipt.node_id))
        if status.phase == "transaction_pinned":
            status = self._advance_exact(
                status,
                next_phase="staging",
                expected_phase="transaction_pinned",
            )
        if status.disposition != "active" or status.phase != "staging":
            return PackageStagingSetExecutionResult(
                status=status,
                staging_receipts=canonical,
            )
        return self._publish_from_evidence(
            status=status,
            request=request,
            plan=plan,
            target=target,
            receipts=canonical,
        )

    def resume(self, operation_id: str) -> PackageStagingSetExecutionResult:
        """Finish after every staging receipt is durable, without live candidates."""

        status = self._kernel.status(operation_id)
        request = self._kernel.journal.request(operation_id)
        if status is None or request is None:
            raise PackageLifecycleJournalError(
                "Package operation does not exist",
                code="package_operation_not_found",
                path=self._kernel.journal.path,
            )
        if (
            status.disposition != "active"
            or status.phase not in {"transaction_pinned", "staging", "set_published"}
            or status.classification is None
            or status.classification.decision != "plugin_bound"
        ):
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        if status.phase == "set_published":
            return self.recover(operation_id)
        plan = self._plan(operation_id, status.attempt_epoch)
        if plan is None:
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        pin = self._current_pin(status, plan)
        context = self._durable_staging_context(status, plan, pin)
        if context is None:
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        target, receipts = context
        if status.phase == "transaction_pinned":
            status = self._advance_exact(
                status,
                next_phase="staging",
                expected_phase="transaction_pinned",
            )
        if status.disposition != "active" or status.phase != "staging":
            return PackageStagingSetExecutionResult(
                status=status,
                staging_receipts=receipts,
            )
        return self._publish_from_evidence(
            status=status,
            request=request,
            plan=plan,
            target=target,
            receipts=receipts,
        )

    def recover(self, operation_id: str) -> PackageStagingSetExecutionResult:
        """Read and revalidate staging/set evidence without repeating effects."""

        status = self._kernel.status(operation_id)
        if status is None:
            raise PackageLifecycleJournalError(
                "Package operation does not exist",
                code="package_operation_not_found",
                path=self._kernel.journal.path,
            )
        if (
            status.phase not in {"staging", "set_published"}
            or status.disposition not in {"active", "retryable_failure"}
            or status.classification is None
            or status.classification.decision != "plugin_bound"
            or status.classification.request_fingerprint != status.request_fingerprint
        ):
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        plan = self._plan(operation_id, status.attempt_epoch)
        if plan is None:
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        pin = self._current_pin(status, plan)
        context = self._durable_staging_context(status, plan, pin)
        if context is None:
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
        target, receipts = context
        committed = self._committed_sets.current(operation_id)
        if committed is None:
            if status.phase == "set_published":
                return PackageStagingSetExecutionResult(
                    status=_local_refusal(
                        status,
                        code="package_operation_identity_conflict",
                    ),
                    staging_receipts=receipts,
                )
            return PackageStagingSetExecutionResult(
                status=status,
                staging_receipts=receipts,
            )
        expected_lock = DependencyClosureLockV2.create(
            plan,
            stable_refs={receipt.node_id: receipt.stable_ref for receipt in receipts},
        )
        expected_set = CommittedPackageSetRefV1.create(
            expected_lock,
            request_fingerprint=status.request_fingerprint,
            product_id=target.product_id,
            scope_id=target.scope_id,
            installation_id=target.installation_id,
            plugin_id=target.plugin_id,
            classification_fingerprint=status.classification.evidence_ref,
            commit_revision=committed.record_revision,
        )
        if (
            committed.closure_lock != expected_lock
            or committed.committed_set != expected_set
        ):
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                ),
                staging_receipts=receipts,
            )
        return PackageStagingSetExecutionResult(
            status=status,
            staging_receipts=receipts,
            committed_set=committed.committed_set,
        )

    def _publish_from_evidence(
        self,
        *,
        status: PackageLifecycleStatusV1,
        request: PackageLifecycleRequestV1,
        plan: VerifiedClosurePlanV2,
        target: PackagePluginRootTargetV1,
        receipts: tuple[PackageArtifactStagingReceiptV1, ...],
    ) -> PackageStagingSetExecutionResult:
        assert status.classification is not None
        fresh = self._classification_recheck.recheck(request, status.classification)
        if not isinstance(fresh, PluginBoundPackageClassificationV1):
            raise TypeError("Classification recheck returned invalid evidence")
        if fresh != status.classification:
            failure = PackageLifecycleFailureV1.for_operation(
                "package_target_classification_changed",
                stage="staging",
                operation_id=status.operation_id,
                evidence_ref=fresh.evidence_ref,
            )
            changed = self._kernel.record_failure(
                failure,
                expected_phase="staging",
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
            return PackageStagingSetExecutionResult(
                status=changed,
                staging_receipts=receipts,
            )
        closure_lock = DependencyClosureLockV2.create(
            plan,
            stable_refs={receipt.node_id: receipt.stable_ref for receipt in receipts},
        )
        try:
            committed = self._committed_sets.publish(
                closure_lock,
                request_fingerprint=status.request_fingerprint,
                product_id=target.product_id,
                scope_id=target.scope_id,
                installation_id=target.installation_id,
                plugin_id=target.plugin_id,
                classification_fingerprint=status.classification.evidence_ref,
            )
        except PackageCommittedSetJournalError:
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                ),
                staging_receipts=receipts,
            )
        published = self._advance_exact(
            status,
            next_phase="set_published",
            expected_phase="staging",
        )
        return PackageStagingSetExecutionResult(
            status=published,
            staging_receipts=receipts,
            committed_set=committed,
        )

    def _advance_exact(
        self,
        status: PackageLifecycleStatusV1,
        *,
        next_phase: PackageLifecyclePhase,
        expected_phase: PackageLifecyclePhase,
    ) -> PackageLifecycleStatusV1:
        try:
            return self._kernel.advance(
                status.operation_id,
                next_phase=next_phase,
                expected_phase=expected_phase,
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
        except PackageLifecycleJournalError:
            current = self._kernel.status(status.operation_id)
            if current is None:
                raise
            if (
                current.disposition == "active"
                and current.phase == next_phase
                and current.attempt_epoch == status.attempt_epoch
            ):
                return current
            return current

    def _durable_staging_context(
        self,
        status: PackageLifecycleStatusV1,
        plan: VerifiedClosurePlanV2,
        pin: PackageTransactionPinReceiptV1 | None,
    ) -> (
        tuple[
            PackagePluginRootTargetV1,
            tuple[PackageArtifactStagingReceiptV1, ...],
        ]
        | None
    ):
        if pin is None:
            return None
        receipts = self._staging_journal.receipts(plan.operation_id)
        if {receipt.node_id for receipt in receipts} != {
            node.node_id for node in plan.nodes
        }:
            return None
        root_receipts = tuple(
            receipt
            for receipt in receipts
            if receipt.staging_request.plan_node.role == "root"
        )
        if len(root_receipts) != 1:
            return None
        target = root_receipts[0].staging_request.root_target
        if target is None:
            return None
        request = self._kernel.journal.request(status.operation_id)
        if request is None or not self._target_matches(target, request, status):
            return None
        if not all(
            self._receipt_covers_current_plan(
                receipt,
                plan=plan,
                pin=pin,
                target=target,
            )
            for receipt in receipts
        ):
            return None
        return target, receipts

    def _receipt_covers_current_plan(
        self,
        receipt: PackageArtifactStagingReceiptV1,
        *,
        plan: VerifiedClosurePlanV2,
        pin: PackageTransactionPinReceiptV1,
        target: PackagePluginRootTargetV1,
    ) -> bool:
        request = receipt.staging_request
        if (
            request.operation_id != plan.operation_id
            or request.attempt_epoch > plan.attempt_epoch
            or request.request_fingerprint != target.request_fingerprint
            or request.prepublication_graph_digest != plan.graph_digest
            or request.pin_receipt_id != pin.receipt_id
            or request.recovery_identity != pin.pin_request.recovery_identity
        ):
            return False
        current_node = next(
            (node for node in plan.nodes if node.node_id == request.node_id),
            None,
        )
        if current_node is None or current_node != request.plan_node:
            return False
        prior = self._plan(plan.operation_id, request.attempt_epoch)
        if prior is None or prior.graph_digest != plan.graph_digest:
            return False
        try:
            expected = PackageArtifactStagingRequestV1.create(
                prior,
                node_id=request.node_id,
                request_fingerprint=request.request_fingerprint,
                classification_fingerprint=request.classification_fingerprint,
                pin_receipt=pin,
                root_target=target if request.plan_node.role == "root" else None,
            )
        except (TypeError, ValueError):
            return False
        return expected == request

    def _current_pin(
        self,
        status: PackageLifecycleStatusV1,
        plan: VerifiedClosurePlanV2,
    ) -> PackageTransactionPinReceiptV1 | None:
        try:
            receipt = self._pin_journal.current_for_operation(status.operation_id)
        except PackageTransactionPinJournalError:
            return None
        if (
            receipt is None
            or receipt.state != "acquired"
            or status.classification is None
        ):
            return None
        current = PackageTransactionPinRequestV1.create(
            plan,
            request_fingerprint=status.request_fingerprint,
            classification_fingerprint=status.classification.evidence_ref,
            recovery_identity=receipt.pin_request.recovery_identity,
        )
        acquired = receipt.pin_request
        if (
            acquired.operation_id != current.operation_id
            or acquired.attempt_epoch > current.attempt_epoch
            or acquired.request_fingerprint != current.request_fingerprint
            or acquired.classification_fingerprint != current.classification_fingerprint
            or acquired.prepublication_graph_digest
            != current.prepublication_graph_digest
            or acquired.recovery_identity != current.recovery_identity
            or acquired.root_target_id != current.root_target_id
            or acquired.targets != current.targets
            or acquired.pin_kind != current.pin_kind
        ):
            return None
        prior = self._plan(acquired.operation_id, acquired.attempt_epoch)
        if prior is None:
            return None
        expected = PackageTransactionPinRequestV1.create(
            prior,
            request_fingerprint=acquired.request_fingerprint,
            classification_fingerprint=acquired.classification_fingerprint,
            recovery_identity=acquired.recovery_identity,
        )
        return receipt if expected == acquired else None

    def _plan(
        self,
        operation_id: str,
        attempt_epoch: int,
    ) -> VerifiedClosurePlanV2 | None:
        try:
            plan = self._closure_plans.plan(
                operation_id=operation_id,
                attempt_epoch=attempt_epoch,
            )
        except Exception:
            return None
        return plan if isinstance(plan, VerifiedClosurePlanV2) else None

    @staticmethod
    def _target_matches(
        target: object,
        request: PackageLifecycleRequestV1,
        status: PackageLifecycleStatusV1,
    ) -> bool:
        return bool(
            isinstance(target, PackagePluginRootTargetV1)
            and target.operation_id == status.operation_id
            and target.request_fingerprint == status.request_fingerprint
            and target.product_id == request.product_id
            and target.scope_id == request.scope_id
            and (
                request.requested_plugin_id is None
                or target.plugin_id == request.requested_plugin_id
            )
        )

    @staticmethod
    def _can_stage(
        status: PackageLifecycleStatusV1,
        plan: VerifiedClosurePlanV2,
    ) -> bool:
        return bool(
            status.disposition == "active"
            and status.phase in {"transaction_pinned", "staging", "set_published"}
            and status.attempt_epoch == plan.attempt_epoch
            and status.classification is not None
            and status.classification.decision == "plugin_bound"
            and status.classification.request_fingerprint == status.request_fingerprint
        )

    @staticmethod
    def _live_candidates_match(
        candidate: VerifiedPackageClosureCandidate,
        plan: VerifiedClosurePlanV2,
    ) -> bool:
        if len(candidate.candidates) != len(plan.nodes) or not all(
            isinstance(item, VerifiedWheelCandidate)
            and isinstance(item.evidence, VerifiedWheelArtifactV1)
            for item in candidate.candidates
        ):
            return False
        by_node = {item.evidence.node_id: item for item in candidate.candidates}
        if len(by_node) != len(candidate.candidates):
            return False
        return all(
            _candidate_matches_node(by_node.get(node.node_id), node, plan)
            for node in plan.nodes
        )


def _candidate_matches_node(
    candidate: VerifiedWheelCandidate | None,
    node: VerifiedClosurePlanNodeV2,
    plan: VerifiedClosurePlanV2,
) -> bool:
    if candidate is None:
        return False
    envelope = candidate.authenticated_envelope
    acquisition = candidate.acquisition_receipt
    wheel = candidate.evidence
    if (
        not isinstance(envelope, AuthenticatedSourceEnvelopeV1)
        or not isinstance(acquisition, BoundedAcquisitionReceiptV1)
        or not isinstance(wheel, VerifiedWheelArtifactV1)
    ):
        return False
    return bool(
        wheel.operation_id == plan.operation_id
        and wheel.attempt_epoch == plan.attempt_epoch
        and wheel.node_id == node.node_id
        and wheel.distribution == node.distribution
        and wheel.version == node.version
        and wheel.artifact_digest == node.artifact_digest
        and wheel.extraction_tree_digest == node.extraction_tree_digest
        and wheel.fingerprint == node.wheel_evidence_fingerprint
        and acquisition.operation_id == plan.operation_id
        and acquisition.attempt_epoch == plan.attempt_epoch
        and acquisition.node_id == node.node_id
        and acquisition.fingerprint == node.acquisition_receipt_fingerprint
        and envelope.operation_id == plan.operation_id
        and envelope.node_id == node.node_id
        and envelope.canonical_source_identity == node.canonical_source_identity
        and envelope.fingerprint == node.source_envelope_fingerprint
    )


def _local_refusal(
    status: PackageLifecycleStatusV1,
    *,
    code: str,
) -> PackageLifecycleStatusV1:
    evidence_ref = sha256(
        canonical_json_bytes(
            {
                "attemptEpoch": status.attempt_epoch,
                "code": code,
                "operationId": status.operation_id,
                "requestFingerprint": status.request_fingerprint,
                "stage": status.phase,
            }
        )
    ).hexdigest()
    failure = PackageLifecycleFailureV1.for_operation(
        code,
        stage=cast(PackageLifecyclePhase, status.phase),
        operation_id=status.operation_id,
        evidence_ref=evidence_ref,
    )
    return PackageLifecycleStatusV1(
        operation_id=status.operation_id,
        request_fingerprint=status.request_fingerprint,
        phase=status.phase,
        disposition="rejected",
        attempt_epoch=status.attempt_epoch,
        journal_revision=status.journal_revision,
        attempt_revision=status.attempt_revision,
        classification=status.classification,
        failure=failure,
    )


__all__ = [
    "PackagePluginRootTargetAuthorityPort",
    "PackageStagingClosurePlanEvidencePort",
    "PackageStagingSetExecutionResult",
    "PackageStagingSetLifecycleOwner",
]
