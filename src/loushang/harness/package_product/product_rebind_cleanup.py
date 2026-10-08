"""Strict Product observation of old A2 quarantine and cleanup facts.

The result is momentary, not a durable cleanup certificate. It accounts for
every direct Store entry and must be rechecked under an admitted mutation guard.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    BoundedAcquisitionReceiptV1,
    PackageQuarantineAttemptObservationV1,
    PackageQuarantineCleanupTargetV1,
    PackageQuarantineStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupOwner,
    PackageQuarantineCleanupStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionBasisV1,
    PackageClosureResolutionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencySelectionV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
    PackageCommittedSetRecordV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
    PackageAuthenticatedSourceEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV2,
    PackageLifecycleStatusV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageRetentionHandoffJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
    PackageTransactionPinTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
)


class PackageProductRebindCleanupReadError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageProductRebindCleanupObservationV1:
    operation_id: str
    request_fingerprint: str
    attempt_epoch: int
    attempt_revision: int
    known_attempts: tuple[PackageQuarantineAttemptObservationV1, ...]
    store_identity: tuple[int, int]
    committed_attempts: tuple[PackageQuarantineAttemptObservationV1, ...]
    artifact_evidence_refs: tuple[str, ...]
    resolution_evidence_refs: tuple[str, ...]
    cleanup_ids: tuple[str, ...]
    known_cleanup_ref: str


@dataclass(frozen=True, slots=True)
class PackageProductAcquiredCleanupObservationV1:
    """Read-only physical and durable proof before root-claim cleanup."""

    status: PackageLifecycleStatusV1
    root_attempt: PackageQuarantineAttemptObservationV1
    acquisition_receipt: BoundedAcquisitionReceiptV1
    artifact_evidence_refs: tuple[str, ...]
    resolution_evidence_refs: tuple[str, ...]
    store_identity: tuple[int, int]
    committed_attempts: tuple[PackageQuarantineAttemptObservationV1, ...]


@dataclass(frozen=True, slots=True)
class PackageProductInterruptedAcquiredCleanupObservationV1:
    """Exact cleanup target and replay state for one interrupted root claim."""

    status: PackageLifecycleStatusV1
    target: PackageQuarantineCleanupTargetV1
    tombstone: PackageQuarantineCleanupStatusV1 | None
    root_attempt: PackageQuarantineAttemptObservationV1
    acquisition_receipt: BoundedAcquisitionReceiptV1
    artifact_evidence_refs: tuple[str, ...]
    resolution_evidence_refs: tuple[str, ...]
    store_identity: tuple[int, int]
    committed_attempts: tuple[PackageQuarantineAttemptObservationV1, ...]


@dataclass(frozen=True, slots=True)
class PackageProductResolvingNodeObservationV1:
    """One selected closure node and its bounded durable evidence prefix."""

    attempt: PackageQuarantineAttemptObservationV1
    source_recorded: bool
    acquisition_receipt: BoundedAcquisitionReceiptV1 | None
    verified_recorded: bool


@dataclass(frozen=True, slots=True)
class PackageProductResolvingCleanupObservationV1:
    """Read-only complete Store and journal account during closure resolution."""

    status: PackageLifecycleStatusV1
    nodes: tuple[PackageProductResolvingNodeObservationV1, ...]
    artifact_evidence_refs: tuple[str, ...]
    resolution_evidence_refs: tuple[str, ...]
    store_identity: tuple[int, int]
    committed_attempts: tuple[PackageQuarantineAttemptObservationV1, ...]
    tombstones: tuple[PackageQuarantineCleanupStatusV1, ...]


@dataclass(frozen=True, slots=True)
class PackageProductPinnedCleanupObservationV1:
    """Exact acquired retention pin with an unmodified verified closure."""

    closure: PackageProductResolvingCleanupObservationV1
    pin: PackageTransactionPinReceiptV1


@dataclass(frozen=True, slots=True)
class PackageProductInterruptedResolvingNodeObservationV1:
    """One exact cleanup target or an untouched selected node."""

    node: PackageProductResolvingNodeObservationV1
    target: PackageQuarantineCleanupTargetV1 | None
    tombstone: PackageQuarantineCleanupStatusV1 | None


@dataclass(frozen=True, slots=True)
class PackageProductInterruptedResolvingCleanupObservationV1:
    """Replayable node targets after a selected closure interruption."""

    status: PackageLifecycleStatusV1
    nodes: tuple[PackageProductInterruptedResolvingNodeObservationV1, ...]
    artifact_evidence_refs: tuple[str, ...]
    resolution_evidence_refs: tuple[str, ...]
    store_identity: tuple[int, int]
    committed_attempts: tuple[PackageQuarantineAttemptObservationV1, ...]


class PackageProductRebindCleanupReader:
    """Join strict owner journals to physical slots of known old attempts."""

    def __init__(
        self,
        *,
        lifecycle: PackageLifecycleJournal,
        resolution: PackageClosureResolutionJournal,
        artifacts: PackageArtifactEvidenceJournal,
        cleanup: PackageQuarantineCleanupOwner,
        quarantine: PackageQuarantineStore,
        pins: PackageTransactionPinJournal,
        staging: PackageArtifactStagingJournal,
        committed_sets: PackageCommittedSetJournal,
        handoff: PackageRetentionHandoffJournal,
        pin_recovery_identity: str | None = None,
    ) -> None:
        if not isinstance(lifecycle, PackageLifecycleJournal):
            raise TypeError("Package lifecycle journal is required")
        if not isinstance(resolution, PackageClosureResolutionJournal):
            raise TypeError("Package resolution journal is required")
        if not isinstance(artifacts, PackageArtifactEvidenceJournal):
            raise TypeError("Package artifact evidence journal is required")
        if not isinstance(cleanup, PackageQuarantineCleanupOwner):
            raise TypeError("Package cleanup owner is required")
        if not isinstance(quarantine, PackageQuarantineStore):
            raise TypeError("Package quarantine Store is required")
        if not isinstance(pins, PackageTransactionPinJournal):
            raise TypeError("Package transaction pin journal is required")
        if not isinstance(staging, PackageArtifactStagingJournal):
            raise TypeError("Package staging journal is required")
        if not isinstance(committed_sets, PackageCommittedSetJournal):
            raise TypeError("Package committed set journal is required")
        if not isinstance(handoff, PackageRetentionHandoffJournal):
            raise TypeError("Package retention handoff journal is required")
        self._lifecycle = lifecycle
        self._resolution = resolution
        self._artifacts = artifacts
        self._cleanup = cleanup
        self._quarantine = quarantine
        self._pins = pins
        self._staging = staging
        self._committed_sets = committed_sets
        self._handoff = handoff
        self._pin_recovery_identity = pin_recovery_identity

    def observe(self, operation_id: str) -> PackageProductRebindCleanupObservationV1:
        original = self._lifecycle.read_operation(operation_id)
        if original is None:
            raise PackageProductRebindCleanupReadError(
                "Package operation is absent", code="package_rebind_operation_missing"
            )
        request, status = original
        if (
            not isinstance(request, PackageLifecycleRequestV2)
            or status.disposition != "retryable_failure"
            or status.failure is None
            or status.failure.operator_action != "retry"
            or status.classification is None
            or status.classification.decision != "plugin_bound"
        ):
            raise PackageProductRebindCleanupReadError(
                "Package operation has no failed Plugin attempt",
                code="package_rebind_attempt_not_retryable",
            )
        self._require_no_later_effects(operation_id, status.attempt_epoch)
        resolution = self._resolution.read_attempt_evidence(
            operation_id=operation_id, attempt_epoch=status.attempt_epoch
        )
        artifacts = self._artifacts.read_attempt_evidence(
            operation_id=operation_id, attempt_epoch=status.attempt_epoch
        )
        tombstones = self._cleanup.read_operation_tombstones(operation_id)
        if any(
            record.request_fingerprint != status.request_fingerprint
            for record in resolution
        ) or any(
            record.request_fingerprint != status.request_fingerprint
            for record in artifacts
        ):
            raise PackageProductRebindCleanupReadError(
                "Old Package evidence changed request",
                code="package_rebind_cleanup_evidence_changed",
            )
        nodes = {"root"}
        nodes.update(record.node_id for record in artifacts)
        for record in resolution:
            evidence = record.evidence
            if isinstance(evidence, PackageDependencySelectionV1):
                nodes.add(evidence.node_id)
            elif isinstance(evidence, VerifiedClosurePlanV2):
                nodes.update(node.node_id for node in evidence.nodes)
        nodes.update(
            item.target.node_id
            for item in tombstones
            if item.target.attempt_epoch == status.attempt_epoch
        )
        current = self._quarantine.observe_attempts(
            operation_id,
            status.attempt_epoch,
            tuple(sorted(nodes)),
            removed_identities=tuple(
                item.target.attempt_identity
                for item in tombstones
                if item.target.attempt_epoch == status.attempt_epoch
                and item.disposition == "cleanup_complete"
            ),
        )
        earlier = tuple(
            observation
            for epoch in sorted(
                {item.target.attempt_epoch for item in tombstones}
                - {status.attempt_epoch}
            )
            for observation in self._quarantine.observe_attempts(
                operation_id,
                epoch,
                tuple(
                    sorted(
                        {
                            item.target.node_id
                            for item in tombstones
                            if item.target.attempt_epoch == epoch
                        }
                    )
                ),
                removed_identities=tuple(
                    item.target.attempt_identity
                    for item in tombstones
                    if item.target.attempt_epoch == epoch
                    and item.disposition == "cleanup_complete"
                ),
            )
        )
        observed = (*earlier, *current)
        observed_by_key = {
            (item.attempt_epoch, item.node_id): item for item in observed
        }
        for item in tombstones:
            slot = observed_by_key.get((item.target.attempt_epoch, item.target.node_id))
            if (
                item.target.attempt_epoch > status.attempt_epoch
                or slot is None
                or item.target.attempt_name != slot.attempt_name
                or item.target.store_identity != slot.store_identity
            ):
                raise PackageProductRebindCleanupReadError(
                    "Old Package cleanup target changed Store or attempt slot",
                    code="package_rebind_cleanup_target_changed",
                )
        if any(item.disposition != "cleanup_complete" for item in tombstones):
            raise PackageProductRebindCleanupReadError(
                "Old Package cleanup debt is pending",
                code="package_rebind_cleanup_pending",
            )
        if any(item.attempt_identity is not None for item in observed):
            raise PackageProductRebindCleanupReadError(
                "Known old Package quarantine attempt remains",
                code="package_rebind_quarantine_residue",
            )
        committed_attempts, store_identity = self._observe_committed_store(operation_id)
        artifact_refs = tuple(record.evidence_ref for record in artifacts)
        resolution_refs = tuple(record.evidence_ref for record in resolution)
        cleanup_ids = tuple(item.target.cleanup_id for item in tombstones)
        known_cleanup_ref = sha256(
            canonical_json_bytes(
                {
                    "artifactEvidenceRefs": list(artifact_refs),
                    "attemptEpoch": status.attempt_epoch,
                    # Decision records advance attempt_revision; the failed
                    # operation revision remains the evidence anchor.
                    "failedOperationRevision": status.journal_revision,
                    "cleanupStatuses": [
                        {
                            "cleanupId": item.target.cleanup_id,
                            "cleanupRevision": item.cleanup_revision,
                            "disposition": item.disposition,
                        }
                        for item in tombstones
                    ],
                    "knownAttempts": [
                        {
                            "attemptEpoch": item.attempt_epoch,
                            "attemptName": item.attempt_name,
                            "nodeId": item.node_id,
                            "storeIdentity": list(item.store_identity),
                        }
                        for item in observed
                    ],
                    "storeIdentity": list(store_identity),
                    "committedAttempts": [
                        {
                            "attemptIdentity": list(item.attempt_identity),
                            "attemptName": item.attempt_name,
                            "operationId": item.operation_id,
                        }
                        for item in committed_attempts
                        if item.attempt_identity is not None
                    ],
                    "operationId": operation_id,
                    "requestFingerprint": status.request_fingerprint,
                    "resolutionEvidenceRefs": list(resolution_refs),
                    "version": 1,
                }
            )
        ).hexdigest()
        return PackageProductRebindCleanupObservationV1(
            operation_id=operation_id,
            request_fingerprint=status.request_fingerprint,
            attempt_epoch=status.attempt_epoch,
            attempt_revision=status.attempt_revision,
            known_attempts=observed,
            store_identity=store_identity,
            committed_attempts=committed_attempts,
            artifact_evidence_refs=artifact_refs,
            resolution_evidence_refs=resolution_refs,
            cleanup_ids=cleanup_ids,
            known_cleanup_ref=known_cleanup_ref,
        )

    def prove_unstarted_attempt(self, operation_id: str) -> PackageLifecycleStatusV1:
        """Prove one active claim has no Product artifact or Store effects."""

        original = self._lifecycle.read_operation(operation_id)
        if original is None:
            raise PackageProductRebindCleanupReadError(
                "Package operation is absent", code="package_rebind_operation_missing"
            )
        request, status = original
        if (
            not isinstance(request, PackageLifecycleRequestV2)
            or status.disposition != "active"
            or status.phase not in {"classified", "acquiring"}
            or status.classification is None
            or status.classification.decision != "plugin_bound"
        ):
            raise PackageProductRebindCleanupReadError(
                "Claimed Package attempt has advanced beyond safe interruption",
                code="package_rebind_claim_not_unstarted",
            )
        self._require_no_later_effects(operation_id, status.attempt_epoch)
        if self._resolution.read_attempt_evidence(
            operation_id=operation_id, attempt_epoch=status.attempt_epoch
        ) or self._artifacts.read_attempt_evidence(
            operation_id=operation_id, attempt_epoch=status.attempt_epoch
        ):
            raise PackageProductRebindCleanupReadError(
                "Claimed Package attempt already has artifact or resolution evidence",
                code="package_rebind_claim_has_effects",
            )
        tombstones = self._cleanup.read_operation_tombstones(operation_id)
        if any(
            item.disposition != "cleanup_complete"
            or item.target.attempt_epoch >= status.attempt_epoch
            for item in tombstones
        ):
            raise PackageProductRebindCleanupReadError(
                "Claimed Package attempt has cleanup debt or effects",
                code="package_rebind_claim_has_effects",
            )
        current = self._quarantine.observe_attempts(
            operation_id, status.attempt_epoch, ("root",)
        )
        if any(item.attempt_identity is not None for item in current):
            raise PackageProductRebindCleanupReadError(
                "Claimed Package quarantine attempt remains",
                code="package_rebind_claim_has_effects",
            )
        self._observe_committed_store(operation_id)
        return status

    def observe_acquired_claim(
        self, operation_id: str
    ) -> PackageProductAcquiredCleanupObservationV1:
        """Prove one selected root-stage claim and its physical root."""

        status = self._selected_acquired_status(
            operation_id, disposition="active"
        )
        receipt, artifact_refs, resolution_refs = self._acquired_evidence(status)
        tombstones = self._cleanup.read_operation_tombstones(operation_id)
        if any(item.disposition != "cleanup_complete" for item in tombstones) or any(
            item.target.attempt_epoch == status.attempt_epoch for item in tombstones
        ):
            raise PackageProductRebindCleanupReadError(
                "Package root claim has cleanup history requiring replay",
                code="package_rebind_cleanup_pending",
            )
        [root] = self._quarantine.observe_attempts(
            operation_id, status.attempt_epoch, ("root",)
        )
        try:
            self._quarantine.prove_acquisition_sink(root, receipt)
        except OSError as exc:
            raise PackageProductRebindCleanupReadError(
                "Package acquired root changed its physical sink",
                code="package_rebind_acquired_sink_changed",
            ) from exc
        committed, store_identity = self._observe_committed_store(
            operation_id, additional_attempts=(root,)
        )
        return PackageProductAcquiredCleanupObservationV1(
            status=status,
            root_attempt=root,
            acquisition_receipt=receipt,
            artifact_evidence_refs=artifact_refs,
            resolution_evidence_refs=resolution_refs,
            store_identity=store_identity,
            committed_attempts=committed,
        )

    def observe_resolving_claim(
        self, operation_id: str
    ) -> PackageProductResolvingCleanupObservationV1:
        """Account for every selected dependency prefix and physical slot."""

        return self._observe_resolving_attempt(
            operation_id, disposition="active", phase="resolving_closure"
        )

    def observe_verified_claim(
        self, operation_id: str
    ) -> PackageProductResolvingCleanupObservationV1:
        """Require an exact verified plan before clearing closure nodes."""

        return self._observe_resolving_attempt(
            operation_id, disposition="active", phase="closure_verified"
        )

    def observe_pinned_claim(
        self, operation_id: str
    ) -> PackageProductPinnedCleanupObservationV1:
        """Read the retained graph without authorizing its release or cleanup."""

        closure = self._observe_resolving_attempt(
            operation_id, disposition="active", phase="transaction_pinned"
        )
        plan = self._resolution.read_plan(
            operation_id=operation_id,
            attempt_epoch=closure.status.attempt_epoch,
        )
        if plan is None:
            raise PackageProductRebindCleanupReadError(
                "Pinned Package has no verified closure plan",
                code="package_rebind_pin_evidence_changed",
            )
        pin = self._retained_pin(closure.status, plan)
        return PackageProductPinnedCleanupObservationV1(closure=closure, pin=pin)

    def _retained_pin(
        self, status: PackageLifecycleStatusV1, plan: VerifiedClosurePlanV2
    ) -> PackageTransactionPinReceiptV1:
        records = self._pins.read_operation_records(status.operation_id)
        if len(records) != 1:
            raise PackageProductRebindCleanupReadError(
                "Pinned Package has no exact acquired retention record",
                code="package_rebind_pin_evidence_changed",
            )
        pin = records[0].receipt
        request = pin.pin_request
        original_plan = self._resolution.read_plan(
            operation_id=status.operation_id, attempt_epoch=request.attempt_epoch
        )
        if (
            pin.state != "acquired"
            or self._pin_recovery_identity is None
            or request.recovery_identity != self._pin_recovery_identity
            or original_plan is None
            or status.classification is None
            or request.attempt_epoch > status.attempt_epoch
            or request.request_fingerprint != status.request_fingerprint
            or request.classification_fingerprint
            != status.classification.evidence_ref
            or request.prepublication_graph_digest != plan.graph_digest
            or request.root_target_id
            != PackageTransactionPinTargetV1.from_plan_node(
                next(node for node in plan.nodes if node.node_id == plan.root_node_id)
            ).target_id
            or request.targets
            != tuple(
                PackageTransactionPinTargetV1.from_plan_node(node)
                for node in plan.nodes
            )
            or request
            != PackageTransactionPinRequestV1.create(
                original_plan,
                request_fingerprint=status.request_fingerprint,
                classification_fingerprint=status.classification.evidence_ref,
                recovery_identity=request.recovery_identity,
            )
        ):
            raise PackageProductRebindCleanupReadError(
                "Pinned Package retention changed verified closure",
                code="package_rebind_pin_evidence_changed",
            )
        return pin

    def observe_interrupted_resolving_attempt(
        self, operation_id: str
    ) -> PackageProductInterruptedResolvingCleanupObservationV1:
        """Reconstruct every selected target from durable cleanup and Store facts."""

        observed = self._observe_resolving_attempt(
            operation_id, disposition="retryable_failure", phase="resolving_closure"
        )
        return self._interrupted_closure_nodes(observed)

    def observe_interrupted_verified_attempt(
        self, operation_id: str
    ) -> PackageProductInterruptedResolvingCleanupObservationV1:
        """Reconstruct exact verified-closure cleanup after interruption."""

        observed = self._observe_resolving_attempt(
            operation_id, disposition="retryable_failure", phase="closure_verified"
        )
        return self._interrupted_closure_nodes(observed)

    def _interrupted_closure_nodes(
        self, observed: PackageProductResolvingCleanupObservationV1
    ) -> PackageProductInterruptedResolvingCleanupObservationV1:
        by_node = {
            item.target.node_id: item
            for item in observed.tombstones
            if item.target.attempt_epoch == observed.status.attempt_epoch
        }
        nodes = tuple(
            PackageProductInterruptedResolvingNodeObservationV1(
                node=node,
                target=(
                    by_node[node.attempt.node_id].target
                    if node.attempt.node_id in by_node
                    else self._target_from_root(node.attempt)
                    if node.attempt.attempt_identity is not None
                    else None
                ),
                tombstone=by_node.get(node.attempt.node_id),
            )
            for node in observed.nodes
        )
        return PackageProductInterruptedResolvingCleanupObservationV1(
            status=observed.status,
            nodes=nodes,
            artifact_evidence_refs=observed.artifact_evidence_refs,
            resolution_evidence_refs=observed.resolution_evidence_refs,
            store_identity=observed.store_identity,
            committed_attempts=observed.committed_attempts,
        )

    def _observe_resolving_attempt(
        self, operation_id: str, *, disposition: str, phase: str
    ) -> PackageProductResolvingCleanupObservationV1:
        status = self._selected_claim_status(
            operation_id,
            disposition=disposition,
            phases=frozenset({phase}),
            invalid_code=(
                "package_rebind_claim_not_pinned"
                if phase == "transaction_pinned"
                else "package_rebind_claim_not_verified"
                if phase == "closure_verified"
                else "package_rebind_claim_not_resolving"
            ),
        )
        original = self._lifecycle.read_operation(operation_id)
        assert original is not None
        request, _current = original
        assert isinstance(request, PackageLifecycleRequestV2)
        self._require_no_later_effects(
            operation_id,
            status.attempt_epoch,
            allow_pin=phase == "transaction_pinned",
        )
        resolution = self._resolution.read_attempt_evidence(
            operation_id=operation_id, attempt_epoch=status.attempt_epoch
        )
        artifacts = self._artifacts.read_attempt_evidence(
            operation_id=operation_id, attempt_epoch=status.attempt_epoch
        )
        if any(
            record.request_fingerprint != status.request_fingerprint
            for record in resolution
        ) or any(
            record.request_fingerprint != status.request_fingerprint
            for record in artifacts
        ):
            raise PackageProductRebindCleanupReadError(
                "Resolving Package evidence changed request",
                code="package_rebind_resolving_evidence_changed",
            )
        bases = tuple(
            record.evidence
            for record in resolution
            if isinstance(record.evidence, PackageClosureResolutionBasisV1)
        )
        selections = tuple(
            record.evidence
            for record in resolution
            if isinstance(record.evidence, PackageDependencySelectionV1)
        )
        plans = tuple(
            record.evidence
            for record in resolution
            if isinstance(record.evidence, VerifiedClosurePlanV2)
        )
        if (
            len(bases) != 1
            or (phase in {"closure_verified", "transaction_pinned"} and len(plans) != 1)
            or (phase == "resolving_closure" and len(plans) > 1)
            or bases[0].policy_revision != request.policy_revision
            or bases[0].quota_profile_revision != request.quota_profile_revision
            or bases[0].resolution_environment.fingerprint
            != request.resolution_environment_fingerprint
        ):
            raise PackageProductRebindCleanupReadError(
                "Resolving Package basis or plan changed request",
                code="package_rebind_resolving_evidence_changed",
            )
        selected: dict[str, PackageDependencySelectionV1] = {}
        for selection in selections:
            prior = selected.get(selection.node_id)
            if prior is not None and (
                prior.project_name != selection.project_name
                or prior.wheel_filename != selection.wheel_filename
                or prior.canonical_source_identity
                != selection.canonical_source_identity
                or prior.expected_artifact_digest
                != selection.expected_artifact_digest
                or prior.version != selection.version
            ):
                raise PackageProductRebindCleanupReadError(
                    "Selected dependency node changed Source",
                    code="package_rebind_resolving_evidence_changed",
                )
            selected[selection.node_id] = selection
        evidence_by_node: dict[str, list[object]] = {}
        for record in artifacts:
            evidence_by_node.setdefault(record.node_id, []).append(record.evidence)
        if set(evidence_by_node) - ({"root"} | set(selected)):
            raise PackageProductRebindCleanupReadError(
                "Resolving Package has unselected artifact evidence",
                code="package_rebind_resolving_evidence_changed",
            )
        node_ids = tuple(sorted({"root", *selected}))
        tombstones = self._cleanup.read_operation_tombstones(operation_id)
        current_tombstones = tuple(
            item
            for item in tombstones
            if item.target.attempt_epoch == status.attempt_epoch
        )
        current_by_node = {item.target.node_id: item for item in current_tombstones}
        if (
            any(
                item.disposition != "cleanup_complete"
                for item in tombstones
                if item.target.attempt_epoch != status.attempt_epoch
            )
            or (disposition == "active" and current_tombstones)
            or len(current_by_node) != len(current_tombstones)
            or set(current_by_node) - set(node_ids)
            or any(
                item.rejection_code != "package_rebind_restart"
                or item.rejection_stage != phase
                for item in current_tombstones
            )
        ):
            raise PackageProductRebindCleanupReadError(
                "Resolving Package has cleanup history requiring replay",
                code="package_rebind_cleanup_pending",
            )
        attempts = self._quarantine.observe_attempts(
            operation_id,
            status.attempt_epoch,
            node_ids,
            removed_identities=tuple(
                item.target.attempt_identity
                for item in current_tombstones
                if item.disposition == "cleanup_complete"
            ),
        )
        nodes = []
        for attempt in attempts:
            tombstone = current_by_node.get(attempt.node_id)
            if tombstone is not None:
                target = tombstone.target
                if (
                    target.operation_id != operation_id
                    or target.attempt_epoch != status.attempt_epoch
                    or target.node_id != attempt.node_id
                    or target.attempt_name != attempt.attempt_name
                    or target.store_identity != attempt.store_identity
                    or (
                        attempt.attempt_identity is not None
                        and attempt.attempt_identity != target.attempt_identity
                    )
                    or (
                        tombstone.disposition == "cleanup_complete"
                        and attempt.attempt_identity is not None
                    )
                ):
                    raise PackageProductRebindCleanupReadError(
                        "Resolving Package cleanup target changed physical slot",
                        code="package_rebind_cleanup_target_changed",
                    )
            chain = evidence_by_node.get(attempt.node_id, [])
            kinds = tuple(type(item) for item in chain)
            if attempt.node_id == "root":
                expected_source = request.canonical_source_identity
                expected_digest = None
                valid = kinds == (
                    PackageAuthenticatedSourceEvidenceV1,
                    BoundedAcquisitionReceiptV1,
                    VerifiedWheelArtifactV1,
                )
            else:
                selection = selected[attempt.node_id]
                expected_source = selection.canonical_source_identity
                expected_digest = selection.expected_artifact_digest
                valid = kinds in {
                    (),
                    (PackageAuthenticatedSourceEvidenceV1,),
                    (
                        PackageAuthenticatedSourceEvidenceV1,
                        BoundedAcquisitionReceiptV1,
                    ),
                    (
                        PackageAuthenticatedSourceEvidenceV1,
                        BoundedAcquisitionReceiptV1,
                        VerifiedWheelArtifactV1,
                    ),
                }
            if not valid:
                raise PackageProductRebindCleanupReadError(
                    "Resolving Package node evidence has an invalid prefix",
                    code="package_rebind_resolving_evidence_changed",
                )
            source = chain[0] if chain else None
            receipt = chain[1] if len(chain) > 1 else None
            verified = chain[2] if len(chain) > 2 else None
            if source is not None:
                assert isinstance(source, PackageAuthenticatedSourceEvidenceV1)
                envelope = source.envelope
                if (
                    source.attempt_epoch != status.attempt_epoch
                    or envelope.canonical_source_identity != expected_source
                    or envelope.policy_revision != request.policy_revision
                    or envelope.requested_locator_digest
                    != sha256(expected_source.encode("utf-8")).hexdigest()
                    or (
                        expected_digest is not None
                        and envelope.expected_artifact_digest != expected_digest
                    )
                ):
                    raise PackageProductRebindCleanupReadError(
                        "Resolving Package node Source changed selection",
                        code="package_rebind_resolving_evidence_changed",
                    )
            if tombstone is not None and source is None:
                raise PackageProductRebindCleanupReadError(
                    "Resolving Package cleanup target lacks Source evidence",
                    code="package_rebind_resolving_evidence_changed",
                )
            if receipt is not None:
                assert isinstance(receipt, BoundedAcquisitionReceiptV1)
                try:
                    self._quarantine.prove_acquisition_sink(
                        replace(
                            attempt,
                            attempt_identity=(
                                tombstone.target.attempt_identity
                                if tombstone is not None
                                else attempt.attempt_identity
                            ),
                        ),
                        receipt,
                    )
                except OSError as exc:
                    raise PackageProductRebindCleanupReadError(
                        "Resolving Package node changed acquisition sink",
                        code="package_rebind_acquired_sink_changed",
                    ) from exc
            elif attempt.attempt_identity is not None and source is None:
                raise PackageProductRebindCleanupReadError(
                    "Resolving Package slot lacks Source evidence",
                    code="package_rebind_resolving_evidence_changed",
                )
            if (
                verified is not None
                and expected_digest is not None
                and isinstance(verified, VerifiedWheelArtifactV1)
                and verified.artifact_digest != expected_digest
            ):
                raise PackageProductRebindCleanupReadError(
                    "Verified dependency changed selected digest",
                    code="package_rebind_resolving_evidence_changed",
                )
            nodes.append(
                PackageProductResolvingNodeObservationV1(
                    attempt=attempt,
                    source_recorded=source is not None,
                    acquisition_receipt=receipt,
                    verified_recorded=verified is not None,
                )
            )
        if phase in {"closure_verified", "transaction_pinned"}:
            plan = plans[0]
            by_plan = {node.node_id: node for node in plan.nodes}
            if (
                plan.operation_id != operation_id
                or plan.attempt_epoch != status.attempt_epoch
                or plan.resolution_environment_fingerprint
                != request.resolution_environment_fingerprint
                or plan.root_node_id != "root"
                or set(by_plan) != set(node_ids)
            ):
                raise PackageProductRebindCleanupReadError(
                    "Verified Package closure changed selected nodes",
                    code="package_rebind_verified_closure_changed",
                )
            for node in nodes:
                plan_node = by_plan[node.attempt.node_id]
                chain = evidence_by_node[node.attempt.node_id]
                if len(chain) != 3:
                    raise PackageProductRebindCleanupReadError(
                        "Verified Package closure lacks complete node evidence",
                        code="package_rebind_verified_closure_changed",
                    )
                source, receipt, verified = chain
                assert isinstance(source, PackageAuthenticatedSourceEvidenceV1)
                assert isinstance(receipt, BoundedAcquisitionReceiptV1)
                assert isinstance(verified, VerifiedWheelArtifactV1)
                expected_source = (
                    request.canonical_source_identity
                    if node.attempt.node_id == "root"
                    else selected[node.attempt.node_id].canonical_source_identity
                )
                if (
                    plan_node.role
                    != ("root" if node.attempt.node_id == "root" else "dependency")
                    or plan_node.canonical_source_identity != expected_source
                    or plan_node.source_envelope_fingerprint
                    != source.envelope.fingerprint
                    or plan_node.acquisition_receipt_fingerprint
                    != receipt.fingerprint
                    or plan_node.wheel_evidence_fingerprint != verified.fingerprint
                    or plan_node.artifact_digest != verified.artifact_digest
                    or receipt.envelope_fingerprint != source.envelope.fingerprint
                    or receipt.actual_byte_digest != verified.artifact_digest
                    or receipt.actual_byte_count != verified.artifact_size
                    or plan_node.extraction_tree_digest
                    != verified.extraction_tree_digest
                    or plan_node.distribution != verified.distribution
                    or plan_node.version != verified.version
                ):
                    raise PackageProductRebindCleanupReadError(
                        "Verified Package closure changed node evidence",
                        code="package_rebind_verified_closure_changed",
                    )
        if plans and any(
            node.acquisition_receipt is None or not node.verified_recorded
            for node in nodes
        ):
            raise PackageProductRebindCleanupReadError(
                "Verified closure plan lacks complete node evidence",
                code="package_rebind_resolving_evidence_changed",
            )
        committed, store_identity = self._observe_committed_store(
            operation_id,
            additional_attempts=tuple(
                node.attempt
                for node in nodes
                if node.attempt.attempt_identity is not None
            ),
        )
        return PackageProductResolvingCleanupObservationV1(
            status=status,
            nodes=tuple(nodes),
            artifact_evidence_refs=tuple(item.evidence_ref for item in artifacts),
            resolution_evidence_refs=tuple(item.evidence_ref for item in resolution),
            store_identity=store_identity,
            committed_attempts=committed,
            tombstones=tombstones,
        )

    def observe_interrupted_acquired_attempt(
        self, operation_id: str
    ) -> PackageProductInterruptedAcquiredCleanupObservationV1:
        """Reconstruct exact cleanup target after a root-claim interruption."""

        status = self._selected_acquired_status(
            operation_id, disposition="retryable_failure"
        )
        receipt, artifact_refs, resolution_refs = self._acquired_evidence(status)
        tombstones = self._cleanup.read_operation_tombstones(operation_id)
        current = tuple(
            item
            for item in tombstones
            if item.target.attempt_epoch == status.attempt_epoch
        )
        if (
            len(current) > 1
            or any(
                item.disposition != "cleanup_complete"
                for item in tombstones
                if item.target.attempt_epoch != status.attempt_epoch
            )
        ):
            raise PackageProductRebindCleanupReadError(
                "Package root cleanup history is ambiguous or pending",
                code="package_rebind_cleanup_pending",
            )
        tombstone = current[0] if current else None
        if tombstone is not None and (
            tombstone.rejection_code != "package_rebind_restart"
            or tombstone.rejection_stage != status.phase
        ):
            raise PackageProductRebindCleanupReadError(
                "Package root cleanup history belongs to another owner path",
                code="package_rebind_cleanup_target_changed",
            )
        [root] = self._quarantine.observe_attempts(
            operation_id,
            status.attempt_epoch,
            ("root",),
            removed_identities=(
                (tombstone.target.attempt_identity,)
                if tombstone is not None
                and tombstone.disposition == "cleanup_complete"
                else ()
            ),
        )
        if tombstone is None:
            target = self._target_from_root(root)
        else:
            target = tombstone.target
            if (
                target.node_id != "root"
                or target.operation_id != operation_id
                or target.attempt_name != root.attempt_name
                or target.store_identity != root.store_identity
                or (
                    root.attempt_identity is not None
                    and root.attempt_identity != target.attempt_identity
                )
                or (
                    tombstone.disposition == "cleanup_complete"
                    and root.attempt_identity is not None
                )
            ):
                raise PackageProductRebindCleanupReadError(
                    "Package root cleanup target changed its physical slot",
                    code="package_rebind_cleanup_target_changed",
                )
        try:
            self._quarantine.prove_acquisition_sink(
                replace(root, attempt_identity=target.attempt_identity), receipt
            )
        except OSError as exc:
            raise PackageProductRebindCleanupReadError(
                "Package root cleanup target changed acquisition sink",
                code="package_rebind_acquired_sink_changed",
            ) from exc
        committed, store_identity = self._observe_committed_store(
            operation_id,
            additional_attempts=(root,) if root.attempt_identity is not None else (),
        )
        return PackageProductInterruptedAcquiredCleanupObservationV1(
            status=status,
            target=target,
            tombstone=tombstone,
            root_attempt=root,
            acquisition_receipt=receipt,
            artifact_evidence_refs=artifact_refs,
            resolution_evidence_refs=resolution_refs,
            store_identity=store_identity,
            committed_attempts=committed,
        )

    def _selected_acquired_status(
        self, operation_id: str, *, disposition: str
    ) -> PackageLifecycleStatusV1:
        return self._selected_claim_status(
            operation_id,
            disposition=disposition,
            phases=frozenset({"acquired", "inspecting", "extracted"}),
            invalid_code="package_rebind_claim_not_acquired",
        )

    def _selected_claim_status(
        self,
        operation_id: str,
        *,
        disposition: str,
        phases: frozenset[str],
        invalid_code: str,
    ) -> PackageLifecycleStatusV1:
        original = self._lifecycle.read_operation(operation_id)
        if original is None:
            raise PackageProductRebindCleanupReadError(
                "Package operation is absent", code="package_rebind_operation_missing"
            )
        request, status = original
        selected = self._lifecycle.latest_rebind(operation_id)
        if (
            not isinstance(request, PackageLifecycleRequestV2)
            or selected is None
            or selected.request != request
            or status.disposition != disposition
            or status.phase not in phases
            or (
                disposition == "retryable_failure"
                and (
                    status.failure is None
                    or status.failure.operator_action != "retry"
                )
            )
            or status.classification is None
            or status.classification.decision != "plugin_bound"
            or status.attempt_epoch != selected.decision.expected_attempt_epoch + 1
            or status.attempt_revision <= selected.record_revision
            or status.request_fingerprint != selected.decision.request_fingerprint
        ):
            raise PackageProductRebindCleanupReadError(
                "Package root claim has no selected rebind decision",
                code=invalid_code,
            )
        return status

    def _acquired_evidence(
        self, status: PackageLifecycleStatusV1
    ) -> tuple[BoundedAcquisitionReceiptV1, tuple[str, ...], tuple[str, ...]]:
        operation_id = status.operation_id
        self._require_no_later_effects(operation_id, status.attempt_epoch)
        artifacts = self._artifacts.read_attempt_evidence(
            operation_id=operation_id, attempt_epoch=status.attempt_epoch
        )
        expected_kinds = ("authenticated_source", "bounded_acquisition")
        verified_kinds = (*expected_kinds, "verified_wheel")
        observed_kinds = tuple(record.evidence_kind for record in artifacts)
        if (
            not (
                (status.phase == "acquired" and observed_kinds == expected_kinds)
                or (
                    status.phase == "inspecting"
                    and observed_kinds in {expected_kinds, verified_kinds}
                )
                or (status.phase == "extracted" and observed_kinds == verified_kinds)
            )
            or any(
                record.node_id != "root"
                or record.request_fingerprint != status.request_fingerprint
                for record in artifacts
            )
            or not isinstance(
                artifacts[0].evidence, PackageAuthenticatedSourceEvidenceV1
            )
            or not isinstance(artifacts[1].evidence, BoundedAcquisitionReceiptV1)
            or (
                len(artifacts) == 3
                and not isinstance(artifacts[2].evidence, VerifiedWheelArtifactV1)
            )
        ):
            raise PackageProductRebindCleanupReadError(
                "Package root claim lacks exact acquisition evidence",
                code="package_rebind_acquired_evidence_changed",
            )
        receipt = artifacts[1].evidence
        resolution = self._resolution.read_attempt_evidence(
            operation_id=operation_id, attempt_epoch=status.attempt_epoch
        )
        if any(
            record.request_fingerprint != status.request_fingerprint
            or not isinstance(record.evidence, PackageClosureResolutionBasisV1)
            for record in resolution
        ):
            raise PackageProductRebindCleanupReadError(
                "Package root claim has later resolution effects",
                code="package_rebind_acquired_evidence_changed",
            )
        return (
            receipt,
            tuple(record.evidence_ref for record in artifacts),
            tuple(record.evidence_ref for record in resolution),
        )

    @staticmethod
    def _target_from_root(
        root: PackageQuarantineAttemptObservationV1,
    ) -> PackageQuarantineCleanupTargetV1:
        if root.attempt_identity is None:
            raise PackageProductRebindCleanupReadError(
                "Package acquired root disappeared before cleanup was recorded",
                code="package_rebind_acquired_sink_changed",
            )
        values = {
            "attemptEpoch": root.attempt_epoch,
            "attemptIdentity": list(root.attempt_identity),
            "attemptName": root.attempt_name,
            "nodeId": root.node_id,
            "operationId": root.operation_id,
            "storeIdentity": list(root.store_identity),
        }
        return PackageQuarantineCleanupTargetV1(
            operation_id=root.operation_id,
            attempt_epoch=root.attempt_epoch,
            node_id=root.node_id,
            store_identity=root.store_identity,
            attempt_identity=root.attempt_identity,
            attempt_name=root.attempt_name,
            cleanup_id=sha256(canonical_json_bytes(values)).hexdigest(),
        )

    def _require_no_later_effects(
        self, operation_id: str, attempt_epoch: int, *, allow_pin: bool = False
    ) -> None:
        if not allow_pin and any(
            record.attempt_epoch == attempt_epoch
            for record in self._pins.read_operation_records(operation_id)
        ):
            raise PackageProductRebindCleanupReadError(
                "Package attempt has transaction pin history requiring its owner",
                code="package_rebind_pin_effects",
            )
        if (
            self._staging.read_operation_receipts(operation_id)
            or any(
                isinstance(event, PackageCommittedSetRecordV1)
                and event.operation_id == operation_id
                for event in self._committed_sets.read_events()
            )
            or self._handoff.read_operation(operation_id) is not None
        ):
            raise PackageProductRebindCleanupReadError(
                "Package operation has later staging, publication, or handoff history",
                code="package_rebind_later_effects",
            )

    def _observe_committed_store(
        self,
        operation_id: str,
        *,
        additional_attempts: tuple[PackageQuarantineAttemptObservationV1, ...] = (),
    ) -> tuple[tuple[PackageQuarantineAttemptObservationV1, ...], tuple[int, int]]:
        committed = {
            status.operation_id: status
            for _request, status in self._lifecycle.read_operations()
            if status.disposition == "committed"
            and status.phase == "committed"
            and status.operation_id != operation_id
        }
        committed_nodes: dict[tuple[str, int], set[str]] = {}
        committed_receipts: dict[tuple[str, int, str], BoundedAcquisitionReceiptV1] = {}
        for artifact_record in self._artifacts.read_records():
            committed_status = committed.get(artifact_record.operation_id)
            if (
                committed_status is not None
                and artifact_record.attempt_epoch == committed_status.attempt_epoch
                and artifact_record.request_fingerprint
                == committed_status.request_fingerprint
                and isinstance(artifact_record.evidence, BoundedAcquisitionReceiptV1)
            ):
                committed_nodes.setdefault(
                    (artifact_record.operation_id, artifact_record.attempt_epoch),
                    set(),
                ).add(artifact_record.node_id)
                committed_receipts[
                    (
                        artifact_record.operation_id,
                        artifact_record.attempt_epoch,
                        artifact_record.node_id,
                    )
                ] = artifact_record.evidence
        committed_attempts = tuple(
            observed_attempt
            for (committed_operation, epoch), node_ids in sorted(
                committed_nodes.items()
            )
            for observed_attempt in self._quarantine.observe_attempts(
                committed_operation, epoch, tuple(sorted(node_ids))
            )
            if observed_attempt.attempt_identity is not None
        )
        try:
            for committed_attempt in committed_attempts:
                self._quarantine.prove_acquisition_sink(
                    committed_attempt,
                    committed_receipts[
                        (
                            committed_attempt.operation_id,
                            committed_attempt.attempt_epoch,
                            committed_attempt.node_id,
                        )
                    ],
                )
            store_identity = self._quarantine.observe_known_entries(
                tuple(
                    (item.attempt_name, item.attempt_identity)
                    for item in (*committed_attempts, *additional_attempts)
                    if item.attempt_identity is not None
                )
            )
        except OSError as exc:
            raise PackageProductRebindCleanupReadError(
                "Package quarantine Store has residual or unsafe entries",
                code="package_rebind_quarantine_not_empty",
            ) from exc
        return committed_attempts, store_identity
