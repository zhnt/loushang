from __future__ import annotations

import asyncio
from datetime import date

import pytest

from loushang.agent.types import AgentToolResult
from loushang.harness.tools.execution import direct_execution
from loushang.harness.tools.workspace import ToolContext, direct_tool


def _runtime_footer(cwd: str) -> str:
    return f"Current date: {date.today().isoformat()}\nCurrent working directory: {cwd}"


def test_session_materialized_decorated_tool_receives_session_cwd(tmp_path) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    @tool()
    async def show_session_cwd(ctx: ToolContext) -> str:
        return ctx.cwd or ""

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    registry.register_tool(direct_tool(show_session_cwd))
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )

    agent = Agent(
        initial_state={
            "system_prompt": "stale prompt",
            "model": model,
            "thinking_level": "off",
            "tools": [],
        },
        convert_to_llm=lambda messages: [],
    )

    session = AgentSession(
        agent=agent,
        session_manager=manager,
        tool_registry=registry,
        active_tool_names=["show_session_cwd"],
    )

    result = asyncio.run(session.agent.tools[0].execute("call-1", {}))

    assert result.content[0].text == "/tmp/project"


def test_session_without_registry_rejects_raw_runtime_tools(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession

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

        async def execute(
            self,
            tool_call_id: str,
            params: dict[str, object],
            signal=None,
            on_update=None,
        ):
            del tool_call_id, params, signal, on_update
            return AgentToolResult(content=[], details={})

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )

    agent = Agent(
        initial_state={
            "system_prompt": "stale prompt",
            "model": model,
            "thinking_level": "off",
            "tools": [RuntimeTool()],
        },
        convert_to_llm=lambda messages: [],
    )

    with pytest.raises(TypeError, match="explicitly bound ToolDefinitions"):
        AgentSession(agent=agent, session_manager=manager)


def test_agent_session_tracks_active_tool_names_and_runtime_tools(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    register_builtin_tools(registry)
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )

    agent = Agent(
        initial_state={
            "system_prompt": "stale prompt",
            "model": model,
            "thinking_level": "off",
            "tools": [],
        },
        convert_to_llm=lambda messages: [],
    )

    session = AgentSession(
        agent=agent,
        session_manager=manager,
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"),
            prompt_fragments=["Repo rules"],
        ),
        tool_registry=registry,
        active_tool_names=["bash"],
        base_prompt="Base prompt.",
    )

    assert session.get_active_tool_names() == ["bash"]
    assert session.get_state().active_tool_names == ["bash"]
    assert [tool.name for tool in session.agent.tools] == ["bash"]
    assert [definition.name for definition in session.get_all_tools()] == [
        "bash",
        "read",
        "ls",
        "find",
        "grep",
        "write",
        "edit",
    ]
    assert session.agent.system_prompt == (
        "Base prompt.\n\nRepo rules\n\nAvailable tools:\n"
        "- bash: Execute shell commands. Prefer a single command string; use cwd for the working directory.\n"
        "- Use bash for shell pipelines, redirects, and commands that are easier to express through the user's shell.\n"
        "- Prefer read, grep, find, ls, write, and edit for file operations when those tools are more precise.\n\n"
        f"{_runtime_footer('/tmp/project')}"
    )


def test_agent_session_builtin_tools_command_can_restore_active_tools(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    register_builtin_tools(registry)
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "stale prompt",
                "model": model,
                "thinking_level": "off",
                "tools": [],
            },
            convert_to_llm=lambda messages: [],
        ),
        session_manager=manager,
        resource_bundle=ResourceBundle(cwd=Path("/tmp/project")),
        tool_registry=registry,
        active_tool_names=["bash"],
        base_prompt="Base prompt.",
    )

    off_result = asyncio.run(session.execute_command_async("/tools", "off bash"))
    reset_result = asyncio.run(session.execute_command_async("/tools", "reset"))

    assert off_result is not None
    assert off_result.result["active_tools"] == []
    assert session.get_active_tool_names() == [
        "read",
        "ls",
        "find",
        "grep",
        "bash",
        "edit",
        "write",
    ]
    assert [tool.name for tool in session.agent.tools] == [
        "read",
        "ls",
        "find",
        "grep",
        "bash",
        "edit",
        "write",
    ]
    assert reset_result is not None
    assert reset_result.result["active_tools"] == [
        "read",
        "ls",
        "find",
        "grep",
        "bash",
        "edit",
        "write",
    ]


