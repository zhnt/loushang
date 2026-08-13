"""Immutable typed request and result contracts for ontology queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias
from uuid import UUID

from loushang.ontology.projection import ProjectionState
from loushang.ontology.schema import SchemaIdentity


@dataclass(frozen=True, slots=True)
class StartFromIds:
    object_ids: tuple[UUID, ...]

    def __init__(self, object_ids: tuple[UUID, ...] | list[UUID]) -> None:
        object.__setattr__(self, "object_ids", tuple(object_ids))


@dataclass(frozen=True, slots=True)
class StartFromType:
    object_type: str


@dataclass(frozen=True, slots=True)
class StartAll:
    pass


@dataclass(frozen=True, slots=True)
class Traverse:
    link_type: str
    direction: str = "outgoing"

    def __post_init__(self) -> None:
        if self.direction not in {"outgoing", "incoming"}:
            raise ValueError("direction must be 'outgoing' or 'incoming'")


@dataclass(frozen=True, slots=True)
class PropertyFilter:
    property_name: str
    operator: str
    value: object


@dataclass(frozen=True, slots=True)
class ObjectTypeFilter:
    object_type: str


@dataclass(frozen=True, slots=True)
class SortBy:
    property_name: str
    ascending: bool = True


@dataclass(frozen=True, slots=True)
class Offset:
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("offset must not be negative")


@dataclass(frozen=True, slots=True)
class Limit:
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("limit must not be negative")


QueryStep: TypeAlias = (
    StartFromIds
    | StartFromType
    | StartAll
    | Traverse
    | PropertyFilter
    | ObjectTypeFilter
    | SortBy
    | Offset
    | Limit
)


@dataclass(frozen=True, slots=True)
class QueryRequest:
    steps: tuple[QueryStep, ...] = field(default_factory=tuple)
    schema_identity: SchemaIdentity | None = None

    def __init__(
        self,
        *,
        steps: tuple[QueryStep, ...] | list[QueryStep] = (),
        schema_identity: SchemaIdentity | None = None,
    ) -> None:
        if schema_identity is not None and not isinstance(
            schema_identity, SchemaIdentity
        ):
            raise TypeError("schema_identity must be a SchemaIdentity")
        object.__setattr__(self, "steps", tuple(steps))
        object.__setattr__(self, "schema_identity", schema_identity)


@dataclass(frozen=True, slots=True)
class QueryDiagnostic:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class QueryResult:
    object_ids: tuple[UUID, ...]
    schema_identity: SchemaIdentity
    projection: ProjectionState
    diagnostics: tuple[QueryDiagnostic, ...] = ()


__all__ = [
    "Limit",
    "ObjectTypeFilter",
    "Offset",
    "PropertyFilter",
    "QueryDiagnostic",
    "QueryRequest",
    "QueryResult",
    "QueryStep",
    "SortBy",
    "StartAll",
    "StartFromIds",
    "StartFromType",
    "Traverse",
]
