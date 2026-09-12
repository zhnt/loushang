"""Real G14 Product composition; only the model response and tool set are synthetic."""

from __future__ import annotations

import asyncio
import faulthandler
import os

from _hosted_boundary_trace import emit, install, text_shape

from loushang.agent import synthetic_model_transport
from loushang.agent.types import AgentToolResult
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage
from loushang.coding.cli.hosted import (
    CodingHostedCommandV1,
    execute_hosted_command,
    parse_launch,
)
from loushang.coding.session.agent_session import AgentSession
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    CallableToolActionAdapter,
    PreparedToolAction,
)

install()


async def _preview(action, context):
    return AgentToolResult(
        content=[TextPart(type="text", text="APPROVED_PREVIEW_EXECUTED")],
        details={},
    )


def _preview_tool() -> ToolDefinition:
    return ToolDefinition(
        name="g14_preview",
        label="Safe preview",
        description="Return an in-memory preview",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=AuthorizedExecution(
            action_adapter=CallableToolActionAdapter(
                lambda call, context: PreparedToolAction(
                    tool_name=call.name,
                    authorization_arguments=call.arguments,
                    execution_arguments=call.arguments,
                    cwd=context.cwd,
                )
            ),
            handler=_preview,
        ),
    )


@synthetic_model_transport
async def scripted_stream(model, context, options=None):
    latest = context.messages[-1]
    latest_text = (
        latest.content
        if isinstance(latest.content, str)
        else "".join(
            part.text for part in latest.content if isinstance(part, TextPart)
        )
    )
    user_text = latest_text if latest.role == "user" else ""
    text = "waiting" if user_text == "hold" else "真实跨进程回复\nG14"
    emit("model_input", roles=[message.role for message in context.messages[-8:]],
         message_count=len(context.messages), latest=text_shape(latest_text),
         latest_role=latest.role)
    if latest.role == "toolResult":
        text = "".join(
            part.text for part in latest.content if isinstance(part, TextPart)
        )
    message = AssistantMessage(
        endpoint="anthropic-messages",
        role="assistant",
        content=(
            [
                ToolCall(
                    type="toolCall", id="preview-1", name="g14_preview", arguments={}
                )
            ]
            if user_text == "approval"
            else [TextPart(type="text", text=text)]
        ),
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=Usage(
            input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}
        ),
        stop_reason="toolUse" if user_text == "approval" else "stop",
        error_message=None,
        timestamp=0.0,
    )
    stream = AssistantMessageEventStream()
    stream.push({"type": "start", "partial": message})
    if user_text != "approval":
        stream.push(
            {
                "type": "text_delta",
                "content_index": 0,
                "delta": text,
                "partial": message,
            }
        )
    if user_text == "hold":
        # Use the same public stream producer ownership as real providers.
        # Interrupt/EOF must cancel and settle this genuinely pending producer.
        async def parked_producer():
            try:
                await asyncio.Event().wait()
            finally:
                emit("producer_settled")

        stream.attach_task(asyncio.create_task(parked_producer()))
    else:
        stream.push({"type": "done", "reason": message.stop_reason, "message": message})
    return stream


if __name__ == "__main__":
    # Preserve the child's native thread stacks if a platform-specific block
    # prevents even asyncio deadlines from running. Never enabled by production.
    # A watchdog exit is always a failed test, never graceful-close evidence.
    faulthandler.dump_traceback_later(30, exit=True)
    if os.environ.get("LOUSHANG_G14_TEST_FAIL_DISPOSE") == "1":

        async def fail_dispose(self):
            raise RuntimeError("private-disposal-sentinel")

        AgentSession.dispose = fail_dispose
    launch, _ = parse_launch()
    command = CodingHostedCommandV1(
        launch,
        model=Model(
            id="faux-model",
            name="Faux",
            provider="faux",
            endpoint="anthropic-messages",
            capabilities=Capabilities(
                input=("text",), context_window=128000, max_tokens=4096
            ),
        ),
        stream_fn=scripted_stream,
        tools=[_preview_tool()],
    )
    try:
        raise SystemExit(execute_hosted_command(command))
    finally:
        faulthandler.cancel_dump_traceback_later()
