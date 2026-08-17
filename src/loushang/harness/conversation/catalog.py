from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from loushang.harness.conversation.index import (
    ConversationIndex,
    IndexedProjection,
)
from loushang.harness.conversation.ports import ConversationProjector
from loushang.harness.conversation.store import (
    ConversationLocator,
    ConversationProviderBinding,
)

H = TypeVar("H")
R = TypeVar("R")
P = TypeVar("P")
Q = TypeVar("Q")


@dataclass(frozen=True)
class ProjectionQuery(Generic[P]):
    """In-process collection helper, not a remote index query language."""

    predicate: Callable[[P], bool] | None = None
    sort_key: Callable[[P], Any] | None = None
    reverse: bool = False
    limit: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reverse, bool):
            raise TypeError("projection query reverse must be a boolean")
        if self.limit is not None:
            if isinstance(self.limit, bool) or not isinstance(self.limit, int):
                raise TypeError("projection query limit must be an integer or None")
            if self.limit < 0:
                raise ValueError("projection query limit must be non-negative")

    def apply(self, projections: Iterable[P]) -> tuple[P, ...]:
        selected = (
            list(projections)
            if self.predicate is None
            else [item for item in projections if self.predicate(item)]
        )
        if self.sort_key is not None:
            selected.sort(key=self.sort_key, reverse=self.reverse)
        if self.limit is not None:
            selected = selected[: self.limit]
        return tuple(selected)


@dataclass(frozen=True)
class ConversationCatalogDiagnostic:
    locator: ConversationLocator | None
    code: str
    message: str


@dataclass(frozen=True)
class ConversationCatalogResult(Generic[P]):
    items: tuple[IndexedProjection[P], ...]
    diagnostics: tuple[ConversationCatalogDiagnostic, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.diagnostics


class ConversationCatalog(Generic[H, R, P, Q]):
    """Federate authoritative Store providers into rebuildable projections."""

    def __init__(
        self,
        *,
        providers: Sequence[ConversationProviderBinding[H, R]],
        projector: ConversationProjector[H, R, P],
        record_id: Callable[[R], str],
        index: ConversationIndex[P, Q] | None = None,
        query_items: (
            Callable[
                [Q, Sequence[IndexedProjection[P]]],
                Sequence[IndexedProjection[P]],
            ]
            | None
        ) = None,
        page_size: int = 100,
        publish_partial: bool = False,
    ) -> None:
        provider_ids = [provider.provider_id for provider in providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("conversation provider ids must be unique")
        if page_size < 1:
            raise ValueError("conversation catalog page size must be positive")
        self._providers = tuple(providers)
        self._projector = projector
        self._record_id = record_id
        self._index = index
        self._query_items = query_items
        self._page_size = page_size
        self._publish_partial = publish_partial

    async def scan(self) -> ConversationCatalogResult[P]:
        items: list[IndexedProjection[P]] = []
        diagnostics: list[ConversationCatalogDiagnostic] = []
        for provider in self._providers:
            cursor: str | None = None
            while True:
                try:
                    page = await provider.store.scan_page(
                        provider.namespace,
                        cursor=cursor,
                        limit=self._page_size,
                    )
                except Exception as exc:
                    diagnostics.append(
                        ConversationCatalogDiagnostic(
                            locator=None,
                            code="provider_scan_failed",
                            message=f"{provider.provider_id}: {exc}",
                        )
                    )
                    break
                diagnostics.extend(
                    ConversationCatalogDiagnostic(
                        locator=None,
                        code=diagnostic.code,
                        message=diagnostic.message,
                    )
                    for diagnostic in page.diagnostics
                )
                for head in page.heads:
                    locator = ConversationLocator(provider.provider_id, head.key)
                    try:
                        load_result = await provider.store.load(head.key)
                        snapshot = load_result.snapshot
                        leaf_id = (
                            self._record_id(snapshot.records[-1])
                            if snapshot.records
                            else None
                        )
                        projection = self._projector.project(
                            header=snapshot.header,
                            records=snapshot.records,
                            leaf_id=leaf_id,
                            locator=locator,
                        )
                        items.append(
                            IndexedProjection(
                                locator=locator,
                                source_revision=snapshot.revision,
                                projection=projection,
                            )
                        )
                    except Exception as exc:
                        diagnostics.append(
                            ConversationCatalogDiagnostic(
                                locator=locator,
                                code="conversation_projection_failed",
                                message=str(exc),
                            )
                        )
                cursor = page.next_cursor
                if cursor is None:
                    break
        return ConversationCatalogResult(tuple(items), tuple(diagnostics))

    async def refresh(self) -> ConversationCatalogResult[P]:
        result = await self.scan()
        if self._index is not None and (result.complete or self._publish_partial):
            await self._index.replace(result.items)
        return result

    async def list(
        self,
        query: Q,
        *,
        refresh: bool = False,
    ) -> ConversationCatalogResult[P]:
        if refresh or self._index is None:
            result = await (self.refresh() if refresh else self.scan())
            return self._apply_query(result, query)
        return ConversationCatalogResult(tuple(await self._index.query(query)))

    def _apply_query(
        self,
        result: ConversationCatalogResult[P],
        query: Q,
    ) -> ConversationCatalogResult[P]:
        if self._query_items is None:
            return result
        return ConversationCatalogResult(
            tuple(self._query_items(query, result.items)),
            result.diagnostics,
        )


__all__ = [
    "ConversationCatalog",
    "ConversationCatalogDiagnostic",
    "ConversationCatalogResult",
    "ProjectionQuery",
]