def test_agent_session_exposes_standard_tool_surfaces(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    registry = ToolRegistry()
    register_builtin_tools(registry)
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "stale prompt",
                "model": model,
                "thinking_level": "off",
                "tools": [],
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"), prompt_fragments=["Repo rules"]
        ),
        tool_registry=registry,
        active_tool_names=["bash"],
        base_prompt="Base prompt.",
    )

    assert session.get_active_tool_names() == ["bash"]
    assert [tool["name"] for tool in session.get_all_tool_infos()] == [
        "bash",
        "read",
        "ls",
        "find",
        "grep",
        "write",
        "edit",
    ]
    assert session.get_all_tool_infos()[0]["sourceInfo"] == {
        "path": "<builtin:bash>",
        "source": "builtin",
        "scope": "temporary",
        "origin": "top-level",
        "baseDir": None,
    }
    assert session.get_tool_definition("bash").name == "bash"
    assert session.get_tool_definition("missing") is None

    asyncio.run(session.set_active_tools(["read", "grep", "missing"]))

    assert session.get_active_tool_names() == ["read", "grep"]
    assert [tool.name for tool in session.agent.tools] == ["read", "grep"]
    assert "Available tools:\n- read:" in session.agent.system_prompt
    assert "- grep:" in session.agent.system_prompt
    assert "- bash:" not in session.agent.system_prompt


def test_agent_session_allowed_tool_names_filter_visible_and_active_tools(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    registry = ToolRegistry()
    register_builtin_tools(registry)
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "stale prompt",
                "model": model,
                "thinking_level": "off",
                "tools": [],
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"), prompt_fragments=["Repo rules"]
        ),
        tool_registry=registry,
        allowed_tool_names=["read", "grep"],
        active_tool_names=["bash", "read", "grep", "missing"],
        base_prompt="Base prompt.",
    )

    assert session.get_active_tool_names() == ["read", "grep"]
    assert [tool.name for tool in session.agent.tools] == ["read", "grep"]
    assert [definition.name for definition in session.get_all_tools()] == [
        "read",
        "grep",
    ]
    assert session.get_tool_definition("bash") is None
    assert "Available tools:\n- read:" in session.agent.system_prompt
    assert "- grep:" in session.agent.system_prompt
    assert "- bash:" not in session.agent.system_prompt

    asyncio.run(session.set_active_tools(["bash", "grep"]))

    assert session.get_active_tool_names() == ["grep"]
    assert [tool.name for tool in session.agent.tools] == ["grep"]


def test_agent_session_extension_context_register_tool_refreshes_active_tools_and_prompt(
    tmp_path,
) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.tools.workspace import ToolDefinition
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    async def execute_dynamic(
        tool_call_id: str, params: dict[str, object], signal=None, on_update=None
    ):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    def _session_start(event, ctx):
        del event
        ctx.register_tool(
            ToolDefinition(
                name="dynamic_tool",
                label="Dynamic Tool",
                description="Tool registered from session_start",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                execution=direct_execution(execute_dynamic),
                prompt_snippet="- dynamic_tool: Run dynamic test behavior",
                prompt_guidelines=(
                    "Use dynamic_tool when the user asks for dynamic behavior tests.",
                ),
            )
        )

    registry = ToolRegistry()
    register_builtin_tools(registry)
    session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base prompt.", "tools": []}),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        resource_bundle=ResourceBundle(cwd=Path("/tmp/project"), prompt_fragments=[]),
        tool_registry=registry,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=Path("<inline:1>"),
                    source="inline",
                    hooks={"session_start": [_session_start]},
                )
            ]
        ),
        base_prompt="Base prompt.",
    )

    assert "dynamic_tool" not in [
        definition.name for definition in session.get_all_tools()
    ]

    asyncio.run(session.reload_extension_runtime())

    assert "dynamic_tool" in [definition.name for definition in session.get_all_tools()]
    assert "dynamic_tool" in session.get_active_tool_names()
    assert "dynamic_tool" in [tool.name for tool in session.agent.tools]
    assert "- dynamic_tool: Run dynamic test behavior" in session.agent.system_prompt
    assert (
        "Use dynamic_tool when the user asks for dynamic behavior tests."
        in session.agent.system_prompt
    )
    dynamic_tool_info = next(
        tool for tool in session.get_all_tool_infos() if tool["name"] == "dynamic_tool"
    )
    assert dynamic_tool_info["sourceInfo"] == {
        "path": "<inline:1>",
        "source": "inline",
        "scope": "temporary",
        "origin": "top-level",
        "baseDir": None,
    }


