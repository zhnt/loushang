"""Reusable directory and index operations for current Agent transcripts.

Products choose a transcript root and when to request refreshes. This runtime
owns only Conversation JSONL transcript discovery, query projection, index refresh,
and coalesced refresh scheduling; it does not create sessions or choose a
Product's lifecycle, model, extension, or diagnostics policy.
"""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Literal

from loushang.harness.conversation import ConversationIndexState, IndexedProjection
from loushang.harness.runtime import CoalescingScheduler
from loushang.harness.transcript.session_catalog import (
    AgentTranscriptSessionCatalog,
    SessionQuery,
    SessionRecord,
    SessionSummary,
    filter_agent_transcript_session_summaries,
)

IndexRefreshFailureRecorder = Callable[[Exception, bool], None]
IndexMaintenance = Literal["bounded_refresh", "repair", "refresh", "refresh_all"]

_MAX_INDEX_TRAVERSALS = 8
_INDEX_TRAVERSAL_TTL = 900.0


@dataclass(frozen=True)
class SessionIndexPageItem:
    item: IndexedProjection[SessionSummary]
    after_cursor: str


@dataclass(frozen=True)
class SessionIndexPage:
    items: tuple[SessionIndexPageItem, ...]
    has_more: bool
    index_state: ConversationIndexState
    index_generation: str
    query_snapshot: str
    restart_required: bool = False
    bounded_fallback: bool = False


@dataclass(frozen=True)
class _SessionIndexTraversal:
    items: tuple[IndexedProjection[SessionSummary], ...]
    index_generation: str
    query_snapshot: str
    expires_at: float
    index_state: ConversationIndexState = "fresh"
    bounded_fallback: bool = False
    ignored_authority: Path | None = None
    aggregate_snapshot: bool = False


