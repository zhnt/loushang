from __future__ import annotations

import asyncio

from loushang.agent import Agent
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.transcript import ApplicationMessage


def test_agent_session_direct_application_input_reuses_one_commit_and_projection(
    tmp_path,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path,
            cwd=tmp_path,
            persist=False,
        )
        session = AgentSession(agent=Agent(), session_manager=manager)
        events: list[str] = []
        session.subscribe_runtime_events(lambda event: events.append(event.kind))
        message = ApplicationMessage(
            application_message_id="extension-direct-1",
            custom_type="notice",
            content="visible note",
            timestamp=0.0,
            origin="extension",
            delivery_mode="direct",
        )

        first = await session._composition.session_runtime.application_inputs.deliver(
            message
        )
        second = await session._composition.session_runtime.application_inputs.deliver(
            message
        )
        await asyncio.sleep(0)

        assert first.disposition == "committed"
        assert second.disposition == "already_committed"
        assert first.record_id == second.record_id
        assert [record.kind for record in manager.get_entries()] == [
            "application.message"
        ]
        assert [message.role for message in session.messages] == ["application"]
        assert events.count("agent.message_start") == 1
        assert events.count("agent.message_end") == 1

    asyncio.run(scenario())


def test_persistent_agent_session_maps_legacy_conversation_id_to_safe_authority(
    tmp_path,
) -> None:
    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "data" / "sessions",
            cwd=tmp_path,
            persist=True,
            session_id="legacy session",
        )

        session = AgentSession(agent=Agent(), session_manager=manager)

        assert manager.get_header().conversation_id == "legacy session"
        assert manager.get_session_file() is not None
        assert manager.get_session_file().parent == (tmp_path / "data" / "sessions")
        assert session._exec_service._store.session_id.startswith("legacy-")
        assert "/" not in session._exec_service._store.session_id
        await session.dispose()

    asyncio.run(scenario())
