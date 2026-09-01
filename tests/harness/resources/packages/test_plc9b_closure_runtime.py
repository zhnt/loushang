from __future__ import annotations

import base64
import csv
import io
import stat
import zipfile
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import cast

from loushang.harness.resources.packages.plugin_lifecycle import (
    PackageClassificationBasisFactV1,
    PackageClassificationFactsV1,
    PackageLifecycleCancelRequestV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleJournal,
    PackageLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionSinkPort,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageQuarantineCleanupTargetV1,
    PackageQuarantineStore,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
    PackageQuarantineCleanupOwner,
    PackageQuarantineCleanupStatusV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    PackageClosureBudgetV1,
    PackageClosureVerificationError,
    PackageClosureVerifier,
    PackageResolutionEnvironmentV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionBasisV1,
    PackageClosureResolutionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencyCleanupDebtError,
    PackageDependencySelectionRequestV1,
    PackageDependencySelectionV1,
    PackageRecursiveClosureOwner,
    PackageRecursiveClosureRequestV2,
    VerifiedPackageClosureCandidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_runtime import (
    PackageClosureExecutionRequestV2,
    PackageClosureLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PluginBoundPackageClassificationV1,
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.runtime import (
    PackageArtifactExecutionRequestV1,
    PackageArtifactExecutionResult,
    PackageArtifactLifecycleOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerifier,
    VerifiedWheelCandidate,
)

OPERATION_ID = "operation-closure-runtime"


class _ClassificationAuthority:
    def classification_facts(
        self,
        _request: PackageLifecycleIngressRequestV1,
    ) -> PackageClassificationFactsV1:
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
                    owner_revision=f"revision:{kind}:1",
                )
                for kind in kinds
            ),
            policy_revision="classification-policy:1",
            classifier_epoch=1,
        )


@dataclass
class _Recheck:
    def recheck(
        self,
        _request: object,
        prior: PluginBoundPackageClassificationV1,
    ) -> PluginBoundPackageClassificationV1:
        return prior


@dataclass
class _Stream:
    envelope: AuthenticatedSourceEnvelopeV1
    payload: bytes

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        sink.begin_request()
        sink.write(self.payload)
        return SourceAdapterResultV1(disposition="complete")


@dataclass
class _SourceAuthority:
    payloads: dict[str, bytes]
    calls: list[str] = field(default_factory=list)

    def authorize(self, request: PackageAcquisitionRequestV1) -> _Stream:
        self.calls.append(request.canonical_source_identity)
        payload = self.payloads[request.canonical_source_identity]
        return _Stream(
            envelope=AuthenticatedSourceEnvelopeV1(
                operation_id=request.operation_id,
                node_id=request.node_id,
                canonical_source_identity=request.canonical_source_identity,
                origin_kind="https",
                authentication_decision="authorized",
                authority_id="source-authority:test",
                requested_locator_digest=request.requested_locator_digest,
                expected_artifact_digest=sha256(payload).hexdigest(),
                redirect_policy_revision="redirect-policy:1",
                policy_revision=request.policy_revision,
                capture_epoch=1,
            ),
            payload=payload,
        )


@dataclass(frozen=True)
class _Selected:
    version: str
    source: str
    filename: str
    digest: str


@dataclass
class _Resolver:
    selections: dict[str, _Selected]
    calls: list[str] = field(default_factory=list)

    def resolve(
        self,
        request: PackageDependencySelectionRequestV1,
    ) -> PackageDependencySelectionV1:
        self.calls.append(request.requirement.project_name)
        selected = self.selections[request.requirement.project_name]
        return PackageDependencySelectionV1(
            operation_id=request.operation_id,
            attempt_epoch=request.attempt_epoch,
            parent_node_id=request.parent_node_id,
            request_fingerprint=request.request_fingerprint,
            resolution_environment_fingerprint=(
                request.resolution_environment_fingerprint
            ),
            requirement_fingerprint=request.requirement_fingerprint,
            project_name=request.requirement.project_name,
            version=selected.version,
            canonical_source_identity=selected.source,
            wheel_filename=selected.filename,
            expected_artifact_digest=selected.digest,
            resolver_id="resolver:test",
            resolver_revision="resolver-revision:1",
        )