def test_agent_session_extension_registers_explicit_tool_routes_live(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.tools import (
        FilesystemActionAdapter,
        authorized_tool,
        direct_tool,
        tool,
    )
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    @tool(prompt_snippet="- runtime_ping: Ping the live extension")
    async def runtime_ping() -> str:
        """Return one direct runtime result."""

        return "pong"

    @tool(prompt_snippet="- runtime_save: Save an authorized runtime note")
    async def runtime_save(
        path: str,
        content: str,
        context: ToolContext,
    ) -> str:
        """Save one runtime note through the authorization Gateway."""

        del content
        return str(context.cwd or "") + "/" + path

    def _session_start(event, ctx) -> None:
        del event
        ctx.register_tool(direct_tool(runtime_ping))
        ctx.register_tool(
            authorized_tool(
                runtime_save,
                action=FilesystemActionAdapter(
                    "write",
                    authorization_fields=("content",),
                ),
            )
        )
        with pytest.raises(
            TypeError,
            match=r"direct_tool\(\.\.\.\) or authorized_tool",
        ):
            ctx.register_tool(runtime_ping)

    session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base prompt.", "tools": []}),
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path,
                cwd=str(tmp_path),
                persist=False,
            )
        ),
        tool_registry=WorkspaceToolRegistry(),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="explicit-authoring",
                    source_path=tmp_path / "extension.py",
                    source="inline",
                    hooks={"session_start": [_session_start]},
                )
            ]
        ),
        base_prompt="Base prompt.",
    )

    asyncio.run(session.reload_extension_runtime())

    assert [definition.name for definition in session.get_all_tools()] == [
        "runtime_ping",
        "runtime_save",
    ]
    assert session.get_active_tool_names() == ["runtime_ping", "runtime_save"]
    assert [tool.name for tool in session.agent.tools] == [
        "runtime_ping",
        "runtime_save",
    ]
    assert "runtime_ping" in session.agent.system_prompt
    assert "runtime_save" in session.agent.system_prompt


