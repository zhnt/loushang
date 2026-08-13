from __future__ import annotations

import asyncio

from loushang.agent import Agent
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.coding.session import AgentSession
from loushang.coding.session_manager import SessionManager
from loushang.harness.scenario import (
    AgentSessionWorkflowAdapter,
    PromptStep,
    StepExpectation,
    Workflow,
    run_workflow,
)


def _assistant_message(text: str) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[TextPart(type="text", text=text)],
        api="test-api",
        provider="test-provider",
        model="test-model",
        response_id=None,
        usage=Usage(
            input=0,
            output=0,
            cache_read=0,
            cache_write=0,
            total_tokens=0,
            cost={},
        ),
        stop_reason="stop",
        error_message=None,
        timestamp=0.0,
    )


def _completed_stream(message: AssistantMessage) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def feed() -> None:
        stream.push({"type": "start", "partial": message})
        stream.push({"type": "done", "reason": "stop", "message": message})  # type: ignore[typeddict-item]

    asyncio.create_task(feed())
    return stream


def test_coding_agent_session_drives_scenario_through_runtime_events(tmp_path) -> None:
    async def scenario() -> tuple[object, tuple[str, ...], list[str]]:
        async def stream_fn(model, context, options=None):
            del model, context, options
            return _completed_stream(_assistant_message("scenario complete"))

        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            persist=False,
        )
        session = AgentSession(
            agent=Agent(stream_fn=stream_fn),
            session_manager=manager,
        )
        runtime_kinds: list[str] = []
        session.subscribe_runtime_events(lambda event: runtime_kinds.append(event.kind))
        adapter = AgentSessionWorkflowAdapter(session)
        workflow = Workflow(
            name="coding runtime contract",
            steps=(
                PromptStep(
                    prompt="finish this",
                    expect=StepExpectation(assistant_contains=("scenario complete",)),
                ),
            ),
        )

        result = await run_workflow(workflow, adapter=adapter, cwd=tmp_path)
        return result, tuple(event.type for event in adapter.events()), runtime_kinds

    result, scenario_event_types, runtime_kinds = asyncio.run(scenario())

    assert result.ok is True
    assert scenario_event_types == (
        "run.started",
        "assistant.message",
        "run.ended",
    )
    assert "agent.message_end" in runtime_kinds