@dataclass
class _Root:
    suspended: bool = False
    cleaned: bool = False

    def suspend_for_recovery(self) -> None:
        self.suspended = True

    def cleanup(self) -> None:
        self.cleaned = True


@dataclass
class _ArtifactOwner:
    kernel: PackageLifecycleOwner
    root: _Root
    calls: int = 0

    def execute(
        self,
        _execution: PackageArtifactExecutionRequestV1,
    ) -> PackageArtifactExecutionResult:
        self.calls += 1
        status = self.kernel.status(OPERATION_ID)
        assert status is not None
        candidate = (
            cast(VerifiedWheelCandidate, self.root)
            if status.disposition == "active"
            and status.phase in {"extracted", "resolving_closure", "closure_verified"}
            else None
        )
        return PackageArtifactExecutionResult(status=status, candidate=candidate)


@dataclass
class _ClosureBuilder:
    changed: bool = False
    reject: bool = False
    cleanup_status: PackageQuarantineCleanupStatusV1 | None = None
    calls: int = 0

    def build(
        self,
        _root: VerifiedWheelCandidate,
        request: PackageRecursiveClosureRequestV2,
    ) -> VerifiedPackageClosureCandidate:
        self.calls += 1
        if self.cleanup_status is not None:
            raise PackageDependencyCleanupDebtError(
                rejection_code=self.cleanup_status.rejection_code,
                cleanup_status=self.cleanup_status,
            )
        if self.reject:
            raise PackageClosureVerificationError(
                "private resolver detail",
                code="package_closure_conflict",
            )
        return VerifiedPackageClosureCandidate(
            plan=_plan(
                attempt_epoch=request.attempt_epoch,
                environment_fingerprint=(request.resolution_environment.fingerprint),
                version="1.1" if self.changed else "1.0",
            ),
            candidates=(),
        )


@dataclass
class _CancellingClosureBuilder(_ClosureBuilder):
    kernel: PackageLifecycleOwner | None = None

    def build(
        self,
        root: VerifiedWheelCandidate,
        request: PackageRecursiveClosureRequestV2,
    ) -> VerifiedPackageClosureCandidate:
        closure = super().build(root, request)
        assert self.kernel is not None
        current = self.kernel.status(OPERATION_ID)
        assert current is not None
        self.kernel.cancel(
            PackageLifecycleCancelRequestV1(
                operation_id=OPERATION_ID,
                request_fingerprint=current.request_fingerprint,
                expected_phase=current.phase,
                expected_journal_revision=current.journal_revision,
                expected_attempt_epoch=current.attempt_epoch,
            )
        )
        return VerifiedPackageClosureCandidate(
            plan=closure.plan,
            candidates=(root,),
        )


def _environment() -> PackageResolutionEnvironmentV1:
    return PackageResolutionEnvironmentV1.from_mapping(
        {
            "implementation_name": "cpython",
            "implementation_version": "3.11.10",
            "os_name": "posix",
            "platform_machine": "x86_64",
            "platform_python_implementation": "CPython",
            "platform_release": "fixture",
            "platform_system": "Linux",
            "platform_version": "fixture",
            "python_full_version": "3.11.10",
            "python_version": "3.11",
            "sys_platform": "linux",
        },
        supported_tags=("py3-none-any",),
    )


def _wheel_filename(project: str, version: str) -> str:
    return f"{project.replace('-', '_')}-{version}-py3-none-any.whl"


def _record_digest(payload: bytes) -> str:
    encoded = base64.urlsafe_b64encode(sha256(payload).digest()).rstrip(b"=")
    return "sha256=" + encoded.decode()


def _wheel_bytes(
    project: str,
    version: str,
    *,
    requires_dist: tuple[str, ...] = (),
) -> bytes:
    normalized = project.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    metadata = (
        f"Metadata-Version: 2.1\nName: {project}\nVersion: {version}\n"
        + "".join(f"Requires-Dist: {requirement}\n" for requirement in requires_dist)
        + "\n"
    ).encode()
    files = {
        f"{normalized}/__init__.py": b"VALUE = 1\n",
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
        ),
        f"{dist_info}/METADATA": metadata,
    }
    rows = [
        (name, _record_digest(payload), str(len(payload)))
        for name, payload in files.items()
    ]
    rows.append((f"{dist_info}/RECORD", "", ""))
    record = io.StringIO(newline="")
    csv.writer(record, lineterminator="\n").writerows(rows)
    files[f"{dist_info}/RECORD"] = record.getvalue().encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return output.getvalue()


