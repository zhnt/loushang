from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

import pytest

from loushang.harness.resources.packages.plugin_lifecycle.closure import (
    NormalizedPackageRequirementV1,
    ResolvedPackageRequirementV1,
    VerifiedClosurePlanNodeV2,
    VerifiedClosurePlanV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    CommittedPackageSetRefV1,
    DependencyClosureLockV2,
    PluginRevisionRefV1,
    VerifiedArtifactRefV1,
)

OPERATION_ID = "operation-commit-records"
INSTALLATION_ID = "installation-test"
PLUGIN_ID = "plugin-test"
REQUEST_FINGERPRINT = "9" * 64
CLASSIFICATION_FINGERPRINT = "8" * 64
ENVIRONMENT_FINGERPRINT = "7" * 64
ROOT_ARTIFACT_DIGEST = "6" * 64
ROOT_TREE_DIGEST = "5" * 64
DEPENDENCY_ARTIFACT_DIGEST = "4" * 64
DEPENDENCY_TREE_DIGEST = "3" * 64
DEPENDENCY_SOURCE = "https://packages.example.test/dependency.whl"


def _plan() -> VerifiedClosurePlanV2:
    dependency = VerifiedClosurePlanNodeV2(
        node_id="dependency-node",
        role="dependency",
        distribution="dependency",
        version="2.0",
        canonical_source_identity=DEPENDENCY_SOURCE,
        source_envelope_fingerprint="1" * 64,
        acquisition_receipt_fingerprint="2" * 64,
        wheel_evidence_fingerprint="3" * 64,
        artifact_digest=DEPENDENCY_ARTIFACT_DIGEST,
        extraction_tree_digest=DEPENDENCY_TREE_DIGEST,
        selected_extras=(),
        requirements=(),
        selected_edges=(),
    )
    requirement = ResolvedPackageRequirementV1(
        requirement=NormalizedPackageRequirementV1.parse("dependency==2.0"),
        marker_applies=True,
        selected_node_id=dependency.node_id,
        expected_source_identity=dependency.canonical_source_identity,
        expected_artifact_digest=dependency.artifact_digest,
    )
    root = VerifiedClosurePlanNodeV2(
        node_id="root",
        role="root",
        distribution="root-plugin",
        version="1.0",
        canonical_source_identity="https://packages.example.test/root.whl",
        source_envelope_fingerprint="a" * 64,
        acquisition_receipt_fingerprint="b" * 64,
        wheel_evidence_fingerprint="c" * 64,
        artifact_digest=ROOT_ARTIFACT_DIGEST,
        extraction_tree_digest=ROOT_TREE_DIGEST,
        selected_extras=(),
        requirements=(requirement,),
        selected_edges=(dependency.node_id,),
    )
    return VerifiedClosurePlanV2.create(
        operation_id=OPERATION_ID,
        attempt_epoch=1,
        root_node_id=root.node_id,
        resolution_environment_fingerprint=ENVIRONMENT_FINGERPRINT,
        nodes=(root, dependency),
        max_depth=1,
    )


def _root_ref() -> PluginRevisionRefV1:
    return PluginRevisionRefV1.create(
        store_identity="plugin-store",
        store_revision="revision-11",
        installation_id=INSTALLATION_ID,
        plugin_id=PLUGIN_ID,
        distribution="root-plugin",
        version="1.0",
        artifact_digest=ROOT_ARTIFACT_DIGEST,
        extraction_tree_digest=ROOT_TREE_DIGEST,
    )


def _dependency_ref(
    *,
    artifact_digest: str = DEPENDENCY_ARTIFACT_DIGEST,
    extraction_tree_digest: str = DEPENDENCY_TREE_DIGEST,
) -> VerifiedArtifactRefV1:
    return VerifiedArtifactRefV1.create(
        store_identity="artifact-store",
        store_revision="revision-21",
        distribution="dependency",
        version="2.0",
        artifact_digest=artifact_digest,
        extraction_tree_digest=extraction_tree_digest,
    )


def _lock() -> DependencyClosureLockV2:
    return DependencyClosureLockV2.create(
        _plan(),
        stable_refs={"root": _root_ref(), "dependency-node": _dependency_ref()},
    )


def _committed_set() -> CommittedPackageSetRefV1:
    return CommittedPackageSetRefV1.create(
        _lock(),
        request_fingerprint=REQUEST_FINGERPRINT,
        product_id="coding",
        scope_id="workspace:test",
        installation_id=INSTALLATION_ID,
        plugin_id=PLUGIN_ID,
        classification_fingerprint=CLASSIFICATION_FINGERPRINT,
        commit_revision=12,
    )


def test_typed_refs_lock_and_committed_set_are_exact_and_round_trippable() -> None:
    root_ref = _root_ref()
    dependency_ref = _dependency_ref()
    lock = _lock()
    committed_set = _committed_set()

    assert PluginRevisionRefV1.from_dict(root_ref.to_dict()) == root_ref
    assert VerifiedArtifactRefV1.from_dict(dependency_ref.to_dict()) == dependency_ref
    assert DependencyClosureLockV2.from_dict(lock.to_dict()) == lock
    assert CommittedPackageSetRefV1.from_dict(committed_set.to_dict()) == committed_set
    assert tuple(node.node_id for node in lock.nodes) == (
        "dependency-node",
        "root",
    )
    assert lock.max_depth == 1
    assert committed_set.root_ref == root_ref
    assert committed_set.dependency_refs == (dependency_ref,)


