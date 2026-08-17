from __future__ import annotations

from loushang.harness.tools.execution import direct_execution


def test_emit_tool_update_accepts_sync_and_async_callbacks() -> None:
    import asyncio

    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.tools.workspace.runtime import emit_tool_update

    seen: list[str] = []

    async def async_callback(result):
        seen.append(f"async:{result.content[0].text}")

    def sync_callback(result):
        seen.append(f"sync:{result.content[0].text}")

    async def scenario() -> None:
        await emit_tool_update(
            sync_callback,
            AgentToolResult(content=[TextPart(type="text", text="one")], details={}),
        )
        await emit_tool_update(
            async_callback,
            AgentToolResult(content=[TextPart(type="text", text="two")], details={}),
        )
        await emit_tool_update(
            None,
            AgentToolResult(
                content=[TextPart(type="text", text="ignored")], details={}
            ),
        )

    asyncio.run(scenario())

    assert seen == ["sync:one", "async:two"]


def test_resolve_maybe_awaitable_accepts_plain_and_async_values() -> None:
    import asyncio

    from loushang.harness.tools.workspace import MaybeAwaitable, resolve_maybe_awaitable

    async def async_value() -> str:
        return "async"

    async def scenario() -> None:
        plain: MaybeAwaitable[str] = "plain"
        assert await resolve_maybe_awaitable(plain) == "plain"
        assert await resolve_maybe_awaitable(async_value()) == "async"

    asyncio.run(scenario())


def test_prepare_tool_arguments_rejects_conflicting_alias_values() -> None:
    import pytest

    from loushang.harness.tools.workspace import prepare_tool_arguments

    assert prepare_tool_arguments(
        {"path": "main.py", "file_path": "main.py"},
        aliases=(("file_path", "path"),),
    ) == {"path": "main.py"}

    with pytest.raises(
        ValueError, match="conflicting tool arguments: path and file_path"
    ):
        prepare_tool_arguments(
            {"path": "main.py", "file_path": "other.py"},
            aliases=(("file_path", "path"),),
        )


def test_wrapped_tool_rejects_pre_aborted_signal_before_execute() -> None:
    import asyncio

    import pytest

    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.tools.workspace import ToolDefinition, wrap_tool_definition

    class AbortedSignal:
        aborted = True

    called = False

    async def execute(tool_call_id, params, signal=None, on_update=None):
        nonlocal called
        del tool_call_id, params, signal, on_update
        called = True
        return AgentToolResult(content=[TextPart(type="text", text="late")], details={})

    tool = wrap_tool_definition(
        ToolDefinition(
            name="abort_probe",
            label="Abort Probe",
            description="Abort probe",
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            execution=direct_execution(execute),
        )
    )

    with pytest.raises(RuntimeError, match="Operation aborted"):
        asyncio.run(tool.execute("call-abort", {}, signal=AbortedSignal()))

    assert called is False
