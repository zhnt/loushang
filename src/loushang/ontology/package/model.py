"""Strict immutable Ontology package artifact values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.ontology.schema import (
    CompiledOntologySchema,
    OntologyCompiler,
    SchemaIdentity,
)

ONTOLOGY_PACKAGE_FORMAT = "loushang.ontology.package/v1"


@dataclass(frozen=True, slots=True)
class OntologyPackageDependencyLock:
    """Exact package artifact required by another package."""

    package_identity: SchemaIdentity
    artifact_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.package_identity, SchemaIdentity):
            raise TypeError("package_identity must be a SchemaIdentity")
        _require_digest("artifact_digest", self.artifact_digest)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        identity = self.package_identity
        return identity.package_id, identity.namespace, identity.version

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "package_identity": self.package_identity.to_dict(),
            "artifact_digest": self.artifact_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> OntologyPackageDependencyLock:
        document = _exact_document(
            value,
            name="ontology package dependency lock",
            keys={"package_identity", "artifact_digest"},
        )
        identity_document = _exact_document(
            document["package_identity"],
            name="schema identity",
            keys={"package_id", "namespace", "version"},
        )
        return cls(
            package_identity=SchemaIdentity.from_dict(identity_document),
            artifact_digest=_document_text(document, "artifact_digest"),
        )


@dataclass(frozen=True, slots=True)
class OntologyPackageArtifact:
    """One compiled Schema bundled with exact direct dependency locks."""

    package_identity: SchemaIdentity
    schema_digest: str
    dependencies: (
        tuple[OntologyPackageDependencyLock, ...] | list[OntologyPackageDependencyLock]
    )
    compiled_schema: CompiledOntologySchema
    format: str = ONTOLOGY_PACKAGE_FORMAT

    def __post_init__(self) -> None:
        if not isinstance(self.package_identity, SchemaIdentity):
            raise TypeError("package_identity must be a SchemaIdentity")
        if not isinstance(self.compiled_schema, CompiledOntologySchema):
            raise TypeError("compiled_schema must be a CompiledOntologySchema")
        if self.package_identity != SchemaIdentity.from_schema(self.compiled_schema):
            raise ValueError("compiled schema identity does not match package identity")
        _require_digest("schema_digest", self.schema_digest)
        if self.schema_digest != _sha256_text(self.compiled_schema.to_json()):
            raise ValueError("compiled schema content does not match schema_digest")

        dependencies = tuple(self.dependencies)
        if any(
            not isinstance(item, OntologyPackageDependencyLock) for item in dependencies
        ):
            raise TypeError(
                "dependencies must contain OntologyPackageDependencyLock values"
            )
        dependencies = tuple(sorted(dependencies, key=lambda item: item.sort_key))
        dependency_ids = [item.package_identity.package_id for item in dependencies]
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError("ontology package contains duplicate dependency IDs")
        if self.package_identity.package_id in dependency_ids:
            raise ValueError("ontology package cannot depend on itself")
        object.__setattr__(self, "dependencies", dependencies)
        if self.format != ONTOLOGY_PACKAGE_FORMAT:
            raise ValueError("unsupported ontology package format")

    @property
    def artifact_digest(self) -> str:
        return _sha256_text(self.to_json())

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": self.format,
            "package_identity": self.package_identity.to_dict(),
            "schema_digest": self.schema_digest,
            "dependencies": [item.to_dict() for item in self.dependencies],
            "compiled_schema": self.compiled_schema.to_dict(),
        }

    def to_json(self) -> str:
        return dump_json_value(
            self.to_dict(),
            name="ontology package artifact",
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> OntologyPackageArtifact:
        try:
            document = _exact_document(
                json.loads(payload),
                name="ontology package artifact",
                keys={
                    "format",
                    "package_identity",
                    "schema_digest",
                    "dependencies",
                    "compiled_schema",
                },
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid ontology package JSON: {exc}") from exc
        if document["format"] != ONTOLOGY_PACKAGE_FORMAT:
            raise ValueError("unsupported ontology package format")
        identity_document = _exact_document(
            document["package_identity"],
            name="schema identity",
            keys={"package_id", "namespace", "version"},
        )
        schema_document = require_json_mapping(
            document["compiled_schema"],
            name="compiled ontology schema",
        )
        schema = OntologyCompiler().load_json(
            dump_json_value(
                schema_document,
                name="compiled ontology schema",
                sort_keys=True,
            )
        )
        return cls(
            package_identity=SchemaIdentity.from_dict(identity_document),
            schema_digest=_document_text(document, "schema_digest"),
            dependencies=[
                OntologyPackageDependencyLock.from_dict(item)
                for item in _document_list(document, "dependencies")
            ],
            compiled_schema=schema,
        )


def _exact_document(
    value: object,
    *,
    name: str,
    keys: set[str],
) -> dict[str, JSONValue]:
    document = require_json_mapping(value, name=name)
    if set(document) != keys:
        raise ValueError(f"{name} fields do not match the supported format")
    return document


def _require_digest(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _document_text(document: dict[str, JSONValue], name: str) -> str:
    value = document[name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ontology package {name} must be a non-empty string")
    return value


def _document_list(
    document: dict[str, JSONValue],
    name: str,
) -> list[JSONValue]:
    value = document[name]
    if not isinstance(value, list):
        raise ValueError(f"ontology package {name} must be a list")
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "ONTOLOGY_PACKAGE_FORMAT",
    "OntologyPackageArtifact",
    "OntologyPackageDependencyLock",
]