def test_live_extension_authorized_tool_runs_through_session_gateway(
    tmp_path,
) -> None:
    import json
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.harness.approval import (
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools import (
        FilesystemActionAdapter,
        authorized_tool,
        tool,
    )
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

    class AskForRuntimeWrite:
        def evaluate(self, _subject: object) -> PolicyDecision:
            return PolicyDecision.ask(
                "Confirm the runtime extension write",
                code="runtime_extension_write",
            )

    handler_calls = 0

    @tool(prompt_snippet="- extension_save: Save one approved extension note")
    async def extension_save(
        path: str,
        content: str,
        context: ToolContext,
    ) -> str:
        nonlocal handler_calls
        handler_calls += 1
        target = Path(context.cwd or ".") / path
        target.write_text(content, encoding="utf-8")
        return str(target.resolve())

    def _session_start(event, ctx) -> None:
        del event
        ctx.register_tool(
            authorized_tool(
                extension_save,
                action=FilesystemActionAdapter(
                    "write",
                    authorization_fields=("content",),
                ),
            )
        )

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    presented = asyncio.Event()
    approval_payloads: list[dict[str, object]] = []

    def present(payload: dict[str, object]) -> None:
        approval_payloads.append(dict(payload))
        presented.set()

    session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base prompt.", "tools": []}),
        session_manager=asyncio.run(
            SessionManager.new(
                session_dir=tmp_path,
                cwd=str(tmp_path),
                persist=False,
            )
        ),
        tool_registry=WorkspaceToolRegistry(),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="authorized-runtime",
                    source_path=tmp_path / "extension.py",
                    source="inline",
                    hooks={"session_start": [_session_start]},
                )
            ]
        ),
        approval_resolver=resolver,
        tool_policy_evaluator=AskForRuntimeWrite(),
        base_prompt="Base prompt.",
    )
    session.set_approval_presenter(present)
    product_events: list[dict[str, object]] = []
    session.subscribe(product_events.append)

    async def scenario() -> object:
        await session.reload_extension_runtime()
        tool = next(
            item for item in session.agent.tools if item.name == "extension_save"
        )
        pending = asyncio.create_task(
            tool.execute(
                "runtime-extension-call",
                {
                    "path": "runtime-note.txt",
                    "content": "private-runtime-content",
                },
            )
        )
        await presented.wait()
        assert handler_calls == 0
        assert not (tmp_path / "runtime-note.txt").exists()
        action_id = approval_payloads[0]["action_id"]
        assert isinstance(action_id, str)
        assert await session.handle_screen_approval(
            {
                "action_id": action_id,
                "outcome": "allow_once",
            }
        )
        return await pending

    result = asyncio.run(scenario())
    audit_events = [
        event
        for event in product_events
        if str(event.get("type", "")).startswith("tool_")
    ]

    assert result.details == str((tmp_path / "runtime-note.txt").resolve())
    assert handler_calls == 1
    assert (tmp_path / "runtime-note.txt").read_text(encoding="utf-8") == (
        "private-runtime-content"
    )
    assert [event["type"] for event in audit_events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_requested",
        "tool_approval_resolved",
        "tool_execution_started",
        "tool_execution_completed",
    ]
    assert {event["tool_call_id"] for event in audit_events} == {
        "runtime-extension-call"
    }
    assert len({event["action_fingerprint"] for event in audit_events}) == 1
    assert audit_events[1]["policy_code"] == "runtime_extension_write"
    action_id = audit_events[2]["action_id"]
    assert audit_events[3]["action_id"] == action_id
    assert audit_events[4]["approval_action_id"] == action_id
    assert audit_events[5]["approval_action_id"] == action_id
    serialized = json.dumps(audit_events)
    assert "private-runtime-content" not in serialized
    assert str(tmp_path / "runtime-note.txt") not in serialized


def test_agent_session_extension_api_register_tool_after_runtime_bind_updates_session_tools(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.harness.extensions.agent import ExtensionAPI, ExtensionRunner
    from loushang.harness.tools.workspace import ToolDefinition

    async def execute_dynamic(
        tool_call_id: str, params: dict[str, object], signal=None, on_update=None
    ):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    api = ExtensionAPI(
        name="demo", source_path=tmp_path / "demo.py", entry_path=tmp_path / "demo.py"
    )

    def _session_start(event, ctx):
        del event, ctx
        api.register_tool(
            ToolDefinition(
                name="api_dynamic_tool",
                label="API Dynamic Tool",
                description="Tool registered through the runtime-bound api",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                execution=direct_execution(execute_dynamic),
                prompt_snippet="- api_dynamic_tool: Run api dynamic behavior",
            )
        )

    api.on("session_start", _session_start)
    session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base prompt.", "tools": []}),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        extension_runner=ExtensionRunner([api.build_loaded_extension()]),
        base_prompt="Base prompt.",
    )

    asyncio.run(session.reload_extension_runtime())

    assert [definition.name for definition in session.get_all_tools()] == [
        "api_dynamic_tool"
    ]
    assert session.get_active_tool_names() == ["api_dynamic_tool"]
    assert "- api_dynamic_tool: Run api dynamic behavior" in session.agent.system_prompt
    assert session._extension_tool_registration_leases == []
    assert session._tool_registry is session._composition.tool_controller.tool_registry
    runner = session._extension_runner
    assert isinstance(runner, ExtensionRunner)
    inventory = runner.registration_inventory
    assert len(inventory) == 1
    owner, identity, state = inventory[0]
    assert owner.owner_kind == "extension"
    assert owner.owner_id == "demo"
    assert owner.runtime_id
    assert owner.generation == 1
    assert identity.public_key == "api_dynamic_tool"
    assert state == "active"

    asyncio.run(session.dispose())
    assert session.get_all_tools() == []
    assert session.get_active_tool_names() == []
    assert [tool.name for tool in session.agent.tools] == []
    assert "- api_dynamic_tool: Run api dynamic behavior" not in (
        session.agent.system_prompt
    )


