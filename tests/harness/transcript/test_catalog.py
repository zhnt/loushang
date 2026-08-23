from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    ConversationProviderBinding,
    ConversationRecord,
    MemoryConversationStore,
)
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    AgentTranscriptSessionCatalog,
    RecordAnnotationPatch,
    SessionQuery,
    build_agent_transcript_label_indexes,
    build_agent_transcript_session_context,
    find_all_agent_transcript_session_summaries,
    project_session_record,
    write_agent_transcript_export,
)


def _header(conversation_id: str, *, cwd: str) -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-07-18T00:00:00Z",
        metadata={"cwd": cwd},
    )


def _record(
    record_id: str,
    text: str,
    *,
    parent_id: str | None = None,
    timestamp: float = 1.0,
) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-07-18T00:00:01Z",
        payload=UserMessage(role="user", content=text, timestamp=timestamp),
    )


def test_catalog_discovers_queries_and_indexes_conversation_jsonl_transcripts(
    tmp_path: Path,
) -> None:
    write_agent_transcript_export(
        tmp_path / "alpha.jsonl",
        _header("alpha", cwd="/workspace/a"),
        [_record("alpha-record", "first searchable message")],
    )
    write_agent_transcript_export(
        tmp_path / "beta.jsonl",
        _header("beta", cwd="/workspace/b"),
        [_record("beta-record", "another message", timestamp=2.0)],
    )

    catalog = AgentTranscriptSessionCatalog(tmp_path)

    assert [record.session_id for record in catalog.list_records()] == ["beta", "alpha"]
    assert [
        summary.session_id
        for summary in catalog.find_summaries(SessionQuery(text="searchable"))
    ] == ["alpha"]
    assert [summary.session_id for summary in catalog.refresh_index()] == [
        "beta",
        "alpha",
    ]
    assert [summary.session_id for summary in catalog.list_indexed_summaries()] == [
        "beta",
        "alpha",
    ]
    assert [
        summary.session_id
        for summary in find_all_agent_transcript_session_summaries(
            tmp_path, SessionQuery(cwd="/workspace/b")
        )
    ] == ["beta"]


def test_catalog_skips_other_jsonl_families_and_publishes_valid_entries(
    tmp_path: Path,
) -> None:
    write_agent_transcript_export(
        tmp_path / "current.jsonl",
        _header("current", cwd="/workspace/current"),
        [_record("record-1", "current message")],
    )
    (tmp_path / "legacy.jsonl").write_text(
        json.dumps({"type": "session", "version": 3, "id": "legacy"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.jsonl").write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "type": "conversation",
                        "conversationId": "broken",
                        "version": 1,
                        "createdAt": "2026-07-18T00:00:00Z",
                    }
                ),
                "{not valid json}",
                "",
            )
        ),
        encoding="utf-8",
    )

    catalog = AgentTranscriptSessionCatalog(tmp_path)

    assert [item.session_id for item in catalog.refresh_index()] == ["current"]
    assert [item.session_id for item in catalog.load_index()] == ["current"]


def test_catalog_marks_index_stale_when_transcript_authority_is_newer(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "current.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("current", cwd="/workspace/current"),
        [_record("record-1", "first")],
    )
    catalog = AgentTranscriptSessionCatalog(tmp_path)
    catalog.refresh_index()
    assert catalog.try_query_index_snapshot().index_state == "fresh"

    write_agent_transcript_export(
        transcript,
        _header("current", cwd="/workspace/current"),
        [
            _record("record-1", "first"),
            _record("record-2", "second", parent_id="record-1"),
        ],
    )
    index_modified = catalog.index_path.stat().st_mtime_ns
    transcript_modified = transcript.stat().st_mtime_ns
    if transcript_modified <= index_modified:
        os.utime(
            transcript,
            ns=(transcript.stat().st_atime_ns, index_modified + 1),
        )

    snapshot = catalog.try_query_index_snapshot()

    assert snapshot.index_state == "stale"
    assert snapshot.items[0].source_revision == 1


