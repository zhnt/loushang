"""Reusable directory and index operations for current Agent transcripts.

Products choose a transcript root and when to request refreshes. This runtime
owns only Conversation JSONL transcript discovery, query projection, index refresh,
and coalesced refresh scheduling; it does not create sessions or choose a
Product's lifecycle, model, extension, or diagnostics policy.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import stat as stat_module
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Literal

from loushang.harness.conversation import ConversationIndexState, IndexedProjection
from loushang.harness.runtime import CoalescingScheduler
from loushang.harness.transcript.discovery import (
    SessionAssetHealthState,
    SessionAssetHealthSummary,
    SessionDiscoveryHealth,
    SessionDiscoveryIssue,
    SessionDiscoveryMetadata,
    SessionDiscoverySource,
    SessionLocator,
)
from loushang.harness.transcript.jsonl_file import load_agent_transcript_file
from loushang.harness.transcript.session_artifacts import (
    inspect_agent_transcript_session_blobs,
)
from loushang.harness.transcript.session_catalog import (
    AgentTranscriptSessionCatalog,
    SessionQuery,
    SessionRecord,
    SessionSummary,
    filter_agent_transcript_session_summaries,
    session_summary_revision,
)

IndexRefreshFailureRecorder = Callable[[Exception, bool], None]
IndexMaintenance = Literal["bounded_refresh", "repair", "refresh", "refresh_all"]

_MAX_INDEX_TRAVERSALS = 8
_INDEX_TRAVERSAL_TTL = 900.0
_MAX_DUPLICATE_COMPARISON_BYTES = 64 * 1024 * 1024
_MAX_DISCOVERY_SOURCES = 32


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
    discovery_issues: tuple[SessionDiscoveryIssue, ...] = ()


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
    discovery_issues: tuple[SessionDiscoveryIssue, ...] = ()


@dataclass(frozen=True)
class _SessionDiscoveryCandidate:
    source: SessionDiscoverySource
    summary: SessionSummary
    source_revision: int
    indexed: IndexedProjection[SessionSummary] | None = None


@dataclass
class _DuplicateComparisonBudget:
    remaining: int = _MAX_DUPLICATE_COMPARISON_BYTES


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
        authority_session_source: SessionDiscoverySource | None = None,
        discovery_session_sources: Sequence[SessionDiscoverySource] = (),
    ) -> None:
        self.session_dir = Path(session_dir)
        self._authority_session_source = authority_session_source or (
            SessionDiscoverySource(
                source_id="sessions.authority",
                root=self.session_dir,
                mode="canonical",
                origin="custom",
                priority=0,
            )
        )
        self._require_authority_source(self._authority_session_source)
        self._discovery_session_sources: list[SessionDiscoverySource] = []
        for source in discovery_session_sources:
            self.add_session_discovery_source(source)
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
        return [
            _decorate_session_summary(
                summary,
                self._authority_session_source,
                source_revision=summary.entry_count,
            )
            for summary in self.session_catalog.list_summaries()
        ]

    @property
    def authority_session_source(self) -> SessionDiscoverySource:
        return self._authority_session_source

    def set_session_authority_source(self, source: SessionDiscoverySource) -> None:
        """Attach the Product-neutral origin label for the writable root."""

        self._require_authority_source(source)
        if any(
            current.source_id == source.source_id
            for current in self._discovery_session_sources
        ):
            raise ValueError("session authority source_id is already bound")
        self._authority_session_source = source

    @property
    def discovery_session_dirs(self) -> tuple[Path, ...]:
        return tuple(source.root for source in self._discovery_session_sources)

    @property
    def discovery_session_sources(self) -> tuple[SessionDiscoverySource, ...]:
        return tuple(self._discovery_session_sources)

    @property
    def session_discovery_issues(self) -> tuple[SessionDiscoveryIssue, ...]:
        return tuple(
            issue
            for source in self._discovery_session_sources
            if (issue := _discovery_root_issue(source)) is not None
        )

    def add_session_discovery_dir(self, session_dir: str | Path) -> None:
        """Add a read-only compatibility root without changing write authority."""

        self.add_session_discovery_source(
            SessionDiscoverySource(
                source_id=(
                    "sessions.compatibility."
                    f"{len(self._discovery_session_sources) + 1}"
                ),
                root=Path(session_dir),
                mode="compatibility",
                origin="configured",
                priority=100 + len(self._discovery_session_sources),
            )
        )

    def add_session_discovery_source(self, source: SessionDiscoverySource) -> None:
        """Admit one typed read-only source for continuity discovery."""

        if not isinstance(source, SessionDiscoverySource):
            raise TypeError("session discovery source must be a SessionDiscoverySource")
        if source.mode != "compatibility":
            raise ValueError("additional session discovery sources must be compatible")
        authority = self._authority_session_source.root
        if source.source_id == self._authority_session_source.source_id:
            raise ValueError("session discovery source_id belongs to the authority")
        if source.root == authority:
            return
        for current in self._discovery_session_sources:
            if current.source_id == source.source_id and current.root != source.root:
                raise ValueError("session discovery source_id is already bound")
            if current.root == source.root:
                return
        if len(self._discovery_session_sources) >= _MAX_DISCOVERY_SOURCES:
            raise ValueError("session discovery source limit exceeded")
        self._discovery_session_sources.append(source)

    def _require_authority_source(self, source: SessionDiscoverySource) -> None:
        if not isinstance(source, SessionDiscoverySource):
            raise TypeError("session authority source must be a SessionDiscoverySource")
        if source.mode != "canonical":
            raise ValueError("session authority source must be canonical")
        authority = Path(os.path.abspath(self.session_dir.expanduser()))
        if source.root != authority:
            raise ValueError("session authority source root does not match session_dir")

    def _safe_discovery_session_sources(self) -> tuple[SessionDiscoverySource, ...]:
        return tuple(
            source
            for source in self._discovery_session_sources
            if _safe_discovery_root(source.root)
        )

    def is_authority_session_file(self, path: str | Path) -> bool:
        return _path_is_within(path, self.session_dir)

    def is_discovery_session_file(self, path: str | Path) -> bool:
        return any(
            _path_is_within(path, source.root)
            for source in self._safe_discovery_session_sources()
        )

    def list_discovered_session_summaries(self) -> list[SessionSummary]:
        candidates = [
            (self._authority_session_source, summary)
            for summary in self.session_catalog.list_summaries()
        ]
        for source in self._safe_discovery_session_sources():
            candidates.extend(
                (source, summary)
                for summary in AgentTranscriptSessionCatalog(
                    source.root,
                    index_writable=False,
                ).list_path_summaries()
            )
        return _merge_discovered_session_summaries(candidates)

    def find_discovered_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return _filter_discovered_session_summaries(
            self.list_discovered_session_summaries(),
            query or SessionQuery(),
        )

    def inspect_discovered_session_assets(
        self,
        session_ref: str | Path,
    ) -> SessionAssetHealthSummary:
        """Inspect durable objects for one explicitly selected transcript."""

        candidate = Path(session_ref).expanduser()
        if candidate.is_file():
            session_file = candidate.resolve()
        else:
            matches = [
                summary
                for summary in self.list_discovered_session_summaries()
                if summary.session_id == str(session_ref)
                and summary.session_file is not None
            ]
            if len(matches) != 1 or matches[0].session_file is None:
                raise ValueError("session asset inspection requires an exact Session")
            discovery = matches[0].discovery
            if discovery is not None and not discovery.resumable:
                raise ValueError("conflicting Session authority cannot be inspected")
            session_file = matches[0].session_file
        if not (
            self.is_authority_session_file(session_file)
            or self.is_discovery_session_file(session_file)
        ):
            raise ValueError("session asset inspection is outside discovery authority")
        header, records = load_agent_transcript_file(session_file)
        health = inspect_agent_transcript_session_blobs(
            session_dir=session_file.parent,
            session_id=header.conversation_id,
            records=records,
        )
        if not health:
            return SessionAssetHealthSummary(state="none")
        unique_objects = {
            item.reference.blob_id: item.reference.size_bytes for item in health
        }
        available = sum(item.state == "available" for item in health)
        missing = sum(item.state == "missing" for item in health)
        corrupt = sum(item.state == "corrupt" for item in health)
        state: SessionAssetHealthState = (
            "corrupt" if corrupt else "missing" if missing else "available"
        )
        return SessionAssetHealthSummary(
            state=state,
            reference_count=len(health),
            object_count=len(unique_objects),
            total_bytes=sum(unique_objects.values()),
            available=available,
            missing=missing,
            corrupt=corrupt,
        )

    def find_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return filter_agent_transcript_session_summaries(
            self.list_session_summaries(),
            query or SessionQuery(),
        )

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
        if self._safe_discovery_session_sources():
            if refresh:
                self.refresh_session_index()
            return self._collect_indexed_session_summaries(SessionQuery())
        return [
            _decorate_session_summary(
                summary,
                self._authority_session_source,
                source_revision=summary.entry_count,
            )
            for summary in self.session_catalog.list_indexed_summaries(
                refresh=refresh
            )
        ]

    def find_indexed_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        if self._safe_discovery_session_sources():
            return self._collect_indexed_session_summaries(query or SessionQuery())
        return [
            _decorate_session_summary(
                summary,
                self._authority_session_source,
                source_revision=summary.entry_count,
            )
            for summary in self.session_catalog.find_indexed_summaries(query)
        ]

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

        if self._safe_discovery_session_sources():
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
                items=tuple(
                    _decorate_indexed_session_summary(
                        item,
                        self._authority_session_source,
                    )
                    for item in bounded.items
                ),
                index_generation=f"bounded:{snapshot.index_generation}",
                query_snapshot=token,
                expires_at=monotonic() + _INDEX_TRAVERSAL_TTL,
                index_state=visible_state,
                bounded_fallback=True,
                ignored_authority=ignored_authority,
                discovery_issues=self.session_discovery_issues,
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
            items=tuple(
                _decorate_indexed_session_summary(
                    item,
                    self._authority_session_source,
                )
                for item in snapshot.items
            ),
            index_generation=snapshot.index_generation,
            query_snapshot=token,
            expires_at=monotonic() + _INDEX_TRAVERSAL_TTL,
            ignored_authority=ignored_authority,
            discovery_issues=self.session_discovery_issues,
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
            (self._authority_session_source, self.session_catalog),
            *(
                (
                    source,
                    AgentTranscriptSessionCatalog(
                        source.root,
                        index_writable=False,
                    ),
                )
                for source in self._safe_discovery_session_sources()
            ),
        )
        unfiltered = SessionQuery()
        current_snapshot = catalogs[0][1].try_query_index_snapshot(
            unfiltered,
            ignore_modified_paths=(ignored_authority,)
            if ignored_authority is not None
            else (),
        )
        current_bounded = current_snapshot.index_state != "fresh"
        current_items = (
            catalogs[0][1].bounded_index_snapshot(unfiltered).items
            if current_bounded
            else current_snapshot.items
        )
        items = [(catalogs[0][0], item) for item in current_items]
        index_states = [current_snapshot.index_state]
        any_bounded = current_bounded
        for source, catalog in catalogs[1:]:
            snapshot = catalog.try_query_index_snapshot(unfiltered)
            index_states.append(snapshot.index_state)
            bounded = snapshot.index_state != "fresh"
            any_bounded = any_bounded or bounded
            items.extend(
                (source, item)
                for item in (
                    snapshot.items
                    if not bounded
                    else catalog.bounded_index_snapshot(unfiltered).items
                )
            )
        merged_items = _merge_discovered_index_items(items)
        selected = _filter_discovered_session_summaries(
            [item.projection for item in merged_items], requested
        )
        by_projection = {id(item.projection): item for item in merged_items}
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
            discovery_issues=self.session_discovery_issues,
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
                discovery_issues=self.session_discovery_issues,
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
                discovery_issues=self.session_discovery_issues,
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
            discovery_issues=traversal.discovery_issues,
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


def _merge_discovered_session_summaries(
    values: Sequence[tuple[SessionDiscoverySource, SessionSummary]],
) -> list[SessionSummary]:
    candidates = [
        _SessionDiscoveryCandidate(
            source=source,
            summary=summary,
            source_revision=summary.entry_count,
        )
        for source, summary in values
    ]
    return sorted(
        (candidate.summary for candidate in _merge_discovered_candidates(candidates)),
        key=lambda summary: _session_summary_sort_key(summary, "recent"),
        reverse=True,
    )


def _merge_discovered_index_items(
    values: Sequence[
        tuple[SessionDiscoverySource, IndexedProjection[SessionSummary]]
    ],
) -> list[IndexedProjection[SessionSummary]]:
    candidates = [
        _SessionDiscoveryCandidate(
            source=source,
            summary=item.projection,
            source_revision=item.source_revision,
            indexed=item,
        )
        for source, item in values
    ]
    merged = _merge_discovered_candidates(candidates)
    return [
        replace(candidate.indexed, projection=candidate.summary)
        for candidate in merged
        if candidate.indexed is not None
    ]


def _merge_discovered_candidates(
    candidates: Sequence[_SessionDiscoveryCandidate],
) -> list[_SessionDiscoveryCandidate]:
    grouped: dict[str, list[_SessionDiscoveryCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.summary.session_id, []).append(candidate)
    comparison_budget = _DuplicateComparisonBudget()
    return [
        _merge_discovered_group(group, comparison_budget=comparison_budget)
        for group in grouped.values()
    ]


def _merge_discovered_group(
    values: Sequence[_SessionDiscoveryCandidate],
    *,
    comparison_budget: _DuplicateComparisonBudget,
) -> _SessionDiscoveryCandidate:
    selected = min(values, key=_session_discovery_candidate_key)
    if len(values) == 1:
        return replace(
            selected,
            summary=_decorate_session_summary(
                selected.summary,
                selected.source,
                source_revision=selected.source_revision,
            ),
        )
    aliases: list[SessionLocator] = []
    conflicts: list[SessionLocator] = []
    selected_path = selected.summary.session_file
    selected_digest = (
        _consume_bounded_file_digest(selected_path, comparison_budget)
        if selected_path is not None
        else None
    )
    for candidate in values:
        if candidate is selected:
            continue
        locator = _session_locator(candidate)
        candidate_path = candidate.summary.session_file
        candidate_digest = (
            _consume_bounded_file_digest(candidate_path, comparison_budget)
            if candidate_path is not None
            else None
        )
        if selected_digest is not None and candidate_digest == selected_digest:
            aliases.append(locator)
        else:
            conflicts.append(locator)
    health: SessionDiscoveryHealth = (
        "conflict"
        if conflicts and selected.source.mode == "compatibility"
        else "needs_attention"
        if conflicts or selected.summary.has_diagnostics
        else "legacy"
        if selected.source.mode == "compatibility"
        else "available"
    )
    discovery = SessionDiscoveryMetadata(
        locator=_session_locator(selected),
        mode=selected.source.mode,
        origin=selected.source.origin,
        health=health,
        aliases=tuple(aliases),
        conflicts=tuple(conflicts),
    )
    return replace(selected, summary=replace(selected.summary, discovery=discovery))


def _decorate_indexed_session_summary(
    item: IndexedProjection[SessionSummary],
    source: SessionDiscoverySource,
) -> IndexedProjection[SessionSummary]:
    return replace(
        item,
        projection=_decorate_session_summary(
            item.projection,
            source,
            source_revision=item.source_revision,
        ),
    )


def _decorate_session_summary(
    summary: SessionSummary,
    source: SessionDiscoverySource,
    *,
    source_revision: int,
) -> SessionSummary:
    health: SessionDiscoveryHealth = (
        "needs_attention"
        if summary.has_diagnostics
        else "legacy"
        if source.mode == "compatibility"
        else "available"
    )
    return replace(
        summary,
        discovery=SessionDiscoveryMetadata(
            locator=SessionLocator(
                source_id=source.source_id,
                conversation_id=summary.session_id,
                session_file=_required_session_file(summary),
                revision=session_summary_revision(summary, source_revision),
            ),
            mode=source.mode,
            origin=source.origin,
            health=health,
        ),
    )


def _session_locator(candidate: _SessionDiscoveryCandidate) -> SessionLocator:
    return SessionLocator(
        source_id=candidate.source.source_id,
        conversation_id=candidate.summary.session_id,
        session_file=_required_session_file(candidate.summary),
        revision=session_summary_revision(
            candidate.summary,
            candidate.source_revision,
        ),
    )


def _required_session_file(summary: SessionSummary) -> Path:
    if summary.session_file is None:
        raise ValueError("local Session discovery requires a transcript path")
    return summary.session_file


def _session_discovery_candidate_key(
    candidate: _SessionDiscoveryCandidate,
) -> tuple[int, int, str, str]:
    session_file = candidate.summary.session_file
    return (
        0 if candidate.source.mode == "canonical" else 1,
        candidate.source.priority,
        candidate.source.source_id,
        str(session_file) if session_file is not None else "",
    )


def _bounded_file_digest(
    path: Path,
    *,
    budget: _DuplicateComparisonBudget,
) -> tuple[int, bytes] | None:
    try:
        before = path.lstat()
    except OSError:
        return None
    if (
        not stat_module.S_ISREG(before.st_mode)
        or _status_is_link_or_reparse(before)
        or before.st_size > budget.remaining
    ):
        return None
    # Reserve the complete fixed snapshot before opening. A failed or racing
    # read still consumes its reservation, so one merge can never retry past
    # the process-wide comparison budget.
    budget.remaining -= before.st_size
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    digest = hashlib.sha256()
    try:
        try:
            handle = os.fdopen(descriptor, "rb", closefd=True)
        except Exception:
            os.close(descriptor)
            raise
        with handle:
            opened = os.fstat(handle.fileno())
            if not _same_file_status(before, opened):
                return None
            remaining = before.st_size
            while remaining:
                chunk = handle.read(min(remaining, 1024 * 1024))
                if not chunk:
                    return None
                digest.update(chunk)
                remaining -= len(chunk)
            after = os.fstat(handle.fileno())
    except OSError:
        return None
    try:
        current = path.lstat()
    except OSError:
        return None
    if not _same_file_status(before, after) or not _same_file_status(before, current):
        return None
    return before.st_size, digest.digest()


def _consume_bounded_file_digest(
    path: Path,
    budget: _DuplicateComparisonBudget,
) -> tuple[int, bytes] | None:
    if budget.remaining <= 0:
        return None
    return _bounded_file_digest(path, budget=budget)


def _same_file_status(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _safe_discovery_root(path: Path) -> bool:
    try:
        status = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return stat_module.S_ISDIR(status.st_mode) and not _status_is_link_or_reparse(
        status
    )


def _discovery_root_issue(
    source: SessionDiscoverySource,
) -> SessionDiscoveryIssue | None:
    try:
        status = source.root.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        return SessionDiscoveryIssue(
            source_id=source.source_id,
            code="unreadable_root",
            path=source.root,
            detail=str(error),
        )
    if not stat_module.S_ISDIR(status.st_mode) or _status_is_link_or_reparse(status):
        return SessionDiscoveryIssue(
            source_id=source.source_id,
            code="unsafe_root",
            path=source.root,
            detail="discovery root is not a direct directory",
        )
    return None


def _status_is_link_or_reparse(status: os.stat_result) -> bool:
    return stat_module.S_ISLNK(status.st_mode) or bool(
        getattr(status, "st_file_attributes", 0)
        & getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
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
