"""Dark PLC9B staging and atomic committed-set lifecycle composition."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.adoption import (
    PackageLegacyAdoptionRequestV1,
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
    PackageCommittedSetGcTombstoneV1,
    PackageCommittedSetJournal,
    PackageCommittedSetJournalError,
    PackageCommittedSetRecordV1,
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
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
    VerifiedWheelCandidate,
)

_ADOPTION_FRESH_TARGET_PHASES = frozenset(
    {
        "classified",
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
        "transaction_pinned",
    }
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


class PackageStagingCheckpointError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageStagingCheckpointV1:
    """Momentary owner proof of staged nodes, with no execution authority."""

    status: PackageLifecycleStatusV1
    plan_fingerprint: str
    pin_receipt_id: str
    root_target: PackagePluginRootTargetV1
    receipts: tuple[PackageArtifactStagingReceiptV1, ...]
    missing_node_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.status, PackageLifecycleStatusV1)
            or self.status.disposition != "active"
            or self.status.phase != "transaction_pinned"
            or not isinstance(self.root_target, PackagePluginRootTargetV1)
            or self.root_target.operation_id != self.status.operation_id
            or self.root_target.request_fingerprint
            != self.status.request_fingerprint
        ):
            raise ValueError("Package staging checkpoint identity changed")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in (self.plan_fingerprint, self.pin_receipt_id)
        ):
            raise ValueError("Package staging checkpoint proof identity is invalid")
        if self.receipts != tuple(
            sorted(self.receipts, key=lambda receipt: receipt.node_id)
        ) or any(
            not isinstance(receipt, PackageArtifactStagingReceiptV1)
            or receipt.operation_id != self.status.operation_id
            for receipt in self.receipts
        ):
            raise ValueError("Package staging checkpoint receipts changed")
        receipt_nodes = tuple(receipt.node_id for receipt in self.receipts)
        if (
            len(set(receipt_nodes)) != len(receipt_nodes)
            or self.missing_node_ids != tuple(sorted(set(self.missing_node_ids)))
            or set(receipt_nodes) & set(self.missing_node_ids)
        ):
            raise ValueError("Package staging checkpoint nodes are not canonical")

    @property
    def checkpoint_id(self) -> str:
        # Selection records advance the attempt CAS without changing staged
        # bytes. Keep the checkpoint identity stable across that selection;
        # callers bind the exact attempt revision separately in their CAS.
        status_identity = self.status.to_dict()
        status_identity.pop("attemptRevision")
        return sha256(
            canonical_json_bytes(
                {
                    "missingNodeIds": list(self.missing_node_ids),
                    "pinReceiptId": self.pin_receipt_id,
                    "planFingerprint": self.plan_fingerprint,
                    "receiptIds": [receipt.receipt_id for receipt in self.receipts],
                    "rootTarget": self.root_target.to_dict(),
                    "status": status_identity,
                }
            )
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class PackagePublishedSetCheckpointV1:
    """Read-only proof of a complete, retained set awaiting commit handoff."""

    status: PackageLifecycleStatusV1
    plan_fingerprint: str
    pin_receipt_id: str
    root_target: PackagePluginRootTargetV1
    receipts: tuple[PackageArtifactStagingReceiptV1, ...]
    committed_set: CommittedPackageSetRefV1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.status, PackageLifecycleStatusV1)
            or self.status.disposition != "active"
            or self.status.phase != "set_published"
            or not isinstance(self.root_target, PackagePluginRootTargetV1)
            or self.root_target.operation_id != self.status.operation_id
            or self.root_target.request_fingerprint != self.status.request_fingerprint
            or not isinstance(self.committed_set, CommittedPackageSetRefV1)
            or self.committed_set.operation_id != self.status.operation_id
            or self.committed_set.request_fingerprint != self.status.request_fingerprint
            or self.receipts != tuple(sorted(self.receipts, key=lambda item: item.node_id))
            or len({item.node_id for item in self.receipts}) != len(self.receipts)
        ):
            raise ValueError("Published Package set checkpoint identity changed")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in (self.plan_fingerprint, self.pin_receipt_id)
        ):
            raise ValueError("Published Package set proof identity is invalid")

    @property
    def checkpoint_id(self) -> str:
        # Selecting an admission changes only the attempt CAS. The published
        # set and its physical evidence must keep the same checkpoint identity.
        status_identity = self.status.to_dict()
        status_identity.pop("attemptRevision")
        return sha256(
            canonical_json_bytes(
                {
                    "committedSet": self.committed_set.to_dict(),
                    "pinReceiptId": self.pin_receipt_id,
                    "planFingerprint": self.plan_fingerprint,
                    "receiptIds": [receipt.receipt_id for receipt in self.receipts],
                    "rootTarget": self.root_target.to_dict(),
                    "status": status_identity,
                }
            )
        ).hexdigest()


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

    def inspect_checkpoint(self, operation_id: str) -> PackageStagingCheckpointV1:
        """Verify a pinned-stage prefix against strict journals and physical Store."""

        checkpoint = self._inspect_checkpoint(operation_id, phase="transaction_pinned")
        assert isinstance(checkpoint, PackageStagingCheckpointV1)
        return checkpoint

    def inspect_published_checkpoint(
        self, operation_id: str
    ) -> PackagePublishedSetCheckpointV1:
        """Verify a published set and its retained physical Store without repair."""

        checkpoint = self._inspect_checkpoint(operation_id, phase="set_published")
        assert isinstance(checkpoint, PackagePublishedSetCheckpointV1)
        return checkpoint

    def _inspect_checkpoint(
        self, operation_id: str, *, phase: str
    ) -> PackageStagingCheckpointV1 | PackagePublishedSetCheckpointV1:

        original = self._kernel.journal.read_operation(operation_id)
        if original is None:
            raise PackageStagingCheckpointError(
                "Package staging operation is absent",
                code="package_staging_checkpoint_missing",
            )
        request, status = original
        if (
            status.disposition != "active"
            or status.phase != phase
            or status.classification is None
            or status.classification.decision != "plugin_bound"
        ):
            raise PackageStagingCheckpointError(
                "Package staging checkpoint phase is unavailable",
                code="package_staging_checkpoint_phase_changed",
            )
        plan = self._plan(operation_id, status.attempt_epoch)
        if plan is None:
            raise PackageStagingCheckpointError(
                "Verified Package closure plan is absent",
                code="package_staging_checkpoint_plan_changed",
            )
        pin_records = self._pin_journal.read_operation_records(operation_id)
        if len(pin_records) != 1:
            raise PackageStagingCheckpointError(
                "Package staging checkpoint has ambiguous pin history",
                code="package_staging_checkpoint_pin_changed",
            )
        pin = self._current_pin(status, plan, read_only=True)
        if pin is None:
            raise PackageStagingCheckpointError(
                "Package transaction pin is not acquired",
                code="package_staging_checkpoint_pin_changed",
            )
        target = self._root_targets.issue_target(request, status.classification)
        if not self._target_matches(target, request, status):
            raise PackageStagingCheckpointError(
                "Package root target changed",
                code="package_staging_checkpoint_target_changed",
            )
        set_events = self._committed_sets.read_events()
        published = tuple(
            event
            for event in set_events
            if isinstance(event, PackageCommittedSetRecordV1)
            and event.operation_id == operation_id
        )
        if (phase == "transaction_pinned" and published) or (
            phase == "set_published" and len(published) != 1
        ):
            raise PackageStagingCheckpointError(
                "Package committed set does not match checkpoint phase",
                code="package_staging_checkpoint_set_changed",
            )
        if phase == "set_published" and any(
            isinstance(event, PackageCommittedSetGcTombstoneV1)
            and event.set_id == published[0].committed_set.set_id
            for event in set_events
        ):
            raise PackageStagingCheckpointError(
                "Published Package set was retired",
                code="package_staging_checkpoint_set_changed",
            )
        receipts = tuple(
            sorted(
                self._staging_journal.read_operation_receipts(operation_id),
                key=lambda receipt: receipt.node_id,
            )
        )
        plan_nodes = {node.node_id for node in plan.nodes}
        staged_nodes = {receipt.node_id for receipt in receipts}
        if len(staged_nodes) != len(receipts) or not staged_nodes <= plan_nodes:
            raise PackageStagingCheckpointError(
                "Package staging receipts changed closure nodes",
                code="package_staging_checkpoint_receipts_changed",
            )
        if phase == "set_published" and staged_nodes != plan_nodes:
            raise PackageStagingCheckpointError(
                "Published Package set has incomplete staging receipts",
                code="package_staging_checkpoint_receipts_changed",
            )
        read_dependencies = getattr(
            self._dependency_staging, "read_operation_settlements", None
        )
        read_root = getattr(self._root_staging, "read_operation_settlements", None)
        if not callable(read_dependencies) or not callable(read_root):
            raise PackageStagingCheckpointError(
                "Package staging Store account is unavailable",
                code="package_staging_checkpoint_store_unverified",
            )

        def store_receipt_ids() -> tuple[str, ...]:
            return tuple(
                sorted(
                    record.receipt.receipt_id
                    for record in (
                        *read_dependencies(operation_id),
                        *read_root(operation_id),
                    )
                )
            )

        settled_ids = store_receipt_ids()
        receipt_ids = tuple(sorted(receipt.receipt_id for receipt in receipts))
        if settled_ids != receipt_ids:
            raise PackageStagingCheckpointError(
                "Package Store and staging journal have different settled nodes",
                code="package_staging_checkpoint_store_unmatched",
            )
        for receipt in receipts:
            if (
                receipt.staging_request.attempt_epoch != status.attempt_epoch
                or not self._receipt_covers_current_plan(
                    receipt, plan=plan, pin=pin, target=target
                )
            ):
                raise PackageStagingCheckpointError(
                    "Package staging receipt changed verified plan",
                    code="package_staging_checkpoint_receipts_changed",
                )
            validate = getattr(
                self._root_staging
                if receipt.staging_request.plan_node.role == "root"
                else self._dependency_staging,
                "read_validate_root_receipt"
                if receipt.staging_request.plan_node.role == "root"
                else "read_validate_dependency_receipt",
                None,
            )
            if not callable(validate) or validate(receipt) != receipt:
                raise PackageStagingCheckpointError(
                    "Package staging Store validation is unavailable",
                    code="package_staging_checkpoint_store_unverified",
                )
        if (
            self._kernel.journal.read_operation(operation_id) != original
            or self._plan(operation_id, status.attempt_epoch) != plan
            or self._pin_journal.read_operation_records(operation_id) != pin_records
            or self._current_pin(status, plan, read_only=True) != pin
            or tuple(
                sorted(
                    self._staging_journal.read_operation_receipts(operation_id),
                    key=lambda receipt: receipt.node_id,
                )
            )
            != receipts
            or self._committed_sets.read_events() != set_events
            or store_receipt_ids() != settled_ids
        ):
            raise PackageStagingCheckpointError(
                "Package staging checkpoint changed while read",
                code="package_staging_checkpoint_changed",
            )
        if phase == "set_published":
            committed = published[0]
            assert status.classification is not None
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
                raise PackageStagingCheckpointError(
                    "Published Package set changed verified closure",
                    code="package_staging_checkpoint_set_changed",
                )
            return PackagePublishedSetCheckpointV1(
                status=status,
                plan_fingerprint=plan.fingerprint,
                pin_receipt_id=pin.receipt_id,
                root_target=target,
                receipts=receipts,
                committed_set=committed.committed_set,
            )
        return PackageStagingCheckpointV1(
            status=status,
            plan_fingerprint=plan.fingerprint,
            pin_receipt_id=pin.receipt_id,
            root_target=target,
            receipts=receipts,
            missing_node_ids=tuple(sorted(plan_nodes - staged_nodes)),
        )

    def stage_and_publish(
        self,
        candidate: VerifiedPackageClosureCandidate,
        *,
        adoption_request: PackageLegacyAdoptionRequestV1 | None = None,
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
            return self.recover(
                status.operation_id,
                adoption_request=adoption_request,
            )
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
        target = (
            self._root_targets.issue_target(request, status.classification)
            if adoption_request is None
            else self._adoption_target(adoption_request, status, request)
        )
        if target is None or not self._target_matches(target, request, status):
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
        except PackagePhysicalStagingError as error:
            candidate.suspend_for_recovery()
            evidence_ref = sha256(
                canonical_json_bytes(
                    {
                        "attemptEpoch": status.attempt_epoch,
                        "code": error.code,
                        "operationId": status.operation_id,
                        "planFingerprint": plan.fingerprint,
                        "stage": "staging",
                    }
                )
            ).hexdigest()
            failure = PackageLifecycleFailureV1.for_operation(
                error.code,
                stage="staging",
                operation_id=status.operation_id,
                evidence_ref=evidence_ref,
            )
            rejected = self._kernel.record_failure(
                failure,
                expected_phase=status.phase,
                expected_journal_revision=status.journal_revision,
                expected_attempt_epoch=status.attempt_epoch,
            )
            return PackageStagingSetExecutionResult(
                status=rejected,
                staging_receipts=tuple(
                    sorted(receipts, key=lambda receipt: receipt.node_id)
                ),
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

    def stage_missing_and_publish(
        self,
        candidate: VerifiedPackageClosureCandidate,
        *,
        expected_checkpoint_id: str,
        expected_missing_node_ids: tuple[str, ...],
    ) -> PackageStagingSetExecutionResult:
        """Recheck a selected physical prefix before filling missing nodes."""

        if not isinstance(candidate, VerifiedPackageClosureCandidate):
            raise TypeError("Verified Package closure candidate is required")
        try:
            checkpoint = self.inspect_checkpoint(candidate.plan.operation_id)
        except BaseException:
            candidate.suspend_for_recovery()
            raise
        if (
            not expected_missing_node_ids
            or checkpoint.checkpoint_id != expected_checkpoint_id
            or checkpoint.missing_node_ids != expected_missing_node_ids
            or candidate.plan.fingerprint != checkpoint.plan_fingerprint
        ):
            candidate.suspend_for_recovery()
            raise PackageStagingCheckpointError(
                "Selected Package staging prefix changed before materialization",
                code="package_staging_checkpoint_changed",
            )
        return self.stage_and_publish(candidate)

    def resume(
        self,
        operation_id: str,
        *,
        adoption_request: PackageLegacyAdoptionRequestV1 | None = None,
    ) -> PackageStagingSetExecutionResult:
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
            return self.recover(
                operation_id,
                adoption_request=adoption_request,
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
        if adoption_request is not None and self._adoption_target(
            adoption_request,
            status,
            request,
        ) != target:
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                )
            )
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

    def recover(
        self,
        operation_id: str,
        *,
        adoption_request: PackageLegacyAdoptionRequestV1 | None = None,
    ) -> PackageStagingSetExecutionResult:
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
        request = self._kernel.journal.request(operation_id)
        if adoption_request is not None and (
            request is None
            or self._adoption_target(adoption_request, status, request) != target
        ):
            return PackageStagingSetExecutionResult(
                status=_local_refusal(
                    status,
                    code="package_operation_identity_conflict",
                ),
                staging_receipts=receipts,
            )
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

    def authorize_adoption(
        self,
        adoption: PackageLegacyAdoptionRequestV1,
    ) -> bool:
        """Bind adoption identity to this owner's logical and physical root."""

        if not isinstance(adoption, PackageLegacyAdoptionRequestV1):
            raise TypeError("Legacy Package adoption request is required")
        status = self._kernel.status(adoption.operation_id)
        request = self._kernel.journal.request(adoption.operation_id)
        return bool(
            status is not None
            and request is not None
            and self._adoption_target(adoption, status, request) is not None
        )

    def _adoption_target(
        self,
        adoption: PackageLegacyAdoptionRequestV1,
        status: PackageLifecycleStatusV1,
        request: PackageLifecycleRequestV1,
    ) -> PackagePluginRootTargetV1 | None:
        if (
            status.operation_id != adoption.operation_id
            or request.operation_id != adoption.operation_id
            or status.disposition not in {"active", "committed"}
            or status.attempt_epoch != adoption.expected_attempt_epoch
            or status.classification is None
            or status.classification.decision != "plugin_bound"
            or status.request_fingerprint
            != adoption.transaction_request_fingerprint
            or request.request_fingerprint
            != adoption.transaction_request_fingerprint
            or status.classification.evidence_ref
            != adoption.expected_classification_fingerprint
            or request.product_id != adoption.product_id
            or request.scope_id != adoption.scope_id
            or request.requested_plugin_id != adoption.plugin_id
        ):
            return None
        target = self._durable_root_target(adoption.operation_id)
        if target is None:
            if status.phase not in _ADOPTION_FRESH_TARGET_PHASES:
                return None
            target = self._root_targets.issue_target(request, status.classification)
        if (
            not self._target_matches(target, request, status)
            or target.installation_id != adoption.installation_id
            or target.plugin_id != adoption.plugin_id
        ):
            return None
        authorize = getattr(self._root_staging, "authorize_adoption", None)
        if not callable(authorize):
            return None
        try:
            accepted = authorize(
                store_id=adoption.store_id,
                current_root_identity=adoption.current_root_identity,
                target=target,
            )
        except Exception:
            return None
        if accepted is not True:
            return None
        return target

    def _durable_root_target(
        self,
        operation_id: str,
    ) -> PackagePluginRootTargetV1 | None:
        try:
            targets = tuple(
                receipt.staging_request.root_target
                for receipt in self._staging_journal.receipts(operation_id)
                if receipt.staging_request.plan_node.role == "root"
            )
        except Exception:
            return None
        return targets[0] if len(targets) == 1 else None

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
        *,
        read_only: bool = False,
    ) -> PackageTransactionPinReceiptV1 | None:
        try:
            if read_only:
                records = self._pin_journal.read_operation_records(status.operation_id)
                receipt = records[-1].receipt if records else None
            else:
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
    "PackagePublishedSetCheckpointV1",
    "PackageStagingClosurePlanEvidencePort",
    "PackageStagingSetExecutionResult",
    "PackageStagingSetLifecycleOwner",
]
