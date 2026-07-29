from __future__ import annotations

from loushang.harness.tools.execution import direct_execution


def test_wrap_tool_definition_exposes_agent_tool_contract() -> None:
    import asyncio

    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.tools.core import ToolDefinition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    calls: list[dict[str, object]] = []

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del signal, on_update
        calls.append({"tool_call_id": tool_call_id, "params": params})
        return AgentToolResult(
            content=[TextPart(type="text", text="ok")], details={"seen": True}
        )

    definition = ToolDefinition(
        name="demo",
        label="Demo",
        description="Demo tool",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        prepare_arguments=lambda raw: {"normalized": raw},
        execution=direct_execution(execute),
    )

    tool = wrap_tool_definition(definition)
    result = asyncio.run(tool.execute("call-1", {"normalized": {"raw": 1}}))

    assert tool.name == "demo"
    assert tool.label == "Demo"
    assert tool.execution_mode == "parallel"
    assert tool.parameters["type"] == "object"
    assert result.details == {"seen": True}
    assert calls == [{"tool_call_id": "call-1", "params": {"normalized": {"raw": 1}}}]


def test_wrap_tool_definition_exposes_custom_execution_mode() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.tools.core import ToolDefinition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    definition = ToolDefinition(
        name="sequential_demo",
        label="Sequential Demo",
        description="Sequential demo tool",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        execution_mode="sequential",
    )

    assert wrap_tool_definition(definition).execution_mode == "sequential"


def test_wrap_tool_definition_preserves_tool_renderers() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.tools.core import (
        ToolDefinition,
        ToolRenderContext,
        ToolRenderResultOptions,
    )
    from loushang.harness.tools.workspace.wrapper import (
        create_tool_definition_from_tool,
        wrap_tool_definition,
    )

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_call(args, theme, context: ToolRenderContext):
        return {"text": f"call {args['path']} {theme['accent']} {context.tool_call_id}"}

    def render_result(
        result, options: ToolRenderResultOptions, theme, context: ToolRenderContext
    ):
        del result, theme
        return {
            "text": f"result expanded={options.expanded} partial={context.is_partial}"
        }

    definition = ToolDefinition(
        name="read",
        label="Read",
        description="Read files",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_call=render_call,
        render_result=render_result,
    )

    wrapped = wrap_tool_definition(definition)
    round_tripped = create_tool_definition_from_tool(wrapped)

    assert wrapped.render_call is render_call
    assert wrapped.renderCall is render_call
    assert wrapped.render_result is render_result
    assert wrapped.renderResult is render_result
    assert round_tripped.render_call is render_call
    assert round_tripped.render_result is render_result
