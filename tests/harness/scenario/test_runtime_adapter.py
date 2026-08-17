from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from loushang.harness.events import RuntimeEvent
from loushang.harness.scenario import (
    AgentSessionWorkflowAdapter,
    PromptStep,
    Workflow,
    run_workflow,
)


def test_agent_session_adapter_observes_common_runtime_events(tmp_path) -> None:
    class RuntimeSession:
        def __init__(self) -> None:
            self.messages: list[object] = []
            self.listeners = []

        def subscribe_runtime_events(self, listener):
            self.listeners.append(listener)
            return lambda: self.listeners.remove(listener)

        async def prompt(self, text: str) -> None:
            user = SimpleNamespace(role="user", content=text)
            assistant = SimpleNamespace(role="assistant", content="done")
            self.messages.extend((user, assistant))
            event = RuntimeEvent(
                event_id="event-1",
                kind="agent.message_end",
                stream_id="session:demo",
                sequence=1,
                occurred_at=datetime(2026, 7, 16, tzinfo=UTC),
                payload={"type": "message_end", "message": assistant},
                session_id="demo",
            )
            for listener in list(self.listeners):
                result = listener(event)
                if asyncio.iscoroutine(result):
                    await result

    adapter = AgentSessionWorkflowAdapter(RuntimeSession())

    result = asyncio.run(
        run_workflow(
            Workflow(name="runtime", steps=(PromptStep(prompt="hello"),)),
            adapter=adapter,
            cwd=tmp_path,
        )
    )

    assert result.ok is True
    assert result.step_results[0].assistant_text == "done"
    assert [event.type for event in result.events] == [
        "run.started",
        "assistant.message",
        "run.ended",
    ]
