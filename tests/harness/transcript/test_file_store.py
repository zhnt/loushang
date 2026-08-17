from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    ConversationRecord,
    StoreAlreadyExistsError,
)
from loushang.harness.transcript import AGENT_MESSAGE_KIND
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileError,
    AgentTranscriptFileLayout,
    create_agent_transcript_file_store,
    load_agent_transcript_repository,
)


def _header(conversation_id: str = "conversation-1") -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-07-18T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )


def _record() -> ConversationRecord[object]:
    return ConversationRecord(
        record_id="record-1",
        parent_id=None,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-07-18T00:00:01Z",
        payload=UserMessage(role="user", content="hello", timestamp=1.0),
    )


def test_file_store_binds_and_discovers_conversation_jsonl_transcript(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        layout = AgentTranscriptFileLayout(tmp_path)
        store = create_agent_transcript_file_store(layout)
        key = ConversationKey(
            namespace=layout.namespace,
            conversation_id="conversation-1",
        )

        snapshot = await store.create(
            key,
            _header(),
            [_record()],
            operation_id=f"create:{key.namespace}:{key.conversation_id}",
        )

        assert snapshot.records == (_record(),)
        path = layout.resolve_path(key)
        assert path is not None
        assert layout.key_for_path(layout.namespace, path) == key
        assert await store.scan(layout.namespace) == (key,)

    asyncio.run(scenario())


def test_file_layout_allows_product_filename_selection(tmp_path: Path) -> None:
    layout = AgentTranscriptFileLayout(
        tmp_path,
        filename_for_key=lambda key: f"{key.conversation_id}.transcript.jsonl",
    )
    key = layout.key("conversation-2")

    assert layout.create_path(key) == tmp_path / "conversation-2.transcript.jsonl"


def test_file_layout_retains_deleted_identity_across_store_instances(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        first_layout = AgentTranscriptFileLayout(tmp_path)
        key = first_layout.key("conversation-1")
        first_store = create_agent_transcript_file_store(first_layout)
        await first_store.create(
            key,
            _header(),
            operation_id=f"create:{key.namespace}:{key.conversation_id}",
        )
        await first_store.delete(
            key,
            expected_revision=0,
            operation_id="delete:conversation-1:0",
        )

        second_layout = AgentTranscriptFileLayout(tmp_path)
        second_store = create_agent_transcript_file_store(second_layout)
        with pytest.raises(StoreAlreadyExistsError, match="retired identity"):
            await second_store.create(
                second_layout.key("conversation-1"),
                _header(),
                operation_id="create:conversation-1:replacement",
            )

    asyncio.run(scenario())


def test_conversation_jsonl_loader_rejects_future_format_without_rewrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / "future.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "conversation",
                "conversationId": "future",
                "version": 2,
                "createdAt": "2026-07-18T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    original = path.read_bytes()

    with pytest.raises(AgentTranscriptFileError) as error:
        load_agent_transcript_repository(path)

    assert error.value.code == "unsupported_session_format"
    assert path.read_bytes() == original
