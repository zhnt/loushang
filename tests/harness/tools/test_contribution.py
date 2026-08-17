from __future__ import annotations

import pytest

from loushang.harness.tools.execution import direct_execution


def test_resolver_returns_all_enabled_contributions_in_registration_order() -> None:
    from loushang.harness.tools.contribution import (
        ToolContribution,
        resolve_tool_contributions,
    )

    read = _tool_definition("read")
    write = _tool_definition("write")
    disabled = _tool_definition("disabled")

    result = resolve_tool_contributions(
        (
            ToolContribution(read, source_info={"source": "builtins"}),
            ToolContribution(write),
            ToolContribution(disabled, enabled=False),
        )
    )

    assert [definition.name for definition in result.definitions] == ["read", "write"]
    assert [contribution.definition.name for contribution in result.contributions] == ["read", "write"]
    assert result.contributions[0].source_info == {"source": "builtins"}
    assert result.diagnostics == ()
    assert result.has_errors is False


def test_resolver_expands_pack_includes_transitively_before_pack_tools() -> None:
    from loushang.harness.tools.contribution import (
        ToolContribution,
        ToolPackDefinition,
        resolve_tool_contributions,
    )

    result = resolve_tool_contributions(
        (
            ToolContribution(_tool_definition("read")),
            ToolContribution(_tool_definition("ls")),
            ToolContribution(_tool_definition("write")),
            ToolContribution(_tool_definition("grep")),
        ),
        packs=(
            ToolPackDefinition(name="base", tools=("read", "ls")),
            ToolPackDefinition(name="edit", includes=("base",), tools=("write", "grep", "read")),
        ),
        include_packs=("edit",),
    )

    assert [definition.name for definition in result.definitions] == ["read", "ls", "write", "grep"]
    assert result.diagnostics == ()


def test_resolver_filters_requested_disabled_tool_names() -> None:
    from loushang.harness.tools.contribution import (
        ToolContribution,
        ToolPackDefinition,
        resolve_tool_contributions,
    )

    result = resolve_tool_contributions(
        (
            ToolContribution(_tool_definition("read")),
            ToolContribution(_tool_definition("write")),
            ToolContribution(_tool_definition("bash"), enabled=False),
        ),
        packs=(ToolPackDefinition(name="default", tools=("read", "write", "bash")),),
        include_packs=("default",),
        disabled_tools=("write",),
    )

    assert [definition.name for definition in result.definitions] == ["read"]
    assert result.diagnostics == ()


def test_resolver_reports_duplicate_tools_and_packs() -> None:
    from loushang.harness.tools.contribution import (
        ToolContribution,
        ToolPackDefinition,
        resolve_tool_contributions,
    )

    result = resolve_tool_contributions(
        (
            ToolContribution(_tool_definition("read"), source_info={"source": "a"}),
            ToolContribution(_tool_definition("read"), source_info={"source": "b"}),
        ),
        packs=(
            ToolPackDefinition(name="default", tools=("read",), source_info={"source": "a"}),
            ToolPackDefinition(name="default", tools=("read",), source_info={"source": "b"}),
        ),
        fail_on_errors=False,
    )

    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "duplicate_tool",
        "duplicate_pack",
    ]
    assert result.diagnostics[0].details["name"] == "read"
    assert result.diagnostics[0].details["sources"] == [{"source": "a"}, {"source": "b"}]
    assert result.diagnostics[1].details["name"] == "default"
    assert result.has_errors is True


def test_resolver_raises_for_missing_references_by_default() -> None:
    from loushang.harness.tools.contribution import (
        ToolContribution,
        ToolPackDefinition,
        ToolResolutionError,
        resolve_tool_contributions,
    )

    with pytest.raises(ToolResolutionError) as exc_info:
        resolve_tool_contributions(
            (ToolContribution(_tool_definition("read")),),
            packs=(ToolPackDefinition(name="broken", includes=("missing-pack",), tools=("missing-tool",)),),
            include_packs=("broken",),
        )

    assert [diagnostic.code for diagnostic in exc_info.value.diagnostics] == [
        "missing_pack",
        "missing_tool",
    ]
    assert [diagnostic.details["name"] for diagnostic in exc_info.value.diagnostics] == [
        "missing-pack",
        "missing-tool",
    ]


def _tool_definition(name: str):
    from loushang.agent.types import AgentToolResult
    from loushang.harness.tools.core import ToolDefinition

    async def execute(tool_call_id, params, signal=None, on_update=None):
        del tool_call_id, params, signal, on_update
        return AgentToolResult(content=[], details={})

    return ToolDefinition(
        name=name,
        label=name.title(),
        description=name,
        parameters={"type": "object", "properties": {}, "required": []},
        execution=direct_execution(execute),
    )
