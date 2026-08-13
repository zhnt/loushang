from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from loushang.ai.types import AssistantMessage, TextPart, ToolCall, Usage, UserMessage
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace import ToolContext


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


async def _execute_tool(tool_name: str, arguments: dict[str, object], context, signal):
    return {
        "tool_name": tool_name,
        "arguments": arguments,
    }


def _tool(name: str):
    from loushang.harness.tools.workspace import ToolDefinition

    return ToolDefinition(
        name=name,
        label=name.replace("_", " ").title(),
        description=f"{name} description",
        parameters={},
        execution=direct_execution(_execute_tool),
    )


def _user_message(text: str) -> UserMessage:
    return UserMessage(
        role="user",
        content=[TextPart(type="text", text=text)],
        timestamp=0.0,
    )


def test_extension_runner_merges_resource_contributions_from_loaded_extensions() -> (
    None
):
    from loushang.harness.extensions.agent import (
        ExtensionResourceContribution,
        ExtensionRunner,
        LoadedExtension,
    )
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceBundle,
    )

    def _resources_discover(event, ctx):
        return ExtensionResourceContribution(
            prompt_descriptors=[
                PromptFragmentDescriptor(
                    name="demo-extension",
                    source_path=Path("/tmp/extensions/demo"),
                    text="Extension prompt",
                )
            ]
        )

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={"resources_discover": [_resources_discover]},
            )
        ]
    )

    merged = runner.discover_resources(ResourceBundle(cwd=Path("/tmp/project")))

    assert merged.prompt_fragments == ["Extension prompt"]
    assert merged.prompt_descriptors[0].name == "demo-extension"
    assert runner.get_diagnostics() == []


def test_extension_runner_wraps_extension_tools_with_context() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace import direct_tool
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    seen: dict[str, object] = {}

    @tool(name="demo_tool")
    async def demo_tool(x: int, ctx: ToolContext) -> dict[str, bool]:
        seen["tool_call_id"] = ctx.tool_call_id
        seen["params"] = {"x": x}
        seen["cwd"] = ctx.cwd
        return {"ok": True}

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                tool_definitions=[direct_tool(demo_tool)],
            )
        ]
    )

    runtime_tool = wrap_tool_definition(runner.list_tool_definitions()[0])
    result = asyncio.run(runtime_tool.execute("tc1", {"x": 1}))

    assert result.details == {"ok": True}
    assert seen == {"tool_call_id": "tc1", "params": {"x": 1}, "cwd": "/tmp/extensions"}


def test_extension_runner_keeps_explicit_four_argument_direct_binding() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.ai.types import TextPart
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.tools.workspace import ToolDefinition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    seen: dict[str, object] = {}

    async def _execute(tool_call_id, params, signal, on_update):
        del signal, on_update
        seen["tool_call_id"] = tool_call_id
        seen["params"] = params
        return AgentToolResult(
            content=[TextPart(type="text", text="ok")], details={"ok": True}
        )

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                tool_definitions=[
                    ToolDefinition(
                        name="demo_tool",
                        label="Demo Tool",
                        description="Tool from loaded extension",
                        parameters={},
                        execution=direct_execution(_execute),
                    )
                ],
            )
        ]
    )

    runtime_tool = wrap_tool_definition(runner.list_tool_definitions()[0])
    result = asyncio.run(runtime_tool.execute("tc1", {"x": 1}))

    assert result.details == {"ok": True}
    assert seen == {"tool_call_id": "tc1", "params": {"x": 1}}


def test_extension_runner_resolves_duplicate_command_names() -> None:
    from loushang.harness.extensions.agent.runner import ExtensionRunner
    from loushang.harness.extensions.types import LoadedExtension, RegisteredCommand

    async def _handler(args, ctx):
        del args, ctx

    first = LoadedExtension(name="one", source_path=Path("/tmp/one.py"))
    second = LoadedExtension(name="two", source_path=Path("/tmp/two.py"))
    object.__setattr__(
        first,
        "commands",
        {
            "deploy": RegisteredCommand(
                name="deploy", description="first", handler=_handler
            )
        },
    )
    object.__setattr__(
        second,
        "commands",
        {
            "deploy": RegisteredCommand(
                name="deploy", description="second", handler=_handler
            )
        },
    )

    runner = ExtensionRunner([first, second])

    names = [command.invocation_name for command in runner.get_registered_commands()]
    assert names == ["deploy:1", "deploy:2"]
    assert runner.get_command("deploy:1").extension_name == "one"
    assert runner.get_command("deploy:2").extension_name == "two"
    assert runner.get_command("deploy:1").source_info.path == Path("/tmp/one.py")


def test_extension_runner_preserves_package_command_source_info() -> None:
    from loushang.harness.extensions.agent.runner import ExtensionRunner
    from loushang.harness.extensions.types import LoadedExtension, RegisteredCommand

    async def _handler(args, ctx):
        del args, ctx

    extension = LoadedExtension(
        name="pkg",
        source_path=Path("/tmp/packages/pkg/extensions/deploy.py"),
        source_kind="external_package",
        source_scope="package",
        source_root=Path("/tmp/packages/pkg/extensions"),
    )
    object.__setattr__(
        extension,
        "commands",
        {
            "deploy": RegisteredCommand(
                name="deploy", description="package", handler=_handler
            )
        },
    )

    runner = ExtensionRunner([extension])
    command = runner.get_command("deploy")

    assert command is not None
    assert command.source_info.path == Path("/tmp/packages/pkg/extensions/deploy.py")
    assert command.source_info.origin == "package"
    assert command.source_info.base_dir == Path("/tmp/packages/pkg/extensions")


def test_extension_runner_avoids_command_alias_collision_with_literal_name() -> None:
    from loushang.harness.extensions.agent.runner import ExtensionRunner
    from loushang.harness.extensions.types import LoadedExtension, RegisteredCommand

    async def _handler(args, ctx):
        del args, ctx

    first = LoadedExtension(name="one", source_path=Path("/tmp/one.py"))
    second = LoadedExtension(name="two", source_path=Path("/tmp/two.py"))
    third = LoadedExtension(name="three", source_path=Path("/tmp/three.py"))
    object.__setattr__(
        first,
        "commands",
        {
            "deploy": RegisteredCommand(
                name="deploy", description="first", handler=_handler
            )
        },
    )
    object.__setattr__(
        second,
        "commands",
        {
            "deploy": RegisteredCommand(
                name="deploy", description="second", handler=_handler
            )
        },
    )
    object.__setattr__(
        third,
        "commands",
        {
            "deploy:1": RegisteredCommand(
                name="deploy:1", description="literal", handler=_handler
            )
        },
    )

    runner = ExtensionRunner([first, second, third])

    names = [command.invocation_name for command in runner.get_registered_commands()]
    assert names == ["deploy:2", "deploy:3", "deploy:1"]
    assert runner.get_command("deploy:1").extension_name == "three"
    assert runner.get_command("deploy:2").extension_name == "one"
    assert runner.get_command("deploy:3").extension_name == "two"


def test_extension_runner_shortcut_collisions_are_first_wins() -> None:
    from loushang.harness.extensions.agent.runner import ExtensionRunner
    from loushang.harness.extensions.types import LoadedExtension, RegisteredShortcut

    first = LoadedExtension(name="one", source_path=Path("/tmp/one.py"))
    second = LoadedExtension(name="two", source_path=Path("/tmp/two.py"))
    object.__setattr__(
        first,
        "shortcuts",
        {
            "ctrl+p": RegisteredShortcut(
                shortcut="ctrl+p", handler=lambda ctx: None, description="first"
            )
        },
    )
    object.__setattr__(
        second,
        "shortcuts",
        {
            "ctrl+p": RegisteredShortcut(
                shortcut="ctrl+p", handler=lambda ctx: None, description="second"
            )
        },
    )

    runner = ExtensionRunner([first, second])

    shortcuts = runner.get_shortcuts()
    diagnostics = runner.get_shortcut_diagnostics()

    assert len(shortcuts) == 1
    assert [shortcut.shortcut for shortcut in shortcuts] == ["ctrl+p"]
    assert shortcuts[0].description == "first"
    assert shortcuts[0].extension_name == "one"
    assert shortcuts[0].source_info.path == Path("/tmp/one.py")
    assert len(diagnostics) == 1
    assert any(
        diagnostic.source_path == second.source_path for diagnostic in diagnostics
    )


