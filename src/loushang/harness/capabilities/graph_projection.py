"""Read-only observation of the committed Capability Mount graph."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.foundation.json import JSONValue
from loushang.harness.capabilities.effective_runtime import (
    EffectiveRuntimeClocks,
    EffectiveRuntimeDiff,
    EffectiveRuntimeView,
    ModelSurfaceReference,
    RuntimeProfileSlotReference,
    compose_effective_runtime_view,
    diff_effective_runtime_views,
    effective_runtime_clocks,
    runtime_projection_to_json,
)
from loushang.harness.capabilities.graph_runtime import (
    CapabilityGraphBindingAttempt,
    MountGraphSnapshot,
    MountNodeSnapshot,
    RegistrationInventoryEntry,
    RegistrationInventorySnapshot,
    RuntimeCapabilityGraphRuntime,
)
from loushang.harness.runtime import RuntimeProfileSnapshot


@dataclass(frozen=True)
class CapabilityGraphExplanation:
    graph_id: str
    capability_id: str
    node: MountNodeSnapshot
    dependencies: tuple[str, ...]
    dependents: tuple[str, ...]
    registration_ids: tuple[str, ...]
    last_attempt: CapabilityGraphBindingAttempt | None
    clocks: EffectiveRuntimeClocks
    registrations: tuple[RegistrationInventoryEntry, ...]


@dataclass(frozen=True)
class RuntimeProfileSlotExplanation:
    product_id: str
    runtime_id: str
    clocks: EffectiveRuntimeClocks
    slot: RuntimeProfileSlotReference


@dataclass(frozen=True)
class RegistrationExplanation:
    product_id: str
    runtime_id: str
    clocks: EffectiveRuntimeClocks
    entry: RegistrationInventoryEntry
    owner_node: MountNodeSnapshot | None


RuntimeProjection = (
    EffectiveRuntimeView
    | EffectiveRuntimeDiff
    | CapabilityGraphExplanation
    | RuntimeProfileSlotExplanation
    | RegistrationExplanation
    | MountGraphSnapshot
    | RegistrationInventorySnapshot
)


class RuntimeCapabilityGraphProjector:
    """Project one runtime instance; it neither selects nor mutates Providers."""

    def __init__(self, runtime: RuntimeCapabilityGraphRuntime) -> None:
        if not isinstance(runtime, RuntimeCapabilityGraphRuntime):
            raise TypeError("graph Projector requires RuntimeCapabilityGraphRuntime")
        self._runtime = runtime

    def snapshot(self, graph_id: str | None = None) -> MountGraphSnapshot:
        if graph_id is not None and graph_id != self._runtime.graph_id:
            raise KeyError(f"Projector does not own Mount graph: {graph_id}")
        if self._runtime.is_closed:
            raise RuntimeError("Capability Mount graph is disposed")
        snapshot = self._runtime.snapshot
        if snapshot is None:
            raise RuntimeError("Capability Mount graph has not been committed")
        return snapshot

    def registration_inventory(self) -> RegistrationInventorySnapshot:
        inventory = self._runtime.registration_inventory
        if inventory is None:
            raise RuntimeError("Capability registration inventory is not committed")
        return inventory

    def effective_view(
        self,
        profile: RuntimeProfileSnapshot,
        *,
        model_surface: ModelSurfaceReference | None = None,
        registrations: RegistrationInventorySnapshot | None = None,
    ) -> EffectiveRuntimeView:
        return compose_effective_runtime_view(
            self.snapshot(),
            self._registrations(registrations),
            profile,
            model_surface=model_surface,
        )

    def explain(
        self,
        capability_id: str,
        *,
        profile: RuntimeProfileSnapshot | None = None,
        model_surface: ModelSurfaceReference | None = None,
        registrations: RegistrationInventorySnapshot | None = None,
    ) -> CapabilityGraphExplanation:
        node = self._node(capability_id)
        inventory = self._registrations(registrations)
        capability_registrations = self._registrations_for(
            capability_id,
            inventory=inventory,
        )
        clocks = self._clocks(
            profile=profile,
            model_surface=model_surface,
            registrations=inventory,
        )
        return CapabilityGraphExplanation(
            graph_id=self._runtime.graph_id,
            capability_id=capability_id,
            node=node,
            dependencies=self.dependencies(capability_id),
            dependents=self.dependents(capability_id),
            registration_ids=tuple(
                registration.registration_id
                for registration in capability_registrations
            ),
            last_attempt=self._runtime.last_attempt,
            clocks=clocks,
            registrations=capability_registrations,
        )

    def explain_profile_slot(
        self,
        profile: RuntimeProfileSnapshot,
        slot: str,
        *,
        model_surface: ModelSurfaceReference | None = None,
        registrations: RegistrationInventorySnapshot | None = None,
    ) -> RuntimeProfileSlotExplanation:
        view = self.effective_view(
            profile,
            model_surface=model_surface,
            registrations=registrations,
        )
        for reference in view.profile_slots:
            if reference.slot == slot:
                return RuntimeProfileSlotExplanation(
                    product_id=view.product_id,
                    runtime_id=view.runtime_id,
                    clocks=view.clocks,
                    slot=reference,
                )
        raise KeyError(f"Runtime Profile slot is not selected: {slot}")

    def explain_registration(
        self,
        registration_id: str,
        *,
        profile: RuntimeProfileSnapshot | None = None,
        model_surface: ModelSurfaceReference | None = None,
        registrations: RegistrationInventorySnapshot | None = None,
    ) -> RegistrationExplanation:
        inventory = self._registrations(registrations)
        matches = tuple(
            entry
            for entry in inventory.entries
            if entry.registration_id == registration_id
        )
        if len(matches) != 1:
            raise KeyError(
                "Registration is not uniquely present in the inventory: "
                f"{registration_id}"
            )
        entry = matches[0]
        owner_node = None
        if entry.owner_kind == "capability" and entry.attachment == "effective":
            candidate = self._node(entry.owner_id)
            if candidate.mount_generation == entry.owner_generation:
                owner_node = candidate
        return RegistrationExplanation(
            product_id=self._runtime.product_id,
            runtime_id=self._runtime.runtime_id,
            clocks=self._clocks(
                profile=profile,
                model_surface=model_surface,
                registrations=inventory,
            ),
            entry=entry,
            owner_node=owner_node,
        )

    def dependencies(self, capability_id: str) -> tuple[str, ...]:
        node = self._node(capability_id)
        return tuple(item.capability_id for item in node.requirements)

    def dependents(self, capability_id: str) -> tuple[str, ...]:
        return self._node(capability_id).required_by

    def impact(self, capability_id: str) -> tuple[str, ...]:
        self._node(capability_id)
        impacted: set[str] = set()
        pending = list(self.dependents(capability_id))
        while pending:
            candidate = pending.pop(0)
            if candidate in impacted:
                continue
            impacted.add(candidate)
            pending.extend(self.dependents(candidate))
        order = tuple(node.capability_id for node in self.snapshot().nodes)
        return tuple(node_id for node_id in order if node_id in impacted)

    def diff(
        self,
        before: EffectiveRuntimeView,
        after: EffectiveRuntimeView,
    ) -> EffectiveRuntimeDiff:
        return diff_effective_runtime_views(before, after)

    def to_json(self, value: RuntimeProjection) -> dict[str, JSONValue]:
        if not isinstance(
            value,
            (
                EffectiveRuntimeView,
                EffectiveRuntimeDiff,
                CapabilityGraphExplanation,
                RuntimeProfileSlotExplanation,
                RegistrationExplanation,
                MountGraphSnapshot,
                RegistrationInventorySnapshot,
            ),
        ):
            raise TypeError("unsupported runtime projection value")
        return runtime_projection_to_json(value)

    def _clocks(
        self,
        *,
        profile: RuntimeProfileSnapshot | None,
        model_surface: ModelSurfaceReference | None,
        registrations: RegistrationInventorySnapshot | None = None,
    ) -> EffectiveRuntimeClocks:
        return effective_runtime_clocks(
            self.snapshot(),
            self._registrations(registrations),
            profile=profile,
            model_surface=model_surface,
        )

    def _node(self, capability_id: str) -> MountNodeSnapshot:
        for node in self.snapshot().nodes:
            if node.capability_id == capability_id:
                return node
        raise KeyError(f"Capability is not present in the Mount graph: {capability_id}")

    def _registrations_for(
        self,
        capability_id: str,
        *,
        inventory: RegistrationInventorySnapshot | None = None,
    ) -> tuple[RegistrationInventoryEntry, ...]:
        return tuple(
            entry
            for entry in self._registrations(inventory).entries
            if entry.owner_id == capability_id
            and entry.owner_kind == "capability"
            and entry.attachment == "effective"
        )

    def _registrations(
        self,
        inventory: RegistrationInventorySnapshot | None,
    ) -> RegistrationInventorySnapshot:
        if inventory is None:
            return self.registration_inventory()
        if not isinstance(inventory, RegistrationInventorySnapshot):
            raise TypeError("registrations must be RegistrationInventorySnapshot")
        graph = self.snapshot()
        if (
            inventory.graph_id != graph.graph_id
            or inventory.runtime_id != graph.runtime_id
        ):
            raise ValueError("registration inventory and Mount graph ids differ")
        return inventory


__all__ = [
    "CapabilityGraphExplanation",
    "RegistrationExplanation",
    "RuntimeCapabilityGraphProjector",
    "RuntimeProfileSlotExplanation",
]
