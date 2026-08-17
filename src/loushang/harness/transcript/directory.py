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
from collections.abc import Callable
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
    find_all_agent_transcript_session_summaries,
    find_all_indexed_agent_transcript_session_summaries,
    list_all_agent_transcript_session_summaries,
    list_all_indexed_agent_transcript_session_summaries,
    refresh_all_agent_transcript_session_indexes,
)

IndexRefreshFailureRecorder = Callable[[Exception, bool], None]
IndexMaintenance = Literal["repair", "refresh", "refresh_all"]

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


@dataclass(frozen=True)
class _SessionIndexTraversal:
    items: tuple[IndexedProjection[SessionSummary], ...]
    index_generation: str
    query_snapshot: str
    expires_at: float


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
    ) -> None:
        self.session_dir = Path(session_dir)
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

    def find_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return self.session_catalog.find_summaries(query)

    def list_all_session_summaries(self) -> list[SessionSummary]:
        return list_all_agent_transcript_session_summaries(self.session_dir.parent)

    def find_all_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return find_all_agent_transcript_session_summaries(
            self.session_dir.parent,
            query,
        )

    def refresh_session_index(self) -> list[SessionSummary]:
        summaries = self.session_catalog.refresh_index()
        self._last_session_index_refresh = monotonic()
        return summaries

    def repair_session_index(self) -> list[SessionSummary]:
        summaries = self.session_catalog.repair_index()
        self._last_session_index_refresh = monotonic()
        return summaries

    def refresh_all_session_indexes(self) -> list[SessionSummary]:
        summaries = refresh_all_agent_transcript_session_indexes(
            self.session_dir.parent
        )
        self._last_session_index_refresh = monotonic()
        return summaries

    def list_indexed_session_summaries(
        self,
        *,
        refresh: bool = False,
    ) -> list[SessionSummary]:
        if self.auto_refresh_session_index and not refresh:
            self.request_session_index_refresh_if_due()
        return self.session_catalog.list_indexed_summaries(refresh=refresh)

    def find_indexed_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return self.session_catalog.find_indexed_summaries(query)

    def try_query_session_index_page(
        self,
        query: SessionQuery | None = None,
        *,
        cursor: str | None = None,
        limit: int = 25,
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

        requested = replace(query or SessionQuery(), limit=None)
        snapshot = self.session_catalog.try_query_index_snapshot(requested)
        if snapshot.index_state != "fresh":
            self._request_session_index_refresh_from_running_loop()
            visible_state: ConversationIndexState = (
                "stale" if snapshot.index_state == "stale" else "unavailable"
            )
            return SessionIndexPage(
                items=(),
                has_more=False,
                index_state=visible_state,
                index_generation=snapshot.index_generation,
                query_snapshot=snapshot.query_snapshot,
            )

        token = secrets.token_urlsafe(18)
        traversal = _SessionIndexTraversal(
            items=snapshot.items,
            index_generation=snapshot.index_generation,
            query_snapshot=token,
            expires_at=monotonic() + _INDEX_TRAVERSAL_TTL,
        )
        with self._index_traversal_lock:
            self._evict_index_traversals()
            self._index_traversals[token] = traversal
            while len(self._index_traversals) > _MAX_INDEX_TRAVERSALS:
                self._index_traversals.popitem(last=False)
        return self._session_index_page(traversal, token=token, start=0, limit=limit)

    def list_all_indexed_session_summaries(
        self,
        *,
        refresh: bool = False,
    ) -> list[SessionSummary]:
        if self.auto_refresh_session_index and not refresh:
            self.request_session_index_refresh_if_due(all_sessions=True)
        return list_all_indexed_agent_transcript_session_summaries(
            self.session_dir.parent,
            refresh=refresh,
        )

    def find_all_indexed_session_summaries(
        self,
        query: SessionQuery | None = None,
    ) -> list[SessionSummary]:
        return find_all_indexed_agent_transcript_session_summaries(
            self.session_dir.parent,
            query,
        )

    def request_session_index_refresh(self, *, all_sessions: bool = False) -> None:
        """Schedule one best-effort index refresh after Product state changes."""

        self._session_index_flush.delay_seconds = self.session_index_flush_delay
        self._session_index_flush.schedule(
            "refresh_all" if all_sessions else "refresh"
        )

    def request_session_index_repair(self) -> None:
        """Schedule an incremental local repair, with full rebuild as fallback."""

        self._session_index_flush.delay_seconds = self.session_index_flush_delay
        self._session_index_flush.schedule("repair")

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
        current = self.session_catalog.try_query_index_snapshot(SessionQuery(limit=1))
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
            index_state="fresh",
            index_generation=traversal.index_generation,
            query_snapshot=traversal.query_snapshot,
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

    def _request_session_index_refresh_from_running_loop(self) -> None:
        """Queue repair only when a Host loop can keep it off the read path."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self.request_session_index_repair()


def _merge_index_maintenance(
    left: IndexMaintenance,
    right: IndexMaintenance,
) -> IndexMaintenance:
    priority = {"repair": 0, "refresh": 1, "refresh_all": 2}
    return left if priority[left] >= priority[right] else right


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
