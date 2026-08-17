"""Standard runtime binding for Product capability composition.

This module binds the Product-selected mechanisms for resource activation,
prompt sections, skill activation, and capability packs.  Product plans own
which mechanisms they select and the values they pass to them; this module
owns only the neutral factories and their configuration contracts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TypeVar

from loushang.harness.capabilities.packs import (
    CapabilityPack,
    CapabilityPackComposer,
    CapabilityPackComposition,
)
from loushang.harness.capabilities.prompt import PromptSectionComposer
from loushang.harness.resources.activation import (
    ResourceActivation,
    ResourceActivationRuntime,
    SkillActivationRuntime,
)
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.runtime import (
    COMMAND_PACKS_SLOT,
    PROMPT_SECTIONS_SLOT,
    RESOURCE_RUNTIME_SLOT,
    SIDE_QUESTION_PROVIDER_SLOT,
    SKILL_ACTIVATION_SLOT,
    TOOL_PACKS_SLOT,
    ProductRuntimePlan,
    ResolvedRuntimeProfile,
    RuntimeCapabilityImplementation,
    RuntimeCapabilityRegistry,
    RuntimeCapabilitySelection,
    RuntimeProfileBinder,
    RuntimeProfileBinding,
    RuntimeProfileSource,
    SessionSideQuestionProviderFactory,
    SideQuestionProviderFactory,
    standard_capability_composition_slots,
)

RESOURCE_ACTIVATION_IMPLEMENTATION = "harness.resource_activation"
PROMPT_SECTIONS_IMPLEMENTATION = "harness.prompt_sections"
DISABLED_SKILL_ACTIVATION_IMPLEMENTATION = "harness.disabled_skill_activation"
ORDERED_CAPABILITY_PACKS_IMPLEMENTATION = "harness.ordered_capability_packs"
AGENT_SIDE_QUESTION_IMPLEMENTATION = "harness.agent_side_question"
CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION = 1
RESOURCE_CAPABILITY_SLOT_KEYS = frozenset(
    {
        RESOURCE_RUNTIME_SLOT.key,
        PROMPT_SECTIONS_SLOT.key,
        SKILL_ACTIVATION_SLOT.key,
        TOOL_PACKS_SLOT.key,
        COMMAND_PACKS_SLOT.key,
    }
)

T = TypeVar("T")
TValue = TypeVar("TValue")


def standard_capability_composition_plan(
    *,
    product_id: str,
    allowed_sources: frozenset[RuntimeProfileSource] = frozenset({"product"}),
    slot_allowed_sources: Mapping[str, frozenset[RuntimeProfileSource]] | None = None,
    prompt_separator: str = "\n\n",
    strip_prompt_sections: bool = True,
) -> ProductRuntimePlan:
    """Declare the standard composition mechanisms for one Product."""

    source_overrides = dict(slot_allowed_sources or {})
    unknown_overrides = source_overrides.keys() - {
        slot.key for slot in standard_capability_composition_slots()
    }
    if unknown_overrides:
        raise ValueError(
            "unknown capability-composition source override: "
            + ", ".join(sorted(unknown_overrides))
        )
    slots = tuple(
        replace(
            slot,
            allowed_sources=source_overrides.get(slot.key, allowed_sources),
        )
        for slot in standard_capability_composition_slots()
    )
    return ProductRuntimePlan(
        product_id=product_id,
        slots=slots,
        defaults=(
            RuntimeCapabilitySelection(
                slot=RESOURCE_RUNTIME_SLOT.key,
                implementation=RESOURCE_ACTIVATION_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
            RuntimeCapabilitySelection(
                slot=PROMPT_SECTIONS_SLOT.key,
                implementation=PROMPT_SECTIONS_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
                config={
                    "separator": prompt_separator,
                    "stripSections": strip_prompt_sections,
                },
            ),
            RuntimeCapabilitySelection(
                slot=SKILL_ACTIVATION_SLOT.key,
                implementation=DISABLED_SKILL_ACTIVATION_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
            RuntimeCapabilitySelection(
                slot=TOOL_PACKS_SLOT.key,
                implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
            RuntimeCapabilitySelection(
                slot=COMMAND_PACKS_SLOT.key,
                implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
            RuntimeCapabilitySelection(
                slot=SIDE_QUESTION_PROVIDER_SLOT.key,
                implementation=AGENT_SIDE_QUESTION_IMPLEMENTATION,
                implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            ),
        ),
    )


@dataclass
class CapabilityCompositionRuntime:
    """Live binding for standard resource and capability-composition slots.

    The profile determines the mechanisms. Products pass already-admitted
    resource bundles, prompt sections, and packs to these operations; no
    Product content, extension objects, or handler callables enter this
    runtime.
    """

    binding: RuntimeProfileBinding
    _binder: RuntimeProfileBinder
    _profile: ResolvedRuntimeProfile

    @property
    def profile(self) -> ResolvedRuntimeProfile:
        current_resources = {
            capability.slot.key: capability
            for capability in self.binding.profile.capabilities
        }
        return ResolvedRuntimeProfile(
            product_id=self._profile.product_id,
            capabilities=tuple(
                current_resources.get(capability.slot.key, capability)
                for capability in self._profile.capabilities
            ),
            schema_version=self._profile.schema_version,
        )

    def apply_skill_activation(
        self,
        bundle: ResourceBundle,
        disabled_skills: tuple[str, ...] | list[str],
    ) -> ResourceBundle:
        return self.skill_activation.apply(bundle, disabled_skills)

    def activate_resources(self, bundle: ResourceBundle | None) -> ResourceActivation:
        return self.resource_runtime.activate(bundle)

    def compose_prompt_sections(self) -> PromptSectionComposer:
        return self.prompt_section_composer

    def compose_tool_packs(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]:
        return self.tool_pack_composer.compose(packs)

    def compose_command_packs(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]:
        return self.command_pack_composer.compose(packs)

    @property
    def resource_runtime(self) -> ResourceActivationRuntime:
        return _require_value(
            self.binding.value(RESOURCE_RUNTIME_SLOT.key),
            ResourceActivationRuntime,
            RESOURCE_RUNTIME_SLOT.key,
        )

    @property
    def skill_activation(self) -> SkillActivationRuntime:
        return _require_value(
            self.binding.value(SKILL_ACTIVATION_SLOT.key),
            SkillActivationRuntime,
            SKILL_ACTIVATION_SLOT.key,
        )

    @property
    def prompt_section_composer(self) -> PromptSectionComposer:
        return _require_value(
            self.binding.value(PROMPT_SECTIONS_SLOT.key),
            PromptSectionComposer,
            PROMPT_SECTIONS_SLOT.key,
        )

    @property
    def tool_pack_composer(self) -> CapabilityPackComposer:
        return _require_value(
            self.binding.value(TOOL_PACKS_SLOT.key),
            CapabilityPackComposer,
            TOOL_PACKS_SLOT.key,
        )

    @property
    def command_pack_composer(self) -> CapabilityPackComposer:
        return _require_value(
            self.binding.value(COMMAND_PACKS_SLOT.key),
            CapabilityPackComposer,
            COMMAND_PACKS_SLOT.key,
        )

    def dispose(self) -> None:
        self._binder.dispose_sync(self.binding)


def bind_capability_composition_runtime(
    profile: ResolvedRuntimeProfile,
    *,
    context: object | None = None,
    additional_implementations: Iterable[RuntimeCapabilityImplementation] = (),
) -> CapabilityCompositionRuntime:
    """Synchronously bind standard capability-composition implementations."""

    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            implementation
            for implementation in (
                *standard_capability_composition_implementations(),
                *tuple(additional_implementations),
            )
            if implementation.slot in RESOURCE_CAPABILITY_SLOT_KEYS
        )
    )
    resource_profile = resource_capability_profile(profile)
    return CapabilityCompositionRuntime(
        binding=binder.bind_sync(resource_profile, context=context),
        _binder=binder,
        _profile=profile,
    )


def standard_capability_composition_implementations() -> tuple[
    RuntimeCapabilityImplementation, ...
]:
    """Return the first-party standard composition implementations.

    These mechanisms are intentionally closed over exact configuration shapes.
    Product policy such as resource roots, disabled selectors, and conflict
    resolution remains outside the selected mechanism.
    """

    return (
        RuntimeCapabilityImplementation(
            slot=RESOURCE_RUNTIME_SLOT.key,
            implementation=RESOURCE_ACTIVATION_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_resource_runtime,
        ),
        RuntimeCapabilityImplementation(
            slot=PROMPT_SECTIONS_SLOT.key,
            implementation=PROMPT_SECTIONS_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_prompt_section_composer,
        ),
        RuntimeCapabilityImplementation(
            slot=SKILL_ACTIVATION_SLOT.key,
            implementation=DISABLED_SKILL_ACTIVATION_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_skill_activation_runtime,
        ),
        RuntimeCapabilityImplementation(
            slot=TOOL_PACKS_SLOT.key,
            implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_capability_pack_composer,
        ),
        RuntimeCapabilityImplementation(
            slot=COMMAND_PACKS_SLOT.key,
            implementation=ORDERED_CAPABILITY_PACKS_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_capability_pack_composer,
        ),
        RuntimeCapabilityImplementation(
            slot=SIDE_QUESTION_PROVIDER_SLOT.key,
            implementation=AGENT_SIDE_QUESTION_IMPLEMENTATION,
            implementation_version=CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION,
            create=_create_agent_side_question_provider_factory,
        ),
    )


def resource_capability_profile(
    profile: ResolvedRuntimeProfile,
) -> ResolvedRuntimeProfile:
    """Project the private resource mechanism selections from one full Profile."""

    capabilities = tuple(
        capability
        for capability in profile.capabilities
        if capability.slot.key in RESOURCE_CAPABILITY_SLOT_KEYS
    )
    present = {capability.slot.key for capability in capabilities}
    missing = RESOURCE_CAPABILITY_SLOT_KEYS - present
    if missing:
        raise ValueError(
            "resource capability profile is missing slots: "
            + ", ".join(sorted(missing))
        )
    return ResolvedRuntimeProfile(
        product_id=profile.product_id,
        capabilities=capabilities,
        schema_version=profile.schema_version,
    )


def _create_resource_runtime(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> ResourceActivationRuntime:
    del context
    _require_exact_config(selection, expected=set())
    return ResourceActivationRuntime()


def _create_prompt_section_composer(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> PromptSectionComposer:
    del context
    config = _require_exact_config(
        selection,
        expected={"separator", "stripSections"},
    )
    separator = config["separator"]
    strip_sections = config["stripSections"]
    if not isinstance(separator, str) or type(strip_sections) is not bool:
        raise TypeError(
            "prompt section configuration requires a string separator and bool "
            "stripSections"
        )
    return PromptSectionComposer(separator=separator, strip_sections=strip_sections)


def _create_skill_activation_runtime(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> SkillActivationRuntime:
    del context
    _require_exact_config(selection, expected=set())
    return SkillActivationRuntime()


def _create_capability_pack_composer(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> CapabilityPackComposer:
    del context
    _require_exact_config(selection, expected=set())
    return CapabilityPackComposer()


def _create_agent_side_question_provider_factory(
    selection: RuntimeCapabilitySelection,
    context: object | None,
) -> SideQuestionProviderFactory:
    del context
    _require_exact_config(selection, expected=set())
    return SessionSideQuestionProviderFactory()


def _require_exact_config(
    selection: RuntimeCapabilitySelection,
    *,
    expected: set[str],
) -> Mapping[str, object]:
    config = selection.config
    if set(config) != expected:
        expected_keys = ", ".join(sorted(expected)) or "no keys"
        actual_keys = ", ".join(sorted(config)) or "no keys"
        raise ValueError(
            f"{selection.implementation} configuration must contain "
            f"{expected_keys}; received {actual_keys}"
        )
    return config


def _require_value(
    value: object | tuple[object, ...],
    expected_type: type[TValue],
    slot: str,
) -> TValue:
    if isinstance(value, tuple):
        if len(value) != 1:
            raise TypeError(
                "standard capability runtime requires one selected implementation: "
                f"{slot}"
            )
        value = value[0]
    if not isinstance(value, expected_type):
        raise TypeError(f"selected capability implementation is invalid: {slot}")
    return value


__all__ = [
    "AGENT_SIDE_QUESTION_IMPLEMENTATION",
    "CAPABILITY_COMPOSITION_IMPLEMENTATION_VERSION",
    "CapabilityCompositionRuntime",
    "DISABLED_SKILL_ACTIVATION_IMPLEMENTATION",
    "ORDERED_CAPABILITY_PACKS_IMPLEMENTATION",
    "PROMPT_SECTIONS_IMPLEMENTATION",
    "RESOURCE_CAPABILITY_SLOT_KEYS",
    "RESOURCE_ACTIVATION_IMPLEMENTATION",
    "bind_capability_composition_runtime",
    "resource_capability_profile",
    "standard_capability_composition_plan",
    "standard_capability_composition_implementations",
]
