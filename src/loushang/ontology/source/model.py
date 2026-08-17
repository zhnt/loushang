"""Immutable contracts for mapped source snapshots selected by a Product."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import cast
from uuid import UUID

from loushang.foundation.json import (
    JSONValue,
    dump_json_value,
    require_json_mapping,
)
from loushang.ontology.schema.identity import SchemaIdentity

SOURCE_BINDING_FORMAT = "loushang.ontology.source-binding/v1"


def _non_empty_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _finite(name: str, value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(
        float(cast(int | float, value))
    ):
        raise ValueError(f"{name} must be a finite number")
    return float(cast(int | float, value))


@dataclass(frozen=True, slots=True)
class SourceInputRevision:
    """One coordinate in a materialization source revision vector."""

    binding_id: str
    mapping_version: str
    source_revision: str

    def __post_init__(self) -> None:
        for name in ("binding_id", "mapping_version", "source_revision"):
            _non_empty_text(name, getattr(self, name))


class SourceCoverage(str, Enum):
    """Declared completeness of one mapped snapshot for its source view."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SourceInputCut:
    """Exact mapped input selected into an immutable materialization cut."""

    binding_id: str
    mapping_version: str
    source_revision: str
    payload_digest: str
    coverage: SourceCoverage

    def __post_init__(self) -> None:
        for name in (
            "binding_id",
            "mapping_version",
            "source_revision",
            "payload_digest",
        ):
            _non_empty_text(name, getattr(self, name))
        if len(self.payload_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.payload_digest
        ):
            raise ValueError("payload_digest must be a lowercase SHA-256 digest")
        if not isinstance(self.coverage, SourceCoverage):
            raise TypeError("coverage must be a SourceCoverage")

    @property
    def revision(self) -> SourceInputRevision:
        return SourceInputRevision(
            self.binding_id,
            self.mapping_version,
            self.source_revision,
        )


@dataclass(frozen=True, slots=True)
class SourceBinding:
    """Bind source-owned schema states to one versioned Product mapping.

    Targets are package-local stable semantic IDs, never renameable API names.
    This contract identifies authority; it contains no connector or scheduler.
    """

    binding_id: str
    mapping_version: str
    schema_identity: SchemaIdentity
    object_existence_ids: tuple[str, ...] = ()
    property_ids: tuple[str, ...] = ()
    link_type_ids: tuple[str, ...] = ()
    coverage: SourceCoverage = SourceCoverage.COMPLETE

    def __post_init__(self) -> None:
        _non_empty_text("binding_id", self.binding_id)
        _non_empty_text("mapping_version", self.mapping_version)
        if not isinstance(self.schema_identity, SchemaIdentity):
            raise TypeError("schema_identity must be a SchemaIdentity")
        if not isinstance(self.coverage, SourceCoverage):
            raise TypeError("coverage must be a SourceCoverage")
        for name in ("object_existence_ids", "property_ids", "link_type_ids"):
            raw = tuple(getattr(self, name))
            if any(not isinstance(item, str) for item in raw):
                raise TypeError(f"{name} must contain strings")
            values = tuple(sorted(raw))
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{name} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
            object.__setattr__(self, name, values)
        if (
            not self.object_existence_ids
            and not self.property_ids
            and not self.link_type_ids
        ):
            raise ValueError(
                "source binding must declare at least one authority target"
            )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": SOURCE_BINDING_FORMAT,
            "binding_id": self.binding_id,
            "mapping_version": self.mapping_version,
            "schema_identity": self.schema_identity.to_dict(),
            "object_existence_ids": list(self.object_existence_ids),
            "property_ids": list(self.property_ids),
            "link_type_ids": list(self.link_type_ids),
            "coverage": self.coverage.value,
        }

    @classmethod
    def from_dict(cls, value: object) -> SourceBinding:
        document = require_json_mapping(value, name="source binding")
        if document.get("format") != SOURCE_BINDING_FORMAT:
            raise ValueError("unsupported source binding format")
        return cls(
            binding_id=_document_text(document, "binding_id"),
            mapping_version=_document_text(document, "mapping_version"),
            schema_identity=SchemaIdentity.from_dict(document["schema_identity"]),
            object_existence_ids=_document_text_tuple(
                document,
                "object_existence_ids",
            ),
            property_ids=_document_text_tuple(document, "property_ids"),
            link_type_ids=_document_text_tuple(document, "link_type_ids"),
            coverage=SourceCoverage(_document_text(document, "coverage")),
        )


