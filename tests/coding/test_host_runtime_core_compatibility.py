from __future__ import annotations

import asyncio

from loushang.agent import Agent
from loushang.coding.session import RunState as CodingRunState
from loushang.coding.session.agent_session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.events.host import HostLifecycleEvent
from loushang.harness.runtime.execution import HostRuntime
from loushang.harness.runtime.input_queue import HostInputQueue
from loushang.harness.runtime.types import RunState
from loushang.harness.session import (
    AgentEventRouter,
    PromptController,
    QueueController,
    SessionRuntime,
)


def test_coding_host_records_share_harness_identity() -> None:
    assert CodingRunState is RunState


def test_coding_queue_adapter_uses_harness_mechanism() -> None:
    controller = QueueController(
        agent=Agent(),
        preflight_user_input=lambda text: object(),
        reject_extension_command=lambda text: None,
        emit_queue_update=lambda: None,
    )

    assert isinstance(controller._queue, HostInputQueue)


def test_agent_session_coordinates_public_lifecycle_through_host_runtime(
    tmp_path,
) -> None:
    async def scenario() -> None:
        agent = Agent()
        started = asyncio.Event()
        release = asyncio.Event()
        abort_calls = 0
        wait_calls = 0

        async def prompt(_input, images=None) -> None:
            del images
            started.set()
            await release.wait()

        def abort() -> None:
            nonlocal abort_calls
            abort_calls += 1
            release.set()

        async def wait_for_idle() -> None:
            nonlocal wait_calls
            wait_calls += 1

        agent.prompt = prompt  # type: ignore[method-assign]
        agent.abort = abort  # type: ignore[method-assign]
        agent.wait_for_idle = wait_for_idle  # type: ignore[method-assign]
        session = AgentSession(
            agent=agent,
            session_manager=await SessionManager.new(
                session_dir=tmp_path,
                cwd=tmp_path,
                persist=False,
            ),
        )
        runtime = session._composition.session_runtime
        assert isinstance(runtime, SessionRuntime)
        assert isinstance(runtime.queue, QueueController)
        assert isinstance(runtime.prompt_controller, PromptController)
        assert isinstance(runtime.agent_event_router, AgentEventRouter)
        host_events: list[HostLifecycleEvent] = []
        runtime.host_runtime.subscribe(host_events.append)

        task = asyncio.create_task(session.prompt("prepare reference output"))
        await started.wait()

        assert isinstance(runtime.host_runtime, HostRuntime)
        assert session.get_state().run == RunState(status="running")
        session.abort()
        await task
        await session.wait_for_idle()

        assert abort_calls == 1
        assert wait_calls == 1
        assert session.get_state().run == RunState(status="idle")
        assert [event.kind for event in host_events[:3]] == [
            "run_started",
            "abort_requested",
            "run_aborted",
        ]

        await session.dispose()
        assert runtime.host_runtime.is_disposed is True

    asyncio.run(scenario())
