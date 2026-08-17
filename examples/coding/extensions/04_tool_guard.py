from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.harness.tools.execution import direct_execution

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    assistant_text_message,
    assistant_tool_call_message,
    build_runtime,
    latest_tool_results,
    latest_user_text,
    print_messages,
    stream_with_final_message,
)

from loushang.agent.types import AgentToolResult
from loushang.ai.types import TextPart
from loushang.harness.tools.core import ToolDefinition

EXTENSION_SOURCE = """
from loushang.agent.types import AgentToolResult
from loushang.ai.types import TextPart
from loushang.harness.extensions.agent import ToolCallDecision, ToolResultDecision
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution


async def _guarded_execute(tool_call_id, params, signal=None, on_update=None):
    return AgentToolResult(
        content=[TextPart(type="text", text=str(params["value"] * 10))],
        details={"guarded_value": params["value"] * 10},
    )


def register(api):
    def _tool_call(event, ctx):
        value = event.args["value"]
        if value > 10:
            return ToolCallDecision(block=True, reason="guard blocked values above 10")
        return ToolCallDecision(
            tool_name="guarded_calculate",
            arguments={"value": value + 1},
        )

    def _tool_result(event, ctx):
        return ToolResultDecision(
            result=AgentToolResult(
                content=[TextPart(type="text", text=f"guarded result: {event.result.content[0].text}")],
                details={"wrapped": True, "original_details": event.result.details},
            )
        )

    api.on("tool_call", _tool_call)
    api.on("tool_result", _tool_result)
    api.register_tool(
        ToolDefinition(
            name="guarded_calculate",
            label="Guarded Calculate",
            description="Extension-managed calculation target.",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            execution=direct_execution(_guarded_execute),
        )
    )
"""


async def _base_calculate(tool_call_id: str, params: dict[str, object], signal=None, on_update=None):
    return AgentToolResult(
        content=[TextPart(type="text", text=f"base result: {params['value']}")],
        details={"base_value": params["value"]},
    )


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-ext-guard-") as tmpdir:
        project_root = Path(tmpdir)
        extensions_dir = project_root / "extensions"
        extensions_dir.mkdir(parents=True)
        extension_file = extensions_dir / "tool_guard.py"
        extension_file.write_text(EXTENSION_SOURCE.strip() + "\n", encoding="utf-8")

        async def stream_fn(model, context, options=None):
            last_message = context.messages[-1] if context.messages else None
            if getattr(last_message, "role", None) == "toolResult":
                return stream_with_final_message(assistant_text_message("Guard example finished this turn."))
            user_text = latest_user_text(context.messages)
            if "blocked" in user_text:
                return stream_with_final_message(assistant_tool_call_message("calculate", {"value": 11}))
            return stream_with_final_message(assistant_tool_call_message("calculate", {"value": 2}))

        runtime = build_runtime(
            session_dir=project_root / ".loushang-sessions",
            stream_fn=stream_fn,
            system_prompt="Tool guard extension example.",
            tools=[
                ToolDefinition(
                    name="calculate",
                    label="Calculate",
                    description="Base calculation tool that the extension can intercept.",
                    parameters={
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                    execution=direct_execution(_base_calculate),
                )
            ],
        )
        session = await runtime.create_session(cwd=str(project_root))

        print("=== Extension Example: Tool Guard ===")
        print(f"Project root: {project_root}")
        print(f"Extension file: {extension_file}")
        print(f"Active tools: {', '.join(session.get_active_tool_names())}")
        print()

        print("Allowed request:")
        await session.prompt("Run the allowed calculation flow.")
        allowed_result = latest_tool_results(session)[-1]
        print(f"- tool_name: {allowed_result.tool_name}")
        print(f"- text: {allowed_result.content[0].text}")
        print(f"- details: {allowed_result.details}")
        print()

        print("Blocked request:")
        await session.prompt("Run the blocked calculation flow.")
        blocked_result = latest_tool_results(session)[-1]
        print(f"- tool_name: {blocked_result.tool_name}")
        print(f"- text: {blocked_result.content[0].text}")
        print(f"- is_error: {blocked_result.is_error}")
        print()

        print("Messages:")
        print_messages(session)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
