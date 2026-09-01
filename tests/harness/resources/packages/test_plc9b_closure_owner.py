from __future__ import annotations

import base64
import csv
import io
import stat
import zipfile
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionReceiptV1,
    BoundedAcquisitionSinkPort,
    PackageAcquisitionBudgetV1,
    PackageAcquisitionOwner,
    PackageAcquisitionRequestV1,
    PackageAuthenticatedSourceEvidenceV1,
    PackageQuarantineStore,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.cleanup import (
    PackageQuarantineCleanupJournal,
    PackageQuarantineCleanupOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    PackageClosureBudgetV1,
    PackageClosureVerificationError,
    PackageClosureVerifier,
    PackageResolutionEnvironmentV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_journal import (
    PackageClosureResolutionBasisV1,
    PackageClosureResolutionJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure_owner import (
    PackageDependencyCleanupDebtError,
    PackageDependencyResolutionError,
    PackageDependencySelectionRequestV1,
    PackageDependencySelectionV1,
    PackageRecursiveClosureOwner,
    PackageRecursiveClosureRequestV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.phase_evidence import (
    PackageArtifactEvidenceJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    PackageInspectionBudgetV1,
    PackageWheelVerificationError,
    PackageWheelVerifier,
    VerifiedWheelCandidate,
)

OPERATION_ID = "operation-recursive-closure"
REQUEST_FINGERPRINT = "9" * 64
POLICY_REVISION = "source-policy:1"


def _environment() -> PackageResolutionEnvironmentV1:
    return PackageResolutionEnvironmentV1.from_mapping(
        {
            "implementation_name": "cpython",
            "implementation_version": "3.11.10",
            "os_name": "posix",
            "platform_machine": "x86_64",
            "platform_python_implementation": "CPython",
            "platform_release": "test",
            "platform_system": "Linux",
            "platform_version": "test",
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
    requires_python: str | None = None,
    provides_extra: tuple[str, ...] = ("a", "b", "fast"),
) -> bytes:
    normalized = project.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    metadata = (
        f"Metadata-Version: 2.1\nName: {project}\nVersion: {version}\n"
        + "".join(f"Provides-Extra: {extra}\n" for extra in provides_extra)
        + ("" if requires_python is None else f"Requires-Python: {requires_python}\n")
        + "".join(f"Requires-Dist: {item}\n" for item in requires_dist)
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


@dataclass
class _Stream:
    envelope: AuthenticatedSourceEnvelopeV1
    payload: bytes

    def transfer_to(self, sink: BoundedAcquisitionSinkPort) -> SourceAdapterResultV1:
        sink.begin_request()
        sink.write(self.payload)
        return SourceAdapterResultV1(disposition="complete")


@dataclass
class _Authority:
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
class _SelectedArtifact:
    version: str
    source: str
    filename: str
    digest: str


@dataclass
class _Resolver:
    selections: dict[str, _SelectedArtifact]
    calls: list[PackageDependencySelectionRequestV1] = field(default_factory=list)
    change_parent: bool = False

    def resolve(
        self,
        request: PackageDependencySelectionRequestV1,
    ) -> PackageDependencySelectionV1:
        self.calls.append(request)
        selected = self.selections[request.requirement.project_name]
        return PackageDependencySelectionV1(
            operation_id=request.operation_id,
            attempt_epoch=request.attempt_epoch,
            parent_node_id=(
                "changed-parent" if self.change_parent else request.parent_node_id
            ),
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


class _DependencyCleanupDebtWheelVerifier(PackageWheelVerifier):
    def verify(self, candidate, **kwargs):  # type: ignore[no-untyped-def]
        if candidate.receipt.node_id != "root":
            raise PackageWheelVerificationError(
                "private cleanup failure",
                code="package_quarantine_cleanup_retryable",
                stage="inspecting",
                rejection_code="package_wheel_metadata_invalid",
                rejection_stage="inspecting",
            )
        return super().verify(candidate, **kwargs)


@dataclass
class _Fixture:
    owner: PackageRecursiveClosureOwner
    root: VerifiedWheelCandidate
    request: PackageRecursiveClosureRequestV2
    resolver: _Resolver
    authority: _Authority
    evidence: PackageArtifactEvidenceJournal
    store: PackageQuarantineStore
    acquisition_owner: PackageAcquisitionOwner
    wheel_verifier: PackageWheelVerifier
    resolution: PackageClosureResolutionJournal
    cleanup: PackageQuarantineCleanupOwner


def _fixture(
    tmp_path: Path,
    packages: dict[str, tuple[str, tuple[str, ...]]],
    *,
    budgets: PackageClosureBudgetV1 | None = None,
    root_requires_python: str | None = None,
    root_provides_extra: tuple[str, ...] | None = None,
    wheel_verifier: PackageWheelVerifier | None = None,
) -> _Fixture:
    payloads: dict[str, bytes] = {}
    selections: dict[str, _SelectedArtifact] = {}
    for project, (version, requirements) in packages.items():
        payload = _wheel_bytes(
            project,
            version,
            requires_dist=requirements,
            requires_python=(
                root_requires_python if project == "root-plugin" else None
            ),
            provides_extra=(
                root_provides_extra
                if project == "root-plugin" and root_provides_extra is not None
                else ("a", "b", "fast")
            ),
        )
        source = f"https://packages.example.test/{_wheel_filename(project, version)}"
        payloads[source] = payload
        selections[project] = _SelectedArtifact(
            version=version,
            source=source,
            filename=_wheel_filename(project, version),
            digest=sha256(payload).hexdigest(),
        )
    authority = _Authority(payloads)
    resolver = _Resolver(selections)
    store = PackageQuarantineStore(tmp_path / "quarantine")
    cleanup = PackageQuarantineCleanupOwner(
        journal=PackageQuarantineCleanupJournal(tmp_path / "cleanup.jsonl"),
        store=store,
    )
    acquisition = PackageAcquisitionOwner(
        source_authority=authority,
        quarantine_store=store,
    )
    evidence = PackageArtifactEvidenceJournal(tmp_path / "evidence.jsonl")
    wheel_verifier = wheel_verifier or PackageWheelVerifier()
    resolution = PackageClosureResolutionJournal(tmp_path / "closure.jsonl")
    resolution_environment = _environment()
    closure_budgets = budgets or PackageClosureBudgetV1()
    resolution.bind_basis(
        PackageClosureResolutionBasisV1(
            operation_id=OPERATION_ID,
            attempt_epoch=1,
            request_fingerprint=REQUEST_FINGERPRINT,
            policy_revision=POLICY_REVISION,
            quota_profile_revision="quota:1",
            resolution_environment=resolution_environment,
            budgets=closure_budgets,
        )
    )
    acquisition_budgets = PackageAcquisitionBudgetV1(
        max_transport_bytes=128 * 1024,
        max_requests=1,
        max_redirects=0,
        max_wall_time_ms=1000,
    )
    inspection_budgets = PackageInspectionBudgetV1()
    root_selection = selections["root-plugin"]
    root_request = PackageAcquisitionRequestV1(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        node_id="root",
        canonical_source_identity=root_selection.source,
        request_fingerprint=REQUEST_FINGERPRINT,
        requested_locator_digest=sha256(root_selection.source.encode()).hexdigest(),
        policy_revision=POLICY_REVISION,
    )
    authorized = acquisition.authorize_source(root_request)
    evidence.append(
        request_fingerprint=REQUEST_FINGERPRINT,
        evidence=PackageAuthenticatedSourceEvidenceV1(
            attempt_epoch=1,
            envelope=authorized.envelope,
        ),
    )
    acquired = acquisition.acquire_authorized(
        root_request,
        authorized,
        budgets=acquisition_budgets,
    )
    evidence.append(
        request_fingerprint=REQUEST_FINGERPRINT,
        evidence=acquired.receipt,
    )
    root = wheel_verifier.verify(
        acquired,
        wheel_filename=root_selection.filename,
        supported_tags=frozenset({"py3-none-any"}),
        budgets=inspection_budgets,
    )
    evidence.append(
        request_fingerprint=REQUEST_FINGERPRINT,
        evidence=root.evidence,
    )
    return _Fixture(
        owner=PackageRecursiveClosureOwner(
            resolver=resolver,
            acquisition_owner=acquisition,
            evidence_journal=evidence,
            wheel_verifier=wheel_verifier,
            closure_verifier=PackageClosureVerifier(),
            acquisition_budgets=acquisition_budgets,
            inspection_budgets=inspection_budgets,
            cleanup_owner=cleanup,
            selection_journal=resolution,
        ),
        root=root,
        request=PackageRecursiveClosureRequestV2(
            operation_id=OPERATION_ID,
            attempt_epoch=1,
            request_fingerprint=REQUEST_FINGERPRINT,
            policy_revision=POLICY_REVISION,
            resolution_environment=resolution_environment,
            budgets=closure_budgets,
        ),
        resolver=resolver,
        authority=authority,
        evidence=evidence,
        store=store,
        acquisition_owner=acquisition,
        wheel_verifier=wheel_verifier,
        resolution=resolution,
        cleanup=cleanup,
    )


def _reopen_root(fixture: _Fixture) -> VerifiedWheelCandidate:
    source_record = fixture.evidence.find(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        node_id="root",
        kind="authenticated_source",
    )
    receipt_record = fixture.evidence.find(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        node_id="root",
        kind="bounded_acquisition",
    )
    verified_record = fixture.evidence.find(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        node_id="root",
        kind="verified_wheel",
    )
    assert source_record is not None
    assert receipt_record is not None
    assert verified_record is not None
    assert isinstance(source_record.evidence, PackageAuthenticatedSourceEvidenceV1)
    assert isinstance(receipt_record.evidence, BoundedAcquisitionReceiptV1)
    root_selection = fixture.resolver.selections["root-plugin"]
    request = PackageAcquisitionRequestV1(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        node_id="root",
        canonical_source_identity=root_selection.source,
        request_fingerprint=REQUEST_FINGERPRINT,
        requested_locator_digest=sha256(root_selection.source.encode()).hexdigest(),
        policy_revision=POLICY_REVISION,
    )
    acquired = fixture.acquisition_owner.reopen_acquired(
        request,
        receipt_record.evidence,
        reset_extraction=True,
        authenticated_envelope=source_record.evidence.envelope,
    )
    reopened = fixture.wheel_verifier.verify(
        acquired,
        wheel_filename=root_selection.filename,
        supported_tags=frozenset({"py3-none-any"}),
        budgets=PackageInspectionBudgetV1(),
    )
    assert reopened.evidence == verified_record.evidence
    return reopened


def test_recursive_owner_acquires_marker_selected_dependency_graph(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": (
                "1.0",
                (
                    "dep[fast]>=2",
                    "ignored==1; python_version < '3'",
                ),
            ),
            "dep": ("2.0", ("leaf==1; extra == 'fast'",)),
            "leaf": ("1.0", ()),
        },
    )

    closure = fixture.owner.build(fixture.root, fixture.request)

    assert closure.plan.node_count == 3
    assert closure.plan.edge_count == 2
    assert closure.plan.max_depth == 2
    nodes = {node.distribution: node for node in closure.plan.nodes}
    assert nodes["dep"].selected_extras == ("fast",)
    assert nodes["root-plugin"].selected_edges == (nodes["dep"].node_id,)
    assert nodes["dep"].selected_edges == (nodes["leaf"].node_id,)
    assert len(fixture.resolver.calls) == 2
    assert len(fixture.authority.calls) == 3
    assert [record.evidence_kind for record in fixture.evidence.records()] == [
        "authenticated_source",
        "bounded_acquisition",
        "verified_wheel",
    ] * 3
    closure.cleanup()
    assert fixture.store.attempt_names() == ()


def test_recursive_owner_reaches_fixpoint_when_incoming_extras_expand_late(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("alpha==1", "zeta==1")),
            "alpha": ("1.0", ("shared[a]==1",)),
            "zeta": ("1.0", ("zeta-child==1",)),
            "zeta-child": ("1.0", ("shared[b]==1",)),
            "shared": ("1.0", ("leaf==1; extra == 'b'",)),
            "leaf": ("1.0", ()),
        },
    )

    closure = fixture.owner.build(fixture.root, fixture.request)

    nodes = {node.distribution: node for node in closure.plan.nodes}
    assert closure.plan.node_count == 6
    assert nodes["shared"].selected_extras == ("a", "b")
    assert nodes["shared"].selected_edges == (nodes["leaf"].node_id,)
    assert len(fixture.authority.calls) == 6
    closure.cleanup()
    assert fixture.store.attempt_names() == ()


def test_recursive_owner_replays_durable_selections_and_artifacts_without_io(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("dep==2",)),
            "dep": ("2.0", ("leaf==1",)),
            "leaf": ("1.0", ()),
        },
    )
    first = fixture.owner.build(fixture.root, fixture.request)
    first_plan = first.plan
    assert len(fixture.resolution.records()) == 3
    first.suspend_for_recovery()
    source_calls = len(fixture.authority.calls)
    fixture.resolver.calls.clear()

    reopened_root = _reopen_root(fixture)
    replayed = fixture.owner.build(reopened_root, fixture.request)

    assert replayed.plan == first_plan
    assert fixture.resolver.calls == []
    assert len(fixture.authority.calls) == source_calls
    assert len(fixture.resolution.records()) == 3
    assert len(fixture.evidence.records()) == 9
    replayed.cleanup()
    assert fixture.store.attempt_names() == ()