def test_agent_session_dynamic_extension_tools_respect_allowed_tool_names(
    tmp_path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.extensions.agent import ExtensionRunner, LoadedExtension
    from loushang.harness.tools.workspace import ToolDefinition
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    async def execute_dynamic(
        tool_call_id: str, params: dict[str, object], signal=None, on_update=None
    ):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    def _session_start(event, ctx):
        del event
        ctx.register_tool(
            ToolDefinition(
                name="dynamic_tool",
                label="Dynamic Tool",
                description="Tool registered from session_start",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                execution=direct_execution(execute_dynamic),
                prompt_snippet="- dynamic_tool: Run dynamic test behavior",
            )
        )

    registry = ToolRegistry()
    register_builtin_tools(registry)
    session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base prompt.", "tools": []}),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        tool_registry=registry,
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={"session_start": [_session_start]},
                )
            ]
        ),
        allowed_tool_names=["read", "dynamic_tool"],
        active_tool_names=["read", "dynamic_tool"],
        base_prompt="Base prompt.",
    )

    asyncio.run(session.reload_extension_runtime())

    assert [definition.name for definition in session.get_all_tools()] == [
        "read",
        "dynamic_tool",
    ]
    assert session.get_active_tool_names() == ["read", "dynamic_tool"]
    assert "- read:" in session.agent.system_prompt
    assert "- dynamic_tool: Run dynamic test behavior" in session.agent.system_prompt
    assert "- bash:" not in session.agent.system_prompt

    no_tools_session = AgentSession(
        agent=Agent(initial_state={"system_prompt": "Base prompt.", "tools": []}),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        tool_registry=ToolRegistry(),
        extension_runner=ExtensionRunner(
            [
                LoadedExtension(
                    name="demo",
                    source_path=tmp_path / "demo.py",
                    hooks={"session_start": [_session_start]},
                )
            ]
        ),
        allowed_tool_names=[],
        active_tool_names=[],
        base_prompt="Base prompt.",
    )

    asyncio.run(no_tools_session.reload_extension_runtime())

    assert no_tools_session.get_all_tools() == []
    assert no_tools_session.get_active_tool_names() == []
    assert "dynamic_tool" not in no_tools_session.agent.system_prompt


def test_agent_session_get_all_tools_projects_sdk_source_info(tmp_path) -> None:
    from loushang.agent import Agent
    from loushang.agent.types import AgentToolResult
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.harness.tools.workspace import ToolDefinition
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    async def execute_custom_tool(
        tool_call_id: str, params: dict[str, object], signal=None, on_update=None
    ):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    registry = ToolRegistry()
    registry.register_tool(
        ToolDefinition(
            name="custom_tool",
            label="Custom Tool",
            description="custom tool",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            execution=direct_execution(execute_custom_tool),
        )
    )
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )

    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "stale prompt",
                "model": model,
                "thinking_level": "off",
                "tools": [],
            }
        ),
        session_manager=asyncio.run(
            SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
        ),
        tool_registry=registry,
    )

    assert session.get_all_tool_infos() == [
        {
            "name": "custom_tool",
            "description": "custom tool",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "sourceInfo": {
                "path": "<sdk:custom_tool>",
                "source": "sdk",
                "scope": "temporary",
                "origin": "top-level",
                "baseDir": None,
            },
        }
    ]


def test_agent_session_tracks_multiple_builtin_tool_names(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    register_builtin_tools(registry)
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )

    agent = Agent(
        initial_state={
            "system_prompt": "stale prompt",
            "model": model,
            "thinking_level": "off",
            "tools": [],
        },
        convert_to_llm=lambda messages: [],
    )

    session = AgentSession(
        agent=agent,
        session_manager=manager,
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"),
            prompt_fragments=["Repo rules"],
        ),
        tool_registry=registry,
        active_tool_names=["bash", "read", "grep"],
        base_prompt="Base prompt.",
    )

    assert session.get_active_tool_names() == ["bash", "read", "grep"]
    assert [tool.name for tool in session.agent.tools] == ["bash", "read", "grep"]
    assert (
        "read: Read text files and images from the coding workspace."
        in session.agent.system_prompt
    )
    assert (
        "grep: Search file contents for patterns in the coding workspace."
        in session.agent.system_prompt
    )


