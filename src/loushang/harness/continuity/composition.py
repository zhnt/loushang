"""Compose admitted continuity provider packs into one immutable Experience."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from loushang.harness.capabilities.component_contracts import (
    _digest_document,
    _require_nonempty,
    _require_sha256,
)
from loushang.harness.continuity.import_provider import (
    MAX_CONTINUITY_IMPORT_PROVIDERS,
)
from loushang.harness.continuity.provider import ContinuityProvider
from loushang.harness.continuity.types import (
    CONTINUITY_PROVIDER_PROFILE_VERSION,
    ContinuityProviderSourceDescriptor,
    ExperienceDescriptor,
)
from loushang.harness.runtime.profile import (
    CONTINUITY_PROVIDER_PACKS_SLOT,
    ResolvedRuntimeProfile,
    ResolvedRuntimeSelection,
    RuntimeProfileBinding,
)


@dataclass(frozen=True)
class ContinuityProviderPack:
    """One bound capability value containing one or more related Providers."""

    providers: tuple[ContinuityProvider, ...]

    def __post_init__(self) -> None:
        providers = tuple(self.providers)
        if not providers:
            raise ValueError("continuity provider packs must not be empty")
        object.__setattr__(self, "providers", providers)


@dataclass(frozen=True, slots=True, init=False)
class PluginContinuityProviderProvenance:
    """Redacted exact-chain provenance for one owner-generation Provider."""

    component_id: str
    plugin_id: str
    contribution_id: str
    instance_id: str
    instance_revision: int
    source_trust_class: str
    source_trust_policy_revision: str
    supported_actions: tuple[str, ...]
    candidate_fingerprint: str
    admission_fingerprint: str
    selection_plan_fingerprint: str
    binding_fingerprint: str
    recovery_fingerprint: str
    generation_fingerprint: str

    def __init__(self) -> None:
        raise TypeError("Plugin Continuity provenance is owner-constructed")

    def __post_init__(self) -> None:
        for name, value in (
            ("component id", self.component_id),
            ("Plugin id", self.plugin_id),
            ("contribution id", self.contribution_id),
            ("Plugin instance id", self.instance_id),
            ("Plugin trust class", self.source_trust_class),
            ("Plugin trust policy revision", self.source_trust_policy_revision),
        ):
            _require_nonempty(value, name=name)
        if (
            isinstance(self.instance_revision, bool)
            or not isinstance(self.instance_revision, int)
            or self.instance_revision < 1
        ):
            raise ValueError("Plugin instance revision must be positive")
        for name, value in (
            ("Plugin candidate fingerprint", self.candidate_fingerprint),
            ("component admission fingerprint", self.admission_fingerprint),
            ("component selection fingerprint", self.selection_plan_fingerprint),
            ("component binding fingerprint", self.binding_fingerprint),
            ("owner recovery fingerprint", self.recovery_fingerprint),
            ("owner generation fingerprint", self.generation_fingerprint),
        ):
            _require_sha256(value, name=name)
        if self.supported_actions not in {
            ("activate",),
            ("activate", "delete"),
        }:
            raise ValueError("Plugin Continuity admitted actions are invalid")


ContinuityProviderProvenance: TypeAlias = (
    ResolvedRuntimeSelection | PluginContinuityProviderProvenance
)


@dataclass(frozen=True)
class BoundContinuityProvider:
    provider: ContinuityProvider
    provenance: ContinuityProviderProvenance

    @property
    def source(self) -> ContinuityProviderSourceDescriptor:
        return continuity_provider_source(self)


@dataclass(frozen=True, init=False)
class _GatedPluginBoundContinuityProvider(BoundContinuityProvider):
    def __init__(self) -> None:
        raise TypeError("Plugin Continuity bindings are owner-constructed")


@dataclass(frozen=True)
class ExperienceComposition:
    experience: ExperienceDescriptor
    capability_profile: ResolvedRuntimeProfile
    continuity_providers: tuple[BoundContinuityProvider, ...]


class ContinuityCompositionError(ValueError):
    """Raised when bound provider packs conflict with the Experience contract."""


def compose_experience_continuity(
    *,
    experience: ExperienceDescriptor,
    binding: RuntimeProfileBinding,
) -> ExperienceComposition:
    """Consume process-bound packs without resolving or binding factories again."""

    try:
        capability = binding.profile.capability(CONTINUITY_PROVIDER_PACKS_SLOT.key)
    except KeyError:
        return ExperienceComposition(
            experience=experience,
            capability_profile=binding.profile,
            continuity_providers=(),
        )

    raw_values = binding.value(CONTINUITY_PROVIDER_PACKS_SLOT.key)
    values = raw_values if isinstance(raw_values, tuple) else (raw_values,)
    if len(values) != len(capability.selections):
        raise ContinuityCompositionError(
            "bound provider packs do not match resolved selection provenance"
        )

    composed: list[BoundContinuityProvider] = []
    provider_ids: set[str] = set()
    for value, provenance in zip(values, capability.selections, strict=True):
        if not isinstance(value, ContinuityProviderPack):
            raise ContinuityCompositionError(
                "continuity.provider_packs factories must return "
                "ContinuityProviderPack values"
            )
        for provider in value.providers:
            descriptor = provider.descriptor
            if (
                descriptor.implementation_version
                != provenance.selection.implementation_version
            ):
                raise ContinuityCompositionError(
                    f"provider {descriptor.provider_id!r} implementation version "
                    f"{descriptor.implementation_version} does not match bound "
                    f"selection version "
                    f"{provenance.selection.implementation_version}"
                )
            bound = BoundContinuityProvider(
                provider=provider,
                provenance=provenance,
            )
            _validate_bound_provider(
                experience,
                bound,
                provider_ids=provider_ids,
            )
            composed.append(bound)
    _validate_aggregate_limit(composed)
    return ExperienceComposition(
        experience=experience,
        capability_profile=binding.profile,
        continuity_providers=tuple(composed),
    )


def _compose_experience_continuity_with_plugins(
    base: ExperienceComposition,
    plugin_providers: tuple[BoundContinuityProvider, ...],
) -> ExperienceComposition:
    """Produce the sole final composition from sealed Product and Plugin inputs."""

    if not isinstance(base, ExperienceComposition):
        raise TypeError("final Continuity composition requires its Product base")
    providers = list(base.continuity_providers)
    provider_ids = {
        item.provider.descriptor.provider_id for item in base.continuity_providers
    }
    for bound in plugin_providers:
        if not isinstance(bound, _GatedPluginBoundContinuityProvider) or not isinstance(
            bound.provenance,
            PluginContinuityProviderProvenance,
        ):
            raise TypeError(
                "final Continuity Plugin input requires owner-derived provenance"
            )
        _validate_bound_provider(
            base.experience,
            bound,
            provider_ids=provider_ids,
        )
        providers.append(bound)
    _validate_aggregate_limit(providers)
    return ExperienceComposition(
        experience=base.experience,
        capability_profile=base.capability_profile,
        continuity_providers=tuple(providers),
    )


def _bind_gated_plugin_continuity_provider(
    provider: ContinuityProvider,
    provenance: PluginContinuityProviderProvenance,
) -> _GatedPluginBoundContinuityProvider:
    if not isinstance(provenance, PluginContinuityProviderProvenance):
        raise TypeError("Plugin Continuity binding requires owner provenance")
    bound = object.__new__(_GatedPluginBoundContinuityProvider)
    object.__setattr__(bound, "provider", provider)
    object.__setattr__(bound, "provenance", provenance)
    return bound


def _create_plugin_continuity_provider_provenance(
    *,
    component_id: str,
    plugin_id: str,
    contribution_id: str,
    instance_id: str,
    instance_revision: int,
    source_trust_class: str,
    source_trust_policy_revision: str,
    supported_actions: tuple[str, ...],
    candidate_fingerprint: str,
    admission_fingerprint: str,
    selection_plan_fingerprint: str,
    binding_fingerprint: str,
    recovery_fingerprint: str,
    generation_fingerprint: str,
) -> PluginContinuityProviderProvenance:
    provenance = object.__new__(PluginContinuityProviderProvenance)
    for name, value in locals().items():
        if name != "provenance":
            object.__setattr__(provenance, name, value)
    provenance.__post_init__()
    return provenance


def continuity_provider_source(
    bound: BoundContinuityProvider,
) -> ContinuityProviderSourceDescriptor:
    """Project admitted Runtime Profile provenance without live factories."""

    if not isinstance(bound, BoundContinuityProvider):
        raise TypeError("continuity Provider source requires a bound Provider")
    provider_id = bound.provider.descriptor.provider_id
    provenance = bound.provenance
    if isinstance(provenance, PluginContinuityProviderProvenance):
        return plugin_continuity_provider_source(
            provider_id=provider_id,
            implementation_version=(bound.provider.descriptor.implementation_version),
            provenance=provenance,
        )
    selection = provenance.selection
    return ContinuityProviderSourceDescriptor(
        provider_id=provider_id,
        source=provenance.source,
        source_id=provenance.layer_id,
        implementation=selection.implementation,
        implementation_version=selection.implementation_version,
    )


def plugin_continuity_provider_source(
    *,
    provider_id: str,
    implementation_version: int,
    provenance: PluginContinuityProviderProvenance,
) -> ContinuityProviderSourceDescriptor:
    """Project owner-derived Plugin provenance before wrapper publication."""

    if not isinstance(provenance, PluginContinuityProviderProvenance):
        raise TypeError("Plugin Continuity source requires typed provenance")
    return ContinuityProviderSourceDescriptor(
        provider_id=provider_id,
        source="plugin",
        source_id=provenance.generation_fingerprint,
        implementation=provenance.component_id,
        implementation_version=implementation_version,
        plugin_id=provenance.plugin_id,
        contribution_id=provenance.contribution_id,
        instance_id=provenance.instance_id,
        instance_revision=provenance.instance_revision,
        source_trust_class=provenance.source_trust_class,
        source_trust_policy_revision=provenance.source_trust_policy_revision,
        owner_binding_fingerprint=_digest_document(
            "loushang.plugin-continuity-owner-binding/v1",
            {
                "admissionFingerprint": provenance.admission_fingerprint,
                "bindingFingerprint": provenance.binding_fingerprint,
                "candidateFingerprint": provenance.candidate_fingerprint,
                "selectionPlanFingerprint": provenance.selection_plan_fingerprint,
                "supportedActions": list(provenance.supported_actions),
            },
        ),
        owner_recovery_fingerprint=provenance.recovery_fingerprint,
    )


def _validate_bound_provider(
    experience: ExperienceDescriptor,
    bound: BoundContinuityProvider,
    *,
    provider_ids: set[str],
) -> None:
    descriptor = bound.provider.descriptor
    if descriptor.profile_version != CONTINUITY_PROVIDER_PROFILE_VERSION:
        raise ContinuityCompositionError(
            f"provider {descriptor.provider_id!r} requires unsupported "
            f"continuity profile version {descriptor.profile_version}"
        )
    if descriptor.experience_id != experience.experience_id:
        raise ContinuityCompositionError(
            f"provider {descriptor.provider_id!r} declares Experience "
            f"{descriptor.experience_id!r}, expected {experience.experience_id!r}"
        )
    unknown_domains = set(descriptor.domain_ids) - set(experience.domain_ids)
    if unknown_domains:
        raise ContinuityCompositionError(
            f"provider {descriptor.provider_id!r} declares Domains outside "
            f"the Experience: {', '.join(sorted(unknown_domains))}"
        )
    if descriptor.provider_id in provider_ids:
        raise ContinuityCompositionError(
            f"duplicate continuity provider ID: {descriptor.provider_id}"
        )
    provider_ids.add(descriptor.provider_id)
    # Validate finite, redacted source identity before publication.
    continuity_provider_source(bound)


def _validate_aggregate_limit(
    providers: list[BoundContinuityProvider],
) -> None:
    if len(providers) > MAX_CONTINUITY_IMPORT_PROVIDERS:
        raise ContinuityCompositionError(
            "final Continuity Provider composition exceeds its aggregate limit"
        )


__all__ = [
    "BoundContinuityProvider",
    "ContinuityCompositionError",
    "ContinuityProviderPack",
    "ExperienceComposition",
    "compose_experience_continuity",
    "continuity_provider_source",
]
