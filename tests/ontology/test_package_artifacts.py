from __future__ import annotations

import json
from dataclasses import replace

import pytest

from loushang.ontology.package import (
    ONTOLOGY_PACKAGE_FORMAT,
    OntologyPackageArtifact,
    OntologyPackageDependencyLock,
    OntologyPackageValidationError,
    build_ontology_package_artifact,
    lock_ontology_package_dependency,
    validate_ontology_package_set,
)
from loushang.ontology.schema import (
    ObjectTypeDefinition,
    OntologyCompiler,
    OntologyPackageDraft,
    SchemaIdentity,
    StateAuthority,
)


def _schema(
    package_id: str,
    *,
    namespace: str | None = None,
    version: str = "1.0.0",
):
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id=package_id,
            namespace=namespace or f"urn:test:{package_id}",
            version=version,
            object_types=(
                ObjectTypeDefinition(
                    "Entity",
                    semantic_id="entity",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                ),
            ),
        )
    )


def _artifact(package_id: str, **schema_options) -> OntologyPackageArtifact:
    return build_ontology_package_artifact(_schema(package_id, **schema_options))


def _validation_code(*artifacts: OntologyPackageArtifact) -> str:
    with pytest.raises(OntologyPackageValidationError) as exc_info:
        validate_ontology_package_set(artifacts)
    return exc_info.value.code


def test_package_artifact_round_trip_and_dependency_order_are_deterministic() -> None:
    alpha = _artifact("test.alpha")
    beta = _artifact("test.beta")
    schema = _schema("test.root")
    first = build_ontology_package_artifact(
        schema,
        dependencies=(beta, alpha),
    )
    second = build_ontology_package_artifact(
        schema,
        dependencies=(alpha, beta),
    )

    restored = OntologyPackageArtifact.from_json(first.to_json())

    assert restored == first == second
    assert [item.package_identity.package_id for item in restored.dependencies] == [
        "test.alpha",
        "test.beta",
    ]
    assert restored.artifact_digest == second.artifact_digest
    assert len(restored.schema_digest) == 64
    assert len(restored.artifact_digest) == 64
    assert validate_ontology_package_set((first, beta, alpha)) == (
        alpha,
        beta,
        first,
    )


def test_package_json_is_strict_and_schema_content_is_verified() -> None:
    artifact = _artifact("test.strict")
    document = json.loads(artifact.to_json())
    document["registry_url"] = "forbidden"

    with pytest.raises(ValueError, match="fields do not match"):
        OntologyPackageArtifact.from_json(json.dumps(document))
    with pytest.raises(ValueError, match="schema content"):
        replace(artifact, schema_digest="0" * 64)
    with pytest.raises(ValueError, match="unsupported ontology package format"):
        replace(artifact, format="loushang.ontology.package/v0")

    assert ONTOLOGY_PACKAGE_FORMAT.endswith("/v1")


def test_closed_set_rejects_missing_identity_and_digest_drift_separately() -> None:
    dependency = _artifact("test.dependency")
    root = build_ontology_package_artifact(
        _schema("test.root"),
        dependencies=(dependency,),
    )

    assert _validation_code(root) == "package_dependency_missing"

    changed_identity = _artifact("test.dependency", version="2.0.0")
    assert (
        _validation_code(
            root,
            changed_identity,
        )
        == "package_dependency_identity_mismatch"
    )

    changed_lock = replace(
        root,
        dependencies=(
            replace(
                root.dependencies[0],
                artifact_digest="0" * 64,
            ),
        ),
    )
    assert (
        _validation_code(
            changed_lock,
            dependency,
        )
        == "package_dependency_digest_mismatch"
    )


def test_closed_set_rejects_duplicate_ids_namespaces_and_dependency_cycles() -> None:
    alpha = _artifact("test.alpha")
    alpha_v2 = _artifact("test.alpha", version="2.0.0")
    namespace_conflict = _artifact(
        "test.other",
        namespace=alpha.package_identity.namespace,
    )

    assert _validation_code(alpha, alpha_v2) == "duplicate_package_id"
    assert (
        _validation_code(
            alpha,
            namespace_conflict,
        )
        == "package_namespace_conflict"
    )

    beta = _artifact("test.beta")
    alpha_cycle = replace(
        alpha,
        dependencies=(lock_ontology_package_dependency(beta),),
    )
    beta_cycle = replace(
        beta,
        dependencies=(lock_ontology_package_dependency(alpha),),
    )
    assert (
        _validation_code(
            alpha_cycle,
            beta_cycle,
        )
        == "package_dependency_cycle"
    )


def test_package_rejects_duplicate_and_self_dependency_locks() -> None:
    alpha = _artifact("test.alpha")
    beta = _artifact("test.beta")
    beta_lock = lock_ontology_package_dependency(beta)

    with pytest.raises(ValueError, match="duplicate dependency IDs"):
        replace(alpha, dependencies=(beta_lock, beta_lock))
    with pytest.raises(ValueError, match="depend on itself"):
        replace(
            alpha,
            dependencies=(
                OntologyPackageDependencyLock(
                    package_identity=SchemaIdentity.from_schema(alpha.compiled_schema),
                    artifact_digest=alpha.artifact_digest,
                ),
            ),
        )
