from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from loushang.ai.types import UserMessage
from loushang.harness.conversation import ConversationKey, MemoryConversationStore
from loushang.harness.transcript import (
    AgentTranscriptFileLayout,
    AgentTranscriptLifecycle,
    AgentTranscriptProfile,
    AgentTranscriptRuntimeBinding,
    AgentTranscriptSessionFactory,
    create_agent_transcript_file_store,
)


def test_session_factory_composes_native_create_restore_and_fork(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed: list[str] = []
        validations: list[tuple[str, str, bool]] = []

        async def bind_runtime(context, binding: str):
            layout = AgentTranscriptFileLayout(context.session_dir)
            if context.persist:
                assert context.session_file is not None
                key = layout.key(context.header.conversation_id)
                layout.bind_create_path(key, context.session_file)
                store = create_agent_transcript_file_store(layout)
            else:
                key = ConversationKey("memory", context.header.conversation_id)
                store = MemoryConversationStore(
                    record_id=lambda record: record.record_id
                )

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
        factory = AgentTranscriptSessionFactory(
            lifecycle=lifecycle,
            resolve_binding_input=lambda persist: "persistent" if persist else "memory",
            header_metadata=lambda binding: {"productBinding": binding},
            validate_restored_header=lambda header, binding, persist: (
                validations.append((header.conversation_id, binding, persist))
            ),
            session_file_factory=lifecycle.default_jsonl_session_file,
            clock=lambda: datetime(2026, 7, 19, tzinfo=UTC),
            conversation_id_factory=lambda: "generated-session",
        )

        created = await factory.new(
            session_dir=tmp_path,
            cwd="/workspace",
            session_id="source-session",
        )
        assert created.context.session_file is not None
        assert created.context.session_file.is_file() is False
        assert created.context.header.metadata == {
            "cwd": "/workspace",
            "productBinding": "persistent",
        }
        await created.transcript.append_agent_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        assert created.context.session_file.is_file()

        restored = await factory.open(
            created.context.session_file,
            session_dir=tmp_path / "override",
            cwd_override="/other-workspace",
        )
        assert restored.context.session_dir == (tmp_path / "override").resolve()
        assert restored.context.cwd == "/other-workspace"
        assert validations == [("source-session", "persistent", True)]

        forked = await factory.fork(
            restored,
            leaf_id=restored.transcript.leaf_id or "",
            binding_input="persistent",
        )
        assert forked.context.header.parent_conversation_id == "source-session"
        assert forked.context.header.metadata["parentSession"] == str(
            created.context.session_file
        )
        assert [record.record_id for record in forked.transcript.records] == [
            record.record_id for record in restored.transcript.records
        ]

        copied = await factory.fork_from(
            created.context.session_file,
            target_cwd="/copied-workspace",
            session_dir=tmp_path,
            persist=False,
        )
        assert copied.context.persist is False
        assert copied.context.header.parent_conversation_id == "source-session"
        assert copied.context.header.metadata["parentSession"] == str(
            created.context.session_file
        )
        assert len(copied.transcript.records) == 1

        await created.dispose()
        await restored.dispose()
        await forked.dispose()
        await copied.dispose()
        assert disposed == [
            "memory",
            "persistent",
            "persistent",
            "persistent",
            "memory",
        ]

    asyncio.run(scenario())


def test_session_factory_validates_explicit_session_identity_before_binding(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        bindings: list[bool] = []

        async def bind_runtime(context, binding: str):
            del context, binding
            raise AssertionError("invalid ids must not acquire a runtime binding")

        factory = AgentTranscriptSessionFactory(
            lifecycle=AgentTranscriptLifecycle(bind_runtime=bind_runtime),
            resolve_binding_input=lambda persist: bindings.append(persist) or "binding",
            header_metadata=lambda binding: {},
        )

        try:
            await factory.new(
                session_dir=tmp_path,
                cwd="/workspace",
                session_id=" ",
            )
        except ValueError as error:
            assert str(error) == "session_id must not be blank"
        else:
            raise AssertionError("expected a blank session id to fail")
        assert bindings == []

    asyncio.run(scenario())
