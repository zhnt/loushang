from __future__ import annotations

import asyncio
from pathlib import Path

from loushang.ai.types import UserMessage
from loushang.harness.conversation import ConversationKey, MemoryConversationStore
from loushang.harness.transcript import (
    AgentTranscriptFileLayout,
    AgentTranscriptLifecycle,
    AgentTranscriptProfile,
    AgentTranscriptRuntimeBinding,
    AgentTranscriptSessionFactory,
    ProductTranscriptSession,
    create_agent_transcript_file_store,
)


class _ExampleProductSession(ProductTranscriptSession[str, str]):
    _factory: AgentTranscriptSessionFactory[str, str]

    @classmethod
    def _session_factory(cls) -> AgentTranscriptSessionFactory[str, str]:
        return cls._factory

    def _fork_binding_input(self) -> str:
        return self._lifecycle_session.product_binding


def test_product_transcript_session_owns_standard_session_operations(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        disposed: list[str] = []

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
        _ExampleProductSession._factory = AgentTranscriptSessionFactory(
            lifecycle=lifecycle,
            resolve_binding_input=lambda persist: "persistent" if persist else "memory",
            header_metadata=lambda binding: {"productBinding": binding},
            session_file_factory=lifecycle.default_jsonl_session_file,
        )

        session = await _ExampleProductSession.new(
            session_dir=tmp_path,
            cwd="/workspace",
            session_id="example-session",
        )
        await session.append_message(
            UserMessage(role="user", content="hello", timestamp=1.0)
        )
        await session.append_session_info("Example")

        assert session.get_session_record().session_id == "example-session"
        assert session.get_session_summary().name == "Example"
        assert session.build_session_context().messages[0].content == "hello"
        assert [
            record.session_id for record in _ExampleProductSession.list(tmp_path)
        ] == ["example-session"]

        _ExampleProductSession.refresh_index(tmp_path)
        assert _ExampleProductSession.load_index(tmp_path)[0].name == "Example"

        forked = await session.fork(session.get_leaf_id() or "")
        assert forked.get_session_record().parent_session == str(session.session_file)
        assert forked.get_session_summary().message_count == 1

        await _ExampleProductSession.rename_session(
            session.session_file or tmp_path, "Renamed"
        )
        summaries_by_id = {
            summary.session_id: summary
            for summary in _ExampleProductSession.list_summaries(tmp_path)
        }
        assert summaries_by_id["example-session"].name == "Renamed"

        await session.dispose_runtime_profile()
        await forked.dispose_runtime_profile()
        assert disposed == ["persistent", "persistent", "persistent"]

    asyncio.run(scenario())


def test_product_transcript_session_discards_provisional_authority(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async def bind_runtime(context, binding: str):
            layout = AgentTranscriptFileLayout(context.session_dir)
            key = layout.key(context.header.conversation_id)
            assert context.session_file is not None
            layout.bind_create_path(key, context.session_file)

            async def dispose() -> None:
                return None

            return AgentTranscriptRuntimeBinding(
                store=create_agent_transcript_file_store(layout),
                key=key,
                profile=AgentTranscriptProfile.default(),
                product_binding=binding,
                dispose=dispose,
            )

        lifecycle = AgentTranscriptLifecycle(bind_runtime=bind_runtime)
        _ExampleProductSession._factory = AgentTranscriptSessionFactory(
            lifecycle=lifecycle,
            resolve_binding_input=lambda persist: "persistent",
            header_metadata=lambda binding: {"productBinding": binding},
            session_file_factory=lifecycle.default_jsonl_session_file,
        )
        session = await _ExampleProductSession.new(
            session_dir=tmp_path,
            cwd="/workspace",
            session_id="provisional",
        )
        planned_path = session.session_file

        assert planned_path is not None
        assert session.is_persisted() is False
        assert session.get_session_file() == planned_path
        assert not planned_path.exists()

        await session.dispose_runtime_profile()

        assert not planned_path.exists()
        assert list(tmp_path.glob("*.jsonl")) == []

    asyncio.run(scenario())
