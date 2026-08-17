from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict

import pytest

from loushang.harness.tools.execution import direct_execution


class SearchArgs(TypedDict):
    pattern: str
    path: str
    ignore_case: NotRequired[bool]


@dataclass
class ReadArgs:
    path: str
    limit: int | None = None


def search(args: SearchArgs) -> None:
    del args


def read(args: ReadArgs) -> None:
    del args


def test_tool_definition_validates_prompt_guidelines_sequence() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.harness.tools.core import ToolDefinition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    definition = ToolDefinition(
        name="demo",
        label="Demo",
        description="demo",
        parameters={"type": "object", "properties": {}, "required": []},
        execution=direct_execution(execute),
        prompt_guidelines=["one", "two"],
    )

    assert definition.prompt_guidelines == ("one", "two")

    with pytest.raises(TypeError, match="prompt_guidelines must be a sequence"):
        ToolDefinition(
            name="bad",
            label="Bad",
            description="bad",
            parameters={"type": "object", "properties": {}, "required": []},
            execution=direct_execution(execute),
            prompt_guidelines="bad",  # type: ignore[arg-type]
        )


def test_project_tool_definition_uses_neutral_source_info() -> None:
    from pathlib import Path

    from loushang.harness.tools.core import ToolDefinition, project_tool_definition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return None

    definition = ToolDefinition(
        name="read",
        label="Read",
        description="Read files",
        parameters={"type": "object"},
        execution=direct_execution(execute),
    )

    assert project_tool_definition(
        definition, builtin_names=frozenset({"read"})
    )["sourceInfo"] == {
        "path": "<builtin:read>",
        "source": "builtin",
        "scope": "temporary",
        "origin": "top-level",
        "baseDir": None,
    }
    assert project_tool_definition(
        definition,
        type("Source", (), {"path": Path("tools.py"), "source": "filesystem"})(),
    )["sourceInfo"]["path"] == "tools.py"


def test_tool_decorator_attaches_metadata_without_normalizing_returns() -> None:
    from loushang.harness.tools.core import DecoratedToolSpec, tool

    @tool(name="hello", label="Hello", description="Say hello")
    async def greet(name: str) -> str:
        return f"hello {name}"

    spec = getattr(greet, "__loushang_tool_spec__")

    assert isinstance(spec, DecoratedToolSpec)
    assert spec.name == "hello"
    assert spec.label == "Hello"
    assert spec.description == "Say hello"
    assert spec.fn is greet


def test_schema_inference_handles_typeddict_and_dataclass() -> None:
    from loushang.harness.tools.core import infer_schema_from_signature

    search_schema = infer_schema_from_signature(search)
    read_schema = infer_schema_from_signature(read)

    assert search_schema["properties"]["args"]["properties"]["pattern"]["type"] == "string"
    assert "ignore_case" not in search_schema["properties"]["args"]["required"]
    assert read_schema["properties"]["args"]["properties"]["limit"]["anyOf"] == [
        {"type": "integer"},
        {"type": "null"},
    ]


def test_registry_accepts_neutral_definitions_and_preserves_order_and_source_info() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.harness.tools.core import ToolDefinition, ToolRegistry

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    first = ToolDefinition(
        name="first",
        label="First",
        description="first",
        parameters={"type": "object", "properties": {}, "required": []},
        execution=direct_execution(execute),
    )
    second = ToolDefinition(
        name="second",
        label="Second",
        description="second",
        parameters={"type": "object", "properties": {}, "required": []},
        execution=direct_execution(execute),
    )

    registry = ToolRegistry()
    registry.register_tool(first, source_info={"source": "test"})
    registry.register_tool(second, enabled=False)

    assert [definition.name for definition in registry.list_definitions()] == ["first", "second"]
    assert [definition.name for definition in registry.list_enabled_definitions()] == ["first"]
    assert registry.get_source_info("first") == {"source": "test"}

    registry.enable_tool("second")
    registry.disable_tool("first")

    assert [definition.name for definition in registry.list_enabled_definitions()] == ["second"]


