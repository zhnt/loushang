"""Pure construction and closed-set validation for Ontology packages."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from loushang.ontology.package.model import (
    OntologyPackageArtifact,
    OntologyPackageDependencyLock,
)
from loushang.ontology.schema import CompiledOntologySchema, SchemaIdentity


class OntologyPackageValidationError(ValueError):
    """Stable package closure failure without registry or resolver behavior."""

    def __init__(self, code: str, message: str) -> None:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")
        self.code = code
        super().__init__(message)


def lock_ontology_package_dependency(
    artifact: OntologyPackageArtifact,
) -> OntologyPackageDependencyLock:
    """Lock one exact package identity and complete artifact content."""

    if not isinstance(artifact, OntologyPackageArtifact):
        raise TypeError("artifact must be an OntologyPackageArtifact")
    return OntologyPackageDependencyLock(
        package_identity=artifact.package_identity,
        artifact_digest=artifact.artifact_digest,
    )


def build_ontology_package_artifact(
    schema: CompiledOntologySchema,
    *,
    dependencies: Iterable[OntologyPackageArtifact] = (),
) -> OntologyPackageArtifact:
    """Bundle one compiled Schema with exact direct dependency locks."""

    if not isinstance(schema, CompiledOntologySchema):
        raise TypeError("schema must be a CompiledOntologySchema")
    dependency_artifacts = tuple(dependencies)
    if any(
        not isinstance(item, OntologyPackageArtifact) for item in dependency_artifacts
    ):
        raise TypeError("dependencies must contain OntologyPackageArtifact values")
    return OntologyPackageArtifact(
        package_identity=SchemaIdentity.from_schema(schema),
        schema_digest=_sha256_text(schema.to_json()),
        dependencies=tuple(
            lock_ontology_package_dependency(item) for item in dependency_artifacts
        ),
        compiled_schema=schema,
    )


def validate_ontology_package_set(
    artifacts: Iterable[OntologyPackageArtifact],
) -> tuple[OntologyPackageArtifact, ...]:
    """Validate one exact closed set; perform no version solving or schema merge."""

    values = tuple(artifacts)
    if any(not isinstance(item, OntologyPackageArtifact) for item in values):
        raise TypeError("artifacts must contain OntologyPackageArtifact values")
    by_id: dict[str, OntologyPackageArtifact] = {}
    namespace_owner: dict[str, str] = {}
    for artifact in values:
        package_id = artifact.package_identity.package_id
        if package_id in by_id:
            raise OntologyPackageValidationError(
                "duplicate_package_id",
                f"package '{package_id}' appears more than once",
            )
        by_id[package_id] = artifact
        namespace = artifact.package_identity.namespace
        previous = namespace_owner.get(namespace)
        if previous is not None:
            raise OntologyPackageValidationError(
                "package_namespace_conflict",
                f"packages '{previous}' and '{package_id}' share namespace "
                f"'{namespace}'",
            )
        namespace_owner[namespace] = package_id

    adjacency: dict[str, tuple[str, ...]] = {}
    for package_id, artifact in by_id.items():
        dependency_ids: list[str] = []
        for dependency in artifact.dependencies:
            dependency_id = dependency.package_identity.package_id
            actual = by_id.get(dependency_id)
            if actual is None:
                raise OntologyPackageValidationError(
                    "package_dependency_missing",
                    f"package '{package_id}' requires absent package '{dependency_id}'",
                )
            if actual.package_identity != dependency.package_identity:
                raise OntologyPackageValidationError(
                    "package_dependency_identity_mismatch",
                    f"package '{dependency_id}' identity does not match the lock "
                    f"required by '{package_id}'",
                )
            dependency_ids.append(dependency_id)
        adjacency[package_id] = tuple(sorted(dependency_ids))

    _reject_dependency_cycles(adjacency)

    for package_id, artifact in by_id.items():
        for dependency in artifact.dependencies:
            dependency_id = dependency.package_identity.package_id
            actual = by_id[dependency_id]
            if actual.artifact_digest != dependency.artifact_digest:
                raise OntologyPackageValidationError(
                    "package_dependency_digest_mismatch",
                    f"package '{dependency_id}' content does not match the lock "
                    f"required by '{package_id}'",
                )

    return tuple(by_id[package_id] for package_id in sorted(by_id))


def _reject_dependency_cycles(adjacency: dict[str, tuple[str, ...]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(package_id: str, path: tuple[str, ...]) -> None:
        if package_id in visiting:
            cycle_start = path.index(package_id)
            cycle = (*path[cycle_start:], package_id)
            raise OntologyPackageValidationError(
                "package_dependency_cycle",
                "ontology package dependency cycle: " + " -> ".join(cycle),
            )
        if package_id in visited:
            return
        visiting.add(package_id)
        for dependency_id in adjacency[package_id]:
            visit(dependency_id, (*path, package_id))
        visiting.remove(package_id)
        visited.add(package_id)

    for package_id in sorted(adjacency):
        visit(package_id, ())


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "OntologyPackageValidationError",
    "build_ontology_package_artifact",
    "lock_ontology_package_dependency",
    "validate_ontology_package_set",
]
