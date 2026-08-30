"""Optional architecture tool pack selected by the Coding product."""

from __future__ import annotations

from typing import Never

from loushang.coding.arch.tool import (
    INSPECT_IMPORT_GRAPH_TOOL_NAME,
    ImportGraphToolRuntime,
)
from loushang.coding.capabilities import CODING_ARCH_CAPABILITY
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.tools.contribution import ToolPackDefinition
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
) -> Never:
    """Reject the retired direct publisher; Product composition owns Tools."""

    del registry, mode, runtime
    raise RuntimeError(
        "direct Coding Arch Tool registration was retired; select the "
        "coding-architecture composition instead"
    )


__all__ = ["CODING_ARCH_TOOL_PACK", "register_coding_arch_tools"]
