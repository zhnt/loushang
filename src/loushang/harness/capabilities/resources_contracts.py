"""Definition and focused Consumer requirements for ``harness.resources``."""

from __future__ import annotations

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
)

RESOURCE_RUNTIME_FACET = "resource.runtime"
PROMPT_SECTIONS_FACET = "prompt.sections"
SKILL_ACTIVATION_FACET = "skill.activation"
TOOL_PACKS_FACET = "tool.packs"
COMMAND_PACKS_FACET = "command.packs"

RESOURCES_CAPABILITY_DEFINITION = CapabilityDefinition(
    capability_id="harness.resources",
    owner_id="harness",
    contract_version=1,
    facets=(
        RESOURCE_RUNTIME_FACET,
        PROMPT_SECTIONS_FACET,
        SKILL_ACTIVATION_FACET,
        TOOL_PACKS_FACET,
        COMMAND_PACKS_FACET,
    ),
    scope="session",
    refresh_boundary="sealed",
    phase="bootstrap",
)

RESOURCES_ACTIVATION_REQUIREMENT = CapabilityRequirement(
    capability="harness.resources",
    facets=(RESOURCE_RUNTIME_FACET, SKILL_ACTIVATION_FACET),
    compatible_contract=CapabilityContractRange.exact(1),
)
RESOURCES_PROMPT_REQUIREMENT = CapabilityRequirement(
    capability="harness.resources",
    facets=(PROMPT_SECTIONS_FACET,),
    compatible_contract=CapabilityContractRange.exact(1),
)
RESOURCES_TOOL_PACK_REQUIREMENT = CapabilityRequirement(
    capability="harness.resources",
    facets=(TOOL_PACKS_FACET,),
    compatible_contract=CapabilityContractRange.exact(1),
)
RESOURCES_COMMAND_PACK_REQUIREMENT = CapabilityRequirement(
    capability="harness.resources",
    facets=(COMMAND_PACKS_FACET,),
    compatible_contract=CapabilityContractRange.exact(1),
)

__all__ = [
    "COMMAND_PACKS_FACET",
    "PROMPT_SECTIONS_FACET",
    "RESOURCES_ACTIVATION_REQUIREMENT",
    "RESOURCES_CAPABILITY_DEFINITION",
    "RESOURCES_COMMAND_PACK_REQUIREMENT",
    "RESOURCES_PROMPT_REQUIREMENT",
    "RESOURCES_TOOL_PACK_REQUIREMENT",
    "RESOURCE_RUNTIME_FACET",
    "SKILL_ACTIVATION_FACET",
    "TOOL_PACKS_FACET",
]
