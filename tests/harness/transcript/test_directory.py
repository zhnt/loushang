from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.ai.types import UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationRecord,
    IndexedProjection,
)
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    AgentTranscriptDirectoryRuntime,
    SessionQuery,
    SessionSummary,
    write_agent_transcript_export,
)


def _header(conversation_id: str, *, cwd: str) -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-07-19T00:00:00Z",
        metadata={"cwd": cwd},
    )


def _record(
    record_id: str,
    text: str,
    *,
    timestamp: float,
) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-07-19T00:00:01Z",
        payload=UserMessage(role="user", content=text, timestamp=timestamp),
    )


def test_directory_runtime_exposes_current_and_all_root_catalog_queries(
    tmp_path: Path,
) -> None:
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    write_agent_transcript_export(
        project_a / "alpha.jsonl",
        _header("alpha", cwd="/workspace/a"),
        [_record("alpha-record", "first searchable message", timestamp=1.0)],
    )
    write_agent_transcript_export(
        project_b / "beta.jsonl",
        _header("beta", cwd="/workspace/b"),
        [_record("beta-record", "second searchable message", timestamp=2.0)],
    )

    runtime = AgentTranscriptDirectoryRuntime(session_dir=project_a)
    runtime.add_session_discovery_dir(project_b)

    assert [record.session_id for record in runtime.list_sessions()] == ["alpha"]
    assert [
        summary.session_id
        for summary in runtime.find_session_summaries(SessionQuery(text="first"))
    ] == ["alpha"]
    assert [
        summary.session_id
        for summary in runtime.find_all_session_summaries(SessionQuery(text="second"))
    ] == ["beta"]
    assert [summary.session_id for summary in runtime.refresh_session_index()] == [
        "alpha"
    ]
    assert [
        summary.session_id for summary in runtime.list_indexed_session_summaries()
    ] == ["beta", "alpha"]