class AgentTranscriptDirectoryRuntime:
    """Expose catalog reads and bounded index refresh scheduling.

    The runtime is intentionally independent from active-session lifecycle.
    Products can reuse it beside their own session factory and decide whether
    index refreshes are automatic, explicit, or disabled.
    """

    def __init__(
        self,
        *,
        session_dir: str | Path,
        auto_refresh_session_index: bool = False,
        session_index_refresh_interval: float = 0.5,
        session_index_flush_delay: float = 0.25,
        record_index_refresh_failure: IndexRefreshFailureRecorder | None = None,
        discovery_session_dirs: Sequence[str | Path] = (),
    ) -> None:
        self.session_dir = Path(session_dir)
        self._discovery_session_dirs: list[Path] = []
        for directory in discovery_session_dirs:
            self.add_session_discovery_dir(directory)
        self.auto_refresh_session_index = auto_refresh_session_index
        self.session_index_refresh_interval = session_index_refresh_interval
        self.session_index_flush_delay = session_index_flush_delay
        self._record_index_refresh_failure = record_index_refresh_failure
        self._last_session_index_refresh = 0.0
        self._index_traversals: OrderedDict[str, _SessionIndexTraversal] = OrderedDict()
        self._index_traversal_lock = Lock()
        self._session_index_flush = CoalescingScheduler[IndexMaintenance](
            self._flush_scheduled_session_index,
            merge=_merge_index_maintenance,
            delay_seconds=session_index_flush_delay,
        )

    @property
    def session_catalog(self) -> AgentTranscriptSessionCatalog:
        """Return the current-root catalog without caching Product state."""

        return AgentTranscriptSessionCatalog(self.session_dir)

    def list_sessions(self) -> list[SessionRecord]:
        return self.session_catalog.list_records()

    def list_session_summaries(self) -> list[SessionSummary]:
        return self.session_catalog.list_summaries()

    @property
    def discovery_session_dirs(self) -> tuple[Path, ...]:
        return tuple(self._discovery_session_dirs)

    def add_session_discovery_dir(self, session_dir: str | Path) -> None:
        """Add a read-only compatibility root without changing write authority."""

        candidate = Path(session_dir).expanduser().resolve(strict=False)
        authority = self.session_dir.expanduser().resolve(strict=False)
        if candidate == authority or candidate in self._discovery_session_dirs:
            return
        self._discovery_session_dirs.append(candidate)

    def is_authority_session_file(self, path: str | Path) -> bool:
        return _path_is_within(path, self.session_dir)

    def is_discovery_session_file(self, path: str | Path) -> bool:
        return any(
            _path_is_within(path, directory)
            for directory in self._discovery_session_dirs
        )

    def list_discovered_session_summaries(self) -> list[SessionSummary]:
        summaries = self.list_session_summaries()
        for directory in self._discovery_session_dirs:
            summaries.extend(AgentTranscriptSessionCatalog(directory).list_summaries())
        return _deduplicate_session_summaries(summaries)

    def find_discovered_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return _filter_discovered_session_summaries(
            self.list_discovered_session_summaries(),
            query or SessionQuery(),
        )

    def find_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return self.session_catalog.find_summaries(query)

    def list_all_session_summaries(self) -> list[SessionSummary]:
        return self.list_discovered_session_summaries()

    def find_all_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return self.find_discovered_session_summaries(query)

    def refresh_session_index(self) -> list[SessionSummary]:
        summaries = self.session_catalog.refresh_index()
        self._last_session_index_refresh = monotonic()
        return summaries

    def repair_session_index(self) -> list[SessionSummary]:
        summaries = self.session_catalog.repair_index()
        self._last_session_index_refresh = monotonic()
        return summaries

    def refresh_bounded_session_index(self) -> list[SessionSummary]:
        summaries = self.session_catalog.refresh_bounded_index()
        self._last_session_index_refresh = monotonic()
        return summaries

    def refresh_all_session_indexes(self) -> list[SessionSummary]:
        # Compatibility roots are read-only. The global authority is the only
        # directory whose projection index this runtime may mutate.
        return self.refresh_session_index()

    def list_indexed_session_summaries(
        self,
        *,
        refresh: bool = False,
    ) -> list[SessionSummary]:
        if self.auto_refresh_session_index and not refresh:
            self.request_session_index_refresh_if_due()
        if any(path.is_dir() for path in self._discovery_session_dirs):
            if refresh:
                self.refresh_session_index()
            return self._collect_indexed_session_summaries(SessionQuery())
        return self.session_catalog.list_indexed_summaries(refresh=refresh)

    def find_indexed_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        if any(path.is_dir() for path in self._discovery_session_dirs):
            return self._collect_indexed_session_summaries(query or SessionQuery())
        return self.session_catalog.find_indexed_summaries(query)

    def _collect_indexed_session_summaries(
        self,
        query: SessionQuery,
    ) -> list[SessionSummary]:
        """Collect one pinned authority-plus-discovery index traversal."""

        requested_limit = query.limit
        if requested_limit == 0:
            return []
        page_limit = min(100, requested_limit or 100)
        page = self.try_query_session_index_page(query, limit=page_limit)
        summaries: list[SessionSummary] = []
        while True:
            summaries.extend(item.item.projection for item in page.items)
            if requested_limit is not None and len(summaries) >= requested_limit:
                return summaries[:requested_limit]
            if not page.has_more or not page.items or page.restart_required:
                return summaries
            page = self.try_query_session_index_page(
                cursor=page.items[-1].after_cursor,
                limit=page_limit,
            )

    def try_query_session_index_page(
        self,
        query: SessionQuery | None = None,
        *,
        cursor: str | None = None,
        limit: int = 25,
        ignore_authority: str | Path | None = None,
    ) -> SessionIndexPage:
        """Return a bounded, non-rebuilding page from an immutable traversal.

        The first call reads only the projection index and pins that result in
        a small process-local cache. Continuation calls use the pinned
        traversal, so ordinary index upserts cannot move or skip rows.
        """

        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("session index page limit must be between 1 and 100")
        if cursor is not None:
            return self._continue_session_index_page(cursor=cursor, limit=limit)

        if any(path.is_dir() for path in self._discovery_session_dirs):
            return self._start_discovered_session_index_page(
                query=query,
                limit=limit,
                ignore_authority=ignore_authority,
            )

        requested = replace(query or SessionQuery(), limit=None)
        ignored_authority = (
            Path(ignore_authority).expanduser().resolve(strict=False)
            if ignore_authority is not None
            else None
        )
        snapshot = self.session_catalog.try_query_index_snapshot(
            requested,
            ignore_modified_paths=(ignored_authority,)
            if ignored_authority is not None
            else (),
        )
        if snapshot.index_state != "fresh":
            visible_state: ConversationIndexState = (
                "stale" if snapshot.index_state == "stale" else "unavailable"
            )
            bounded = self.session_catalog.bounded_index_snapshot(requested)
            token = secrets.token_urlsafe(18)
            traversal = _SessionIndexTraversal(
                items=bounded.items,
                index_generation=f"bounded:{snapshot.index_generation}",
                query_snapshot=token,
                expires_at=monotonic() + _INDEX_TRAVERSAL_TTL,
                index_state=visible_state,
                bounded_fallback=True,
                ignored_authority=ignored_authority,
            )
            with self._index_traversal_lock:
                self._evict_index_traversals()
                self._index_traversals[token] = traversal
                while len(self._index_traversals) > _MAX_INDEX_TRAVERSALS:
                    self._index_traversals.popitem(last=False)
            return self._session_index_page(
                traversal,
                token=token,
                start=0,
                limit=limit,
            )

        token = secrets.token_urlsafe(18)
        traversal = _SessionIndexTraversal(
            items=snapshot.items,
            index_generation=snapshot.index_generation,
            query_snapshot=token,
            expires_at=monotonic() + _INDEX_TRAVERSAL_TTL,
            ignored_authority=ignored_authority,
        )
        with self._index_traversal_lock:
            self._evict_index_traversals()
            self._index_traversals[token] = traversal
            while len(self._index_traversals) > _MAX_INDEX_TRAVERSALS:
                self._index_traversals.popitem(last=False)
        return self._session_index_page(traversal, token=token, start=0, limit=limit)

    def _start_discovered_session_index_page(
        self,
        *,
        query: SessionQuery | None,
        limit: int,
        ignore_authority: str | Path | None,
    ) -> SessionIndexPage:
        """Pin one merged snapshot across global authority and legacy cwd roots."""

        requested = replace(query or SessionQuery(), limit=None)
        ignored_authority = (
            Path(ignore_authority).expanduser().resolve(strict=False)
            if ignore_authority is not None
            else None
        )
        catalogs = (
            self.session_catalog,
            *(
                AgentTranscriptSessionCatalog(path)
                for path in self._discovery_session_dirs
                if path.is_dir()
            ),
        )
        current_snapshot = catalogs[0].try_query_index_snapshot(
            requested,
            ignore_modified_paths=(ignored_authority,)
            if ignored_authority is not None
            else (),
        )
        current_bounded = current_snapshot.index_state != "fresh"
        current_items = (
            catalogs[0].bounded_index_snapshot(requested).items
            if current_bounded
            else current_snapshot.items
        )
        items = list(current_items)
        index_states = [current_snapshot.index_state]
        any_bounded = current_bounded
        for catalog in catalogs[1:]:
            snapshot = catalog.try_query_index_snapshot(requested)
            index_states.append(snapshot.index_state)
            bounded = snapshot.index_state != "fresh"
            any_bounded = any_bounded or bounded
            items.extend(
                snapshot.items
                if not bounded
                else catalog.bounded_index_snapshot(requested).items
            )

        unique_items: dict[str, IndexedProjection[SessionSummary]] = {}
        for item in items:
            session_file = item.projection.session_file
            key = item.projection.session_id or (
                str(session_file.expanduser().resolve(strict=False))
                if session_file is not None
                else f"{item.locator.provider_id}:{item.locator.key}"
            )
            unique_items.setdefault(key, item)
        selected = _filter_discovered_session_summaries(
            [item.projection for item in unique_items.values()], requested
        )
        by_projection = {id(item.projection): item for item in unique_items.values()}
        token = secrets.token_urlsafe(18)
        visible_state: ConversationIndexState = (
            "unavailable"
            if "unavailable" in index_states
            else "stale"
            if "stale" in index_states
            else "fresh"
        )
        traversal = _SessionIndexTraversal(
            items=tuple(by_projection[id(summary)] for summary in selected),
            index_generation=f"aggregate:{current_snapshot.index_generation}",
            query_snapshot=token,
            expires_at=monotonic() + _INDEX_TRAVERSAL_TTL,
            index_state=visible_state,
            bounded_fallback=any_bounded,
            ignored_authority=ignored_authority,
            aggregate_snapshot=True,
        )
        with self._index_traversal_lock:
            self._evict_index_traversals()
            self._index_traversals[token] = traversal
            while len(self._index_traversals) > _MAX_INDEX_TRAVERSALS:
                self._index_traversals.popitem(last=False)
        return self._session_index_page(
            traversal,
            token=token,
            start=0,
            limit=limit,
        )

    def list_all_indexed_session_summaries(
        self,
        *,
        refresh: bool = False,
    ) -> list[SessionSummary]:
        if self.auto_refresh_session_index and not refresh:
            self.request_session_index_refresh_if_due(all_sessions=True)
        if refresh:
            self.refresh_session_index()
        return self._collect_indexed_session_summaries(SessionQuery())

    def find_all_indexed_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return self._collect_indexed_session_summaries(query or SessionQuery())

    def request_session_index_refresh(self, *, all_sessions: bool = False) -> None:
        """Schedule one best-effort index refresh after Product state changes."""

        self._session_index_flush.delay_seconds = self.session_index_flush_delay
        self._session_index_flush.schedule("refresh_all" if all_sessions else "refresh")

    def request_session_index_repair(self) -> None:
        """Schedule an incremental local repair, with full rebuild as fallback."""

        self._session_index_flush.delay_seconds = self.session_index_flush_delay
        self._session_index_flush.schedule("repair")

    def request_bounded_session_index_refresh(self) -> None:
        """Schedule a complete head/tail index rebuild off the listing path."""

        self._session_index_flush.delay_seconds = self.session_index_flush_delay
        self._session_index_flush.schedule("bounded_refresh")

    def request_session_index_refresh_if_due(
        self,
        *,
        all_sessions: bool = False,
    ) -> None:
        if monotonic() - self._last_session_index_refresh >= (
            self.session_index_refresh_interval
        ):
            self.request_session_index_refresh(all_sessions=all_sessions)

    async def drain_session_index_flush(self) -> None:
        """Finish a pending refresh for deterministic Product disposal/tests."""

        await self._session_index_flush.drain()

    async def _flush_scheduled_session_index(
        self,
        maintenance: IndexMaintenance,
    ) -> None:
        try:
            if maintenance == "refresh_all":
                await asyncio.to_thread(self.refresh_all_session_indexes)
            elif maintenance == "refresh":
                await asyncio.to_thread(self.refresh_session_index)
            elif maintenance == "bounded_refresh":
                await asyncio.to_thread(self.refresh_bounded_session_index)
            else:
                await asyncio.to_thread(self.repair_session_index)
        except Exception as exc:
            if self._record_index_refresh_failure is not None:
                self._record_index_refresh_failure(
                    exc,
                    maintenance == "refresh_all",
                )

    def _continue_session_index_page(
        self,
        *,
        cursor: str,
        limit: int,
    ) -> SessionIndexPage:
        token, start = _decode_index_cursor(cursor)
        with self._index_traversal_lock:
            self._evict_index_traversals()
            traversal = self._index_traversals.get(token)
            if traversal is not None:
                self._index_traversals.move_to_end(token)
        if traversal is None:
            return SessionIndexPage(
                items=(),
                has_more=False,
                index_state="stale",
                index_generation="expired",
                query_snapshot=token,
                restart_required=True,
            )
        if traversal.bounded_fallback or traversal.aggregate_snapshot:
            return self._session_index_page(
                traversal,
                token=token,
                start=start,
                limit=limit,
            )
        current = self.session_catalog.try_query_index_snapshot(
            SessionQuery(limit=1),
            ignore_modified_paths=(traversal.ignored_authority,)
            if traversal.ignored_authority is not None
            else (),
        )
        if (
            current.index_state != "fresh"
            or current.index_generation != traversal.index_generation
        ):
            with self._index_traversal_lock:
                self._index_traversals.pop(token, None)
            return SessionIndexPage(
                items=(),
                has_more=False,
                index_state=current.index_state,
                index_generation=current.index_generation,
                query_snapshot=current.query_snapshot,
                restart_required=True,
            )
        return self._session_index_page(
            traversal,
            token=token,
            start=start,
            limit=limit,
        )

    @staticmethod
    def _session_index_page(
        traversal: _SessionIndexTraversal,
        *,
        token: str,
        start: int,
        limit: int,
    ) -> SessionIndexPage:
        if start < 0 or start > len(traversal.items):
            raise ValueError("session index cursor offset is invalid")
        end = min(start + limit, len(traversal.items))
        return SessionIndexPage(
            items=tuple(
                SessionIndexPageItem(
                    item=item,
                    after_cursor=_encode_index_cursor(token, index + 1),
                )
                for index, item in enumerate(
                    traversal.items[start:end],
                    start=start,
                )
            ),
            has_more=end < len(traversal.items),
            index_state=traversal.index_state,
            index_generation=traversal.index_generation,
            query_snapshot=traversal.query_snapshot,
            bounded_fallback=traversal.bounded_fallback,
        )

    def _evict_index_traversals(self) -> None:
        now = monotonic()
        expired = tuple(
            token
            for token, traversal in self._index_traversals.items()
            if traversal.expires_at <= now
        )
        for token in expired:
            self._index_traversals.pop(token, None)