def _plan(
    *,
    attempt_epoch: int,
    environment_fingerprint: str,
    version: str = "1.0",
) -> VerifiedClosurePlanV2:
    root = VerifiedClosurePlanNodeV2(
        node_id="root",
        role="root",
        distribution="root-plugin",
        version=version,
        canonical_source_identity="https://packages.example.test/root.whl",
        source_envelope_fingerprint="1" * 64,
        acquisition_receipt_fingerprint="2" * 64,
        wheel_evidence_fingerprint="3" * 64,
        artifact_digest="4" * 64,
        extraction_tree_digest="5" * 64,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
    )
    return VerifiedClosurePlanV2.create(
        operation_id=OPERATION_ID,
        attempt_epoch=attempt_epoch,
        root_node_id="root",
        resolution_environment_fingerprint=environment_fingerprint,
        nodes=(root,),
        max_depth=0,
    )


def _ingress(
    environment: PackageResolutionEnvironmentV1,
) -> PackageLifecycleIngressRequestV1:
    return PackageLifecycleIngressRequestV1(
        operation_id=OPERATION_ID,
        action="install",
        product_id="coding",
        scope_id="workspace:closure-runtime",
        requested_package="root-plugin==1.0",
        requested_plugin_id="root.plugin",
        source_locator="https://packages.example.test/root.whl",
        policy_revision="package-policy:1",
        quota_profile_revision="quota:1",
        resolution_environment_fingerprint=environment.fingerprint,
    )


def _setup(
    tmp_path: Path,
    *,
    phase: str = "extracted",
    builder: _ClosureBuilder | None = None,
):
    environment = _environment()
    kernel = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "lifecycle.jsonl"),
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    status = kernel.submit(_ingress(environment))
    for next_phase in (
        "acquiring",
        "acquired",
        "inspecting",
        "extracted",
        "resolving_closure",
    ):
        if status.phase == phase:
            break
        status = kernel.advance(
            OPERATION_ID,
            next_phase=next_phase,  # type: ignore[arg-type]
            expected_phase=status.phase,
            expected_journal_revision=status.journal_revision,
            expected_attempt_epoch=status.attempt_epoch,
        )
    assert status.phase == phase
    root = _Root()
    artifact_owner = _ArtifactOwner(kernel, root)
    closure_builder = builder or _ClosureBuilder()
    resolution = PackageClosureResolutionJournal(tmp_path / "closure.jsonl")
    owner = PackageClosureLifecycleOwner(
        kernel=kernel,
        artifact_owner=artifact_owner,
        closure_builder=closure_builder,
        resolution_journal=resolution,
    )
    execution = PackageClosureExecutionRequestV2(
        artifact=PackageArtifactExecutionRequestV1(
            operation_id=OPERATION_ID,
            request_fingerprint=status.request_fingerprint,
            expected_attempt_epoch=status.attempt_epoch,
            wheel_filename="root_plugin-1.0-py3-none-any.whl",
        ),
        resolution_environment=environment,
        budgets=PackageClosureBudgetV1(),
    )
    return (
        kernel,
        owner,
        artifact_owner,
        closure_builder,
        resolution,
        execution,
        root,
    )


def _basis(
    kernel: PackageLifecycleOwner,
    execution: PackageClosureExecutionRequestV2,
) -> PackageClosureResolutionBasisV1:
    request = kernel.journal.request(OPERATION_ID)
    assert request is not None
    return PackageClosureResolutionBasisV1(
        operation_id=OPERATION_ID,
        attempt_epoch=execution.artifact.expected_attempt_epoch,
        request_fingerprint=execution.artifact.request_fingerprint,
        policy_revision=request.policy_revision,
        quota_profile_revision=request.quota_profile_revision,
        resolution_environment=execution.resolution_environment,
        budgets=execution.budgets,
        root_extras=execution.root_extras,
    )


