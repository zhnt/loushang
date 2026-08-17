"""Definition and Consumer requirements for the Harness workspace Bundle."""

from __future__ import annotations

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
)

WORKSPACE_READ_FACET = "read"
WORKSPACE_LIST_FACET = "list"
WORKSPACE_SEARCH_FACET = "search"
WORKSPACE_WRITE_FACET = "write"
WORKSPACE_EDIT_FACET = "edit"
WORKSPACE_PROCESS_LAUNCH_FACET = "process.launch"

WORKSPACE_CAPABILITY_DEFINITION = CapabilityDefinition(
    capability_id="harness.workspace",
    owner_id="harness",
    contract_version=1,
    facets=(
        WORKSPACE_READ_FACET,
        WORKSPACE_LIST_FACET,
        WORKSPACE_SEARCH_FACET,
        WORKSPACE_WRITE_FACET,
        WORKSPACE_EDIT_FACET,
        WORKSPACE_PROCESS_LAUNCH_FACET,
    ),
    scope="workspace",
    refresh_boundary="sealed",
    phase="bootstrap",
    authority_ceiling=frozenset({"filesystem", "process"}),
)

WORKSPACE_TOOL_REQUIREMENT = CapabilityRequirement(
    capability="harness.workspace",
    facets=(
        WORKSPACE_READ_FACET,
        WORKSPACE_LIST_FACET,
        WORKSPACE_SEARCH_FACET,
        WORKSPACE_WRITE_FACET,
        WORKSPACE_EDIT_FACET,
    ),
    compatible_contract=CapabilityContractRange.exact(1),
)

WORKSPACE_PROCESS_REQUIREMENT = CapabilityRequirement(
    capability="harness.workspace",
    facets=(WORKSPACE_PROCESS_LAUNCH_FACET,),
    compatible_contract=CapabilityContractRange.exact(1),
)

__all__ = [
    "WORKSPACE_CAPABILITY_DEFINITION",
    "WORKSPACE_EDIT_FACET",
    "WORKSPACE_LIST_FACET",
    "WORKSPACE_PROCESS_LAUNCH_FACET",
    "WORKSPACE_PROCESS_REQUIREMENT",
    "WORKSPACE_READ_FACET",
    "WORKSPACE_SEARCH_FACET",
    "WORKSPACE_TOOL_REQUIREMENT",
    "WORKSPACE_WRITE_FACET",
]
