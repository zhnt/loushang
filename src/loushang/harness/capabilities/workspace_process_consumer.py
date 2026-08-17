"""Consumer seam for the authorized process-launch workspace facet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_PROCESS_LAUNCH_FACET,
    WORKSPACE_PROCESS_REQUIREMENT,
)
from loushang.harness.workspace.process import AuthorizedProcessLauncher


@dataclass(frozen=True)
class WorkspaceProcessCapabilityConsumer:
    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != WORKSPACE_PROCESS_REQUIREMENT:
            raise ValueError("workspace process Consumer received the wrong facet view")

    @property
    def launcher(self) -> AuthorizedProcessLauncher:
        return cast(
            AuthorizedProcessLauncher,
            self.facets.require(WORKSPACE_PROCESS_LAUNCH_FACET),
        )


__all__ = ["WorkspaceProcessCapabilityConsumer"]