def test_closure_runtime_commits_plan_before_closure_verified_phase(
    tmp_path: Path,
) -> None:
    kernel, owner, _artifact, builder, resolution, execution, _root = _setup(tmp_path)

    result = owner.execute(execution)

    assert result.status.phase == "closure_verified"
    assert result.status.disposition == "active"
    assert result.candidate is not None
    assert builder.calls == 1
    assert resolution.plan(operation_id=OPERATION_ID, attempt_epoch=1) == (
        result.candidate.plan
    )
    assert kernel.status(OPERATION_ID) == result.status


def test_closure_runtime_replays_plan_append_crash_and_verified_phase(
    tmp_path: Path,
) -> None:
    (
        kernel,
        owner,
        _artifact,
        builder,
        resolution,
        execution,
        _root,
    ) = _setup(tmp_path, phase="resolving_closure")
    plan = _plan(
        attempt_epoch=1,
        environment_fingerprint=execution.resolution_environment.fingerprint,
    )
    resolution.bind_basis(_basis(kernel, execution))
    resolution.append_plan(
        request_fingerprint=execution.artifact.request_fingerprint,
        plan=plan,
    )

    recovered = owner.execute(execution)
    replayed = owner.execute(execution)

    assert recovered.status.phase == "closure_verified"
    assert replayed.status == recovered.status
    assert replayed.candidate is not None
    assert replayed.candidate.plan == plan
    assert builder.calls == 2
    assert len(resolution.records()) == 2


def test_closure_runtime_rejects_changed_durable_plan_without_phase_advance(
    tmp_path: Path,
) -> None:
    builder = _ClosureBuilder(changed=True)
    kernel, owner, _artifact, _builder, resolution, execution, _root = _setup(
        tmp_path,
        phase="resolving_closure",
        builder=builder,
    )
    resolution.bind_basis(_basis(kernel, execution))
    resolution.append_plan(
        request_fingerprint=execution.artifact.request_fingerprint,
        plan=_plan(
            attempt_epoch=1,
            environment_fingerprint=execution.resolution_environment.fingerprint,
        ),
    )

    result = owner.execute(execution)

    assert result.status.phase == "resolving_closure"
    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_operation_identity_conflict"
    assert kernel.status(OPERATION_ID) == result.status
    assert len(resolution.records()) == 2


def test_closure_runtime_records_typed_closure_failure_without_secret_echo(
    tmp_path: Path,
) -> None:
    builder = _ClosureBuilder(reject=True)
    _kernel, owner, _artifact, _builder, resolution, execution, _root = _setup(
        tmp_path,
        phase="resolving_closure",
        builder=builder,
    )

    result = owner.execute(execution)

    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_closure_conflict"
    assert "private resolver detail" not in str(result.status)
    assert [record.evidence_kind for record in resolution.records()] == [
        "resolution_basis"
    ]


def test_closure_runtime_projects_dependency_cleanup_debt_separately(
    tmp_path: Path,
) -> None:
    target_values = {
        "attemptEpoch": 1,
        "attemptIdentity": [3, 4],
        "attemptName": "attempt-dependency",
        "nodeId": "dependency-node",
        "operationId": OPERATION_ID,
        "storeIdentity": [1, 2],
    }
    target = PackageQuarantineCleanupTargetV1(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        node_id="dependency-node",
        store_identity=(1, 2),
        attempt_identity=(3, 4),
        attempt_name="attempt-dependency",
        cleanup_id=sha256(canonical_json_bytes(target_values)).hexdigest(),
    )
    cleanup_status = PackageQuarantineCleanupJournal(
        tmp_path / "cleanup.jsonl"
    ).append_pending(
        target,
        rejection_code="package_wheel_metadata_invalid",
        rejection_stage="inspecting",
    )
    builder = _ClosureBuilder(cleanup_status=cleanup_status)
    _kernel, owner, _artifact, _builder, _resolution, execution, _root = _setup(
        tmp_path,
        phase="resolving_closure",
        builder=builder,
    )

    result = owner.execute(execution)

    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_closure_artifact_invalid"
    assert result.cleanup_status == cleanup_status
    assert result.cleanup_status.failure is not None
    assert result.cleanup_status.failure.retry_domain == "cleanup"


