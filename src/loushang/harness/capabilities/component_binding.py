"""Narrow construction seam for selected Capability owner components."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TypeAlias

from loushang.harness.capabilities.component_contracts import (
    _digest_document,
    _require_nonempty,
    _require_sha256,
)
from loushang.harness.capabilities.component_selection import (
    ResolvedCapabilityComponent,
)


@dataclass(frozen=True, slots=True)
class CapabilityComponentDependencyView:
    """One owner-approved service reference exposed to a component factory."""

    service_reference: str
    value: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_nonempty(
            self.service_reference,
            name="component dependency service reference",
        )


@dataclass(frozen=True, slots=True)
class CapabilityOwnerComponentContext:
    """Least-authority owner inputs; never a runtime-wide service locator."""

    product_id: str
    runtime_id: str
    owner_generation: int
    resolved: ResolvedCapabilityComponent
    owner_inputs: Mapping[str, object] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    dependencies: tuple[CapabilityComponentDependencyView, ...] = ()
    binding_inputs: Mapping[str, object] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _require_nonempty(self.product_id, name="component Product id")
        _require_nonempty(self.runtime_id, name="component runtime id")
        if isinstance(self.owner_generation, bool) or not isinstance(
            self.owner_generation, int
        ):
            raise TypeError("Owner component generation must be an integer")
        if self.owner_generation < 1:
            raise ValueError("Owner component generation must be positive")
        if not isinstance(self.resolved, ResolvedCapabilityComponent):
            raise TypeError("Component context requires a resolved component")
        if self.product_id != self.resolved.admission.candidate.product_id:
            raise ValueError("Component context Product does not match its selection")
        dependencies = tuple(self.dependencies)
        if any(
            not isinstance(item, CapabilityComponentDependencyView)
            for item in dependencies
        ):
            raise TypeError("Component dependencies must use typed views")
        references = tuple(item.service_reference for item in dependencies)
        if len(set(references)) != len(references):
            raise ValueError("Component dependencies must not repeat a service")
        if set(references) - set(self.resolved.definition.service_references):
            raise ValueError("Component dependency is outside its Definition")
        if not isinstance(self.owner_inputs, Mapping):
            raise TypeError("Component owner inputs must be a mapping")
        if not isinstance(self.binding_inputs, Mapping):
            raise TypeError("Component binding inputs must be a mapping")
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(
            self,
            "owner_inputs",
            MappingProxyType(dict(self.owner_inputs)),
        )
        object.__setattr__(
            self,
            "binding_inputs",
            MappingProxyType(dict(self.binding_inputs)),
        )

    def dependency(self, service_reference: str) -> object:
        if service_reference not in self.resolved.definition.service_references:
            raise KeyError(
                f"service is outside the component Definition: {service_reference}"
            )
        for dependency in self.dependencies:
            if dependency.service_reference == service_reference:
                return dependency.value
        raise KeyError(f"component dependency was not supplied: {service_reference}")


@dataclass(frozen=True, slots=True, init=False)
class CapabilityOwnerComponentValue:
    """One constructed payload paired with its exact selected identity."""

    component_id: str
    owner_generation: int
    binding_fingerprint: str
    payload: object = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("Owner component value is Binding-constructed")

    def __post_init__(self) -> None:
        _require_nonempty(self.component_id, name="component value id")
        if isinstance(self.owner_generation, bool) or not isinstance(
            self.owner_generation, int
        ):
            raise TypeError("Component value generation must be an integer")
        if self.owner_generation < 1:
            raise ValueError("Component value generation must be positive")
        _require_sha256(
            self.binding_fingerprint,
            name="component value binding fingerprint",
        )


CapabilityOwnerComponentFactory: TypeAlias = Callable[
    [CapabilityOwnerComponentContext],
    object | Awaitable[object],
]
CapabilityOwnerComponentDisposer: TypeAlias = Callable[
    [CapabilityOwnerComponentValue],
    None | Awaitable[None],
]
CapabilityOwnerComponentPayloadValidator: TypeAlias = Callable[[object], None]


def owner_component_binding_fingerprint(
    resolved: ResolvedCapabilityComponent,
) -> str:
    """Derive the sole legal binding identity from the complete selected chain."""

    if not isinstance(resolved, ResolvedCapabilityComponent):
        raise TypeError("Component binding fingerprint requires a resolved component")
    return _digest_document(
        "loushang.capability-owner-component-binding/v1",
        {
            "bindingSpecFingerprint": (
                resolved.admission.candidate.binding_spec.fingerprint
            ),
            "resolvedComponentFingerprint": resolved.fingerprint,
        },
    )


@dataclass(frozen=True, slots=True)
class CapabilityOwnerComponentBinding:
    """Factory/disposer bound exactly to one resolved admission chain."""

    resolved: ResolvedCapabilityComponent
    binding_fingerprint: str
    create: CapabilityOwnerComponentFactory = field(repr=False, compare=False)
    validate_payload: CapabilityOwnerComponentPayloadValidator = field(
        repr=False,
        compare=False,
    )
    dispose: CapabilityOwnerComponentDisposer | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.resolved, ResolvedCapabilityComponent):
            raise TypeError("Component binding requires a resolved component")
        _require_sha256(
            self.binding_fingerprint,
            name="owner component binding fingerprint",
        )
        if self.binding_fingerprint != owner_component_binding_fingerprint(
            self.resolved
        ):
            raise ValueError("Component binding fingerprint does not match selection")
        if not callable(self.create):
            raise TypeError("Component binding create must be callable")
        if not callable(self.validate_payload):
            raise TypeError("Component payload validator must be callable")
        if self.dispose is not None and not callable(self.dispose):
            raise TypeError("Component binding dispose must be callable")
        if (
            self.resolved.definition.disposer_contract == "required"
            and self.dispose is None
        ):
            raise ValueError("Component Definition requires a disposer")

    async def construct(
        self,
        context: CapabilityOwnerComponentContext,
    ) -> CapabilityOwnerComponentValue:
        if context.resolved.fingerprint != self.resolved.fingerprint:
            raise ValueError("Component context does not match its exact binding")
        payload = self.create(context)
        if inspect.isawaitable(payload):
            payload = await payload
        value = _binding_construct_value(
            component_id=self.resolved.component_id,
            owner_generation=context.owner_generation,
            binding_fingerprint=self.binding_fingerprint,
            payload=payload,
        )
        try:
            self.validate_payload(value.payload)
        except Exception:
            await self.release(value)
            raise
        return value

    async def release(self, value: CapabilityOwnerComponentValue) -> None:
        if not isinstance(value, CapabilityOwnerComponentValue):
            raise TypeError("Component disposer requires a Binding-constructed value")
        if (
            value.component_id != self.resolved.component_id
            or value.binding_fingerprint != self.binding_fingerprint
        ):
            raise ValueError("Component disposer cannot retire another binding")
        disposer = self.dispose
        if disposer is None:
            return
        result = disposer(value)
        if inspect.isawaitable(result):
            await result


def _binding_construct_value(
    *,
    component_id: str,
    owner_generation: int,
    binding_fingerprint: str,
    payload: object,
) -> CapabilityOwnerComponentValue:
    value = object.__new__(CapabilityOwnerComponentValue)
    object.__setattr__(value, "component_id", component_id)
    object.__setattr__(value, "owner_generation", owner_generation)
    object.__setattr__(value, "binding_fingerprint", binding_fingerprint)
    object.__setattr__(value, "payload", payload)
    value.__post_init__()
    return value


__all__ = [
    "CapabilityComponentDependencyView",
    "CapabilityOwnerComponentBinding",
    "CapabilityOwnerComponentContext",
    "CapabilityOwnerComponentDisposer",
    "CapabilityOwnerComponentFactory",
    "CapabilityOwnerComponentPayloadValidator",
    "CapabilityOwnerComponentValue",
    "owner_component_binding_fingerprint",
]
