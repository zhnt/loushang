from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from loushang.harness.tools.execution import direct_execution


def test_extension_api_register_tool_accepts_explicit_direct_tool() -> None:
    from loushang.harness.extensions.agent.api import ExtensionAPI
    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace import direct_tool

    @tool()
    async def greet(name: str) -> str:
        return f"hi {name}"

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo"))
    api.register_tool(direct_tool(greet))
    loaded = api.build_loaded_extension()

    assert loaded.tool_definitions[0].name == "greet"


def test_extension_types_export_registered_command_flag_shortcut_and_input() -> None:
    from loushang.harness.extensions.agent import (
        InputEvent,
        InputEventResult,
        RegisteredCommand,
        RegisteredFlag,
        RegisteredShortcut,
        ResolvedCommand,
        SourceInfo,
    )

    assert RegisteredCommand
    assert RegisteredFlag
    assert RegisteredShortcut
    assert ResolvedCommand
    assert SourceInfo
    assert InputEvent
    assert InputEventResult


def test_extension_command_registration_surface_matches_pi_style_signature() -> None:
    from dataclasses import fields

    from loushang.harness.extensions.agent import RegisteredCommand
    from loushang.harness.extensions.agent.api import ExtensionAPI

    api_signature = inspect.signature(ExtensionAPI.register_command)

    assert "hidden" not in api_signature.parameters
    assert "hidden" not in {field.name for field in fields(RegisteredCommand)}


def test_extension_command_context_is_distinct_from_extension_context() -> None:
    from loushang.harness.extensions.context import (
        ExtensionCommandContext,
        ExtensionContext,
    )

    assert ExtensionCommandContext is not ExtensionContext


def test_extension_api_registers_command_flag_and_shortcut() -> None:
    from loushang.harness.extensions.agent.api import ExtensionAPI
    from loushang.harness.extensions.types import ResolvedCommand
    from loushang.harness.resources.source import SourceInfo

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))

    async def _deploy(args, ctx):
        del args, ctx

    api.register_command("deploy", description="Deploy project", handler=_deploy)
    api.register_flag(
        "plan", type="boolean", description="Enable plan mode", default=False
    )
    api.register_shortcut(
        "ctrl+p", description="Trigger deploy", handler=lambda ctx: None
    )

    loaded = api.build_loaded_extension()

    assert loaded.commands["deploy"].description == "Deploy project"
    assert SourceInfo(path=Path("/tmp/demo.py")).path == Path("/tmp/demo.py")
    assert loaded.flags["plan"].type == "boolean"
    assert loaded.flags["plan"].default is False
    assert loaded.shortcuts["ctrl+p"].description == "Trigger deploy"
    assert ResolvedCommand(
        name="deploy",
        handler=_deploy,
        invocation_name="deploy",
        source_info=SourceInfo(path=Path("/tmp/demo.py")),
        extension_name="demo",
    ).source_info.path == Path("/tmp/demo.py")


def test_extension_api_registers_message_renderer() -> None:
    from loushang.harness.extensions.agent.api import ExtensionAPI

    def _renderer(message, options, theme):
        return (message, options, theme)

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))
    api.register_message_renderer("demo.card", _renderer)
    loaded = api.build_loaded_extension()

    assert loaded.message_renderers == {
        "demo.card": _renderer,
    }


def test_extension_api_runtime_reads_are_empty_before_binding() -> None:
    from loushang.harness.extensions.agent.api import ExtensionAPI

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))

    assert api.get_commands() == []
    assert api.get_active_tools() == []
    assert api.get_all_tools() == []
    assert api.get_flag("missing") is None


def test_extension_api_runtime_actions_are_noop_before_binding() -> None:
    import asyncio

    from loushang.harness.extensions.agent.api import ExtensionAPI

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))

    asyncio.run(api.append_entry("demo"))
    asyncio.run(api.set_session_name("Demo"))
    asyncio.run(api.set_label("entry", "label"))
    asyncio.run(api.set_thinking_level("high"))
    asyncio.run(api.send_message({"customType": "demo"}))
    asyncio.run(api.send_user_message("hello"))
    asyncio.run(api.set_active_tools(["read"]))
    asyncio.run(api.set_model({"provider": "demo", "model_id": "model"}))

    assert api.get_session_name() is None
    assert api.get_thinking_level() == "off"