def test_closure_runtime_terminal_cancel_does_not_reenter_builder(
    tmp_path: Path,
) -> None:
    kernel, owner, artifact, builder, resolution, execution, _root = _setup(
        tmp_path,
        phase="resolving_closure",
    )
    current = kernel.status(OPERATION_ID)
    assert current is not None
    cancelled = kernel.cancel(
        PackageLifecycleCancelRequestV1(
            operation_id=OPERATION_ID,
            request_fingerprint=current.request_fingerprint,
            expected_phase=current.phase,
            expected_journal_revision=current.journal_revision,
            expected_attempt_epoch=current.attempt_epoch,
        )
    )

    result = owner.execute(execution)

    assert result.status == cancelled
    assert result.candidate is None
    assert artifact.calls == 1
    assert builder.calls == 0
    assert resolution.records() == ()


def test_closure_runtime_releases_candidate_when_cancel_wins_final_phase_cas(
    tmp_path: Path,
) -> None:
    builder = _CancellingClosureBuilder()
    kernel, owner, _artifact, _builder, resolution, execution, root = _setup(
        tmp_path,
        phase="resolving_closure",
        builder=builder,
    )
    builder.kernel = kernel

    result = owner.execute(execution)

    current = kernel.status(OPERATION_ID)
    assert current is not None
    assert result.status == current
    assert result.status.disposition == "cancelled"
    assert result.candidate is None
    assert root.suspended is True
    assert [record.evidence_kind for record in resolution.records()] == [
        "resolution_basis",
        "verified_plan",
    ]


def test_closure_runtime_rejects_environment_change_before_builder(
    tmp_path: Path,
) -> None:
    kernel, owner, artifact, builder, resolution, execution, root = _setup(
        tmp_path,
        phase="resolving_closure",
    )
    changed_environment = PackageResolutionEnvironmentV1.from_mapping(
        execution.resolution_environment.as_marker_mapping()
        | {"python_full_version": "3.12.0", "python_version": "3.12"},
        supported_tags=("py3-none-any",),
    )
    changed = PackageClosureExecutionRequestV2(
        artifact=execution.artifact,
        resolution_environment=changed_environment,
        budgets=execution.budgets,
    )

    result = owner.execute(changed)

    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_operation_identity_conflict"
    assert kernel.status(OPERATION_ID) is not None
    assert kernel.status(OPERATION_ID).disposition == "active"  # type: ignore[union-attr]
    assert artifact.calls == 0
    assert builder.calls == 0
    assert root.cleaned is False
    assert resolution.records() == ()


def test_closure_runtime_rejects_changed_budget_before_root_or_dependency_io(
    tmp_path: Path,
) -> None:
    kernel, owner, artifact, builder, resolution, execution, _root = _setup(
        tmp_path,
        phase="resolving_closure",
    )
    resolution.bind_basis(_basis(kernel, execution))
    changed = PackageClosureExecutionRequestV2(
        artifact=execution.artifact,
        resolution_environment=execution.resolution_environment,
        budgets=PackageClosureBudgetV1(max_nodes=1),
    )

    result = owner.execute(changed)

    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_operation_identity_conflict"
    assert artifact.calls == 0
    assert builder.calls == 0
    assert len(resolution.records()) == 1


def test_closure_runtime_requires_root_extras_to_match_lifecycle_request(
    tmp_path: Path,
) -> None:
    _kernel, owner, artifact, builder, resolution, execution, _root = _setup(
        tmp_path,
        phase="resolving_closure",
    )
    changed = PackageClosureExecutionRequestV2(
        artifact=execution.artifact,
        resolution_environment=execution.resolution_environment,
        budgets=execution.budgets,
        root_extras=("fast",),
    )

    result = owner.execute(changed)

    assert result.status.disposition == "rejected"
    assert result.status.failure is not None
    assert result.status.failure.code == "package_operation_identity_conflict"
    assert artifact.calls == 0
    assert builder.calls == 0
    assert resolution.records() == ()


