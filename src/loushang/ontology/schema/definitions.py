"""Serializable, runtime-neutral ontology schema definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ValueType(str, Enum):
    """Stable scalar names used at the schema boundary."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    JSON = "json"


class LinkCardinality(str, Enum):
    """Serializable link cardinalities."""

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class StateAuthority(str, Enum):
    """Declared owner class; not a binding or execution authorization."""

    SOURCE_BACKED = "source-backed"
    ONTOLOGY_OWNED = "ontology-owned"
    DERIVED = "derived"


@dataclass(frozen=True, slots=True)
class SchemaVersion:
    """Opaque schema version validated by :class:`OntologyCompiler`."""

    value: str

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PropertyDefinition:
    """Serializable property declaration.

    ``value_type`` and ``default`` deliberately accept ``object`` at the draft
    boundary. The compiler turns valid values into strict immutable schema
    content and reports invalid values as diagnostics instead of leaking
    incidental constructor exceptions. ``semantic_id`` and ``state_authority``
    are compiler-required when the property belongs to an object type, but not
    when the same draft shape describes a structural interface member.
    """

    name: str
    value_type: ValueType | object
    semantic_id: str | None = field(default=None, kw_only=True)
    state_authority: StateAuthority | object | None = field(
        default=None,
        kw_only=True,
    )
    required: bool = False
    unique: bool = False
    indexed: bool = False
    default: object = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class InterfaceTypeDefinition:
    """Named structural property contract implemented by object types.

    Interface conformance consumes property name, value type, and requiredness.
    Other reusable ``PropertyDefinition`` metadata does not impose storage or
    uniqueness behavior on implementing object types.
    """

    name: str
    properties: tuple[PropertyDefinition, ...] | list[PropertyDefinition] = field(
        default_factory=tuple
    )
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", tuple(self.properties))


@dataclass(frozen=True, slots=True)
class ObjectTypeDefinition:
    """Serializable object-type declaration."""

    name: str
    semantic_id: str | None = field(default=None, kw_only=True)
    state_authority: StateAuthority | object | None = field(
        default=None,
        kw_only=True,
    )
    properties: tuple[PropertyDefinition, ...] | list[PropertyDefinition] = field(
        default_factory=tuple
    )
    parent_types: tuple[str, ...] | list[str] = field(default_factory=tuple)
    abstract: bool = False
    icon: str | None = None
    description: str = ""
    display_name_property: str | None = None
    interfaces: tuple[str, ...] | list[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", tuple(self.properties))
        object.__setattr__(self, "parent_types", tuple(self.parent_types))
        object.__setattr__(self, "interfaces", tuple(self.interfaces))


@dataclass(frozen=True, slots=True)
class LinkTypeDefinition:
    """Serializable link-type declaration."""

    name: str
    source_type: str
    target_type: str
    semantic_id: str | None = field(default=None, kw_only=True)
    state_authority: StateAuthority | object | None = field(
        default=None,
        kw_only=True,
    )
    cardinality: LinkCardinality | object = LinkCardinality.ONE_TO_MANY
    required: bool = False
    inverse_name: str | None = None
    temporal: bool = True
    description: str = ""


@dataclass(frozen=True, slots=True)
class ActionParameterDefinition:
    """One typed input accepted by a published semantic Action."""

    name: str
    value_type: ValueType | object
    description: str = ""


@dataclass(frozen=True, slots=True)
class SetPropertyEffectDefinition:
    """Set one stable property from one named Action parameter."""

    property_id: str
    value_parameter: str


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """First narrow published Action contract compiled into Schema v4."""

    name: str
    target_object_type_id: str
    parameters: (
        tuple[ActionParameterDefinition, ...] | list[ActionParameterDefinition]
    )
    effect: SetPropertyEffectDefinition | object
    policy_requirement_ref: str
    semantic_id: str | None = field(default=None, kw_only=True)
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", tuple(self.parameters))


@dataclass(frozen=True, slots=True)
class OntologyPackageDraft:
    """Caller-owned declarations submitted to the pure schema compiler."""

    package_id: str
    namespace: str
    version: SchemaVersion | str
    object_types: tuple[ObjectTypeDefinition, ...] | list[ObjectTypeDefinition] = field(
        default_factory=tuple
    )
    link_types: tuple[LinkTypeDefinition, ...] | list[LinkTypeDefinition] = field(
        default_factory=tuple
    )
    interface_types: tuple[InterfaceTypeDefinition, ...] | list[
        InterfaceTypeDefinition
    ] = field(default_factory=tuple)
    actions: tuple[ActionDefinition, ...] | list[ActionDefinition] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        if isinstance(self.version, str):
            object.__setattr__(self, "version", SchemaVersion(self.version))
        object.__setattr__(self, "interface_types", tuple(self.interface_types))
        object.__setattr__(self, "object_types", tuple(self.object_types))
        object.__setattr__(self, "link_types", tuple(self.link_types))
        object.__setattr__(self, "actions", tuple(self.actions))


__all__ = [
    "ActionDefinition",
    "ActionParameterDefinition",
    "InterfaceTypeDefinition",
    "LinkCardinality",
    "LinkTypeDefinition",
    "ObjectTypeDefinition",
    "OntologyPackageDraft",
    "PropertyDefinition",
    "SchemaVersion",
    "SetPropertyEffectDefinition",
    "StateAuthority",
    "ValueType",
]
