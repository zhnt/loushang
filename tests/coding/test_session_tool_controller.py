from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.agent import Agent
from loushang.agent.types import AgentToolResult
from loushang.harness.diagnostics import DiagnosticsService
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime import RegistrationOwner
from loushang.harness.session.tool_controller import ToolController
from loushang.harness.tools.core import tool
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace import ToolContext, ToolDefinition, direct_tool
from loushang.harness.tools.workspace.registry import (
    WorkspaceToolRegistry as ToolRegistry,
)


async def _execute_noop(
    tool_call_id: str, params: dict[str, object], signal=None, on_update=None
):
    del tool_call_id, params, signal, on_update
    return AgentToolResult(content=[], details={})


def _tool_definition(
    name: str,
    *,
    label: str | None = None,
    description: str | None = None,
    prompt_snippet: str | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        label=label or name.replace("_", " ").title(),
        description=description or f"{name} tool",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        execution=direct_execution(_execute_noop),
        prompt_snippet=prompt_snippet,
    )


def _active_runtime_tool_controller() -> tuple[
    ToolController,
    ToolRegistry,
    Agent,
    ToolDefinition,
    ToolDefinition,
]:
    registry = ToolRegistry()
    original = _tool_definition(
        "runtime_tool",
        description="Original runtime tool",
        prompt_snippet="- runtime_tool: original behavior",
    )
    replacement = _tool_definition(
        "runtime_tool",
        description="Replacement runtime tool",
        prompt_snippet="- runtime_tool: replacement behavior",
    )
    registry.register_tool(original)
    agent = Agent(initial_state={"system_prompt": "stale", "tools": []})
    controller = ToolController(
        agent=agent,
        get_cwd=lambda: "/tmp/project",
        tool_registry=registry,
        allowed_tool_names=None,
        initial_active_tool_names=["runtime_tool"],
        base_prompt="Base prompt.",
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
    )
    controller.apply_active_tools(["runtime_tool"])
    return controller, registry, agent, original, replacement


def test_tool_controller_materializes_active_registry_tools_and_rebuilds_prompt(
    tmp_path,
) -> None:
    @tool(prompt_snippet="Show the session cwd.")
    async def show_session_cwd(ctx: ToolContext) -> str:
        """Show the session cwd."""
        return ctx.cwd or ""

    registry = ToolRegistry()
    registry.register_tool(direct_tool(show_session_cwd))
    agent = Agent(initial_state={"system_prompt": "stale prompt", "tools": []})
    diagnostics = DiagnosticsService()

    controller = ToolController(
        agent=agent,
        get_cwd=lambda: "/tmp/project",
        tool_registry=registry,
        allowed_tool_names=None,
        initial_active_tool_names=["show_session_cwd"],
        base_prompt="Base prompt.",
        get_resource_bundle=lambda: ResourceBundle(
            cwd=Path("/tmp/project"), prompt_fragments=["Repo rules"]
        ),
        get_diagnostics_service=lambda: diagnostics,
    )
    controller.apply_active_tools(["show_session_cwd"])

    result = asyncio.run(agent.tools[0].execute("call-1", {}))

    assert controller.get_active_tool_names() == ["show_session_cwd"]
    assert result.content[0].text == "/tmp/project"
    assert "Base prompt." in agent.system_prompt
    assert "Repo rules" in agent.system_prompt
    assert "Available tools:\n- show_session_cwd:" in agent.system_prompt


def test_tool_controller_filters_allowed_visible_and_active_tools(tmp_path) -> None:
    async def _execute(
        tool_call_id: str, params: dict[str, object], signal=None, on_update=None
    ):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    registry = ToolRegistry()
    registry.register_tool(
        ToolDefinition(
            name="read",
            label="Read",
            description="Read files",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            execution=direct_execution(_execute),
        )
    )
    registry.register_tool(
        ToolDefinition(
            name="bash",
            label="Bash",
            description="Run commands",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            execution=direct_execution(_execute),
        )
    )
    controller = ToolController(
        agent=Agent(initial_state={"tools": []}),
        get_cwd=lambda: "/tmp/project",
        tool_registry=registry,
        allowed_tool_names={"read"},
        initial_active_tool_names=["bash", "read", "missing"],
        base_prompt="Base prompt.",
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
    )

    controller.apply_active_tools(["bash", "read", "missing"])

    assert controller.get_active_tool_names() == ["read"]
    assert [definition.name for definition in controller.get_all_tools()] == ["read"]
    assert controller.get_tool_definition("bash") is None
    assert [tool.name for tool in controller.agent.tools] == ["read"]