def test_real_closure_runtime_recovers_graph_without_resolver_or_source_io(
    tmp_path: Path,
) -> None:
    environment = _environment()
    root_payload = _wheel_bytes(
        "root-plugin",
        "1.0",
        requires_dist=("dependency==2",),
    )
    dependency_payload = _wheel_bytes("dependency", "2.0")
    root_source = "https://packages.example.test/root_plugin-1.0-py3-none-any.whl"
    dependency_source = "https://packages.example.test/dependency-2.0-py3-none-any.whl"
    authority = _SourceAuthority(
        {
            root_source: root_payload,
            dependency_source: dependency_payload,
        }
    )
    resolver = _Resolver(
        {
            "dependency": _Selected(
                version="2.0",
                source=dependency_source,
                filename=_wheel_filename("dependency", "2.0"),
                digest=sha256(dependency_payload).hexdigest(),
            )
        }
    )
    kernel = PackageLifecycleOwner(
        journal=PackageLifecycleJournal(tmp_path / "lifecycle.jsonl"),
        classification_authority=_ClassificationAuthority(),
        enabled=True,
    )
    status = kernel.submit(
        PackageLifecycleIngressRequestV1(
            operation_id=OPERATION_ID,
            action="install",
            product_id="coding",
            scope_id="workspace:closure-runtime",
            requested_package="root-plugin==1.0",
            requested_plugin_id="root.plugin",
            source_locator=root_source,
            policy_revision="package-policy:1",
            quota_profile_revision="quota:1",
            resolution_environment_fingerprint=environment.fingerprint,
        )
    )
    store = PackageQuarantineStore(tmp_path / "quarantine")
    acquisition = PackageAcquisitionOwner(
        source_authority=authority,
        quarantine_store=store,
    )
    evidence = PackageArtifactEvidenceJournal(tmp_path / "evidence.jsonl")
    resolution = PackageClosureResolutionJournal(tmp_path / "closure.jsonl")
    wheel_verifier = PackageWheelVerifier()
    acquisition_budgets = PackageAcquisitionBudgetV1(
        max_transport_bytes=128 * 1024,
        max_requests=1,
        max_redirects=0,
        max_wall_time_ms=1000,
    )
    inspection_budgets = PackageInspectionBudgetV1()
    cleanup_owner = PackageQuarantineCleanupOwner(
        journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
        store=store,
    )
    artifact_owner = PackageArtifactLifecycleOwner(
        kernel=kernel,
        classification_recheck=_Recheck(),
        acquisition_owner=acquisition,
        evidence_journal=evidence,
        cleanup_owner=cleanup_owner,
        wheel_verifier=wheel_verifier,
        acquisition_budgets=acquisition_budgets,
        inspection_budgets=inspection_budgets,
        supported_tags=frozenset({"py3-none-any"}),
    )
    recursive_owner = PackageRecursiveClosureOwner(
        resolver=resolver,
        acquisition_owner=acquisition,
        evidence_journal=evidence,
        wheel_verifier=wheel_verifier,
        closure_verifier=PackageClosureVerifier(),
        acquisition_budgets=acquisition_budgets,
        inspection_budgets=inspection_budgets,
        cleanup_owner=cleanup_owner,
        selection_journal=resolution,
    )
    owner = PackageClosureLifecycleOwner(
        kernel=kernel,
        artifact_owner=artifact_owner,
        closure_builder=recursive_owner,
        resolution_journal=resolution,
    )
    execution = PackageClosureExecutionRequestV2(
        artifact=PackageArtifactExecutionRequestV1(
            operation_id=OPERATION_ID,
            request_fingerprint=status.request_fingerprint,
            expected_attempt_epoch=1,
            wheel_filename=_wheel_filename("root-plugin", "1.0"),
        ),
        resolution_environment=environment,
        budgets=PackageClosureBudgetV1(),
    )

    first = owner.execute(execution)

    assert first.status.phase == "closure_verified"
    assert first.candidate is not None
    assert first.candidate.plan.node_count == 2
    assert resolver.calls == ["dependency"]
    assert len(authority.calls) == 2
    assert [record.evidence_kind for record in resolution.records()] == [
        "resolution_basis",
        "selection",
        "verified_plan",
    ]
    assert len(evidence.records()) == 6
    first_plan = first.candidate.plan
    first.candidate.suspend_for_recovery()
    resolver.calls.clear()

    replayed = owner.execute(execution)

    assert replayed.status == first.status
    assert replayed.candidate is not None
    assert replayed.candidate.plan == first_plan
    assert resolver.calls == []
    assert len(authority.calls) == 2
    assert len(resolution.records()) == 3
    assert len(evidence.records()) == 6
    replayed.candidate.cleanup()
    assert store.attempt_names() == ()
