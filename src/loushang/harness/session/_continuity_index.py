"""Native indexed transcript operations for a bound Continuity provider."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar, Protocol

from loushang.harness.continuity.activation import CallbackPreparedActivationLease
from loushang.harness.continuity.types import (
    ContinuityArtifactReference,
    ContinuityDiagnostic,
    ContinuityPreview,
    ContinuityPreviewSection,
    ContinuitySummary,
    ContinuityTarget,
    ProviderPage,
    ProviderPageItem,
    ProviderQuery,
)
from loushang.harness.conversation import IndexedProjection
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.runtime import SessionOperationResult
from loushang.harness.transcript import (
    AgentTranscriptSessionCatalog,
    SessionAssetHealthSummary,
    SessionIndexPage,
    SessionQuery,
    SessionSummary,
    same_agent_transcript_session_path,
    session_summary_authority_is_current,
    session_summary_revision,
)


class _PreparedIndexedSession(Protocol):
    async def consume(self) -> object: ...

    async def abort(self) -> None: ...

    async def close(self) -> None: ...


class _IndexedSessionRuntime(Protocol):
    session_dir: Path

    def try_query_session_index_page(
        self,
        query: SessionQuery | None = None,
        *,
        cursor: str | None = None,
        limit: int = 25,
        ignore_authority: str | Path | None = None,
    ) -> SessionIndexPage: ...

    def request_session_index_refresh(self, *, all_sessions: bool = False) -> None: ...

    def request_session_index_repair(self) -> None: ...

    def request_bounded_session_index_refresh(self) -> None: ...

    def get_current_session(self) -> object | None: ...

    def get_current_session_ref(self) -> str | None: ...

    async def delete_session(self, session_id: str | Path) -> bool: ...

    async def prepare_restore_session_operation(
        self,
        session_id: str | Path,
        *,
        fallback_cwd: str | Path | None = None,
        missing_cwd: str = "error",
    ) -> _PreparedIndexedSession: ...


class _IndexedSessionContinuity:
    """Own the original indexed identity through preview, activation and deletion."""

    _provider_id: ClassVar[str]
    _domain_id: ClassVar[str]
    _conflicted_target_error: ClassVar[type[RuntimeError]]
    _product_label: ClassVar[str]
    _max_preview_cache: ClassVar[int]
    _requires_messages: ClassVar[bool]
    _stale_target_error: ClassVar[type[RuntimeError]]
    _index_status_diagnostics: ClassVar[Mapping[str, tuple[str, str]]]

    def __init__(
        self,
        runtime: _IndexedSessionRuntime,
        *,
        cwd: str | Path | None,
        all_sessions: bool,
    ) -> None:
        self._runtime = runtime
        self._cwd = canonical_session_directory(cwd)
        self._all_sessions = all_sessions
        self._index_refresh_requested = False
        self._preview_items: OrderedDict[str, IndexedProjection[SessionSummary]] = (
            OrderedDict()
        )

    def _summarize(self, indexed: IndexedProjection[SessionSummary]) -> ContinuitySummary:
        summary = indexed.projection
        return ContinuitySummary(
            target=ContinuityTarget(
                provider_id=self._provider_id,
                opaque_id=summary.session_id,
                revision=session_summary_revision(summary, indexed.source_revision),
            ),
            domain_ids=(self._domain_id,),
            primary_domain_id=self._domain_id,
            title=_summary_title(summary),
            updated_at=summary.updated_at,
            created_at=summary.created_at,
            subtitle=_session_subtitle(summary),
            excerpt=summary.last_message_preview or summary.first_message,
            status=_session_status(summary),
            actions=(
                ("activate", "delete")
                if summary.discovery is None or summary.discovery.mode == "canonical"
                else ("activate",)
            ),
        )

    def _discovery_diagnostics(self, page: SessionIndexPage) -> list[ContinuityDiagnostic]:
        return [
            ContinuityDiagnostic(
                code=f"{self._domain_id}_session_discovery_{issue.code}",
                message=f"Ignored Session source {issue.source_id}: {issue.detail}.",
                provider_id=self._provider_id,
            )
            for issue in page.discovery_issues
        ]

    def _require_summary_allowed(self, summary: SessionSummary, *, deleting: bool) -> None:
        discovery = summary.discovery
        if discovery is None:
            return
        if not discovery.resumable:
            raise self._conflicted_target_error(
                "This Session ID has different transcripts in multiple discovery "
                "sources. Select an exact path or resolve the conflict before resume."
            )
        if deleting and discovery.mode != "canonical":
            raise RuntimeError(
                "Compatibility Sessions are read-only; resume them before deletion."
            )

    async def _preview_history(
        self, summary: SessionSummary, path: Path, rows: list[tuple[str, str]],
    ) -> tuple[str | None, bool]:
        raise NotImplementedError

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        indexed = self._cached_target(target)
        summary = indexed.projection
        history_changed = False
        history_text: str | None = None
        rows = [
            ("Session ID", summary.session_id),
            ("Workspace", summary.cwd or "Unknown"),
            (
                "Messages",
                str(summary.message_count)
                if summary.counts_exact
                else f"at least {summary.message_count}",
            ),
            (
                "Entries",
                str(summary.entry_count)
                if summary.counts_exact
                else f"at least {summary.entry_count}",
            ),
        ]
        discovery = summary.discovery
        if discovery is not None:
            mode = "canonical" if discovery.mode == "canonical" else "compatibility"
            rows.extend(
                (
                    ("Storage", f"{discovery.origin.capitalize()} {mode}"),
                    ("Health", discovery.health.replace("_", " ").title()),
                )
            )
            if discovery.aliases:
                rows.append(("Compatible copies", str(len(discovery.aliases))))
            if discovery.conflicts:
                rows.append(("Conflicting copies", str(len(discovery.conflicts))))
        if summary.session_file is not None:
            history_text, history_changed = await self._preview_history(
                summary, summary.session_file, rows
            )
        inspect_assets = getattr(
            self._runtime,
            "inspect_discovered_session_assets",
            None,
        )
        if callable(inspect_assets) and summary.session_file is not None:
            try:
                asset_health = await settled_io(
                    inspect_assets,
                    summary.session_file,
                )
            except (OSError, ValueError):
                asset_health = SessionAssetHealthSummary(state="unavailable")
            if isinstance(asset_health, SessionAssetHealthSummary):
                rows.append(("Assets", _asset_health_label(asset_health)))
        if summary.model:
            provider = summary.model.get("provider")
            model_id = summary.model.get("model_id")
            if provider and model_id:
                rows.append(("Model", f"{provider}/{model_id}"))
        if summary.authority_fingerprint is not None:
            history_changed = (
                not session_summary_authority_is_current(summary) or history_changed
            )
        artifacts = (
            (
                ContinuityArtifactReference(
                    label="Transcript",
                    reference=str(summary.session_file),
                ),
            )
            if summary.session_file is not None
            else ()
        )
        revision = session_summary_revision(summary, indexed.source_revision)
        return ContinuityPreview(
            target=target,
            revision=revision,
            heading=_summary_title(summary),
            sections=(
                ContinuityPreviewSection(
                    kind="text",
                    text=(
                        "History changed; refresh"
                        if history_changed
                        else history_text
                        or summary.last_message_preview
                        or summary.first_message
                    ),
                ),
                ContinuityPreviewSection(
                    kind="key_value",
                    title=f"{self._product_label} session",
                    rows=tuple(rows),
                ),
                ContinuityPreviewSection(
                    kind="artifacts",
                    artifacts=artifacts,
                ),
            ),
            stale=revision != target.revision or history_changed,
        )


    async def query(
        self, request: ProviderQuery
    ) -> ProviderPage:
        current_reference = self._runtime.get_current_session_ref()
        page = await asyncio.to_thread(
            self._runtime.try_query_session_index_page,
            SessionQuery(
                cwd=None if self._all_sessions else self._query_cwd(),
                text=request.text or None,
                sort_by="created" if request.sort_id == "created" else "recent",
                has_messages=self._requires_messages,
                source_mode="canonical" if "delete" in request.required_actions else None,
                exclude_session_file=current_reference,
            ),
            cursor=request.cursor,
            limit=request.limit,
            ignore_authority=current_reference,
        )
        items: list[ProviderPageItem] = []
        for page_item in page.items:
            indexed = page_item.item
            session_id = indexed.projection.session_id
            self._preview_items[session_id] = indexed
            self._preview_items.move_to_end(session_id)
            while len(self._preview_items) > self._max_preview_cache:
                self._preview_items.popitem(last=False)
            items.append(
                ProviderPageItem(
                    summary=self._summarize(indexed),
                    after_cursor=page_item.after_cursor,
                )
            )
        diagnostics = self._discovery_diagnostics(page)
        if page.restart_required:
            status = "expired"
        elif page.index_state != "fresh":
            if not self._index_refresh_requested:
                if page.bounded_fallback:
                    self._runtime.request_bounded_session_index_refresh()
                else:
                    self._runtime.request_session_index_repair()
                self._index_refresh_requested = True
            status = "bounded" if page.bounded_fallback else "unavailable"
        else:
            self._index_refresh_requested = False
            status = None
        if status is not None:
            code, message = self._index_status_diagnostics[status]
            diagnostics.append(
                ContinuityDiagnostic(
                    code=code,
                    message=message,
                    provider_id=self._provider_id,
                )
            )
        return ProviderPage(
            items=tuple(items),
            has_more=page.has_more,
            index_state=(
                "rebuilding" if page.index_state == "unavailable" else page.index_state
            ),
            index_generation=page.index_generation,
            query_snapshot=page.query_snapshot,
            diagnostics=tuple(diagnostics),
        )

    async def resolve_history_source(
        self,
        target: ContinuityTarget,
    ) -> str | Path:
        """Resolve one current native transcript without preparing a Session."""

        indexed, reference = self._require_listed_source(target)
        await self._require_current_source(indexed)
        return reference

    async def prepare(
        self,
        target: ContinuityTarget,
    ) -> CallbackPreparedActivationLease:
        reference = await self.resolve_history_source(target)
        indexed = self._cached_target(target)
        summary = indexed.projection
        current = self._runtime.get_current_session()
        if current is not None and _same_session_reference(
            self._runtime.get_current_session_ref(),
            reference,
        ):
            return CallbackPreparedActivationLease(
                target=target,
                disposition="in_place",
                consume=lambda: SessionOperationResult(
                    previous=current,
                    current=current,
                    payload=None,
                    cancelled=False,
                ),
            )
        candidate = await self._runtime.prepare_restore_session_operation(reference)
        if (
            summary.authority_fingerprint is not None
            and not session_summary_authority_is_current(summary)
        ):
            await candidate.abort()
            raise self._stale_target_error(
                f"The selected {self._product_label} session changed while it was being prepared."
            )
        return CallbackPreparedActivationLease(
            target=target,
            disposition="in_place",
            consume=candidate.consume,
            abort=candidate.abort,
        )

    async def delete(
        self, target: ContinuityTarget
    ) -> bool:
        indexed, reference = self._require_listed_source(target, deleting=True)
        if _same_session_reference(
            self._runtime.get_current_session_ref(),
            reference,
        ):
            raise ValueError("Cannot delete the currently active session")
        await self._require_current_source(indexed)
        deleted = await self._runtime.delete_session(reference)
        if deleted:
            self._preview_items.pop(target.opaque_id, None)
        return deleted

    def _require_listed_source(
        self,
        target: ContinuityTarget,
        *,
        deleting: bool = False,
    ) -> tuple[IndexedProjection[SessionSummary], str | Path]:
        indexed = self._cached_target(target)
        summary = indexed.projection
        self._require_summary_allowed(summary, deleting=deleting)
        if target.revision != session_summary_revision(summary, indexed.source_revision):
            raise self._stale_target_error(f"The selected {self._product_label} session summary is stale.")
        # Index rows are advisory projections; use the original indexed identity.
        reference = (
            summary.session_id
            if summary.discovery is not None
            else summary.session_file or summary.session_id
        )
        return indexed, reference

    async def _require_current_source(
        self,
        indexed: IndexedProjection[SessionSummary],
    ) -> None:
        summary = indexed.projection
        if summary.authority_fingerprint is not None:
            if session_summary_authority_is_current(summary):
                return
        else:
            revision = await asyncio.to_thread(
                AgentTranscriptSessionCatalog(
                    self._runtime.session_dir
                ).load_authoritative_revision,
                indexed.locator,
            )
            if revision == indexed.source_revision:
                return
        raise self._stale_target_error(f"The selected {self._product_label} session changed after it was listed.")

    def _cached_target(
        self,
        target: ContinuityTarget,
    ) -> IndexedProjection[SessionSummary]:
        if target.provider_id != self._provider_id:
            raise ValueError("continuity target belongs to another Provider")
        try:
            item = self._preview_items[target.opaque_id]
        except KeyError as exc:
            raise self._stale_target_error(
                f"The selected {self._product_label} session is no longer in this query snapshot."
            ) from exc
        self._preview_items.move_to_end(target.opaque_id)
        return item

    def _query_cwd(self) -> str | None:
        if self._cwd is not None:
            return self._cwd
        try:
            value = getattr(self._runtime, "cwd", None)
        except Exception:
            return None
        if not isinstance(value, str) or not value:
            return None
        return canonical_session_directory(value)


def _same_session_reference(
    current: str | None,
    target: str | Path,
) -> bool:
    if current is None:
        return False
    target_text = str(target)
    if current == target_text:
        return True
    return same_agent_transcript_session_path(
        Path(current).expanduser(),
        Path(target_text).expanduser(),
    )


def canonical_session_directory(cwd: str | Path | None) -> str | None:
    return (
        str(Path(cwd).expanduser().resolve(strict=False)) if cwd is not None else None
    )


def _summary_title(summary: SessionSummary) -> str:
    for value in (summary.name, summary.first_message, summary.session_id[:8]):
        if isinstance(value, str) and (normalized := " ".join(value.split())):
            return normalized[:512]
    return summary.session_id[:8]


def _session_status(summary: SessionSummary) -> str | None:
    discovery = summary.discovery
    if discovery is None:
        return "Needs attention" if summary.has_diagnostics else None
    if discovery.health == "conflict":
        return "Conflict"
    if discovery.health == "needs_attention":
        return "Needs attention"
    if summary.has_diagnostics:
        return "Needs attention"
    if discovery.health == "legacy":
        return f"Legacy · {discovery.origin}"
    return None


def _session_subtitle(summary: SessionSummary) -> str | None:
    discovery = summary.discovery
    if discovery is None or discovery.mode == "canonical":
        return summary.cwd or None
    origin = discovery.origin.capitalize()
    return f"{summary.cwd or 'Unknown workspace'} · {origin} compatibility"


def _asset_health_label(health: SessionAssetHealthSummary) -> str:
    if health.state == "none":
        return "None"
    if health.state == "unavailable":
        return "Unavailable (preview budget or read boundary)"
    suffix = f" · {health.object_count} objects · {health.total_bytes} bytes"
    if health.state == "available":
        return f"Available{suffix}"
    if health.state == "partial":
        return f"Present (integrity checked on resume){suffix}"
    return (
        f"{health.state.title()}{suffix} · "
        f"{health.missing} missing · {health.corrupt} corrupt"
    )
