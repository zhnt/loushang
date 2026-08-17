from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loushang.agent.types import AgentTool, AgentToolResult
from loushang.ai.types import TextPart
from loushang.harness.capabilities.commands import (
    CommandRuntimeSource,
    SessionCommandRuntime,
)
from loushang.harness.commands import (
    CommandDescriptor,
    CommandDispatchOutcome,
)
from loushang.harness.conversation import CommandExecutionRecord
from loushang.harness.session.bash import (
    SessionCommandExecutionRuntime,
)
from loushang.harness.session.tool_runtime import SessionToolRuntime
from loushang.harness.tools.contribution import ToolContribution
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import direct_execution
from loushang.harness.workspace.exec import ExecOutputChunk


async def _noop_execute(
    tool_call_id: str,
    params: dict[str, Any],
    signal: object | None,
    on_update: object | None,
) -> AgentToolResult[object]:
    del tool_call_id, params, signal, on_update
    return AgentToolResult(content=[], details={})


def _tool_definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        label=name.title(),
        description=f"{name} tool",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        execution=direct_execution(_noop_execute),
    )


class _Agent:
    def __init__(self) -> None:
        self.tools: list[AgentTool[Any]] = []


class _ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition]) -> None:
        self.definitions = list(definitions)
        self.materialized: list[list[str]] = []

    def get_definition(self, name: str) -> ToolDefinition:
        return next(
            definition for definition in self.definitions if definition.name == name
        )

    def get_source_info(self, name: str) -> object | None:
        self.get_definition(name)
        return None

    def list_contributions(self) -> tuple[ToolContribution, ...]:
        return ()

    def list_definitions(self) -> list[ToolDefinition]:
        return list(self.definitions)

    def list_enabled_definitions(self) -> list[ToolDefinition]:
        return list(self.definitions)

    def materialize_definitions(
        self,
        definitions: list[ToolDefinition],
        *,
        context_provider: Callable[..., object] | None = None,
    ) -> list[AgentTool[Any]]:
        del context_provider
        self.materialized.append([definition.name for definition in definitions])
        return []

    def register_tool(
        self,
        tool: ToolDefinition | object,
        *,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> ToolDefinition:
        del enabled, source_info
        assert isinstance(tool, ToolDefinition)
        self.definitions.append(tool)
        return tool


def test_session_tool_runtime_rebinds_only_product_selected_tools() -> None:
    registry = _ToolRegistry([_tool_definition("read"), _tool_definition("bash")])
    prompt_rebuilds: list[list[str]] = []
    runtime = SessionToolRuntime(
        agent=_Agent(),
        tool_registry=registry,
        allowed_tool_names={"read", "bash"},
        initial_active_tool_names=["read"],
        default_active_tool_names=lambda: ["read"],
        should_activate_new_tool=lambda name, definition: name == definition.name,
        build_tool_context=lambda *, tool_call_id: {"call_id": tool_call_id},
        rebuild_prompt=lambda definitions: prompt_rebuilds.append(
            [definition.name for definition in definitions or ()]
        ),
    )

    runtime.apply_active_tools(["bash", "missing"])

    assert runtime.get_active_tool_names() == ["bash"]
    assert registry.materialized == [["bash"]]
    assert prompt_rebuilds == [["bash"]]


def test_session_command_runtime_keeps_catalog_and_dispatch_precedence_separate() -> (
    None
):
    builtin_descriptor = CommandDescriptor[None](
        name="review",
        description="Built-in review command",
        source="builtin",
    )
    extension_descriptor = CommandDescriptor[None](
        name="review",
        description="Extension review command",
        source="extension",
    )

    def _builtin_handler(command: object) -> CommandDispatchOutcome[str]:
        del command
        return CommandDispatchOutcome.handled_result("builtin")

    def _extension_handler(command: object) -> CommandDispatchOutcome[str]:
        del command
        return CommandDispatchOutcome.handled_result("extension")

    runtime = SessionCommandRuntime(
        sources=(
            CommandRuntimeSource(
                pack_id="product.commands",
                source="product",
                descriptor_priority=300,
                handler_priority=200,
                list_descriptors=lambda: [builtin_descriptor],
                handler_name="builtin",
                handler=_builtin_handler,
            ),
            CommandRuntimeSource(
                pack_id="extension.commands",
                source="extension",
                descriptor_priority=200,
                handler_priority=300,
                list_descriptors=lambda: [extension_descriptor],
                handler_name="extension",
                handler=_extension_handler,
            ),
        )
    )

    descriptors = runtime.list_commands()
    result = asyncio.run(runtime.execute("review", "current change"))

    assert [descriptor.source for descriptor in descriptors] == [
        "builtin",
        "extension",
    ]
    assert result == "extension"


def test_session_command_runtime_stops_after_handled_none_result() -> None:
    calls: list[str] = []

    def _handled_none(command: object) -> CommandDispatchOutcome[str]:
        del command
        calls.append("handled-none")
        return CommandDispatchOutcome.handled_result()

    def _fallback(command: object) -> CommandDispatchOutcome[str]:
        del command
        calls.append("fallback")
        return CommandDispatchOutcome.handled_result("fallback")

    runtime = SessionCommandRuntime(
        sources=(
            CommandRuntimeSource(
                pack_id="handled-none.commands",
                source="product",
                descriptor_priority=200,
                handler_priority=200,
                list_descriptors=tuple,
                handler_name="handled-none",
                handler=_handled_none,
            ),
            CommandRuntimeSource(
                pack_id="fallback.commands",
                source="extension",
                descriptor_priority=100,
                handler_priority=100,
                list_descriptors=tuple,
                handler_name="fallback",
                handler=_fallback,
            ),
        )
    )

    outcome = asyncio.run(runtime.dispatch("review", ""))

    assert outcome.handled is True
    assert outcome.result is None
    assert outcome.handler_name == "handled-none"
    assert calls == ["handled-none"]


def test_command_execution_runtime_streams_and_commits_one_record() -> None:
    records: list[CommandExecutionRecord] = []
    chunks: list[ExecOutputChunk] = []
    refreshes = 0
    executed: list[dict[str, object]] = []

    async def _execute(
        tool_call_id: str,
        params: dict[str, object],
        signal: object | None,
        on_update: Callable[[object], Awaitable[None]] | None,
    ) -> AgentToolResult[object]:
        del tool_call_id, signal
        executed.append(params)
        assert on_update is not None
        await on_update(
            AgentToolResult(
                content=[TextPart(type="text", text="partial\\n")],
                details={"stream": "stdout"},
            )
        )
        return AgentToolResult(
            content=[TextPart(type="text", text="complete\\n")],
            details={"exit_code": 0},
        )

    async def _append(record: CommandExecutionRecord) -> None:
        records.append(record)

    def _refresh() -> None:
        nonlocal refreshes
        refreshes += 1

    definition = ToolDefinition(
        name="bash",
        label="Bash",
        description="Run a shell command",
        parameters={},
        execution=direct_execution(_execute),
    )
    from loushang.harness.tools.core import wrap_tool_definition

    runtime_tool = wrap_tool_definition(definition)

    async def _execute_definition(
        selected_definition,
        *,
        tool_call_id,
        arguments,
        signal=None,
        on_update=None,
        operation_bindings=None,
    ):
        del operation_bindings
        assert selected_definition is definition
        return await runtime_tool.execute(
            tool_call_id,
            arguments,
            signal=signal,
            on_update=on_update,
        )

    runtime = SessionCommandExecutionRuntime(
        command_name="Bash",
        get_cwd=lambda: "/project",
        get_definition=lambda: definition,
        execute_definition=_execute_definition,
        build_execution_params=lambda command, cwd: {
            "command": ["/bin/bash", "-lc", command],
            "cwd": cwd,
        },
        create_call_id=lambda: "call-1",
        append_record=_append,
        refresh_context=_refresh,
    )

    result = asyncio.run(runtime.execute("printf done", on_output=chunks.append))

    assert result["output"] == "complete\\n"
    assert executed == [
        {"command": ["/bin/bash", "-lc", "printf done"], "cwd": "/project"}
    ]
    assert chunks == [ExecOutputChunk(stream="stdout", text="partial\\n")]
    assert records == [
        CommandExecutionRecord(
            command="printf done",
            output="complete\\n",
            exit_code=0,
        )
    ]
    assert refreshes == 1


def test_tool_activation_profile_selects_product_defaults() -> None:
    from loushang.harness.session.tool_controller import ToolActivationProfile

    profile = ToolActivationProfile(
        preferred_names=("read", "bash"),
        builtin_names=frozenset({"read", "bash"}),
        activate_new_tools=True,
    )
    definitions = [_tool_definition("write"), _tool_definition("read")]

    assert profile.default_names(definitions) == ["read", "write"]
    assert profile.default_names(definitions, {"read"}) == ["read"]
    assert profile.should_activate_new("custom", definitions[0]) is True
    assert profile.should_activate_new("read", definitions[1]) is False


def test_capabilities_module_reexports_canonical_runtime_owners() -> None:
    from loushang.harness.capabilities.commands import (
        CommandRuntimeSource as CanonicalCommandRuntimeSource,
    )
    from loushang.harness.session import capabilities
    from loushang.harness.session.bash import (
        BashCommandExecutionRuntime,
        bash_result_from_tool_result,
    )
    from loushang.harness.session.tool_runtime import (
        SessionToolRuntime as CanonicalSessionToolRuntime,
    )

    assert capabilities.CommandRuntimeSource is CanonicalCommandRuntimeSource
    assert capabilities.SessionCommandExecutionRuntime is BashCommandExecutionRuntime
    assert capabilities.SessionToolRuntime is CanonicalSessionToolRuntime
    assert capabilities.command_result_from_tool_result is bash_result_from_tool_result