def test_extension_api_exec_command_requires_runtime_binding() -> None:
    import asyncio

    from loushang.harness.extensions.agent.api import ExtensionAPI

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))

    with pytest.raises(RuntimeError, match="Extension runtime is not bound"):
        asyncio.run(api.exec_command("git", ["status"]))


def test_extension_api_exec_command_delegates_to_runtime_binding() -> None:
    import asyncio
    from types import SimpleNamespace

    from loushang.harness.extensions.agent.api import ExtensionAPI
    from loushang.harness.workspace.exec import ExecOutputChunk, ExecResult

    calls: list[tuple[object, object, dict[str, object]]] = []
    updates: list[ExecOutputChunk] = []

    async def _exec_command(command, args=(), **options):
        calls.append((command, args, dict(options)))
        on_update = options.get("on_update")
        if callable(on_update):
            update = on_update(ExecOutputChunk(stream="stdout", text="ok\n"))
            if inspect.isawaitable(update):
                await update
        return ExecResult(exit_code=0, stdout="ok\n")

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))
    api.bind_runtime_state(
        SimpleNamespace(bindings=SimpleNamespace(exec_command=_exec_command))
    )

    async def scenario() -> None:
        result = await api.exec_command(
            "git",
            ["status", "--short"],
            cwd="/repo",
            env={"LOUSHANG": "1"},
            timeout_seconds=5,
            stdin="input",
            on_update=updates.append,
        )
        assert result.stdout == "ok\n"

    asyncio.run(scenario())

    assert updates == [ExecOutputChunk(stream="stdout", text="ok\n")]
    assert calls == [
        (
            "git",
            ["status", "--short"],
            {
                "cwd": "/repo",
                "env": {"LOUSHANG": "1"},
                "timeout_seconds": 5,
                "stdin": "input",
                "signal": None,
                "on_update": updates.append,
                "preview_max_lines": 2000,
                "preview_max_bytes": 50 * 1024,
                "artifact_dir": None,
                "capture_full_output": True,
                "rolling_max_bytes": 100 * 1024,
            },
        )
    ]


def test_registered_command_requires_async_handler() -> None:
    import pytest

    from loushang.harness.extensions.types import RegisteredCommand

    def _sync_handler(args, ctx):
        del args, ctx

    with pytest.raises(TypeError, match="async callable"):
        RegisteredCommand(name="deploy", handler=_sync_handler)


def test_extension_api_accepts_input_hook() -> None:
    from loushang.harness.extensions.agent.api import ExtensionAPI

    def _input(event, ctx):
        del event, ctx
        return {"action": "continue"}

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))
    api.on("input", _input)
    loaded = api.build_loaded_extension()

    assert loaded.hooks["input"] == [_input]


def test_extension_api_annotates_flag_type_as_literal() -> None:
    from typing import Literal, get_type_hints

    from loushang.harness.extensions.agent.api import ExtensionAPI
    from loushang.harness.extensions.types import RegisteredFlag

    register_flag_hints = get_type_hints(ExtensionAPI.register_flag)
    registered_flag_hints = get_type_hints(RegisteredFlag)

    assert register_flag_hints["type"] == Literal["boolean", "string"]
    assert registered_flag_hints["type"] == Literal["boolean", "string"]


def test_extension_api_rejects_invalid_flag_type() -> None:
    from loushang.harness.extensions.agent.api import ExtensionAPI

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))

    with pytest.raises(ValueError, match="Unsupported flag type"):
        api.register_flag("plan", type="number")  # type: ignore[arg-type]


def test_extension_api_rejects_invalid_flag_default_for_type() -> None:
    from loushang.harness.extensions.agent.api import ExtensionAPI

    api = ExtensionAPI(name="demo", source_path=Path("/tmp/demo.py"))

    with pytest.raises(ValueError, match="Boolean flags must use a boolean default"):
        api.register_flag("plan", type="boolean", default="yes")

    with pytest.raises(ValueError, match="String flags must use a string default"):
        api.register_flag("label", type="string", default=True)


