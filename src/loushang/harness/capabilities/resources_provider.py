"""Source-complete Provider for the ``harness.resources`` Capability Bundle."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

from loushang.foundation.json import dump_json_value
from loushang.harness.capabilities.composition_runtime import (
    RESOURCE_CAPABILITY_SLOT_KEYS,
    resource_capability_profile,
    standard_capability_composition_implementations,
)
from loushang.harness.capabilities.contracts import CapabilityContractRange
from loushang.harness.capabilities.packs import (
    CapabilityPack,
    CapabilityPackComposition,
)
from loushang.harness.capabilities.prompt import PreparedPrompt, PromptSection
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.capabilities.resources_contracts import (
    COMMAND_PACKS_FACET,
    PROMPT_SECTIONS_FACET,
    RESOURCE_RUNTIME_FACET,
    RESOURCES_CAPABILITY_DEFINITION,
    SKILL_ACTIVATION_FACET,
    TOOL_PACKS_FACET,
)
from loushang.harness.resources.activation import ResourceActivation
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime import (
    COMMAND_PACKS_SLOT,
    PROMPT_SECTIONS_SLOT,
    RESOURCE_RUNTIME_SLOT,
    SKILL_ACTIVATION_SLOT,
    TOOL_PACKS_SLOT,
    ResolvedRuntimeProfile,
    RuntimeCapabilityImplementation,
    RuntimeCapabilityRegistry,
    RuntimeProfileBinder,
    RuntimeProfileBinding,
)


@dataclass
class _BoundResources:
    binding: RuntimeProfileBinding = field(repr=False)
    binder: RuntimeProfileBinder = field(repr=False)

    def value(self, slot: str) -> object:
        value = self.binding.value(slot)
        if isinstance(value, tuple):
            if len(value) != 1:
                raise TypeError(f"resource facet requires one selected value: {slot}")
            return value[0]
        return value

    def dispose(self) -> None:
        self.binder.dispose_sync(self.binding)


@dataclass(frozen=True)
class _ResourceRuntimeFacet:
    _owner: _BoundResources = field(repr=False, compare=False)

    def activate(self, bundle: ResourceBundle | None) -> ResourceActivation:
        runtime = self._owner.value(RESOURCE_RUNTIME_SLOT.key)
        activate = getattr(runtime, "activate", None)
        if not callable(activate):
            raise TypeError("resource.runtime does not provide activate()")
        value = activate(bundle)
        if not isinstance(value, ResourceActivation):
            raise TypeError("resource.runtime returned an invalid activation")
        return value


@dataclass(frozen=True)
class _SkillActivationFacet:
    _owner: _BoundResources = field(repr=False, compare=False)

    def apply(
        self,
        bundle: ResourceBundle,
        disabled_skills: tuple[str, ...] | list[str],
    ) -> ResourceBundle:
        runtime = self._owner.value(SKILL_ACTIVATION_SLOT.key)
        apply = getattr(runtime, "apply", None)
        if not callable(apply):
            raise TypeError("skill.activation does not provide apply()")
        value = apply(bundle, disabled_skills)
        if not isinstance(value, ResourceBundle):
            raise TypeError("skill.activation returned an invalid ResourceBundle")
        return value


@dataclass(frozen=True)
class _PromptSectionsFacet:
    _owner: _BoundResources = field(repr=False, compare=False)

    def compose(self, sections: Iterable[PromptSection]) -> PreparedPrompt:
        composer = self._owner.value(PROMPT_SECTIONS_SLOT.key)
        compose = getattr(composer, "compose", None)
        if not callable(compose):
            raise TypeError("prompt.sections does not provide compose()")
        value = compose(sections)
        if not isinstance(value, PreparedPrompt):
            raise TypeError("prompt.sections returned an invalid PreparedPrompt")
        return value


@dataclass(frozen=True)
class _PackFacet:
    _owner: _BoundResources = field(repr=False, compare=False)
    _slot: str

    def compose(
        self,
        packs: Iterable[CapabilityPack[object]],
    ) -> CapabilityPackComposition[object]:
        composer = self._owner.value(self._slot)
        compose = getattr(composer, "compose", None)
        if not callable(compose):
            raise TypeError(f"{self._slot} does not provide compose()")
        value = compose(packs)
        if not isinstance(value, CapabilityPackComposition):
            raise TypeError(f"{self._slot} returned an invalid pack composition")
        return value


def resources_capability_provider_binding(
    *,
    profile: ResolvedRuntimeProfile,
    scope_instance_id: str,
    additional_implementations: Iterable[RuntimeCapabilityImplementation] = (),
    provider_id: str = "harness.resources.standard",
    source_id: str = "builtin",
) -> CapabilityBundleProviderBinding:
    """Map private Profile selections into one graph-owned Bundle Provider.

    The returned binding is source-complete but is not production-mounted by
    CLA3.  Resource bundles, prompt text, disabled-skill selectors, Extension
    content, and live registrations are call data and deliberately do not enter
    the construction fingerprint.
    """

    focused_profile = resource_capability_profile(profile)
    implementations = tuple(
        implementation
        for implementation in (
            *standard_capability_composition_implementations(),
            *tuple(additional_implementations),
        )
        if implementation.slot in RESOURCE_CAPABILITY_SLOT_KEYS
    )
    provider = CapabilityBundleProvider(
        capability_id=RESOURCES_CAPABILITY_DEFINITION.capability_id,
        provider_id=provider_id,
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(
            RESOURCES_CAPABILITY_DEFINITION.contract_version
        ),
        facets=RESOURCES_CAPABILITY_DEFINITION.facets,
        source_id=source_id,
        selection_rule="Product resource mechanism selections",
    )

    def create(_context: CapabilityProviderContext) -> CapabilityBundleValue:
        binder = RuntimeProfileBinder(RuntimeCapabilityRegistry(implementations))
        binding = binder.bind_sync(focused_profile)
        owner = _BoundResources(binding=binding, binder=binder)
        try:
            return CapabilityBundleValue(
                facets=(
                    CapabilityFacetBinding(
                        RESOURCE_RUNTIME_FACET,
                        _ResourceRuntimeFacet(owner),
                    ),
                    CapabilityFacetBinding(
                        PROMPT_SECTIONS_FACET,
                        _PromptSectionsFacet(owner),
                    ),
                    CapabilityFacetBinding(
                        SKILL_ACTIVATION_FACET,
                        _SkillActivationFacet(owner),
                    ),
                    CapabilityFacetBinding(
                        TOOL_PACKS_FACET,
                        _PackFacet(owner, TOOL_PACKS_SLOT.key),
                    ),
                    CapabilityFacetBinding(
                        COMMAND_PACKS_FACET,
                        _PackFacet(owner, COMMAND_PACKS_SLOT.key),
                    ),
                )
            )
        except BaseException:
            owner.dispose()
            raise

    def dispose(value: CapabilityBundleValue) -> None:
        resource_facet = value.require(RESOURCE_RUNTIME_FACET)
        if not isinstance(resource_facet, _ResourceRuntimeFacet):
            raise TypeError("resources Provider received an alien Bundle value")
        resource_facet._owner.dispose()

    return CapabilityBundleProviderBinding(
        provider=provider,
        scope_instance_id=scope_instance_id,
        binding_input_fingerprint=_binding_input_fingerprint(
            profile=focused_profile,
            scope_instance_id=scope_instance_id,
            provider_id=provider_id,
        ),
        create=create,
        dispose=dispose,
    )


def _binding_input_fingerprint(
    *,
    profile: ResolvedRuntimeProfile,
    scope_instance_id: str,
    provider_id: str,
) -> str:
    payload = dump_json_value(
        {
            "schemaVersion": 1,
            "capabilityId": RESOURCES_CAPABILITY_DEFINITION.capability_id,
            "contractVersion": RESOURCES_CAPABILITY_DEFINITION.contract_version,
            "providerId": provider_id,
            "providerVersion": 1,
            "scopeInstanceId": scope_instance_id,
            "profile": profile.snapshot().to_json(),
        },
        name="resources binding-input fingerprint",
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = ["resources_capability_provider_binding"]
