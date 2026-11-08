"""Observation-only Host probes and synthetic streaming for manual GUI acceptance."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic

from loushang.agent import synthetic_model_transport
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.types import AssistantMessage, TextPart, Usage
from loushang.appservice.execution_registry import ExecutionRegistryV1
from loushang.coding.hosted_execution import CodingHostedExecutionSessionV1
from loushang.coding.hosted_session import CodingRealHostedSessionV1


def install(root, audit):
    original_init = CodingRealHostedSessionV1.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        audit("agent_created", session_id=self.identity.session_id, agent=id(self._session))

    CodingRealHostedSessionV1.__init__ = init
    original_finish = ExecutionRegistryV1._finish

    def finish(self, invocation, outcome):
        result = original_finish(self, invocation, outcome)
        audit("execution_terminal", execution_id=invocation.record.state.execution_id,
              status=invocation.record.state.status.value)
        return result

    ExecutionRegistryV1._finish = finish
    original_interrupt = ExecutionRegistryV1.interrupt

    def interrupt(self, binding, execution_id):
        result = original_interrupt(self, binding, execution_id)
        audit("interrupt", execution_id=execution_id, requested=result.state.interrupt_requested)
        return result

    ExecutionRegistryV1.interrupt = interrupt
    original_snapshot = CodingHostedExecutionSessionV1.snapshot_execution

    async def snapshot(self):
        result = await original_snapshot(self)
        audit("snapshot_read", session_id=self.identity.session_id,
              execution_id=result.observation.execution_id,
              status=result.observation.status.value if result.observation.status else None,
              draft=result.draft, records=[{"kind": r.kind.value, "text": r.text} for r in result.source.records])
        return result

    CodingHostedExecutionSessionV1.snapshot_execution = snapshot
    calls = 0

    @synthetic_model_transport
    async def stream(model, context, options=None):
        nonlocal calls
        calls += 1
        number = calls
        latest = context.messages[-1]
        text = latest.content if isinstance(latest.content, str) else "".join(
            part.text for part in latest.content if isinstance(part, TextPart))
        audit("model_entered", number=number, input=text)
        message = AssistantMessage(endpoint="anthropic-messages", role="assistant",
            content=[TextPart(type="text", text=f"GUI 验收 {number}：正在执行")],
            api="anthropic-messages", provider="faux", model="faux-model", response_id=None,
            usage=Usage(input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}),
            stop_reason="stop", error_message=None, timestamp=0.0)
        output = AssistantMessageEventStream()
        output.push({"type": "start", "partial": message})
        output.push({"type": "text_delta", "content_index": 0,
                     "delta": message.content[0].text, "partial": message})

        async def produce():
            deadline = monotonic() + 900
            try:
                while not (root / f"release-{number}").exists():
                    assert monotonic() < deadline, f"GUI gate {number} expired"
                    await asyncio.sleep(0.05)
                suffix = f"；GUI 验收 {number}：已完成"
                completed = replace(message, content=[TextPart(type="text", text=message.content[0].text + suffix)])
                output.push({"type": "text_delta", "content_index": 0, "delta": suffix, "partial": completed})
                audit("model_progressed", number=number)
                output.push({"type": "done", "reason": "stop", "message": completed})
                audit("model_returned", number=number)
            except asyncio.CancelledError:
                audit("model_cancelled", number=number)
                raise

        output.attach_task(asyncio.create_task(produce()))
        return output

    return stream
