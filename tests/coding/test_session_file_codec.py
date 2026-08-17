from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationRecord,
)
from loushang.harness.transcript import AGENT_MESSAGE_KIND
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileError,
    AgentTranscriptFileLayout,
    create_agent_transcript_file_store,
    load_agent_transcript_file,
    load_agent_transcript_repository,
    write_agent_transcript_export,
)

SessionFileError = AgentTranscriptFileError
load_session_file = load_agent_transcript_file
load_session_repository = load_agent_transcript_repository
write_session_file = write_agent_transcript_export


def _header() -> ConversationHeader:
    return ConversationHeader(
        conversation_id="session-1",
        version=1,
        created_at="2026-07-16T00:00:00Z",
        metadata={"cwd": "/workspace/project"},
    )


def _message_record(
    record_id: str = "record-1",
    parent_id: str | None = None,
) -> ConversationRecord[object]:
    return ConversationRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-07-16T00:00:01Z",
        payload=UserMessage(role="user", content="Hello", timestamp=1.0),
    )


def test_write_append_and_load_native_session_file(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    first = _message_record()
    second = _message_record("record-2", first.record_id)

    write_session_file(path, _header(), [first])
    layout = AgentTranscriptFileLayout(tmp_path)
    key = layout.bind_existing_path(path)
    store = create_agent_transcript_file_store(layout)
    snapshot = asyncio.run(store.load(key)).snapshot
    asyncio.run(
        store.append(
            key,
            second,
            expected_revision=snapshot.revision,
            operation_id=second.record_id,
        )
    )
    header, records = load_session_file(path)

    assert header == _header()
    assert records == [first, second]
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["type"] == "conversation"
    assert lines[0]["conversationId"] == "session-1"
    assert [line["type"] for line in lines[1:]] == ["record", "record"]
    assert lines[1]["kind"] == AGENT_MESSAGE_KIND


def test_native_session_load_skips_only_partial_tail(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    record = _message_record()
    write_session_file(path, _header(), [record])
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"type":"record"')

    header, records = load_session_file(path)

    assert header == _header()
    assert records == [record]


def test_file_store_repairs_partial_tail_before_append(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.jsonl"
    first = _message_record()
    write_session_file(path, _header(), [first])
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"type":"record"')

    layout = AgentTranscriptFileLayout(tmp_path)
    key = layout.bind_existing_path(path)
    store = create_agent_transcript_file_store(layout)
    snapshot = asyncio.run(store.load(key)).snapshot
    asyncio.run(
        store.append(
            key,
            _message_record("record-2", "record-1"),
            expected_revision=snapshot.revision,
            operation_id="record-2",
        )
    )
    reloaded = load_session_repository(path)

    assert [record.record_id for record in reloaded.records] == [
        "record-1",
        "record-2",
    ]


def test_native_session_rejects_invalid_complete_record(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session_file(path, _header(), [_message_record()])
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{not-json}\n")

    with pytest.raises(SessionFileError):
        load_session_file(path)


def test_native_repository_rejects_session_v3_without_rewriting(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    values = [
        {
            "type": "session",
            "version": 3,
            "id": "session-1",
            "timestamp": "2026-07-16T00:00:00Z",
            "cwd": "/workspace/project",
            "parentSession": None,
        },
        {
            "type": "message",
            "id": "record-1",
            "parentId": None,
            "timestamp": "2026-07-16T00:00:01Z",
            "message": {"role": "user", "content": "Hello", "timestamp": 1.0},
        },
    ]
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in values),
        encoding="utf-8",
    )
    original = path.read_bytes()

    with pytest.raises(SessionFileError) as error:
        load_session_repository(path)

    assert error.value.code == "unsupported_session_format"
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("contents", "code"),
    [
        ("not-json\n", "invalid_session_header_json"),
        (
            '{"type":"record","recordId":"record-1"}\n',
            "unsupported_session_format",
        ),
        (
            '{"type":"session","version":2,"id":"old",'
            '"timestamp":"2026-07-16T00:00:00Z","cwd":"/tmp"}\n',
            "unsupported_session_format",
        ),
    ],
)
def test_unsupported_input_is_rejected_without_rewrite(
    tmp_path: Path,
    contents: str,
    code: str,
) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(SessionFileError) as error:
        load_session_file(path)

    assert error.value.code == code
    assert path.read_text(encoding="utf-8") == contents


def test_loaded_repository_append_is_detached_from_source(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    write_session_file(path, _header(), [_message_record()])
    original = path.read_bytes()
    repository = load_session_repository(path)

    repository.append(_message_record("record-2", "record-1"))

    assert len(repository.records) == 2
    assert path.read_bytes() == original
    assert len(load_session_repository(path).records) == 1


def test_read_only_repository_rejects_session_v3_without_rewriting_source(
    tmp_path: Path,
) -> None:
    path = tmp_path / "session.jsonl"
    values = [
        {
            "type": "session",
            "version": 3,
            "id": "session-1",
            "timestamp": "2026-07-16T00:00:00Z",
            "cwd": "/workspace/project",
            "parentSession": None,
        },
        {
            "type": "message",
            "id": "record-1",
            "parentId": None,
            "timestamp": "2026-07-16T00:00:01Z",
            "message": {"role": "user", "content": "Hello", "timestamp": 1.0},
        },
    ]
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in values),
        encoding="utf-8",
    )
    original = path.read_bytes()

    with pytest.raises(SessionFileError) as error:
        load_session_repository(path)

    assert error.value.code == "unsupported_session_format"
    assert path.read_bytes() == original


@pytest.mark.parametrize("loader", [load_session_file, load_session_repository])
def test_conversation_jsonl_future_version_is_rejected(tmp_path: Path, loader) -> None:
    path = tmp_path / "session.jsonl"
    header = _header()
    path.write_text(
        json.dumps(
            {
                "type": "conversation",
                "conversationId": header.conversation_id,
                "version": 2,
                "createdAt": header.created_at,
                "metadata": dict(header.metadata),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SessionFileError) as error:
        loader(path)

    assert error.value.code == "unsupported_session_format"
