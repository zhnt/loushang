from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from loushang.agent import Agent
from loushang.ai.types import TextPart
from loushang.coding.session_manager import SessionManager
from loushang.harness.extensions.agent import ExtensionInputRuntime
from loushang.harness.extensions.agent.input_adapter import ExtensionInputAdapter
from loushang.harness.session import (
    ApplicationInputRuntime,
    QueueController,
)


def _preflight(text: str):
    return SimpleNamespace(consumed=False, text=text)


def _queue_controller(
    agent: Agent, queue_updates: list[tuple[list[str], list[str]]]
) -> QueueController:
    controller = QueueController(
        agent=agent,
        preflight_user_input=_preflight,
        reject_extension_command=lambda text: None,
        emit_queue_update=lambda: queue_updates.append(
            (controller.get_steering_messages(), controller.get_follow_up_messages())
        ),
    )
    return controller


def _application_inputs(
    agent: Agent,
    session_manager: SessionManager,
    queue_controller: QueueController,
    dispatch,
) -> ApplicationInputRuntime:
    async def project_direct(message, record_id: str) -> None:
        agent.state.set_messages(session_manager.build_session_context().messages)
        await dispatch({"type": "message_start", "message": message})
        await dispatch(
            {"type": "message_end", "message": message},
            source_record_id=record_id,
        )

    async def run_trigger_turn(message) -> None:
        await agent.prompt(message)

    return ApplicationInputRuntime(
        commit_application_message=session_manager.commit_application_message,
        queue=queue_controller,
        project_direct=project_direct,
        run_trigger_turn=run_trigger_turn,
    )


def _controller(
    agent: Agent,
    queue_controller: QueueController,
    application_inputs: ApplicationInputRuntime,
) -> ExtensionInputAdapter:
    return ExtensionInputAdapter(
        agent=agent,
        runtime=ExtensionInputRuntime(
            application_inputs=application_inputs,
            prepared_user_inputs=queue_controller,
            run_prompt=agent.prompt,
        ),
    )


def test_extension_message_controller_persists_custom_message_and_emits_events(
    tmp_path,
) -> None:
    agent = Agent()
    queue_updates: list[tuple[list[str], list[str]]] = []
    events: list[tuple[str, str]] = []

    async def _dispatch(event, **_kwargs):
        events.append((event["type"], event["message"].custom_type))

    session_manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    queue_controller = _queue_controller(agent, queue_updates)
    controller = _controller(
        agent,
        queue_controller,
        _application_inputs(
            agent, session_manager, queue_controller, _dispatch
        ),
    )

    asyncio.run(
        controller.send_message(
            {
                "customType": "demo_notice",
                "content": "visible note",
                "display": True,
                "details": {"source": "sdk"},
            }
        )
    )

    assert [message.role for message in agent.state.messages] == ["application"]
    assert agent.state.messages[0].custom_type == "demo_notice"
    assert events == [("message_start", "demo_notice"), ("message_end", "demo_notice")]
    assert queue_updates == []


def test_extension_message_controller_queues_streaming_messages_by_deliver_as(
    tmp_path,
) -> None:
    agent = Agent()
    agent.state.is_streaming = True
    queue_updates: list[tuple[list[str], list[str]]] = []
    session_manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    queue_controller = _queue_controller(agent, queue_updates)
    controller = _controller(
        agent,
        queue_controller,
        _application_inputs(
            agent,
            session_manager,
            queue_controller,
            lambda event, **kwargs: _noop_dispatch(event, **kwargs),
        ),
    )

    asyncio.run(
        controller.send_message(
            {"customType": "note", "content": "custom follow"},
            {"deliverAs": "followUp"},
        )
    )
    asyncio.run(controller.send_user_message("queued steer", {"deliverAs": "steer"}))

    assert controller.has_pending_messages() is True
    assert queue_controller.get_steering_messages() == ["queued steer"]
    assert queue_controller.get_follow_up_messages() == ["custom follow"]
    assert queue_updates == [
        ([], ["custom follow"]),
        (["queued steer"], ["custom follow"]),
    ]


def test_extension_message_controller_validates_streaming_user_message_deliver_as(
    tmp_path,
) -> None:
    agent = Agent()
    agent.state.is_streaming = True
    queue_updates: list[tuple[list[str], list[str]]] = []
    session_manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    queue_controller = _queue_controller(agent, queue_updates)
    controller = _controller(
        agent,
        queue_controller,
        _application_inputs(
            agent,
            session_manager,
            queue_controller,
            lambda event, **kwargs: _noop_dispatch(event, **kwargs),
        ),
    )

    with pytest.raises(RuntimeError, match="Specify deliverAs"):
        asyncio.run(
            controller.send_user_message([TextPart(type="text", text="queued")])
        )


async def _noop_dispatch(_event, **_kwargs) -> None:
    return None
