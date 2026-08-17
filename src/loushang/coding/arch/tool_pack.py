"""Optional architecture tool pack selected by the Coding product."""

from __future__ import annotations

from loushang.coding.arch.tool import (
    INSPECT_IMPORT_GRAPH_TOOL_NAME,
    ImportGraphToolRuntime,
    create_inspect_import_graph_tool_definition,
)
from loushang.coding.capabilities import CODING_ARCH_CAPABILITY
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.tools.contribution import (
    ToolContribution,
    ToolPackDefinition,
    resolve_tool_contributions,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

CODING_ARCH_TOOL_PACK = ToolPackDefinition(
    name="coding.arch.tools",
    tools=(INSPECT_IMPORT_GRAPH_TOOL_NAME,),
    metadata={"product_capability": CODING_ARCH_CAPABILITY},
)


def register_coding_arch_tools(
    registry: WorkspaceToolRegistry,
    *,
    mode: CapabilityMountMode = "on_demand",
    runtime: ImportGraphToolRuntime | None = None,
) -> WorkspaceToolRegistry:
    """Admit arch tools according to Coding's Product mount policy."""

    if mode == "disabled":
        return registry
    if mode not in {"on_demand", "always"}:
        raise ValueError(f"unsupported coding.arch mount mode: {mode!r}")
    definition = create_inspect_import_graph_tool_definition(runtime=runtime)
    resolution = resolve_tool_contributions(
        (ToolContribution(definition),),
        packs=(CODING_ARCH_TOOL_PACK,),
        include_packs=(CODING_ARCH_TOOL_PACK.name,),
    )
    for selected in resolution.definitions:
        registry.register_tool(selected, enabled=mode == "always")
    return registry


__all__ = ["CODING_ARCH_TOOL_PACK", "register_coding_arch_tools"]