def test_extension_runner_flag_collisions_are_first_wins() -> None:
    from loushang.harness.extensions.agent.runner import ExtensionRunner
    from loushang.harness.extensions.types import LoadedExtension, RegisteredFlag

    first = LoadedExtension(name="one", source_path=Path("/tmp/one.py"))
    second = LoadedExtension(name="two", source_path=Path("/tmp/two.py"))
    object.__setattr__(
        first,
        "flags",
        {
            "plan": RegisteredFlag(
                name="plan", type="boolean", description="first", default=False
            )
        },
    )
    object.__setattr__(
        second,
        "flags",
        {
            "plan": RegisteredFlag(
                name="plan", type="boolean", description="second", default=True
            )
        },
    )

    runner = ExtensionRunner([first, second])

    flags = runner.get_flags()
    diagnostics = runner.get_flag_diagnostics()

    assert len(flags) == 1
    assert [flag.name for flag in flags] == ["plan"]
    assert flags[0].description == "first"
    assert flags[0].default is False
    assert flags[0].extension_name == "one"
    assert flags[0].source_info.path == Path("/tmp/one.py")
    assert len(diagnostics) == 1
    assert any(
        diagnostic.source_path == second.source_path for diagnostic in diagnostics
    )


def test_extension_runner_populates_flag_defaults() -> None:
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredFlag,
    )

    first = LoadedExtension(name="first", source_path=Path("/tmp/one.py"))
    second = LoadedExtension(name="second", source_path=Path("/tmp/two.py"))
    object.__setattr__(
        first,
        "flags",
        {
            "plan": RegisteredFlag(
                name="plan", type="boolean", description="first", default=False
            ),
            "request-id": RegisteredFlag(
                name="request-id", type="string", description="first", default="abc"
            ),
        },
    )
    object.__setattr__(
        second,
        "flags",
        {
            "verbose": RegisteredFlag(
                name="verbose", type="boolean", description="second", default=True
            )
        },
    )

    runner = ExtensionRunner([first, second])

    assert runner.get_flag_values() == {
        "plan": False,
        "request-id": "abc",
        "verbose": True,
    }


def test_extension_runner_does_not_overwrite_explicit_flag_values_with_defaults() -> (
    None
):
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredFlag,
    )

    ext = LoadedExtension(name="demo", source_path=Path("/tmp/demo.py"))
    object.__setattr__(
        ext,
        "flags",
        {
            "plan": RegisteredFlag(
                name="plan", type="boolean", description="plan mode", default=False
            )
        },
    )

    runner = ExtensionRunner([ext])
    runner.set_flag_value("plan", True)

    assert runner.get_flag_values()["plan"] is True


def test_extension_runner_emits_lifecycle_hooks_and_rejects_duplicate_tools() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    state = {"first": [], "second": []}

    def _first_session_start(event, ctx):
        state["first"].append("start")

    def _first_session_refresh(event, ctx):
        state["first"].append("refresh")

    def _first_session_shutdown(event, ctx):
        state["first"].append("shutdown")

    def _second_session_start(event, ctx):
        state["second"].append("start")

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="first",
                source_path=Path("/tmp/extensions/first.py"),
                hooks={
                    "session_start": [_first_session_start],
                    "session_refresh": [_first_session_refresh],
                    "session_shutdown": [_first_session_shutdown],
                },
                tool_definitions=[_tool("ext_tool")],
            ),
            LoadedExtension(
                name="second",
                source_path=Path("/tmp/extensions/second.py"),
                hooks={"session_start": [_second_session_start]},
                tool_definitions=[_tool("ext_tool")],
            ),
        ]
    )

    asyncio.run(runner.emit_session_start(object()))
    asyncio.run(runner.emit_session_refresh(object()))
    asyncio.run(runner.emit_session_shutdown(object()))

    assert state["first"] == ["start", "refresh", "shutdown"]
    assert state["second"] == ["start"]
    assert [definition.name for definition in runner.list_tool_definitions()] == [
        "ext_tool"
    ]
    assert [diagnostic.code for diagnostic in runner.get_diagnostics()] == [
        "duplicate_extension_tool"
    ]


def test_extension_runner_records_hook_failures_as_diagnostics() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.resources.types import ResourceBundle

    def _broken_resources_discover(event, ctx):
        raise RuntimeError("boom")

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="broken",
                source_path=Path("/tmp/extensions/broken.py"),
                hooks={"resources_discover": [_broken_resources_discover]},
            )
        ]
    )

    merged = runner.discover_resources(ResourceBundle(cwd=Path("/tmp/project")))

    assert merged.prompt_fragments == []
    assert [diagnostic.code for diagnostic in merged.diagnostics] == [
        "extension_resources_discover_failed"
    ]


def test_extension_runner_closes_async_session_hook_coroutines() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    async def _async_session_start(event, ctx):
        del event, ctx
        return None

    created: list[object] = []

    def _hook(event, ctx):
        coroutine = _async_session_start(event, ctx)
        created.append(coroutine)
        return coroutine

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="async",
                source_path=Path("/tmp/extensions/async.py"),
                hooks={"session_start": [_hook]},
            )
        ]
    )

    asyncio.run(runner.emit_session_start(object()))

    assert len(created) == 1
    assert inspect.getcoroutinestate(created[0]) == inspect.CORO_CLOSED
    assert runner.get_diagnostics() == []


def test_extension_runner_records_session_refresh_hook_failures() -> None:
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        ExtensionRuntimeBindings,
        LoadedExtension,
        SessionRefreshEvent,
    )

    def _broken_refresh(event, ctx):
        del event, ctx
        raise RuntimeError("boom")

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="broken",
                source_path=Path("/tmp/broken.py"),
                hooks={"session_refresh": [_broken_refresh]},
            )
        ]
    )

    runner.bind_runtime(
        ExtensionRuntimeBindings(
            cwd="/tmp/project",
            get_active_tool_names=lambda: ["read"],
            get_model_selection=lambda: {"provider": "demo", "model_id": "demo-model"},
            set_active_tools=lambda tool_names: None,
            set_model=lambda selection: None,
            request_resource_refresh=lambda: None,
            shutdown=lambda: None,
            record_diagnostic=lambda diagnostic: None,
        )
    )
    asyncio.run(
        runner.emit_session_refresh(
            SessionRefreshEvent(reason="model_selection_changed")
        )
    )

    assert any(
        d.code == "extension_session_refresh_failed" for d in runner.get_diagnostics()
    )


def test_extension_runner_records_session_action_callback_failures_via_refresh_hook_diagnostics() -> (
    None
):
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        ExtensionRuntimeBindings,
        LoadedExtension,
        SessionRefreshEvent,
    )

    async def _broken_refresh(event, ctx):
        del event
        await ctx.set_model(object())

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="broken",
                source_path=Path("/tmp/broken.py"),
                hooks={"session_refresh": [_broken_refresh]},
            )
        ]
    )

    def _raise_model_failure(selection) -> None:
        del selection
        raise RuntimeError("callback failed")

    runner.bind_runtime(
        ExtensionRuntimeBindings(
            cwd="/tmp/project",
            get_active_tool_names=lambda: ["read"],
            get_model_selection=lambda: {"provider": "demo", "model_id": "demo-model"},
            set_active_tools=lambda tool_names: None,
            set_model=_raise_model_failure,
            request_resource_refresh=lambda: None,
            shutdown=lambda: None,
            record_diagnostic=lambda diagnostic: None,
        )
    )
    asyncio.run(
        runner.emit_session_refresh(
            SessionRefreshEvent(reason="model_selection_changed")
        )
    )

    assert any(
        d.code == "extension_session_refresh_failed" for d in runner.get_diagnostics()
    )


def test_extension_runner_pipelines_tool_call_decisions() -> None:
    import asyncio

    from loushang.agent.types import BeforeToolCallContext
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        ToolCallDecision,
    )

    seen: list[tuple[str, dict[str, object]]] = []

    def _rewrite(event, ctx):
        seen.append((event.tool_call.name, event.args))
        return ToolCallDecision(tool_name="calc_rewritten", arguments={"y": 2})

    async def _block(event, ctx):
        seen.append((event.tool_call.name, event.args))
        return ToolCallDecision(block=True, reason="blocked by extension")

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="rewrite",
                source_path=Path("/tmp/extensions/rewrite.py"),
                hooks={"tool_call": [_rewrite]},
            ),
            LoadedExtension(
                name="block",
                source_path=Path("/tmp/extensions/block.py"),
                hooks={"tool_call": [_block]},
            ),
        ]
    )

    decision = asyncio.run(
        runner.before_tool_call(
            BeforeToolCallContext(
                assistant_message=_assistant_tool_call_message(),
                tool_call=_assistant_tool_call_message().content[0],
                args={"x": 1},
                context=_agent_context(),
            ),
            None,
        )
    )

    assert decision is not None
    assert decision.block is True
    assert decision.reason == "blocked by extension"
    assert seen == [
        ("calc", {"x": 1}),
        ("calc_rewritten", {"y": 2}),
    ]