def test_directory_runtime_merges_read_only_legacy_discovery_roots(
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "user-home" / "data" / "sessions"
    legacy_dir = tmp_path / "project" / ".loushang" / "sessions"
    global_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    write_agent_transcript_export(
        global_dir / "global.jsonl",
        _header("global", cwd="/workspace/project"),
        [_record("global-record", "new global session", timestamp=2.0)],
    )
    write_agent_transcript_export(
        legacy_dir / "legacy.jsonl",
        _header("legacy", cwd="/workspace/project"),
        [_record("legacy-record", "old local session", timestamp=1.0)],
    )
    write_agent_transcript_export(
        legacy_dir / "copied-global.jsonl",
        _header("global", cwd="/workspace/project"),
        [_record("copied-record", "copied global session", timestamp=3.0)],
    )
    runtime = AgentTranscriptDirectoryRuntime(session_dir=global_dir)
    runtime.add_session_discovery_dir(legacy_dir)
    runtime.refresh_session_index()

    summaries = runtime.find_discovered_session_summaries(
        SessionQuery(cwd="/workspace/project")
    )
    first_page = runtime.try_query_session_index_page(
        SessionQuery(cwd="/workspace/project"),
        limit=1,
    )
    second_page = runtime.try_query_session_index_page(
        cursor=first_page.items[0].after_cursor,
        limit=1,
    )

    assert [summary.session_id for summary in summaries] == ["global", "legacy"]
    assert summaries[0].session_file == global_dir / "global.jsonl"
    assert [item.item.projection.session_id for item in first_page.items] == ["legacy"]
    assert [item.item.projection.session_id for item in second_page.items] == ["global"]
    assert first_page.index_state == "unavailable"
    assert first_page.bounded_fallback is True
    assert first_page.has_more is True
    assert second_page.has_more is False
    assert runtime.session_dir == global_dir


def test_directory_runtime_indexed_views_share_cwd_and_global_federation(
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "user-home" / "data" / "sessions"
    legacy_dir = tmp_path / "project" / ".loushang" / "sessions"
    global_dir.mkdir(parents=True)
    legacy_dir.mkdir(parents=True)
    write_agent_transcript_export(
        global_dir / "current.jsonl",
        _header("current", cwd="/workspace/current"),
        [_record("current-record", "current global", timestamp=2.0)],
    )
    write_agent_transcript_export(
        global_dir / "other.jsonl",
        _header("other", cwd="/workspace/other"),
        [_record("other-record", "other global", timestamp=3.0)],
    )
    write_agent_transcript_export(
        legacy_dir / "legacy.jsonl",
        _header("legacy", cwd="/workspace/current"),
        [_record("legacy-record", "current legacy", timestamp=1.0)],
    )
    runtime = AgentTranscriptDirectoryRuntime(session_dir=global_dir)
    runtime.add_session_discovery_dir(legacy_dir)
    runtime.refresh_session_index()

    current = runtime.find_indexed_session_summaries(
        SessionQuery(cwd="/workspace/current")
    )
    user_global = runtime.list_all_indexed_session_summaries()

    assert {summary.session_id for summary in current} == {"current", "legacy"}
    assert {summary.session_id for summary in user_global} == {
        "current",
        "legacy",
        "other",
    }


def test_directory_runtime_coalesces_requested_index_refreshes(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    write_agent_transcript_export(
        project_dir / "alpha.jsonl",
        _header("alpha", cwd="/workspace/a"),
        [_record("alpha-record", "indexed message", timestamp=1.0)],
    )
    runtime = AgentTranscriptDirectoryRuntime(
        session_dir=project_dir,
        auto_refresh_session_index=True,
        session_index_flush_delay=60.0,
    )

    async def scenario() -> None:
        runtime.request_session_index_refresh()
        runtime.request_session_index_refresh(all_sessions=True)
        await runtime.drain_session_index_flush()

    asyncio.run(scenario())

    assert runtime.session_catalog.index_path.exists()
    assert [
        summary.session_id for summary in runtime.list_all_indexed_session_summaries()
    ] == ["alpha"]


def test_directory_runtime_contains_scheduled_refresh_failures(tmp_path: Path) -> None:
    failures: list[tuple[str, bool]] = []

    class _BrokenDirectoryRuntime(AgentTranscriptDirectoryRuntime):
        def refresh_session_index(self) -> list[SessionSummary]:
            raise RuntimeError("index unavailable")

    runtime = _BrokenDirectoryRuntime(
        session_dir=tmp_path,
        session_index_flush_delay=60.0,
        record_index_refresh_failure=lambda exc, all_sessions: failures.append(
            (str(exc), all_sessions)
        ),
    )

    async def scenario() -> None:
        runtime.request_session_index_refresh()
        await runtime.drain_session_index_flush()

    asyncio.run(scenario())

    assert failures == [("index unavailable", False)]


def test_non_rebuilding_index_page_detects_missing_authority_without_replay(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    for index in range(3):
        write_agent_transcript_export(
            project_dir / f"session-{index}.jsonl",
            _header(f"session-{index}", cwd="/workspace/a"),
            [_record(f"record-{index}", f"message {index}", timestamp=float(index))],
        )
    runtime = AgentTranscriptDirectoryRuntime(session_dir=project_dir)
    runtime.refresh_session_index()
    for transcript in project_dir.glob("*.jsonl"):
        transcript.unlink()

    first = runtime.try_query_session_index_page(limit=2)
    assert first.index_state == "stale"
    assert first.items == ()
    assert first.has_more is False
    assert first.bounded_fallback is True
    assert runtime.session_catalog.index_path.exists()
    assert not list(project_dir.glob("*.jsonl"))


def test_index_page_restarts_after_generation_rebuild(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    for index in range(2):
        write_agent_transcript_export(
            project_dir / f"session-{index}.jsonl",
            _header(f"session-{index}", cwd="/workspace/a"),
            [_record(f"record-{index}", f"message {index}", timestamp=float(index))],
        )
    runtime = AgentTranscriptDirectoryRuntime(session_dir=project_dir)
    runtime.refresh_session_index()
    first = runtime.try_query_session_index_page(limit=1)

    write_agent_transcript_export(
        project_dir / "new.jsonl",
        _header("new", cwd="/workspace/a"),
        [_record("new-record", "new message", timestamp=3.0)],
    )
    runtime.refresh_session_index()
    continuation = runtime.try_query_session_index_page(
        cursor=first.items[0].after_cursor,
        limit=5,
    )

    assert continuation.restart_required is True
    assert continuation.items == ()
    assert continuation.index_generation != first.index_generation


def test_index_page_pins_query_snapshot_across_ordinary_upsert(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    for index in range(2):
        write_agent_transcript_export(
            project_dir / f"session-{index}.jsonl",
            _header(f"session-{index}", cwd="/workspace/a"),
            [_record(f"record-{index}", f"message {index}", timestamp=float(index))],
        )
    runtime = AgentTranscriptDirectoryRuntime(session_dir=project_dir)
    runtime.refresh_session_index()
    first = runtime.try_query_session_index_page(limit=1)
    indexed = first.items[0].item

    async def upsert() -> None:
        index = runtime.session_catalog._projection_index()
        await index.upsert(
            IndexedProjection(
                locator=indexed.locator,
                source_revision=indexed.source_revision + 1,
                projection=indexed.projection,
            )
        )

    asyncio.run(upsert())
    continuation = runtime.try_query_session_index_page(
        cursor=first.items[0].after_cursor,
        limit=5,
    )

    assert continuation.restart_required is False
    assert continuation.query_snapshot == first.query_snapshot
    assert continuation.index_generation == first.index_generation
    assert [item.item.projection.session_id for item in continuation.items] == [
        "session-1"
    ]


def test_missing_index_page_returns_bounded_preview_without_rebuilding_authority(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    write_agent_transcript_export(
        project_dir / "alpha.jsonl",
        _header("alpha", cwd="/workspace/a"),
        [_record("record", "message", timestamp=1.0)],
    )
    runtime = AgentTranscriptDirectoryRuntime(
        session_dir=project_dir,
        session_index_flush_delay=60.0,
    )

    page = runtime.try_query_session_index_page(limit=10)

    assert len(page.items) == 1
    assert page.items[0].item.projection.session_id == "alpha"
    assert page.items[0].item.projection.bounded is True
    assert page.index_state == "unavailable"
    assert page.bounded_fallback is True
    assert not runtime.session_catalog.index_path.exists()


def test_directory_can_finish_bounded_index_rebuild_off_the_listing_path(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    for index in range(3):
        write_agent_transcript_export(
            project_dir / f"session-{index}.jsonl",
            _header(f"session-{index}", cwd="/workspace/a"),
            [_record(f"record-{index}", f"message {index}", timestamp=index + 1)],
        )
    runtime = AgentTranscriptDirectoryRuntime(
        session_dir=project_dir,
        session_index_flush_delay=60.0,
    )

    first = runtime.try_query_session_index_page(limit=10)
    assert first.bounded_fallback is True
    runtime.request_bounded_session_index_refresh()
    asyncio.run(runtime.drain_session_index_flush())

    rebuilt = runtime.try_query_session_index_page(limit=10)
    assert rebuilt.index_state == "fresh"
    assert rebuilt.bounded_fallback is False
    assert len(rebuilt.items) == 3
    assert all(item.item.projection.bounded for item in rebuilt.items)