def test_tool_controller_rejects_raw_runtime_tools_when_registry_is_absent(
    tmp_path,
) -> None:
    del tmp_path

    class RuntimeTool:
        name = "runtime_tool"
        label = "Runtime Tool"
        description = "runtime tool"
        parameters = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }
        prepare_arguments = None
        execution_mode = "parallel"

        async def execute(
            self,
            tool_call_id: str,
            params: dict[str, object],
            signal=None,
            on_update=None,
        ):
            del tool_call_id, params, signal, on_update
            return AgentToolResult(content=[], details={})

    agent = Agent(initial_state={"tools": [RuntimeTool()]})
    with pytest.raises(TypeError, match="explicitly bound ToolDefinitions"):
        ToolController(
            agent=agent,
            get_cwd=lambda: "/tmp/project",
            tool_registry=None,
            allowed_tool_names=None,
            initial_active_tool_names=["runtime_tool"],
            base_prompt="Base prompt.",
            get_resource_bundle=lambda: None,
            get_diagnostics_service=lambda: None,
        )


def test_tool_controller_routes_runtime_registration_through_contribution_resolver(
    tmp_path,
    monkeypatch,
) -> None:
    import loushang.harness.session.tool_controller as tool_controller
    from loushang.harness.tools.contribution import resolve_tool_contributions

    base_tool = _tool_definition("read", label="Read", description="Read files")
    runtime_tool = _tool_definition(
        "runtime_tool",
        label="Runtime Tool",
        description="Registered at runtime",
    )
    registry = ToolRegistry()
    registry.register_tool(base_tool, source_info={"source": "base"})
    runtime_source_info = {
        "source": "extension",
        "path": str(tmp_path / "extension.py"),
    }
    calls: list[
        tuple[tuple[str, ...], object | None, dict[str, object], dict[str, object]]
    ] = []

    def spy_resolver(contributions, **kwargs):
        contribution_tuple = tuple(contributions)
        runtime_contribution = contribution_tuple[-1]
        calls.append(
            (
                tuple(
                    contribution.definition.name for contribution in contribution_tuple
                ),
                runtime_contribution.source_info,
                dict(runtime_contribution.metadata),
                dict(kwargs),
            )
        )
        return resolve_tool_contributions(contribution_tuple, **kwargs)

    monkeypatch.setattr(
        tool_controller, "resolve_tool_contributions", spy_resolver, raising=False
    )
    controller = ToolController(
        agent=Agent(initial_state={"tools": []}),
        get_cwd=lambda: "/tmp/project",
        tool_registry=registry,
        allowed_tool_names=None,
        initial_active_tool_names=[],
        base_prompt="Base prompt.",
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
    )

    definition = controller.register_runtime_tool(
        runtime_tool, source_info=runtime_source_info
    )

    assert definition.name == "runtime_tool"
    assert calls == [
        (
            ("read", "runtime_tool"),
            runtime_source_info,
            {
                "kind": "runtime_tool",
                "runtime_tool": "runtime_tool",
            },
            {"fail_on_errors": False},
        )
    ]
    assert [definition.name for definition in registry.list_definitions()] == [
        "read",
        "runtime_tool",
    ]
    assert registry.get_source_info("runtime_tool") == runtime_source_info