def test_agent_session_tracks_mutation_builtin_tool_names(tmp_path) -> None:
    from pathlib import Path

    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    register_builtin_tools(registry)
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )

    agent = Agent(
        initial_state={
            "system_prompt": "stale prompt",
            "model": model,
            "thinking_level": "off",
            "tools": [],
        },
        convert_to_llm=lambda messages: [],
    )

    session = AgentSession(
        agent=agent,
        session_manager=manager,
        resource_bundle=ResourceBundle(
            cwd=Path("/tmp/project"),
            prompt_fragments=["Repo rules"],
        ),
        tool_registry=registry,
        active_tool_names=["write", "edit"],
        base_prompt="Base prompt.",
    )

    assert session.get_active_tool_names() == ["write", "edit"]
    assert [tool.name for tool in session.agent.tools] == ["write", "edit"]
    assert (
        "write: Write a text file in the coding workspace."
        in session.agent.system_prompt
    )
    assert (
        "edit: Apply exact text replacements to a file in the coding workspace."
        in session.agent.system_prompt
    )


def test_session_active_tools_still_materialize_after_substrate_migration(
    tmp_path,
) -> None:
    import asyncio

    from loushang.ai.model import Capabilities, Model
    from loushang.coding.bootstrap import create_agent_session
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    @tool()
    async def show_session_cwd(ctx: ToolContext) -> str:
        return ctx.cwd or ""

    registry = ToolRegistry()
    registry.register_tool(direct_tool(show_session_cwd))
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )

    session = create_agent_session(
        session_manager=manager,
        model=model,
        tools=registry.list_enabled_definitions(),
    )

    result = asyncio.run(session.agent.tools[0].execute("call-1", {}))

    assert session.get_active_tool_names() == ["show_session_cwd"]
    assert [tool.name for tool in session.agent.tools] == ["show_session_cwd"]
    assert result.content[0].text == "/tmp/project"