@dataclass(frozen=True, slots=True, init=False)
class MappedSourceProperty:
    """One source field already mapped to a stable ontology property ID."""

    property_id: str
    field_ref: str
    valid_from: float
    _value_json: str = field(repr=False)

    def __init__(
        self,
        *,
        property_id: str,
        value: object,
        field_ref: str,
        valid_from: float,
    ) -> None:
        object.__setattr__(
            self, "property_id", _non_empty_text("property_id", property_id)
        )
        object.__setattr__(self, "field_ref", _non_empty_text("field_ref", field_ref))
        object.__setattr__(self, "valid_from", _finite("valid_from", valid_from))
        object.__setattr__(
            self,
            "_value_json",
            dump_json_value(value, name="mapped source property value", sort_keys=True),
        )

    @property
    def raw_value(self) -> JSONValue:
        return cast(JSONValue, json.loads(self._value_json))

    def _to_digest_document(self) -> dict[str, JSONValue]:
        return {
            "property_id": self.property_id,
            "field_ref": self.field_ref,
            "valid_from": self.valid_from,
            "value": self.raw_value,
        }


@dataclass(frozen=True, slots=True, init=False)
class MappedSourceObject:
    """One canonical object identity selected by an application mapping."""

    object_id: UUID
    object_type_id: str
    source_record_ref: str
    identity_field_ref: str
    _properties: tuple[MappedSourceProperty, ...] = field(repr=False)

    def __init__(
        self,
        *,
        object_id: UUID,
        object_type_id: str,
        source_record_ref: str,
        identity_field_ref: str,
        properties: Iterable[MappedSourceProperty] = (),
    ) -> None:
        if not isinstance(object_id, UUID):
            raise TypeError("object_id must be a UUID")
        raw_properties = tuple(properties)
        if any(not isinstance(item, MappedSourceProperty) for item in raw_properties):
            raise TypeError("properties must contain MappedSourceProperty values")
        values = tuple(sorted(raw_properties, key=lambda item: item.property_id))
        ids = [item.property_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("mapped source object contains duplicate properties")
        object.__setattr__(self, "object_id", object_id)
        object.__setattr__(
            self,
            "object_type_id",
            _non_empty_text("object_type_id", object_type_id),
        )
        object.__setattr__(
            self,
            "source_record_ref",
            _non_empty_text("source_record_ref", source_record_ref),
        )
        object.__setattr__(
            self,
            "identity_field_ref",
            _non_empty_text("identity_field_ref", identity_field_ref),
        )
        object.__setattr__(self, "_properties", values)

    @property
    def properties(self) -> tuple[MappedSourceProperty, ...]:
        return self._properties

    def _to_digest_document(self) -> dict[str, JSONValue]:
        return {
            "object_id": str(self.object_id),
            "object_type_id": self.object_type_id,
            "source_record_ref": self.source_record_ref,
            "identity_field_ref": self.identity_field_ref,
            "properties": [item._to_digest_document() for item in self._properties],
        }


@dataclass(frozen=True, slots=True, init=False)
class MappedSourceLink:
    """One source-owned relationship already mapped to a stable link ID."""

    source_id: UUID
    link_type_id: str
    target_id: UUID
    source_record_ref: str
    field_ref: str
    valid_from: float
    _properties_json: str = field(repr=False)

    def __init__(
        self,
        *,
        source_id: UUID,
        link_type_id: str,
        target_id: UUID,
        source_record_ref: str,
        field_ref: str,
        valid_from: float,
        properties: object | None = None,
    ) -> None:
        if not isinstance(source_id, UUID) or not isinstance(target_id, UUID):
            raise TypeError("mapped source link endpoints must be UUID values")
        checked_properties = require_json_mapping(
            {} if properties is None else properties,
            name="mapped source link properties",
        )
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(
            self,
            "link_type_id",
            _non_empty_text("link_type_id", link_type_id),
        )
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(
            self,
            "source_record_ref",
            _non_empty_text("source_record_ref", source_record_ref),
        )
        object.__setattr__(self, "field_ref", _non_empty_text("field_ref", field_ref))
        object.__setattr__(self, "valid_from", _finite("valid_from", valid_from))
        object.__setattr__(
            self,
            "_properties_json",
            dump_json_value(
                checked_properties,
                name="mapped source link properties",
                sort_keys=True,
            ),
        )

    @property
    def properties(self) -> dict[str, JSONValue]:
        return cast(dict[str, JSONValue], json.loads(self._properties_json))

    def _to_digest_document(self) -> dict[str, JSONValue]:
        return {
            "source_id": str(self.source_id),
            "link_type_id": self.link_type_id,
            "target_id": str(self.target_id),
            "source_record_ref": self.source_record_ref,
            "field_ref": self.field_ref,
            "valid_from": self.valid_from,
            "properties": self.properties,
        }


@dataclass(frozen=True, slots=True, init=False)
class MappedSourceSnapshot:
    """An immutable mapped snapshot payload for one source binding revision."""

    _objects: tuple[MappedSourceObject, ...] = field(repr=False)
    _links: tuple[MappedSourceLink, ...] = field(repr=False)

    def __init__(
        self,
        *,
        objects: Iterable[MappedSourceObject] = (),
        links: Iterable[MappedSourceLink] = (),
    ) -> None:
        raw_objects = tuple(objects)
        if any(not isinstance(item, MappedSourceObject) for item in raw_objects):
            raise TypeError("objects must contain MappedSourceObject values")
        values = tuple(sorted(raw_objects, key=lambda item: str(item.object_id)))
        ids = [item.object_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("mapped source snapshot contains duplicate object IDs")
        raw_links = tuple(links)
        if any(not isinstance(item, MappedSourceLink) for item in raw_links):
            raise TypeError("links must contain MappedSourceLink values")
        link_values = tuple(
            sorted(
                raw_links,
                key=lambda item: (
                    str(item.source_id),
                    item.link_type_id,
                    str(item.target_id),
                ),
            )
        )
        link_keys = [
            (item.source_id, item.link_type_id, item.target_id) for item in link_values
        ]
        if len(link_keys) != len(set(link_keys)):
            raise ValueError("mapped source snapshot contains duplicate links")
        object.__setattr__(self, "_objects", values)
        object.__setattr__(self, "_links", link_values)

    @property
    def objects(self) -> tuple[MappedSourceObject, ...]:
        return self._objects

    @property
    def links(self) -> tuple[MappedSourceLink, ...]:
        return self._links

    @property
    def content_digest(self) -> str:
        document: dict[str, JSONValue] = {
            "objects": [item._to_digest_document() for item in self._objects],
            "links": [item._to_digest_document() for item in self._links],
        }
        payload = dump_json_value(
            document,
            name="mapped source snapshot digest document",
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MappedSourceInput:
    """One reproducible mapped snapshot selected for materialization.

    Change-set payloads are intentionally deferred until a base-revision chain
    contract is implemented; this first slice never presents a delta as a full
    snapshot.
    """

    binding_id: str
    mapping_version: str
    source_revision: str
    coverage: SourceCoverage
    payload: MappedSourceSnapshot

    def __post_init__(self) -> None:
        for name in ("binding_id", "mapping_version", "source_revision"):
            _non_empty_text(name, getattr(self, name))
        if not isinstance(self.payload, MappedSourceSnapshot):
            raise TypeError("payload must be a MappedSourceSnapshot")
        if not isinstance(self.coverage, SourceCoverage):
            raise TypeError("coverage must be a SourceCoverage")

    @property
    def revision(self) -> SourceInputRevision:
        return SourceInputRevision(
            self.binding_id,
            self.mapping_version,
            self.source_revision,
        )

    @property
    def cut(self) -> SourceInputCut:
        return SourceInputCut(
            self.binding_id,
            self.mapping_version,
            self.source_revision,
            self.payload.content_digest,
            self.coverage,
        )


def _document_text(document: dict[str, JSONValue], name: str) -> str:
    try:
        return _non_empty_text(name, document[name])
    except KeyError as exc:
        raise ValueError(f"source binding is missing {name}") from exc


def _document_text_tuple(
    document: dict[str, JSONValue],
    name: str,
) -> tuple[str, ...]:
    try:
        value = document[name]
    except KeyError as exc:
        raise ValueError(f"source binding is missing {name}") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"source binding {name} must be a list of strings")
    return tuple(cast(list[str], value))


__all__ = [
    "SOURCE_BINDING_FORMAT",
    "MappedSourceInput",
    "MappedSourceLink",
    "MappedSourceObject",
    "MappedSourceProperty",
    "MappedSourceSnapshot",
    "SourceBinding",
    "SourceCoverage",
    "SourceInputCut",
    "SourceInputRevision",
]