def test_closure_lock_is_deterministic_and_requires_the_exact_typed_node_set() -> None:
    plan = _plan()
    refs = {"root": _root_ref(), "dependency-node": _dependency_ref()}

    assert DependencyClosureLockV2.create(plan, stable_refs=refs) == (
        DependencyClosureLockV2.create(
            plan,
            stable_refs={
                "dependency-node": refs["dependency-node"],
                "root": refs["root"],
            },
        )
    )
    with pytest.raises(ValueError, match="node set"):
        DependencyClosureLockV2.create(
            plan,
            stable_refs={"root": refs["root"]},
        )
    with pytest.raises(ValueError, match="node set"):
        DependencyClosureLockV2.create(
            plan,
            stable_refs={**refs, "extra": _dependency_ref()},
        )


def test_closure_lock_rejects_role_confusion_and_changed_artifact_evidence() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="root requires"):
        DependencyClosureLockV2.create(
            plan,
            stable_refs={
                "root": _dependency_ref(),
                "dependency-node": _dependency_ref(),
            },
        )
    with pytest.raises(ValueError, match="dependency requires"):
        DependencyClosureLockV2.create(
            plan,
            stable_refs={
                "root": _root_ref(),
                "dependency-node": _root_ref(),
            },
        )
    with pytest.raises(ValueError, match="does not match"):
        DependencyClosureLockV2.create(
            plan,
            stable_refs={
                "root": _root_ref(),
                "dependency-node": _dependency_ref(artifact_digest="f" * 64),
            },
        )
    with pytest.raises(ValueError, match="does not match"):
        DependencyClosureLockV2.create(
            plan,
            stable_refs={
                "root": _root_ref(),
                "dependency-node": _dependency_ref(extraction_tree_digest="e" * 64),
            },
        )


@pytest.mark.parametrize(
    ("document", "id_field", "decoder"),
    [
        (_root_ref().to_dict(), "refId", PluginRevisionRefV1.from_dict),
        (
            _dependency_ref().to_dict(),
            "refId",
            VerifiedArtifactRefV1.from_dict,
        ),
        (_lock().to_dict(), "lockDigest", DependencyClosureLockV2.from_dict),
        (
            _committed_set().to_dict(),
            "setId",
            CommittedPackageSetRefV1.from_dict,
        ),
    ],
)
def test_typed_records_reject_forged_content_ids(
    document: dict[str, object],
    id_field: str,
    decoder: Callable[[object], object],
) -> None:
    document[id_field] = "0" * 64

    with pytest.raises(ValueError, match="does not match"):
        decoder(document)


def test_closure_lock_revalidates_embedded_plan_instead_of_only_its_digest() -> None:
    lock = _lock()
    changed_depth = lock.to_dict()
    changed_depth["maxDepth"] = 0
    with pytest.raises(ValueError, match="plan evidence"):
        DependencyClosureLockV2.from_dict(changed_depth)

    changed_fingerprint = lock.to_dict()
    changed_fingerprint["verifiedPlanFingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="plan fingerprint"):
        DependencyClosureLockV2.from_dict(changed_fingerprint)

    changed_graph = lock.to_dict()
    changed_graph["prepublicationGraphDigest"] = "0" * 64
    with pytest.raises(ValueError, match="plan evidence"):
        DependencyClosureLockV2.from_dict(changed_graph)


def test_versioned_wire_schemas_reject_extensions_and_future_versions() -> None:
    artifact_document = _dependency_ref().to_dict()
    artifact_document["path"] = "/tmp/not-a-stable-ref"
    with pytest.raises(ValueError, match="versioned schema"):
        VerifiedArtifactRefV1.from_dict(artifact_document)

    root_document = _root_ref().to_dict()
    root_document["refVersion"] = 2
    with pytest.raises(ValueError, match="Unsupported"):
        PluginRevisionRefV1.from_dict(root_document)

    lock_document = _lock().to_dict()
    lock_document["transactionPin"] = "live-handle"
    with pytest.raises(ValueError, match="versioned schema"):
        DependencyClosureLockV2.from_dict(lock_document)

    set_document = _committed_set().to_dict()
    set_document["setVersion"] = 2
    with pytest.raises(ValueError, match="Unsupported"):
        CommittedPackageSetRefV1.from_dict(set_document)


def test_committed_set_rejects_root_identity_drift_and_is_credential_free() -> None:
    lock = _lock()
    with pytest.raises(ValueError, match="root identity changed"):
        CommittedPackageSetRefV1.create(
            lock,
            request_fingerprint=REQUEST_FINGERPRINT,
            product_id="coding",
            scope_id="workspace:test",
            installation_id="installation-other",
            plugin_id=PLUGIN_ID,
            classification_fingerprint=CLASSIFICATION_FINGERPRINT,
            commit_revision=12,
        )

    document = _committed_set().to_dict()
    serialized = repr(document).lower()
    assert "credential" not in serialized
    assert "token" not in serialized
    assert "password" not in serialized
    assert "live-handle" not in serialized
    assert "/tmp/" not in serialized


def test_nested_ref_tampering_is_rejected_even_when_outer_record_is_unchanged() -> None:
    lock_document = deepcopy(_lock().to_dict())
    nodes = lock_document["nodes"]
    assert isinstance(nodes, list)
    first_node = nodes[0]
    assert isinstance(first_node, dict)
    stable_ref = first_node["stableRef"]
    assert isinstance(stable_ref, dict)
    stable_value = stable_ref["value"]
    assert isinstance(stable_value, dict)
    stable_value["storeRevision"] = "revision-forged"

    with pytest.raises(ValueError, match="ref id does not match"):
        DependencyClosureLockV2.from_dict(lock_document)
