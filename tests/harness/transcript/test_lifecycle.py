from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.ai.types import UserMessage
from loushang.harness.conversation import (
    ConversationHeader,
    ConversationKey,
    MemoryConversationStore,
)
from loushang.harness.transcript import (
    AGENT_MESSAGE_KIND,
    AgentTranscriptFileLayout,
    AgentTranscriptLifecycle,
    AgentTranscriptProfile,
    AgentTranscriptRecord,
    AgentTranscriptRuntimeBinding,
    ModelSelectionSnapshot,
    create_agent_transcript_file_store,
    delete_agent_transcript_jsonl,
    write_agent_transcript_export,
)


def _header(conversation_id: str = "conversation-1") -> ConversationHeader:
    return ConversationHeader(
        conversation_id=conversation_id,
        version=1,
        created_at="2026-07-18T00:00:00Z",
        metadata={"cwd": "/workspace"},
    )


def _record(
    record_id: str,
    parent_id: str | None = None,
) -> AgentTranscriptRecord:
    return AgentTranscriptRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=AGENT_MESSAGE_KIND,
        payload_version=1,
        created_at="2026-07-18T00:00:01Z",
        payload=UserMessage(role="user", content=record_id, timestamp=1.0),
    )


def test_lifecycle_creates_restores_and_disposes_native_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        disposed: list[str] = []

        async def bind_runtime(context, binding: str):
            layout = AgentTranscriptFileLayout(context.session_dir)
            key = layout.key(context.header.conversation_id)
            if context.persist:
                assert context.session_file is not None
                layout.bind_create_path(key, context.session_file)
                store = create_agent_transcript_file_store(layout)
            else:
                store = MemoryConversationStore(
                    record_id=lambda record: record.record_id
                )
                key = ConversationKey("memory", context.header.conversation_id)

            async def dispose() -> None:
                disposed.append(binding)

            return AgentTranscriptRuntimeBinding(
                store=store,
                key=key,
                profile=AgentTranscriptProfile.default(),
                product_binding=binding,
                dispose=dispose,
            )

        lifecycle = AgentTranscriptLifecycle(bind_runtime=bind_runtime)
        header = _header()
        context = lifecycle.new_context(
            session_dir=tmp_path,
            cwd="/workspace",
            persist=True,
            header=header,
            session_file=lifecycle.default_jsonl_session_file(tmp_path, header),
        )
        created = await lifecycle.create(context, "created")
        assert context.session_file is not None
        assert not context.session_file.exists()
        assert created.transcript.is_materialized is False
        staged = await created.transcript.append_model_selection(
            ModelSelectionSnapshot(
                endpoint_id="test-endpoint", provider="provider", model_id="model"
            )
        )
        assert staged.receipt is None
        assert not context.session_file.exists()
        await created.transcript.append_agent_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        assert created.transcript.is_materialized is True
        assert context.session_file.is_file()
        await created.dispose()
        await created.dispose()

        restored_context = lifecycle.conversation_jsonl_context(
            context.session_file,
            persist=True,
        )
        restored = await lifecycle.restore(restored_context, "restored")
        assert restored.product_binding == "restored"
        assert [record.record_id for record in restored.transcript.records] == [
            record.record_id for record in created.transcript.records
        ]
        await restored.dispose()

        assert disposed == ["created", "restored"]

    asyncio.run(scenario())


