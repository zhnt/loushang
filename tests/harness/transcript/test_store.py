from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from itertools import count

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.conversation import (
    CommandExecutionRecord,
    ConversationCommitResult,
    ConversationHeader,
    ConversationKey,
    ConversationSnapshot,
    MemoryConversationStore,
    StoreCommitOutcomeUnknown,
    StoreDataError,
)
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    APPLICATION_MESSAGE_KIND,
    COMMAND_EXECUTION_KIND,
    CONTEXT_BRANCH_SUMMARY_KIND,
    CONTEXT_COMPACTION_CHECKPOINT_KIND,
    CONVERSATION_METADATA_PATCH_KIND,
    EXTENSION_DATA_KIND,
    MODEL_SELECTION_KIND,
    RECORD_ANNOTATION_PATCH_KIND,
    THINKING_SELECTION_KIND,
    AgentTranscriptRecordFactory,
    AgentTranscriptUnitOfWork,
    ApplicationMessage,
    BranchContextSummary,
    ContextCompactionCheckpoint,
    ConversationMetadataPatch,
    ExtensionData,
    ModelSelectionSnapshot,
    RecordAnnotationPatch,
    ThinkingSelectionSnapshot,
    TranscriptCommitter,
)


class FailingMemoryStore(MemoryConversationStore):
    def __init__(self) -> None:
        super().__init__(record_id=lambda record: record.record_id)
        self.append_calls = 0
        self.failure: Exception | None = None

    async def append(
        self,
        key: ConversationKey,
        record,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult:
        self.append_calls += 1
        if self.failure is not None:
            error = self.failure
            self.failure = None
            raise error
        return await super().append(
            key,
            record,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )


class BlockingAppendMemoryStore(MemoryConversationStore):
    def __init__(self) -> None:
        super().__init__(record_id=lambda record: record.record_id)
        self.committed = asyncio.Event()
        self.release = asyncio.Event()

    async def append(
        self,
        key: ConversationKey,
        record,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult:
        result = await super().append(
            key,
            record,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )
        self.committed.set()
        await self.release.wait()
        return result


class BlockingCreateMemoryStore(MemoryConversationStore):
    def __init__(self) -> None:
        super().__init__(record_id=lambda record: record.record_id)
        self.committed = asyncio.Event()
        self.release = asyncio.Event()

    async def create(self, key, header, records=(), *, operation_id: str):
        snapshot = await super().create(
            key,
            header,
            records,
            operation_id=operation_id,
        )
        self.committed.set()
        await self.release.wait()
        return snapshot


class LostAppendResponseMemoryStore(MemoryConversationStore):
    def __init__(self) -> None:
        super().__init__(record_id=lambda record: record.record_id)
        self.append_calls = 0

    async def append(
        self,
        key: ConversationKey,
        record,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult:
        self.append_calls += 1
        result = await super().append(
            key,
            record,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )
        if self.append_calls == 1:
            raise StoreCommitOutcomeUnknown("append response lost")
        return result


class BlockingFailureMemoryStore(MemoryConversationStore):
    def __init__(self) -> None:
        super().__init__(record_id=lambda record: record.record_id)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def append(
        self,
        key: ConversationKey,
        record,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult:
        del key, record, expected_revision, operation_id
        self.started.set()
        await self.release.wait()
        raise StoreDataError("durable commit failed")


def _header(conversation_id: str = "conversation-1") -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-07-16T00:00:00Z",
    )


def _key(conversation_id: str = "conversation-1") -> ConversationKey:
    return ConversationKey("test", conversation_id)


def _id_factory(prefix: str = "record"):
    values = count(1)
    return lambda: f"{prefix}-{next(values)}"


async def _create(
    backend=None,
    *,
    ids=None,
) -> AgentTranscriptUnitOfWork:
    resolved_backend = backend or MemoryConversationStore(
        record_id=lambda record: record.record_id
    )
    return await AgentTranscriptUnitOfWork.create(
        resolved_backend,
        _key(),
        _header(),
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
        id_factory=ids or _id_factory(),
    )


def _application(message_id: str, content: str) -> ApplicationMessage:
    return ApplicationMessage(
        application_message_id=message_id,
        custom_type="notice",
        content=content,
        timestamp=1.0,
    )


def test_store_create_append_load_and_replay_context() -> None:
    async def scenario() -> None:
        backend = MemoryConversationStore(record_id=lambda record: record.record_id)
        store = await _create(backend)

        first_commit = await store.append_agent_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        second_commit = await store.append_application_message(
            _application("application-1", "continue")
        )
        first = first_commit.record
        second = second_commit.record

        assert store.revision == 2
        assert first_commit.receipt.revision == 1
        assert second_commit.receipt.revision == 2
        assert store.leaf_id == second.record_id
        assert second.parent_id == first.record_id
        assert store.get(first.record_id) == first
        assert store.children(first.record_id) == (second,)
        assert store.active_path() == (first, second)
        assert [node.record for node in store.tree()] == [first]
        context = store.replay_context()
        assert len(context.messages) == 2
        assert isinstance(context.messages[0], UserMessage)
        assert context.messages[0].content == "hello"

        loaded = await AgentTranscriptUnitOfWork.load(backend, _key())
        assert loaded.header == store.header
        assert loaded.records == store.records
        assert loaded.revision == store.revision
        assert loaded.leaf_id == store.leaf_id

    asyncio.run(scenario())


def test_provisional_store_materializes_with_staged_records_on_first_user_message() -> (
    None
):
    async def scenario() -> None:
        backend = MemoryConversationStore(record_id=lambda record: record.record_id)
        store = await AgentTranscriptUnitOfWork.create(
            backend,
            _key(),
            _header(),
            clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
            id_factory=_id_factory(),
            defer_materialization=True,
        )

        assert store.is_materialized is False
        assert await backend.scan(_key().namespace) == ()

        staged = await store.append_model_selection(
            ModelSelectionSnapshot(
                endpoint_id="test-endpoint", provider="provider", model_id="model"
            )
        )
        assert staged.receipt is None
        assert staged.durable is False
        assert store.revision == 1
        assert await backend.scan(_key().namespace) == ()

        committed = await store.append_agent_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        assert committed.receipt is not None
        assert committed.receipt.revision == 2
        assert committed.durable is True
        assert store.is_materialized is True
        assert await backend.scan(_key().namespace) == (_key(),)

        loaded = await AgentTranscriptUnitOfWork.load(backend, _key())
        assert [record.kind for record in loaded.records] == [
            MODEL_SELECTION_KIND,
            AGENT_MESSAGE_KIND,
        ]

    asyncio.run(scenario())


def test_committed_append_finishes_atomically_after_repeated_cancellation() -> None:
    async def scenario() -> None:
        backend = BlockingAppendMemoryStore()
        store = await _create(backend, ids=_id_factory())
        committer = TranscriptCommitter(store)
        message = _application("application-1", "notice")

        task = asyncio.create_task(committer.commit_application_message(message))
        await backend.committed.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)

        assert task.done() is False
        backend.release.set()
        committed = await task

        assert committed.disposition == "committed"
        assert task.cancelling() == 0
        assert store.revision == 1
        assert len(store.records) == 1

        duplicate = await committer.commit_application_message(message)
        assert duplicate.disposition == "already_committed"
        assert duplicate.record_id == committed.record_id
        assert len(store.records) == 1

        second = await store.append_application_message(
            _application("application-2", "next")
        )
        assert second.receipt is not None
        assert second.receipt.revision == 2

    asyncio.run(scenario())


def test_first_materialization_finishes_atomically_after_cancellation() -> None:
    async def scenario() -> None:
        backend = BlockingCreateMemoryStore()
        store = await AgentTranscriptUnitOfWork.create(
            backend,
            _key(),
            _header(),
            clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
            id_factory=_id_factory(),
            defer_materialization=True,
        )

        task = asyncio.create_task(
            store.append_agent_message(
                UserMessage(role="user", content="hello", timestamp=1.0)
            )
        )
        await backend.committed.wait()
        task.cancel()
        await asyncio.sleep(0)

        assert task.done() is False
        backend.release.set()
        committed = await task

        assert committed.receipt is not None
        assert committed.receipt.revision == 1
        assert store.is_materialized is True
        assert store.revision == 1
        second = await store.append_application_message(
            _application("application-2", "next")
        )
        assert second.receipt is not None
        assert second.receipt.revision == 2

    asyncio.run(scenario())


def test_commit_surfaces_backend_error_when_cancellation_arrives_concurrently() -> None:
    async def scenario() -> None:
        backend = BlockingFailureMemoryStore()
        store = await _create(backend)
        task = asyncio.create_task(
            store.append_application_message(_application("application-1", "notice"))
        )
        await backend.started.wait()
        task.cancel()
        await asyncio.sleep(0)
        backend.release.set()

        with pytest.raises(StoreDataError, match="durable commit failed"):
            await task
        assert task.cancelling() == 0
        assert store.revision == 0
        assert store.records == ()

    asyncio.run(scenario())


def test_append_retries_a_lost_success_response_once_with_the_same_operation() -> None:
    async def scenario() -> None:
        backend = LostAppendResponseMemoryStore()
        store = await _create(backend, ids=lambda: "record-1")

        committed = await store.append_application_message(
            _application("application-1", "notice")
        )

        assert backend.append_calls == 2
        assert committed.receipt is not None
        assert committed.receipt.revision == 1
        assert store.revision == 1
        assert len(store.records) == 1

    asyncio.run(scenario())


def test_store_prevalidates_graph_and_does_not_advance_on_append_failure() -> None:
    async def scenario() -> None:
        backend = FailingMemoryStore()
        ids = iter(("record-1", "record-1", "record-2"))
        store = await _create(backend, ids=lambda: next(ids))
        first = (
            await store.append_application_message(_application("one", "one"))
        ).record
        assert backend.append_calls == 1

        with pytest.raises(ValueError, match="Duplicate branch record id"):
            await store.append_application_message(_application("duplicate", "bad"))
        assert backend.append_calls == 1
        assert store.records == (first,)
        assert store.leaf_id == first.record_id
        assert store.revision == 1

        backend.failure = OSError("backend unavailable")
        with pytest.raises(OSError, match="backend unavailable"):
            await store.append_application_message(_application("failed", "failed"))
        assert backend.append_calls == 2
        assert store.records == (first,)
        assert store.leaf_id == first.record_id
        assert store.revision == 1

    asyncio.run(scenario())


def test_store_rejects_a_prebuilt_record_from_a_stale_leaf() -> None:
    async def scenario() -> None:
        backend = FailingMemoryStore()
        store = await _create(backend)
        first = (
            await store.append_application_message(_application("one", "one"))
        ).record
        stale = AgentTranscriptRecordFactory(
            clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
            id_factory=lambda: "stale",
        ).create(
            APPLICATION_MESSAGE_KIND,
            _application("stale", "stale"),
            parent_id=None,
        )

        with pytest.raises(ValueError, match="parent must match the selected leaf"):
            await store.commit(stale)

        assert backend.append_calls == 1
        assert store.records == (first,)
        assert store.leaf_id == first.record_id
        assert store.revision == 1

    asyncio.run(scenario())


def test_application_commit_failure_is_not_remembered() -> None:
    async def scenario() -> None:
        backend = FailingMemoryStore()
        backend.failure = OSError("backend unavailable")
        store = await _create(backend, ids=iter(("failed", "recovered")).__next__)
        committer = TranscriptCommitter(store)

        with pytest.raises(OSError, match="backend unavailable"):
            await committer.commit_application_message(_application("one", "one"))

        recovered = await committer.commit_application_message(
            _application("one", "one")
        )
        assert recovered.disposition == "committed"
        assert recovered.record_id == "recovered"
        assert store.revision == 1

    asyncio.run(scenario())


def test_concurrent_appends_form_one_revision_ordered_chain() -> None:
    async def scenario() -> None:
        store = await _create()
        first_commit, second_commit = await asyncio.gather(
            store.append_application_message(_application("one", "one")),
            store.append_application_message(_application("two", "two")),
        )
        first = first_commit.record
        second = second_commit.record

        assert first.parent_id is None
        assert second.parent_id == first.record_id
        assert (first_commit.receipt.revision, second_commit.receipt.revision) == (1, 2)
        assert store.records == (first, second)
        assert store.revision == 2

    asyncio.run(scenario())


def test_store_branch_reset_delta_and_fork_copy_only_the_active_path() -> None:
    async def scenario() -> None:
        backend = MemoryConversationStore(record_id=lambda record: record.record_id)
        store = await _create(backend)
        root = (
            await store.append_application_message(_application("root", "root"))
        ).record
        left = (
            await store.append_application_message(_application("left", "left"))
        ).record
        store.branch(root.record_id)
        right = (
            await store.append_application_message(_application("right", "right"))
        ).record

        assert store.children(root.record_id) == (left, right)
        delta = store.branch_delta(left.record_id, right.record_id)
        assert delta.common_ancestor_id == root.record_id
        assert delta.divergent_records == (left,)

        forked = await store.fork(
            _key("conversation-fork"),
            ConversationHeader(
                conversation_id="conversation-fork",
                version=1,
                created_at="2026-07-16T00:01:00Z",
                parent_conversation_id="conversation-1",
            ),
        )
        assert forked.records == (root, right)
        assert forked.revision == 2
        assert forked.leaf_id == right.record_id

        store.reset_branch()
        assert store.leaf_id is None
        assert store.active_path() == ()

    asyncio.run(scenario())


def test_store_exposes_all_standard_typed_append_operations() -> None:
    async def scenario() -> None:
        store = await _create()
        root = (
            await store.append_agent_message(
                UserMessage(role="user", content="hello", timestamp=1.0)
            )
        ).record
        await store.append_thinking_selection(ThinkingSelectionSnapshot(level="high"))
        await store.append_model_selection(
            ModelSelectionSnapshot(
                endpoint_id="test-endpoint", provider="test", model_id="model"
            )
        )
        await store.append_command_execution(
            CommandExecutionRecord(command="pwd", output="/tmp", exit_code=0)
        )
        await store.append_compaction_checkpoint(
            ContextCompactionCheckpoint(
                summary="summary",
                first_kept_record_id=root.record_id,
                tokens_before=10,
            )
        )
        await store.append_branch_summary(
            BranchContextSummary(from_record_id=root.record_id, summary="branch")
        )
        await store.append_application_message(_application("application-1", "notice"))
        await store.append_extension_data(ExtensionData(extension_type="demo"))
        await store.append_annotation_patch(
            RecordAnnotationPatch(
                target_record_id=root.record_id,
                namespace="display.label",
                operation="set",
                value="root",
            )
        )
        await store.append_metadata_patch(
            ConversationMetadataPatch(values={"name": "demo"})
        )

        assert tuple(record.kind for record in store.records) == (
            AGENT_MESSAGE_KIND,
            THINKING_SELECTION_KIND,
            MODEL_SELECTION_KIND,
            COMMAND_EXECUTION_KIND,
            CONTEXT_COMPACTION_CHECKPOINT_KIND,
            CONTEXT_BRANCH_SUMMARY_KIND,
            APPLICATION_MESSAGE_KIND,
            EXTENSION_DATA_KIND,
            RECORD_ANNOTATION_PATCH_KIND,
            CONVERSATION_METADATA_PATCH_KIND,
        )
        assert store.revision == 10

    asyncio.run(scenario())


def test_store_validates_identity_before_backend_create() -> None:
    backend = MemoryConversationStore()

    async def scenario() -> ConversationSnapshot:
        with pytest.raises(ValueError, match="key and header id"):
            await AgentTranscriptUnitOfWork.create(
                backend,
                _key("different"),
                _header(),
            )
        return await backend.create(
            _key(),
            _header(),
            operation_id="create:test:conversation-1",
        )

    snapshot = asyncio.run(scenario())
    assert snapshot.revision == 0
    assert snapshot.records == ()


def test_initial_records_are_validated_before_backend_create() -> None:
    async def scenario() -> None:
        backend = MemoryConversationStore()
        source = await _create(ids=lambda: "duplicate")
        record = (
            await source.append_application_message(_application("one", "one"))
        ).record
        with pytest.raises(ValueError, match="Duplicate branch record id"):
            await AgentTranscriptUnitOfWork.create(
                backend,
                _key(),
                _header(),
                records=(record, record),
            )
        assert await backend.scan("test") == ()

    asyncio.run(scenario())
