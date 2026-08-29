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
RESOURCE_CATALOG_FACET = "resource.catalog"
RESOURCE_LOAD_FACET = "resource.load"

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

RESOURCES_CAPABILITY_DEFINITION_V2 = CapabilityDefinition(
    capability_id="harness.resources",
    owner_id="harness",
    contract_version=2,
    facets=(
        RESOURCE_RUNTIME_FACET,
        PROMPT_SECTIONS_FACET,
        SKILL_ACTIVATION_FACET,
        TOOL_PACKS_FACET,
        COMMAND_PACKS_FACET,
        RESOURCE_CATALOG_FACET,
        RESOURCE_LOAD_FACET,
    ),
    scope="session",
    refresh_boundary="sealed",
    phase="bootstrap",
)

RESOURCES_CAPABILITY_DEFINITION_V3 = CapabilityDefinition(
    capability_id="harness.resources",
    owner_id="harness",
    contract_version=3,
    facets=RESOURCES_CAPABILITY_DEFINITION_V2.facets,
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
RESOURCES_SESSION_COMPOSITION_REQUIREMENT = CapabilityRequirement(
    capability="harness.resources",
    facets=(
        RESOURCE_RUNTIME_FACET,
        PROMPT_SECTIONS_FACET,
        SKILL_ACTIVATION_FACET,
        TOOL_PACKS_FACET,
        COMMAND_PACKS_FACET,
    ),
    compatible_contract=CapabilityContractRange(minimum=1, maximum=2),
)
RESOURCES_CATALOG_REQUIREMENT = CapabilityRequirement(
    capability="harness.resources",
    facets=(RESOURCE_CATALOG_FACET,),
    compatible_contract=CapabilityContractRange.exact(2),
)
RESOURCES_LOAD_REQUIREMENT = CapabilityRequirement(
    capability="harness.resources",
    facets=(RESOURCE_LOAD_FACET,),
    compatible_contract=CapabilityContractRange.exact(2),
)
RESOURCES_CATALOG_LOAD_REQUIREMENT = CapabilityRequirement(
    capability="harness.resources",
    facets=(RESOURCE_CATALOG_FACET, RESOURCE_LOAD_FACET),
    compatible_contract=CapabilityContractRange.exact(2),
)
RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT = CapabilityRequirement(
    capability="harness.resources",
    facets=(RESOURCE_CATALOG_FACET, RESOURCE_LOAD_FACET),
    compatible_contract=CapabilityContractRange.exact(3),
)

__all__ = [
    "COMMAND_PACKS_FACET",
    "PROMPT_SECTIONS_FACET",
    "RESOURCE_CATALOG_FACET",
    "RESOURCE_LOAD_FACET",
    "RESOURCES_ACTIVATION_REQUIREMENT",
    "RESOURCES_CAPABILITY_DEFINITION",
    "RESOURCES_CAPABILITY_DEFINITION_V2",
    "RESOURCES_CAPABILITY_DEFINITION_V3",
    "RESOURCES_CATALOG_LOAD_REQUIREMENT",
    "RESOURCES_CATALOG_REQUIREMENT",
    "RESOURCES_COMMAND_PACK_REQUIREMENT",
    "RESOURCES_LOAD_REQUIREMENT",
    "RESOURCES_PROMPT_REQUIREMENT",
    "RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT",
    "RESOURCES_SESSION_COMPOSITION_REQUIREMENT",
    "RESOURCES_TOOL_PACK_REQUIREMENT",
    "RESOURCE_RUNTIME_FACET",
    "SKILL_ACTIVATION_FACET",
    "TOOL_PACKS_FACET",
]
