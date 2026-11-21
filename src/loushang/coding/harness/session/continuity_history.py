"""Use an owned session index to list and revalidate Continuity targets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.coding.session import continuity as _binding
from loushang.harness.continuity import (
    CallbackPreparedActivationLease,
    ContinuityDiagnostic,
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
    SessionQuery,
    SessionSummary,
    same_agent_transcript_session_path,
    session_summary_authority_is_current,
    session_summary_revision,
)
from loushang.harness.transcript.jsonl_file import AgentTranscriptFileError

if TYPE_CHECKING:
    from loushang.coding.resume.history import (
        CodingResumeHeaderPreview,
        CodingResumeHistoryPreview,
        CodingResumeRecentPage,
    )


@dataclass(frozen=True, slots=True)
class HistoryPreview:
    header: CodingResumeHeaderPreview | None = None
    snapshot: CodingResumeHistoryPreview | None = None
    recent: CodingResumeRecentPage | None = None
    changed: bool = False


async def read_history_preview(
    runtime: object,
    path: Path,
    *,
    session_id: str,
    authority_fingerprint: str | None,
    max_bytes: int,
) -> HistoryPreview:
    # Keep each native read owned through completion even if the preview is cancelled.
    try:
        header = await settled_io(_binding.read_coding_resume_header, path)
    except (OSError, ValueError):
        return HistoryPreview()
    if header.header.conversation_id != session_id:
        return HistoryPreview(changed=True)

    def matches(evidence: CodingResumeHistoryPreview | CodingResumeRecentPage) -> bool:
        return evidence.header_preview.header == header.header and (
            authority_fingerprint is None
            or evidence.source_fingerprint == authority_fingerprint
        )

    try:
        from loushang.coding.runtime.agent_session_runtime import AgentSessionRuntime

        if isinstance(runtime, AgentSessionRuntime):
            snapshot = await AgentSessionRuntime.preview_resume_history(
                runtime, path, max_bytes=max_bytes
            )
        else:
            snapshot = await settled_io(
                _binding.read_coding_resume_snapshot, path, max_bytes=max_bytes
            )
    except AgentTranscriptFileError as error:
        if error.code != "session_file_too_large":
            return HistoryPreview(header=header)
        try:
            if isinstance(runtime, AgentSessionRuntime):
                recent = await AgentSessionRuntime.preview_resume_recent_page(
                    runtime, path
                )
            else:
                recent = await settled_io(_binding.read_coding_resume_recent_page, path)
        except (OSError, ValueError):
            return HistoryPreview(header=header)
        if not recent.records:
            return HistoryPreview(header=header)
        if not matches(recent):
            return HistoryPreview(header=header, changed=True)
        return HistoryPreview(header=header, recent=recent)
    except (OSError, ValueError):
        return HistoryPreview(header=header)
    if not matches(snapshot):
        return HistoryPreview(header=header, changed=True)
    return HistoryPreview(header=header, snapshot=snapshot)


def _require_listed_source(
    self: _binding.CodingContinuityProvider,
    target: ContinuityTarget,
    *,
    deleting: bool = False,
) -> tuple[IndexedProjection[SessionSummary], str | Path]:
    indexed = cached_target(self, target)
    summary = indexed.projection
    _binding._require_unconflicted_summary(summary, deleting=deleting)
    if target.revision != session_summary_revision(summary, indexed.source_revision):
        raise _binding.StaleContinuityTargetError(_binding._STALE_SUMMARY_MESSAGE)
    # Index rows are advisory projections; use the original indexed identity.
    reference = (
        summary.session_id
        if summary.discovery is not None
        else summary.session_file or summary.session_id
    )
    return indexed, reference


async def require_current_source(
    runtime: _binding.CodingContinuityRuntimePort,
    indexed: IndexedProjection[SessionSummary],
) -> None:
    summary = indexed.projection
    if summary.authority_fingerprint is not None:
        if session_summary_authority_is_current(summary):
            return
    else:
        revision = await asyncio.to_thread(
            AgentTranscriptSessionCatalog(
                runtime.session_dir
            ).load_authoritative_revision,
            indexed.locator,
        )
        if revision == indexed.source_revision:
            return
    raise _binding.StaleContinuityTargetError(_binding._CHANGED_SINCE_LISTING_MESSAGE)


async def query_index(
    self: _binding.CodingContinuityProvider, request: ProviderQuery
) -> ProviderPage:
    current_reference = self._runtime.get_current_session_ref()
    page = await asyncio.to_thread(
        self._runtime.try_query_session_index_page,
        SessionQuery(
            cwd=None if self._all_sessions else _query_cwd(self),
            text=request.text or None,
            sort_by="created" if request.sort_id == "created" else "recent",
            has_messages=_binding._INDEX_REQUIRES_MESSAGES,
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
        while len(self._preview_items) > _binding._MAX_PREVIEW_CACHE:
            self._preview_items.popitem(last=False)
        items.append(
            ProviderPageItem(
                summary=_binding._continuity_summary(indexed),
                after_cursor=page_item.after_cursor,
            )
        )
    diagnostics = _binding._session_index_discovery_diagnostics(page)
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
        code, message = _binding._INDEX_STATUS_DIAGNOSTICS[status]
        diagnostics.append(
            ContinuityDiagnostic(
                code=code,
                message=message,
                provider_id=_binding.CODING_CONTINUITY_PROVIDER_ID,
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


def _query_cwd(self: _binding.CodingContinuityProvider) -> str | None:
    if self._cwd is not None:
        return self._cwd
    try:
        value = getattr(self._runtime, "cwd", None)
    except Exception:
        return None
    if not isinstance(value, str) or not value:
        return None
    return canonical_directory(value)


async def resolve_listed_history(
    self: _binding.CodingContinuityProvider,
    target: ContinuityTarget,
) -> str | Path:
    """Resolve one current native transcript without preparing a Session."""

    indexed, reference = _require_listed_source(self, target)
    await require_current_source(self._runtime, indexed)
    return reference


async def prepare_listed_session(
    self: _binding.CodingContinuityProvider,
    target: ContinuityTarget,
) -> CallbackPreparedActivationLease:
    reference = await self.resolve_history_source(target)
    indexed = cached_target(self, target)
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
        raise _binding.StaleContinuityTargetError(
            _binding._CHANGED_DURING_PREPARATION_MESSAGE
        )
    return CallbackPreparedActivationLease(
        target=target,
        disposition="in_place",
        consume=candidate.consume,
        abort=candidate.abort,
    )


async def delete_listed_session(
    self: _binding.CodingContinuityProvider, target: ContinuityTarget
) -> bool:
    indexed, reference = _require_listed_source(self, target, deleting=True)
    if _same_session_reference(
        self._runtime.get_current_session_ref(),
        reference,
    ):
        raise ValueError("Cannot delete the currently active session")
    await require_current_source(self._runtime, indexed)
    deleted = await self._runtime.delete_session(reference)
    if deleted:
        self._preview_items.pop(target.opaque_id, None)
    return deleted


def cached_target(
    self: _binding.CodingContinuityProvider,
    target: ContinuityTarget,
) -> IndexedProjection[SessionSummary]:
    if target.provider_id != _binding.CODING_CONTINUITY_PROVIDER_ID:
        raise ValueError("continuity target belongs to another Provider")
    try:
        item = self._preview_items[target.opaque_id]
    except KeyError as exc:
        raise _binding.StaleContinuityTargetError(
            _binding._UNLISTED_SUMMARY_MESSAGE
        ) from exc
    self._preview_items.move_to_end(target.opaque_id)
    return item


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


def canonical_directory(cwd: str | Path | None) -> str | None:
    return (
        str(Path(cwd).expanduser().resolve(strict=False)) if cwd is not None else None
    )