def test_bash_tool_forwards_exec_updates_and_preview_metadata(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecOutputChunk, ExecRequest, ExecResult

    seen_updates: list[AgentToolResult[dict[str, object]]] = []

    class FakeExecService:
        async def execute(
            self, request: ExecRequest, signal=None, on_update=None
        ) -> ExecResult:
            del request, signal
            if on_update is not None:
                await on_update(ExecOutputChunk(stream="stdout", text="chunk-1\n"))
                await on_update(ExecOutputChunk(stream="stderr", text="chunk-err\n"))
            return ExecResult(
                exit_code=0,
                stdout="chunk-1\nchunk-2\nchunk-3\n",
                stderr="chunk-err\n",
                stdout_preview="chunk-2\nchunk-3\n",
                stdout_truncated=True,
                stdout_truncated_by="lines",
                stdout_artifact_path=str(tmp_path / "stdout.log"),
                stderr_preview="chunk-err\n",
                stderr_chunks=("chunk-err\n",),
                stdout_chunks=("chunk-1\n", "chunk-2\n", "chunk-3\n"),
            )

    async def scenario() -> None:
        runtime_tool = wrap_tool_definition(
            create_bash_tool_definition(
                exec_service=FakeExecService(),
            )
        )

        result = await runtime_tool.execute(
            "tool-call-1",
            {"command": ["/bin/sh", "-c", "echo hi"]},
            None,
            seen_updates.append,
        )

        assert result.content[0].text == "chunk-2\nchunk-3\nchunk-err\n"
        assert result.details["stdout_artifact_path"] == str(tmp_path / "stdout.log")
        assert result.details["truncated"] is True
        assert result.details["truncated_by"] == "lines"
        assert result.details["stderr"] == "chunk-err\n"

    asyncio.run(scenario())

    assert seen_updates[0].content == []
    assert seen_updates[0].details is None
    assert [update.content[0].text for update in seen_updates[1:]] == [
        "chunk-1\n",
        "chunk-1\nchunk-err\n",
    ]
    assert [update.details["stream"] for update in seen_updates[1:]] == [
        "stdout",
        "stderr",
    ]


def test_bash_tool_details_include_pi_style_truncation_schema(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecRequest, ExecResult

    stdout_artifact_path = str(tmp_path / "stdout.log")

    class FakeExecService:
        async def execute(
            self, request: ExecRequest, signal=None, on_update=None
        ) -> ExecResult:
            del request, signal, on_update
            return ExecResult(
                exit_code=0,
                stdout="line-1\nline-2\nline-3\n",
                stdout_preview="line-2\nline-3\n",
                stdout_truncated=True,
                stdout_truncated_by="lines",
                stdout_artifact_path=stdout_artifact_path,
            )

    async def scenario() -> None:
        runtime_tool = wrap_tool_definition(
            create_bash_tool_definition(exec_service=FakeExecService())
        )
        result = await runtime_tool.execute(
            "tool-call-1", {"command": ["/bin/sh", "-c", "echo hi"]}
        )

        assert result.details["stdout_artifact_path"] == stdout_artifact_path
        assert result.details["full_output_path"] == stdout_artifact_path
        assert "fullOutputPath" not in result.details
        assert result.details["truncation"]["truncated"] is True
        assert result.details["truncation"]["truncatedBy"] == "lines"
        assert result.details["truncation"]["totalLines"] == 3
        assert result.details["truncation"]["outputLines"] == 2
        assert result.details["truncation"]["maxBytes"] == 50 * 1024

    asyncio.run(scenario())


def test_bash_tool_full_output_path_uses_stderr_artifact_when_stdout_is_present(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_bash_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecRequest, ExecResult

    stderr_artifact_path = str(tmp_path / "stderr.log")

    class FakeExecService:
        async def execute(
            self, request: ExecRequest, signal=None, on_update=None
        ) -> ExecResult:
            del request, signal, on_update
            return ExecResult(
                exit_code=0,
                stdout="ok\n",
                stderr="warning\n" * 3000,
                stderr_preview="warning\n",
                stderr_truncated=True,
                stderr_truncated_by="lines",
                stderr_artifact_path=stderr_artifact_path,
            )

    async def scenario() -> None:
        runtime_tool = wrap_tool_definition(
            create_bash_tool_definition(exec_service=FakeExecService())
        )
        result = await runtime_tool.execute(
            "tool-call-1", {"command": ["/bin/sh", "-c", "echo hi"]}
        )

        assert result.details["stdout_artifact_path"] is None
        assert result.details["stderr_artifact_path"] == stderr_artifact_path
        assert result.details["full_output_path"] == stderr_artifact_path
        assert "fullOutputPath" not in result.details

    asyncio.run(scenario())


def test_agent_session_execute_bash_records_command_execution(tmp_path) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.conversation import CommandExecutionRecord
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )
    from loushang.harness.transcript import COMMAND_EXECUTION_KIND
    from loushang.harness.workspace.exec import ExecOutputChunk, ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class RecordingExecService:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def execute(self, request, signal=None, on_update=None):
            self.requests.append(request)
            if on_update is not None:
                await on_update(ExecOutputChunk(stream="stdout", text="hi\n"))
            return ExecResult(exit_code=0, stdout="hi\n", stderr="")

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    exec_service = RecordingExecService()
    register_builtin_tools(
        registry,
        exec_service=exec_service,
    )
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "stale prompt",
                "model": model,
                "thinking_level": "off",
                "tools": [],
            },
            convert_to_llm=lambda messages: [],
        ),
        session_manager=manager,
        tool_registry=registry,
        active_tool_names=["bash"],
        tool_policy_evaluator=AllowingPolicyEngine(),
    )

    async def scenario() -> None:
        result = await session.execute_bash("printf hi")
        assert result == {
            "output": "hi\n",
            "exit_code": 0,
            "cancelled": False,
            "truncated": False,
            "full_output_path": None,
        }

    asyncio.run(scenario())

    assert exec_service.requests[0].command == ("/bin/bash", "-lc", "printf hi")
    assert exec_service.requests[0].cwd == "/tmp/project"
    record = manager.get_entries()[-1]
    assert record.kind == COMMAND_EXECUTION_KIND
    assert isinstance(record.payload, CommandExecutionRecord)
    assert record.payload.output == "hi\n"
    assert session.agent.state.messages[-1].role == "user"


