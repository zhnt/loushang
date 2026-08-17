"""Tool-facing Consumer of the narrow workspace Capability facet lease."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_EDIT_FACET,
    WORKSPACE_LIST_FACET,
    WORKSPACE_READ_FACET,
    WORKSPACE_SEARCH_FACET,
    WORKSPACE_TOOL_REQUIREMENT,
    WORKSPACE_WRITE_FACET,
)
from loushang.harness.tools.workspace.factory import ToolsOptions
from loushang.harness.workspace.operations import (
    EditOperations,
    FindOperations,
    GrepOperations,
    LsOperations,
    ReadOperations,
    WriteOperations,
)


@dataclass(frozen=True)
class WorkspaceToolCapabilityConsumer:
    """Adapt declared filesystem facets without receiving the graph runtime."""

    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != WORKSPACE_TOOL_REQUIREMENT:
            raise ValueError("workspace Tool Consumer received the wrong facet view")

    def apply(self, options: ToolsOptions = ToolsOptions()) -> ToolsOptions:
        search = self.facets.require(WORKSPACE_SEARCH_FACET)
        return replace(
            options,
            read_operations=cast(
                ReadOperations,
                self.facets.require(WORKSPACE_READ_FACET),
            ),
            ls_operations=cast(
                LsOperations,
                self.facets.require(WORKSPACE_LIST_FACET),
            ),
            find_operations=cast(FindOperations, search),
            grep_operations=cast(GrepOperations, search),
            write_operations=cast(
                WriteOperations,
                self.facets.require(WORKSPACE_WRITE_FACET),
            ),
            edit_operations=cast(
                EditOperations,
                self.facets.require(WORKSPACE_EDIT_FACET),
            ),
        )


__all__ = ["WorkspaceToolCapabilityConsumer"]
