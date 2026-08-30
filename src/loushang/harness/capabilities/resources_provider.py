"""Source-complete Provider for the ``harness.resources`` Capability Bundle."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

from loushang.foundation.json import dump_json_value
from loushang.harness.capabilities.composition_runtime import (
    RESOURCE_CAPABILITY_SLOT_KEYS,
    ResourceCatalogGenerationCapture,
    StagedResourceCompositionCandidate,
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
    RESOURCE_CATALOG_FACET,
    RESOURCE_LOAD_FACET,
    RESOURCE_RUNTIME_FACET,
    RESOURCES_CAPABILITY_DEFINITION,
    RESOURCES_CAPABILITY_DEFINITION_V2,
    RESOURCES_CAPABILITY_DEFINITION_V3,
    RESOURCES_CAPABILITY_DEFINITION_V4,
    SKILL_ACTIVATION_FACET,
    TOOL_PACKS_FACET,
)
from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._catalog_records import ResourceCatalogSnapshot
from loushang.harness.resources._resource_owner_grants import (
    _mint_resource_catalog_owner_grant,
)
from loushang.harness.resources._skill_catalog_consumer import (
    EffectiveSkillCatalogProjection,
    build_effective_skill_catalog_projection,
)
from loushang.harness.resources._skill_catalog_status import (
    SkillCatalogStatusProjection,
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


@dataclass
class _StagedResources:
    candidate: StagedResourceCompositionCandidate = field(repr=False)

    def value(self, slot: str) -> object:
        value = self.candidate.binding.value(slot)
        if isinstance(value, tuple):
            if len(value) != 1:
                raise TypeError(f"resource facet requires one selected value: {slot}")
            return value[0]
        return value

    async def dispose(self) -> None:
        await self.candidate._dispose_graph_owned_async()


@dataclass(frozen=True)
class _ResourceRuntimeFacet:
    _owner: _BoundResources | _StagedResources = field(repr=False, compare=False)

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
    _owner: _BoundResources | _StagedResources = field(repr=False, compare=False)

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
    _owner: _BoundResources | _StagedResources = field(repr=False, compare=False)

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
    _owner: _BoundResources | _StagedResources = field(repr=False, compare=False)
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


@dataclass(frozen=True)
class _ResourceCatalogFacetV2:
    _owner: _StagedResources = field(repr=False, compare=False)

    def capture(self) -> _CapturedResourceCatalogView:
        return _capture_resource_catalog(self._owner, include_skills=False)


@dataclass(frozen=True)
class _ResourceCatalogFacetV3:
    _owner: _StagedResources = field(repr=False, compare=False)

    def capture(self) -> _CapturedResourceCatalogView:
        return _capture_resource_catalog(self._owner, include_skills=True)


@dataclass(frozen=True)
class _ResourceCatalogFacetV4:
    _owner: _StagedResources = field(repr=False, compare=False)

    def capture(self) -> _CapturedResourceCatalogView:
        return _capture_resource_catalog(
            self._owner,
            include_skills=True,
            include_status=True,
        )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _CapturedResourceCatalogView:
    _generation: ResourceCatalogGenerationCapture = field(repr=False, compare=False)
    snapshot: ResourceCatalogSnapshot
    skill_projection: EffectiveSkillCatalogProjection | None = None
    skill_status_projection: SkillCatalogStatusProjection | None = None
    _skill_action_owner_grant: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def _skill_action_owner_catalog(self) -> object:
        return self

    def load_handle(self, identity: object) -> object:
        return self._generation.load_handle(identity)

    async def load(self, handle: object) -> object:
        return await self._generation.load(handle)


def _capture_resource_catalog(
    owner: _StagedResources,
    *,
    include_skills: bool,
    include_status: bool = False,
) -> _CapturedResourceCatalogView:
    generation = owner.candidate.capture_resource_catalog_generation()
    snapshot = generation.snapshot
    projection = generation.projection
    status = generation.skill_status_projection
    if not isinstance(snapshot, ResourceCatalogSnapshot):
        raise TypeError("Resource Catalog generation snapshot is invalid")
    if include_skills:
        if not isinstance(projection, ResourceCatalogProjection):
            raise TypeError("Resource Catalog generation projection is invalid")
        skill_projection = build_effective_skill_catalog_projection(
            snapshot=snapshot,
            projection=projection,
        )
    else:
        skill_projection = None
    skill_status = None
    if include_status:
        if not isinstance(status, SkillCatalogStatusProjection):
            raise TypeError("Resource Catalog Skill status projection is invalid")
        if (
            status.catalog_generation != snapshot.catalog_generation
            or status.catalog_snapshot_fingerprint != snapshot.snapshot_fingerprint
        ):
            raise RuntimeError("Skill status projection belongs to another Catalog")
        skill_status = status
    captured = _CapturedResourceCatalogView(
        _generation=generation,
        snapshot=snapshot,
        skill_projection=skill_projection,
        skill_status_projection=skill_status,
    )
    if skill_projection is not None and skill_projection.managed_action_sources:
        object.__setattr__(
            captured,
            "_skill_action_owner_grant",
            _mint_resource_catalog_owner_grant(
                captured,
                snapshot=snapshot,
                skill_projection=skill_projection,
            ),
        )
    return captured


@dataclass(frozen=True)
class _ResourceLoadFacet:
    _owner: _StagedResources = field(repr=False, compare=False)

    def load_handle(self, identity: object) -> object:
        return self._owner.candidate.resource_load_handle(identity)

    async def load(self, handle: object) -> object:
        return await self._owner.candidate.load_resource(handle)


def resources_capability_provider_binding(
    *,
    profile: ResolvedRuntimeProfile,
    scope_instance_id: str,
    additional_implementations: Iterable[RuntimeCapabilityImplementation] = (),
    provider_id: str = "harness.resources.standard",
    source_id: str = "builtin",
    staged_candidate: StagedResourceCompositionCandidate | None = None,
    enable_skill_catalog_v3: bool = False,
    enable_skill_catalog_v4: bool = False,
) -> CapabilityBundleProviderBinding:
    """Map private Profile selections into one graph-owned Bundle Provider.

    The returned binding is production-mounted as the declared dependency of
    ``harness.session``. Resource bundles, prompt text, disabled-skill
    selectors, Extension content, and live registrations are call data and
    deliberately do not enter the construction fingerprint.
    """

    if not isinstance(enable_skill_catalog_v3, bool):
        raise TypeError("Skill Catalog v3 opt-in must be a bool")
    if not isinstance(enable_skill_catalog_v4, bool):
        raise TypeError("Skill Catalog v4 opt-in must be a bool")
    if enable_skill_catalog_v3 and enable_skill_catalog_v4:
        raise ValueError("Skill Catalog contract opt-ins are mutually exclusive")
    focused_profile = resource_capability_profile(profile)
    if staged_candidate is not None:
        staged_profile = resource_capability_profile(staged_candidate.profile)
        if staged_profile.snapshot().to_json() != focused_profile.snapshot().to_json():
            raise ValueError(
                "staged resource candidate does not match the declared Profile"
            )
    prepared_generation_fingerprint = (
        None
        if staged_candidate is None
        else staged_candidate.resource_owner_generation_binding_fingerprint
    )
    has_prepared_generation = prepared_generation_fingerprint is not None
    if (enable_skill_catalog_v3 or enable_skill_catalog_v4) and not (
        has_prepared_generation
    ):
        version = 4 if enable_skill_catalog_v4 else 3
        raise ValueError(
            f"Skill Catalog v{version} requires a prepared owner generation"
        )
    definition = (
        RESOURCES_CAPABILITY_DEFINITION_V4
        if enable_skill_catalog_v4
        else RESOURCES_CAPABILITY_DEFINITION_V3
        if enable_skill_catalog_v3
        else RESOURCES_CAPABILITY_DEFINITION_V2
        if has_prepared_generation
        else RESOURCES_CAPABILITY_DEFINITION
    )
    provider_version = definition.contract_version
    implementations = tuple(
        implementation
        for implementation in (
            *standard_capability_composition_implementations(),
            *tuple(additional_implementations),
        )
        if implementation.slot in RESOURCE_CAPABILITY_SLOT_KEYS
    )
    provider = CapabilityBundleProvider(
        capability_id=(
            RESOURCES_CAPABILITY_DEFINITION_V4.capability_id
            if enable_skill_catalog_v4
            else RESOURCES_CAPABILITY_DEFINITION_V3.capability_id
            if enable_skill_catalog_v3
            else RESOURCES_CAPABILITY_DEFINITION_V2.capability_id
            if has_prepared_generation
            else RESOURCES_CAPABILITY_DEFINITION.capability_id
        ),
        provider_id=provider_id,
        implementation_version=provider_version,
        compatible_contract=CapabilityContractRange.exact(
            RESOURCES_CAPABILITY_DEFINITION_V4.contract_version
            if enable_skill_catalog_v4
            else RESOURCES_CAPABILITY_DEFINITION_V3.contract_version
            if enable_skill_catalog_v3
            else RESOURCES_CAPABILITY_DEFINITION_V2.contract_version
            if has_prepared_generation
            else RESOURCES_CAPABILITY_DEFINITION.contract_version
        ),
        facets=(
            RESOURCES_CAPABILITY_DEFINITION_V4.facets
            if enable_skill_catalog_v4
            else RESOURCES_CAPABILITY_DEFINITION_V3.facets
            if enable_skill_catalog_v3
            else RESOURCES_CAPABILITY_DEFINITION_V2.facets
            if has_prepared_generation
            else RESOURCES_CAPABILITY_DEFINITION.facets
        ),
        source_id=source_id,
        selection_rule="Product resource mechanism selections",
    )

    def create(_context: CapabilityProviderContext) -> CapabilityBundleValue:
        owner: _BoundResources | _StagedResources
        skill_projection: EffectiveSkillCatalogProjection | None = None
        skill_status_projection: SkillCatalogStatusProjection | None = None
        if staged_candidate is None:
            binder = RuntimeProfileBinder(RuntimeCapabilityRegistry(implementations))
            binding = binder.bind_sync(focused_profile)
            owner = _BoundResources(binding=binding, binder=binder)
        else:
            if (
                staged_candidate.resource_owner_generation_binding_fingerprint
                != prepared_generation_fingerprint
            ):
                raise RuntimeError(
                    "Staged Resource owner generation changed after Provider binding"
                )
            if enable_skill_catalog_v3 or enable_skill_catalog_v4:
                bootstrap_handles = staged_candidate._root_owned_handles()
                catalog_snapshot = bootstrap_handles.resource_catalog_snapshot
                catalog_projection = bootstrap_handles.resource_catalog_projection
                if not isinstance(catalog_snapshot, ResourceCatalogSnapshot):
                    raise TypeError("Skill Catalog snapshot is invalid")
                if not isinstance(catalog_projection, ResourceCatalogProjection):
                    raise TypeError(
                        "Skill Catalog compatibility projection is unavailable"
                    )
                skill_projection = build_effective_skill_catalog_projection(
                    snapshot=catalog_snapshot,
                    projection=catalog_projection,
                )
                if enable_skill_catalog_v4:
                    status_value = bootstrap_handles._resource_skill_status_projection
                    if not isinstance(status_value, SkillCatalogStatusProjection):
                        raise TypeError(
                            "Skill Catalog v4 status projection is unavailable"
                        )
                    if (
                        status_value.catalog_generation
                        != catalog_snapshot.catalog_generation
                        or status_value.catalog_snapshot_fingerprint
                        != catalog_snapshot.snapshot_fingerprint
                    ):
                        raise RuntimeError(
                            "Skill Catalog v4 status projection belongs to another "
                            "Catalog generation"
                        )
                    skill_status_projection = status_value
            staged_candidate._begin_graph_construction()
            owner = _StagedResources(staged_candidate)
        try:
            facets = [
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
            ]
            if has_prepared_generation:
                if not isinstance(owner, _StagedResources):
                    raise RuntimeError(
                        "Resource Catalog v2 requires a staged owner generation"
                    )
                if enable_skill_catalog_v4:
                    if (
                        skill_projection is None
                        or skill_status_projection is None
                    ):
                        raise RuntimeError(
                            "Skill Catalog v4 projections are unavailable"
                        )
                    catalog_facet: object = _ResourceCatalogFacetV4(owner)
                elif enable_skill_catalog_v3:
                    if skill_projection is None:
                        raise RuntimeError(
                            "Skill Catalog v3 projection is unavailable"
                        )
                    catalog_facet = _ResourceCatalogFacetV3(owner)
                else:
                    catalog_facet = _ResourceCatalogFacetV2(owner)
                facets.extend(
                    (
                        CapabilityFacetBinding(
                            RESOURCE_CATALOG_FACET,
                            catalog_facet,
                        ),
                        CapabilityFacetBinding(
                            RESOURCE_LOAD_FACET,
                            _ResourceLoadFacet(owner),
                        ),
                    )
                )
            value = CapabilityBundleValue(facets=tuple(facets))
            if staged_candidate is not None:
                staged_candidate._commit_graph_ownership()
        except BaseException:
            if staged_candidate is None:
                owner.dispose()
            elif staged_candidate.ownership_state == "graph_constructing":
                staged_candidate._restore_root_ownership()
            raise
        return value

    async def dispose(value: CapabilityBundleValue) -> None:
        resource_facet = value.require(RESOURCE_RUNTIME_FACET)
        if not isinstance(resource_facet, _ResourceRuntimeFacet):
            raise TypeError("resources Provider received an alien Bundle value")
        owner = resource_facet._owner
        if isinstance(owner, _StagedResources):
            await owner.dispose()
        else:
            owner.dispose()

    return CapabilityBundleProviderBinding(
        provider=provider,
        scope_instance_id=scope_instance_id,
        binding_input_fingerprint=_binding_input_fingerprint(
            profile=focused_profile,
            scope_instance_id=scope_instance_id,
            provider_id=provider_id,
            contract_version=definition.contract_version,
            provider_version=provider_version,
        ),
        create=create,
        dispose=dispose,
    )


def _binding_input_fingerprint(
    *,
    profile: ResolvedRuntimeProfile,
    scope_instance_id: str,
    provider_id: str,
    contract_version: int,
    provider_version: int,
) -> str:
    if contract_version == 1:
        payload_value: dict[str, object] = {
            "schemaVersion": 1,
            "capabilityId": RESOURCES_CAPABILITY_DEFINITION.capability_id,
            "contractVersion": 1,
            "providerId": provider_id,
            "providerVersion": 1,
            "scopeInstanceId": scope_instance_id,
            "profile": profile.snapshot().to_json(),
        }
    else:
        payload_value = {
            "schemaVersion": 2,
            "capabilityId": RESOURCES_CAPABILITY_DEFINITION_V2.capability_id,
            "contractVersion": contract_version,
            "providerId": provider_id,
            "providerVersion": provider_version,
            "scopeInstanceId": scope_instance_id,
            "profile": profile.snapshot().to_json(),
        }
    payload = dump_json_value(
        payload_value,
        name="resources binding-input fingerprint",
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = ["resources_capability_provider_binding"]