def test_extension_api_v1_core_types_are_available() -> None:
    from loushang.harness.diagnostics.types import DiagnosticDraft
    from loushang.harness.extensions.events import VALID_EXTENSION_EVENTS
    from loushang.harness.extensions.types import (
        BeforeAgentStartResult,
        ContextResult,
        LoadedExtension,
        ToolCallDecision,
        ToolResultDecision,
    )
    from loushang.harness.tools.workspace import ToolDefinition

    async def _execute_tool(
        tool_name: str, arguments: dict[str, object], context, signal
    ):
        return {"tool_name": tool_name, "arguments": arguments}

    def _session_start(event, ctx):
        return None

    tool = ToolDefinition(
        name="demo_tool",
        label="Demo Tool",
        description="Tool from loaded extension",
        parameters={},
        execution=direct_execution(_execute_tool),
    )
    diagnostic = DiagnosticDraft(
        code="demo", message="demo diagnostic", source_path=Path("/tmp/demo")
    )
    loaded = LoadedExtension(
        name="demo_extension",
        source_path=Path("/tmp/demo_extension.py"),
        entry_path=Path("/tmp/demo_extension.py"),
        hooks={"session_start": [_session_start]},
        tool_definitions=[tool],
        diagnostics=[diagnostic],
    )

    assert {
        "session_start",
        "before_agent_start",
        "session_shutdown",
        "session_compact",
        "session_tree",
        "resources_discover",
        "agent_start",
        "agent_end",
        "turn_start",
        "turn_end",
        "message_start",
        "message_update",
        "message_end",
        "tool_execution_start",
        "tool_execution_update",
        "tool_execution_end",
        "user_bash",
        "model_select",
        "context",
        "tool_call",
        "tool_result",
    }.issubset(set(VALID_EXTENSION_EVENTS))
    assert loaded.hooks["session_start"] == [_session_start]
    assert loaded.tool_definitions == [tool]
    assert loaded.diagnostics == [diagnostic]
    assert (
        BeforeAgentStartResult(
            system_prompt_append="Be concise.", block=False
        ).system_prompt_append
        == "Be concise."
    )
    assert ContextResult(messages=[]).messages == []
    assert ToolCallDecision(block=True, reason="blocked").reason == "blocked"
    assert ToolResultDecision(result={"ok": True}).result == {"ok": True}


def test_extension_api_registers_hooks_and_tools() -> None:
    from loushang.harness.extensions.agent.api import ExtensionAPI
    from loushang.harness.tools.workspace import ToolDefinition

    async def _execute_tool(
        tool_name: str, arguments: dict[str, object], context, signal
    ):
        return {"tool_name": tool_name, "arguments": arguments}

    def _session_start(event, ctx):
        return None

    tool = ToolDefinition(
        name="demo_tool",
        label="Demo Tool",
        description="Tool from api",
        parameters={},
        execution=direct_execution(_execute_tool),
    )
    api = ExtensionAPI(
        name="demo_extension",
        source_path=Path("/tmp/demo_extension.py"),
        entry_path=Path("/tmp/demo_extension.py"),
    )

    api.on("session_start", _session_start)
    api.register_tool(tool)
    loaded = api.build_loaded_extension()

    assert loaded.name == "demo_extension"
    assert loaded.hooks["session_start"] == [_session_start]
    assert loaded.tool_definitions == [tool]


def test_extension_api_rejects_unknown_event_names() -> None:
    from loushang.harness.extensions.agent.api import ExtensionAPI

    api = ExtensionAPI(
        name="demo_extension", source_path=Path("/tmp/demo_extension.py")
    )

    try:
        api.on("not_real", lambda event, ctx: None)
    except ValueError as error:
        assert "Unsupported extension event" in str(error)
    else:
        raise AssertionError("Expected ValueError for unsupported event name")


def test_extension_api_v2_core_types_include_session_refresh() -> None:
    from loushang.harness.extensions.events import VALID_EXTENSION_EVENTS

    assert "session_refresh" in VALID_EXTENSION_EVENTS


