from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
    PackageLifecycleRetryRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionReceiptV1,
    PackageAcquisitionBudgetV1,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecyclePhase,
    PackageLifecycleRequestV1,
    PluginBoundPackageClassificationV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingJournal,
    PackageArtifactStagingReceiptV1,
    PackageArtifactStagingRequestV1,
    PackagePluginRootTargetV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackageStagingSetLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
    VerifiedWheelCandidate,
)

OPERATION_ID = "operation-staging-set-runtime"
ENVIRONMENT_FINGERPRINT = "7" * 64
RECOVERY_IDENTITY = "recovery-staging-set-runtime"


class _CrashEdge(RuntimeError):
    pass


class _ClassificationAuthority:
    def classification_facts(
        self,
        _request: PackageLifecycleIngressRequestV1,
    ) -> PackageClassificationFactsV1:
        return _classification_facts(classifier_epoch=1)


class _CrashAfterPhaseKernel(PackageLifecycleOwner):
    def __init__(self, *, journal: PackageLifecycleJournal) -> None:
        super().__init__(
            journal=journal,
            classification_authority=_ClassificationAuthority(),
            enabled=True,
        )
        self.crash_after: PackageLifecyclePhase | None = None

    def advance(
        self,
        operation_id: str,
        *,
        next_phase: PackageLifecyclePhase,
        expected_phase: PackageLifecyclePhase,
        expected_journal_revision: int,
        expected_attempt_epoch: int,
    ):
        status = super().advance(
            operation_id,
            next_phase=next_phase,
            expected_phase=expected_phase,
            expected_journal_revision=expected_journal_revision,
            expected_attempt_epoch=expected_attempt_epoch,
        )
        if self.crash_after == next_phase:
            self.crash_after = None
            raise _CrashEdge(next_phase)
        return status


@dataclass
class _Acquired:
    authenticated_envelope: AuthenticatedSourceEnvelopeV1
    receipt: BoundedAcquisitionReceiptV1
    suspended: bool = False

    def suspend_for_recovery(self) -> None:
        self.suspended = True

    def cleanup(self) -> None:
        self.suspended = True


@dataclass
class _Plans:
    plans: dict[int, VerifiedClosurePlanV2]

    def plan(
        self,
        *,
        operation_id: str,
        attempt_epoch: int,
    ) -> VerifiedClosurePlanV2 | None:
        plan = self.plans.get(attempt_epoch)
        if plan is not None and plan.operation_id != operation_id:
            return None
        return plan


@dataclass
class _ClassificationRecheck:
    changed: bool = False
    calls: int = 0

    def recheck(
        self,
        _request: PackageLifecycleRequestV1,
        prior: PluginBoundPackageClassificationV1,
    ) -> PluginBoundPackageClassificationV1:
        self.calls += 1
        if not self.changed:
            return prior
        facts = _classification_facts(classifier_epoch=prior.classifier_epoch + 1)
        return replace(
            prior,
            basis_facts=facts,
            policy_revision=facts.policy_revision,
            classifier_epoch=facts.classifier_epoch,
        )


@dataclass
class _RootTargets:
    calls: int = 0

    def issue_target(
        self,
        request: PackageLifecycleRequestV1,
        _classification: PluginBoundPackageClassificationV1,
    ) -> PackagePluginRootTargetV1:
        self.calls += 1
        return PackagePluginRootTargetV1.create(
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            product_id=request.product_id,
            scope_id=request.scope_id,
            installation_id="installation-test",
            plugin_id=request.requested_plugin_id or "plugin-test",
            authority_id="plugin-target-authority",
            authority_revision="target-revision:1",
        )


