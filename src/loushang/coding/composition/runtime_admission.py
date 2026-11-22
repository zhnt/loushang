"""Coding-owned admission adapter for externally variable runtime capabilities."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from loushang.coding.composition.plan import CODING_CAPABILITY_PLAN
from loushang.harness.capabilities import (
    StagedResourceCompositionCandidate,
    stage_resource_composition_candidate,
)
from loushang.harness.extensions.agent import ExtensionRunner
from loushang.harness.extensions.declarations import (
    ExtensionCapabilityDeclarationSnapshot,
)
from loushang.harness.extensions.types import LoadedExtension
from loushang.harness.runtime import (
    SIDE_QUESTION_PROVIDER_SLOT,
    ResolvedRuntimeProfile,
    RuntimeCapabilityImplementation,
)
from loushang.harness.session.extension_profiles import (
    prepare_extension_profile,
    require_compatible_declaration_change,
    require_supported_resource_baseline,
)
from loushang.harness.session.legacy_side_question import (
    LegacySideQuestionBinding,
    bind_legacy_side_question,
)

SIDE_QUESTION_RUNTIME_PERMISSION = SIDE_QUESTION_PROVIDER_SLOT.key
_EXTENSION_SLOT_PERMISSIONS = {
    SIDE_QUESTION_PROVIDER_SLOT.key: frozenset({SIDE_QUESTION_RUNTIME_PERMISSION}),
}


@dataclass(frozen=True)
class CodingCapabilityProfileResolution:
    """Pure resolved profile plus the Product-approved executable factories."""

    profile: ResolvedRuntimeProfile
    implementations: tuple[RuntimeCapabilityImplementation, ...]

    def bind(self) -> StagedResourceCompositionCandidate:
        return stage_resource_composition_candidate(
            self.profile,
            additional_implementations=self.implementations,
        )

    def bind_side_question(self) -> LegacySideQuestionBinding:
        return bind_legacy_side_question(
            self.profile,
            additional_implementations=self.implementations,
        )


def resolve_coding_capability_profile(
    extensions: Iterable[LoadedExtension],
) -> CodingCapabilityProfileResolution:
    """Admit active Coding Extension replacements and resolve one final profile."""

    profile, implementations = prepare_extension_profile(
        extensions,
        CODING_CAPABILITY_PLAN,
        _EXTENSION_SLOT_PERMISSIONS,
        factory_error="Extension side-question replacement must create a Provider factory",
    )
    return CodingCapabilityProfileResolution(
        profile=profile, implementations=implementations
    )


@dataclass(frozen=True)
class CodingExtensionDeclarationPreflight:
    """Re-run Coding's pure admission before a live Extension generation swap."""

    baseline_profile: ResolvedRuntimeProfile

    def __post_init__(self) -> None:
        require_supported_resource_baseline(
            self.baseline_profile, product_label="Coding"
        )

    def __call__(self, candidate: ExtensionCapabilityDeclarationSnapshot) -> None:
        require_compatible_declaration_change(
            self.baseline_profile,
            candidate,
            CODING_CAPABILITY_PLAN,
            _EXTENSION_SLOT_PERMISSIONS,
        )


def bind_coding_side_question(
    extension_runtime: ExtensionRunner,
) -> LegacySideQuestionBinding:
    """Bind the final Extension-selected side-question factory for one Session."""

    return resolve_coding_capability_profile(
        extension_runtime.active_extensions
    ).bind_side_question()


__all__ = [
    "CodingExtensionDeclarationPreflight",
    "CodingCapabilityProfileResolution",
    "SIDE_QUESTION_RUNTIME_PERMISSION",
    "bind_coding_side_question",
    "resolve_coding_capability_profile",
]
