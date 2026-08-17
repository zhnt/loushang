from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.harness.tools.workspace import (
    WorkspaceToolProfile,
    WorkspaceToolRegistry,
    create_profiled_workspace_tool_definition,
    create_profiled_workspace_tool_definitions,
    create_profiled_workspace_tools,
)


def _design_copy(definition):
    return replace(
        definition,
        description=f"Design workspace: {definition.description}",
    )


DESIGN_TOOL_PROFILE = WorkspaceToolProfile(
    profile_id="design.workspace",
    tool_names=("read", "write"),
    builtin_tool_names=("read", "ls", "write"),
    pack_id="design.builtin",
    decorate_definition=_design_copy,
)


def test_profile_builds_product_copy_without_changing_tool_order() -> None:
    definitions = create_profiled_workspace_tool_definitions(DESIGN_TOOL_PROFILE)

    assert [definition.name for definition in definitions] == ["read", "write"]
    assert all(
        definition.description.startswith("Design workspace:")
        for definition in definitions
    )
    assert [
        tool.name for tool in create_profiled_workspace_tools(DESIGN_TOOL_PROFILE)
    ] == ["read", "write"]


def test_registry_resolves_the_profile_builtin_pack() -> None:
    registry = WorkspaceToolRegistry().register_profile(DESIGN_TOOL_PROFILE)

    assert [definition.name for definition in registry.list_definitions()] == [
        "read",
        "ls",
        "write",
    ]
    assert registry.get_definition("ls").description.startswith("Design workspace:")


def test_registry_copy_and_selection_preserve_contribution_metadata() -> None:
    read, write = create_profiled_workspace_tool_definitions(DESIGN_TOOL_PROFILE)
    registry = WorkspaceToolRegistry()
    registry.register_tool(read, source_info={"product": "design"})
    registry.register_tool(write, enabled=False, source_info={"product": "design"})

    copied = registry.copy()
    selected = registry.select(("write", "read"))

    assert [tool.name for tool in copied.list_definitions()] == ["read", "write"]
    assert [tool.name for tool in copied.list_enabled_definitions()] == ["read"]
    assert copied.get_source_info("read") == {"product": "design"}
    assert [tool.name for tool in selected.list_definitions()] == ["write", "read"]
    assert [tool.name for tool in selected.list_enabled_definitions()] == ["read"]


def test_profile_rejects_definition_name_changes() -> None:
    profile = WorkspaceToolProfile(
        profile_id="invalid.workspace",
        tool_names=("read",),
        decorate_definition=lambda definition: replace(
            definition,
            name="write",
        ),
    )

    with pytest.raises(ValueError, match="preserve the tool name"):
        create_profiled_workspace_tool_definition(profile, "read")