def test_catalog_repairs_only_changed_new_and_deleted_transcripts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    alpha = tmp_path / "alpha.jsonl"
    beta = tmp_path / "beta.jsonl"
    gamma = tmp_path / "gamma.jsonl"
    write_agent_transcript_export(
        alpha,
        _header("alpha", cwd="/workspace"),
        [_record("alpha-1", "alpha")],
    )
    write_agent_transcript_export(
        beta,
        _header("beta", cwd="/workspace"),
        [_record("beta-1", "beta")],
    )
    catalog = AgentTranscriptSessionCatalog(tmp_path)
    catalog.refresh_index()
    index_modified = catalog.index_path.stat().st_mtime_ns

    write_agent_transcript_export(
        beta,
        _header("beta", cwd="/workspace"),
        [
            _record("beta-1", "beta"),
            _record("beta-2", "changed", parent_id="beta-1"),
        ],
    )
    write_agent_transcript_export(
        gamma,
        _header("gamma", cwd="/workspace"),
        [_record("gamma-1", "new")],
    )
    for path in (beta, gamma):
        if path.stat().st_mtime_ns <= index_modified:
            os.utime(
                path,
                ns=(path.stat().st_atime_ns, index_modified + 1),
            )
    alpha.unlink()

    projected: list[str] = []
    original = catalog._project_index_summary

    def project(header, records, leaf_id, locator):
        projected.append(header.conversation_id)
        return original(header, records, leaf_id, locator)

    monkeypatch.setattr(catalog, "_project_index_summary", project)

    repaired = catalog.repair_index()

    assert projected == ["beta", "gamma"]
    assert {summary.session_id for summary in repaired} == {"beta", "gamma"}
    assert (
        next(
            summary for summary in repaired if summary.session_id == "beta"
        ).entry_count
        == 2
    )
    assert catalog.try_query_index_snapshot().index_state == "fresh"


def test_catalog_query_can_exclude_sessions_without_messages(tmp_path: Path) -> None:
    write_agent_transcript_export(
        tmp_path / "empty.jsonl",
        _header("empty", cwd="/workspace"),
        [],
    )
    write_agent_transcript_export(
        tmp_path / "active.jsonl",
        _header("active", cwd="/workspace"),
        [_record("record-1", "hello")],
    )
    catalog = AgentTranscriptSessionCatalog(tmp_path)

    assert [
        summary.session_id
        for summary in catalog.find_summaries(SessionQuery(has_messages=True))
    ] == ["active"]
    assert [
        summary.session_id
        for summary in catalog.find_summaries(SessionQuery(has_messages=False))
    ] == ["empty"]


def test_catalog_context_and_labels_use_selected_standard_record_path() -> None:
    root = _record("root", "root")
    selected = _record("selected", "selected branch", parent_id="root")
    other = _record("other", "other branch", parent_id="root")
    label = ConversationRecord(
        record_id="label",
        parent_id="selected",
        kind=RECORD_ANNOTATION_PATCH_KIND,
        payload_version=1,
        created_at="2026-07-18T00:00:02Z",
        payload=RecordAnnotationPatch(
            target_record_id="selected",
            namespace="display.label",
            operation="set",
            value="important",
        ),
    )

    context = build_agent_transcript_session_context(
        [root, selected, other, label], leaf_id="selected"
    )
    labels, timestamps = build_agent_transcript_label_indexes(
        [root, selected, other, label]
    )

    assert [message.content for message in context.messages] == [
        "root",
        "selected branch",
    ]
    assert labels == {"selected": "important"}
    assert timestamps == {"selected": "2026-07-18T00:00:02Z"}