def test_extension_runner_pipelines_tool_result_decisions() -> None:
    import asyncio

    from loushang.agent.types import AfterToolCallContext, AgentToolResult
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        ToolResultDecision,
    )

    seen: list[str] = []

    def _rewrite_once(event, ctx):
        seen.append(event.result.content[0].text)
        return ToolResultDecision(
            result=AgentToolResult(
                content=[TextPart(type="text", text="first rewrite")],
                details={"stage": 1},
            )
        )

    async def _rewrite_again(event, ctx):
        seen.append(event.result.content[0].text)
        return ToolResultDecision(
            result=AgentToolResult(
                content=[TextPart(type="text", text="final rewrite")],
                details={"stage": 2},
                terminate=True,
            )
        )

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="first",
                source_path=Path("/tmp/extensions/first.py"),
                hooks={"tool_result": [_rewrite_once]},
            ),
            LoadedExtension(
                name="second",
                source_path=Path("/tmp/extensions/second.py"),
                hooks={"tool_result": [_rewrite_again]},
            ),
        ]
    )

    result = asyncio.run(
        runner.after_tool_call(
            AfterToolCallContext(
                assistant_message=_assistant_tool_call_message(),
                tool_call=_assistant_tool_call_message().content[0],
                args={"x": 1},
                result=AgentToolResult(
                    content=[TextPart(type="text", text="original")],
                    details={"stage": 0},
                ),
                is_error=False,
                context=_agent_context(),
            ),
            None,
        )
    )

    assert result is not None
    assert result.content == [TextPart(type="text", text="final rewrite")]
    assert result.details == {"stage": 2}
    assert result.terminate is True
    assert seen == ["original", "first rewrite"]


def test_extension_runner_pipelines_context_results_without_mutating_input_messages() -> (
    None
):
    import asyncio

    from loushang.harness.extensions.agent import (
        ContextResult,
        ExtensionRunner,
        LoadedExtension,
    )

    seen: list[str] = []

    def _rewrite(event, ctx):
        seen.append(event.messages[0].content[0].text)
        event.messages[0] = _user_message("rewritten by extension")
        return ContextResult(messages=event.messages)

    async def _append(event, ctx):
        seen.append(event.messages[0].content[0].text)
        return ContextResult(
            messages=event.messages + [_user_message("appended later")]
        )

    original_messages = [_user_message("original")]
    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="rewrite",
                source_path=Path("/tmp/extensions/rewrite.py"),
                hooks={"context": [_rewrite]},
            ),
            LoadedExtension(
                name="append",
                source_path=Path("/tmp/extensions/append.py"),
                hooks={"context": [_append]},
            ),
        ]
    )

    rewritten = asyncio.run(runner.emit_context(original_messages, cwd="/tmp/project"))

    assert [message.content[0].text for message in original_messages] == ["original"]
    assert [message.content[0].text for message in rewritten] == [
        "rewritten by extension",
        "appended later",
    ]
    assert seen == ["original", "rewritten by extension"]


def test_extension_runner_emit_input_chains_transform_results() -> None:
    import asyncio

    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        InputEventResult,
        LoadedExtension,
    )

    seen: list[tuple[str, str]] = []

    def _first(event, ctx):
        del ctx
        seen.append((event.text, event.source))
        return InputEventResult(action="transform", text=f"{event.text} one")

    def _second(event, ctx):
        del ctx
        seen.append((event.text, event.source))
        return {"action": "transform", "text": f"{event.text} two"}

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="one", source_path=Path("/tmp/one.py"), hooks={"input": [_first]}
            ),
            LoadedExtension(
                name="two", source_path=Path("/tmp/two.py"), hooks={"input": [_second]}
            ),
        ]
    )

    result = asyncio.run(
        runner.emit_input("start", None, source="rpc", cwd="/tmp/project")
    )

    assert result.action == "transform"
    assert result.text == "start one two"
    assert seen == [("start", "rpc"), ("start one", "rpc")]


def test_extension_runner_emit_input_stops_on_handled_result() -> None:
    import asyncio

    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        InputEventResult,
        LoadedExtension,
    )

    seen: list[str] = []

    def _first(event, ctx):
        del ctx
        seen.append(event.text)
        return InputEventResult(action="handled")

    def _second(event, ctx):
        del ctx
        seen.append(event.text)
        return None

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="one", source_path=Path("/tmp/one.py"), hooks={"input": [_first]}
            ),
            LoadedExtension(
                name="two", source_path=Path("/tmp/two.py"), hooks={"input": [_second]}
            ),
        ]
    )

    result = asyncio.run(
        runner.emit_input("start", None, source="interactive", cwd="/tmp/project")
    )

    assert result.action == "handled"
    assert seen == ["start"]


def test_extension_runner_returns_command_argument_completions() -> None:
    import asyncio

    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    async def _handler(args, ctx):
        del args, ctx

    async def _complete(prefix: str):
        await asyncio.sleep(0)
        return [{"value": f"{prefix}-prod"}]

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="deploy-ext",
                source_path=Path("/tmp/deploy.py"),
                commands={
                    "deploy": RegisteredCommand(
                        name="deploy",
                        handler=_handler,
                        get_argument_completions=_complete,
                    )
                },
            )
        ]
    )

    completions = asyncio.run(
        runner.get_command_argument_completions("deploy", "staging")
    )

    assert completions == [{"value": "staging-prod"}]


def test_extension_runner_records_diagnostic_for_invalid_command_argument_completions() -> (
    None
):
    import asyncio

    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
    )

    async def _handler(args, ctx):
        del args, ctx

    def _complete(prefix: str):
        del prefix
        return "invalid"

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="deploy-ext",
                source_path=Path("/tmp/deploy.py"),
                commands={
                    "deploy": RegisteredCommand(
                        name="deploy",
                        handler=_handler,
                        get_argument_completions=_complete,
                    )
                },
            )
        ]
    )

    assert asyncio.run(runner.get_command_argument_completions("deploy", "")) is None
    assert [diagnostic.code for diagnostic in runner.get_diagnostics()] == [
        "invalid_extension_command_argument_completions"
    ]


def test_extension_api_runtime_read_methods_work_from_command_closure() -> None:
    import asyncio

    from loushang.harness.commands import SessionCommandDescriptor
    from loushang.harness.extensions.agent import ExtensionAPI, ExtensionRunner
    from loushang.harness.resources.source import SourceInfo

    seen: dict[str, object] = {}
    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))
    api.register_flag("plan", type="boolean", default=False)

    async def _inspect(args, ctx):
        del args, ctx
        seen["commands"] = [command.name for command in api.get_commands()]
        seen["active_tools"] = api.get_active_tools()
        seen["all_tools"] = api.get_all_tools()
        seen["plan"] = api.get_flag("plan")

    api.register_command("inspect", handler=_inspect)
    runner = ExtensionRunner([api.build_loaded_extension()])
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection=None,
            list_commands=lambda: [
                SessionCommandDescriptor(
                    name="inspect",
                    description=None,
                    source="extension",
                    source_info=SourceInfo(path=Path("/tmp/demo.py")),
                ),
                SessionCommandDescriptor(
                    name="skill:qa",
                    description=None,
                    source="skill",
                    source_info=SourceInfo(path=Path("/tmp/skill/SKILL.md")),
                ),
            ],
        )
    )

    command = runner.get_command("inspect")
    assert command is not None
    context = runner.create_command_context(fallback_cwd="/tmp/project")
    asyncio.run(command.handler("", context))

    assert seen == {
        "commands": ["inspect", "skill:qa"],
        "active_tools": ["read"],
        "all_tools": [{"name": "read"}, {"name": "grep"}],
        "plan": False,
    }


