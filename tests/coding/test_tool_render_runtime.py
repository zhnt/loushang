from __future__ import annotations

from loushang.harness.tools.execution import direct_execution


def test_tool_render_runtime_preserves_state_and_last_rendered_per_tool_call() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.presentation import ToolRenderRuntime
    from loushang.harness.tools.workspace import ToolDefinition

    invalidated: list[str] = []
    observations: list[tuple[str, object | None, bool, bool, int]] = []

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_call(args, theme, context):
        del theme
        calls = context.state.setdefault("calls", 0) + 1
        context.state["calls"] = calls
        observations.append(
            (
                "call",
                context.last_rendered,
                context.execution_started,
                context.args_complete,
                calls,
            )
        )
        context.invalidate()
        return {"text": f"call-{calls}-{args['path']}"}

    def render_result(result, options, theme, context):
        del result, theme
        calls = int(context.state["calls"])
        observations.append(
            (
                "result",
                context.last_rendered,
                context.is_partial,
                options.expanded,
                calls,
            )
        )
        return {"text": f"result-{calls}-{options.expanded}"}

    definition = ToolDefinition(
        name="read",
        label="Read",
        description="Read files",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_call=render_call,
        render_result=render_result,
    )
    runtime = ToolRenderRuntime(
        cwd="/repo", theme={"accent": "blue"}, on_invalidate=invalidated.append
    )

    first_call = runtime.render_call(
        definition,
        "call-1",
        {"path": "README.md"},
        execution_started=False,
        args_complete=False,
    )
    second_call = runtime.render_call(definition, "call-1", {"path": "README.md"})
    first_result = runtime.render_result(
        definition,
        "call-1",
        AgentToolResult(content=[TextPart(type="text", text="partial")], details={}),
        is_partial=True,
    )
    second_result = runtime.render_result(
        definition,
        "call-1",
        AgentToolResult(content=[TextPart(type="text", text="final")], details={}),
        expanded=True,
    )

    assert first_call == {"text": "call-1-README.md"}
    assert second_call == {"text": "call-2-README.md"}
    assert first_result == {"text": "result-2-False"}
    assert second_result == {"text": "result-2-True"}
    assert invalidated == ["call-1", "call-1"]
    assert observations == [
        ("call", None, False, False, 1),
        ("call", first_call, True, True, 2),
        ("result", None, True, False, 2),
        ("result", first_result, False, True, 2),
    ]


def test_tool_render_runtime_keeps_renderer_state_isolated_by_tool_call_id() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.presentation import ToolRenderRuntime
    from loushang.harness.tools.workspace import ToolDefinition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_call(args, theme, context):
        del args, theme
        context.state["count"] = context.state.get("count", 0) + 1
        return {"text": f"{context.tool_call_id}:{context.state['count']}"}

    definition = ToolDefinition(
        name="demo",
        label="Demo",
        description="Demo",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        execution=direct_execution(execute),
        render_call=render_call,
    )
    runtime = ToolRenderRuntime()

    assert runtime.render_call(definition, "call-1", {}) == {"text": "call-1:1"}
    assert runtime.render_call(definition, "call-2", {}) == {"text": "call-2:1"}
    assert runtime.render_call(definition, "call-1", {}) == {"text": "call-1:2"}


def test_tool_render_runtime_renders_tool_execution_events_with_partial_flags() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.presentation import ToolRenderRuntime
    from loushang.harness.tools.workspace import ToolDefinition

    observations: list[tuple[str, object | None, bool, bool, bool, object | None]] = []

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[TextPart(type="text", text="ok")], details={})

    def render_call(args, theme, context):
        del theme
        context.state["path"] = args["path"]
        observations.append(
            (
                "call",
                context.last_rendered,
                context.is_partial,
                context.expanded,
                context.is_error,
                context.args,
            )
        )
        return {"text": f"call {args['path']}"}

    def render_result(result, options, theme, context):
        del theme
        observations.append(
            (
                result.content[0].text,
                context.last_rendered,
                context.is_partial,
                options.expanded,
                context.is_error,
                context.args,
            )
        )
        return {
            "text": f"{context.state['path']} {result.content[0].text} partial={options.is_partial}"
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
    runtime = ToolRenderRuntime()

    def resolver(name):
        return definition if name == "read" else None

    start = runtime.render_event(
        {
            "type": "tool_execution_start",
            "tool_call_id": "call-1",
            "tool_name": "read",
            "args": {"path": "README.md"},
        },
        resolver,
    )
    partial = runtime.render_event(
        {
            "type": "tool_execution_update",
            "tool_call_id": "call-1",
            "tool_name": "read",
            "args": {"path": "README.md"},
            "partial_result": AgentToolResult(
                content=[TextPart(type="text", text="partial")], details={}
            ),
        },
        resolver,
    )
    final = runtime.render_event(
        {
            "type": "tool_execution_end",
            "tool_call_id": "call-1",
            "tool_name": "read",
            "result": AgentToolResult(
                content=[TextPart(type="text", text="final")], details={}
            ),
            "is_error": True,
        },
        resolver,
        expanded=True,
    )

    assert start == {"text": "call README.md"}
    assert partial == {"text": "README.md partial partial=True"}
    assert final == {"text": "README.md final partial=False"}
    assert observations == [
        ("call", None, True, False, False, {"path": "README.md"}),
        ("partial", None, True, False, False, {"path": "README.md"}),
        ("final", partial, False, True, True, {"path": "README.md"}),
    ]


def test_tool_render_runtime_ignores_non_renderable_tool_events() -> None:
    from loushang.harness.presentation import ToolRenderRuntime

    runtime = ToolRenderRuntime()

    def resolver(name):
        del name
        return None

    assert runtime.render_event({"type": "message_start"}, resolver) is None
    assert (
        runtime.render_event(
            {
                "type": "tool_execution_start",
                "tool_call_id": "call-1",
                "tool_name": "missing",
            },
            resolver,
        )
        is None
    )
