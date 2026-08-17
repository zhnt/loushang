"""Narrow read and atomic-replacement ports for materialized projections."""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from loushang.ontology.projection.model import (
    ProjectedObject,
    ProjectionSnapshot,
    ProjectionState,
)
from loushang.ontology.schema import CompiledOntologySchema


class ProjectionUnavailableError(RuntimeError):
    """Raised when a projection adapter has no installed snapshot."""


@runtime_checkable
class ProjectionReadStore(Protocol):
    """Read capability consumed by backend-neutral query evaluation."""

    @property
    def schema(self) -> CompiledOntologySchema: ...

    @property
    def projection_state(self) -> ProjectionState: ...

    def read_snapshot(self) -> ProjectionSnapshot: ...

    def get(self, object_id: UUID) -> ProjectedObject | None: ...

    def get_by_type(self, object_type: str) -> tuple[ProjectedObject, ...]: ...

    def find_neighbors(
        self,
        object_id: UUID,
        link_type: str,
        direction: str = "outgoing",
    ) -> tuple[ProjectedObject, ...]: ...

    def all_objects(self) -> tuple[ProjectedObject, ...]: ...


@runtime_checkable
class ProjectionStore(ProjectionReadStore, Protocol):
    """Projection persistence with one atomic snapshot replacement command."""

    def replace(self, snapshot: ProjectionSnapshot) -> ProjectionState: ...


__all__ = [
    "ProjectionReadStore",
    "ProjectionStore",
    "ProjectionUnavailableError",
]
