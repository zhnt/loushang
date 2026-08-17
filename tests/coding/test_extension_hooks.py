from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage


def _usage() -> Usage:
    return Usage(
        input=0,
        output=0,
        cache_read=0,
        cache_write=0,
        total_tokens=0,
        cost={},
    )


def _assistant_tool_call_message(
    tool_name: str = "calc", arguments: dict[str, object] | None = None
) -> AssistantMessage:
    return AssistantMessage(
        endpoint="test-endpoint",
        role="assistant",
        content=[
            ToolCall(
                type="toolCall",
                id="tc_1",
                name=tool_name,
                arguments=arguments or {"x": 1},
            )
        ],
        api="anthropic-messages",
        provider="faux",
        model="faux-model",
        response_id=None,
        usage=_usage(),
        stop_reason="toolUse",
        error_message=None,
        timestamp=0.0,
    )


def _agent_context():
    from loushang.agent.types import AgentContext

    return AgentContext(
        system_prompt="system",
        messages=[],
        tools=[],
    )


def test_hook_dispatcher_pipelines_tool_call_decisions() -> None:
    from loushang.agent.types import BeforeToolCallContext
    from loushang.harness.extensions.agent import LoadedExtension, ToolCallDecision
    from loushang.harness.extensions.agent.hooks import ExtensionToolHookDispatcher

    seen: list[tuple[str, object]] = []

    def _context_factory(_extension):
        return SimpleNamespace(cwd="/tmp/project")

    def _rewrite(event, ctx):
        seen.append((event.tool_call.name, event.args))
        assert ctx.cwd == "/tmp/project"
        return ToolCallDecision(tool_name="calc_rewritten", arguments={"y": 2})

    def _block(event, ctx):
        del ctx
        seen.append((event.tool_call.name, event.args))
        return ToolCallDecision(block=True, reason="blocked by extension")

    runner_diagnostics: list[object] = []
    dispatcher = ExtensionToolHookDispatcher(
        [
            LoadedExtension(
                name="rewrite",
                source_path=Path("/tmp/rewrite.py"),
                hooks={"tool_call": [_rewrite]},
            ),
            LoadedExtension(
                name="block",
                source_path=Path("/tmp/block.py"),
                hooks={"tool_call": [_block]},
            ),
        ],
        context_factory=_context_factory,
        diagnostics=runner_diagnostics,
    )

    message = _assistant_tool_call_message()
    result = asyncio.run(
        dispatcher.before_tool_call(
            BeforeToolCallContext(
                assistant_message=message,
                tool_call=message.content[0],
                args={"x": 1},
                context=_agent_context(),
            )
        )
    )

    assert result is not None
    assert result.block is True
    assert result.reason == "blocked by extension"
    assert result.tool_name == "calc_rewritten"
    assert result.arguments == {"y": 2}
    assert seen == [("calc", {"x": 1}), ("calc_rewritten", {"y": 2})]
    assert runner_diagnostics == []


def test_hook_dispatcher_pipelines_tool_result_decisions() -> None:
    from loushang.agent.types import AfterToolCallContext, AgentToolResult
    from loushang.harness.extensions.agent import LoadedExtension, ToolResultDecision
    from loushang.harness.extensions.agent.hooks import ExtensionToolHookDispatcher

    seen: list[tuple[object, object]] = []

    def _rewrite_once(event, ctx):
        del ctx
        seen.append((event.result.details, event.hook_details))
        return ToolResultDecision(
            result=AgentToolResult(
                content=[TextPart(type="text", text="one")], details={"step": 1}
            )
        )

    def _rewrite_again(event, ctx):
        del ctx
        seen.append((event.result.details, event.hook_details))
        return ToolResultDecision(
            result=AgentToolResult(
                content=[TextPart(type="text", text="two")],
                details={"step": 2},
                terminate=True,
            )
        )

    dispatcher = ExtensionToolHookDispatcher(
        [
            LoadedExtension(
                name="one",
                source_path=Path("/tmp/one.py"),
                hooks={"tool_result": [_rewrite_once]},
            ),
            LoadedExtension(
                name="two",
                source_path=Path("/tmp/two.py"),
                hooks={"tool_result": [_rewrite_again]},
            ),
        ],
        context_factory=lambda _extension: SimpleNamespace(cwd="/tmp/project"),
        diagnostics=[],
    )

    message = _assistant_tool_call_message()
    result = asyncio.run(
        dispatcher.after_tool_call(
            AfterToolCallContext(
                assistant_message=message,
                tool_call=message.content[0],
                args={"x": 1},
                result=AgentToolResult(
                    content=[TextPart(type="text", text="zero")], details={"step": 0}
                ),
                is_error=False,
                context=_agent_context(),
                hook_details={"step": 0},
            )
        )
    )

    assert result is not None
    assert result.content == [TextPart(type="text", text="two")]
    assert result.details == {"step": 2}
    assert result.terminate is True
    assert seen == [
        ({"step": 0}, {"step": 0}),
        ({"step": 1}, {"step": 1}),
    ]


