from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

import pytest

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.adoption import (
    PackageLegacyAdoptionOwner,
    PackageLegacyAdoptionRequestV1,
    PackageLegacyStateEvidenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.adoption_transaction import (
    PackageLegacyAdoptionTransactionAdapter,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    PackageClosureBudgetV1,
    PackageResolutionEnvironmentV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_runtime import (
    PackageClosureExecutionRequestV2,
    PackageClosureExecutionResult,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_admission import (
    PackageCommitLifecycleOwner,
    PackagePublicationReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    DependencyClosureLockV2,
    PluginRevisionRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceReceiptV1,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageClassificationBasisKind,
    PackageLifecycleFailureV1,
    PackageLifecyclePhase,
    PackageLifecycleStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.runtime import (
    PackageArtifactExecutionRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging_set_runtime import (
    PackageStagingSetExecutionResult,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pin_runtime import (
    PackageTransactionPinExecutionResult,
)
from loushang.harness.resources.packages.plugin_lifecycle.transaction_pins import (
    PackageTransactionPinJournal,
    PackageTransactionPinReceiptV1,
    PackageTransactionPinRequestV1,
)

STORE_ID = "package-store:adoption-transaction"
OPERATION_ID = "adoption-transaction-operation"
PRODUCT_ID = "coding"
SCOPE_ID = "workspace:adoption-transaction"
INSTALLATION_ID = "installation-adoption-transaction"
PLUGIN_ID = "acme.plugin"
LEGACY_ROOT_ID = "1" * 64
CURRENT_ROOT_ID = "2" * 64
LEGACY_STATE_DIGEST = "3" * 64
ARTIFACT_DIGEST = "5" * 64
TREE_DIGEST = "6" * 64
SECRET = "private-adoption-credential"


class _Authority:
    def classification_facts(
        self,
        _request: PackageLifecycleIngressRequestV1,
    ) -> PackageClassificationFactsV1:
        kinds: tuple[PackageClassificationBasisKind, ...] = (
            "explicit_plugin_intent",
            "existing_plugin_binding",
            "existing_plugin_history",
            "independent_non_plugin_authority",
        )
        return PackageClassificationFactsV1(
            facts=tuple(
                PackageClassificationBasisFactV1(
                    kind=kind,
                    present=kind == "existing_plugin_history",
                    authority_id=f"authority:{kind}",
                    owner_revision=f"revision:{kind}:1",
                )
                for kind in kinds
            ),
            policy_revision="classification-policy:1",
            classifier_epoch=1,
        )


@dataclass
class _Fences:
    receipt: PackageEpochFenceReceiptV1
    calls: int = 0
    lock: Lock = field(default_factory=Lock, repr=False)

    def current(self, _store_id: str) -> PackageEpochFenceReceiptV1:
        with self.lock:
            self.calls += 1
            return self.receipt


@dataclass
class _LegacyState:
    evidence: PackageLegacyStateEvidenceV1
    calls: int = 0
    lock: Lock = field(default_factory=Lock, repr=False)

    def observe(
        self,
        *,
        store_id: str,
        legacy_root_identity: str,
    ) -> PackageLegacyStateEvidenceV1:
        assert store_id == STORE_ID
        assert legacy_root_identity == LEGACY_ROOT_ID
        with self.lock:
            self.calls += 1
            return self.evidence


@dataclass(frozen=True)
class _Fixture:
    kernel: PackageLifecycleOwner
    request: PackageLegacyAdoptionRequestV1
    execution: PackageClosureExecutionRequestV2
    candidate: VerifiedPackageClosureCandidate
    pin_journal: PackageTransactionPinJournal
    committed_sets: PackageCommittedSetJournal
    fence: PackageEpochFenceReceiptV1
    legacy: PackageLegacyStateEvidenceV1


def _environment() -> PackageResolutionEnvironmentV1:
    return PackageResolutionEnvironmentV1.from_mapping(
        {
            "implementation_name": "cpython",
            "implementation_version": "3.11.10",
            "os_name": "posix",
            "platform_machine": "x86_64",
            "platform_python_implementation": "CPython",
            "platform_release": "adoption",
            "platform_system": "Linux",
            "platform_version": "adoption",
            "python_full_version": "3.11.10",
            "python_version": "3.11",
            "sys_platform": "linux",
        },
        supported_tags=("py3-none-any",),
    )


def _fixture(tmp_path: Path) -> _Fixture:
    kernel = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "lifecycle.jsonl"),
        classification_authority=_Authority(),
        enabled=True,
    )
    environment = _environment()
    status = kernel.submit(
        PackageLifecycleIngressRequestV1(
            operation_id=OPERATION_ID,
            action="install",
            product_id=PRODUCT_ID,
            scope_id=SCOPE_ID,
            requested_package="acme-plugin==1.0",
            requested_plugin_id=PLUGIN_ID,
            source_locator=(
                f"https://user:{SECRET}@packages.example.test/acme-plugin.whl"
                f"?token={SECRET}#{SECRET}"
            ),
            policy_revision="package-policy:1",
            quota_profile_revision="quota:1",
            resolution_environment_fingerprint=environment.fingerprint,
        )
    )
    assert status.classification is not None
    fence = PackageEpochFenceReceiptV1.create(
        PackageEpochFenceRequestV1.create(
            store_id=STORE_ID,
            prior_fence=None,
            legacy_root_identity=LEGACY_ROOT_ID,
            fenced_root_identity=CURRENT_ROOT_ID,
            namespace_id="7" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id="8" * 64,
            snapshot_receipt_id="9" * 64,
            root_switch_receipt_id="a" * 64,
        )
    )
    legacy = PackageLegacyStateEvidenceV1.create(
        store_id=STORE_ID,
        legacy_root_identity=LEGACY_ROOT_ID,
        state_digest=LEGACY_STATE_DIGEST,
        entry_count=4,
        byte_count=1024,
    )
    request = PackageLegacyAdoptionRequestV1.create(
        current_fence=fence,
        legacy_state=legacy,
        operation_id=status.operation_id,
        transaction_request_fingerprint=status.request_fingerprint,
        expected_classification_fingerprint=status.classification.evidence_ref,
        expected_attempt_epoch=status.attempt_epoch,
        product_id=PRODUCT_ID,
        scope_id=SCOPE_ID,
        installation_id=INSTALLATION_ID,
        plugin_id=PLUGIN_ID,
    )
    node = VerifiedClosurePlanNodeV2(
        node_id="root",
        role="root",
        distribution="acme-plugin",
        version="1.0",
        canonical_source_identity="https://packages.example.test/acme-plugin.whl",
        source_envelope_fingerprint="b" * 64,
        acquisition_receipt_fingerprint="c" * 64,
        wheel_evidence_fingerprint="d" * 64,
        artifact_digest=ARTIFACT_DIGEST,
        extraction_tree_digest=TREE_DIGEST,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
    )
    plan = VerifiedClosurePlanV2.create(
        operation_id=status.operation_id,
        attempt_epoch=status.attempt_epoch,
        root_node_id=node.node_id,
        resolution_environment_fingerprint=environment.fingerprint,
        nodes=(node,),
        max_depth=0,
    )
    execution = PackageClosureExecutionRequestV2(
        artifact=PackageArtifactExecutionRequestV1(
            operation_id=status.operation_id,
            request_fingerprint=status.request_fingerprint,
            expected_attempt_epoch=status.attempt_epoch,
            wheel_filename="acme_plugin-1.0-py3-none-any.whl",
            credential_reference=f"opaque:{SECRET}",
        ),
        resolution_environment=environment,
        budgets=PackageClosureBudgetV1(),
    )
    return _Fixture(
        kernel=kernel,
        request=request,
        execution=execution,
        candidate=VerifiedPackageClosureCandidate(plan=plan, candidates=()),
        pin_journal=PackageTransactionPinJournal(tmp_path / "pins.jsonl"),
        committed_sets=PackageCommittedSetJournal(tmp_path / "sets.jsonl"),
        fence=fence,
        legacy=legacy,
    )


def _advance(
    kernel: PackageLifecycleOwner,
    status: PackageLifecycleStatusV1,
    phase: PackageLifecyclePhase,
) -> PackageLifecycleStatusV1:
    return kernel.advance(
        status.operation_id,
        next_phase=phase,
        expected_phase=status.phase,
        expected_journal_revision=status.journal_revision,
        expected_attempt_epoch=status.attempt_epoch,
    )


@dataclass
class _Closure:
    fixture: _Fixture
    calls: int = 0

    def execute(
        self,
        execution: PackageClosureExecutionRequestV2,
    ) -> PackageClosureExecutionResult:
        assert execution is self.fixture.execution
        self.calls += 1
        status = self.fixture.kernel.status(OPERATION_ID)
        assert status is not None
        phases: tuple[PackageLifecyclePhase, ...] = (
            "acquiring",
            "acquired",
            "inspecting",
            "extracted",
            "resolving_closure",
            "closure_verified",
        )
        for phase in phases:
            status = _advance(self.fixture.kernel, status, phase)
        return PackageClosureExecutionResult(
            status=status,
            candidate=self.fixture.candidate,
        )


@dataclass
class _FailingClosure:
    fixture: _Fixture
    code: str
    calls: int = 0

    def execute(
        self,
        _execution: PackageClosureExecutionRequestV2,
    ) -> PackageClosureExecutionResult:
        self.calls += 1
        status = self.fixture.kernel.status(OPERATION_ID)
        assert status is not None
        acquiring = _advance(self.fixture.kernel, status, "acquiring")
        details = (
            ("condition:no_acquired_digest",)
            if self.code == "package_operation_timed_out"
            else ()
        )
        failed = self.fixture.kernel.record_failure(
            PackageLifecycleFailureV1.for_operation(
                self.code,
                stage="acquiring",
                operation_id=OPERATION_ID,
                evidence_ref=self.fixture.request.transaction_request_fingerprint,
                details=details,
            ),
            expected_phase="acquiring",
            expected_journal_revision=acquiring.journal_revision,
            expected_attempt_epoch=acquiring.attempt_epoch,
        )
        return PackageClosureExecutionResult(status=failed)


@dataclass
class _Pins:
    fixture: _Fixture
    calls: int = 0

    def pin(
        self,
        candidate: VerifiedPackageClosureCandidate,
        *,
        recovery_identity: str,
    ) -> PackageTransactionPinExecutionResult:
        assert candidate is self.fixture.candidate
        assert recovery_identity == "legacy-adoption-recovery"
        self.calls += 1
        status = self.fixture.kernel.status(OPERATION_ID)
        assert status is not None and status.classification is not None
        pin_request = PackageTransactionPinRequestV1.create(
            candidate.plan,
            request_fingerprint=status.request_fingerprint,
            classification_fingerprint=status.classification.evidence_ref,
            recovery_identity=recovery_identity,
        )
        receipt = PackageTransactionPinReceiptV1.acquire(
            pin_request,
            pin_id="e" * 64,
            owner_identity="adoption-retention-owner",
            owner_revision=1,
            lease_id="adoption-lease",
            lease_revision=1,
        )
        self.fixture.pin_journal.append(receipt)
        pinned = _advance(self.fixture.kernel, status, "transaction_pinned")
        return PackageTransactionPinExecutionResult(
            status=pinned,
            candidate=candidate,
            receipt=receipt,
        )


@dataclass
class _Staging:
    fixture: _Fixture
    stage_calls: int = 0
    resume_calls: int = 0

    def stage_and_publish(
        self,
        candidate: VerifiedPackageClosureCandidate,
    ) -> PackageStagingSetExecutionResult:
        assert candidate is self.fixture.candidate
        self.stage_calls += 1
        return self._publish()

    def resume(self, _operation_id: str) -> PackageStagingSetExecutionResult:
        self.resume_calls += 1
        return self._publish()

    def _publish(self) -> PackageStagingSetExecutionResult:
        status = self.fixture.kernel.status(OPERATION_ID)
        assert status is not None and status.classification is not None
        if status.phase == "transaction_pinned":
            status = _advance(self.fixture.kernel, status, "staging")
        root = self.fixture.candidate.plan.nodes[0]
        root_ref = PluginRevisionRefV1.create(
            store_identity="plugin-revision-store",
            store_revision="plugin-revision:adoption-transaction",
            installation_id=INSTALLATION_ID,
            plugin_id=PLUGIN_ID,
            distribution=root.distribution,
            version=root.version,
            artifact_digest=root.artifact_digest,
            extraction_tree_digest=root.extraction_tree_digest,
        )
        closure_lock = DependencyClosureLockV2.create(
            self.fixture.candidate.plan,
            stable_refs={root.node_id: root_ref},
        )
        committed = self.fixture.committed_sets.publish(
            closure_lock,
            request_fingerprint=status.request_fingerprint,
            product_id=PRODUCT_ID,
            scope_id=SCOPE_ID,
            installation_id=INSTALLATION_ID,
            plugin_id=PLUGIN_ID,
            classification_fingerprint=status.classification.evidence_ref,
        )
        published = _advance(self.fixture.kernel, status, "set_published")
        return PackageStagingSetExecutionResult(
            status=published,
            committed_set=committed,
        )


@dataclass
class _Commit:
    owner: PackageCommitLifecycleOwner
    crash_after_commit: bool = False
    calls: int = 0

    def commit(self, operation_id: str) -> PackagePublicationReceiptV1:
        self.calls += 1
        receipt = self.owner.commit(operation_id)
        if self.crash_after_commit:
            raise _CrashAfterCommit
        return receipt


class _Never:
    calls = 0

    def execute(self, _execution: object) -> object:
        self.calls += 1
        raise AssertionError("closure must not run")

    def pin(self, _candidate: object, *, recovery_identity: str) -> object:
        del recovery_identity
        self.calls += 1
        raise AssertionError("pin must not run")

    def stage_and_publish(self, _candidate: object) -> object:
        self.calls += 1
        raise AssertionError("staging must not run")

    def resume(self, _operation_id: str) -> object:
        self.calls += 1
        raise AssertionError("resume must not run")

    def commit(self, _operation_id: str) -> object:
        self.calls += 1
        raise AssertionError("commit must not run")


class _CrashAfterCommit(RuntimeError):
    pass


class _CrashDuringStaging(RuntimeError):
    pass


def _adapter(
    fixture: _Fixture,
    *,
    closure: object,
    pins: object,
    staging: object,
    commit: object,
) -> PackageLegacyAdoptionTransactionAdapter:
    return PackageLegacyAdoptionTransactionAdapter(
        kernel=fixture.kernel,
        execution=fixture.execution,
        recovery_identity="legacy-adoption-recovery",
        closure=closure,  # type: ignore[arg-type]
        pins=pins,  # type: ignore[arg-type]
        staging=staging,  # type: ignore[arg-type]
        commit=commit,  # type: ignore[arg-type]
    )


def _outer(
    fixture: _Fixture,
    transaction: PackageLegacyAdoptionTransactionAdapter,
) -> tuple[PackageLegacyAdoptionOwner, _Fences, _LegacyState]:
    fences = _Fences(fixture.fence)
    legacy = _LegacyState(fixture.legacy)
    return (
        PackageLegacyAdoptionOwner(
            store_id=STORE_ID,
            fences=fences,
            legacy_state=legacy,
            transaction=transaction,
        ),
        fences,
        legacy,
    )


def _success_components(
    fixture: _Fixture,
    *,
    crash_after_commit: bool = False,
) -> tuple[_Closure, _Pins, _Staging, _Commit]:
    closure = _Closure(fixture)
    pins = _Pins(fixture)
    staging = _Staging(fixture)
    commit = _Commit(
        PackageCommitLifecycleOwner(
            kernel=fixture.kernel,
            committed_sets=fixture.committed_sets,
            pin_journal=fixture.pin_journal,
        ),
        crash_after_commit=crash_after_commit,
    )
    return closure, pins, staging, commit


def test_adoption_transaction_composes_exact_complete_b_sequence_and_replays(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    closure, pins, staging, commit = _success_components(fixture)
    adapter = _adapter(
        fixture,
        closure=closure,
        pins=pins,
        staging=staging,
        commit=commit,
    )
    owner, fences, legacy = _outer(fixture, adapter)

    adopted = owner.adopt(fixture.request)
    replay = owner.adopt(fixture.request)

    assert adopted == replay
    assert adopted.disposition == "adopted"
    assert adopted.receipt is not None
    assert adopted.receipt.publication.committed_set.root_ref.plugin_id == PLUGIN_ID
    assert closure.calls == pins.calls == staging.stage_calls == 1
    assert staging.resume_calls == 0
    assert commit.calls == 2
    assert fences.calls == legacy.calls == 4
    committed = fixture.kernel.status(OPERATION_ID)
    assert committed is not None and committed.disposition == "committed"
    assert SECRET not in repr(adapter)
    assert SECRET not in repr(adopted)


@pytest.mark.parametrize(
    ("code", "disposition"),
    (
        ("package_source_unauthorized", "rejected"),
        ("package_operation_timed_out", "retryable_failure"),
    ),
)
def test_adoption_transaction_preserves_acquisition_failure_without_later_effects(
    tmp_path: Path,
    code: str,
    disposition: str,
) -> None:
    fixture = _fixture(tmp_path)
    closure = _FailingClosure(fixture, code)
    never = _Never()
    adapter = _adapter(
        fixture,
        closure=closure,
        pins=never,
        staging=never,
        commit=never,
    )
    owner, _fences, _legacy = _outer(fixture, adapter)

    result = owner.adopt(fixture.request)

    assert result.disposition == disposition
    assert result.code == code
    assert result.receipt is None
    assert closure.calls == 1
    assert never.calls == 0
    assert fixture.committed_sets.records() == ()
    assert fixture.pin_journal.records() == ()


def test_adoption_transaction_refuses_product_substitution_before_effect(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    substituted = PackageLegacyAdoptionRequestV1.create(
        current_fence=fixture.fence,
        legacy_state=fixture.legacy,
        operation_id=fixture.request.operation_id,
        transaction_request_fingerprint=(
            fixture.request.transaction_request_fingerprint
        ),
        expected_classification_fingerprint=(
            fixture.request.expected_classification_fingerprint
        ),
        expected_attempt_epoch=fixture.request.expected_attempt_epoch,
        product_id="agent",
        scope_id=fixture.request.scope_id,
        installation_id=fixture.request.installation_id,
        plugin_id=fixture.request.plugin_id,
    )
    never = _Never()
    adapter = _adapter(
        fixture,
        closure=never,
        pins=never,
        staging=never,
        commit=never,
    )
    owner, _fences, _legacy = _outer(fixture, adapter)

    result = owner.adopt(substituted)

    assert result.disposition == "rejected"
    assert result.code == "package_operation_identity_conflict"
    assert never.calls == 0
    current = fixture.kernel.status(OPERATION_ID)
    assert current is not None and current.phase == "classified"


def test_adoption_transaction_resumes_set_published_without_prior_phase_replay(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    closure, pins, staging, _commit = _success_components(fixture)
    closure_result = closure.execute(fixture.execution)
    assert closure_result.candidate is fixture.candidate
    pinned = pins.pin(
        fixture.candidate,
        recovery_identity="legacy-adoption-recovery",
    )
    assert pinned.candidate is fixture.candidate
    staged = staging.stage_and_publish(fixture.candidate)
    assert staged.status.phase == "set_published"
    never = _Never()
    commit = _Commit(
        PackageCommitLifecycleOwner(
            kernel=fixture.kernel,
            committed_sets=fixture.committed_sets,
            pin_journal=fixture.pin_journal,
        )
    )
    adapter = _adapter(
        fixture,
        closure=never,
        pins=never,
        staging=never,
        commit=commit,
    )
    owner, _fences, _legacy = _outer(fixture, adapter)

    result = owner.adopt(fixture.request)

    assert result.disposition == "adopted"
    assert never.calls == 0
    assert commit.calls == 1


def test_adoption_transaction_refuses_bare_transaction_pin_without_reacquisition(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    closure, pins, _staging, _commit = _success_components(fixture)
    closure_result = closure.execute(fixture.execution)
    assert closure_result.candidate is fixture.candidate
    pinned = pins.pin(
        fixture.candidate,
        recovery_identity="legacy-adoption-recovery",
    )
    assert pinned.status.phase == "transaction_pinned"
    fixture.candidate.suspend_for_recovery()
    never = _Never()
    adapter = _adapter(
        fixture,
        closure=never,
        pins=never,
        staging=never,
        commit=never,
    )
    owner, _fences, _legacy = _outer(fixture, adapter)

    result = owner.adopt(fixture.request)

    assert result.disposition == "rejected"
    assert result.code == "package_route_unavailable"
    assert never.calls == 0
    current = fixture.kernel.status(OPERATION_ID)
    assert current is not None and current.phase == "transaction_pinned"


def test_adoption_transaction_resumes_staging_after_receipts_are_durable(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    closure, pins, staging, commit = _success_components(fixture)
    closure_result = closure.execute(fixture.execution)
    assert closure_result.candidate is fixture.candidate
    pinned = pins.pin(
        fixture.candidate,
        recovery_identity="legacy-adoption-recovery",
    )
    assert pinned.status.phase == "transaction_pinned"
    staged = _advance(fixture.kernel, pinned.status, "staging")
    assert staged.phase == "staging"
    fixture.candidate.suspend_for_recovery()
    never = _Never()
    adapter = _adapter(
        fixture,
        closure=never,
        pins=never,
        staging=staging,
        commit=commit,
    )
    owner, _fences, _legacy = _outer(fixture, adapter)

    result = owner.adopt(fixture.request)

    assert result.disposition == "adopted"
    assert staging.stage_calls == 0
    assert staging.resume_calls == 1
    assert never.calls == 0
    assert commit.calls == 1


def test_adoption_transaction_suspends_candidate_when_staging_crashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    closure, pins, _staging, _commit = _success_components(fixture)
    suspension_calls = 0
    suspend = fixture.candidate.suspend_for_recovery

    def counted_suspend() -> None:
        nonlocal suspension_calls
        suspension_calls += 1
        suspend()

    monkeypatch.setattr(fixture.candidate, "suspend_for_recovery", counted_suspend)

    class _CrashingStaging:
        def stage_and_publish(self, _candidate: object) -> object:
            raise _CrashDuringStaging

        def resume(self, _operation_id: str) -> object:
            raise AssertionError("resume must not run")

    never = _Never()
    adapter = _adapter(
        fixture,
        closure=closure,
        pins=pins,
        staging=_CrashingStaging(),
        commit=never,
    )
    owner, _fences, _legacy = _outer(fixture, adapter)

    with pytest.raises(_CrashDuringStaging):
        owner.adopt(fixture.request)

    assert suspension_calls == 1
    assert never.calls == 0
    current = fixture.kernel.status(OPERATION_ID)
    assert current is not None and current.phase == "transaction_pinned"


def test_adoption_transaction_crash_after_commit_replays_without_prior_effects(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    closure, pins, staging, crashing_commit = _success_components(
        fixture,
        crash_after_commit=True,
    )
    crashing = _adapter(
        fixture,
        closure=closure,
        pins=pins,
        staging=staging,
        commit=crashing_commit,
    )
    owner, _fences, _legacy = _outer(fixture, crashing)

    with pytest.raises(_CrashAfterCommit):
        owner.adopt(fixture.request)

    committed = fixture.kernel.status(OPERATION_ID)
    assert committed is not None and committed.disposition == "committed"
    never = _Never()
    replay_commit = _Commit(
        PackageCommitLifecycleOwner(
            kernel=fixture.kernel,
            committed_sets=fixture.committed_sets,
            pin_journal=fixture.pin_journal,
        )
    )
    replay = _adapter(
        fixture,
        closure=never,
        pins=never,
        staging=never,
        commit=replay_commit,
    )
    replay_owner, _replay_fences, _replay_legacy = _outer(fixture, replay)

    result = replay_owner.adopt(fixture.request)

    assert result.disposition == "adopted"
    assert never.calls == 0
    assert replay_commit.calls == 1


def test_adoption_transaction_rejects_phase_result_not_owned_by_kernel(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    current = fixture.kernel.status(OPERATION_ID)
    assert current is not None
    lied = PackageLifecycleStatusV1(
        operation_id=current.operation_id,
        request_fingerprint=current.request_fingerprint,
        phase="closure_verified",
        disposition="active",
        attempt_epoch=current.attempt_epoch,
        journal_revision=current.journal_revision,
        attempt_revision=current.attempt_revision,
        classification=current.classification,
    )

    class _LyingClosure:
        def execute(self, _execution: object) -> PackageClosureExecutionResult:
            return PackageClosureExecutionResult(
                status=lied,
                candidate=fixture.candidate,
            )

    never = _Never()
    adapter = _adapter(
        fixture,
        closure=_LyingClosure(),
        pins=never,
        staging=never,
        commit=never,
    )
    owner, _fences, _legacy = _outer(fixture, adapter)

    result = owner.adopt(fixture.request)

    assert result.disposition == "rejected"
    assert result.code == "package_operation_identity_conflict"
    assert never.calls == 0