def test_extension_runner_get_message_renderer_uses_first_registration() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    def _first_renderer(message, options, theme):
        return ("first", message, options, theme)

    def _second_renderer(message, options, theme):
        return ("second", message, options, theme)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="first",
                source_path=Path("/tmp/first.py"),
                message_renderers={"demo.card": _first_renderer},
            ),
            LoadedExtension(
                name="second",
                source_path=Path("/tmp/second.py"),
                message_renderers={"demo.card": _second_renderer},
            ),
        ]
    )

    assert runner.get_message_renderer("demo.card") is _first_renderer
    assert runner.get_message_renderer("demo.card") is _first_renderer
    assert runner.get_message_renderer("missing") is None


def test_extension_runner_does_not_expose_or_bind_inactive_surfaces() -> None:
    from loushang.harness.extensions.agent import (
        ExtensionPolicyDecision,
        ExtensionRunner,
        LoadedExtension,
        RegisteredCommand,
        RegisteredFlag,
        RegisteredShortcut,
    )

    class RuntimeAPI:
        def __init__(self) -> None:
            self.bind_calls = 0

        def bind_runtime_state(self, state: object) -> None:
            del state
            self.bind_calls += 1

    async def _command(arguments: str, context: object) -> None:
        del arguments, context

    def renderer(message: object, options: object, theme: object) -> object:
        return message, options, theme

    api = RuntimeAPI()
    inactive = LoadedExtension(
        name="inactive",
        source_path=Path("/tmp/inactive.py"),
        tool_definitions=[_tool("hidden_tool")],
        commands={
            "hidden": RegisteredCommand(name="hidden", handler=_command),
        },
        flags={
            "hidden": RegisteredFlag(
                name="hidden",
                type="boolean",
                default=True,
            ),
        },
        shortcuts={
            "ctrl+h": RegisteredShortcut(
                shortcut="ctrl+h",
                handler=lambda context: context,
            ),
        },
        message_renderers={"hidden.card": renderer},
        api=api,
        policy=ExtensionPolicyDecision(enabled=False),
    )

    runner = ExtensionRunner([inactive])
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=[],
            model_selection=None,
        )
    )

    assert runner.list_tool_definitions() == []
    assert runner.get_registered_commands() == []
    assert runner.get_flags() == []
    assert runner.get_shortcuts() == []
    assert runner.get_flag_values() == {}
    assert runner.get_message_renderer("hidden.card") is None
    assert runner.list_message_renderers() == []
    assert runner.list_extensions()[0]["enabled"] is False
    assert api.bind_calls == 0


def test_extension_runner_exposes_headless_renderer_and_diagnostic_snapshots() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.resources.diagnostics import resource_diagnostic

    def _renderer(message, options, theme):
        return (message, options, theme)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="cards",
                source_path=Path("/tmp/extensions/cards.py"),
                message_renderers={"demo.card": _renderer},
                diagnostics=[
                    resource_diagnostic(
                        code="demo_warning", message="demo", resource_id="demo.card"
                    )
                ],
            )
        ]
    )

    renderers = runner.list_message_renderers()
    snapshot = runner.get_diagnostic_snapshot()

    assert renderers[0]["customType"] == "demo.card"
    assert renderers[0]["extensionName"] == "cards"
    assert renderers[0]["sourceInfo"]["path"] == "/tmp/extensions/cards.py"
    assert snapshot["total"] == 1
    assert snapshot["diagnostics"][0]["resourceId"] == "demo.card"


def test_extension_runner_resources_discover_accepts_pi_style_path_result(
    tmp_path,
) -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.resources.types import ResourceBundle

    prompt_file = tmp_path / "prompts" / "plan.md"
    skill_file = tmp_path / "skills" / "debug" / "SKILL.md"
    theme_file = tmp_path / "themes" / "clean.json"
    prompt_file.parent.mkdir()
    skill_file.parent.mkdir(parents=True)
    theme_file.parent.mkdir()
    prompt_file.write_text("Plan prompt", encoding="utf-8")
    skill_file.write_text("Debug skill", encoding="utf-8")
    theme_file.write_text("{}", encoding="utf-8")

    def _resources_discover(event, ctx):
        del event, ctx
        return {
            "promptPaths": [str(prompt_file)],
            "skillPaths": [str(skill_file.parent)],
            "themePaths": [str(theme_file)],
        }

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="resources",
                source_path=tmp_path / "extensions" / "resources.py",
                hooks={"resources_discover": [_resources_discover]},
            )
        ]
    )

    bundle = runner.discover_resources(ResourceBundle(cwd=tmp_path))

    assert [(prompt.name, prompt.text) for prompt in bundle.prompts] == [
        ("plan", "Plan prompt")
    ]
    assert [(skill.name, skill.content) for skill in bundle.skills] == [
        ("debug", "Debug skill")
    ]
    assert [(theme.name, theme.source_path) for theme in bundle.themes] == [
        ("clean", theme_file)
    ]


def test_extension_runner_resources_discover_awaits_async_path_result(tmp_path) -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.resources.types import ResourceBundle

    prompt_file = tmp_path / "prompts" / "plan.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("Async plan prompt", encoding="utf-8")
    calls: list[str] = []

    async def _resources_discover(event, ctx):
        del event
        calls.append(ctx.cwd)
        await asyncio.sleep(0)
        return {"promptPaths": [str(prompt_file)]}

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="resources",
                source_path=tmp_path / "extensions" / "resources.py",
                hooks={"resources_discover": [_resources_discover]},
            )
        ]
    )

    bundle = asyncio.run(runner.discover_resources_async(ResourceBundle(cwd=tmp_path)))

    assert calls == [str(tmp_path)]
    assert [(prompt.name, prompt.text) for prompt in bundle.prompts] == [
        ("plan", "Async plan prompt")
    ]
    assert runner.get_diagnostics() == []


def test_extension_runner_resources_discover_path_result_reports_missing_paths(
    tmp_path,
) -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.resources.types import ResourceBundle

    missing_prompt = tmp_path / "prompts" / "missing.md"
    missing_skill = tmp_path / "skills" / "missing"
    missing_theme = tmp_path / "themes" / "missing.json"

    def _resources_discover(event, ctx):
        del event, ctx
        return {
            "promptPaths": [str(missing_prompt)],
            "skillPaths": [str(missing_skill)],
            "themePaths": [str(missing_theme)],
        }

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="resources",
                source_path=tmp_path / "extensions" / "resources.py",
                hooks={"resources_discover": [_resources_discover]},
            )
        ]
    )

    bundle = runner.discover_resources(ResourceBundle(cwd=tmp_path))

    assert [diagnostic.code for diagnostic in bundle.diagnostics] == [
        "extension_prompt_path_not_found",
        "extension_skill_path_not_found",
        "extension_theme_path_not_found",
    ]
    assert runner.get_diagnostics()[-3:] == bundle.diagnostics


def test_extension_api_runtime_action_methods_delegate_from_command_closure() -> None:
    import asyncio

    from loushang.harness.extensions.agent import ExtensionAPI, ExtensionRunner

    tracker: dict[str, object] = {}
    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))

    async def _act(args, ctx):
        del args, ctx
        await api.append_entry("demo_state", {"ok": True})
        await api.send_message({"customType": "notice", "content": "hello"})
        await api.send_user_message("follow up", {"deliverAs": "followUp"})
        await api.set_active_tools(["read", "grep"])
        await api.set_model({"provider": "demo", "model_id": "next"})
        tracker["thinking_before"] = api.get_thinking_level()
        await api.set_thinking_level("high")
        await api.set_session_name("Renamed")
        seen_name = api.get_session_name()
        await api.set_label("entry-1", "important")
        tracker["seen_name"] = seen_name

    api.register_command("act", handler=_act)
    runner = ExtensionRunner([api.build_loaded_extension()])
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=[],
            model_selection=None,
            tracker=tracker,
        )
    )

    command = runner.get_command("act")
    assert command is not None
    context = runner.create_command_context(fallback_cwd="/tmp/project")
    asyncio.run(command.handler("", context))

    assert tracker["append_entry_calls"] == [("demo_state", {"ok": True})]
    assert tracker["send_message_calls"] == [
        ({"customType": "notice", "content": "hello"}, None)
    ]
    assert tracker["send_user_message_calls"] == [
        ("follow up", {"deliverAs": "followUp"})
    ]
    assert tracker["set_active_tools_calls"] == [["read", "grep"]]
    assert tracker["set_model_calls"] == [{"provider": "demo", "model_id": "next"}]
    assert tracker["thinking_before"] == "medium"
    assert tracker["set_thinking_level_calls"] == ["high"]
    assert tracker["set_session_name_calls"] == ["Renamed"]
    assert tracker["seen_name"] == "Demo Session"
    assert tracker["set_label_calls"] == [("entry-1", "important")]


