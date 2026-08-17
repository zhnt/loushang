from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
)
from loushang.harness.transcript import (
    APPLICATION_MESSAGE_KIND,
    AgentTranscriptRecordFactory,
    AgentTranscriptUnitOfWork,
    ApplicationMessage,
    ApplicationMessageIdentityConflictError,
    TranscriptCommitter,
)


def _ids(*values: str):
    values_iter = iter(values)
    return lambda: next(values_iter)


def _message(content: str = "notice") -> ApplicationMessage:
    return ApplicationMessage(
        application_message_id="application-1",
        custom_type="notice",
        content=content,
        timestamp=1.0,
    )


async def _store(*, ids) -> AgentTranscriptUnitOfWork:
    backend = MemoryConversationStore(record_id=lambda record: record.record_id)
    return await AgentTranscriptUnitOfWork.create(
        backend,
        ConversationKey("test", "conversation-1"),
        ConversationHeader(
            conversation_id="conversation-1",
            version=1,
            created_at="2026-07-16T00:00:00Z",
        ),
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
        id_factory=ids,
    )


def test_record_factory_builds_records_without_committing_them() -> None:
    factory = AgentTranscriptRecordFactory(
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
        id_factory=_ids("record-1"),
    )

    record = factory.create(
        APPLICATION_MESSAGE_KIND,
        _message(),
        parent_id="parent-1",
    )

    assert record.record_id == "record-1"
    assert record.parent_id == "parent-1"
    assert record.created_at == "2026-07-16T00:00:00Z"


def test_committer_is_idempotent_and_rejects_identity_conflicts() -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("record-1"))
        committer = TranscriptCommitter(store)

        first = await committer.commit_application_message(_message())
        duplicate = await committer.commit_application_message(_message())

        assert first.disposition == "committed"
        assert duplicate.disposition == "already_committed"
        assert duplicate.record_id == first.record_id
        assert len(store.records) == 1
        assert store.records[0].kind == APPLICATION_MESSAGE_KIND

        with pytest.raises(
            ApplicationMessageIdentityConflictError,
            match="different payload",
        ):
            await committer.commit_application_message(_message("changed"))
        assert len(store.records) == 1

    asyncio.run(scenario())


def test_failed_append_is_not_memoized_as_committed() -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("same", "same", "recovered"))
        await store.append_application_message(
            ApplicationMessage(
                application_message_id="existing",
                custom_type="notice",
                content="existing",
                timestamp=0.0,
            )
        )
        committer = TranscriptCommitter(store)

        with pytest.raises(ValueError, match="Duplicate branch record id"):
            await committer.commit_application_message(_message())

        recovered = await committer.commit_application_message(_message())
        assert recovered.disposition == "committed"
        assert recovered.record_id == "recovered"

    asyncio.run(scenario())


def test_committer_rebuilds_application_message_identity_from_loaded_records() -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("record-1"))
        first = await TranscriptCommitter(store).commit_application_message(_message())
        loaded = await AgentTranscriptUnitOfWork.load(store.backend, store.key)

        duplicate = await TranscriptCommitter(loaded).commit_application_message(
            _message()
        )

        assert duplicate.disposition == "already_committed"
        assert duplicate.record_id == first.record_id
        assert loaded.revision == 1

    asyncio.run(scenario())


def test_record_factory_requires_timezone_aware_clock() -> None:
    factory = AgentTranscriptRecordFactory(
        clock=lambda: datetime(2026, 7, 16),
        id_factory=_ids("record-1"),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        factory.create(APPLICATION_MESSAGE_KIND, _message(), parent_id=None)