def test_hook_dispatcher_pipelines_explicit_null_tool_result_details() -> None:
    from loushang.agent.types import AfterToolCallContext, AgentToolResult
    from loushang.harness.extensions.agent import LoadedExtension, ToolResultDecision
    from loushang.harness.extensions.agent.hooks import ExtensionToolHookDispatcher

    seen: list[tuple[object, object]] = []

    def _clear(event, ctx):
        del ctx
        seen.append((event.result.details, event.hook_details))
        return ToolResultDecision(
            result=AgentToolResult(
                content=[TextPart(type="text", text="cleared")], details=None
            )
        )

    def _observe(event, ctx):
        del ctx
        seen.append((event.result.details, event.hook_details))
        return None

    dispatcher = ExtensionToolHookDispatcher(
        [
            LoadedExtension(
                name="clear",
                source_path=Path("/tmp/clear.py"),
                hooks={"tool_result": [_clear]},
            ),
            LoadedExtension(
                name="observe",
                source_path=Path("/tmp/observe.py"),
                hooks={"tool_result": [_observe]},
            ),
        ],
        context_factory=lambda _extension: SimpleNamespace(cwd="/tmp/project"),
        diagnostics=[],
    )
    message = _assistant_tool_call_message()

    result = asyncio.run(
        dispatcher.after_tool_call(
            AfterToolCallContext(
                assistant_message=message,
                tool_call=message.content[0],
                args={"x": 1},
                result=AgentToolResult(
                    content=[TextPart(type="text", text="original")],
                    details={"value": 1},
                ),
                is_error=False,
                context=_agent_context(),
                hook_details={"value": 1},
            )
        )
    )

    assert result is not None
    assert result.details_provided is True
    assert result.details is None
    assert seen == [
        ({"value": 1}, {"value": 1}),
        (None, None),
    ]


def test_hook_dispatcher_records_tool_hook_errors_and_continues() -> None:
    from loushang.agent.types import BeforeToolCallContext
    from loushang.harness.extensions.agent import LoadedExtension, ToolCallDecision
    from loushang.harness.extensions.agent.hooks import ExtensionToolHookDispatcher

    runtime_errors: list[tuple[str, str, str]] = []

    def _broken(event, ctx):
        del event, ctx
        raise RuntimeError("boom")

    def _rewrite(event, ctx):
        del event, ctx
        return ToolCallDecision(arguments={"ok": True})

    diagnostics: list[object] = []
    dispatcher = ExtensionToolHookDispatcher(
        [
            LoadedExtension(
                name="broken",
                source_path=Path("/tmp/broken.py"),
                hooks={"tool_call": [_broken]},
            ),
            LoadedExtension(
                name="rewrite",
                source_path=Path("/tmp/rewrite.py"),
                hooks={"tool_call": [_rewrite]},
            ),
        ],
        context_factory=lambda _extension: SimpleNamespace(cwd="/tmp/project"),
        diagnostics=diagnostics,
        runtime_error_handler=lambda extension, event, error: runtime_errors.append(
            (extension.name, event, str(error))
        ),
    )

    message = _assistant_tool_call_message()
    result = asyncio.run(
        dispatcher.before_tool_call(
            BeforeToolCallContext(
                assistant_message=message,
                tool_call=message.content[0],
                args={"x": 1},
                context=_agent_context(),
            )
        )
    )

    assert result is not None
    assert result.arguments == {"ok": True}
    assert [getattr(diagnostic, "code", None) for diagnostic in diagnostics] == [
        "extension_tool_call_failed"
    ]
    assert runtime_errors == [("broken", "tool_call", "boom")]
