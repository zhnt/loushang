"""Definition and Consumer requirement for durable Model Input preparation."""

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
)

MODEL_INPUT_PREPARATION_FACET = "prepare"

MODEL_INPUT_CAPABILITY_DEFINITION = CapabilityDefinition(
    capability_id="harness.model_input",
    owner_id="harness",
    contract_version=1,
    facets=(MODEL_INPUT_PREPARATION_FACET,),
    scope="session",
    refresh_boundary="sealed",
    phase="final",
    authority_ceiling=frozenset({"transcript"}),
)

MODEL_INPUT_PREPARATION_REQUIREMENT = CapabilityRequirement(
    capability=MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
    facets=(MODEL_INPUT_PREPARATION_FACET,),
    compatible_contract=CapabilityContractRange.exact(1),
)

__all__ = [
    "MODEL_INPUT_CAPABILITY_DEFINITION",
    "MODEL_INPUT_PREPARATION_FACET",
    "MODEL_INPUT_PREPARATION_REQUIREMENT",
]
