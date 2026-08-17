from __future__ import annotations

import asyncio

from loushang.ai.types import TextPart, ToolResultMessage
from loushang.harness.extensions.agent import ExtensionAgentEventRuntime


def test_extension_event_sink_mirrors_lifecycle_events_with_turn_index() -> None:
    assistant = type("Assistant", (), {"role": "assistant"})()
    tool_result = ToolResultMessage(
        role="toolResult",
        tool_call_id="tc1",
        tool_name="bash",
        content=[TextPart(type="text", text="ok")],
        is_error=False,
        timestamp=0.0,
    )
    emitted: list[tuple[object, str]] = []

    class Runner:
        async def emit_agent_event(self, event, *, cwd: str = "") -> None:
            emitted.append((event, cwd))

    sink = ExtensionAgentEventRuntime(
        get_extension_runtime=lambda: Runner(),
        get_cwd=lambda: "/tmp/project",
        clock=lambda: 123.456,
    )

    async def scenario() -> None:
        await sink.emit_agent_event({"type": "agent_start"})
        await sink.emit_agent_event({"type": "turn_start"})
        await sink.emit_agent_event(
            {"type": "turn_end", "message": assistant, "tool_results": [tool_result]}
        )
        await sink.emit_agent_event({"type": "turn_start"})

    asyncio.run(scenario())

    assert emitted == [
        ({"type": "agent_start"}, "/tmp/project"),
        (
            {
                "type": "turn_start",
                "turn_index": 0,
                "timestamp": 123456,
            },
            "/tmp/project",
        ),
        (
            {
                "type": "turn_end",
                "turn_index": 0,
                "message": assistant,
                "tool_results": [tool_result],
            },
            "/tmp/project",
        ),
        (
            {
                "type": "turn_start",
                "turn_index": 1,
                "timestamp": 123456,
            },
            "/tmp/project",
        ),
    ]