def test_recursive_owner_rejects_resolver_identity_change_before_dependency_io(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("dep==2",)),
            "dep": ("2.0", ()),
        },
    )
    fixture.resolver.change_parent = True

    with pytest.raises(PackageDependencyResolutionError) as rejected:
        fixture.owner.build(fixture.root, fixture.request)

    assert rejected.value.code == "package_closure_conflict"
    assert len(fixture.authority.calls) == 1
    assert fixture.store.attempt_names() == ()
    assert len(fixture.evidence.records()) == 3


def test_recursive_owner_rejects_selected_digest_and_cleans_every_candidate(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("dep==2",)),
            "dep": ("2.0", ()),
        },
    )
    selected = fixture.resolver.selections["dep"]
    fixture.resolver.selections["dep"] = replace(selected, digest="0" * 64)

    with pytest.raises(PackageClosureVerificationError) as rejected:
        fixture.owner.build(fixture.root, fixture.request)

    assert rejected.value.code == "package_closure_artifact_invalid"
    assert fixture.store.attempt_names() == ()
    assert len(fixture.evidence.records()) == 6


def test_recursive_owner_enforces_total_request_budget_before_source_call(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("dep==2",)),
            "dep": ("2.0", ()),
        },
        budgets=PackageClosureBudgetV1(max_total_requests=1),
    )

    with pytest.raises(PackageClosureVerificationError) as limited:
        fixture.owner.build(fixture.root, fixture.request)

    assert limited.value.code == "package_resource_limit_exceeded"
    assert limited.value.dimension == "requests"
    assert len(fixture.authority.calls) == 1
    assert fixture.store.attempt_names() == ()


