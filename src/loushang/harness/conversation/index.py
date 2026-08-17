from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from loushang.harness.conversation.store import ConversationLocator

ProjectionT = TypeVar("ProjectionT")
QueryT = TypeVar("QueryT")
QueryT_contra = TypeVar("QueryT_contra", contravariant=True)
ConversationIndexState = Literal["fresh", "stale", "unavailable", "unknown"]


@dataclass(frozen=True)
class IndexedProjection(Generic[ProjectionT]):
    """One rebuildable projection tied to its authoritative source revision."""

    locator: ConversationLocator
    source_revision: int
    projection: ProjectionT


@dataclass(frozen=True)
class ConversationIndexSnapshot(Generic[ProjectionT]):
    """One non-rebuilding, revision-bearing view of a projection index."""

    items: tuple[IndexedProjection[ProjectionT], ...]
    index_state: ConversationIndexState
    index_generation: str
    query_snapshot: str


class ConversationIndex(Protocol[ProjectionT, QueryT_contra]):
    async def upsert(self, item: IndexedProjection[ProjectionT]) -> bool: ...

    async def delete(
        self,
        locator: ConversationLocator,
        *,
        through_revision: int,
    ) -> bool: ...

    async def get(
        self,
        locator: ConversationLocator,
    ) -> IndexedProjection[ProjectionT] | None: ...

    async def query(
        self,
        query: QueryT_contra,
    ) -> Sequence[IndexedProjection[ProjectionT]]: ...

    async def query_snapshot(
        self,
        query: QueryT_contra,
    ) -> ConversationIndexSnapshot[ProjectionT]: ...

    async def replace(
        self,
        items: Sequence[IndexedProjection[ProjectionT]],
    ) -> tuple[IndexedProjection[ProjectionT], ...]: ...


class IndexQuery(Protocol[QueryT_contra, ProjectionT]):
    """Filter or order indexed projections for one query."""

    def __call__(
        self,
        query: QueryT_contra,
        items: Sequence[IndexedProjection[ProjectionT]],
    ) -> Sequence[IndexedProjection[ProjectionT]]: ...


class MemoryConversationIndex(Generic[ProjectionT, QueryT]):
    """Reference rebuildable index with revision and deletion ordering."""

    def __init__(
        self,
        *,
        query_items: IndexQuery[QueryT, ProjectionT],
    ) -> None:
        self._query_items = query_items
        self._items: dict[ConversationLocator, IndexedProjection[ProjectionT]] = {}
        self._tombstones: dict[ConversationLocator, int] = {}
        self._generation = "memory-1"
        self._sequence = 0

    async def upsert(self, item: IndexedProjection[ProjectionT]) -> bool:
        tombstone = self._tombstones.get(item.locator, -1)
        current = self._items.get(item.locator)
        if item.source_revision <= tombstone:
            return False
        if current is not None and item.source_revision < current.source_revision:
            return False
        self._items[item.locator] = item
        self._sequence += 1
        return True

    async def delete(
        self,
        locator: ConversationLocator,
        *,
        through_revision: int,
    ) -> bool:
        previous = self._tombstones.get(locator, -1)
        if through_revision < previous:
            return False
        self._tombstones[locator] = through_revision
        current = self._items.get(locator)
        if current is not None and current.source_revision <= through_revision:
            del self._items[locator]
        self._sequence += 1
        return through_revision > previous

    async def get(
        self,
        locator: ConversationLocator,
    ) -> IndexedProjection[ProjectionT] | None:
        return self._items.get(locator)

    async def query(
        self,
        query: QueryT,
    ) -> Sequence[IndexedProjection[ProjectionT]]:
        return tuple(self._query_items(query, tuple(self._items.values())))

    async def query_snapshot(
        self,
        query: QueryT,
    ) -> ConversationIndexSnapshot[ProjectionT]:
        return ConversationIndexSnapshot(
            items=tuple(self._query_items(query, tuple(self._items.values()))),
            index_state="fresh",
            index_generation=self._generation,
            query_snapshot=f"{self._generation}:{self._sequence}",
        )

    async def replace(
        self,
        items: Sequence[IndexedProjection[ProjectionT]],
    ) -> tuple[IndexedProjection[ProjectionT], ...]:
        replacement = {
            item.locator: item
            for item in items
            if item.source_revision > self._tombstones.get(item.locator, -1)
        }
        self._items = replacement
        generation = int(self._generation.removeprefix("memory-")) + 1
        self._generation = f"memory-{generation}"
        self._sequence = 0
        return tuple(replacement.values())


__all__ = [
    "ConversationIndex",
    "ConversationIndexSnapshot",
    "ConversationIndexState",
    "IndexQuery",
    "IndexedProjection",
    "MemoryConversationIndex",
]
