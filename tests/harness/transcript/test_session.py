from __future__ import annotations

import asyncio

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
)
from loushang.harness.transcript import (
    AgentTranscriptSession,
    AgentTranscriptUnitOfWork,
)


def test_agent_transcript_session_owns_standard_commit_and_label_operations() -> None:
    async def scenario() -> None:
        backend = MemoryConversationStore(record_id=lambda record: record.record_id)
        transcript = await AgentTranscriptUnitOfWork.create(
            backend,
            ConversationKey("test", "conversation-1"),
            ConversationHeader(
                conversation_id="conversation-1",
                version=1,
                created_at="2026-07-18T00:00:00Z",
            ),
            id_factory=iter(("record-1", "record-2", "record-3")).__next__,
        )
        session = AgentTranscriptSession(
            transcript=transcript,
            application_message_id_factory=lambda: "application-1",
        )
        committed: list[str] = []
        session.set_commit_observer(lambda result: committed.append(result.record_id))

        message_id = await session.append_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        await session.append_label(message_id, "important")
        application_id = await session.append_custom_message_entry(
            "notice",
            "saved",
            display=True,
        )

        assert session.get_label(message_id) == "important"
        assert [record.record_id for record in session.get_branch()] == [
            message_id,
            "record-2",
            application_id,
        ]
        assert [message.role for message in session.build_context().messages] == [
            "user",
            "application",
        ]
        assert committed == [message_id, "record-2", application_id]
        suffix = session.get_append_only_entries_since(message_id)
        assert suffix is not None
        assert [record.record_id for record in suffix] == ["record-2", application_id]
        assert session.get_append_only_entries_since(application_id) == ()
        session.branch(message_id)
        assert session.get_append_only_entries_since(application_id) is None

    asyncio.run(scenario())


def test_incremental_graph_append_waits_for_receipt_without_blocking_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        backend = MemoryConversationStore(record_id=lambda record: record.record_id)
        transcript = await AgentTranscriptUnitOfWork.create(
            backend,
            ConversationKey("test", "responsive-append"),
            ConversationHeader(
                conversation_id="responsive-append",
                version=1,
                created_at="2026-07-18T00:00:00Z",
            ),
        )
        await transcript.append_agent_message(
            UserMessage(role="user", content="first", timestamp=1.0)
        )
        entered = asyncio.Event()
        release = asyncio.Event()
        original = backend.append

        async def held_append(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(backend, "append", held_append)
        operation = asyncio.create_task(
            transcript.append_agent_message(
                UserMessage(role="user", content="second", timestamp=2.0)
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.sleep(0)
            assert not operation.done()
            assert transcript.revision == 1
            assert (await backend.load(transcript.key)).snapshot.revision == 1
        finally:
            release.set()
            if operation.done():
                await asyncio.gather(operation, return_exceptions=True)
        await operation
        assert transcript.revision == 2
        assert (await backend.load(transcript.key)).snapshot.revision == 2

    asyncio.run(scenario())
