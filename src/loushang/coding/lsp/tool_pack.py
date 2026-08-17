"""Optional semantic tool pack selected by the Coding Product."""

from __future__ import annotations

from loushang.coding.capabilities import CODING_LSP_CAPABILITY
from loushang.coding.lsp.tools import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
    InspectSymbolRuntime,
    create_document_outline_tool_definition,
    create_inspect_symbol_tool_definition,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.tools.contribution import (
    ToolContribution,
    ToolPackDefinition,
    resolve_tool_contributions,
)
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry

CODING_LSP_TOOL_PACK = ToolPackDefinition(
    name="coding.lsp.tools",
    tools=(INSPECT_SYMBOL_TOOL_NAME, DOCUMENT_OUTLINE_TOOL_NAME),
    metadata={"product_capability": CODING_LSP_CAPABILITY},
)


def register_coding_lsp_tools(
    registry: WorkspaceToolRegistry,
    *,
    runtime: InspectSymbolRuntime,
    mode: CapabilityMountMode = "on_demand",
) -> WorkspaceToolRegistry:
    """Admit session-bound LSP tools according to Coding's mount policy."""

    if mode == "disabled":
        return registry
    if mode not in {"on_demand", "always"}:
        raise ValueError(f"unsupported coding.lsp mount mode: {mode!r}")
    resolution = resolve_tool_contributions(
        (
            ToolContribution(create_inspect_symbol_tool_definition(runtime)),
            ToolContribution(create_document_outline_tool_definition(runtime)),
        ),
        packs=(CODING_LSP_TOOL_PACK,),
        include_packs=(CODING_LSP_TOOL_PACK.name,),
    )
    for definition in resolution.definitions:
        registry.register_tool(definition, enabled=mode == "always")
    return registry


__all__ = ["CODING_LSP_TOOL_PACK", "register_coding_lsp_tools"]
