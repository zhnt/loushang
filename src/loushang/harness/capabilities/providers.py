"""Data-only Bundle Provider declarations consumed by graph planning.

PR3 intentionally contains no factory or live value.  The graph binder adds the
narrow construction/disposal seam after planning can reject invalid metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityRequirement,
)


@dataclass(frozen=True)
class CapabilityBundleProvider:
    """Selected Provider metadata; diagnostic labels must already be redacted.

    Live construction belongs to the graph binder. ``source_id`` and
    ``selection_rule`` are projected verbatim and therefore must never contain
    credentials, raw exceptions, environment values, or other sensitive data.
    """

    capability_id: str
    provider_id: str
    implementation_version: int
    compatible_contract: CapabilityContractRange
    facets: tuple[str, ...]
    requirements: tuple[CapabilityRequirement, ...] = ()
    required_authorities: frozenset[str] = frozenset()
    source_id: str = "builtin"
    selection_rule: str = "explicit"

    def __post_init__(self) -> None:
        capability_id = _require_nonempty(
            self.capability_id,
            name="provider capability id",
        )
        provider_id = _require_nonempty(self.provider_id, name="provider id")
        if isinstance(self.implementation_version, bool) or not isinstance(
            self.implementation_version, int
        ):
            raise TypeError("provider implementation version must be an integer")
        if self.implementation_version < 1:
            raise ValueError("provider implementation version must be at least 1")
        if not isinstance(self.compatible_contract, CapabilityContractRange):
            raise TypeError(
                "provider compatible_contract must be a CapabilityContractRange"
            )
        facets = _normalized_names(self.facets, name="provider facets")
        if not facets:
            raise ValueError("provider facets must not be empty")
        requirements = tuple(self.requirements)
        if any(
            not isinstance(requirement, CapabilityRequirement)
            for requirement in requirements
        ):
            raise TypeError(
                "provider requirements must contain CapabilityRequirement values"
            )
        required_capabilities = [item.capability for item in requirements]
        if len(set(required_capabilities)) != len(required_capabilities):
            raise ValueError(
                "provider requirements must not repeat a capability identity"
            )
        authorities = frozenset(
            _require_nonempty(value, name="provider required authority")
            for value in self.required_authorities
        )
        source_id = _require_nonempty(self.source_id, name="provider source id")
        selection_rule = _require_nonempty(
            self.selection_rule,
            name="provider selection rule",
        )
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "facets", facets)
        object.__setattr__(self, "requirements", requirements)
        object.__setattr__(self, "required_authorities", authorities)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "selection_rule", selection_rule)


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _normalized_names(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    normalized = tuple(_require_nonempty(value, name=name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


__all__ = ["CapabilityBundleProvider"]