def test_extension_hook_failures_include_provenance_metadata() -> None:
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    def _broken(event, ctx):
        del event, ctx
        raise RuntimeError("boom")

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/demo-ext.py"),
                hooks={"input": [_broken]},
            )
        ]
    )

    asyncio.run(runner.emit_input("hello", cwd="/tmp/project"))

    diagnostic = runner.get_diagnostics()[-1]
    assert diagnostic.code == "extension_input_failed"
    assert diagnostic.source_path == Path("/tmp/demo-ext.py")
    assert diagnostic.details["metadata"] == {
        "extension_name": "demo",
        "hook": "input",
        "source": "filesystem",
        "scope": "project",
        "origin": "top-level",
        "base_dir": "/tmp",
    }


def _runtime_bindings(
    *,
    cwd: str,
    active_tool_names: list[str],
    model_selection: object | None,
    tracker: dict[str, object] | None = None,
    on_error=None,
    ui_context=None,
    is_idle=lambda: True,
    has_pending_messages=lambda: False,
    get_context_usage=lambda: None,
    get_system_prompt=lambda: "",
    session_manager=None,
    model_registry=None,
    get_signal=lambda: None,
    wait_for_idle=None,
    reload=None,
    navigate_tree=None,
    fork=None,
    new_session=None,
    switch_session=None,
    list_commands=lambda: [],
    get_thinking_level=lambda: "medium",
    exec_command=None,
):
    from loushang.harness.extensions.agent import ExtensionRuntimeBindings

    runtime_tracker = tracker if tracker is not None else {}
    runtime_tracker.setdefault("set_active_tools_calls", [])
    runtime_tracker.setdefault("set_model_calls", [])
    runtime_tracker.setdefault("set_thinking_level_calls", [])
    runtime_tracker.setdefault("append_entry_calls", [])
    runtime_tracker.setdefault("send_message_calls", [])
    runtime_tracker.setdefault("send_user_message_calls", [])
    runtime_tracker.setdefault("set_session_name_calls", [])
    runtime_tracker.setdefault("set_label_calls", [])
    runtime_tracker.setdefault("resource_refresh_requests", 0)
    runtime_tracker.setdefault("shutdown_calls", 0)
    runtime_tracker.setdefault("abort_calls", 0)
    runtime_tracker.setdefault("compact_calls", [])
    runtime_tracker.setdefault("wait_for_idle_calls", 0)
    runtime_tracker.setdefault("reload_calls", 0)
    runtime_tracker.setdefault("navigate_tree_calls", [])
    runtime_tracker.setdefault("fork_calls", [])
    runtime_tracker.setdefault("new_session_calls", [])
    runtime_tracker.setdefault("switch_session_calls", [])
    runtime_tracker.setdefault("recorded_diagnostics", [])

    async def _wait_for_idle() -> None:
        runtime_tracker["wait_for_idle_calls"] += 1

    async def _reload() -> None:
        runtime_tracker["reload_calls"] += 1

    async def _navigate_tree(
        target_id: str, options: object | None = None
    ) -> dict[str, object]:
        runtime_tracker["navigate_tree_calls"].append((target_id, options))
        return {"cancelled": False}

    async def _fork(entry_id: str, options: object | None = None) -> dict[str, object]:
        del options
        runtime_tracker["fork_calls"].append(entry_id)
        return {"cancelled": False}

    async def _new_session(options: object | None = None) -> dict[str, object]:
        runtime_tracker["new_session_calls"].append(options)
        return {"cancelled": False}

    async def _switch_session(
        session_path: str, options: object | None = None
    ) -> dict[str, object]:
        runtime_tracker["switch_session_calls"].append((session_path, options))
        return {"cancelled": False}

    async def _send_message(message: object, options: object | None = None) -> None:
        runtime_tracker["send_message_calls"].append((message, options))

    async def _send_user_message(
        content: object, options: object | None = None
    ) -> None:
        runtime_tracker["send_user_message_calls"].append((content, options))

    async def _compact(custom_instructions: str | None = None) -> None:
        runtime_tracker["compact_calls"].append(custom_instructions)

    async def _set_active_tools(tool_names: list[str]) -> None:
        runtime_tracker["set_active_tools_calls"].append(list(tool_names))

    async def _set_model(selection) -> None:
        runtime_tracker["set_model_calls"].append(selection)

    async def _append_entry(custom_type: str, data: object | None = None) -> None:
        runtime_tracker["append_entry_calls"].append((custom_type, data))

    async def _set_session_name(name: str | None) -> None:
        runtime_tracker["set_session_name_calls"].append(name)

    async def _set_label(entry_id: str, label: str | None) -> None:
        runtime_tracker["set_label_calls"].append((entry_id, label))

    async def _set_thinking_level(level: str) -> None:
        runtime_tracker["set_thinking_level_calls"].append(level)

    return ExtensionRuntimeBindings(
        cwd=cwd,
        session_manager=session_manager,
        model_registry=model_registry,
        get_signal=get_signal,
        get_active_tool_names=lambda: list(active_tool_names),
        get_all_tools=lambda: [{"name": "read"}, {"name": "grep"}],
        get_model_selection=lambda: model_selection,
        set_active_tools=_set_active_tools,
        set_model=_set_model,
        append_entry=_append_entry,
        send_message=_send_message,
        send_user_message=_send_user_message,
        set_session_name=_set_session_name,
        get_session_name=lambda: "Demo Session",
        set_label=_set_label,
        list_commands=list_commands,
        request_resource_refresh=lambda: runtime_tracker.__setitem__(
            "resource_refresh_requests",
            runtime_tracker["resource_refresh_requests"] + 1,
        ),
        shutdown=lambda: runtime_tracker.__setitem__(
            "shutdown_calls", runtime_tracker["shutdown_calls"] + 1
        ),
        abort=lambda: runtime_tracker.__setitem__(
            "abort_calls", runtime_tracker["abort_calls"] + 1
        ),
        is_idle=is_idle,
        has_pending_messages=has_pending_messages,
        get_context_usage=get_context_usage,
        get_thinking_level=get_thinking_level,
        set_thinking_level=_set_thinking_level,
        compact=_compact,
        get_system_prompt=get_system_prompt,
        wait_for_idle=wait_for_idle or _wait_for_idle,
        reload=reload or _reload,
        navigate_tree=navigate_tree or _navigate_tree,
        fork=fork or _fork,
        new_session=new_session or _new_session,
        switch_session=switch_session or _switch_session,
        exec_command=exec_command,
        record_diagnostic=lambda diagnostic: runtime_tracker[
            "recorded_diagnostics"
        ].append(diagnostic),
        ui_context=ui_context,
        on_error=on_error,
    )


def test_extension_runner_reports_hook_failures_to_runtime_error_sink() -> None:
    import asyncio
    from types import SimpleNamespace

    from loushang.agent.types import (
        AfterToolCallContext,
        AgentToolResult,
        BeforeToolCallContext,
    )
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionRefreshEvent,
    )

    def _broken(name):
        def _hook(event, ctx):
            del event, ctx
            raise RuntimeError(f"{name} boom")

        return _hook

    errors: list[dict[str, object]] = []
    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="broken",
                source_path=Path("/tmp/broken.py"),
                hooks={
                    "session_refresh": [_broken("session_refresh")],
                    "session_before_switch": [_broken("session_before_switch")],
                    "context": [_broken("context")],
                    "tool_call": [_broken("tool_call")],
                    "tool_result": [_broken("tool_result")],
                },
            )
        ]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=[],
            model_selection=None,
            on_error=errors.append,
        )
    )

    asyncio.run(
        runner.emit_session_refresh(
            SessionRefreshEvent(reason="model_selection_changed")
        )
    )
    assert (
        asyncio.run(runner.before_session_switch(SimpleNamespace(cwd="/tmp/project")))
        is None
    )
    asyncio.run(runner.emit_context([_user_message("original")], cwd="/tmp/project"))
    asyncio.run(
        runner.before_tool_call(
            BeforeToolCallContext(
                assistant_message=_assistant_tool_call_message(),
                tool_call=_assistant_tool_call_message().content[0],
                args={"x": 1},
                context=_agent_context(),
            ),
            None,
        )
    )
    asyncio.run(
        runner.after_tool_call(
            AfterToolCallContext(
                assistant_message=_assistant_tool_call_message(),
                tool_call=_assistant_tool_call_message().content[0],
                args={"x": 1},
                result=AgentToolResult(
                    content=[TextPart(type="text", text="original")], details={}
                ),
                is_error=False,
                context=_agent_context(),
            ),
            None,
        )
    )

    assert errors == [
        {
            "extensionPath": "/tmp/broken.py",
            "event": "session_refresh",
            "error": "session_refresh boom",
        },
        {
            "extensionPath": "/tmp/broken.py",
            "event": "session_before_switch",
            "error": "session_before_switch boom",
        },
        {
            "extensionPath": "/tmp/broken.py",
            "event": "context",
            "error": "context boom",
        },
        {
            "extensionPath": "/tmp/broken.py",
            "event": "tool_call",
            "error": "tool_call boom",
        },
        {
            "extensionPath": "/tmp/broken.py",
            "event": "tool_result",
            "error": "tool_result boom",
        },
    ]


