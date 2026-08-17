from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.coding.continuity import (
    StaleContinuityTargetError,
    bind_coding_continuity,
    shutdown_coding_continuity,
)
from loushang.harness.continuity import ContinuityQuery
from loushang.harness.conversation import ConversationHeader, ConversationRecord
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    AgentTranscriptDirectoryRuntime,
    write_agent_transcript_export,
)


def _header(conversation_id: str) -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-07-24T00:00:00Z",
        metadata={"cwd": "/workspace/project"},
    )


def _record(record_id: str, text: str, *, parent_id: str | None = None):
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-07-24T00:00:01Z",
        payload=UserMessage(role="user", content=text, timestamp=1.0),
    )


class _Runtime(AgentTranscriptDirectoryRuntime):
    def __init__(self, session_dir: Path) -> None:
        super().__init__(
            session_dir=session_dir,
            session_index_flush_delay=60.0,
        )
        self.prepared: list[str] = []
        self.restored: list[str] = []
        self.deleted: list[str] = []
        self.current_session: object | None = None
        self.current_session_ref: str | None = None

    def get_current_session(self) -> object | None:
        return self.current_session

    def get_current_session_ref(self) -> str | None:
        return self.current_session_ref

    async def prepare_restore_session_operation(
        self,
        session_id: str | Path,
        **_kwargs: object,
    ) -> object:
        reference = str(session_id)
        self.prepared.append(reference)
        runtime = self

        class _Candidate:
            async def consume(self) -> object:
                runtime.restored.append(reference)
                return {"current": reference}

            async def abort(self) -> None:
                return None

        return _Candidate()

    async def delete_session(self, session_id: str | Path) -> bool:
        reference = str(session_id)
        self.deleted.append(reference)
        Path(reference).unlink()
        return True


def test_coding_provider_projects_common_summary_preview_and_activation(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Explain the parser architecture")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)
    assert bind_coding_continuity(runtime) is composition

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert len(page.items) == 1
        summary = page.items[0]
        assert summary.title == "Explain the parser architecture"
        assert summary.domain_ids == ("coding",)
        assert summary.target.opaque_id == "session-1"
        assert not hasattr(summary, "branch")
        assert not hasattr(summary, "worktree")
        assert not hasattr(summary, "model")

        preview = await composition.hub.preview(summary.target)
        assert preview.heading == summary.title
        assert preview.sections[1].kind == "key_value"
        assert ("Messages", "1") in preview.sections[1].rows

        lease = await composition.hub.prepare(summary.target)
        assert runtime.prepared == [str(transcript)]
        assert runtime.restored == []
        await lease.consume()
        assert runtime.restored == [str(transcript)]
        await composition.dispose()
        assert bind_coding_continuity(runtime) is composition
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_prepare_treats_current_session_as_noop(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Current prompt")],
    )
    runtime.refresh_session_index()
    current = object()
    runtime.current_session = current
    runtime.current_session_ref = str(transcript)
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        lease = await composition.hub.prepare(page.items[0].target)
        result = await lease.consume()

        assert result.previous is current
        assert result.current is current
        assert result.changed is False
        assert runtime.prepared == []
        assert runtime.restored == []
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_deletes_only_a_fresh_noncurrent_target(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Delete this session")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        assert await composition.hub.delete(page.items[0].target) is True
        assert runtime.deleted == [str(transcript)]
        assert transcript.exists() is False
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_refuses_to_delete_current_session(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session-1"),
        [_record("record-1", "Keep this session")],
    )
    runtime.refresh_session_index()
    runtime.current_session_ref = str(transcript)
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        with pytest.raises(ValueError, match="currently active"):
            await composition.hub.delete(page.items[0].target)
        assert transcript.exists() is True
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_prepare_revalidates_selected_transcript_revision(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    header = _header("session-1")
    first = _record("record-1", "First message")
    write_agent_transcript_export(transcript, header, [first])
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))
        target = page.items[0].target
        write_agent_transcript_export(
            transcript,
            header,
            [
                first,
                _record("record-2", "Changed after listing", parent_id="record-1"),
            ],
        )

        with pytest.raises(StaleContinuityTargetError, match="changed"):
            await composition.hub.prepare(target)
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_rebuilds_stale_index_before_listing_changed_session(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    transcript = tmp_path / "session-1.jsonl"
    header = _header("session-1")
    first = _record("record-1", "First message")
    write_agent_transcript_export(transcript, header, [first])
    runtime.refresh_session_index()
    write_agent_transcript_export(
        transcript,
        header,
        [
            first,
            _record("record-2", "New hi", parent_id="record-1"),
        ],
    )
    index_modified = runtime.session_catalog.index_path.stat().st_mtime_ns
    if transcript.stat().st_mtime_ns <= index_modified:
        os.utime(
            transcript,
            ns=(transcript.stat().st_atime_ns, index_modified + 1),
        )
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        stale = await composition.hub.query(ContinuityQuery(page_size=10))
        assert stale.items == ()
        assert stale.aggregate_index_state == "stale"

        await runtime.drain_session_index_flush()
        refreshed = await composition.hub.query(ContinuityQuery(page_size=10))
        assert len(refreshed.items) == 1
        assert refreshed.items[0].target.revision == "2"
        lease = await composition.hub.prepare(refreshed.items[0].target)
        await lease.abort()
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_reports_missing_index_without_authority_scan(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    write_agent_transcript_export(
        tmp_path / "session-1.jsonl",
        _header("session-1"),
        [_record("record-1", "Not scanned by query")],
    )
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))

        assert page.items == ()
        assert page.aggregate_index_state == "rebuilding"
        assert page.provider_diagnostics[0].code == (
            "coding_continuity_index_not_ready"
        )
        assert not runtime.session_catalog.index_path.exists()
        await runtime.drain_session_index_flush()
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_coding_provider_hides_empty_sessions_from_resume(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path)
    write_agent_transcript_export(
        tmp_path / "empty.jsonl",
        _header("empty"),
        [],
    )
    write_agent_transcript_export(
        tmp_path / "active.jsonl",
        _header("active"),
        [_record("record-1", "Visible prompt")],
    )
    runtime.refresh_session_index()
    composition = bind_coding_continuity(runtime)

    async def scenario() -> None:
        page = await composition.hub.query(ContinuityQuery(page_size=10))

        assert [item.target.opaque_id for item in page.items] == ["active"]
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())
