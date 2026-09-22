"""Side-effect-free fixed Product components for managed first-use evidence.

No tracing installation, environment selection, IO or production monkeypatching
happens on import. The dedicated test child supplies a bounded witness sink.
Witnesses are test observations, never authorization or lifecycle authority.
"""

from __future__ import annotations

import asyncio
import re
import runpy
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import replace
from functools import partial
from pathlib import Path

from loushang.agent import synthetic_model_transport
from loushang.agent.types import AgentToolResult
from loushang.ai.event_stream.stream import AssistantMessageEventStream
from loushang.ai.model import Capabilities, Model
from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    CallableToolActionAdapter,
    PreparedToolAction,
)


def components(witness: Callable[[str, str], None], *, completion_gate: Callable[[str], Awaitable[None]] | None = None):
    """Select only synthetic model/tool behavior, retaining real authorization."""
    calls = 0
    history_turn = None

    async def execute(action, context):
        witness("tool_executed", context.tool_call_id)
        return AgentToolResult(
            content=[TextPart(type="text", text="LMUX_TOOL_COMPLETED")], details={},
        )

    tool = ToolDefinition(
        name="lmux_evidence", label="Managed evidence", description="In-memory test effect",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=AuthorizedExecution(
            action_adapter=CallableToolActionAdapter(
                lambda call, context: PreparedToolAction(
                    tool_name=call.name, authorization_arguments=call.arguments,
                    execution_arguments=call.arguments, cwd=context.cwd,
                )
            ),
            handler=execute,
        ),
    )
    model = Model(
        id="lmux-fixed", name="LMUX fixed", provider="faux", endpoint="anthropic-messages",
        capabilities=Capabilities(input=("text",), context_window=128000, max_tokens=4096),
    )

    @synthetic_model_transport
    async def stream(model, context, options=None):
        nonlocal calls, history_turn
        calls += 1
        identity = f"lmux-call-{calls}"
        latest = context.messages[-1]
        content = latest.content
        text = content if isinstance(content, str) else "".join(
            part.text for part in content if isinstance(part, TextPart)
        )
        request = text if latest.role == "user" else ""
        use_tool = request == "approval"
        reply = text if latest.role == "toolResult" else "LMUX_REPLY_COMPLETED"
        unique = re.fullmatch(r"(reply|delayed|gated) ([0-9a-f]{32})", request)
        gated = unique is not None and unique.group(1) == "gated"
        if gated and completion_gate is None:
            raise ValueError("gated test request requires an explicit completion gate")
        if unique is not None:
            reply = "LMUX_REPLY_" + unique.group(2)
        history = re.fullmatch(r"history ([0-9]{4})", request)
        if history is not None:
            if history_turn is None:
                # The installed child loads this fixed sibling with run_path,
                # so it has no package context for a relative import.
                history_turn = runpy.run_path(
                    str(Path(__file__).with_name("_lmux_history_recipe.py"))
                )["history_turn"]
            _, reply = history_turn(int(history.group(1)))
        parked = request == "hold" or (unique is not None and unique.group(1) in {"delayed", "gated"})
        if request == "hold":
            reply = "LMUX_WAITING"
        message = AssistantMessage(
            endpoint="anthropic-messages", role="assistant",
            content=[ToolCall(type="toolCall", id=identity, name=tool.name, arguments={})]
            if use_tool else [TextPart(type="text", text=reply)],
            api="anthropic-messages", provider="faux", model="lmux-fixed", response_id=None,
            usage=Usage(input=0, output=0, cache_read=0, cache_write=0, total_tokens=0, cost={}),
            stop_reason="toolUse" if use_tool else "stop", error_message=None, timestamp=0.0,
        )
        result = AssistantMessageEventStream()
        result.push({"type": "start", "partial": message})
        if not use_tool:
            result.push({"type": "text_delta", "content_index": 0, "delta": reply, "partial": message})
        if parked:
            async def producer():
                try:
                    witness("producer_started", identity)
                    if gated:
                        assert completion_gate is not None and unique is not None
                        await completion_gate(unique.group(2))
                        witness("gate_released", identity)
                        result.push({"type": "done", "reason": message.stop_reason, "message": message})
                        witness("final_emitted", identity)
                    else:
                        await asyncio.Event().wait()
                finally:
                    witness("producer_settled", identity)

            # A foreign task factory may schedule and then raise, losing the
            # handle before stream adoption. Keep this test producer owned.
            task = asyncio.Task(producer(), loop=asyncio.get_running_loop())
            result.attach_task(task)
        else:
            result.push({"type": "done", "reason": message.stop_reason, "message": message})
        return result

    return model, stream, [tool]


def run_product(argv: list[str], witness: Callable[[str, str], None], *, admission_diagnostic=None, completion_gate=None) -> int:
    """Dedicated-test-process composition; production main owns all lifecycle.

    Not a public launcher: the future fixed child must verify installed origins
    and supply its own bounded witness sink. Never call concurrently in-process.
    """
    from loushang.coding import managed_local, managed_process

    original = managed_local.CodingManagedLocalCommandV1
    model, stream, tools = components(witness, completion_gate=completion_gate)
    constructor = original
    startup_observation = nullcontext()
    if admission_diagnostic is not None:
        diagnostic = runpy.run_path(str(Path(__file__).with_name("_lmux_admission_diagnostic.py")))
        trace = diagnostic["AdmissionTrace"](admission_diagnostic)
        startup = runpy.run_path(str(Path(__file__).with_name("_lmux_startup_diagnostic.py")))
        startup_observation = startup["observe_startup"](managed_process.ManagedChildBootstrapV1, admission_diagnostic)

        def constructor(launch, **kwargs):
            if launch.managed_mux is None:
                raise ValueError("diagnostic requires original managed binding")
            observed = diagnostic["observe_binding"](launch.managed_mux, trace)
            return original(replace(launch, managed_mux=observed), **kwargs)

    try:
        managed_local.CodingManagedLocalCommandV1 = partial(
            constructor, model=model, stream_fn=stream, tools=tools,
        )
        with startup_observation:
            return managed_process.main(argv)
    finally:
        managed_local.CodingManagedLocalCommandV1 = original