def test_recursive_owner_enforces_depth_budget_before_dependency_source_call(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("dep==2",)),
            "dep": ("2.0", ()),
        },
        budgets=PackageClosureBudgetV1(max_depth=0),
    )

    with pytest.raises(PackageClosureVerificationError) as limited:
        fixture.owner.build(fixture.root, fixture.request)

    assert limited.value.code == "package_resource_limit_exceeded"
    assert limited.value.dimension == "graph"
    assert len(fixture.resolver.calls) == 1
    assert len(fixture.authority.calls) == 1
    assert fixture.store.attempt_names() == ()


def test_recursive_owner_rejects_incompatible_resolver_version_before_source_call(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("dep>=2",)),
            "dep": ("2.0", ()),
        },
    )
    selected = fixture.resolver.selections["dep"]
    fixture.resolver.selections["dep"] = replace(selected, version="1.0")

    with pytest.raises(PackageDependencyResolutionError) as rejected:
        fixture.owner.build(fixture.root, fixture.request)

    assert rejected.value.code == "package_closure_conflict"
    assert len(fixture.authority.calls) == 1
    assert fixture.store.attempt_names() == ()


def test_recursive_owner_preflights_root_python_before_resolver_or_source_call(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("dep==2",)),
            "dep": ("2.0", ()),
        },
        root_requires_python=">=4",
    )

    with pytest.raises(PackageClosureVerificationError) as rejected:
        fixture.owner.build(fixture.root, fixture.request)

    assert rejected.value.code == "package_closure_conflict"
    assert fixture.resolver.calls == []
    assert len(fixture.authority.calls) == 1
    assert fixture.store.attempt_names() == ()