def test_extension_runner_emits_agent_lifecycle_events() -> None:
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[object, ...]] = []

    def _agent_start(event, ctx):
        del ctx
        seen.append((event.type,))

    def _turn_start(event, ctx):
        del ctx
        seen.append(
            (
                event.type,
                event.turn_index,
                event.turn_index,
                isinstance(event.timestamp, int),
            )
        )

    def _tool_start(event, ctx):
        del ctx
        seen.append(
            (
                event.type,
                event.tool_call_id,
                event.tool_call_id,
                event.tool_name,
                event.tool_name,
                event.args,
            )
        )

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="events",
                source_path=Path("/tmp/events.py"),
                hooks={
                    "agent_start": [_agent_start],
                    "turn_start": [_turn_start],
                    "tool_execution_start": [_tool_start],
                },
            )
        ]
    )

    asyncio.run(runner.emit_agent_event({"type": "agent_start"}))
    asyncio.run(
        runner.emit_agent_event(
            {"type": "turn_start", "turn_index": 2, "timestamp": 123}
        )
    )
    asyncio.run(
        runner.emit_agent_event(
            {
                "type": "tool_execution_start",
                "tool_call_id": "tc1",
                "tool_name": "bash",
                "args": {"command": "pwd"},
            }
        )
    )

    assert seen == [
        ("agent_start",),
        ("turn_start", 2, 2, True),
        ("tool_execution_start", "tc1", "tc1", "bash", "bash", {"command": "pwd"}),
    ]


def test_extension_runner_emits_runtime_error_for_agent_lifecycle_hook_failure() -> (
    None
):
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    def _broken(event, ctx):
        del event, ctx
        raise RuntimeError("agent start boom")

    errors: list[dict[str, object]] = []
    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="broken",
                source_path=Path("/tmp/broken.py"),
                hooks={"agent_start": [_broken]},
            )
        ]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=[],
            model_selection=None,
            on_error=errors.append,
        )
    )

    asyncio.run(runner.emit_agent_event({"type": "agent_start"}))

    assert [diagnostic.code for diagnostic in runner.get_diagnostics()] == [
        "extension_agent_start_failed"
    ]
    assert errors == [
        {
            "extensionPath": "/tmp/broken.py",
            "event": "agent_start",
            "error": "agent start boom",
        }
    ]


def test_extension_runner_before_agent_start_returns_messages_and_system_prompt() -> (
    None
):
    import asyncio

    from loushang.harness.extensions.agent import (
        BeforeAgentStartResult,
        ExtensionRunner,
        LoadedExtension,
    )

    seen: list[tuple[object, ...]] = []
    retained_contexts: list[object] = []

    def _first(event, ctx):
        seen.append(
            (
                event.type,
                event.prompt,
                event.system_prompt,
                event.system_prompt,
                ctx.get_system_prompt(),
            )
        )
        return BeforeAgentStartResult(
            system_prompt="First override",
            extra_messages=[
                {
                    "customType": "notice",
                    "content": "from extension",
                    "display": True,
                    "details": {"phase": "before"},
                }
            ],
        )

    def _second(event, ctx):
        seen.append((event.type, event.system_prompt, ctx.get_system_prompt()))
        retained_contexts.append(ctx)
        return {"system_prompt": "Second override"}

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="first",
                source_path=Path("/tmp/first.py"),
                hooks={"before_agent_start": [_first]},
            ),
            LoadedExtension(
                name="second",
                source_path=Path("/tmp/second.py"),
                hooks={"before_agent_start": [_second]},
            ),
        ]
    )

    result = asyncio.run(
        runner.emit_before_agent_start(
            prompt="hello",
            images=None,
            system_prompt="Base prompt",
            system_prompt_options={"cwd": "/tmp/project"},
            cwd="/tmp/project",
        )
    )

    assert result is not None
    assert result.system_prompt == "Second override"
    assert result.extra_messages == [
        {
            "customType": "notice",
            "content": "from extension",
            "display": True,
            "details": {"phase": "before"},
        }
    ]
    assert seen == [
        ("before_agent_start", "hello", "Base prompt", "Base prompt", "Base prompt"),
        ("before_agent_start", "First override", "First override"),
    ]
    assert retained_contexts[0].get_system_prompt() == "Second override"


def test_extension_runner_user_bash_returns_first_handler_result() -> None:
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[object, object, str]] = []

    def _first(event, ctx):
        seen.append((event.command, event.exclude_from_context, ctx.cwd))
        return None

    async def _second(event, ctx):
        seen.append((event.command, event.exclude_from_context, ctx.cwd))
        return {"result": {"output": "handled\n", "exitCode": 0}}

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="first",
                source_path=Path("/tmp/first.py"),
                hooks={"user_bash": [_first]},
            ),
            LoadedExtension(
                name="second",
                source_path=Path("/tmp/second.py"),
                hooks={"user_bash": [_second]},
            ),
        ]
    )

    result = asyncio.run(
        runner.emit_user_bash(
            {
                "type": "user_bash",
                "command": "pwd",
                "exclude_from_context": True,
                "cwd": "/tmp/project",
            },
            cwd="/tmp/project",
        )
    )

    assert result == {"result": {"output": "handled\n", "exitCode": 0}}
    assert seen == [("pwd", True, "/tmp/project"), ("pwd", True, "/tmp/project")]


def test_extension_runner_user_bash_reports_runtime_errors() -> None:
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    errors: list[dict[str, object]] = []

    def _broken(event, ctx):
        del event, ctx
        raise RuntimeError("bash hook boom")

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="broken",
                source_path=Path("/tmp/broken.py"),
                hooks={"user_bash": [_broken]},
            )
        ]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=[],
            model_selection=None,
            on_error=errors.append,
        )
    )

    result = asyncio.run(
        runner.emit_user_bash(
            {
                "type": "user_bash",
                "command": "pwd",
                "exclude_from_context": False,
                "cwd": "/tmp/project",
            },
            cwd="/tmp/project",
        )
    )

    assert result is None
    assert [diagnostic.code for diagnostic in runner.get_diagnostics()] == [
        "extension_user_bash_failed"
    ]
    assert errors == [
        {
            "extensionPath": "/tmp/broken.py",
            "event": "user_bash",
            "error": "bash hook boom",
        }
    ]


def test_extension_runner_refresh_runtime_updates_context_visible_state() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[str, tuple[str, ...], object | None]] = []

    def _refresh(event, ctx):
        del event
        seen.append(
            (ctx.cwd, tuple(ctx.get_active_tool_names()), ctx.get_model_selection())
        )

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={"session_refresh": [_refresh]},
            )
        ]
    )

    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/original",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
        )
    )
    runner.refresh_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read", "grep"],
            model_selection={"provider": "demo", "model_id": "demo-model"},
        )
    )
    asyncio.run(runner.emit_session_refresh(object()))

    assert seen == [
        (
            "/tmp/project",
            ("read", "grep"),
            {"provider": "demo", "model_id": "demo-model"},
        )
    ]


