from __future__ import annotations

from typing import TYPE_CHECKING

from loushang.harness.types import AgentRunResult, AgentRunSpec

if TYPE_CHECKING:
    from loushang.agent.types import AgentEvent, AgentMessage


async def run_agent(spec: AgentRunSpec) -> AgentRunResult:
    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)
        if spec.event_sink is not None:
            result = spec.event_sink(event)
            if result is not None:
                await result

    from loushang.agent.agent_loop import run_agent_loop, run_agent_loop_continue

    try:
        if spec.mode == "continue":
            new_messages = await run_agent_loop_continue(
                spec.context,
                spec.config,
                emit,
                signal=spec.signal,
                stream_fn=spec.stream_fn,
            )
        else:
            new_messages = await run_agent_loop(
                list(spec.prompts),
                spec.context,
                spec.config,
                emit,
                signal=spec.signal,
                stream_fn=spec.stream_fn,
            )
    except Exception as error:
        return AgentRunResult(status="failed", events=tuple(events), error=error)

    return AgentRunResult(
        status="completed",
        new_messages=tuple(new_messages),
        events=tuple(events),
        stop_reason=_stop_reason(new_messages),
    )


def _stop_reason(messages: list[AgentMessage]) -> str | None:
    for message in reversed(messages):
        stop_reason = getattr(message, "stop_reason", None)
        if isinstance(stop_reason, str):
            return stop_reason
    return None