@dataclass
class _DependencyStaging:
    receipts: dict[str, PackageArtifactStagingReceiptV1] = field(default_factory=dict)
    calls: int = 0
    physical_stages: int = 0
    events: list[str] = field(default_factory=list)

    def stage_dependency(
        self,
        request: PackageArtifactStagingRequestV1,
        _candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        self.calls += 1
        self.events.append(f"dependency:{request.node_id}")
        existing = self.receipts.get(request.staging_request_id)
        if existing is not None:
            return existing
        node = request.plan_node
        receipt = PackageArtifactStagingReceiptV1.create(
            request,
            stable_ref=VerifiedArtifactRefV1.create(
                store_identity="dependency-store",
                store_revision=f"dependency:{node.artifact_digest}",
                distribution=node.distribution,
                version=node.version,
                artifact_digest=node.artifact_digest,
                extraction_tree_digest=node.extraction_tree_digest,
            ),
        )
        self.receipts[request.staging_request_id] = receipt
        self.physical_stages += 1
        return receipt


@dataclass
class _RootStaging:
    receipts: dict[str, PackageArtifactStagingReceiptV1] = field(default_factory=dict)
    calls: int = 0
    physical_stages: int = 0
    events: list[str] = field(default_factory=list)

    def stage_root(
        self,
        request: PackageArtifactStagingRequestV1,
        _candidate: VerifiedWheelCandidate,
    ) -> PackageArtifactStagingReceiptV1:
        self.calls += 1
        self.events.append(f"root:{request.node_id}")
        existing = self.receipts.get(request.staging_request_id)
        if existing is not None:
            return existing
        target = request.root_target
        assert target is not None
        node = request.plan_node
        receipt = PackageArtifactStagingReceiptV1.create(
            request,
            stable_ref=PluginRevisionRefV1.create(
                store_identity="plugin-revision-store",
                store_revision=f"plugin:{node.artifact_digest}",
                installation_id=target.installation_id,
                plugin_id=target.plugin_id,
                distribution=node.distribution,
                version=node.version,
                artifact_digest=node.artifact_digest,
                extraction_tree_digest=node.extraction_tree_digest,
            ),
        )
        self.receipts[request.staging_request_id] = receipt
        self.physical_stages += 1
        return receipt


@dataclass
class _RuntimeFixture:
    owner: PackageStagingSetLifecycleOwner
    kernel: _CrashAfterPhaseKernel
    plans: _Plans
    pin_journal: PackageTransactionPinJournal
    staging_journal: PackageArtifactStagingJournal
    committed_sets: PackageCommittedSetJournal
    recheck: _ClassificationRecheck
    targets: _RootTargets
    dependency: _DependencyStaging
    root: _RootStaging


def _classification_facts(*, classifier_epoch: int) -> PackageClassificationFactsV1:
    kinds = (
        "explicit_plugin_intent",
        "existing_plugin_binding",
        "existing_plugin_history",
        "independent_non_plugin_authority",
    )
    return PackageClassificationFactsV1(
        facts=tuple(
            PackageClassificationBasisFactV1(
                kind=kind,  # type: ignore[arg-type]
                present=kind == "explicit_plugin_intent",
                authority_id=f"authority:{kind}",
                owner_revision=f"revision:{kind}:{classifier_epoch}",
            )
            for kind in kinds
        ),
        policy_revision=f"classification-policy:{classifier_epoch}",
        classifier_epoch=classifier_epoch,
    )


def _verified_candidate(
    *,
    attempt_epoch: int = 1,
) -> tuple[VerifiedPackageClosureCandidate, tuple[_Acquired, ...]]:
    dependency, dependency_node, dependency_acquired = _wheel_candidate(
        node_id="dependency-node",
        distribution="dependency",
        version="2.0",
        artifact_digest="4" * 64,
        tree_digest="3" * 64,
        attempt_epoch=attempt_epoch,
    )
    requirement = ResolvedPackageRequirementV1(
        requirement=NormalizedPackageRequirementV1.parse("dependency==2.0"),
        marker_applies=True,
        selected_node_id=dependency_node.node_id,
        expected_source_identity=dependency_node.canonical_source_identity,
        expected_artifact_digest=dependency_node.artifact_digest,
    )
    root, root_node, root_acquired = _wheel_candidate(
        node_id="root",
        distribution="root-plugin",
        version="1.0",
        artifact_digest="6" * 64,
        tree_digest="5" * 64,
        attempt_epoch=attempt_epoch,
        requirements=(requirement,),
        selected_edges=(dependency_node.node_id,),
    )
    plan = VerifiedClosurePlanV2.create(
        operation_id=OPERATION_ID,
        attempt_epoch=attempt_epoch,
        root_node_id=root_node.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(root_node, dependency_node),
        max_depth=1,
    )
    by_node = {root.evidence.node_id: root, dependency.evidence.node_id: dependency}
    return (
        VerifiedPackageClosureCandidate(
            plan=plan,
            candidates=tuple(by_node[node.node_id] for node in plan.nodes),
        ),
        (root_acquired, dependency_acquired),
    )


def _wheel_candidate(
    *,
    node_id: str,
    distribution: str,
    version: str,
    artifact_digest: str,
    tree_digest: str,
    attempt_epoch: int,
    requirements: tuple[ResolvedPackageRequirementV1, ...] = (),
    selected_edges: tuple[str, ...] = (),
) -> tuple[VerifiedWheelCandidate, VerifiedClosurePlanNodeV2, _Acquired]:
    source = f"https://packages.example.test/{distribution}.whl"
    envelope = AuthenticatedSourceEnvelopeV1(
        operation_id=OPERATION_ID,
        node_id=node_id,
        canonical_source_identity=source,
        origin_kind="https",
        authentication_decision="authorized",
        authority_id="source-authority",
        requested_locator_digest=sha256(source.encode()).hexdigest(),
        expected_artifact_digest=artifact_digest,
        redirect_policy_revision="redirect-policy:1",
        policy_revision="package-policy:1",
        capture_epoch=1,
    )
    acquisition = BoundedAcquisitionReceiptV1(
        operation_id=OPERATION_ID,
        attempt_epoch=attempt_epoch,
        node_id=node_id,
        envelope_fingerprint=envelope.fingerprint,
        actual_byte_digest=artifact_digest,
        actual_byte_count=10,
        request_count=1,
        redirect_count=0,
        budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=100,
            max_requests=2,
            max_redirects=1,
            max_wall_time_ms=1000,
        ),
        sink_identity=sha256(f"sink:{node_id}".encode()).hexdigest(),
        adapter_result=SourceAdapterResultV1(disposition="complete"),
    )
    wheel = VerifiedWheelArtifactV1(
        operation_id=OPERATION_ID,
        attempt_epoch=attempt_epoch,
        node_id=node_id,
        distribution=distribution,
        version=version,
        wheel_filename=f"{distribution}-{version}-py3-none-any.whl",
        compatible_tags=("py3-none-any",),
        artifact_digest=artifact_digest,
        artifact_size=10,
        wheel_metadata_digest="a" * 64,
        package_metadata_digest="b" * 64,
        record_digest="c" * 64,
        record_verified=True,
        entry_count=1,
        expanded_byte_count=10,
        extraction_tree_digest=tree_digest,
    )
    acquired = _Acquired(envelope, acquisition)
    candidate = VerifiedWheelCandidate(
        acquired=acquired,  # type: ignore[arg-type]
        evidence=wheel,
        requires_dist=(),
        requires_python=None,
        provides_extra=(),
    )
    node = VerifiedClosurePlanNodeV2(
        node_id=node_id,
        role="root" if node_id == "root" else "dependency",
        distribution=distribution,
        version=version,
        canonical_source_identity=source,
        source_envelope_fingerprint=envelope.fingerprint,
        acquisition_receipt_fingerprint=acquisition.fingerprint,
        wheel_evidence_fingerprint=wheel.fingerprint,
        artifact_digest=artifact_digest,
        extraction_tree_digest=tree_digest,
        selected_extras=(),
        requirements=requirements,
        selected_edges=selected_edges,
    )
    return candidate, node, acquired