def test_extension_runner_bind_runtime_and_emit_session_refresh() -> None:
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionRefreshEvent,
    )

    events: list[tuple[str, str]] = []

    def _session_start(event, ctx):
        del event
        events.append(("start", ctx.cwd))

    def _session_refresh(event, ctx):
        del event
        events.append(("refresh", ctx.cwd))

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={
                    "session_start": [_session_start],
                    "session_refresh": [_session_refresh],
                },
            )
        ]
    )

    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
        )
    )
    asyncio.run(runner.emit_session_start(object()))
    runner.refresh_runtime(
        _runtime_bindings(
            cwd="/tmp/project-two",
            active_tool_names=["read", "grep"],
            model_selection={"provider": "demo", "model_id": "second"},
        )
    )
    asyncio.run(
        runner.emit_session_refresh(SessionRefreshEvent(reason="tools_changed"))
    )

    assert events == [("start", "/tmp/project"), ("refresh", "/tmp/project-two")]


def test_extension_runner_context_queries_are_live_after_refresh() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[tuple[str, ...], object | None]] = []
    held_contexts: list[object] = []
    held_accessors: list[tuple[object, object]] = []

    def _before(event, ctx):
        del event
        held_contexts.append(ctx)
        held_accessors.append((ctx.get_active_tool_names, ctx.get_model_selection))
        seen.append((tuple(ctx.get_active_tool_names()), ctx.get_model_selection()))

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={"session_start": [_before]},
            )
        ]
    )

    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
        )
    )
    asyncio.run(runner.emit_session_start(object()))
    runner.refresh_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read", "grep"],
            model_selection={"provider": "demo", "model_id": "second"},
        )
    )

    original_context = held_contexts[0]
    original_get_active_tool_names, original_get_model_selection = held_accessors[0]

    assert tuple(original_context.get_active_tool_names()) == ("read", "grep")
    assert original_context.get_model_selection() == {
        "provider": "demo",
        "model_id": "second",
    }
    assert tuple(original_get_active_tool_names()) == ("read", "grep")
    assert original_get_model_selection() == {"provider": "demo", "model_id": "second"}

    asyncio.run(runner.emit_session_start(object()))

    assert seen == [
        (("read",), {"provider": "demo", "model_id": "first"}),
        (("read", "grep"), {"provider": "demo", "model_id": "second"}),
    ]


def test_extension_runner_context_mutators_delegate_through_live_runtime_bindings() -> (
    None
):
    from loushang.harness.diagnostics.types import DiagnosticDraft
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    tracker: dict[str, object] = {}
    emitted_diagnostic = DiagnosticDraft(code="demo", message="from extension")

    async def _before(event, ctx):
        del event
        await ctx.set_active_tools(["grep"])
        ctx.request_resource_refresh()
        ctx.record_diagnostic(emitted_diagnostic)
        ctx.shutdown()

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={"session_start": [_before]},
            )
        ]
    )

    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
            tracker=tracker,
        )
    )
    asyncio.run(runner.emit_session_start(object()))

    assert tracker["set_active_tools_calls"] == [["grep"]]
    assert tracker["resource_refresh_requests"] == 1
    assert tracker["recorded_diagnostics"] == [emitted_diagnostic]
    assert tracker["shutdown_calls"] == 1


def test_extension_runner_context_pi_style_session_and_registry_actions_delegate() -> (
    None
):
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    tracker: dict[str, object] = {}
    seen: list[tuple[object, ...]] = []

    async def _before(event, ctx):
        del event
        await ctx.set_active_tools(["read", "grep"])
        await ctx.append_entry("demo_state", {"enabled": True})
        await ctx.send_message(
            {"customType": "demo_message", "content": "hello"}, {"triggerTurn": False}
        )
        await ctx.send_user_message("run this", {"deliverAs": "followUp"})
        await ctx.set_session_name("Demo")
        await ctx.set_label("entry-1", "Bookmark")
        seen.append(
            (
                ctx.get_active_tool_names(),
                ctx.get_all_tools(),
                ctx.get_session_name(),
                ctx.list_commands(),
            )
        )

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={"session_start": [_before]},
            )
        ]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
            tracker=tracker,
        )
    )
    asyncio.run(runner.emit_session_start(object()))

    assert tracker["set_active_tools_calls"] == [["read", "grep"]]
    assert tracker["append_entry_calls"] == [("demo_state", {"enabled": True})]
    assert tracker["send_message_calls"] == [
        ({"customType": "demo_message", "content": "hello"}, {"triggerTurn": False})
    ]
    assert tracker["send_user_message_calls"] == [
        ("run this", {"deliverAs": "followUp"})
    ]
    assert tracker["set_session_name_calls"] == ["Demo"]
    assert tracker["set_label_calls"] == [("entry-1", "Bookmark")]
    assert seen == [
        (
            ["read"],
            [{"name": "read"}, {"name": "grep"}],
            "Demo Session",
            [],
        )
    ]


def test_extension_runner_context_runtime_state_methods_delegate_through_bindings() -> (
    None
):
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[object, ...]] = []
    context_usage = {"tokens": 123, "contextWindow": 1000, "percent": 12.3}
    tracker: dict[str, object] = {}

    async def _before(event, ctx):
        del event
        ctx.abort()
        await ctx.compact({"customInstructions": "summarize aggressively"})
        seen.append(
            (
                ctx.is_idle(),
                ctx.is_idle(),
                ctx.has_pending_messages(),
                ctx.has_pending_messages(),
                ctx.get_context_usage(),
                ctx.get_system_prompt(),
                ctx.get_system_prompt(),
            )
        )

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={"session_start": [_before]},
            )
        ]
    )

    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
            tracker=tracker,
            is_idle=lambda: False,
            has_pending_messages=lambda: True,
            get_context_usage=lambda: context_usage,
            get_system_prompt=lambda: "system prompt",
        )
    )
    asyncio.run(runner.emit_session_start(object()))

    assert tracker["abort_calls"] == 1
    assert tracker["compact_calls"] == ["summarize aggressively"]
    assert seen == [
        (
            False,
            False,
            True,
            True,
            context_usage,
            "system prompt",
            "system prompt",
        )
    ]


def test_extension_runner_context_exposes_pi_style_runtime_properties() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[object, ...]] = []
    session_manager = object()
    model_registry = object()
    signal = object()
    model_selection = {"provider": "demo", "model_id": "first"}

    def _before(event, ctx):
        del event
        seen.append(
            (
                ctx.session_manager,
                ctx.session_manager,
                ctx.model_registry,
                ctx.model_registry,
                ctx.model,
                ctx.signal,
            )
        )

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={"session_start": [_before]},
            )
        ]
    )

    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection=model_selection,
            session_manager=session_manager,
            model_registry=model_registry,
            get_signal=lambda: signal,
        )
    )
    asyncio.run(runner.emit_session_start(object()))

    assert seen == [
        (
            session_manager,
            session_manager,
            model_registry,
            model_registry,
            model_selection,
            signal,
        )
    ]


def test_extension_runner_command_context_wait_for_idle_and_reload_delegate_through_bindings() -> (
    None
):
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    tracker: dict[str, object] = {}
    runner = ExtensionRunner(
        [LoadedExtension(name="demo", source_path=Path("/tmp/extensions/demo.py"))]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
            tracker=tracker,
        )
    )

    async def scenario() -> None:
        context = runner.create_command_context(fallback_cwd="/tmp/project")
        assert await context.wait_for_idle() is None
        assert await context.wait_for_idle() is None
        assert await context.reload() is None

    asyncio.run(scenario())

    assert tracker["wait_for_idle_calls"] == 2
    assert tracker["reload_calls"] == 1


def test_extension_runner_command_context_navigate_tree_delegates_through_bindings() -> (
    None
):
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    tracker: dict[str, object] = {}
    runner = ExtensionRunner(
        [LoadedExtension(name="demo", source_path=Path("/tmp/extensions/demo.py"))]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
            tracker=tracker,
        )
    )

    async def scenario() -> None:
        context = runner.create_command_context(fallback_cwd="/tmp/project")
        assert await context.navigate_tree(
            "entry-1", {"summarize": True, "customInstructions": "brief"}
        ) == {"cancelled": False}
        assert await context.navigate_tree("entry-2", {"label": "keep"}) == {
            "cancelled": False
        }

    asyncio.run(scenario())

    assert tracker["navigate_tree_calls"] == [
        ("entry-1", {"summarize": True, "customInstructions": "brief"}),
        ("entry-2", {"label": "keep"}),
    ]