def _merge_index_maintenance(
    left: IndexMaintenance,
    right: IndexMaintenance,
) -> IndexMaintenance:
    priority = {
        "bounded_refresh": 0,
        "repair": 1,
        "refresh": 2,
        "refresh_all": 3,
    }
    return left if priority[left] >= priority[right] else right


def _deduplicate_session_summaries(
    summaries: Sequence[SessionSummary],
) -> list[SessionSummary]:
    selected: dict[str, SessionSummary] = {}
    for summary in summaries:
        session_file = summary.session_file
        key = summary.session_id or (
            str(session_file.expanduser().resolve(strict=False))
            if session_file is not None
            else ""
        )
        selected.setdefault(key, summary)
    return sorted(
        selected.values(),
        key=lambda summary: _session_summary_sort_key(summary, "recent"),
        reverse=True,
    )


def _filter_discovered_session_summaries(
    summaries: Sequence[SessionSummary],
    query: SessionQuery,
) -> list[SessionSummary]:
    ordered = sorted(
        summaries,
        key=lambda summary: _session_summary_sort_key(summary, query.sort_by),
        reverse=True,
    )
    return filter_agent_transcript_session_summaries(ordered, query)


def _session_summary_sort_key(
    summary: SessionSummary,
    sort_by: str,
) -> tuple[str, str, str]:
    timestamp = summary.created_at if sort_by == "created" else summary.updated_at
    session_file = summary.session_file
    return (
        timestamp,
        summary.session_id,
        str(session_file.expanduser().resolve(strict=False))
        if session_file is not None
        else "",
    )


def _path_is_within(path: str | Path, directory: str | Path) -> bool:
    candidate = Path(path).expanduser().resolve(strict=False)
    root = Path(directory).expanduser().resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _encode_index_cursor(token: str, offset: int) -> str:
    payload = json.dumps(
        {"token": token, "offset": offset},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_index_cursor(cursor: str) -> tuple[str, int]:
    if not cursor or len(cursor) > 1024:
        raise ValueError("session index cursor is invalid")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        token = payload["token"]
        offset = payload["offset"]
    except Exception as exc:
        raise ValueError("session index cursor is invalid") from exc
    if not isinstance(token, str) or not token:
        raise ValueError("session index cursor token is invalid")
    if type(offset) is not int or offset < 0:
        raise ValueError("session index cursor offset is invalid")
    return token, offset


__all__ = [
    "AgentTranscriptDirectoryRuntime",
    "IndexRefreshFailureRecorder",
    "SessionIndexPage",
    "SessionIndexPageItem",
]
