from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    ConversationLoadResult,
    ConversationSourceDiagnostic,
    MemoryConversationStore,
    StoreCommitOutcomeUnknown,
)
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    EXTENSION_DATA_KIND,
    AgentTranscriptRecordFactory,
    AgentTranscriptUnitOfWork,
    ApplicationMessage,
    ApplicationMessageIdentityConflictError,
    ExtensionData,
    PrebuiltExtensionDataIdentityConflictError,
    PrebuiltUserMessageIdentityConflictError,
    TranscriptCommitter,
)
from loushang.harness.transcript.unit_of_work import AgentTranscriptCommit


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


def _prebuilt_user_record(*, content: str = "continue"):
    return AgentTranscriptRecordFactory(
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
        id_factory=lambda: "stable-input-record",
    ).create(
        AGENT_MESSAGE_KIND,
        UserMessage(role="user", content=content, timestamp=1.0),
        parent_id=None,
        metadata={
            "coding.runtimeBindingV1": {"version": 1, "inputId": "input-1"},
            "harness.resourceEvidenceV1": {"version": 1},
        },
    )


def _prebuilt_extension_record(*, request_id: str = "request-1"):
    return AgentTranscriptRecordFactory(
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
        id_factory=lambda: "stable-attempt-record",
    ).create(
        EXTENSION_DATA_KIND,
        ExtensionData(
            "coding.activation-attempt/v1",
            {"version": 1, "requestId": request_id},
        ),
        parent_id=None,
    )


def test_prebuilt_extension_record_reconciles_same_id_after_reload() -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("unused"))
        record = _prebuilt_extension_record()
        committer = TranscriptCommitter(store)

        first = await committer.commit_prebuilt_extension_data(record)
        duplicate = await committer.commit_prebuilt_extension_data(record)
        loaded = await AgentTranscriptUnitOfWork.load(store.backend, store.key)
        after_restart = await TranscriptCommitter(loaded).commit_prebuilt_extension_data(
            record
        )

        assert first.disposition == "committed"
        assert duplicate.disposition == "already_committed"
        assert after_restart.disposition == "already_committed"
        assert loaded.records == (record,)
        with pytest.raises(PrebuiltExtensionDataIdentityConflictError):
            await TranscriptCommitter(loaded).commit_prebuilt_extension_data(
                _prebuilt_extension_record(request_id="different")
            )
        loaded.reset_branch()
        with pytest.raises(
            PrebuiltExtensionDataIdentityConflictError, match="selected branch",
        ):
            await TranscriptCommitter(loaded).commit_prebuilt_extension_data(record)

    asyncio.run(scenario())


def test_prebuilt_extension_record_reconciles_lost_ack_only_after_reload() -> None:
    class LostAckStore(MemoryConversationStore):
        append_calls = 0

        async def append(self, key, record, *, expected_revision, operation_id):
            self.append_calls += 1
            await super().append(
                key, record, expected_revision=expected_revision,
                operation_id=operation_id,
            )
            raise StoreCommitOutcomeUnknown("ack lost after durable append")

    async def scenario() -> None:
        backend = LostAckStore(record_id=lambda record: record.record_id)
        key = ConversationKey("test", "conversation-1")
        store = await AgentTranscriptUnitOfWork.create(
            backend, key,
            ConversationHeader(
                conversation_id="conversation-1", version=1,
                created_at="2026-07-16T00:00:00Z",
            ),
        )
        record = _prebuilt_extension_record()
        committer = TranscriptCommitter(store)
        with pytest.raises(StoreCommitOutcomeUnknown):
            await committer.commit_prebuilt_extension_data(record)
        with pytest.raises(StoreCommitOutcomeUnknown, match="authoritative reload"):
            await committer.commit_prebuilt_extension_data(record)
        assert backend.append_calls == 2

        loaded = await AgentTranscriptUnitOfWork.load(backend, key)
        result = await TranscriptCommitter(loaded).commit_prebuilt_extension_data(record)
        assert result.disposition == "already_committed"
        assert loaded.records == (record,)

    asyncio.run(scenario())


def test_prebuilt_user_record_is_committed_once_across_reload() -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("unused"))
        record = _prebuilt_user_record()
        committer = TranscriptCommitter(store)

        first = await committer.commit_prebuilt_user_message(record)
        duplicate = await committer.commit_prebuilt_user_message(record)
        loaded = await AgentTranscriptUnitOfWork.load(store.backend, store.key)
        after_restart = await TranscriptCommitter(loaded).commit_prebuilt_user_message(
            record
        )

        assert first.disposition == "committed"
        assert duplicate.disposition == "already_committed"
        assert after_restart.disposition == "already_committed"
        assert loaded.records == (record,)
        assert loaded.revision == 1

        with pytest.raises(PrebuiltUserMessageIdentityConflictError):
            await TranscriptCommitter(loaded).commit_prebuilt_user_message(
                _prebuilt_user_record(content="different")
            )
        loaded.reset_branch()
        with pytest.raises(
            PrebuiltUserMessageIdentityConflictError, match="selected branch",
        ):
            await TranscriptCommitter(loaded).commit_prebuilt_user_message(record)
        assert loaded.records == (record,)

    asyncio.run(scenario())


