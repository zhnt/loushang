from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

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
    original = catalog._project_summary

    def project(header, records, leaf_id, locator):
        projected.append(header.conversation_id)
        return original(header, records, leaf_id, locator)

    monkeypatch.setattr(catalog, "_project_summary", project)

    repaired = catalog.repair_index()

    assert projected == ["beta", "gamma"]
    assert {summary.session_id for summary in repaired} == {"beta", "gamma"}
    assert next(
        summary for summary in repaired if summary.session_id == "beta"
    ).entry_count == 2
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