def test_extension_runner_command_context_fork_delegates_through_bindings() -> None:
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    tracker: dict[str, object] = {}
    runner = ExtensionRunner(
        [LoadedExtension(name="demo", source_path=Path("/tmp/extensions/demo.py"))]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
            tracker=tracker,
        )
    )

    async def scenario() -> None:
        context = runner.create_command_context(fallback_cwd="/tmp/project")
        assert await context.fork("entry-1") == {"cancelled": False}

    asyncio.run(scenario())

    assert tracker["fork_calls"] == ["entry-1"]


def test_extension_runner_command_context_new_and_switch_session_delegate_through_bindings() -> (
    None
):
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    tracker: dict[str, object] = {}
    runner = ExtensionRunner(
        [LoadedExtension(name="demo", source_path=Path("/tmp/extensions/demo.py"))]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
            tracker=tracker,
        )
    )

    async def scenario() -> None:
        context = runner.create_command_context(fallback_cwd="/tmp/project")
        assert await context.new_session({"parentSession": "parent-1"}) == {
            "cancelled": False
        }
        assert await context.new_session({"parent_session": "parent-2"}) == {
            "cancelled": False
        }
        assert await context.switch_session("/tmp/session.jsonl") == {
            "cancelled": False
        }
        assert await context.switch_session(
            "/tmp/other.jsonl", {"withSession": "ignored"}
        ) == {"cancelled": False}

    asyncio.run(scenario())

    assert tracker["new_session_calls"] == [
        {"parentSession": "parent-1"},
        {"parent_session": "parent-2"},
    ]
    assert tracker["switch_session_calls"] == [
        ("/tmp/session.jsonl", None),
        ("/tmp/other.jsonl", {"withSession": "ignored"}),
    ]


def test_extension_runner_command_context_exec_command_delegates_through_bindings() -> (
    None
):
    import asyncio

    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.workspace.exec import ExecOutputChunk, ExecResult

    calls: list[tuple[object, object, dict[str, object]]] = []
    updates: list[ExecOutputChunk] = []
    signal = object()

    async def _exec_command(command, args=(), **options):
        calls.append((command, args, dict(options)))
        on_update = options.get("on_update")
        if callable(on_update):
            update = on_update(ExecOutputChunk(stream="stderr", text="warn\n"))
            if inspect.isawaitable(update):
                await update
        return ExecResult(exit_code=2, stderr="warn\n")

    runner = ExtensionRunner(
        [LoadedExtension(name="demo", source_path=Path("/tmp/extensions/demo.py"))]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
            exec_command=_exec_command,
        )
    )

    async def scenario() -> None:
        context = runner.create_command_context(fallback_cwd="/tmp/project")
        result = await context.exec_command(
            "git",
            ["status", "--short"],
            cwd="repo",
            env={"LOUSHANG": "1"},
            timeout_seconds=5,
            stdin="payload",
            signal=signal,
            on_update=updates.append,
            preview_max_lines=3,
            preview_max_bytes=128,
            artifact_dir="/tmp/artifacts",
            capture_full_output=False,
            rolling_max_bytes=1024,
        )
        assert result.exit_code == 2

    asyncio.run(scenario())

    assert updates == [ExecOutputChunk(stream="stderr", text="warn\n")]
    assert len(calls) == 1
    command, args, options = calls[0]
    assert command == "git"
    assert args == ["status", "--short"]
    assert options == {
        "cwd": "repo",
        "env": {"LOUSHANG": "1"},
        "timeout_seconds": 5,
        "stdin": "payload",
        "signal": signal,
        "on_update": updates.append,
        "preview_max_lines": 3,
        "preview_max_bytes": 128,
        "artifact_dir": "/tmp/artifacts",
        "capture_full_output": False,
        "rolling_max_bytes": 1024,
    }


def test_extension_runner_invalidates_captured_runtime_contexts() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    runner = ExtensionRunner(
        [LoadedExtension(name="demo", source_path=Path("/tmp/extensions/demo.py"))]
    )
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
        )
    )
    old_context = runner.create_command_context(fallback_cwd="/tmp/project")

    runner.invalidate_contexts("stale command context")
    new_context = runner.create_command_context(fallback_cwd="/tmp/project")

    with pytest.raises(RuntimeError, match="stale command context"):
        old_context.cwd
    assert new_context.cwd == "/tmp/project"


def test_extension_runner_context_exposes_standard_ui_namespace_and_has_ui() -> None:
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension

    seen: list[tuple[bool, bool, bool]] = []

    def _before(event, ctx):
        del event
        seen.append((ctx.ui is ctx, ctx.has_ui, ctx.has_ui))

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={"session_start": [_before]},
            )
        ]
    )

    asyncio.run(runner.emit_session_start(object()))
    runner.bind_runtime(
        _runtime_bindings(
            cwd="/tmp/project",
            active_tool_names=["read"],
            model_selection={"provider": "demo", "model_id": "first"},
            ui_context=object(),
        )
    )
    asyncio.run(runner.emit_session_start(object()))

    assert seen == [(True, False, False), (True, True, True)]


def test_extension_runner_emits_tree_and_compact_decision_hooks() -> None:
    from loushang.harness.extensions.agent import (
        ExtensionRunner,
        LoadedExtension,
        SessionBeforeCompactEvent,
        SessionBeforeCompactResult,
        SessionBeforeForkEvent,
        SessionBeforeForkResult,
        SessionBeforeTreeEvent,
        SessionBeforeTreeResult,
    )
    from loushang.harness.transcript import BranchSummaryOutput, CompactionResult

    seen: list[tuple[str, str]] = []

    def _before_tree(event, ctx):
        del ctx
        seen.append(("tree", event.target_id))
        return SessionBeforeTreeResult(cancel=True, label="first")

    def _before_compact(event, ctx):
        del ctx
        seen.append(("compact", event.reason))
        return SessionBeforeCompactResult(cancel=True)

    def _before_fork(event, ctx):
        del ctx
        seen.append(("fork", event.entry_id))
        return SessionBeforeForkResult(cancel=True, skip_conversation_restore=True)

    async def _after_tree(event, ctx):
        del ctx
        seen.append(("tree2", event.target_id))
        return SessionBeforeTreeResult(
            summary=BranchSummaryOutput(summary="summarized"),
            custom_instructions="custom",
            label="tree2",
        )

    async def _after_compact(event, ctx):
        del ctx
        seen.append(("compact2", event.reason))
        return SessionBeforeCompactResult(
            compaction=CompactionResult(
                summary="extension",
                first_kept_entry_id="root",
                tokens_before=99,
            )
        )

    async def _after_fork(event, ctx):
        del ctx
        seen.append(("fork2", event.entry_id))
        return SessionBeforeForkResult(skip_conversation_restore=True)

    runner = ExtensionRunner(
        [
            LoadedExtension(
                name="demo",
                source_path=Path("/tmp/extensions/demo.py"),
                hooks={
                    "session_before_tree": [_before_tree],
                    "session_before_compact": [_before_compact],
                    "session_before_fork": [_before_fork],
                },
            ),
            LoadedExtension(
                name="demo-2",
                source_path=Path("/tmp/extensions/demo2.py"),
                hooks={
                    "session_before_tree": [_after_tree],
                    "session_before_compact": [_after_compact],
                    "session_before_fork": [_after_fork],
                },
            ),
        ]
    )

    tree_decision = asyncio.run(
        runner.before_session_tree(
            SessionBeforeTreeEvent(
                target_id="entry-1", old_leaf_id="entry-2", cwd="/tmp/project"
            )
        )
    )
    compact_decision = asyncio.run(
        runner.before_session_compact(
            SessionBeforeCompactEvent(reason="manual", cwd="/tmp/project")
        )
    )
    fork_decision = asyncio.run(
        runner.before_session_fork(
            SessionBeforeForkEvent(entry_id="entry-3", cwd="/tmp/project")
        )
    )

    assert tree_decision == SessionBeforeTreeResult(
        summary=BranchSummaryOutput(summary="summarized"),
        custom_instructions="custom",
        label="tree2",
    )
    assert compact_decision == SessionBeforeCompactResult(
        compaction=CompactionResult(
            summary="extension",
            first_kept_entry_id="root",
            tokens_before=99,
        )
    )
    assert fork_decision == SessionBeforeForkResult(skip_conversation_restore=True)
    assert seen == [
        ("tree", "entry-1"),
        ("tree2", "entry-1"),
        ("compact", "manual"),
        ("compact2", "manual"),
        ("fork", "entry-3"),
        ("fork2", "entry-3"),
    ]