def test_prebuilt_user_lookup_reads_authority_without_committing() -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("unused"))
        record = _prebuilt_user_record()
        committer = TranscriptCommitter(store)
        assert (await committer.lookup_prebuilt_user_message(record)).status == "not_committed_verified"
        assert store.records == ()
        await committer.commit_prebuilt_user_message(record)
        assert (await committer.lookup_prebuilt_user_message(record)).status == "committed"
        assert (await committer.lookup_prebuilt_user_message(
            _prebuilt_user_record(content="changed"),
        )).status == "conflict"
        assert (await committer.lookup_prebuilt_user_message(
            replace(record, metadata={"harness.resourceEvidenceV1": {"version": 2}}),
        )).status == "conflict"
        store.reset_branch()
        assert (await committer.lookup_prebuilt_user_message(record)).status == "conflict"
        assert store.records == (record,)

    asyncio.run(scenario())


def test_prebuilt_user_lookup_does_not_use_stale_memory_as_absence() -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("unused"))
        record = _prebuilt_user_record()
        stale = await AgentTranscriptUnitOfWork.load(store.backend, store.key)
        await TranscriptCommitter(store).commit_prebuilt_user_message(record)
        # The authority result wins over an empty process-local submission ledger.
        assert (await TranscriptCommitter(stale).lookup_prebuilt_user_message(record)).status == "committed"
        other = AgentTranscriptRecordFactory(id_factory=lambda: "other-input").create(
            AGENT_MESSAGE_KIND, UserMessage(role="user", content="other", timestamp=2.0),
            parent_id=None,
        )
        assert (await TranscriptCommitter(stale).lookup_prebuilt_user_message(other)).status == "unknown"
        assert stale.records == ()

    asyncio.run(scenario())


def test_prebuilt_user_lookup_authority_failure_is_unknown(monkeypatch) -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("unused"))

        async def unavailable(key):
            raise FileNotFoundError("authority unavailable")

        monkeypatch.setattr(store.backend, "load", unavailable)
        assert (await TranscriptCommitter(store).lookup_prebuilt_user_message(
            _prebuilt_user_record(),
        )).status == "unknown"
        assert store.records == ()

    asyncio.run(scenario())


def test_prebuilt_user_lookup_incomplete_source_cannot_prove_absence(monkeypatch) -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("unused"))
        original_load = store.backend.load

        async def incomplete(key):
            loaded = await original_load(key)
            return ConversationLoadResult(
                snapshot=loaded.snapshot,
                diagnostics=(ConversationSourceDiagnostic("partial_tail", "incomplete tail"),),
            )

        monkeypatch.setattr(store.backend, "load", incomplete)
        assert (await TranscriptCommitter(store).lookup_prebuilt_user_message(
            _prebuilt_user_record(),
        )).status == "unknown"
        assert store.records == ()

    asyncio.run(scenario())


def test_prebuilt_user_lookup_freezes_metadata_before_async_read(monkeypatch) -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("unused"))
        stored = _prebuilt_user_record()
        committer = TranscriptCommitter(store)
        await committer.commit_prebuilt_user_message(stored)
        expected = _prebuilt_user_record()
        original_load = store.backend.load

        async def change_caller_input(key):
            expected.metadata["harness.resourceEvidenceV1"]["version"] = 2
            return await original_load(key)

        monkeypatch.setattr(store.backend, "load", change_caller_input)
        assert (await committer.lookup_prebuilt_user_message(expected)).status == "committed"
        assert store.records == (stored,)

    asyncio.run(scenario())


def test_prebuilt_user_record_reconciles_lost_ack_by_fixed_record_id() -> None:
    class LostAckStore(MemoryConversationStore):
        append_calls = 0

        async def append(self, key, record, *, expected_revision, operation_id):
            self.append_calls += 1
            await super().append(
                key, record,
                expected_revision=expected_revision,
                operation_id=operation_id,
            )
            raise StoreCommitOutcomeUnknown("ack lost after durable append")

    async def scenario() -> None:
        backend = LostAckStore(record_id=lambda record: record.record_id)
        key = ConversationKey("test", "conversation-1")
        store = await AgentTranscriptUnitOfWork.create(
            backend,
            key,
            ConversationHeader(
                conversation_id="conversation-1",
                version=1,
                created_at="2026-07-16T00:00:00Z",
            ),
        )
        record = _prebuilt_user_record()
        committer = TranscriptCommitter(store)
        with pytest.raises(StoreCommitOutcomeUnknown):
            await committer.commit_prebuilt_user_message(record)
        with pytest.raises(StoreCommitOutcomeUnknown, match="authoritative reload"):
            await committer.commit_prebuilt_user_message(record)
        assert backend.append_calls == 2

        assert (await committer.lookup_prebuilt_user_message(record)).status == "committed"
        assert backend.append_calls == 2

        loaded = await AgentTranscriptUnitOfWork.load(backend, key)
        result = await TranscriptCommitter(loaded).commit_prebuilt_user_message(record)
        assert result.disposition == "already_committed"
        assert loaded.records == (record,)
        assert loaded.revision == 1

    asyncio.run(scenario())


def test_prebuilt_user_record_without_durable_receipt_requires_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        store = await _store(ids=_ids("unused"))
        record = _prebuilt_user_record()
        committer = TranscriptCommitter(store)
        calls = 0

        async def missing_receipt(_record):
            nonlocal calls
            calls += 1
            return AgentTranscriptCommit(record=record, receipt=None)

        monkeypatch.setattr(store, "commit", missing_receipt)
        with pytest.raises(StoreCommitOutcomeUnknown, match="durable receipt"):
            await committer.commit_prebuilt_user_message(record)
        with pytest.raises(StoreCommitOutcomeUnknown, match="authoritative reload"):
            await committer.commit_prebuilt_user_message(record)
        assert calls == 1
        assert store.records == ()
        assert (await committer.lookup_prebuilt_user_message(record)).status == "unknown"
        assert calls == 1

    asyncio.run(scenario())