def test_recursive_owner_preflights_root_extras_before_resolver_or_source_call(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("dep==2",)),
            "dep": ("2.0", ()),
        },
        root_provides_extra=(),
    )
    request = replace(fixture.request, root_extras=("fast",))

    with pytest.raises(PackageClosureVerificationError) as rejected:
        fixture.owner.build(fixture.root, request)

    assert rejected.value.code == "package_closure_conflict"
    assert fixture.resolver.calls == []
    assert len(fixture.authority.calls) == 1
    assert fixture.store.attempt_names() == ()


def test_recursive_owner_rejects_direct_url_requirement_without_resolver_call(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": (
                "1.0",
                ("dep @ https://untrusted.example.test/dep.whl",),
            ),
        },
    )

    with pytest.raises(PackageClosureVerificationError) as rejected:
        fixture.owner.build(fixture.root, fixture.request)

    assert rejected.value.code == "package_closure_artifact_invalid"
    assert fixture.resolver.calls == []
    assert fixture.store.attempt_names() == ()


def test_recursive_owner_durably_records_dependency_cleanup_debt(
    tmp_path: Path,
) -> None:
    fixture = _fixture(
        tmp_path,
        {
            "root-plugin": ("1.0", ("dep==2",)),
            "dep": ("2.0", ()),
        },
        wheel_verifier=_DependencyCleanupDebtWheelVerifier(),
    )

    with pytest.raises(PackageDependencyCleanupDebtError) as rejected:
        fixture.owner.build(fixture.root, fixture.request)

    assert rejected.value.code == "package_wheel_metadata_invalid"
    assert "private cleanup failure" not in str(rejected.value)
    cleanup_status = rejected.value.cleanup_status
    assert cleanup_status.disposition == "cleanup_retryable"
    assert cleanup_status.target.node_id != "root"
    assert fixture.cleanup.status(cleanup_status.target.cleanup_id) == cleanup_status
    assert len(fixture.store.attempt_names()) == 1
    repaired = fixture.cleanup.repair(
        cleanup_status.target.cleanup_id,
        expected_cleanup_revision=cleanup_status.cleanup_revision,
    )
    assert repaired.disposition == "cleanup_complete"
    assert fixture.store.attempt_names() == ()


