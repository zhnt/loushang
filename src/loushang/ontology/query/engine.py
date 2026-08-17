"""Reference evaluator for typed ontology query requests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from loushang.ontology.projection import ProjectedObject, ProjectionReadStore
from loushang.ontology.query.contracts import (
    Limit,
    ObjectTypeFilter,
    Offset,
    PropertyFilter,
    QueryDiagnostic,
    QueryRequest,
    QueryResult,
    SortBy,
    StartAll,
    StartFromIds,
    StartFromType,
    Traverse,
)


def execute_query(store: ProjectionReadStore, request: QueryRequest) -> QueryResult:
    """Evaluate a request against one captured immutable projection."""

    snapshot = store.read_snapshot()
    current_identity = snapshot.state.schema_identity
    if (
        request.schema_identity is not None
        and request.schema_identity != current_identity
    ):
        return QueryResult(
            object_ids=(),
            schema_identity=current_identity,
            projection=snapshot.projection_state,
            diagnostics=(
                QueryDiagnostic(
                    code="schema_identity_mismatch",
                    message=(
                        f"Query requires schema {request.schema_identity}; "
                        f"store provides {current_identity}"
                    ),
                ),
            ),
        )

    result: list[ProjectedObject] = []
    for step in request.steps:
        if isinstance(step, StartFromIds):
            result = [
                obj for object_id in step.object_ids if (obj := snapshot.get(object_id))
            ]
        elif isinstance(step, StartFromType):
            result = list(snapshot.get_by_type(step.object_type))
        elif isinstance(step, StartAll):
            result = list(snapshot.all_objects())
        elif isinstance(step, Traverse):
            result = _traverse(snapshot, result, step)
        elif isinstance(step, PropertyFilter):
            result = _filter_by_property(
                result,
                step.property_name,
                step.operator,
                step.value,
            )
        elif isinstance(step, ObjectTypeFilter):
            result = [obj for obj in result if obj.object_type == step.object_type]
        elif isinstance(step, Limit):
            result = result[: step.count]
        elif isinstance(step, Offset):
            result = result[step.count :]
        elif isinstance(step, SortBy):
            result.sort(
                key=lambda obj: _sort_key(obj.get(step.property_name)),
                reverse=not step.ascending,
            )

    return QueryResult(
        object_ids=tuple(obj.id for obj in result),
        schema_identity=current_identity,
        projection=snapshot.projection_state,
    )


def _traverse(
    store: ProjectionReadStore,
    objects: list[ProjectedObject],
    step: Traverse,
) -> list[ProjectedObject]:
    result: list[ProjectedObject] = []
    seen: set[UUID] = set()
    for obj in objects:
        for neighbor in store.find_neighbors(
            obj.id,
            step.link_type,
            direction=step.direction,
        ):
            if neighbor.id not in seen:
                seen.add(neighbor.id)
                result.append(neighbor)
    return result


def _filter_by_property(
    objects: list[ProjectedObject],
    prop: str,
    op: str,
    value: object,
) -> list[ProjectedObject]:
    operators: dict[str, Callable[[Any, Any], bool]] = {
        "==": lambda left, right: left == right,
        "!=": lambda left, right: left != right,
        "<": lambda left, right: (
            left is not None and right is not None and left < right
        ),
        "<=": lambda left, right: (
            left is not None and right is not None and left <= right
        ),
        ">": lambda left, right: (
            left is not None and right is not None and left > right
        ),
        ">=": lambda left, right: (
            left is not None and right is not None and left >= right
        ),
        "in": lambda left, right: left in right if right is not None else False,
        "contains": lambda left, right: right in left if left is not None else False,
    }
    predicate = operators.get(op)
    if predicate is None:
        raise ValueError(f"Unsupported operator: {op}")
    return [obj for obj in objects if predicate(obj.get(prop), value)]


def _sort_key(value: object) -> tuple[bool, str, object]:
    return (value is None, type(value).__name__, value if value is not None else "")


__all__ = ["execute_query"]
