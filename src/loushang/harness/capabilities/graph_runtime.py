"""Live Mount state and immutable projections for one Product/runtime graph."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

from loushang.harness.capabilities.contracts import CapabilityRequirement
from loushang.harness.capabilities.graph_planning import PlannedCapability
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
)
from loushang.harness.runtime.bindings import RuntimeBindingLease, RuntimeBindingState
from loushang.harness.runtime.registration import RegistrationScope

MountLifecycleState = Literal["bound", "disposed"]
GraphBindingAttemptState = Literal["committed", "failed", "cancelled", "disposed"]
RegistrationAttachmentState = Literal["effective", "pending_retirement"]


@dataclass(frozen=True)
class MountRequirementSnapshot:
    capability_id: str
    facets: tuple[str, ...]
    minimum_contract_version: int
    maximum_contract_version: int
    binding: str


@dataclass(frozen=True)
class MountNodeSnapshot:
    capability_id: str
    owner_id: str
    contract_version: int
    facets: tuple[str, ...]
    scope: str
    scope_instance_id: str
    refresh_boundary: str
    phase: str
    mount_generation: int
    provider_id: str
    provider_version: int
    provider_source_id: str
    selection_rule: str
    binding_signature: str
    requirements: tuple[MountRequirementSnapshot, ...]
    required_by: tuple[str, ...]
    lifecycle_state: MountLifecycleState = "bound"


@dataclass(frozen=True)
class MountGraphSnapshot:
    schema_version: int
    graph_id: str
    product_id: str
    runtime_id: str
    profile_fingerprint: str
    generation: int
    roots: tuple[str, ...]
    assembly_fingerprint: str
    nodes: tuple[MountNodeSnapshot, ...]


@dataclass(frozen=True)
class RegistrationInventoryEntry:
    registration_id: str
    surface: str
    public_key: str | None
    owner_kind: str
    owner_id: str
    runtime_id: str
    owner_generation: int
    attachment: RegistrationAttachmentState
    state: str


@dataclass(frozen=True)
class RegistrationInventorySnapshot:
    schema_version: int
    graph_id: str
    runtime_id: str
    mount_generation: int
    revision: str
    entries: tuple[RegistrationInventoryEntry, ...]


@dataclass(frozen=True)
class CapabilityGraphBindingAttempt:
    attempt_number: int
    state: GraphBindingAttemptState
    target_generation: int
    assembly_fingerprint: str | None
    created_capability_ids: tuple[str, ...] = ()
    reused_capability_ids: tuple[str, ...] = ()
    diagnostic_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityFacetSet:
    """Generation-scoped Consumer lease restricted to one declared requirement."""

    requirement: CapabilityRequirement
    _lease: RuntimeBindingLease[CapabilityBundleValue] = field(
        repr=False,
        compare=False,
    )

    @property
    def facet_ids(self) -> tuple[str, ...]:
        return self.requirement.facets

    @property
    def is_current(self) -> bool:
        return self._lease.is_current

    def require(self, facet_id: str) -> object:
        if facet_id not in self.requirement.facets:
            raise KeyError(f"facet is outside the Consumer requirement: {facet_id}")
        return self._lease.require().require(facet_id)


@dataclass
class _MountedCapability:
    planned: PlannedCapability
    provider_binding: CapabilityBundleProviderBinding
    value: CapabilityBundleValue
    binding_state: RuntimeBindingState[CapabilityBundleValue]
    registration_scope: RegistrationScope
    binding_signature: str
    mount_generation: int
    provider_released: bool = False


class RuntimeCapabilityGraphRuntime:
    """Own one live Mount graph; mutation is reserved for its accepted Binder."""

    def __init__(
        self,
        *,
        product_id: str,
        runtime_id: str,
        profile_fingerprint: str,
        graph_id: str | None = None,
    ) -> None:
        self._product_id = _require_nonempty(product_id, name="graph Product id")
        self._runtime_id = _require_nonempty(runtime_id, name="graph runtime id")
        self._profile_fingerprint = _require_sha256_fingerprint(
            profile_fingerprint,
            name="Runtime Profile fingerprint",
        )
        self._graph_id = _require_nonempty(
            graph_id or f"{self._product_id}:{self._runtime_id}",
            name="Mount graph id",
        )
        self._generation = 0
        self._nodes: dict[str, _MountedCapability] = {}
        self._retired_nodes: list[_MountedCapability] = []
        self._retired_scopes: list[RegistrationScope] = []
        self._snapshot: MountGraphSnapshot | None = None
        self._registration_inventory: RegistrationInventorySnapshot | None = None
        self._last_attempt: CapabilityGraphBindingAttempt | None = None
        self._attempt_number = 0
        self._binding_lock = asyncio.Lock()
        self._closed = False

    @property
    def graph_id(self) -> str:
        return self._graph_id

    @property
    def product_id(self) -> str:
        return self._product_id

    @property
    def runtime_id(self) -> str:
        return self._runtime_id

    @property
    def profile_fingerprint(self) -> str:
        return self._profile_fingerprint

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def snapshot(self) -> MountGraphSnapshot | None:
        return self._snapshot

    @property
    def registration_inventory(self) -> RegistrationInventorySnapshot | None:
        return self._registration_inventory

    @property
    def last_attempt(self) -> CapabilityGraphBindingAttempt | None:
        return self._last_attempt

    @property
    def is_closed(self) -> bool:
        return self._closed

    def capture(self, requirement: CapabilityRequirement) -> CapabilityFacetSet:
        """Capture only the facets explicitly declared by one Consumer."""

        if not isinstance(requirement, CapabilityRequirement):
            raise TypeError("graph capture requires a CapabilityRequirement")
        if self._closed:
            raise RuntimeError("Capability Mount graph is disposed")
        mounted = self._nodes.get(requirement.capability)
        if mounted is None:
            raise KeyError(
                f"Capability is not mounted in this graph: {requirement.capability}"
            )
        definition = mounted.planned.definition
        if not requirement.compatible_contract.accepts(definition.contract_version):
            raise RuntimeError("mounted Capability contract is incompatible")
        if set(requirement.facets) - set(mounted.value.facet_ids):
            raise RuntimeError("mounted Capability is missing a required facet")
        return CapabilityFacetSet(
            requirement=requirement,
            _lease=mounted.binding_state.capture(),
        )

    def _next_attempt_number(self) -> int:
        self._attempt_number += 1
        return self._attempt_number


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _require_sha256_fingerprint(value: object, *, name: str) -> str:
    fingerprint = _require_nonempty(value, name=name)
    if len(fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in fingerprint
    ):
        raise ValueError(f"{name} must be lowercase SHA-256 hex")
    return fingerprint


__all__ = [
    "CapabilityFacetSet",
    "CapabilityGraphBindingAttempt",
    "GraphBindingAttemptState",
    "MountGraphSnapshot",
    "MountLifecycleState",
    "MountNodeSnapshot",
    "MountRequirementSnapshot",
    "RegistrationInventoryEntry",
    "RegistrationInventorySnapshot",
    "RegistrationAttachmentState",
    "RuntimeCapabilityGraphRuntime",
]