def test_dependency_selection_records_are_exact_versioned_and_secret_free() -> None:
    requirement = NormalizedPackageRequirementV1.parse("dep[fast]>=2")
    request = PackageDependencySelectionRequestV1(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        parent_node_id="root",
        request_fingerprint=REQUEST_FINGERPRINT,
        resolution_environment_fingerprint=_environment().fingerprint,
        requirement=requirement,
    )
    selection = PackageDependencySelectionV1(
        operation_id=request.operation_id,
        attempt_epoch=request.attempt_epoch,
        parent_node_id=request.parent_node_id,
        request_fingerprint=request.request_fingerprint,
        resolution_environment_fingerprint=(request.resolution_environment_fingerprint),
        requirement_fingerprint=request.requirement_fingerprint,
        project_name="dep",
        version="2.0",
        canonical_source_identity="https://packages.example.test/dep.whl",
        wheel_filename="dep-2.0-py3-none-any.whl",
        expected_artifact_digest="a" * 64,
        resolver_id="resolver:test",
        resolver_revision="resolver-revision:1",
    )

    assert PackageDependencySelectionRequestV1.from_dict(request.to_dict()) == request
    assert PackageDependencySelectionV1.from_dict(selection.to_dict()) == selection
    assert selection.matches(request)
    assert len(selection.fingerprint) == 64
    changed = selection.to_dict()
    changed["secret"] = "must-not-fit"
    with pytest.raises(ValueError, match="versioned schema"):
        PackageDependencySelectionV1.from_dict(changed)
