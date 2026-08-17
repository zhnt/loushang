"""Pure contracts for coarse Product Capability graphs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from loushang.harness.runtime import RuntimeCapabilityScope, RuntimeRefreshBoundary

CapabilityPhase = Literal["bootstrap", "final"]
CapabilityRequirementBinding = Literal["direct", "stable_reference"]

_CAPABILITY_PHASES = frozenset({"bootstrap", "final"})
_REQUIREMENT_BINDINGS = frozenset({"direct", "stable_reference"})
_SCOPES = frozenset({"process", "tenant", "workspace", "session", "turn", "channel"})
_REFRESH_BOUNDARIES = frozenset({"sealed", "turn"})


@dataclass(frozen=True)
class CapabilityContractRange:
    """Inclusive compatible contract-version range."""

    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        _require_positive_integer(self.minimum, name="minimum contract version")
        _require_positive_integer(self.maximum, name="maximum contract version")
        if self.maximum < self.minimum:
            raise ValueError(
                "maximum contract version must not be less than the minimum"
            )

    @classmethod
    def exact(cls, version: int) -> CapabilityContractRange:
        return cls(minimum=version, maximum=version)

    def accepts(self, version: int) -> bool:
        _require_positive_integer(version, name="contract version")
        return self.minimum <= version <= self.maximum


@dataclass(frozen=True)
class CapabilityDefinition:
    """Owner-qualified public contract for one coarse Capability Bundle."""

    capability_id: str
    owner_id: str
    contract_version: int
    facets: tuple[str, ...]
    scope: RuntimeCapabilityScope
    refresh_boundary: RuntimeRefreshBoundary
    phase: CapabilityPhase
    authority_ceiling: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        capability_id = _require_nonempty(self.capability_id, name="capability id")
        owner_id = _require_nonempty(self.owner_id, name="capability owner id")
        if not capability_id.startswith(f"{owner_id}."):
            raise ValueError("capability id must be qualified by its owner id")
        _require_positive_integer(
            self.contract_version,
            name="capability contract version",
        )
        facets = _normalized_names(self.facets, name="capability facets")
        if not facets:
            raise ValueError("capability facets must not be empty")
        scope = _require_choice(self.scope, name="capability scope", choices=_SCOPES)
        refresh_boundary = _require_choice(
            self.refresh_boundary,
            name="capability refresh boundary",
            choices=_REFRESH_BOUNDARIES,
        )
        phase = _require_choice(
            self.phase,
            name="capability phase",
            choices=_CAPABILITY_PHASES,
        )
        authority_ceiling = frozenset(
            _require_nonempty(value, name="capability authority")
            for value in self.authority_ceiling
        )
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "owner_id", owner_id)
        object.__setattr__(self, "facets", facets)
        object.__setattr__(self, "scope", cast(RuntimeCapabilityScope, scope))
        object.__setattr__(
            self,
            "refresh_boundary",
            cast(RuntimeRefreshBoundary, refresh_boundary),
        )
        object.__setattr__(self, "phase", cast(CapabilityPhase, phase))
        object.__setattr__(self, "authority_ceiling", authority_ceiling)


@dataclass(frozen=True)
class CapabilityRequirement:
    """Narrow facet view declared by a Provider or external Consumer."""

    capability: str
    facets: tuple[str, ...]
    compatible_contract: CapabilityContractRange
    optional: bool = False
    binding: CapabilityRequirementBinding = "direct"

    def __post_init__(self) -> None:
        capability = _require_nonempty(
            self.capability,
            name="required capability id",
        )
        facets = _normalized_names(self.facets, name="required capability facets")
        if not facets:
            raise ValueError("required capability facets must not be empty")
        if not isinstance(self.compatible_contract, CapabilityContractRange):
            raise TypeError(
                "required capability compatible_contract must be a "
                "CapabilityContractRange"
            )
        if type(self.optional) is not bool:
            raise TypeError("required capability optional must be a bool")
        binding = _require_choice(
            self.binding,
            name="required capability binding",
            choices=_REQUIREMENT_BINDINGS,
        )
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "facets", facets)
        object.__setattr__(
            self,
            "binding",
            cast(CapabilityRequirementBinding, binding),
        )


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _require_positive_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1:
        raise ValueError(f"{name} must be at least 1")
    return value


def _require_choice(
    value: object,
    *,
    name: str,
    choices: frozenset[str],
) -> str:
    normalized = _require_nonempty(value, name=name)
    if normalized not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}")
    return normalized


def _normalized_names(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    normalized = tuple(_require_nonempty(value, name=name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


__all__ = [
    "CapabilityContractRange",
    "CapabilityDefinition",
    "CapabilityPhase",
    "CapabilityRequirement",
    "CapabilityRequirementBinding",
]