def test_extension_api_exports_runtime_binding_types() -> None:
    from loushang.harness.extensions.agent import (
        ExtensionRuntimeBindings,
        SessionRefreshEvent,
        SessionShutdownEvent,
        SessionStartEvent,
    )

    assert SessionRefreshEvent
    assert (
        SessionStartEvent(reason="new", previous_session_file="/tmp/old.jsonl").reason
        == "new"
    )
    assert (
        SessionStartEvent(
            reason="new", previous_session_file="/tmp/old.jsonl"
        ).previous_session_file
        == "/tmp/old.jsonl"
    )
    assert SessionStartEvent().type == "session_start"
    assert (
        SessionShutdownEvent(
            reason="resume", target_session_file="/tmp/target.jsonl"
        ).target_session_file
        == "/tmp/target.jsonl"
    )
    assert (
        SessionShutdownEvent(
            reason="resume", target_session_file="/tmp/target.jsonl"
        ).target_session_file
        == "/tmp/target.jsonl"
    )
    assert SessionShutdownEvent().type == "session_shutdown"
    assert ExtensionRuntimeBindings


def test_extension_api_v2_core_types_include_session_control_hooks() -> None:
    from loushang.harness.extensions.agent import (
        SessionActionDecision,
        SessionBeforeCompactEvent,
        SessionBeforeForkEvent,
        SessionBeforeSwitchEvent,
        SessionBeforeTreeEvent,
    )
    from loushang.harness.extensions.events import VALID_EXTENSION_EVENTS

    assert "session_before_switch" in VALID_EXTENSION_EVENTS
    assert "session_before_fork" in VALID_EXTENSION_EVENTS
    assert "session_before_compact" in VALID_EXTENSION_EVENTS
    assert "session_before_tree" in VALID_EXTENSION_EVENTS
    assert (
        SessionBeforeSwitchEvent(reason="new", cwd="/tmp/project").type
        == "session_before_switch"
    )
    assert SessionBeforeSwitchEvent(reason="new", cwd="/tmp/project").reason == "new"
    assert (
        SessionBeforeSwitchEvent(
            reason="resume", cwd="/tmp/project", target_session_file="/tmp/target.jsonl"
        ).target_session_file
        == "/tmp/target.jsonl"
    )
    assert (
        SessionBeforeForkEvent(entry_id="entry-1", cwd="/tmp/project").type
        == "session_before_fork"
    )
    assert (
        SessionBeforeForkEvent(entry_id="entry-1", cwd="/tmp/project").entry_id
        == "entry-1"
    )
    assert (
        SessionBeforeForkEvent(entry_id="entry-1", cwd="/tmp/project").entry_id
        == "entry-1"
    )
    assert (
        SessionBeforeCompactEvent(reason="manual", cwd="/tmp/project").type
        == "session_before_compact"
    )
    assert (
        SessionBeforeCompactEvent(reason="manual", cwd="/tmp/project").reason
        == "manual"
    )
    assert (
        SessionBeforeCompactEvent(
            reason="manual", cwd="/tmp/project", custom_instructions="keep"
        ).custom_instructions
        == "keep"
    )
    assert (
        SessionBeforeTreeEvent(
            target_id="entry-1", old_leaf_id="entry-2", cwd="/tmp/project"
        ).type
        == "session_before_tree"
    )
    assert (
        SessionBeforeTreeEvent(
            target_id="entry-1", old_leaf_id="entry-2", cwd="/tmp/project"
        ).target_id
        == "entry-1"
    )
    tree_event = SessionBeforeTreeEvent(
        target_id="entry-1",
        old_leaf_id="entry-2",
        cwd="/tmp/project",
        new_leaf_id="entry-3",
        custom_instructions="summarize",
        replace_instructions=True,
    )
    assert tree_event.target_id == "entry-1"
    assert tree_event.old_leaf_id == "entry-2"
    assert tree_event.new_leaf_id == "entry-3"
    assert tree_event.custom_instructions == "summarize"
    assert tree_event.replace_instructions is True
    assert SessionActionDecision(cancel=True).cancel is True


