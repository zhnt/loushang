"""Immutable snapshots of explicit source-to-canonical identity decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import cast
from uuid import UUID

from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping

IDENTITY_CROSSWALK_FORMAT = "loushang.ontology.identity-crosswalk/v1"


@dataclass(frozen=True, slots=True)
class SourceRecordIdentity:
    """One source record key scoped to a concrete deployment source instance."""

    source_instance_id: str
    binding_id: str
    record_type: str
    source_record_key: str

    def __post_init__(self) -> None:
        for name in (
            "source_instance_id",
            "binding_id",
            "record_type",
            "source_record_key",
        ):
            _non_empty_text(name, getattr(self, name))

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.source_instance_id,
            self.binding_id,
            self.record_type,
            self.source_record_key,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "source_instance_id": self.source_instance_id,
            "binding_id": self.binding_id,
            "record_type": self.record_type,
            "source_record_key": self.source_record_key,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceRecordIdentity:
        document = _exact_document(
            value,
            name="source record identity",
            keys={
                "source_instance_id",
                "binding_id",
                "record_type",
                "source_record_key",
            },
        )
        return cls(
            source_instance_id=_document_text(document, "source_instance_id"),
            binding_id=_document_text(document, "binding_id"),
            record_type=_document_text(document, "record_type"),
            source_record_key=_document_text(document, "source_record_key"),
        )


class IdentityResolutionStatus(str, Enum):
    """Explicit review state; never the output of an Ontology matcher."""

    CONFIRMED = "confirmed"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    """One explicit identity-provider result for a source record."""

    source_identity: SourceRecordIdentity
    status: IdentityResolutionStatus
    canonical_object_id: UUID | None = None
    candidate_object_ids: tuple[UUID, ...] | list[UUID] = ()
    resolution_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_identity, SourceRecordIdentity):
            raise TypeError("source_identity must be a SourceRecordIdentity")
        if not isinstance(self.status, IdentityResolutionStatus):
            raise TypeError("status must be an IdentityResolutionStatus")
        if self.canonical_object_id is not None and not isinstance(
            self.canonical_object_id,
            UUID,
        ):
            raise TypeError("canonical_object_id must be a UUID or None")
        candidates = tuple(self.candidate_object_ids)
        if any(not isinstance(item, UUID) for item in candidates):
            raise TypeError("candidate_object_ids must contain UUID values")
        candidates = tuple(sorted(candidates, key=str))
        if len(candidates) != len(set(candidates)):
            raise ValueError("candidate_object_ids must not contain duplicates")
        object.__setattr__(self, "candidate_object_ids", candidates)
        if self.resolution_ref is not None:
            _non_empty_text("resolution_ref", self.resolution_ref)

        if self.status is IdentityResolutionStatus.CONFIRMED:
            if self.canonical_object_id is None:
                raise ValueError("confirmed identity requires canonical_object_id")
            if candidates:
                raise ValueError("confirmed identity cannot contain candidates")
            if self.resolution_ref is None:
                raise ValueError("confirmed identity requires resolution_ref")
        elif self.status is IdentityResolutionStatus.UNRESOLVED:
            if self.canonical_object_id is not None or candidates:
                raise ValueError(
                    "unresolved identity cannot contain a canonical ID or candidates"
                )
        else:
            if self.canonical_object_id is not None:
                raise ValueError("conflicting identity cannot select a canonical ID")
            if len(candidates) < 2:
                raise ValueError("conflicting identity requires at least two candidates")
            if self.resolution_ref is None:
                raise ValueError("conflicting identity requires resolution_ref")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "source_identity": self.source_identity.to_dict(),
            "status": self.status.value,
            "canonical_object_id": (
                None
                if self.canonical_object_id is None
                else str(self.canonical_object_id)
            ),
            "candidate_object_ids": [str(item) for item in self.candidate_object_ids],
            "resolution_ref": self.resolution_ref,
        }

    @classmethod
    def from_dict(cls, value: object) -> IdentityResolution:
        document = _exact_document(
            value,
            name="identity resolution",
            keys={
                "source_identity",
                "status",
                "canonical_object_id",
                "candidate_object_ids",
                "resolution_ref",
            },
        )
        raw_canonical_id = document["canonical_object_id"]
        if raw_canonical_id is not None and not isinstance(raw_canonical_id, str):
            raise ValueError("canonical_object_id must be a UUID string or null")
        raw_candidates = _document_list(document, "candidate_object_ids")
        if any(not isinstance(item, str) for item in raw_candidates):
            raise ValueError("candidate_object_ids must be a list of UUID strings")
        raw_resolution_ref = document["resolution_ref"]
        if raw_resolution_ref is not None and not isinstance(raw_resolution_ref, str):
            raise ValueError("resolution_ref must be a string or null")
        return cls(
            source_identity=SourceRecordIdentity.from_dict(
                document["source_identity"]
            ),
            status=IdentityResolutionStatus(_document_text(document, "status")),
            canonical_object_id=(
                None if raw_canonical_id is None else UUID(raw_canonical_id)
            ),
            candidate_object_ids=tuple(
                UUID(item) for item in cast(list[str], raw_candidates)
            ),
            resolution_ref=cast(str | None, raw_resolution_ref),
        )


@dataclass(frozen=True, slots=True)
class IdentityCrosswalkSnapshot:
    """Content-addressed identity-provider output selected by a Product host."""

    deployment_id: str
    identity_namespace: str
    revision: str
    entries: tuple[IdentityResolution, ...] | list[IdentityResolution]
    format: str = IDENTITY_CROSSWALK_FORMAT

    def __post_init__(self) -> None:
        for name in ("deployment_id", "identity_namespace", "revision"):
            _non_empty_text(name, getattr(self, name))
        entries = tuple(self.entries)
        if any(not isinstance(item, IdentityResolution) for item in entries):
            raise TypeError("entries must contain IdentityResolution values")
        entries = tuple(sorted(entries, key=lambda item: item.source_identity.sort_key))
        identities = [item.source_identity for item in entries]
        if len(identities) != len(set(identities)):
            raise ValueError("identity crosswalk contains duplicate source records")
        object.__setattr__(self, "entries", entries)
        if self.format != IDENTITY_CROSSWALK_FORMAT:
            raise ValueError("unsupported identity crosswalk format")

    @property
    def crosswalk_digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def resolve_identity(
        self,
        source_identity: SourceRecordIdentity,
    ) -> IdentityResolution | None:
        if not isinstance(source_identity, SourceRecordIdentity):
            raise TypeError("source_identity must be a SourceRecordIdentity")
        return next(
            (
                item
                for item in self.entries
                if item.source_identity == source_identity
            ),
            None,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": self.format,
            "deployment_id": self.deployment_id,
            "identity_namespace": self.identity_namespace,
            "revision": self.revision,
            "entries": [item.to_dict() for item in self.entries],
        }

    def to_json(self) -> str:
        return dump_json_value(
            self.to_dict(),
            name="identity crosswalk snapshot",
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> IdentityCrosswalkSnapshot:
        try:
            document = _exact_document(
                json.loads(payload),
                name="identity crosswalk snapshot",
                keys={
                    "format",
                    "deployment_id",
                    "identity_namespace",
                    "revision",
                    "entries",
                },
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid identity crosswalk JSON: {exc}") from exc
        if document["format"] != IDENTITY_CROSSWALK_FORMAT:
            raise ValueError("unsupported identity crosswalk format")
        return cls(
            deployment_id=_document_text(document, "deployment_id"),
            identity_namespace=_document_text(document, "identity_namespace"),
            revision=_document_text(document, "revision"),
            entries=[
                IdentityResolution.from_dict(item)
                for item in _document_list(document, "entries")
            ],
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


def _document_text(document: dict[str, JSONValue], name: str) -> str:
    value = document[name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"identity crosswalk {name} must be a non-empty string")
    return value


def _document_list(
    document: dict[str, JSONValue],
    name: str,
) -> list[JSONValue]:
    value = document[name]
    if not isinstance(value, list):
        raise ValueError(f"identity crosswalk {name} must be a list")
    return value


__all__ = [
    "IDENTITY_CROSSWALK_FORMAT",
    "IdentityCrosswalkSnapshot",
    "IdentityResolution",
    "IdentityResolutionStatus",
    "SourceRecordIdentity",
]