def test_tool_controller_registers_selected_runtime_resolver_contribution(
    tmp_path,
    monkeypatch,
) -> None:
    import loushang.harness.session.tool_controller as tool_controller
    from loushang.harness.tools.contribution import (
        ToolContribution,
        ToolResolutionResult,
    )

    runtime_tool = _tool_definition(
        "runtime_tool",
        description="Original runtime contribution",
    )
    selected_tool = _tool_definition(
        "runtime_tool",
        description="Selected runtime contribution",
    )
    selected_source_info = {"source": "resolver"}

    def fake_resolver(contributions, **kwargs):
        del kwargs
        original_contribution = tuple(contributions)[-1]
        selected_contribution = ToolContribution(
            selected_tool,
            source_info=selected_source_info,
            metadata=original_contribution.metadata,
        )
        return ToolResolutionResult(
            contributions=(selected_contribution,),
            definitions=(selected_contribution.definition,),
        )

    monkeypatch.setattr(tool_controller, "resolve_tool_contributions", fake_resolver)
    registry = ToolRegistry()
    controller = ToolController(
        agent=Agent(initial_state={"tools": []}),
        get_cwd=lambda: "/tmp/project",
        tool_registry=registry,
        allowed_tool_names=None,
        initial_active_tool_names=[],
        base_prompt="Base prompt.",
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
    )

    definition = controller.register_runtime_tool(
        runtime_tool, source_info={"source": "runtime"}
    )

    assert definition.description == "Selected runtime contribution"
    assert (
        registry.get_definition("runtime_tool").description
        == "Selected runtime contribution"
    )
    assert registry.get_source_info("runtime_tool") == selected_source_info


def test_tool_controller_runtime_registration_preserves_duplicate_overwrite_behavior(
    tmp_path,
) -> None:
    registry = ToolRegistry()
    registry.register_tool(
        _tool_definition("runtime_tool", description="Original runtime tool"),
        source_info={"source": "existing"},
    )
    controller = ToolController(
        agent=Agent(initial_state={"tools": []}),
        get_cwd=lambda: "/tmp/project",
        tool_registry=registry,
        allowed_tool_names=None,
        initial_active_tool_names=[],
        base_prompt="Base prompt.",
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
    )

    definition = controller.register_runtime_tool(
        _tool_definition("runtime_tool", description="Replacement runtime tool"),
        source_info={"source": "runtime"},
    )

    assert definition.description == "Replacement runtime tool"
    assert [definition.name for definition in registry.list_definitions()] == [
        "runtime_tool"
    ]
    assert (
        registry.get_definition("runtime_tool").description
        == "Replacement runtime tool"
    )
    assert registry.get_source_info("runtime_tool") == {"source": "runtime"}


