"""Narrow construction seam paired with a planned Bundle Provider."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeAlias

from loushang.harness.capabilities.contracts import CapabilityRequirement
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.runtime.registration import (
    RegistrationLease,
    RegistrationOwner,
    RegistrationScope,
)


class CapabilityRegistrationCollector:
    """Least-authority Provider view of one Binder-owned registration scope."""

    def __init__(self, scope: RegistrationScope) -> None:
        if not isinstance(scope, RegistrationScope):
            raise TypeError("registration collector requires a RegistrationScope")
        self._scope = scope

    @property
    def owner(self) -> RegistrationOwner:
        return self._scope.owner

    def add(self, lease: RegistrationLease) -> RegistrationLease:
        return self._scope.add(lease)


@dataclass(frozen=True)
class CapabilityFacetBinding:
    """One named live facet; its value is intentionally absent from repr/equality."""

    facet_id: str
    value: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "facet_id",
            _require_nonempty(self.facet_id, name="Capability facet id"),
        )


@dataclass(frozen=True)
class CapabilityBundleValue:
    """The exact live facets constructed by one selected Provider."""

    facets: tuple[CapabilityFacetBinding, ...]

    def __post_init__(self) -> None:
        facets = tuple(self.facets)
        if any(not isinstance(item, CapabilityFacetBinding) for item in facets):
            raise TypeError("Bundle value facets must be CapabilityFacetBinding values")
        facet_ids = tuple(item.facet_id for item in facets)
        if len(set(facet_ids)) != len(facet_ids):
            raise ValueError("Bundle value facets must not repeat a facet identity")
        object.__setattr__(self, "facets", facets)

    @property
    def facet_ids(self) -> tuple[str, ...]:
        return tuple(item.facet_id for item in self.facets)

    def require(self, facet_id: str) -> object:
        for facet in self.facets:
            if facet.facet_id == facet_id:
                return facet.value
        raise KeyError(f"Capability Bundle does not provide facet: {facet_id}")


@dataclass(frozen=True)
class CapabilityDependencyBinding:
    """Provider-visible view containing only one declared dependency requirement."""

    requirement: CapabilityRequirement
    _value: CapabilityBundleValue = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, CapabilityRequirement):
            raise TypeError("dependency binding requires a CapabilityRequirement")
        if not isinstance(self._value, CapabilityBundleValue):
            raise TypeError("dependency binding requires a CapabilityBundleValue")
        if set(self.requirement.facets) - set(self._value.facet_ids):
            raise ValueError("dependency binding is missing a required facet")

    @property
    def capability_id(self) -> str:
        return self.requirement.capability

    def require(self, facet_id: str) -> object:
        if facet_id not in self.requirement.facets:
            raise KeyError(f"facet is outside the declared dependency view: {facet_id}")
        return self._value.require(facet_id)


@dataclass(frozen=True)
class CapabilityProviderContext:
    """Explicit construction inputs; this is not a broad runtime/service locator."""

    product_id: str
    runtime_id: str
    generation: int
    registrations: CapabilityRegistrationCollector = field(
        repr=False,
        compare=False,
    )
    dependencies: tuple[CapabilityDependencyBinding, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "product_id",
            _require_nonempty(self.product_id, name="Provider Product id"),
        )
        object.__setattr__(
            self,
            "runtime_id",
            _require_nonempty(self.runtime_id, name="Provider runtime id"),
        )
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise TypeError("Provider generation must be an integer")
        if self.generation < 1:
            raise ValueError("Provider generation must be at least 1")
        if not isinstance(self.registrations, CapabilityRegistrationCollector):
            raise TypeError(
                "Provider registrations must be a CapabilityRegistrationCollector"
            )
        dependencies = tuple(self.dependencies)
        if any(
            not isinstance(item, CapabilityDependencyBinding) for item in dependencies
        ):
            raise TypeError(
                "Provider dependencies must be CapabilityDependencyBinding values"
            )
        capability_ids = tuple(item.capability_id for item in dependencies)
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("Provider dependencies must not repeat a Capability")
        object.__setattr__(self, "dependencies", dependencies)

    def dependency(self, capability_id: str) -> CapabilityDependencyBinding:
        for dependency in self.dependencies:
            if dependency.capability_id == capability_id:
                return dependency
        raise KeyError(f"Provider has no declared dependency: {capability_id}")


CapabilityProviderFactory: TypeAlias = Callable[
    [CapabilityProviderContext],
    CapabilityBundleValue | Awaitable[CapabilityBundleValue],
]
CapabilityProviderDisposer: TypeAlias = Callable[
    [CapabilityBundleValue],
    None | Awaitable[None],
]


@dataclass(frozen=True)
class CapabilityBundleProviderBinding:
    """Live factory/disposer paired exactly with selected Provider metadata.

    ``scope_instance_id`` is a pre-redacted diagnostic identity projected
    verbatim; it must not embed secrets or raw environment values.
    """

    provider: CapabilityBundleProvider
    scope_instance_id: str
    binding_input_fingerprint: str
    create: CapabilityProviderFactory = field(repr=False, compare=False)
    dispose: CapabilityProviderDisposer | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.provider, CapabilityBundleProvider):
            raise TypeError(
                "Provider binding requires CapabilityBundleProvider metadata"
            )
        object.__setattr__(
            self,
            "scope_instance_id",
            _require_nonempty(
                self.scope_instance_id,
                name="Provider scope-instance id",
            ),
        )
        fingerprint = _require_nonempty(
            self.binding_input_fingerprint,
            name="Provider binding-input fingerprint",
        )
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
            raise ValueError(
                "Provider binding-input fingerprint must be lowercase SHA-256 hex"
            )
        if not callable(self.create):
            raise TypeError("Provider binding create must be callable")
        if self.dispose is not None and not callable(self.dispose):
            raise TypeError("Provider binding dispose must be callable")
        object.__setattr__(self, "binding_input_fingerprint", fingerprint)

    async def construct(
        self,
        context: CapabilityProviderContext,
    ) -> CapabilityBundleValue:
        value = self.create(context)
        if inspect.isawaitable(value):
            value = await value
        if not isinstance(value, CapabilityBundleValue):
            raise TypeError("Provider factory must return a CapabilityBundleValue")
        return value

    async def release(self, value: CapabilityBundleValue) -> None:
        disposer = self.dispose
        if disposer is None:
            return
        result = disposer(value)
        if inspect.isawaitable(result):
            await result


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


__all__ = [
    "CapabilityBundleProviderBinding",
    "CapabilityBundleValue",
    "CapabilityDependencyBinding",
    "CapabilityFacetBinding",
    "CapabilityProviderContext",
    "CapabilityProviderDisposer",
    "CapabilityProviderFactory",
    "CapabilityRegistrationCollector",
]