def test_bounded_catalog_stats_all_and_reads_only_recent_head_tail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import loushang.harness.transcript.session_catalog as catalog_module

    base_mtime = 1_800_000_000_000_000_000
    for index in range(55):
        path = tmp_path / f"session-{index:02d}.jsonl"
        records = [_record(f"first-{index}", f"first prompt {index}")]
        if index == 54:
            records.extend(
                (
                    _record(
                        "large-middle",
                        "x" * 140_000,
                        parent_id=f"first-{index}",
                    ),
                    _record(
                        "last-54",
                        "last bounded preview",
                        parent_id="large-middle",
                    ),
                )
            )
        write_agent_transcript_export(
            path,
            _header(f"session-{index}", cwd="/workspace"),
            records,
        )
        os.utime(path, ns=(base_mtime + index, base_mtime + index))

    reads: list[Path] = []
    original = catalog_module._read_bounded_segments

    def count_reads(candidate, *, segment_bytes):
        reads.append(candidate.path)
        return original(candidate, segment_bytes=segment_bytes)

    monkeypatch.setattr(catalog_module, "_read_bounded_segments", count_reads)
    catalog = AgentTranscriptSessionCatalog(tmp_path)

    snapshot = catalog.bounded_index_snapshot()

    assert snapshot.authority_count == 55
    assert snapshot.enriched_count == 50
    assert len(reads) == 50
    assert len(snapshot.items) == 50
    assert snapshot.bytes_read <= 50 * 2 * 64 * 1024
    assert snapshot.items[0].projection.session_id == "session-54"
    assert snapshot.items[-1].projection.session_id == "session-5"
    assert snapshot.items[0].projection.first_message == "first prompt 54"
    assert snapshot.items[0].projection.last_message_preview == ("last bounded preview")
    assert all(item.projection.bounded for item in snapshot.items)
    assert all(not item.projection.all_messages_text for item in snapshot.items)
    assert not catalog.index_path.exists()
    assert not tuple(tmp_path.glob("*.model-input-v2-index.json"))


def test_bounded_catalog_can_publish_complete_lightweight_index(
    tmp_path: Path,
) -> None:
    for index in range(3):
        write_agent_transcript_export(
            tmp_path / f"session-{index}.jsonl",
            _header(f"session-{index}", cwd="/workspace"),
            [_record(f"record-{index}", f"prompt {index}")],
        )
    catalog = AgentTranscriptSessionCatalog(tmp_path)

    published = catalog.refresh_bounded_index()

    assert len(published) == 3
    assert catalog.index_path.exists()
    assert catalog.try_query_index_snapshot().index_state == "fresh"
    loaded = catalog.load_index()
    assert all(summary.bounded for summary in loaded)
    assert all(summary.authority_fingerprint for summary in loaded)
    assert all(summary.counts_exact for summary in loaded)
    assert all(not summary.all_messages_text for summary in loaded)


def test_bounded_index_refresh_does_not_publish_a_racing_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import loushang.harness.transcript.session_catalog as catalog_module

    transcript = tmp_path / "session.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session", cwd="/workspace"),
        [_record("record", "prompt")],
    )
    catalog = AgentTranscriptSessionCatalog(tmp_path)
    original = catalog_module._project_bounded_session_summary

    def mutate_after_projection(candidate, *, segment_bytes):
        result = original(candidate, segment_bytes=segment_bytes)
        with transcript.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        return result

    monkeypatch.setattr(
        catalog_module,
        "_project_bounded_session_summary",
        mutate_after_projection,
    )

    with pytest.raises(RuntimeError, match="changed"):
        catalog.refresh_bounded_index()
    assert not catalog.index_path.exists()


def test_index_freshness_can_ignore_only_the_active_transcript(
    tmp_path: Path,
) -> None:
    active = tmp_path / "active.jsonl"
    inactive = tmp_path / "inactive.jsonl"
    write_agent_transcript_export(
        active,
        _header("active", cwd="/workspace"),
        [_record("active-record", "active")],
    )
    write_agent_transcript_export(
        inactive,
        _header("inactive", cwd="/workspace"),
        [_record("inactive-record", "inactive")],
    )
    catalog = AgentTranscriptSessionCatalog(tmp_path)
    catalog.refresh_index()
    index_mtime = catalog.index_path.stat().st_mtime_ns

    os.utime(active, ns=(index_mtime + 1, index_mtime + 1))

    assert catalog.try_query_index_snapshot().index_state == "stale"
    assert (
        catalog.try_query_index_snapshot(
            ignore_modified_paths=(active,),
        ).index_state
        == "fresh"
    )

    os.utime(inactive, ns=(index_mtime + 2, index_mtime + 2))
    assert (
        catalog.try_query_index_snapshot(
            ignore_modified_paths=(active,),
        ).index_state
        == "stale"
    )


