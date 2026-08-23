"""Shared strict-data codecs for Plugin-authored Capability requirements."""

from __future__ import annotations

from typing import cast

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityRequirement,
    CapabilityRequirementBinding,
    _capability_contract_range_to_dict,
    _capability_requirement_to_dict,
)
from loushang.harness.resources.plugins.declarations import _exact_document


def capability_contract_range_to_dict(
    value: CapabilityContractRange,
) -> dict[str, object]:
    return _capability_contract_range_to_dict(value)


def capability_contract_range_from_dict(value: object) -> CapabilityContractRange:
    document = _exact_document(
        value,
        name="Capability contract range",
        keys={"maximum", "minimum"},
    )
    return CapabilityContractRange(
        minimum=cast(int, document["minimum"]),
        maximum=cast(int, document["maximum"]),
    )


def capability_requirement_to_dict(value: CapabilityRequirement) -> dict[str, object]:
    return _capability_requirement_to_dict(value)


def capability_requirement_from_dict(value: object) -> CapabilityRequirement:
    document = _exact_document(
        value,
        name="Capability requirement",
        keys={"binding", "capability", "compatibleContract", "facets", "optional"},
    )
    binding = document["binding"]
    capability = document["capability"]
    facets = _canonical_string_list(
        document["facets"],
        name="Capability requirement facets",
    )
    optional = document["optional"]
    if not isinstance(binding, str) or not isinstance(capability, str):
        raise ValueError("Capability requirement identity fields must be strings")
    if not isinstance(optional, bool):
        raise ValueError("Capability requirement optional must be a boolean")
    return CapabilityRequirement(
        capability=capability,
        facets=facets,
        compatible_contract=capability_contract_range_from_dict(
            document["compatibleContract"]
        ),
        optional=optional,
        binding=cast(CapabilityRequirementBinding, binding),
    )


def _canonical_string_list(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a string list")
    if value != sorted(set(value)):
        raise ValueError(f"{name} must use canonical sorted order without duplicates")
    return tuple(value)


__all__ = [
    "capability_contract_range_from_dict",
    "capability_contract_range_to_dict",
    "capability_requirement_from_dict",
    "capability_requirement_to_dict",
]
