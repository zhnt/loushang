from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.acquisition import (
    AuthenticatedSourceEnvelopeV1,
    BoundedAcquisitionReceiptV1,
    PackageAcquisitionBudgetV1,
    SourceAdapterResultV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    PackageClosureArtifactCandidateV2,
    PackageClosureBudgetV1,
    PackageClosureVerificationError,
    PackageClosureVerificationRequestV2,
    PackageClosureVerifier,
    PackageResolutionEnvironmentV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.wheel import (
    VerifiedWheelArtifactV1,
)
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


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


def _candidate(
    node_id: str,
    *,
    distribution: str | None = None,
    version: str = "1.0",
    role: str = "dependency",
    requirements: tuple[ResolvedPackageRequirementV1, ...] = (),
    request_count: int = 1,
    selected_extras: tuple[str, ...] = (),
) -> PackageClosureArtifactCandidateV2:
    name = distribution or node_id
    source = f"https://packages.example.test/{node_id}.whl"
    artifact_digest = _digest(f"artifact:{node_id}")
    envelope = AuthenticatedSourceEnvelopeV1(
        operation_id="closure-operation",
        node_id=node_id,
        canonical_source_identity=source,
        origin_kind="registry",
        authentication_decision="authorized",
        authority_id="fixture-source-authority",
        requested_locator_digest=_digest(source),
        expected_artifact_digest=artifact_digest,
        redirect_policy_revision="redirect-policy:1",
        policy_revision="source-policy:1",
        capture_epoch=1,
    )
    acquisition = BoundedAcquisitionReceiptV1(
        operation_id="closure-operation",
        attempt_epoch=1,
        node_id=node_id,
        envelope_fingerprint=envelope.fingerprint,
        actual_byte_digest=artifact_digest,
        actual_byte_count=100,
        request_count=request_count,
        redirect_count=0,
        budgets=PackageAcquisitionBudgetV1(
            max_transport_bytes=1000,
            max_requests=max(request_count, 1),
            max_redirects=0,
            max_wall_time_ms=1000,
        ),
        sink_identity=_digest(f"sink:{node_id}"),
        adapter_result=SourceAdapterResultV1(disposition="complete"),
    )
    wheel = VerifiedWheelArtifactV1(
        operation_id="closure-operation",
        attempt_epoch=1,
        node_id=node_id,
        distribution=name,
        version=version,
        wheel_filename=f"{name.replace('-', '_')}-{version}-py3-none-any.whl",
        compatible_tags=("py3-none-any",),
        artifact_digest=artifact_digest,
        artifact_size=100,
        wheel_metadata_digest=_digest(f"wheel:{node_id}"),
        package_metadata_digest=_digest(f"metadata:{node_id}"),
        record_digest=_digest(f"record:{node_id}"),
        record_verified=True,
        entry_count=4,
        expanded_byte_count=200,
        extraction_tree_digest=_digest(f"tree:{node_id}"),
    )
    return PackageClosureArtifactCandidateV2(
        role=role,
        envelope=envelope,
        acquisition=acquisition,
        wheel=wheel,
        requirements=requirements,
        selected_extras=selected_extras,
    )


def _requirement(
    target: PackageClosureArtifactCandidateV2,
    *,
    text: str | None = None,
    selected_node_id: str | None = None,
    marker_applies: bool = True,
    expected_source_identity: str | None = None,
    expected_artifact_digest: str | None = None,
) -> ResolvedPackageRequirementV1:
    return ResolvedPackageRequirementV1(
        requirement=NormalizedPackageRequirementV1.parse(
            text or f"{target.wheel.distribution}=={target.wheel.version}"
        ),
        marker_applies=marker_applies,
        selected_node_id=(
            target.wheel.node_id if selected_node_id is None else selected_node_id
        ),
        expected_source_identity=(
            target.envelope.canonical_source_identity
            if expected_source_identity is None
            else expected_source_identity
        ),
        expected_artifact_digest=(
            target.wheel.artifact_digest
            if expected_artifact_digest is None
            else expected_artifact_digest
        ),
    )


def _request(
    *candidates: PackageClosureArtifactCandidateV2,
    budgets: PackageClosureBudgetV1 | None = None,
    root_extras: tuple[str, ...] = (),
) -> PackageClosureVerificationRequestV2:
    return PackageClosureVerificationRequestV2(
        root_node_id="root",
        candidates=tuple(candidates),
        resolution_environment=_environment(),
        budgets=budgets or PackageClosureBudgetV1(),
        root_extras=root_extras,
    )


def test_closure_v2_plan_is_canonical_digest_bound_and_round_trippable() -> None:
    dependency = _candidate("dep")
    root = _candidate(
        "root",
        distribution="root-project",
        role="root",
        requirements=(_requirement(dependency),),
    )

    plan = PackageClosureVerifier().verify(_request(dependency, root))

    assert plan.root_node_id == "root"
    assert tuple(node.node_id for node in plan.nodes) == ("dep", "root")
    assert plan.node_count == 2
    assert plan.edge_count == 1
    assert plan.max_depth == 1
    assert plan.nodes[1].selected_edges == ("dep",)
    assert plan.graph_digest == _digest(plan.canonical_graph_json)
    assert VerifiedClosurePlanV2.from_dict(plan.to_dict()) == plan
    assert PackageClosureVerifier().verify(_request(root, dependency)) == plan


def test_inactive_marker_is_bound_to_environment_without_selecting_an_edge() -> None:
    inactive = ResolvedPackageRequirementV1(
        requirement=NormalizedPackageRequirementV1.parse(
            "windows-only==1.0; sys_platform == 'win32'"
        ),
        marker_applies=False,
        selected_node_id=None,
        expected_source_identity=None,
        expected_artifact_digest=None,
    )
    root = _candidate(
        "root",
        distribution="root-project",
        role="root",
        requirements=(inactive,),
    )

    plan = PackageClosureVerifier().verify(_request(root))

    assert plan.edge_count == 0
    assert plan.nodes[0].requirements == (inactive,)
    assert plan.nodes[0].selected_edges == ()


def test_optional_dependency_markers_use_the_selected_node_extras() -> None:
    leaf = _candidate("leaf")
    optional_requirement = ResolvedPackageRequirementV1(
        requirement=NormalizedPackageRequirementV1.parse(
            "leaf==1.0; extra == 'feature'"
        ),
        marker_applies=True,
        selected_node_id="leaf",
        expected_source_identity=leaf.envelope.canonical_source_identity,
        expected_artifact_digest=leaf.wheel.artifact_digest,
    )
    dependency = _candidate(
        "dep",
        requirements=(optional_requirement,),
        selected_extras=("feature",),
    )
    root = _candidate(
        "root",
        distribution="root-project",
        role="root",
        requirements=(_requirement(dependency, text="dep[feature]==1.0"),),
    )

    plan = PackageClosureVerifier().verify(_request(root, dependency, leaf))

    assert plan.edge_count == 2
    assert next(
        node for node in plan.nodes if node.node_id == "dep"
    ).selected_extras == ("feature",)

    changed = replace(dependency, selected_extras=())
    with pytest.raises(PackageClosureVerificationError) as rejected:
        PackageClosureVerifier().verify(_request(root, changed, leaf))
    assert rejected.value.code == "package_closure_conflict"


def test_closure_depth_uses_the_longest_path_in_a_shared_dag() -> None:
    leaf = _candidate("leaf")
    shared = _candidate(
        "shared",
        requirements=(_requirement(leaf),),
    )
    shallow = _candidate(
        "shallow",
        requirements=(_requirement(shared),),
    )
    deep_tail = _candidate(
        "deep-tail",
        requirements=(_requirement(shared),),
    )
    deep_head = _candidate(
        "deep-head",
        requirements=(_requirement(deep_tail),),
    )
    root = _candidate(
        "root",
        distribution="root-project",
        role="root",
        requirements=(
            _requirement(shallow),
            _requirement(deep_head),
        ),
    )
    candidates = (root, shallow, deep_head, deep_tail, shared, leaf)

    plan = PackageClosureVerifier().verify(_request(*candidates))

    assert plan.max_depth == 4
    with pytest.raises(PackageClosureVerificationError) as rejected:
        PackageClosureVerifier().verify(
            _request(*candidates, budgets=PackageClosureBudgetV1(max_depth=3))
        )
    assert rejected.value.code == "package_resource_limit_exceeded"
    assert rejected.value.dimension == "graph"


def test_decoded_closure_plan_reproves_summary_fields() -> None:
    dependency = _candidate("dep")
    root = _candidate(
        "root",
        distribution="root-project",
        role="root",
        requirements=(_requirement(dependency),),
    )
    plan = PackageClosureVerifier().verify(_request(root, dependency))

    with pytest.raises(ValueError, match="graph facts"):
        replace(plan, max_depth=2)

    document = plan.to_dict()
    nodes = document["nodes"]
    assert isinstance(nodes, list)
    dependency_document = next(
        item for item in nodes if isinstance(item, dict) and item["nodeId"] == "dep"
    )
    dependency_document["canonicalSourceIdentity"] = (
        "https://mirror.example.test/dep.whl"
    )
    graph = {
        "nodes": nodes,
        "resolutionEnvironmentFingerprint": document[
            "resolutionEnvironmentFingerprint"
        ],
        "rootNodeId": document["rootNodeId"],
    }
    document["graphDigest"] = sha256(canonical_json_bytes(graph)).hexdigest()
    with pytest.raises(ValueError, match="edge evidence"):
        VerifiedClosurePlanV2.from_dict(document)


@pytest.mark.parametrize(
    ("case_id", "request_factory", "expected_code"),
    (
        (
            "B-CLOSURE-MISSING",
            lambda: _request(
                _candidate(
                    "root",
                    distribution="root-project",
                    role="root",
                    requirements=(
                        _requirement(_candidate("dep"), selected_node_id="missing"),
                    ),
                )
            ),
            "package_closure_artifact_invalid",
        ),
        (
            "B-CLOSURE-DIGEST",
            lambda: _request(
                (dependency := _candidate("dep")),
                _candidate(
                    "root",
                    distribution="root-project",
                    role="root",
                    requirements=(
                        _requirement(dependency, expected_artifact_digest="f" * 64),
                    ),
                ),
            ),
            "package_closure_artifact_invalid",
        ),
        (
            "B-CLOSURE-ORIGIN",
            lambda: _request(
                (dependency := _candidate("dep")),
                _candidate(
                    "root",
                    distribution="root-project",
                    role="root",
                    requirements=(
                        _requirement(
                            dependency,
                            expected_source_identity=(
                                "https://unauthorized.example.test/dep.whl"
                            ),
                        ),
                    ),
                ),
            ),
            "package_closure_artifact_invalid",
        ),
        (
            "B-CLOSURE-MARKER",
            lambda: _request(
                (dependency := _candidate("dep")),
                _candidate(
                    "root",
                    distribution="root-project",
                    role="root",
                    requirements=(
                        _requirement(
                            dependency,
                            text="dep==1.0; python_version >= '3.11'",
                            marker_applies=False,
                        ),
                    ),
                ),
            ),
            "package_closure_conflict",
        ),
        (
            "B-CLOSURE-NAME",
            lambda: _request(
                _candidate("dep-a", distribution="same-name"),
                _candidate("dep-b", distribution="same-name", version="2.0"),
                _candidate("root", distribution="root-project", role="root"),
            ),
            "package_closure_conflict",
        ),
        (
            "B-CLOSURE-CYCLE",
            lambda: _cycle_request(),
            "package_closure_conflict",
        ),
    ),
)
def test_closure_v2_rejects_adversarial_graphs(
    case_id: str,
    request_factory,
    expected_code: str,
) -> None:
    with pytest.raises(PackageClosureVerificationError) as rejected:
        PackageClosureVerifier().verify(request_factory())

    assert rejected.value.code == expected_code, case_id
    assert rejected.value.stage == "resolving_closure"
    assert case_id not in str(rejected.value)


def _cycle_request() -> PackageClosureVerificationRequestV2:
    provisional_root = _candidate("root", distribution="root-project", role="root")
    provisional_dependency = _candidate("dep")
    root = replace(
        provisional_root,
        requirements=(_requirement(provisional_dependency),),
    )
    dependency = replace(
        provisional_dependency,
        requirements=(_requirement(provisional_root),),
    )
    return _request(root, dependency)


@pytest.mark.parametrize(
    ("case_id", "budgets", "expected_dimension"),
    (
        (
            "B-LIMIT-GRAPH",
            PackageClosureBudgetV1(max_nodes=1),
            "graph",
        ),
        (
            "B-LIMIT-SOLVER",
            PackageClosureBudgetV1(max_solver_steps=0),
            "solver",
        ),
        (
            "B-LIMIT-REQUESTS",
            PackageClosureBudgetV1(max_total_requests=1),
            "requests",
        ),
    ),
)
def test_closure_v2_enforces_composed_resource_budgets(
    case_id: str,
    budgets: PackageClosureBudgetV1,
    expected_dimension: str,
) -> None:
    dependency = _candidate("dep")
    root = _candidate(
        "root",
        distribution="root-project",
        role="root",
        requirements=(_requirement(dependency),),
    )

    with pytest.raises(PackageClosureVerificationError) as rejected:
        PackageClosureVerifier().verify(_request(root, dependency, budgets=budgets))

    assert rejected.value.code == "package_resource_limit_exceeded", case_id
    assert rejected.value.dimension == expected_dimension


def test_closure_v1_is_replay_only_and_cannot_satisfy_v2() -> None:
    case_id = "B-CLOSURE-V1"
    legacy = PluginDependencyClosureLock(
        package_content_digest="a" * 64,
        python_distributions=(),
    )

    with pytest.raises(PackageClosureVerificationError) as rejected:
        PackageClosureVerifier().verify(legacy)

    assert rejected.value.code == "package_closure_evidence_unsupported"
    assert rejected.value.stage == "resolving_closure"
    assert case_id not in str(rejected.value)


def test_closure_v2_rejects_broken_typed_evidence_chain() -> None:
    root = _candidate("root", distribution="root-project", role="root")
    tampered = replace(
        root,
        acquisition=replace(root.acquisition, envelope_fingerprint="f" * 64),
    )

    with pytest.raises(PackageClosureVerificationError) as rejected:
        PackageClosureVerifier().verify(_request(tampered))

    assert rejected.value.code == "package_closure_artifact_invalid"
