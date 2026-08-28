"""Compose admitted continuity provider packs into one immutable Experience."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class BoundContinuityProvider:
    provider: ContinuityProvider
    provenance: ResolvedRuntimeSelection

    @property
    def source(self) -> ContinuityProviderSourceDescriptor:
        return continuity_provider_source(self)


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
    experience_domains = set(experience.domain_ids)
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
            if descriptor.profile_version != CONTINUITY_PROVIDER_PROFILE_VERSION:
                raise ContinuityCompositionError(
                    f"provider {descriptor.provider_id!r} requires unsupported "
                    f"continuity profile version {descriptor.profile_version}"
                )
            if descriptor.experience_id != experience.experience_id:
                raise ContinuityCompositionError(
                    f"provider {descriptor.provider_id!r} declares Experience "
                    f"{descriptor.experience_id!r}, expected "
                    f"{experience.experience_id!r}"
                )
            unknown_domains = set(descriptor.domain_ids) - experience_domains
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
            bound = BoundContinuityProvider(
                provider=provider,
                provenance=provenance,
            )
            # Validate finite, redacted source identity before publication.
            continuity_provider_source(bound)
            composed.append(bound)
    return ExperienceComposition(
        experience=experience,
        capability_profile=binding.profile,
        continuity_providers=tuple(composed),
    )


def continuity_provider_source(
    bound: BoundContinuityProvider,
) -> ContinuityProviderSourceDescriptor:
    """Project Runtime Profile provenance without exposing live factories."""

    if not isinstance(bound, BoundContinuityProvider):
        raise TypeError("continuity Provider source requires a bound Provider")
    provenance = bound.provenance
    selection = provenance.selection
    provider_id = bound.provider.descriptor.provider_id
    config = selection.config
    if provenance.source == "extension" and config.get(
        "continuityPluginSchemaVersion"
    ) == 1:
        try:
            plugin_id = _plugin_text(config, "pluginId")
            contribution_id = _plugin_text(config, "contributionId")
            instance_id = _plugin_text(config, "instanceId")
            instance_revision = _plugin_positive_int(config, "instanceRevision")
            source_trust_class = _plugin_text(config, "sourceTrustClass")
            source_trust_policy_revision = _plugin_text(
                config,
                "sourceTrustPolicyRevision",
            )
        except (TypeError, ValueError) as exc:
            raise ContinuityCompositionError(
                "Plugin continuity Provider provenance is invalid"
            ) from exc
        return ContinuityProviderSourceDescriptor(
            provider_id=provider_id,
            source="plugin",
            source_id=provenance.layer_id,
            implementation=selection.implementation,
            implementation_version=selection.implementation_version,
            plugin_id=plugin_id,
            contribution_id=contribution_id,
            instance_id=instance_id,
            instance_revision=instance_revision,
            source_trust_class=source_trust_class,
            source_trust_policy_revision=source_trust_policy_revision,
        )
    return ContinuityProviderSourceDescriptor(
        provider_id=provider_id,
        source=provenance.source,
        source_id=provenance.layer_id,
        implementation=selection.implementation,
        implementation_version=selection.implementation_version,
    )


def _plugin_text(config: object, key: str) -> str:
    if not isinstance(config, dict) and not hasattr(config, "get"):
        raise TypeError("Plugin continuity provenance must be a mapping")
    value = config.get(key)  # type: ignore[union-attr]
    if not isinstance(value, str) or not value:
        raise ValueError(f"Plugin continuity provenance {key} is invalid")
    return value


def _plugin_positive_int(config: object, key: str) -> int:
    if not isinstance(config, dict) and not hasattr(config, "get"):
        raise TypeError("Plugin continuity provenance must be a mapping")
    value = config.get(key)  # type: ignore[union-attr]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"Plugin continuity provenance {key} is invalid")
    return value


__all__ = [
    "BoundContinuityProvider",
    "ContinuityCompositionError",
    "ContinuityProviderPack",
    "ExperienceComposition",
    "compose_experience_continuity",
    "continuity_provider_source",
]