def test_tool_registry_duplicate_registration_compatibility_baseline() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.harness.tools.core import ToolDefinition, ToolRegistry

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    first = ToolDefinition(
        name="shared",
        label="First",
        description="first",
        parameters={"type": "object"},
        execution=direct_execution(execute),
    )
    replacement = ToolDefinition(
        name="shared",
        label="Replacement",
        description="replacement",
        parameters={"type": "object"},
        execution=direct_execution(execute),
    )
    registry = ToolRegistry()

    assert (
        registry.register_tool(
            first,
            enabled=False,
            source_info={"owner": "first"},
        )
        is first
    )
    assert (
        registry.register_tool(
            replacement,
            enabled=True,
            source_info={"owner": "replacement"},
        )
        is replacement
    )

    assert registry.list_definitions() == [replacement]
    assert registry.list_enabled_definitions() == [replacement]
    assert registry.get_source_info("shared") == {"owner": "replacement"}
    assert not hasattr(registry, "unregister_tool")


def test_tool_registry_live_bindings_restore_the_previous_exact_winner() -> None:
    import asyncio

    from loushang.agent.types import AgentToolResult
    from loushang.harness.runtime import RegistrationIdentity, RegistrationOwner
    from loushang.harness.tools.core import ToolDefinition, ToolRegistry

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    def definition(label: str) -> ToolDefinition:
        return ToolDefinition(
            name="shared",
            label=label,
            description=label,
            parameters={"type": "object"},
            execution=direct_execution(execute),
        )

    registry = ToolRegistry()
    base = definition("Base")
    updated_base = definition("Updated base")
    first = definition("First owner")
    second = definition("Second owner")
    registry.register_tool(base, source_info={"owner": "base"})
    first_owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="first",
        runtime_id="session-1",
        generation=0,
    )
    second_owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="second",
        runtime_id="session-1",
        generation=0,
    )

    first_lease = registry.bind_tool(
        first,
        owner=first_owner,
        source_info={"owner": "first"},
    )
    second_lease = registry.bind_tool(
        second,
        owner=second_owner,
        source_info={"owner": "second"},
    )

    assert first_lease.identity != second_lease.identity
    assert registry.list_definitions() == [second]
    assert registry.get_source_info("shared") == {"owner": "second"}
    assert {
        identity.registration_id
        for _owner, identity, _state in registry.registration_inventory
    }.issuperset(
        {
            first_lease.identity.registration_id,
            second_lease.identity.registration_id,
        }
    )

    wrong_surface = RegistrationIdentity(
        surface="command",
        registration_id=second_lease.identity.registration_id,
        public_key="shared",
    )
    assert registry._remove_bound_tool(
        owner=second_owner,
        identity=wrong_surface,
    ).state == "failed_terminal"
    assert registry.list_definitions() == [second]

    assert (
        registry.register_tool(updated_base, source_info={"owner": "updated-base"})
        is updated_base
    )
    assert registry.list_definitions() == [second]
    assert registry.get_source_info("shared") == {"owner": "second"}

    assert asyncio.run(second_lease.dispose()).state == "removed"
    assert registry.list_definitions() == [first]
    assert registry.get_source_info("shared") == {"owner": "first"}

    replacement_lease = registry.bind_tool(
        second,
        owner=second_owner,
        source_info={"owner": "second"},
    )
    assert replacement_lease.state == "active"
    assert asyncio.run(first_lease.dispose()).state == "removed"
    assert registry.list_definitions() == [second]
    assert registry.get_source_info("shared") == {"owner": "second"}

    assert asyncio.run(replacement_lease.dispose()).state == "removed"
    assert registry.list_definitions() == [updated_base]
    assert registry.get_source_info("shared") == {"owner": "updated-base"}
    assert asyncio.run(first_lease.dispose()).state == "already_removed"


def test_tool_registry_adopts_bootstrap_tool_into_exact_generation_ownership() -> (
    None
):
    import asyncio

    from loushang.agent.types import AgentToolResult
    from loushang.harness.runtime import RegistrationOwner, RegistrationScope
    from loushang.harness.tools.core import ToolDefinition, ToolRegistry

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    def definition(label: str) -> ToolDefinition:
        return ToolDefinition(
            name="shared",
            label=label,
            description=label,
            parameters={"type": "object"},
            execution=direct_execution(execute),
        )

    registry = ToolRegistry()
    bootstrap = definition("Bootstrap")
    source_info = object()
    registry.register_tool(bootstrap, source_info=source_info)
    old_owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="tools",
        runtime_id="session-1",
        generation=1,
    )
    new_owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="tools",
        runtime_id="session-1",
        generation=2,
    )

    old_lease = registry.adopt_compatibility_tool(
        bootstrap,
        owner=old_owner,
        source_info=source_info,
    )
    assert old_lease is not None
    new_definition = definition("New generation")
    new_lease = registry.stage_tool(new_definition, owner=new_owner)

    assert new_lease.state == "staged"
    assert all(
        identity.registration_id != new_lease.identity.registration_id
        for _owner, identity, _state in registry.registration_inventory
    )
    assert registry.list_definitions()[0].label == "Bootstrap"
    scope = RegistrationScope(new_owner)
    scope.add(new_lease)
    scope.commit()
    assert new_lease.state == "active"
    assert any(
        identity.registration_id == new_lease.identity.registration_id
        for _owner, identity, _state in registry.registration_inventory
    )
    assert asyncio.run(old_lease.dispose()).state == "removed"
    assert registry.list_definitions() == [new_definition]
    assert asyncio.run(new_lease.dispose()).state == "removed"
    assert registry.list_definitions() == []


