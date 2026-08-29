"""Standard runtime binding for Product capability composition.

This module binds the Product-selected mechanisms for resource activation,
prompt sections, skill activation, and capability packs.  Product plans own
which mechanisms they select and the values they pass to them; this module
owns only the neutral factories and their configuration contracts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

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


@runtime_checkable
class _PreparedResourceOwnerGeneration(Protocol):
    """Lifecycle-only seam for the candidate-owned Catalog generation.

    The concrete implementation lives below ``resource_catalog``.  Keeping
    this structural seam here prevents the capability-composition layer from
    importing Resource source/engine implementations back into the graph.
    """

    @property
    def ownership_state(self) -> str: ...

    @property
    def provider_binding_fingerprint(self) -> str: ...

    @property
    def catalog_snapshot(self) -> object: ...

    @property
    def catalog_projection(self) -> object: ...

    @property
    def _skill_status_projection(self) -> object: ...

    def load_handle(self, identity: Any) -> Any: ...

    async def load(self, handle: Any) -> Any: ...

    def _borrows_extension_source_lease(self, source: object) -> bool: ...

    def _begin_graph_construction(self) -> None: ...

    def _commit_graph_ownership(self) -> None: ...

    def _restore_root_ownership(self) -> None: ...

    async def dispose_root_owned(self) -> None: ...

    async def _dispose_graph_owned(self) -> None: ...


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
class _CapabilityCompositionCandidate:
    binding: RuntimeProfileBinding
    binder: RuntimeProfileBinder
    profile: ResolvedRuntimeProfile
    ownership: Literal[
        "root_owned",
        "graph_constructing",
        "graph_owned",
        "retiring",
        "disposed",
    ] = "root_owned"
    owner_generation: _PreparedResourceOwnerGeneration | None = None
    retirement_owner: Literal["root", "graph"] | None = None


@dataclass(frozen=True)
class _RootOwnedResourceCapabilityHandles:
    """Private bootstrap-only views into one root-owned candidate."""

    _runtime: StagedResourceCompositionCandidate

    def _require_root(self) -> StagedResourceCompositionCandidate:
        if self._runtime.ownership_state != "root_owned":
            raise RuntimeError("Resource bootstrap handles are no longer root-owned")
        return self._runtime

    @property
    def skill_activation(self) -> SkillActivationRuntime:
        return self._require_root().skill_activation

    def activate_resources(self, bundle: ResourceBundle | None) -> ResourceActivation:
        return self._require_root().activate_resources(bundle)

    @property
    def prompt_section_composer(self) -> PromptSectionComposer:
        return self._require_root().prompt_section_composer

    @property
    def tool_pack_composer(self) -> CapabilityPackComposer:
        return self._require_root().tool_pack_composer

    @property
    def resource_catalog_snapshot(self) -> object:
        runtime = self._require_root()
        return runtime._require_prepared_owner_generation().catalog_snapshot

    @property
    def resource_catalog_projection(self) -> object:
        runtime = self._require_root()
        return runtime._require_prepared_owner_generation().catalog_projection

    @property
    def _resource_skill_status_projection(self) -> object:
        runtime = self._require_root()
        generation = runtime._require_prepared_owner_generation()
        return generation._skill_status_projection

    def dispose(self) -> None:
        self._runtime.dispose()


class StagedResourceCompositionCandidate:
    """Staged resource mechanisms with exactly one transferable owner.

    Synchronous Product bootstrap owns the candidate initially.  The Session
    Capability graph may claim that same candidate exactly once; after the
    claim, this object is only a compatibility view and the graph owns release.
    No Product content, Extension object, or handler callback enters the
    binding.
    """

    def __init__(
        self,
        *,
        binding: RuntimeProfileBinding,
        _binder: RuntimeProfileBinder,
        _profile: ResolvedRuntimeProfile,
    ) -> None:
        self.__candidate = _CapabilityCompositionCandidate(
            binding=binding,
            binder=_binder,
            profile=_profile,
        )

    @property
    def binding(self) -> RuntimeProfileBinding:
        """Compatibility read view; lifecycle ownership stays in the candidate."""

        return self.__candidate.binding

    @property
    def _binder(self) -> RuntimeProfileBinder:
        """Compatibility-only test seam for the private Provider binder."""

        return self.__candidate.binder

    @property
    def profile(self) -> ResolvedRuntimeProfile:
        current_resources = {
            capability.slot.key: capability
            for capability in self.binding.profile.capabilities
        }
        return ResolvedRuntimeProfile(
            product_id=self.__candidate.profile.product_id,
            capabilities=tuple(
                current_resources.get(capability.slot.key, capability)
                for capability in self.__candidate.profile.capabilities
            ),
            schema_version=self.__candidate.profile.schema_version,
        )

    @property
    def ownership_state(self) -> str:
        """Return the redacted handoff state used by lifecycle tests."""

        return self.__candidate.ownership

    @property
    def has_prepared_owner_generation(self) -> bool:
        return self.__candidate.owner_generation is not None

    @property
    def prepared_owner_generation_state(self) -> str | None:
        generation = self.__candidate.owner_generation
        return None if generation is None else generation.ownership_state

    @property
    def resource_owner_generation_binding_fingerprint(self) -> str | None:
        generation = self.__candidate.owner_generation
        if generation is None:
            return None
        return generation.provider_binding_fingerprint

    def _assert_can_attach_prepared_owner_generation(self) -> None:
        if self.__candidate.ownership != "root_owned":
            raise RuntimeError(
                "Only a root-owned Resource candidate can prepare an owner generation"
            )
        if self.__candidate.owner_generation is not None:
            raise RuntimeError(
                "Resource candidate already has a prepared owner generation"
            )

    def _attach_prepared_owner_generation(self, generation: object) -> None:
        """Take exclusive root custody of one unpublished owner generation."""

        self._assert_can_attach_prepared_owner_generation()
        if not isinstance(generation, _PreparedResourceOwnerGeneration):
            raise TypeError("Resource candidate requires a prepared owner generation")
        if generation.ownership_state != "root_owned":
            raise RuntimeError("Prepared owner generation is not root-owned")
        self.__candidate.owner_generation = generation

    def _require_prepared_owner_generation(
        self,
    ) -> _PreparedResourceOwnerGeneration:
        generation = self.__candidate.owner_generation
        if generation is None:
            raise RuntimeError("Resource candidate has no prepared owner generation")
        return generation

    def _borrows_prepared_extension_source_lease(self, source: object) -> bool:
        """Prove exact borrowed-lease identity to the joint construction root."""

        if self.__candidate.ownership != "root_owned":
            raise RuntimeError("Resource candidate is not root-owned")
        generation = self._require_prepared_owner_generation()
        return generation._borrows_extension_source_lease(source)

    @property
    def resource_catalog_snapshot(self) -> object:
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource Catalog generation is not graph-owned")
        return self._require_prepared_owner_generation().catalog_snapshot

    @property
    def resource_catalog_projection(self) -> object:
        if self.__candidate.ownership not in {"root_owned", "graph_owned"}:
            raise RuntimeError("Resource Catalog generation is not retained")
        return self._require_prepared_owner_generation().catalog_projection

    @property
    def _resource_skill_status_projection(self) -> object:
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource Catalog generation is not graph-owned")
        return self._require_prepared_owner_generation()._skill_status_projection

    def resource_load_handle(self, identity: object) -> object:
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource Catalog generation is not graph-owned")
        return self._require_prepared_owner_generation().load_handle(identity)

    async def load_resource(self, handle: object) -> object:
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError("Resource Catalog generation is not graph-owned")
        return await self._require_prepared_owner_generation().load(handle)

    def _root_owned_handles(self) -> _RootOwnedResourceCapabilityHandles:
        """Return the focused private handles used only during bootstrap."""

        if self.__candidate.ownership != "root_owned":
            raise RuntimeError("Resource candidate is not root-owned")
        return _RootOwnedResourceCapabilityHandles(self)

    def select_final_profile(self, profile: ResolvedRuntimeProfile) -> None:
        """Attach final immutable selection facts without rebuilding resources.

        The resource projection must be identical to the already-constructed
        bootstrap candidate.  A changed resource mechanism requires a future
        graph replacement contract and therefore fails closed in this slice.
        """

        if self.__candidate.ownership != "root_owned":
            raise RuntimeError("Only a root-owned resource candidate can be selected")
        expected = self.binding.profile.snapshot().to_json()
        actual = resource_capability_profile(profile).snapshot().to_json()
        if actual != expected:
            raise RuntimeError(
                "Final resource mechanism selections differ from the staged candidate"
            )
        self.__candidate.profile = profile

    def _begin_graph_construction(self) -> None:
        if self.__candidate.ownership != "root_owned":
            raise RuntimeError("Resource candidate is not available for graph claim")
        generation = self.__candidate.owner_generation
        if generation is not None:
            generation._begin_graph_construction()
        self.__candidate.ownership = "graph_constructing"

    def _commit_graph_ownership(self) -> None:
        if self.__candidate.ownership != "graph_constructing":
            raise RuntimeError("Resource candidate graph claim was not started")
        generation = self.__candidate.owner_generation
        if generation is not None:
            generation._commit_graph_ownership()
        self.__candidate.ownership = "graph_owned"

    def _restore_root_ownership(self) -> None:
        if self.__candidate.ownership != "graph_constructing":
            raise RuntimeError("Resource candidate graph claim is not in progress")
        generation = self.__candidate.owner_generation
        if generation is not None:
            generation._restore_root_ownership()
        self.__candidate.ownership = "root_owned"

    def _dispose_graph_owned(self) -> None:
        if self.__candidate.owner_generation is not None:
            raise RuntimeError(
                "Prepared Resource owner generation requires asynchronous disposal"
            )
        if self.__candidate.ownership == "disposed":
            return
        if self.__candidate.ownership != "graph_owned":
            raise RuntimeError(
                "Graph cannot dispose a resource candidate it does not own"
            )
        self.__candidate.binder.dispose_sync(self.binding)
        self.__candidate.ownership = "disposed"

    async def _dispose_graph_owned_async(self) -> None:
        generation = self.__candidate.owner_generation
        if generation is None:
            self._dispose_graph_owned()
            return
        if self.__candidate.ownership == "disposed":
            return
        if self.__candidate.ownership == "graph_owned":
            self.__candidate.ownership = "retiring"
            self.__candidate.retirement_owner = "graph"
        elif not (
            self.__candidate.ownership == "retiring"
            and self.__candidate.retirement_owner == "graph"
        ):
            raise RuntimeError(
                "Graph cannot dispose a Resource candidate it does not own"
            )
        await generation._dispose_graph_owned()
        self.__candidate.binder.dispose_sync(self.binding)
        self.__candidate.ownership = "disposed"
        self.__candidate.retirement_owner = None

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
        """Dispose only while the construction root still owns the candidate."""

        if self.__candidate.ownership == "disposed":
            return
        if self.__candidate.owner_generation is not None:
            raise RuntimeError(
                "Prepared Resource owner generation requires dispose_root_owned()"
            )
        if self.__candidate.ownership == "graph_owned":
            return
        if self.__candidate.ownership == "graph_constructing":
            raise RuntimeError("Resource candidate ownership transfer is in progress")
        self.__candidate.binder.dispose_sync(self.binding)
        self.__candidate.ownership = "disposed"

    async def dispose_root_owned(self) -> None:
        """Retire the complete staged candidate before Graph adoption."""

        generation = self.__candidate.owner_generation
        if generation is None:
            self.dispose()
            return
        if self.__candidate.ownership == "disposed":
            return
        if self.__candidate.ownership == "root_owned":
            self.__candidate.ownership = "retiring"
            self.__candidate.retirement_owner = "root"
        elif not (
            self.__candidate.ownership == "retiring"
            and self.__candidate.retirement_owner == "root"
        ):
            raise RuntimeError(
                "Construction root cannot dispose a Resource candidate it does not own"
            )
        await generation.dispose_root_owned()
        self.__candidate.binder.dispose_sync(self.binding)
        self.__candidate.ownership = "disposed"
        self.__candidate.retirement_owner = None


def stage_resource_composition_candidate(
    profile: ResolvedRuntimeProfile,
    *,
    context: object | None = None,
    additional_implementations: Iterable[RuntimeCapabilityImplementation] = (),
) -> StagedResourceCompositionCandidate:
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
    return StagedResourceCompositionCandidate(
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
    "StagedResourceCompositionCandidate",
    "DISABLED_SKILL_ACTIVATION_IMPLEMENTATION",
    "ORDERED_CAPABILITY_PACKS_IMPLEMENTATION",
    "PROMPT_SECTIONS_IMPLEMENTATION",
    "RESOURCE_CAPABILITY_SLOT_KEYS",
    "RESOURCE_ACTIVATION_IMPLEMENTATION",
    "stage_resource_composition_candidate",
    "resource_capability_profile",
    "standard_capability_composition_plan",
    "standard_capability_composition_implementations",
]
