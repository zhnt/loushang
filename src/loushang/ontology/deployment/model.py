"""Strict immutable values selecting one Ontology deployment cut."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast

from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.ontology.schema.identity import SchemaIdentity

DEPLOYMENT_PROFILE_FORMAT = "loushang.ontology.deployment-profile/v2"


@dataclass(frozen=True, slots=True)
class SchemaArtifactLock:
    """Exact compiled Ontology schema selected by one deployment."""

    schema_identity: SchemaIdentity
    content_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.schema_identity, SchemaIdentity):
            raise TypeError("schema_identity must be a SchemaIdentity")
        _require_digest("content_digest", self.content_digest)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema_identity": self.schema_identity.to_dict(),
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> SchemaArtifactLock:
        document = _exact_document(
            value,
            name="schema artifact lock",
            keys={"schema_identity", "content_digest"},
        )
        identity_document = _exact_document(
            document["schema_identity"],
            name="schema identity",
            keys={"package_id", "namespace", "version"},
        )
        return cls(
            schema_identity=SchemaIdentity.from_dict(identity_document),
            content_digest=_document_text(document, "content_digest"),
        )


@dataclass(frozen=True, slots=True)
class SourceAdapterArtifactLock:
    """Exact source-adapter manifest selected by one deployment."""

    adapter_id: str
    adapter_version: str
    manifest_digest: str

    def __post_init__(self) -> None:
        _non_empty_text("adapter_id", self.adapter_id)
        _non_empty_text("adapter_version", self.adapter_version)
        _require_digest("manifest_digest", self.manifest_digest)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "manifest_digest": self.manifest_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceAdapterArtifactLock:
        document = _exact_document(
            value,
            name="source adapter artifact lock",
            keys={"adapter_id", "adapter_version", "manifest_digest"},
        )
        return cls(
            adapter_id=_document_text(document, "adapter_id"),
            adapter_version=_document_text(document, "adapter_version"),
            manifest_digest=_document_text(document, "manifest_digest"),
        )


@dataclass(frozen=True, slots=True)
class IdentityCrosswalkArtifactLock:
    """Exact immutable identity-provider output selected by one deployment."""

    identity_namespace: str
    revision: str
    content_digest: str

    def __post_init__(self) -> None:
        _non_empty_text("identity_namespace", self.identity_namespace)
        _non_empty_text("revision", self.revision)
        _require_digest("content_digest", self.content_digest)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "identity_namespace": self.identity_namespace,
            "revision": self.revision,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> IdentityCrosswalkArtifactLock:
        document = _exact_document(
            value,
            name="identity crosswalk artifact lock",
            keys={"identity_namespace", "revision", "content_digest"},
        )
        return cls(
            identity_namespace=_document_text(document, "identity_namespace"),
            revision=_document_text(document, "revision"),
            content_digest=_document_text(document, "content_digest"),
        )


@dataclass(frozen=True, slots=True)
class SourceInstanceSelection:
    """Bind one concrete Product source instance to declared Adapter bindings."""

    source_instance_id: str
    adapter_id: str
    binding_ids: tuple[str, ...] | list[str]

    def __post_init__(self) -> None:
        _non_empty_text("source_instance_id", self.source_instance_id)
        _non_empty_text("adapter_id", self.adapter_id)
        binding_ids = tuple(sorted(self.binding_ids))
        if not binding_ids:
            raise ValueError("source instance selection requires binding_ids")
        if any(not isinstance(item, str) or not item.strip() for item in binding_ids):
            raise ValueError("binding_ids must contain non-empty strings")
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("source instance selection contains duplicate binding IDs")
        object.__setattr__(self, "binding_ids", binding_ids)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "source_instance_id": self.source_instance_id,
            "adapter_id": self.adapter_id,
            "binding_ids": list(self.binding_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceInstanceSelection:
        document = _exact_document(
            value,
            name="source instance selection",
            keys={"source_instance_id", "adapter_id", "binding_ids"},
        )
        raw_binding_ids = _document_list(document, "binding_ids")
        if any(not isinstance(item, str) for item in raw_binding_ids):
            raise ValueError("source instance binding_ids must be a string list")
        return cls(
            source_instance_id=_document_text(document, "source_instance_id"),
            adapter_id=_document_text(document, "adapter_id"),
            binding_ids=cast(list[str], raw_binding_ids),
        )


@dataclass(frozen=True, slots=True)
class DeploymentProfile:
    """Content-addressed artifact selection; contains no runtime credentials."""

    deployment_id: str
    schema_lock: SchemaArtifactLock
    adapter_locks: (
        tuple[SourceAdapterArtifactLock, ...] | list[SourceAdapterArtifactLock]
    )
    source_instances: (
        tuple[SourceInstanceSelection, ...] | list[SourceInstanceSelection]
    )
    identity_crosswalk_lock: IdentityCrosswalkArtifactLock | None
    fact_store_ref: str
    projection_store_ref: str
    format: str = DEPLOYMENT_PROFILE_FORMAT

    def __post_init__(self) -> None:
        _non_empty_text("deployment_id", self.deployment_id)
        if not isinstance(self.schema_lock, SchemaArtifactLock):
            raise TypeError("schema_lock must be a SchemaArtifactLock")
        locks = tuple(self.adapter_locks)
        if any(not isinstance(item, SourceAdapterArtifactLock) for item in locks):
            raise TypeError(
                "adapter_locks must contain SourceAdapterArtifactLock values"
            )
        locks = tuple(sorted(locks, key=lambda item: item.adapter_id))
        adapter_ids = [item.adapter_id for item in locks]
        if len(adapter_ids) != len(set(adapter_ids)):
            raise ValueError("deployment profile contains duplicate adapter IDs")
        object.__setattr__(self, "adapter_locks", locks)

        source_instances = tuple(self.source_instances)
        if any(
            not isinstance(item, SourceInstanceSelection) for item in source_instances
        ):
            raise TypeError(
                "source_instances must contain SourceInstanceSelection values"
            )
        source_instances = tuple(
            sorted(source_instances, key=lambda item: item.source_instance_id)
        )
        source_instance_ids = [item.source_instance_id for item in source_instances]
        if len(source_instance_ids) != len(set(source_instance_ids)):
            raise ValueError("deployment profile contains duplicate source instances")
        selected_binding_ids = [
            binding_id
            for source_instance in source_instances
            for binding_id in source_instance.binding_ids
        ]
        if len(selected_binding_ids) != len(set(selected_binding_ids)):
            raise ValueError(
                "deployment profile assigns a binding to multiple source instances"
            )
        object.__setattr__(self, "source_instances", source_instances)
        if self.identity_crosswalk_lock is not None and not isinstance(
            self.identity_crosswalk_lock,
            IdentityCrosswalkArtifactLock,
        ):
            raise TypeError(
                "identity_crosswalk_lock must be an "
                "IdentityCrosswalkArtifactLock or None"
            )
        _non_empty_text("fact_store_ref", self.fact_store_ref)
        _non_empty_text("projection_store_ref", self.projection_store_ref)
        if self.format != DEPLOYMENT_PROFILE_FORMAT:
            raise ValueError("unsupported deployment profile format")

    @property
    def profile_digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": self.format,
            "deployment_id": self.deployment_id,
            "schema_lock": self.schema_lock.to_dict(),
            "adapter_locks": [item.to_dict() for item in self.adapter_locks],
            "source_instances": [item.to_dict() for item in self.source_instances],
            "identity_crosswalk_lock": (
                None
                if self.identity_crosswalk_lock is None
                else self.identity_crosswalk_lock.to_dict()
            ),
            "fact_store_ref": self.fact_store_ref,
            "projection_store_ref": self.projection_store_ref,
        }

    def to_json(self) -> str:
        return dump_json_value(
            self.to_dict(),
            name="deployment profile",
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> DeploymentProfile:
        try:
            document = _exact_document(
                json.loads(payload),
                name="deployment profile",
                keys={
                    "format",
                    "deployment_id",
                    "schema_lock",
                    "adapter_locks",
                    "source_instances",
                    "identity_crosswalk_lock",
                    "fact_store_ref",
                    "projection_store_ref",
                },
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid deployment profile JSON: {exc}") from exc
        if document["format"] != DEPLOYMENT_PROFILE_FORMAT:
            raise ValueError("unsupported deployment profile format")
        raw_adapter_locks = _document_list(document, "adapter_locks")
        raw_source_instances = _document_list(document, "source_instances")
        raw_identity_lock = document["identity_crosswalk_lock"]
        return cls(
            deployment_id=_document_text(document, "deployment_id"),
            schema_lock=SchemaArtifactLock.from_dict(document["schema_lock"]),
            adapter_locks=[
                SourceAdapterArtifactLock.from_dict(item) for item in raw_adapter_locks
            ],
            source_instances=[
                SourceInstanceSelection.from_dict(item) for item in raw_source_instances
            ],
            identity_crosswalk_lock=(
                None
                if raw_identity_lock is None
                else IdentityCrosswalkArtifactLock.from_dict(raw_identity_lock)
            ),
            fact_store_ref=_document_text(document, "fact_store_ref"),
            projection_store_ref=_document_text(document, "projection_store_ref"),
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


def _non_empty_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_digest(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _document_text(document: dict[str, JSONValue], name: str) -> str:
    try:
        return _non_empty_text(name, document[name])
    except KeyError as exc:  # pragma: no cover - exact fields report first
        raise ValueError(f"deployment profile is missing {name}") from exc


def _document_list(
    document: dict[str, JSONValue],
    name: str,
) -> list[JSONValue]:
    value = document[name]
    if not isinstance(value, list):
        raise ValueError(f"deployment profile {name} must be a list")
    return value


__all__ = [
    "DEPLOYMENT_PROFILE_FORMAT",
    "DeploymentProfile",
    "IdentityCrosswalkArtifactLock",
    "SchemaArtifactLock",
    "SourceAdapterArtifactLock",
    "SourceInstanceSelection",
]