def test_extension_api_uses_product_neutral_runtime_context_contract() -> None:
    import inspect
    from collections.abc import Awaitable, Callable
    from typing import get_args, get_origin, get_type_hints

    from loushang.harness.extensions.context import (
        ExtensionCommandContext,
        ExtensionContext,
        ExtensionRuntimeBindings,
    )
    from loushang.harness.runtime import ProductRuntimeBindings

    get_model_selection_hints = get_type_hints(ExtensionContext.get_model_selection)
    set_model_hints = get_type_hints(ExtensionContext.set_model)
    set_active_tools_hints = get_type_hints(ExtensionContext.set_active_tools)
    send_message_hints = get_type_hints(ExtensionContext.send_message)
    send_user_message_hints = get_type_hints(ExtensionContext.send_user_message)
    runtime_binding_hints = get_type_hints(ExtensionRuntimeBindings)

    assert ExtensionRuntimeBindings is ProductRuntimeBindings
    assert get_model_selection_hints["return"] == object | None
    assert set_model_hints["selection"] is object
    assert set_model_hints["return"] is type(None)
    assert set_active_tools_hints["return"] is type(None)
    assert send_message_hints["return"] is type(None)
    assert send_user_message_hints["return"] is type(None)
    assert inspect.iscoroutinefunction(ExtensionContext.set_model)
    assert inspect.iscoroutinefunction(ExtensionContext.set_active_tools)
    assert inspect.iscoroutinefunction(ExtensionContext.append_entry)
    assert inspect.iscoroutinefunction(ExtensionContext.set_session_name)
    assert inspect.iscoroutinefunction(ExtensionContext.set_label)
    assert inspect.iscoroutinefunction(ExtensionContext.set_thinking_level)
    assert inspect.iscoroutinefunction(ExtensionContext.send_message)
    assert inspect.iscoroutinefunction(ExtensionContext.send_user_message)
    assert inspect.iscoroutinefunction(ExtensionCommandContext.send_message)
    assert inspect.iscoroutinefunction(ExtensionCommandContext.send_user_message)
    assert inspect.iscoroutinefunction(ExtensionCommandContext.append_entry)
    assert inspect.iscoroutinefunction(ExtensionCommandContext.set_session_name)
    assert inspect.iscoroutinefunction(ExtensionCommandContext.set_label)

    get_model_selection_binding = runtime_binding_hints["get_model_selection"]
    assert get_origin(get_model_selection_binding) is Callable
    assert get_args(get_model_selection_binding) == ([], object | None)

    set_active_tools_binding = runtime_binding_hints["set_active_tools"]
    assert get_origin(set_active_tools_binding) is Callable
    assert get_args(set_active_tools_binding) == ([list[str]], Awaitable[None])

    set_model_binding = runtime_binding_hints["set_model"]
    assert get_origin(set_model_binding) is Callable
    assert get_args(set_model_binding) == ([object], Awaitable[None])

    for binding_name in (
        "append_entry",
        "set_session_name",
        "set_label",
        "set_thinking_level",
    ):
        mutation_binding = runtime_binding_hints[binding_name]
        assert get_origin(mutation_binding) is Callable
        assert get_args(mutation_binding)[1] == Awaitable[None]


def test_extension_loader_build_extension_adapts_context_and_session_refresh(
    tmp_path,
) -> None:
    from loushang.harness.extensions.agent.loader import ExtensionLoader
    from loushang.harness.resources.types import ExtensionDescriptor

    extension_file = tmp_path / "legacy_builder_v2.py"
    extension_file.write_text(
        """
class LegacyExtension:
    def context(self, event):
        return f"context:{event}"

    def session_refresh(self, event):
        return f"refresh:{event}"


def build_extension():
    return LegacyExtension()
        """.strip()
        + "\n",
        encoding="utf-8",
    )

    loader = ExtensionLoader()
    loaded = loader.load_extensions(
        [
            ExtensionDescriptor(
                name="legacy_builder_v2",
                source_path=extension_file,
                entry_path=extension_file,
            )
        ]
    )

    assert len(loaded) == 1
    assert loaded[0].hooks["context"][0]("ctx-event", object()) == "context:ctx-event"
    assert (
        loaded[0].hooks["session_refresh"][0]("refresh-event", object())
        == "refresh:refresh-event"
    )