def _fixture(
    tmp_path: Path,
    *,
    changed_classification: bool = False,
) -> tuple[_RuntimeFixture, VerifiedPackageClosureCandidate, tuple[_Acquired, ...]]:
    candidate, acquired = _verified_candidate()
    journal = PackageLifecycleJournal(tmp_path / "lifecycle.jsonl")
    kernel = _CrashAfterPhaseKernel(journal=journal)
    status = kernel.submit(
        PackageLifecycleIngressRequestV1(
            operation_id=OPERATION_ID,
            action="install",
            product_id="coding",
            scope_id="workspace:test",
            requested_package="root-plugin==1.0",
            requested_plugin_id="plugin-test",
            source_locator="https://packages.example.test/root-plugin.whl",
            policy_revision="package-policy:1",
            quota_profile_revision="quota:1",
            resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        )
    )
    for phase in (
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
        "closure_verified",
    ):
        status = kernel.advance(
            OPERATION_ID,
            next_phase=phase,  # type: ignore[arg-type]
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    assert status.classification is not None
    pin_request = PackageTransactionPinRequestV1.create(
        candidate.plan,
        request_fingerprint=status.request_fingerprint,
        classification_fingerprint=status.classification.evidence_ref,
        recovery_identity=RECOVERY_IDENTITY,
    )
    pin_receipt = PackageTransactionPinReceiptV1.acquire(
        pin_request,
        pin_id="f" * 64,
        owner_identity="retention-owner",
        owner_revision=1,
        lease_id="lease-staging-set",
        lease_revision=1,
    )
    pin_journal = PackageTransactionPinJournal(tmp_path / "pins.jsonl")
    pin_journal.append(pin_receipt)
    status = kernel.advance(
        OPERATION_ID,
        next_phase="transaction_pinned",
        expected_phase="closure_verified",
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )
    plans = _Plans({1: candidate.plan})
    recheck = _ClassificationRecheck(changed=changed_classification)
    targets = _RootTargets()
    dependency = _DependencyStaging()
    root = _RootStaging()
    stage_events: list[str] = []
    dependency.events = stage_events
    root.events = stage_events
    staging_journal = PackageArtifactStagingJournal(tmp_path / "staging.jsonl")
    committed_sets = PackageCommittedSetJournal(tmp_path / "sets.jsonl")
    owner = PackageStagingSetLifecycleOwner(
        kernel=kernel,
        classification_recheck=recheck,
        closure_plans=plans,
        pin_journal=pin_journal,
        root_targets=targets,
        dependency_staging=dependency,
        root_staging=root,
        staging_journal=staging_journal,
        committed_sets=committed_sets,
    )
    return (
        _RuntimeFixture(
            owner=owner,
            kernel=kernel,
            plans=plans,
            pin_journal=pin_journal,
            staging_journal=staging_journal,
            committed_sets=committed_sets,
            recheck=recheck,
            targets=targets,
            dependency=dependency,
            root=root,
        ),
        candidate,
        acquired,
    )


def _restarted_owner(
    fixture: _RuntimeFixture,
    tmp_path: Path,
) -> PackageStagingSetLifecycleOwner:
    kernel = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(fixture.kernel.journal.path),
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    return PackageStagingSetLifecycleOwner(
        kernel=kernel,
        classification_recheck=fixture.recheck,
        closure_plans=fixture.plans,
        pin_journal=PackageTransactionPinJournal(fixture.pin_journal.path),
        root_targets=fixture.targets,
        dependency_staging=fixture.dependency,
        root_staging=fixture.root,
        staging_journal=PackageArtifactStagingJournal(fixture.staging_journal.path),
        committed_sets=PackageCommittedSetJournal(fixture.committed_sets.path),
    )


def test_staging_set_runtime_stages_journals_rechecks_and_publishes_exact_set(
    tmp_path: Path,
) -> None:
    fixture, candidate, acquired = _fixture(tmp_path)

    result = fixture.owner.stage_and_publish(candidate)
    replay_candidate, replay_acquired = _verified_candidate()
    replay = fixture.owner.stage_and_publish(replay_candidate)

    assert result.status.phase == "set_published"
    assert result.status.disposition == "active"
    assert result.committed_set is not None
    assert replay == result
    assert len(result.staging_receipts) == 2
    assert len(fixture.staging_journal.records()) == 2
    assert len(fixture.committed_sets.records()) == 1
    assert fixture.dependency.physical_stages == 1
    assert fixture.root.physical_stages == 1
    assert fixture.dependency.events == ["dependency:dependency-node", "root:root"]
    assert fixture.recheck.calls == 1
    assert all(item.suspended for item in acquired + replay_acquired)


def test_staging_set_runtime_rechecks_classification_after_staging_before_set(
    tmp_path: Path,
) -> None:
    fixture, candidate, acquired = _fixture(
        tmp_path,
        changed_classification=True,
    )

    result = fixture.owner.stage_and_publish(candidate)

    assert result.status.phase == "staging"
    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_target_classification_changed"
    assert len(result.staging_receipts) == 2
    assert fixture.committed_sets.records() == ()
    assert fixture.recheck.calls == 1
    assert all(item.suspended for item in acquired)


def test_staging_set_runtime_rejects_live_candidate_drift_before_store_effect(
    tmp_path: Path,
) -> None:
    fixture, candidate, acquired = _fixture(tmp_path)
    changed_wheel = replace(candidate.candidates[0].evidence, artifact_size=11)
    candidate.candidates[0].evidence = changed_wheel

    result = fixture.owner.stage_and_publish(candidate)

    assert result.status.phase == "transaction_pinned"
    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_operation_identity_conflict"
    assert fixture.dependency.calls == fixture.root.calls == 0
    assert fixture.staging_journal.records() == ()
    assert fixture.committed_sets.records() == ()
    assert all(item.suspended for item in acquired)


def test_staging_set_runtime_resumes_receipts_after_crash_before_set(
    tmp_path: Path,
) -> None:
    fixture, candidate, _acquired = _fixture(tmp_path)
    fixture.kernel.crash_after = "staging"

    with pytest.raises(_CrashEdge, match="staging"):
        fixture.owner.stage_and_publish(candidate)

    assert fixture.kernel.status(OPERATION_ID).phase == "staging"  # type: ignore[union-attr]
    assert len(fixture.staging_journal.records()) == 2
    assert fixture.committed_sets.records() == ()
    restarted = _restarted_owner(fixture, tmp_path)
    resumed = restarted.resume(OPERATION_ID)

    assert resumed.status.phase == "set_published"
    assert resumed.committed_set is not None
    assert fixture.dependency.physical_stages == 1
    assert fixture.root.physical_stages == 1
    assert len(fixture.committed_sets.records()) == 1


def test_staging_set_runtime_recovers_set_after_crash_without_live_candidate(
    tmp_path: Path,
) -> None:
    fixture, candidate, _acquired = _fixture(tmp_path)
    fixture.kernel.crash_after = "set_published"

    with pytest.raises(_CrashEdge, match="set_published"):
        fixture.owner.stage_and_publish(candidate)

    current = fixture.kernel.status(OPERATION_ID)
    assert current is not None and current.phase == "set_published"
    interrupted = fixture.kernel.interrupt(
        OPERATION_ID,
        expected_phase="set_published",
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )
    restarted = _restarted_owner(fixture, tmp_path)
    recovered = restarted.recover(OPERATION_ID)

    assert interrupted.disposition == "retryable_failure"
    assert recovered.status == interrupted
    assert recovered.committed_set == fixture.committed_sets.records()[0].committed_set
    assert len(recovered.staging_receipts) == 2
    assert fixture.dependency.physical_stages == 1
    assert fixture.root.physical_stages == 1


def test_staging_set_runtime_adopts_prior_attempt_receipts_without_restage(
    tmp_path: Path,
) -> None:
    fixture, candidate, _acquired = _fixture(tmp_path)
    fixture.kernel.crash_after = "staging"
    with pytest.raises(_CrashEdge):
        fixture.owner.stage_and_publish(candidate)
    current = fixture.kernel.status(OPERATION_ID)
    assert current is not None
    interrupted = fixture.kernel.interrupt(
        OPERATION_ID,
        expected_phase="staging",
        expected_journal_revision=current.journal_revision,
        expected_attempt_epoch=current.attempt_epoch,
    )
    retried = fixture.kernel.retry(
        PackageLifecycleRetryRequestV1(
            operation_id=OPERATION_ID,
            request_fingerprint=interrupted.request_fingerprint,
            expected_attempt_epoch=interrupted.attempt_epoch,
        )
    )
    prior = fixture.plans.plans[1]
    fixture.plans.plans[2] = VerifiedClosurePlanV2.create(
        operation_id=prior.operation_id,
        attempt_epoch=2,
        root_node_id=prior.root_node_id,
        resolution_environment_fingerprint=prior.resolution_environment_fingerprint,
        nodes=prior.nodes,
        max_depth=prior.max_depth,
    )

    resumed = fixture.owner.resume(OPERATION_ID)

    assert retried.phase == "staging" and retried.attempt_epoch == 2
    assert resumed.status.phase == "set_published"
    assert resumed.status.attempt_epoch == 2
    assert resumed.committed_set is not None
    assert resumed.committed_set.attempt_epoch == 2
    assert fixture.dependency.physical_stages == 1
    assert fixture.root.physical_stages == 1