def test_index_fingerprint_detects_replaced_authority_even_with_older_mtime(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "session.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session", cwd="/workspace"),
        [_record("record", "prompt")],
    )
    catalog = AgentTranscriptSessionCatalog(tmp_path)
    catalog.refresh_index()
    index_mtime = catalog.index_path.stat().st_mtime_ns

    os.utime(transcript, ns=(index_mtime - 1, index_mtime - 1))

    assert transcript.stat().st_mtime_ns < index_mtime
    assert catalog.try_query_index_snapshot().index_state == "stale"


def test_resume_index_omits_and_does_not_search_full_message_text(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "session.jsonl"
    write_agent_transcript_export(
        transcript,
        _header("session", cwd="/workspace"),
        [
            _record("first", "visible first prompt"),
            _record("middle", "private middle search token", parent_id="first"),
            _record("last", "visible last preview", parent_id="middle"),
        ],
    )
    catalog = AgentTranscriptSessionCatalog(tmp_path)

    catalog.refresh_index()

    payload = catalog.index_path.read_text(encoding="utf-8")
    assert "all_messages_text" not in payload
    assert "private middle search token" not in payload
    indexed = catalog.load_index()[0]
    assert indexed.all_messages_text == ""
    assert indexed.authority_fingerprint is not None
    assert indexed.bounded is False
    assert (
        catalog.find_indexed_summaries(SessionQuery(text="private middle search token"))
        == []
    )


def test_agent_catalog_projects_a_non_file_store_provider() -> None:
    namespace = "remote"
    key = ConversationKey(namespace, "remote-session")
    store = MemoryConversationStore(record_id=lambda record: record.record_id)

    async def create() -> None:
        await store.create(
            key,
            _header("remote-session", cwd="/workspace/remote"),
            [_record("remote-record", "remote message")],
            operation_id="create:remote-session",
        )

    asyncio.run(create())
    catalog = AgentTranscriptSessionCatalog.from_provider(
        ConversationProviderBinding("remote-provider", namespace, store)
    )

    summaries = catalog.list_summaries()

    assert [summary.session_id for summary in summaries] == ["remote-session"]
    assert summaries[0].session_file is None
    assert summaries[0].locator is not None
    assert summaries[0].locator.provider_id == "remote-provider"


def test_project_session_record_preserves_catalog_listing_shape() -> None:
    record = SessionRecordLike(
        session_id="session-1",
        cwd="/workspace",
        session_file=Path("/tmp/session.jsonl"),
        parent_session=None,
        leaf_id="leaf-1",
        metadata=MetadataLike(
            created_at="2026-07-18T00:00:00Z",
            updated_at="2026-07-18T00:00:01Z",
            name="Demo",
        ),
        message_count=2,
        model={"provider": "test", "model_id": "small"},
    )

    assert project_session_record(record) == {
        "session_id": "session-1",
        "cwd": "/workspace",
        "session_file": "/tmp/session.jsonl",
        "parent_session": None,
        "leaf_id": "leaf-1",
        "metadata": {
            "created_at": "2026-07-18T00:00:00Z",
            "updated_at": "2026-07-18T00:00:01Z",
            "name": "Demo",
        },
        "message_count": 2,
        "model": {"provider": "test", "model_id": "small"},
    }


class MetadataLike:
    def __init__(self, *, created_at: str, updated_at: str, name: str) -> None:
        self.created_at = created_at
        self.updated_at = updated_at
        self.name = name


class SessionRecordLike:
    def __init__(
        self,
        *,
        session_id: str,
        cwd: str,
        session_file: Path,
        parent_session: str | None,
        leaf_id: str | None,
        metadata: MetadataLike,
        message_count: int,
        model: dict[str, str],
    ) -> None:
        self.session_id = session_id
        self.cwd = cwd
        self.session_file = session_file
        self.parent_session = parent_session
        self.leaf_id = leaf_id
        self.metadata = metadata
        self.message_count = message_count
        self.model = model