def test_tool_controller_rebinds_active_same_name_runtime_replacement(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register_tool(
        _tool_definition(
            "runtime_tool",
            description="Original runtime tool",
            prompt_snippet="- runtime_tool: original behavior",
        )
    )
    agent = Agent(initial_state={"system_prompt": "stale", "tools": []})
    controller = ToolController(
        agent=agent,
        get_cwd=lambda: "/tmp/project",
        tool_registry=registry,
        allowed_tool_names=None,
        initial_active_tool_names=["runtime_tool"],
        base_prompt="Base prompt.",
        get_resource_bundle=lambda: None,
        get_diagnostics_service=lambda: None,
    )
    controller.apply_active_tools(["runtime_tool"])

    controller.register_runtime_tool(
        _tool_definition(
            "runtime_tool",
            description="Replacement runtime tool",
            prompt_snippet="- runtime_tool: replacement behavior",
        ),
        source_info={"source": "runtime"},
    )

    assert controller.get_active_tool_names() == ["runtime_tool"]
    assert [tool.description for tool in agent.tools] == ["Replacement runtime tool"]
    assert "- runtime_tool: replacement behavior" in agent.system_prompt
    assert "- runtime_tool: original behavior" not in agent.system_prompt


def test_tool_controller_live_binding_restores_active_tool_and_prompt(
    tmp_path,
) -> None:
    del tmp_path
    controller, _registry, agent, _original, replacement = (
        _active_runtime_tool_controller()
    )

    lease = controller.bind_runtime_tool(
        replacement,
        owner=RegistrationOwner(
            owner_kind="extension",
            owner_id="demo",
            runtime_id="session-1",
            generation=0,
        ),
        source_info={"source": "runtime"},
    )

    assert [tool.description for tool in agent.tools] == ["Replacement runtime tool"]
    assert "- runtime_tool: replacement behavior" in agent.system_prompt

    assert asyncio.run(lease.dispose()).state == "removed"
    assert controller.get_active_tool_names() == ["runtime_tool"]
    assert [tool.description for tool in agent.tools] == ["Original runtime tool"]
    assert "- runtime_tool: original behavior" in agent.system_prompt
    assert "- runtime_tool: replacement behavior" not in agent.system_prompt


def test_tool_controller_live_bind_rolls_back_when_view_rebind_fails() -> None:
    controller, registry, agent, original, replacement = (
        _active_runtime_tool_controller()
    )
    stable_prompt = agent.system_prompt
    rebuild_prompt = controller._runtime.rebuild_prompt
    failures_remaining = 1

    def fail_once(definitions: list[ToolDefinition] | None) -> None:
        nonlocal failures_remaining
        if failures_remaining:
            failures_remaining -= 1
            raise RuntimeError("injected prompt failure")
        rebuild_prompt(definitions)

    controller._runtime.rebuild_prompt = fail_once
    with pytest.raises(RuntimeError, match="injected prompt failure"):
        controller.bind_runtime_tool(
            replacement,
            owner=RegistrationOwner(
                owner_kind="extension",
                owner_id="demo",
                runtime_id="session-1",
                generation=0,
            ),
        )

    assert registry.list_definitions() == [original]
    assert [tool.description for tool in agent.tools] == ["Original runtime tool"]
    assert agent.system_prompt == stable_prompt


def test_tool_controller_live_dispose_retries_view_rebind_after_exact_removal() -> (
    None
):
    controller, registry, agent, original, replacement = (
        _active_runtime_tool_controller()
    )
    lease = controller.bind_runtime_tool(
        replacement,
        owner=RegistrationOwner(
            owner_kind="extension",
            owner_id="demo",
            runtime_id="session-1",
            generation=0,
        ),
    )
    rebuild_prompt = controller._runtime.rebuild_prompt
    failures_remaining = 1

    def fail_once(definitions: list[ToolDefinition] | None) -> None:
        nonlocal failures_remaining
        if failures_remaining:
            failures_remaining -= 1
            raise RuntimeError("injected prompt failure")
        rebuild_prompt(definitions)

    controller._runtime.rebuild_prompt = fail_once

    assert asyncio.run(lease.dispose()).state == "failed_retryable"
    assert registry.list_definitions() == [original]
    assert [tool.description for tool in agent.tools] == ["Original runtime tool"]
    assert "- runtime_tool: replacement behavior" in agent.system_prompt

    assert asyncio.run(lease.dispose()).state == "already_removed"
    assert "- runtime_tool: original behavior" in agent.system_prompt
    assert "- runtime_tool: replacement behavior" not in agent.system_prompt


def test_tool_controller_runtime_registration_preserves_default_activation(
    tmp_path,
) -> None:
    registry = ToolRegistry()
    agent = Agent(initial_state={"system_prompt": "stale", "tools": []})
    controller = ToolController(
        agent=agent,
        get_cwd=lambda: "/tmp/project",
        tool_registry=registry,
        allowed_tool_names=None,
        initial_active_tool_names=[],
        base_prompt="Base prompt.",
        get_resource_bundle=lambda: ResourceBundle(
            cwd=Path("/tmp/project"), prompt_fragments=[]
        ),
        get_diagnostics_service=lambda: None,
        default_activate_new_tools=True,
    )

    controller.register_runtime_tool(
        _tool_definition(
            "runtime_tool",
            description="Runtime tool",
            prompt_snippet="- runtime_tool: run runtime behavior",
        )
    )

    assert controller.get_active_tool_names() == ["runtime_tool"]
    assert [tool.name for tool in agent.tools] == ["runtime_tool"]
    assert "- runtime_tool: run runtime behavior" in agent.system_prompt