def test_agent_session_execute_bash_compatibility_uses_windows_shell_tool(
    tmp_path,
) -> None:
    import asyncio
    import base64

    from loushang.agent import Agent
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.harness.environment import HostEnvironment
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace import create_shell_tool_definition
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
    from loushang.harness.workspace.exec import ExecResult
    from loushang.harness.workspace.shell import ResolvedShell

    class AllowingPolicy:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class Resolver:
        def resolve(self, selection=None):
            del selection
            return ResolvedShell(
                kind="powershell",
                executable=r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                flavor="windows-powershell",
                target_id="windows-local",
                target_os_family="windows",
                source="system",
                version="5.1",
                edition="Desktop",
            )

    class Operations:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def execute(self, request, *, signal=None, on_update=None):
            del signal, on_update
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="windows\n")

    operations = Operations()
    registry = WorkspaceToolRegistry()
    registry.register_tool(
        create_shell_tool_definition(
            operations=operations,
            environment=HostEnvironment(
                os_family="windows",
                platform_name="win32",
                architecture="amd64",
            ),
            resolver_factory=lambda environment, environ, cwd: Resolver(),
        )
    )
    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd=r"C:\workspace", persist=False)
    )
    session = AgentSession(
        agent=Agent(),
        session_manager=manager,
        tool_registry=registry,
        active_tool_names=["shell"],
        tool_policy_evaluator=AllowingPolicy(),
    )

    result = asyncio.run(session.execute_bash("Get-Location"))

    assert result["output"] == "windows\n"
    request = operations.requests[0]
    assert request.command[0].endswith("powershell.exe")
    decoded = base64.b64decode(request.command[-1]).decode("utf-16le")
    assert "Get-Location" in decoded


def test_agent_session_abort_bash_cancels_active_execution_and_records_command(
    tmp_path,
) -> None:
    import asyncio

    from loushang.agent import Agent
    from loushang.ai.model import Capabilities, Model
    from loushang.coding import SessionManager
    from loushang.coding.session import AgentSession
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.conversation import CommandExecutionRecord
    from loushang.harness.policy import PolicyDecision
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )
    from loushang.harness.transcript import COMMAND_EXECUTION_KIND
    from loushang.harness.workspace.exec import ExecOutputChunk, ExecResult

    class AllowingPolicyEngine:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.allow()

    class BlockingExecService:
        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def execute(self, request, signal=None, on_update=None):
            del request
            self.started.set()
            if on_update is not None:
                await on_update(ExecOutputChunk(stream="stdout", text="partial\n"))
            while signal is not None and not getattr(signal, "aborted", False):
                await asyncio.sleep(0.01)
            return ExecResult(
                exit_code=-1, stdout="partial\n", stderr="", cancelled=True
            )

    manager = asyncio.run(
        SessionManager.new(session_dir=tmp_path, cwd="/tmp/project", persist=False)
    )
    registry = ToolRegistry()
    exec_service = BlockingExecService()
    register_builtin_tools(
        registry,
        exec_service=exec_service,
    )
    model = Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )
    session = AgentSession(
        agent=Agent(
            initial_state={
                "system_prompt": "stale prompt",
                "model": model,
                "thinking_level": "off",
                "tools": [],
            },
            convert_to_llm=lambda messages: [],
        ),
        session_manager=manager,
        tool_registry=registry,
        active_tool_names=["bash"],
        tool_policy_evaluator=AllowingPolicyEngine(),
    )

    async def scenario() -> None:
        task = asyncio.create_task(session.execute_bash("sleep 1"))
        await exec_service.started.wait()
        session.abort_bash()
        result = await asyncio.wait_for(task, timeout=0.5)
        assert result == {
            "output": "partial\n",
            "exit_code": None,
            "cancelled": True,
            "truncated": False,
            "full_output_path": None,
        }

    asyncio.run(scenario())

    record = manager.get_entries()[-1]
    assert record.kind == COMMAND_EXECUTION_KIND
    assert isinstance(record.payload, CommandExecutionRecord)
    assert record.payload.cancelled is True
    assert session.agent.state.messages[-1].role == "user"
