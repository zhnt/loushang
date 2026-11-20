"""Read and verify history evidence for a listed Session."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.coding.session import continuity as _binding
from loushang.harness.conversation import IndexedProjection
from loushang.harness.journal._owned_io import settled_io
from loushang.harness.transcript import (
    AgentTranscriptSessionCatalog,
    SessionSummary,
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


def require_listed_reference(
    indexed: IndexedProjection[SessionSummary],
    *,
    target_revision: str | None,
    stale_message: str,
) -> str | Path:
    summary = indexed.projection
    if target_revision != session_summary_revision(summary, indexed.source_revision):
        raise _binding.StaleContinuityTargetError(stale_message)
    # Index rows are advisory projections; use the original indexed identity.
    return (
        summary.session_id
        if summary.discovery is not None
        else summary.session_file or summary.session_id
    )


async def require_current_source(
    runtime: _binding.CodingContinuityRuntimePort,
    indexed: IndexedProjection[SessionSummary],
    *,
    changed_message: str,
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
    raise _binding.StaleContinuityTargetError(changed_message)
