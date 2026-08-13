"""Immutable materialized object, property, link, and snapshot values."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import cast
from uuid import UUID

from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.ontology.schema import (
    CompiledObjectTypeDefinition,
    CompiledOntologySchema,
    CompiledPropertyDefinition,
    LinkCardinality,
    SchemaIdentity,
    ValueType,
)
from loushang.ontology.source import SourceInputCut, SourceInputRevision


@dataclass(frozen=True, slots=True)
class MaterializationCut:
    """Exact schema, mapped-source payloads, and Fact selection coordinates."""

    schema_identity: SchemaIdentity
    source_inputs: tuple[SourceInputCut, ...]
    fact_watermark: int
    valid_at: float
    recorded_at: float
    fact_revalidation_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.schema_identity, SchemaIdentity):
            raise TypeError("schema_identity must be a SchemaIdentity")
        if any(
            not isinstance(item, SourceInputCut) for item in self.source_inputs
        ):
            raise TypeError("source_inputs must contain SourceInputCut values")
        values = tuple(
            sorted(
                self.source_inputs,
                key=lambda item: (item.binding_id, item.mapping_version),
            )
        )
        bindings = [item.binding_id for item in values]
        if len(bindings) != len(set(bindings)):
            raise ValueError("materialization cut contains duplicate source bindings")
        object.__setattr__(self, "source_inputs", values)
        if type(self.fact_watermark) is not int or self.fact_watermark < 0:
            raise ValueError("fact_watermark must be a non-negative integer")
        for name in ("valid_at", "recorded_at"):
            object.__setattr__(self, name, _finite(name, getattr(self, name)))
        if self.fact_revalidation_digest is not None and (
            len(self.fact_revalidation_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.fact_revalidation_digest
            )
        ):
            raise ValueError(
                "fact_revalidation_digest must be a lowercase SHA-256 digest or None"
            )


@dataclass(frozen=True, slots=True)
class FactOrigin:
    """A projected value selected from one immutable semantic Fact."""

    fact_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.fact_id, UUID):
            raise TypeError("fact_id must be a UUID")


@dataclass(frozen=True, slots=True)
class SourceOrigin:
    """A projected value selected from one immutable mapped source field."""

    binding_id: str
    mapping_version: str
    source_revision: str
    source_record_ref: str
    field_ref: str

    def __post_init__(self) -> None:
        for name in (
            "binding_id",
            "mapping_version",
            "source_revision",
            "source_record_ref",
            "field_ref",
        ):
            _non_empty_text(name, getattr(self, name))

    @property
    def input_revision(self) -> SourceInputRevision:
        return SourceInputRevision(
            self.binding_id,
            self.mapping_version,
            self.source_revision,
        )


@dataclass(frozen=True, slots=True)
class SchemaDefaultOrigin:
    """A projected value supplied by the selected compiled schema."""

    schema_identity: SchemaIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.schema_identity, SchemaIdentity):
            raise TypeError("schema_identity must be a SchemaIdentity")


OperationalOrigin = FactOrigin | SourceOrigin
ValueOrigin = OperationalOrigin | SchemaDefaultOrigin


@dataclass(frozen=True, slots=True, init=False)
class ProjectedProperty:
    """One immutable property value selected for a bitemporal snapshot."""

    name: str
    value_type: ValueType
    valid_from: float
    fact_id: UUID | None
    author_ref: str | None
    source_ref: str
    origin: ValueOrigin
    _value_json: str = field(repr=False)

    def __init__(
        self,
        *,
        name: str,
        value_type: ValueType,
        value: object,
        valid_from: float,
        source_ref: str,
        origin: ValueOrigin,
        fact_id: UUID | None = None,
        author_ref: str | None = None,
    ) -> None:
        _non_empty_text("name", name)
        if not isinstance(value_type, ValueType):
            raise TypeError("value_type must be a ValueType")
        _validate_value_type(name, value_type, value)
        if fact_id is not None and not isinstance(fact_id, UUID):
            raise TypeError("fact_id must be a UUID or None")
        if not isinstance(origin, (FactOrigin, SourceOrigin, SchemaDefaultOrigin)):
            raise TypeError("origin must be a supported ValueOrigin")
        if isinstance(origin, FactOrigin) and fact_id != origin.fact_id:
            raise ValueError("FactOrigin must match projected property fact_id")
        if not isinstance(origin, FactOrigin) and fact_id is not None:
            raise ValueError("only FactOrigin may carry a projected property fact_id")
        if author_ref is not None:
            _non_empty_text("author_ref", author_ref)
        _non_empty_text("source_ref", source_ref)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value_type", value_type)
        object.__setattr__(self, "valid_from", _finite("valid_from", valid_from))
        object.__setattr__(self, "fact_id", fact_id)
        object.__setattr__(self, "author_ref", author_ref)
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(
            self,
            "_value_json",
            dump_json_value(value, name="projected property value", sort_keys=True),
        )

    @property
    def raw_value(self) -> JSONValue:
        return cast(JSONValue, json.loads(self._value_json))

    @property
    def value(self) -> object:
        value = self.raw_value
        if self.value_type is ValueType.DATETIME:
            assert isinstance(value, str)
            return datetime.fromisoformat(value)
        return value


@dataclass(frozen=True, slots=True, init=False)
class ProjectedLink:
    """One immutable active link selected for a bitemporal snapshot."""

    source_id: UUID
    link_type: str
    target_id: UUID
    valid_from: float
    fact_id: UUID | None
    source_ref: str
    origin: OperationalOrigin
    _properties_json: str = field(repr=False)

    def __init__(
        self,
        *,
        source_id: UUID,
        link_type: str,
        target_id: UUID,
        properties: object,
        valid_from: float,
        source_ref: str,
        origin: OperationalOrigin,
        fact_id: UUID | None = None,
    ) -> None:
        if not isinstance(source_id, UUID) or not isinstance(target_id, UUID):
            raise TypeError("projected link endpoints must be UUID values")
        if fact_id is not None and not isinstance(fact_id, UUID):
            raise TypeError("projected link fact_id must be a UUID or None")
        _validate_operational_origin("projected link", origin, fact_id)
        if isinstance(origin, FactOrigin) and fact_id != origin.fact_id:
            raise ValueError("projected link FactOrigin must match fact_id")
        _non_empty_text("link_type", link_type)
        _non_empty_text("source_ref", source_ref)
        checked_properties = require_json_mapping(
            properties,
            name="projected link properties",
        )
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "link_type", link_type)
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "valid_from", _finite("valid_from", valid_from))
        object.__setattr__(self, "fact_id", fact_id)
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(
            self,
            "_properties_json",
            dump_json_value(
                checked_properties,
                name="projected link properties",
                sort_keys=True,
            ),
        )

    @property
    def properties(self) -> dict[str, JSONValue]:
        return cast(dict[str, JSONValue], json.loads(self._properties_json))


@dataclass(frozen=True, slots=True, init=False)
class ProjectedObject:
    """One immutable object with detached property values."""

    id: UUID
    object_type: str
    origin: OperationalOrigin
    _properties: tuple[ProjectedProperty, ...] = field(repr=False)

    def __init__(
        self,
        *,
        object_id: UUID,
        object_type: str,
        origin: OperationalOrigin,
        properties: Iterable[ProjectedProperty] = (),
    ) -> None:
        if not isinstance(object_id, UUID):
            raise TypeError("object_id must be a UUID")
        _validate_operational_origin("projected object", origin, None)
        _non_empty_text("object_type", object_type)
        values = tuple(sorted(properties, key=lambda item: item.name))
        names = [item.name for item in values]
        if len(names) != len(set(names)):
            raise ValueError("projected object contains duplicate properties")
        object.__setattr__(self, "id", object_id)
        object.__setattr__(self, "object_type", object_type)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "_properties", values)

    @property
    def properties(self) -> tuple[ProjectedProperty, ...]:
        return self._properties

    def property(self, name: str) -> ProjectedProperty | None:
        return next((item for item in self._properties if item.name == name), None)

    def get(self, name: str) -> object | None:
        prop = self.property(name)
        return None if prop is None else prop.value

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "id": str(self.id),
            "object_type": self.object_type,
            "properties": {prop.name: prop.raw_value for prop in self._properties},
        }


@dataclass(frozen=True, slots=True)
class ProjectionState:
    """Immutable reproducibility coordinates for one projection snapshot."""

    schema_identity: SchemaIdentity
    projection_version: int
    materialization_cut: MaterializationCut
    built_at: float

    def __post_init__(self) -> None:
        if not isinstance(self.schema_identity, SchemaIdentity):
            raise TypeError("schema_identity must be a SchemaIdentity")
        if not isinstance(self.materialization_cut, MaterializationCut):
            raise TypeError("materialization_cut must be a MaterializationCut")
        if self.schema_identity != self.materialization_cut.schema_identity:
            raise ValueError(
                "projection state and materialization cut schema identities disagree"
            )
        if type(self.projection_version) is not int or self.projection_version < 1:
            raise ValueError("projection_version must be a positive integer")
        object.__setattr__(self, "built_at", _finite("built_at", self.built_at))

    @property
    def schema_version(self) -> str:
        return self.schema_identity.version

    @property
    def fact_watermark(self) -> int:
        return self.materialization_cut.fact_watermark

    @property
    def valid_at(self) -> float:
        return self.materialization_cut.valid_at

    @property
    def recorded_at(self) -> float:
        return self.materialization_cut.recorded_at


class ProjectionFreshnessStatus(str, Enum):
    """Comparison result between a projection cut and an observed Fact head."""

    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class ProjectionFreshness:
    """Detached runtime observation; never part of immutable snapshot state."""

    status: ProjectionFreshnessStatus
    projection_fact_watermark: int
    observed_fact_watermark: int | None
    observed_at: float
    projection_source_inputs: tuple[SourceInputRevision, ...] = ()
    observed_source_heads: tuple[SourceInputRevision, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProjectionFreshnessStatus):
            raise TypeError("status must be a ProjectionFreshnessStatus")
        for name in ("projection_fact_watermark", "observed_fact_watermark"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        object.__setattr__(
            self, "observed_at", _finite("observed_at", self.observed_at)
        )
        for name in ("projection_source_inputs", "observed_source_heads"):
            values = tuple(getattr(self, name))
            if any(not isinstance(item, SourceInputRevision) for item in values):
                raise TypeError(f"{name} must contain SourceInputRevision values")
            object.__setattr__(self, name, values)
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(item, str) or not item for item in self.diagnostics
        ):
            raise TypeError("diagnostics must be a tuple of non-empty strings")


def evaluate_projection_freshness(
    state: ProjectionState,
    *,
    observed_fact_watermark: int | None,
    observed_source_heads: Iterable[SourceInputRevision] | None = None,
    observed_at: float,
) -> ProjectionFreshness:
    """Compare an immutable build cut with explicit Fact and source observations."""

    if not isinstance(state, ProjectionState):
        raise TypeError("state must be a ProjectionState")
    expected_sources = tuple(
        item.revision for item in state.materialization_cut.source_inputs
    )
    observed_sources = (
        () if observed_source_heads is None else tuple(observed_source_heads)
    )
    if any(not isinstance(item, SourceInputRevision) for item in observed_sources):
        raise TypeError("observed_source_heads must contain SourceInputRevision values")
    observed_sources = tuple(
        sorted(
            observed_sources,
            key=lambda item: (item.binding_id, item.mapping_version),
        )
    )
    observed_by_binding: dict[str, SourceInputRevision] = {}
    for item in observed_sources:
        if item.binding_id in observed_by_binding:
            raise ValueError("observed_source_heads contains duplicate source bindings")
        observed_by_binding[item.binding_id] = item

    diagnostics: list[str] = []
    fact_status = ProjectionFreshnessStatus.CURRENT
    if observed_fact_watermark is None:
        fact_status = ProjectionFreshnessStatus.UNKNOWN
        diagnostics.append("current Fact watermark was not observed")
    elif type(observed_fact_watermark) is not int or observed_fact_watermark < 0:
        raise ValueError("observed_fact_watermark must be non-negative or None")
    elif observed_fact_watermark < state.fact_watermark:
        fact_status = ProjectionFreshnessStatus.DEGRADED
        diagnostics.append(
            "observed Fact watermark is behind the projection build watermark",
        )
    elif observed_fact_watermark > state.fact_watermark:
        fact_status = ProjectionFreshnessStatus.STALE

    source_status = ProjectionFreshnessStatus.CURRENT
    if expected_sources:
        missing = [
            item.binding_id
            for item in expected_sources
            if item.binding_id not in observed_by_binding
        ]
        if missing:
            source_status = ProjectionFreshnessStatus.UNKNOWN
            diagnostics.append(
                "source heads were not observed for: " + ", ".join(sorted(missing))
            )
        elif any(
            observed_by_binding[item.binding_id] != item for item in expected_sources
        ):
            source_status = ProjectionFreshnessStatus.STALE

    if ProjectionFreshnessStatus.DEGRADED in {fact_status, source_status}:
        status = ProjectionFreshnessStatus.DEGRADED
    elif ProjectionFreshnessStatus.UNKNOWN in {fact_status, source_status}:
        status = ProjectionFreshnessStatus.UNKNOWN
    elif ProjectionFreshnessStatus.STALE in {fact_status, source_status}:
        status = ProjectionFreshnessStatus.STALE
    else:
        status = ProjectionFreshnessStatus.CURRENT
    return ProjectionFreshness(
        status=status,
        projection_fact_watermark=state.fact_watermark,
        observed_fact_watermark=observed_fact_watermark,
        observed_at=observed_at,
        projection_source_inputs=expected_sources,
        observed_source_heads=observed_sources,
        diagnostics=tuple(diagnostics),
    )


@dataclass(frozen=True, slots=True, init=False)
class ProjectionSnapshot:
    """Detached, immutable, and fully rebuildable serving graph."""

    schema: CompiledOntologySchema
    state: ProjectionState
    fact_ids: tuple[UUID, ...]
    _objects: tuple[ProjectedObject, ...] = field(repr=False)
    _links: tuple[ProjectedLink, ...] = field(repr=False)

    def __init__(
        self,
        *,
        schema: CompiledOntologySchema,
        state: ProjectionState,
        objects: Iterable[ProjectedObject],
        links: Iterable[ProjectedLink],
        fact_ids: Iterable[UUID],
    ) -> None:
        object_values = tuple(sorted(objects, key=lambda item: str(item.id)))
        link_values = tuple(
            sorted(
                links,
                key=lambda item: (
                    str(item.source_id),
                    item.link_type,
                    str(item.target_id),
                ),
            )
        )
        object_ids = [item.id for item in object_values]
        link_keys = [
            (item.source_id, item.link_type, item.target_id) for item in link_values
        ]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("projection snapshot contains duplicate objects")
        if len(link_keys) != len(set(link_keys)):
            raise ValueError("projection snapshot contains duplicate links")
        known_ids = set(object_ids)
        if any(
            link.source_id not in known_ids or link.target_id not in known_ids
            for link in link_values
        ):
            raise ValueError("projection snapshot link endpoint is missing")
        if state.schema_identity != SchemaIdentity.from_schema(schema):
            raise ValueError(
                "projection state schema identity does not match its schema"
            )
        checked_fact_ids = tuple(fact_ids)
        if any(not isinstance(item, UUID) for item in checked_fact_ids):
            raise TypeError("projection fact_ids must contain only UUID values")
        known_fact_ids = set(checked_fact_ids)
        if any(
            prop.fact_id is not None and prop.fact_id not in known_fact_ids
            for obj in object_values
            for prop in obj.properties
        ) or any(
            link.fact_id is not None and link.fact_id not in known_fact_ids
            for link in link_values
        ):
            raise ValueError("projected values must reference selected fact_ids")
        source_revisions = {
            item.revision for item in state.materialization_cut.source_inputs
        }
        for obj in object_values:
            _validate_snapshot_origin(
                obj.origin,
                known_fact_ids=known_fact_ids,
                source_revisions=source_revisions,
                schema_identity=state.schema_identity,
            )
            for prop in obj.properties:
                _validate_snapshot_origin(
                    prop.origin,
                    known_fact_ids=known_fact_ids,
                    source_revisions=source_revisions,
                    schema_identity=state.schema_identity,
                )
        for link in link_values:
            _validate_snapshot_origin(
                link.origin,
                known_fact_ids=known_fact_ids,
                source_revisions=source_revisions,
                schema_identity=state.schema_identity,
            )
        _validate_schema_shape(schema, object_values, link_values)
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "fact_ids", checked_fact_ids)
        object.__setattr__(self, "_objects", object_values)
        object.__setattr__(self, "_links", link_values)

    @property
    def projection_state(self) -> ProjectionState:
        return self.state

    @property
    def objects(self) -> tuple[ProjectedObject, ...]:
        return self._objects

    @property
    def links(self) -> tuple[ProjectedLink, ...]:
        return self._links

    def read_snapshot(self) -> ProjectionSnapshot:
        """Return this immutable view for snapshot-consistent query evaluation."""

        return self

    def get(self, object_id: UUID) -> ProjectedObject | None:
        return next((item for item in self._objects if item.id == object_id), None)

    def get_by_type(self, object_type: str) -> tuple[ProjectedObject, ...]:
        return tuple(item for item in self._objects if item.object_type == object_type)

    def find_neighbors(
        self,
        object_id: UUID,
        link_type: str,
        direction: str = "outgoing",
    ) -> tuple[ProjectedObject, ...]:
        if direction not in {"outgoing", "incoming"}:
            raise ValueError("direction must be 'outgoing' or 'incoming'")
        neighbor_ids = (
            [
                link.target_id
                for link in self._links
                if link.source_id == object_id and link.link_type == link_type
            ]
            if direction == "outgoing"
            else [
                link.source_id
                for link in self._links
                if link.target_id == object_id and link.link_type == link_type
            ]
        )
        by_id = {item.id: item for item in self._objects}
        return tuple(by_id[item] for item in neighbor_ids)

    def all_objects(self) -> tuple[ProjectedObject, ...]:
        return self._objects


def _finite(name: str, value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(
        float(cast(int | float, value))
    ):
        raise ValueError(f"{name} must be a finite number")
    return float(cast(int | float, value))


def _validate_operational_origin(
    subject: str,
    origin: object,
    fact_id: UUID | None,
) -> None:
    if not isinstance(origin, (FactOrigin, SourceOrigin)):
        raise TypeError(f"{subject} origin must be a FactOrigin or SourceOrigin")
    if isinstance(origin, FactOrigin) and fact_id not in (None, origin.fact_id):
        raise ValueError(f"{subject} FactOrigin must match fact_id")
    if isinstance(origin, SourceOrigin) and fact_id is not None:
        raise ValueError(f"{subject} SourceOrigin cannot carry a fact_id")


def _validate_snapshot_origin(
    origin: ValueOrigin,
    *,
    known_fact_ids: set[UUID],
    source_revisions: set[SourceInputRevision],
    schema_identity: SchemaIdentity,
) -> None:
    if isinstance(origin, FactOrigin):
        if origin.fact_id not in known_fact_ids:
            raise ValueError("projected FactOrigin must reference a selected fact_id")
    elif isinstance(origin, SourceOrigin):
        if origin.input_revision not in source_revisions:
            raise ValueError(
                "projected SourceOrigin must reference the materialization cut"
            )
    elif origin.schema_identity != schema_identity:
        raise ValueError(
            "projected SchemaDefaultOrigin must match the projection schema"
        )


def _non_empty_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_value_type(name: str, value_type: ValueType, value: object) -> None:
    valid = True
    if value_type is ValueType.STRING:
        valid = isinstance(value, str)
    elif value_type is ValueType.INTEGER:
        valid = type(value) is int
    elif value_type is ValueType.NUMBER:
        valid = type(value) in (int, float) and math.isfinite(
            float(cast(int | float, value))
        )
    elif value_type is ValueType.BOOLEAN:
        valid = type(value) is bool
    elif value_type is ValueType.DATETIME:
        valid = isinstance(value, str)
        if valid:
            try:
                datetime.fromisoformat(cast(str, value))
            except ValueError:
                valid = False
    if not valid:
        raise ValueError(f"projected property '{name}' is not a {value_type.value}")


def _validate_schema_shape(
    schema: CompiledOntologySchema,
    objects: tuple[ProjectedObject, ...],
    links: tuple[ProjectedLink, ...],
) -> None:
    by_id = {item.id: item for item in objects}
    unique_values: dict[tuple[str, str, str], UUID] = {}
    for obj in objects:
        object_definition = schema.object_type(obj.object_type)
        if object_definition is None or object_definition.abstract:
            raise ValueError(
                f"projected object type '{obj.object_type}' is not materializable"
            )
        declarations = _schema_properties(schema, object_definition)
        present = {prop.name for prop in obj.properties}
        for name, (owner, definition) in declarations.items():
            if definition.required and name not in present:
                raise ValueError(
                    f"required projected property '{obj.object_type}.{name}' is missing"
                )
        for prop in obj.properties:
            declaration = declarations.get(prop.name)
            if declaration is None:
                raise ValueError(
                    f"projected property '{obj.object_type}.{prop.name}' is undeclared"
                )
            owner, definition = declaration
            if prop.value_type is not definition.value_type:
                raise ValueError(
                    f"projected property '{obj.object_type}.{prop.name}' has the wrong type"
                )
            if definition.unique:
                key = (
                    owner,
                    prop.name,
                    dump_json_value(prop.raw_value, sort_keys=True),
                )
                previous = unique_values.get(key)
                if previous is not None:
                    raise ValueError(
                        f"unique projected property '{owner}.{prop.name}' is duplicated"
                    )
                unique_values[key] = obj.id

    for link_definition in schema.link_types:
        matching = tuple(
            link for link in links if link.link_type == link_definition.name
        )
        outgoing: dict[UUID, int] = {}
        incoming: dict[UUID, int] = {}
        for link in matching:
            source = by_id[link.source_id]
            target = by_id[link.target_id]
            if (
                source.object_type != link_definition.source_type
                or target.object_type != link_definition.target_type
            ):
                raise ValueError(
                    f"projected link '{link_definition.name}' has invalid endpoint types"
                )
            outgoing[link.source_id] = outgoing.get(link.source_id, 0) + 1
            incoming[link.target_id] = incoming.get(link.target_id, 0) + 1
        if link_definition.cardinality in {
            LinkCardinality.ONE_TO_ONE,
            LinkCardinality.MANY_TO_ONE,
        } and any(count > 1 for count in outgoing.values()):
            raise ValueError(
                f"projected link '{link_definition.name}' violates outgoing cardinality"
            )
        if link_definition.cardinality in {
            LinkCardinality.ONE_TO_ONE,
            LinkCardinality.ONE_TO_MANY,
        } and any(count > 1 for count in incoming.values()):
            raise ValueError(
                f"projected link '{link_definition.name}' violates incoming cardinality"
            )
        if link_definition.required and any(
            obj.object_type == link_definition.source_type and obj.id not in outgoing
            for obj in objects
        ):
            raise ValueError(
                f"required projected link '{link_definition.name}' is missing"
            )

    known_link_types = {item.name for item in schema.link_types}
    if any(link.link_type not in known_link_types for link in links):
        raise ValueError("projection snapshot contains an undeclared link type")


def _schema_properties(
    schema: CompiledOntologySchema,
    object_type: CompiledObjectTypeDefinition,
) -> dict[str, tuple[str, CompiledPropertyDefinition]]:
    resolved: dict[str, tuple[str, CompiledPropertyDefinition]] = {}
    visited: set[str] = set()

    def visit(current: CompiledObjectTypeDefinition) -> None:
        if current.name in visited:
            return
        visited.add(current.name)
        for parent_name in current.parent_types:
            parent = schema.object_type(parent_name)
            if parent is not None:
                visit(parent)
        for definition in current.properties:
            resolved[definition.name] = (current.name, definition)

    visit(object_type)
    return resolved


__all__ = [
    "FactOrigin",
    "MaterializationCut",
    "OperationalOrigin",
    "ProjectedLink",
    "ProjectedObject",
    "ProjectedProperty",
    "ProjectionSnapshot",
    "ProjectionState",
    "SchemaDefaultOrigin",
    "SourceOrigin",
    "ValueOrigin",
]
