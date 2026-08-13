"""Typed chain builder over a read-only ontology projection."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loushang.ontology.projection import (
    ProjectedObject,
    ProjectionReadStore,
)
from loushang.ontology.query.contracts import (
    Limit,
    ObjectTypeFilter,
    Offset,
    PropertyFilter,
    QueryRequest,
    QueryResult,
    QueryStep,
    SortBy,
    StartAll,
    StartFromIds,
    StartFromType,
    Traverse,
)
from loushang.ontology.query.engine import execute_query
from loushang.ontology.schema import SchemaIdentity


class QueryBuilder:
    """Build one immutable request and evaluate it against a projection view."""

    def __init__(self, store: ProjectionReadStore) -> None:
        self._store = store
        self._steps: list[QueryStep] = []

    def start_from(self, obj: ProjectedObject | UUID) -> QueryBuilder:
        obj_id = obj.id if isinstance(obj, ProjectedObject) else obj
        self._steps.append(StartFromIds((obj_id,)))
        return self

    def start_from_type(self, object_type: str) -> QueryBuilder:
        self._steps.append(StartFromType(object_type))
        return self

    def start_all(self) -> QueryBuilder:
        self._steps.append(StartAll())
        return self

    def follow(self, link_type: str, direction: str = "outgoing") -> QueryBuilder:
        self._steps.append(Traverse(link_type, direction))
        return self

    def where(self, property_name: str, op: str, value: Any) -> QueryBuilder:
        self._steps.append(PropertyFilter(property_name, op, value))
        return self

    def where_type(self, object_type: str) -> QueryBuilder:
        self._steps.append(ObjectTypeFilter(object_type))
        return self

    def limit(self, n: int) -> QueryBuilder:
        self._steps.append(Limit(n))
        return self

    def offset(self, n: int) -> QueryBuilder:
        self._steps.append(Offset(n))
        return self

    def sort_by(self, property_name: str, ascending: bool = True) -> QueryBuilder:
        self._steps.append(SortBy(property_name, ascending))
        return self

    def to_request(self) -> QueryRequest:
        schema_identity = SchemaIdentity.from_schema(self._store.schema)
        return QueryRequest(steps=self._steps, schema_identity=schema_identity)

    def execute_result(self) -> QueryResult:
        snapshot = self._store.read_snapshot()
        return execute_query(snapshot, self._request_for(snapshot))

    def execute(self) -> list[ProjectedObject]:
        snapshot = self._store.read_snapshot()
        result = execute_query(snapshot, self._request_for(snapshot))
        return [
            obj
            for object_id in result.object_ids
            if (obj := snapshot.get(object_id)) is not None
        ]

    def execute_ids(self) -> list[UUID]:
        return list(self.execute_result().object_ids)

    def execute_first(self) -> ProjectedObject | None:
        results = self.execute()
        return results[0] if results else None

    def execute_count(self) -> int:
        return len(self.execute_result().object_ids)

    def execute_exists(self) -> bool:
        return bool(self.execute_result().object_ids)

    def _request_for(self, store: ProjectionReadStore) -> QueryRequest:
        return QueryRequest(
            steps=self._steps,
            schema_identity=store.projection_state.schema_identity,
        )


__all__ = ["QueryBuilder"]