def test_tool_registry_adoption_requires_exact_bootstrap_provenance() -> None:
    import asyncio

    from loushang.agent.types import AgentToolResult
    from loushang.harness.runtime import RegistrationOwner
    from loushang.harness.tools.core import ToolDefinition, ToolRegistry

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    def definition(label: str) -> ToolDefinition:
        return ToolDefinition(
            name="shared",
            label=label,
            description=label,
            parameters={"type": "object"},
            execution=direct_execution(execute),
        )

    registry = ToolRegistry()
    product = definition("Product")
    extension = definition("Extension")
    registry.register_tool(product, source_info="product")
    owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="tools",
        runtime_id="session-1",
        generation=1,
    )

    assert (
        registry.adopt_compatibility_tool(
            extension,
            owner=owner,
            source_info="extension",
        )
        is None
    )
    lease = registry.stage_tool(extension, owner=owner, source_info="extension")
    lease.activate()
    assert registry.get_definition("shared") is extension
    assert asyncio.run(lease.dispose()).state == "removed"
    assert registry.get_definition("shared") is product


def test_tool_registry_adoption_rollback_restores_compatibility_entry() -> None:
    from loushang.agent.types import AgentToolResult
    from loushang.harness.runtime import RegistrationOwner
    from loushang.harness.tools.core import ToolDefinition, ToolRegistry

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    definition = ToolDefinition(
        name="shared",
        label="Bootstrap",
        description="Bootstrap",
        parameters={"type": "object"},
        execution=direct_execution(execute),
    )
    registry = ToolRegistry()
    registry.register_tool(definition, source_info="extension")
    owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="tools",
        runtime_id="session-1",
        generation=1,
    )
    adopted = registry.adopt_compatibility_tool(
        definition,
        owner=owner,
        source_info="extension",
    )
    assert adopted is not None

    assert adopted.rollback_registration().state == "removed"
    readopted = registry.adopt_compatibility_tool(
        definition,
        owner=owner,
        source_info="extension",
    )
    assert readopted is not None


def test_registry_rejects_decorated_plain_return_tools() -> None:
    from loushang.harness.tools.core import ToolRegistry, tool

    @tool()
    async def greet(name: str) -> str:
        return f"hello {name}"

    registry = ToolRegistry()

    with pytest.raises(TypeError, match="explicitly bound ToolDefinition"):
        registry.register_tool(greet)


def test_tools_core_does_not_export_pi_style_wrapper_aliases() -> None:
    import loushang.harness.tools.core as core

    assert not hasattr(core, "wrapToolDefinition")
    assert not hasattr(core, "wrapToolDefinitions")
    assert not hasattr(core, "createToolDefinitionFromAgentTool")


def test_wrap_tool_definition_uses_neutral_schema_and_executes() -> None:
    import asyncio

    from loushang.agent.types import AgentToolResult
    from loushang.harness.tools.core import ToolDefinition, wrap_tool_definition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del signal, on_update
        return AgentToolResult(content=[], details={"tool_call_id": tool_call_id, "params": params})

    definition = ToolDefinition(
        name="demo",
        label="Demo",
        description="demo",
        parameters={"type": "object", "properties": {"value": {"type": "string"}}},
        provider_parameters={"type": "object", "properties": {"provider": {"type": "string"}}},
        execution=direct_execution(execute),
    )
    runtime_tool = wrap_tool_definition(definition)

    result = asyncio.run(runtime_tool.execute("call-1", {"value": "x"}))

    assert runtime_tool.name == "demo"
    assert runtime_tool.parameters == definition.provider_parameters
    assert result.details == {"tool_call_id": "call-1", "params": {"value": "x"}}
