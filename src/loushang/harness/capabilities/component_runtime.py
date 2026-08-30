"""Atomic owner-generation construction, publication, pinning, and disposal."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from loushang.harness.capabilities.component_binding import (
    CapabilityComponentDependencyView,
    CapabilityOwnerComponentBinding,
    CapabilityOwnerComponentContext,
    CapabilityOwnerComponentValue,
)
from loushang.harness.capabilities.component_contracts import (
    _digest_document,
    _require_nonempty,
    _require_sha256,
)
from loushang.harness.capabilities.component_selection import (
    ResolvedCapabilityComponentSet,
)
from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic

OwnerComponentGenerationState = Literal["published", "retiring", "disposed"]


class CapabilityOwnerComponentBindingError(RuntimeError):
    """Redacted atomic owner-generation construction or retirement failure."""

    def __init__(self, diagnostic_codes: tuple[str, ...]) -> None:
        self.diagnostic_codes = tuple(sorted(set(diagnostic_codes)))
        super().__init__(
            "Capability owner-component binding failed: "
            + ", ".join(self.diagnostic_codes)
        )


@dataclass(frozen=True, slots=True)
class CapabilityOwnerComponentGenerationEntry:
    component_kind: str
    component_id: str
    admission_fingerprint: str
    binding_fingerprint: str
    selection_ordinal: int

    def __post_init__(self) -> None:
        _require_nonempty(self.component_kind, name="generation component kind")
        _require_nonempty(self.component_id, name="generation component id")
        _require_sha256(
            self.admission_fingerprint,
            name="generation component admission fingerprint",
        )
        _require_sha256(
            self.binding_fingerprint,
            name="generation component binding fingerprint",
        )
        if isinstance(self.selection_ordinal, bool) or not isinstance(
            self.selection_ordinal, int
        ):
            raise TypeError("Generation component ordinal must be an integer")
        if self.selection_ordinal < 0:
            raise ValueError("Generation component ordinal cannot be negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "admissionFingerprint": self.admission_fingerprint,
            "bindingFingerprint": self.binding_fingerprint,
            "componentId": self.component_id,
            "componentKind": self.component_kind,
            "selectionOrdinal": self.selection_ordinal,
        }


@dataclass(frozen=True, slots=True)
class CapabilityOwnerComponentGenerationSnapshot:
    capability_id: str
    owner_id: str
    product_id: str
    runtime_id: str
    generation: int
    resolved_set_fingerprint: str
    entries: tuple[CapabilityOwnerComponentGenerationEntry, ...]
    generation_fingerprint: str

    def __post_init__(self) -> None:
        for name, value in (
            ("Capability id", self.capability_id),
            ("Capability owner id", self.owner_id),
            ("Product id", self.product_id),
            ("runtime id", self.runtime_id),
        ):
            _require_nonempty(value, name=name)
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise TypeError("Owner component generation must be an integer")
        if self.generation < 1:
            raise ValueError("Owner component generation must be positive")
        _require_sha256(
            self.resolved_set_fingerprint,
            name="resolved component set fingerprint",
        )
        entries = tuple(self.entries)
        if any(
            not isinstance(item, CapabilityOwnerComponentGenerationEntry)
            for item in entries
        ):
            raise TypeError("Owner generation entries must be typed records")
        if tuple(item.selection_ordinal for item in entries) != tuple(
            range(len(entries))
        ):
            raise ValueError("Owner generation entries must preserve selection order")
        _require_sha256(
            self.generation_fingerprint,
            name="owner generation fingerprint",
        )
        if self.generation_fingerprint != _generation_fingerprint(
            capability_id=self.capability_id,
            owner_id=self.owner_id,
            product_id=self.product_id,
            runtime_id=self.runtime_id,
            generation=self.generation,
            resolved_set_fingerprint=self.resolved_set_fingerprint,
            entries=entries,
        ):
            raise ValueError("Owner generation fingerprint is inconsistent")
        object.__setattr__(self, "entries", entries)


@dataclass(slots=True)
class _MountedOwnerComponent:
    binding: CapabilityOwnerComponentBinding
    value: CapabilityOwnerComponentValue
    released: bool = False


@dataclass(slots=True)
class _OwnerGeneration:
    snapshot: CapabilityOwnerComponentGenerationSnapshot
    mounted: tuple[_MountedOwnerComponent, ...]
    state: OwnerComponentGenerationState = "published"
    lease_count: int = 0
    disposing: bool = False


@dataclass(slots=True)
class CapabilityOwnerComponentLease:
    """Explicit pin on one exact owner generation and component value."""

    _runtime: CapabilityOwnerComponentRuntime = field(repr=False)
    _generation: _OwnerGeneration = field(repr=False)
    _mounted: _MountedOwnerComponent = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def generation(self) -> int:
        return self._generation.snapshot.generation

    @property
    def component_id(self) -> str:
        return self._mounted.value.component_id

    @property
    def is_open(self) -> bool:
        return not self._closed

    def require(self) -> object:
        if self._closed or self._generation.state == "disposed":
            raise RuntimeError("Capability owner-component lease is closed")
        return self._mounted.value.payload

    async def aclose(self) -> tuple[str, ...]:
        return await self._runtime._release_lease(self)

    async def __aenter__(self) -> CapabilityOwnerComponentLease:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()


@dataclass(frozen=True, slots=True)
class CapabilityOwnerComponentBindResult:
    snapshot: CapabilityOwnerComponentGenerationSnapshot
    retirement_diagnostic_codes: tuple[str, ...] = ()


class CapabilityOwnerComponentRuntime:
    """Own component generations inside one mounted Capability."""

    def __init__(
        self,
        *,
        capability_id: str,
        owner_id: str,
        product_id: str,
        runtime_id: str,
    ) -> None:
        self._capability_id = _require_nonempty(
            capability_id,
            name="owner-component Capability id",
        )
        self._owner_id = _require_nonempty(owner_id, name="Capability owner id")
        if not self._capability_id.startswith(f"{self._owner_id}."):
            raise ValueError("Owner-component runtime owner does not own its Capability")
        self._product_id = _require_nonempty(product_id, name="component Product id")
        self._runtime_id = _require_nonempty(runtime_id, name="component runtime id")
        self._owner_generation = 0
        self._current: _OwnerGeneration | None = None
        self._retired: list[_OwnerGeneration] = []
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def capability_id(self) -> str:
        return self._capability_id

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def product_id(self) -> str:
        return self._product_id

    @property
    def runtime_id(self) -> str:
        return self._runtime_id

    @property
    def generation(self) -> int:
        return self._owner_generation

    @property
    def snapshot(self) -> CapabilityOwnerComponentGenerationSnapshot | None:
        return None if self._current is None else self._current.snapshot

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def has_pending_retirements(self) -> bool:
        return bool(self._retired)

    def capture_one(self, component_kind: str) -> CapabilityOwnerComponentLease:
        leases = self._capture(component_kind)
        if len(leases) != 1:
            for lease in leases:
                lease._closed = True
                lease._generation.lease_count -= 1
            raise RuntimeError("Component kind is not an exclusive mounted value")
        return leases[0]

    def capture_all(
        self,
        component_kind: str,
    ) -> tuple[CapabilityOwnerComponentLease, ...]:
        return self._capture(component_kind)

    def _capture(self, component_kind: str) -> tuple[CapabilityOwnerComponentLease, ...]:
        _require_nonempty(component_kind, name="captured component kind")
        if self._closed:
            raise RuntimeError("Capability owner-component runtime is disposed")
        generation = self._current
        if generation is None or generation.state != "published":
            raise RuntimeError("Capability owner-component generation is not mounted")
        mounted = tuple(
            item
            for item in generation.mounted
            if item.binding.resolved.definition.component_kind == component_kind
        )
        if not mounted:
            raise KeyError(f"Component kind is not mounted: {component_kind}")
        generation.lease_count += len(mounted)
        return tuple(
            CapabilityOwnerComponentLease(self, generation, item) for item in mounted
        )

    async def _release_lease(
        self,
        lease: CapabilityOwnerComponentLease,
    ) -> tuple[str, ...]:
        async with self._lock:
            if lease._runtime is not self:
                raise ValueError("Component lease belongs to another runtime")
            if lease._closed:
                return ()
            lease._closed = True
            generation = lease._generation
            if generation.lease_count < 1:
                raise RuntimeError("Component generation lease accounting is corrupt")
            generation.lease_count -= 1
        cleanup_task = asyncio.create_task(self._drain_ready())
        return await _await_cancellation_atomic(cleanup_task)

    async def _drain_ready(self) -> tuple[str, ...]:
        async with self._lock:
            ready = tuple(
                generation
                for generation in self._retired
                if generation.lease_count == 0 and not generation.disposing
            )
            for generation in ready:
                generation.disposing = True
        if not ready:
            return ()
        codes = await _dispose_generations(ready)
        async with self._lock:
            self._retired = [
                generation
                for generation in self._retired
                if generation.state != "disposed"
            ]
        return codes


class CapabilityOwnerComponentBinder:
    """Construct all selected components before one no-await owner publication."""

    async def bind(
        self,
        runtime: CapabilityOwnerComponentRuntime,
        resolved_set: ResolvedCapabilityComponentSet,
        bindings: tuple[CapabilityOwnerComponentBinding, ...],
        *,
        owner_inputs: Mapping[str, Mapping[str, object]] | None = None,
        dependency_views: Mapping[
            str, tuple[CapabilityComponentDependencyView, ...]
        ]
        | None = None,
    ) -> CapabilityOwnerComponentBindResult:
        if not isinstance(runtime, CapabilityOwnerComponentRuntime):
            raise TypeError("Owner-component Binder requires its runtime")
        if not isinstance(resolved_set, ResolvedCapabilityComponentSet):
            raise TypeError("Owner-component Binder requires a resolved set")
        binding_by_admission = _index_bindings(bindings)
        self._validate_target(runtime, resolved_set, binding_by_admission)
        owner_inputs = {} if owner_inputs is None else owner_inputs
        dependency_views = {} if dependency_views is None else dependency_views

        async with runtime._lock:
            if runtime._closed:
                raise RuntimeError("Capability owner-component runtime is disposed")
            target_generation = runtime.generation + 1
            staged: list[_MountedOwnerComponent] = []
            try:
                for resolved in resolved_set.components:
                    binding = binding_by_admission[resolved.admission_fingerprint]
                    component_id = resolved.component_id
                    value = await binding.construct(
                        CapabilityOwnerComponentContext(
                            product_id=runtime.product_id,
                            runtime_id=runtime.runtime_id,
                            owner_generation=target_generation,
                            resolved=resolved,
                            owner_inputs=owner_inputs.get(component_id, {}),
                            dependencies=dependency_views.get(component_id, ()),
                            binding_inputs=(
                                resolved.admission.candidate.binding_spec.binding_inputs
                            ),
                        )
                    )
                    staged.append(
                        _MountedOwnerComponent(binding=binding, value=value)
                    )
                # Last cancellable point before the synchronous publication window.
                await asyncio.sleep(0)
                snapshot = _generation_snapshot(
                    runtime=runtime,
                    resolved_set=resolved_set,
                    bindings=binding_by_admission,
                    generation=target_generation,
                )
            except asyncio.CancelledError:
                cleanup = asyncio.create_task(_rollback_staged(tuple(staged)))
                await _await_cancellation_atomic(cleanup)
                raise
            except Exception as exc:
                cleanup = asyncio.create_task(_rollback_staged(tuple(staged)))
                rollback_codes = await _await_cancellation_atomic(cleanup)
                codes = ("component_construction_failed", *rollback_codes)
                raise CapabilityOwnerComponentBindingError(codes) from exc

            previous = runtime._current
            current = _OwnerGeneration(snapshot=snapshot, mounted=tuple(staged))
            runtime._current = current
            runtime._owner_generation = target_generation
            if previous is not None:
                previous.state = "retiring"
                runtime._retired.append(previous)

        cleanup_task = asyncio.create_task(runtime._drain_ready())
        retirement_codes = await _await_cancellation_atomic(cleanup_task)
        return CapabilityOwnerComponentBindResult(
            snapshot=snapshot,
            retirement_diagnostic_codes=retirement_codes,
        )

    async def drain(
        self,
        runtime: CapabilityOwnerComponentRuntime,
    ) -> tuple[str, ...]:
        if not isinstance(runtime, CapabilityOwnerComponentRuntime):
            raise TypeError("Owner-component Binder requires its runtime")
        cleanup_task = asyncio.create_task(runtime._drain_ready())
        return await _await_cancellation_atomic(cleanup_task)

    async def dispose(
        self,
        runtime: CapabilityOwnerComponentRuntime,
    ) -> tuple[str, ...]:
        if not isinstance(runtime, CapabilityOwnerComponentRuntime):
            raise TypeError("Owner-component Binder requires its runtime")
        async with runtime._lock:
            if not runtime._closed:
                runtime._closed = True
                current = runtime._current
                runtime._current = None
                if current is not None:
                    current.state = "retiring"
                    runtime._retired.append(current)
        cleanup_task = asyncio.create_task(runtime._drain_ready())
        return await _await_cancellation_atomic(cleanup_task)

    @staticmethod
    def _validate_target(
        runtime: CapabilityOwnerComponentRuntime,
        resolved_set: ResolvedCapabilityComponentSet,
        binding_by_admission: Mapping[str, CapabilityOwnerComponentBinding],
    ) -> None:
        if (
            resolved_set.product_id != runtime.product_id
            or resolved_set.capability_id != runtime.capability_id
            or resolved_set.owner_id != runtime.owner_id
        ):
            raise ValueError("Resolved component set targets another owner runtime")
        selected = tuple(
            component.admission_fingerprint
            for component in resolved_set.components
        )
        if set(binding_by_admission) != set(selected):
            raise CapabilityOwnerComponentBindingError(
                ("component_binding_set_mismatch",)
            )
        for resolved in resolved_set.components:
            binding = binding_by_admission[resolved.admission_fingerprint]
            if binding.resolved.fingerprint != resolved.fingerprint:
                raise CapabilityOwnerComponentBindingError(
                    ("component_binding_selection_mismatch",)
                )


def _index_bindings(
    bindings: tuple[CapabilityOwnerComponentBinding, ...],
) -> dict[str, CapabilityOwnerComponentBinding]:
    indexed: dict[str, CapabilityOwnerComponentBinding] = {}
    for binding in bindings:
        if not isinstance(binding, CapabilityOwnerComponentBinding):
            raise TypeError("Component bindings must be typed records")
        fingerprint = binding.resolved.admission_fingerprint
        if fingerprint in indexed:
            raise ValueError("Component bindings must not repeat an admission")
        indexed[fingerprint] = binding
    return indexed


def _generation_snapshot(
    *,
    runtime: CapabilityOwnerComponentRuntime,
    resolved_set: ResolvedCapabilityComponentSet,
    bindings: Mapping[str, CapabilityOwnerComponentBinding],
    generation: int,
) -> CapabilityOwnerComponentGenerationSnapshot:
    entries = tuple(
        CapabilityOwnerComponentGenerationEntry(
            component_kind=resolved.definition.component_kind,
            component_id=resolved.component_id,
            admission_fingerprint=resolved.admission_fingerprint,
            binding_fingerprint=bindings[
                resolved.admission_fingerprint
            ].binding_fingerprint,
            selection_ordinal=resolved.selection_ordinal,
        )
        for resolved in resolved_set.components
    )
    fingerprint = _generation_fingerprint(
        capability_id=runtime.capability_id,
        owner_id=runtime.owner_id,
        product_id=runtime.product_id,
        runtime_id=runtime.runtime_id,
        generation=generation,
        resolved_set_fingerprint=resolved_set.fingerprint,
        entries=entries,
    )
    return CapabilityOwnerComponentGenerationSnapshot(
        capability_id=runtime.capability_id,
        owner_id=runtime.owner_id,
        product_id=runtime.product_id,
        runtime_id=runtime.runtime_id,
        generation=generation,
        resolved_set_fingerprint=resolved_set.fingerprint,
        entries=entries,
        generation_fingerprint=fingerprint,
    )


def _generation_fingerprint(
    *,
    capability_id: str,
    owner_id: str,
    product_id: str,
    runtime_id: str,
    generation: int,
    resolved_set_fingerprint: str,
    entries: tuple[CapabilityOwnerComponentGenerationEntry, ...],
) -> str:
    return _digest_document(
        "loushang.capability-owner-component-generation/v1",
        {
            "capabilityId": capability_id,
            "entries": [entry.to_dict() for entry in entries],
            "generation": generation,
            "ownerId": owner_id,
            "productId": product_id,
            "resolvedSetFingerprint": resolved_set_fingerprint,
            "runtimeId": runtime_id,
        },
    )


async def _rollback_staged(
    staged: tuple[_MountedOwnerComponent, ...],
) -> tuple[str, ...]:
    codes: list[str] = []
    for mounted in reversed(staged):
        try:
            await mounted.binding.release(mounted.value)
        except asyncio.CancelledError:
            codes.append("component_rollback_cancelled")
        except Exception:
            codes.append("component_rollback_failed")
    return tuple(sorted(set(codes)))


async def _dispose_generations(
    generations: tuple[_OwnerGeneration, ...],
) -> tuple[str, ...]:
    codes: list[str] = []
    for generation in generations:
        for mounted in reversed(generation.mounted):
            if mounted.released:
                continue
            try:
                await mounted.binding.release(mounted.value)
            except Exception:
                codes.append("component_retirement_failed")
            else:
                mounted.released = True
        generation.disposing = False
        if all(mounted.released for mounted in generation.mounted):
            generation.state = "disposed"
        else:
            generation.state = "retiring"
    return tuple(sorted(set(codes)))


__all__ = [
    "CapabilityOwnerComponentBindResult",
    "CapabilityOwnerComponentBinder",
    "CapabilityOwnerComponentBindingError",
    "CapabilityOwnerComponentGenerationEntry",
    "CapabilityOwnerComponentGenerationSnapshot",
    "CapabilityOwnerComponentLease",
    "CapabilityOwnerComponentRuntime",
    "OwnerComponentGenerationState",
]