def test_lifecycle_detaches_conversation_jsonl_source_before_writing(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        source = tmp_path / "source.jsonl"
        write_agent_transcript_export(source, _header(), [_record("source-record")])
        original = source.read_bytes()

        async def bind_runtime(context, binding: str):
            del context
            store = MemoryConversationStore(record_id=lambda record: record.record_id)

            async def dispose() -> None:
                return None

            return AgentTranscriptRuntimeBinding(
                store=store,
                key=ConversationKey("memory", "conversation-1"),
                profile=AgentTranscriptProfile.default(),
                product_binding=binding,
                dispose=dispose,
            )

        lifecycle = AgentTranscriptLifecycle(bind_runtime=bind_runtime)
        context = lifecycle.conversation_jsonl_context(source, persist=False)
        detached = await lifecycle.restore(context, "detached")
        await detached.transcript.append_agent_message(
            UserMessage(role="user", content="new", timestamp=2.0)
        )

        assert len(detached.transcript.records) == 2
        assert source.read_bytes() == original
        await detached.dispose()

    asyncio.run(scenario())


def test_lifecycle_context_allows_a_persistent_non_native_provider(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store = MemoryConversationStore(record_id=lambda record: record.record_id)

        async def bind_runtime(context, binding: str):
            async def dispose() -> None:
                return None

            return AgentTranscriptRuntimeBinding(
                store=store,
                key=ConversationKey("database", context.header.conversation_id),
                profile=AgentTranscriptProfile.default(),
                product_binding=binding,
                dispose=dispose,
            )

        lifecycle = AgentTranscriptLifecycle(bind_runtime=bind_runtime)
        context = lifecycle.new_context(
            session_dir=tmp_path,
            cwd="/workspace",
            persist=True,
            header=_header(),
        )

        created = await lifecycle.create(context, "created")
        assert await store.scan("database") == ()
        await created.transcript.append_agent_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        restored = await lifecycle.restore(context, "restored")

        assert context.persist
        assert context.session_file is None
        assert restored.transcript.header == created.transcript.header
        await created.dispose()
        await restored.dispose()

    asyncio.run(scenario())


def test_lifecycle_forks_only_selected_source_path(tmp_path: Path) -> None:
    async def scenario() -> None:
        async def bind_runtime(context, binding: str):
            store = MemoryConversationStore(record_id=lambda record: record.record_id)

            async def dispose() -> None:
                return None

            return AgentTranscriptRuntimeBinding(
                store=store,
                key=ConversationKey("memory", context.header.conversation_id),
                profile=AgentTranscriptProfile.default(),
                product_binding=binding,
                dispose=dispose,
            )

        lifecycle = AgentTranscriptLifecycle(bind_runtime=bind_runtime)
        source = await lifecycle.create(
            lifecycle.new_context(
                session_dir=tmp_path,
                cwd="/workspace",
                persist=False,
                header=_header("source"),
            ),
            "source",
        )
        root = (
            await source.transcript.append_agent_message(
                UserMessage(role="user", content="root", timestamp=1.0)
            )
        ).record
        first = (
            await source.transcript.append_agent_message(
                UserMessage(role="user", content="first", timestamp=2.0)
            )
        ).record
        source.transcript.branch(root.record_id)
        await source.transcript.append_agent_message(
            UserMessage(role="user", content="second", timestamp=3.0)
        )

        forked = await lifecycle.fork(
            source.transcript,
            lifecycle.new_context(
                session_dir=tmp_path,
                cwd="/workspace",
                persist=False,
                header=_header("fork"),
            ),
            "fork",
            leaf_id=first.record_id,
        )

        assert [record.record_id for record in forked.transcript.records] == [
            root.record_id,
            first.record_id,
        ]
        assert forked.transcript.leaf_id == first.record_id
        await source.dispose()
        await forked.dispose()

    asyncio.run(scenario())


def test_lifecycle_releases_binding_after_create_failure_and_protects_active_file(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed: list[str] = []

        async def bind_runtime(context, binding: str):
            async def dispose() -> None:
                disposed.append(binding)

            return AgentTranscriptRuntimeBinding(
                store=MemoryConversationStore(
                    record_id=lambda record: record.record_id
                ),
                key=ConversationKey("memory", "wrong-conversation"),
                profile=AgentTranscriptProfile.default(),
                product_binding=binding,
                dispose=dispose,
            )

        lifecycle = AgentTranscriptLifecycle(bind_runtime=bind_runtime)
        context = lifecycle.new_context(
            session_dir=tmp_path,
            cwd="/workspace",
            persist=False,
            header=_header(),
        )
        with pytest.raises(ValueError, match="conversation key and header id"):
            await lifecycle.create(context, "failed")
        assert disposed == ["failed"]

        source = tmp_path / "deletable.jsonl"
        write_agent_transcript_export(source, _header(), [_record("record-1")])
        with pytest.raises(ValueError, match="currently active"):
            await delete_agent_transcript_jsonl(
                source,
                current_session_file=source,
            )
        assert await delete_agent_transcript_jsonl(source)
        assert not source.exists()
        assert not await delete_agent_transcript_jsonl(source)

    asyncio.run(scenario())
