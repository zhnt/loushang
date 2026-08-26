"""One-way legacy ``ResourceSnapshot`` adaptation for the inert RCP1 Catalog.

The adapter never discovers files, opens bodies, or invents provenance.  Its
caller must supply the exact source generation and content-origin evidence for
each legacy descriptor.  No production loader imports this module in RCP1.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, cast

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._catalog_records import (
    NO_BODY_MEDIA_TYPE,
    ExtensionOutputOrigin,
    ResourceCandidateSummary,
    ResourceCatalogDiagnostic,
    ResourceCatalogSnapshot,
    ResourceContentOrigin,
    ResourceIdentity,
    ResourceInvocationPolicy,
    ResourceSourceGenerationRef,
    ResourceSourceSnapshot,
    build_candidate_summary,
    build_source_snapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceBundle,
    ResourceSnapshot,
    ResourceSourceKind,
    SkillDescriptor,
    ThemeDescriptor,
)

LegacyDescriptor: TypeAlias = (
    PromptFragmentDescriptor | SkillDescriptor | ExtensionDescriptor | ThemeDescriptor
)
LegacyProvenanceResolver: TypeAlias = Callable[
    [LegacyDescriptor], "LegacyCandidateProvenance"
]


class LegacyShadowAdaptationError(ValueError):
    """Legacy evidence is insufficient for the strict shadow schema."""


@dataclass(frozen=True)
class LegacyCandidateProvenance:
    source_generation_ref: ResourceSourceGenerationRef
    source_class: ResourceSourceKind
    scope_id: str
    source_root_order: int
    content_origin: ResourceContentOrigin
    opaque_locator: str

    def __post_init__(self) -> None:
        if not self.scope_id:
            raise ValueError("Legacy shadow scope id must be non-empty.")
        if self.source_root_order < 0:
            raise ValueError("Legacy shadow source root order cannot be negative.")
        if not self.opaque_locator:
            raise ValueError("Legacy shadow opaque locator must be non-empty.")


@dataclass(frozen=True)
class LegacyShadowEffectiveEntry:
    identity: ResourceIdentity
    candidate_fingerprints: tuple[str, ...]


@dataclass(frozen=True)
class LegacyShadowCandidateBinding:
    candidate_fingerprint: str
    resource_kind: str
    descriptor: LegacyDescriptor
    content_origin: ResourceContentOrigin


@dataclass(frozen=True)
class LegacyShadowAdaptation:
    source_snapshots: tuple[ResourceSourceSnapshot, ...]
    legacy_effective_entries: tuple[LegacyShadowEffectiveEntry, ...]
    candidate_bindings: tuple[LegacyShadowCandidateBinding, ...]
    legacy_diagnostics: tuple[DiagnosticDraft, ...]


@dataclass(frozen=True)
class ResourceShadowDifference:
    identity: ResourceIdentity
    legacy_candidate_fingerprints: tuple[str, ...]
    catalog_candidate_fingerprints: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ResourceCatalogShadowReport:
    matches: bool
    differences: tuple[ResourceShadowDifference, ...]
    known_exceptions: tuple[ResourceShadowDifference, ...]


def adapt_legacy_resource_snapshot(
    snapshot: ResourceSnapshot,
    *,
    discovery_request_fingerprint: str,
    provenance_resolver: LegacyProvenanceResolver,
    diagnostic_source_generation_ref: ResourceSourceGenerationRef | None = None,
) -> LegacyShadowAdaptation:
    """Normalize one current snapshot into exact-generation source snapshots."""

    candidate_descriptors = _candidate_descriptors(snapshot)
    active_descriptors = _active_descriptors(snapshot)
    by_object_id: dict[int, ResourceCandidateSummary] = {}
    candidates_by_source: dict[
        ResourceSourceGenerationRef, list[ResourceCandidateSummary]
    ] = defaultdict(list)

    for resource_kind, descriptor in candidate_descriptors:
        provenance = provenance_resolver(descriptor)
        candidate = _adapt_descriptor(
            descriptor,
            resource_kind=resource_kind,
            discovery_request_fingerprint=discovery_request_fingerprint,
            provenance=provenance,
        )
        by_object_id[id(descriptor)] = candidate
        candidates_by_source[provenance.source_generation_ref].append(candidate)

    missing_active = [
        descriptor
        for _resource_kind, descriptor in active_descriptors
        if id(descriptor) not in by_object_id
    ]
    if missing_active:
        raise LegacyShadowAdaptationError(
            "Legacy active descriptors must also appear in the candidate inventory."
        )

    source_refs = tuple(sorted(candidates_by_source, key=_source_generation_sort_key))
    diagnostics_by_source: dict[
        ResourceSourceGenerationRef, list[ResourceCatalogDiagnostic]
    ] = defaultdict(list)
    if snapshot.diagnostics:
        target = diagnostic_source_generation_ref
        if target is None:
            if len(source_refs) != 1:
                raise LegacyShadowAdaptationError(
                    "Legacy diagnostics spanning multiple sources require an explicit "
                    "diagnostic source generation."
                )
            target = source_refs[0]
        if target not in candidates_by_source:
            candidates_by_source[target] = []
            source_refs = tuple(
                sorted(candidates_by_source, key=_source_generation_sort_key)
            )
        diagnostics_by_source[target].extend(
            _adapt_diagnostic(diagnostic, source_id=target.source_id)
            for diagnostic in snapshot.diagnostics
        )

    source_snapshots = tuple(
        build_source_snapshot(
            source_generation_ref=source_ref,
            discovery_request_fingerprint=discovery_request_fingerprint,
            candidate_summaries=tuple(candidates_by_source[source_ref]),
            diagnostics=tuple(diagnostics_by_source[source_ref]),
        )
        for source_ref in source_refs
    )

    effective_by_identity: dict[ResourceIdentity, list[str]] = defaultdict(list)
    for _resource_kind, descriptor in active_descriptors:
        candidate = by_object_id[id(descriptor)]
        effective_by_identity[candidate.identity].append(
            candidate.candidate_fingerprint
        )
    legacy_effective = tuple(
        LegacyShadowEffectiveEntry(
            identity=identity,
            candidate_fingerprints=tuple(fingerprints),
        )
        for identity, fingerprints in sorted(effective_by_identity.items())
    )
    candidate_bindings = tuple(
        sorted(
            (
                LegacyShadowCandidateBinding(
                    candidate_fingerprint=by_object_id[
                        id(descriptor)
                    ].candidate_fingerprint,
                    resource_kind=resource_kind,
                    descriptor=descriptor,
                    content_origin=by_object_id[id(descriptor)].content_origin,
                )
                for resource_kind, descriptor in candidate_descriptors
            ),
            key=lambda binding: binding.candidate_fingerprint,
        )
    )
    return LegacyShadowAdaptation(
        source_snapshots=source_snapshots,
        legacy_effective_entries=legacy_effective,
        candidate_bindings=candidate_bindings,
        legacy_diagnostics=snapshot.diagnostics,
    )


def compare_legacy_resource_snapshot(
    *,
    adaptation: LegacyShadowAdaptation,
    catalog_snapshot: ResourceCatalogSnapshot,
    known_extension_collision_identities: Iterable[ResourceIdentity] = (),
) -> ResourceCatalogShadowReport:
    """Compare effective evidence and isolate only the frozen Extension exception."""

    known = frozenset(known_extension_collision_identities)
    bindings = {
        binding.candidate_fingerprint: binding
        for binding in adaptation.candidate_bindings
    }
    legacy = {
        entry.identity: entry.candidate_fingerprints
        for entry in adaptation.legacy_effective_entries
    }
    catalog = {
        entry.identity: entry.candidate_fingerprints
        for entry in catalog_snapshot.effective_entries
    }
    differences: list[ResourceShadowDifference] = []
    known_exceptions: list[ResourceShadowDifference] = []
    for identity in sorted(set(legacy) | set(catalog)):
        legacy_fingerprints = legacy.get(identity, ())
        catalog_fingerprints = catalog.get(identity, ())
        if legacy_fingerprints == catalog_fingerprints:
            continue
        difference = ResourceShadowDifference(
            identity=identity,
            legacy_candidate_fingerprints=legacy_fingerprints,
            catalog_candidate_fingerprints=catalog_fingerprints,
            reason=(
                "legacy_extension_post_discovery_collision"
                if identity in known
                else "effective_candidate_mismatch"
            ),
        )
        if identity in known:
            if not _is_frozen_extension_collision(
                identity=identity,
                legacy_candidate_fingerprints=legacy_fingerprints,
                bindings=bindings,
            ):
                raise LegacyShadowAdaptationError(
                    "A known Extension collision exception requires duplicate legacy "
                    "Skill/Prompt evidence with extension_output provenance."
                )
            known_exceptions.append(difference)
        else:
            differences.append(difference)
    observed_difference_identities = {
        difference.identity for difference in (*differences, *known_exceptions)
    }
    if not known <= observed_difference_identities:
        raise LegacyShadowAdaptationError(
            "A declared Extension collision exception did not match a shadow difference."
        )
    return ResourceCatalogShadowReport(
        matches=not differences,
        differences=tuple(differences),
        known_exceptions=tuple(known_exceptions),
    )


def project_shadow_compatibility_bundle(
    *,
    adaptation: LegacyShadowAdaptation,
    catalog_snapshot: ResourceCatalogSnapshot,
    cwd: Path,
) -> ResourceBundle:
    """Build a disposable v1 projection for tests without changing authority."""

    bindings = {
        binding.candidate_fingerprint: binding
        for binding in adaptation.candidate_bindings
    }
    selected = [
        bindings[fingerprint]
        for entry in catalog_snapshot.effective_entries
        for fingerprint in entry.candidate_fingerprints
    ]
    context_bindings = sorted(
        (
            binding
            for binding in selected
            if binding.resource_kind == "context"
            and isinstance(binding.descriptor, PromptFragmentDescriptor)
        ),
        key=_legacy_context_projection_key,
    )
    contexts = tuple(
        cast(PromptFragmentDescriptor, binding.descriptor)
        for binding in context_bindings
    )
    prompts = tuple(
        binding.descriptor
        for binding in selected
        if binding.resource_kind == "prompt"
        and isinstance(binding.descriptor, PromptFragmentDescriptor)
    )
    skills = tuple(
        binding.descriptor
        for binding in selected
        if binding.resource_kind == "skill"
        and isinstance(binding.descriptor, SkillDescriptor)
    )
    extensions = tuple(
        binding.descriptor
        for binding in selected
        if binding.resource_kind == "extension"
        and isinstance(binding.descriptor, ExtensionDescriptor)
    )
    themes = tuple(
        binding.descriptor
        for binding in selected
        if binding.resource_kind == "theme"
        and isinstance(binding.descriptor, ThemeDescriptor)
    )
    projected = ResourceSnapshot(
        cwd=cwd,
        active_context_descriptors=contexts,
        active_prompt_descriptors=prompts,
        active_skill_descriptors=skills,
        active_extension_descriptors=extensions,
        active_theme_descriptors=themes,
        diagnostics=adaptation.legacy_diagnostics,
    )
    return projected.to_bundle()


def _candidate_descriptors(
    snapshot: ResourceSnapshot,
) -> tuple[tuple[str, LegacyDescriptor], ...]:
    return (
        *(
            ("context", descriptor)
            for descriptor in snapshot.candidate_agents_descriptors
        ),
        *(
            ("prompt", descriptor)
            for descriptor in snapshot.candidate_prompt_descriptors
        ),
        *(("skill", descriptor) for descriptor in snapshot.candidate_skill_descriptors),
        *(
            ("extension", descriptor)
            for descriptor in snapshot.candidate_extension_descriptors
        ),
        *(("theme", descriptor) for descriptor in snapshot.candidate_theme_descriptors),
    )


def _legacy_context_projection_key(
    binding: LegacyShadowCandidateBinding,
) -> tuple[int, int, str, str]:
    descriptor = binding.descriptor
    assert isinstance(descriptor, PromptFragmentDescriptor)
    source_rank = {
        "user_global": 0,
        "project_local": 1,
        "temporary": 2,
        "external_package": 3,
        "built_in": 4,
    }[descriptor.source_kind]
    return (
        source_rank,
        descriptor.source_root_order,
        descriptor.canonical_name or descriptor.name,
        binding.candidate_fingerprint,
    )


def _is_frozen_extension_collision(
    *,
    identity: ResourceIdentity,
    legacy_candidate_fingerprints: tuple[str, ...],
    bindings: dict[str, LegacyShadowCandidateBinding],
) -> bool:
    if identity.resource_kind not in {"prompt", "skill"}:
        return False
    if len(legacy_candidate_fingerprints) < 2:
        return False
    return any(
        isinstance(bindings[fingerprint].content_origin, ExtensionOutputOrigin)
        for fingerprint in legacy_candidate_fingerprints
    )


def _active_descriptors(
    snapshot: ResourceSnapshot,
) -> tuple[tuple[str, LegacyDescriptor], ...]:
    active_context = snapshot.active_context_descriptors
    if not active_context and snapshot.active_agents_descriptor is not None:
        active_context = (snapshot.active_agents_descriptor,)
    return (
        *(("context", descriptor) for descriptor in active_context),
        *(("prompt", descriptor) for descriptor in snapshot.active_prompt_descriptors),
        *(("skill", descriptor) for descriptor in snapshot.active_skill_descriptors),
        *(
            ("extension", descriptor)
            for descriptor in snapshot.active_extension_descriptors
        ),
        *(("theme", descriptor) for descriptor in snapshot.active_theme_descriptors),
    )


def _adapt_descriptor(
    descriptor: LegacyDescriptor,
    *,
    resource_kind: str,
    discovery_request_fingerprint: str,
    provenance: LegacyCandidateProvenance,
) -> ResourceCandidateSummary:
    if (
        descriptor.source_kind != provenance.source_class
        or descriptor.source_scope != provenance.scope_id
        or descriptor.source_root_order != provenance.source_root_order
    ):
        raise LegacyShadowAdaptationError(
            "Legacy descriptor facts do not match owner-supplied source facts."
        )
    identity = ResourceIdentity(
        resource_kind=resource_kind,
        schema_id=f"loushang.resource.{resource_kind}",
        schema_version=1,
        public_id=descriptor.id or descriptor.name,
    )
    body = _descriptor_body(descriptor)
    if body is None:
        if resource_kind not in {"extension", "theme"}:
            raise LegacyShadowAdaptationError(
                f"Legacy {resource_kind} '{identity.public_id}' has no exact body identity."
            )
        media_type = NO_BODY_MEDIA_TYPE
        expected_digest = None
        expected_length = None
    else:
        encoded = body.encode("utf-8")
        media_type = _media_type(resource_kind)
        expected_digest = hashlib.sha256(encoded).hexdigest()
        expected_length = len(encoded)

    candidate_diagnostics = tuple(
        _adapt_diagnostic(
            diagnostic,
            source_id=provenance.source_generation_ref.source_id,
            identity=identity,
        )
        for diagnostic in descriptor.diagnostics
    )
    model_invocable = not isinstance(
        descriptor, ExtensionDescriptor | ThemeDescriptor
    ) and not (
        isinstance(descriptor, SkillDescriptor) and descriptor.disable_model_invocation
    )
    return build_candidate_summary(
        identity=identity,
        canonical_name=descriptor.canonical_name or descriptor.name,
        description=getattr(descriptor, "description", None),
        media_type=media_type,
        invocation_policy=ResourceInvocationPolicy(
            enabled=descriptor.enabled,
            model_invocable=model_invocable,
            reason="legacy_snapshot_shadow",
        ),
        source_generation_ref=provenance.source_generation_ref,
        source_class=provenance.source_class,
        scope_id=provenance.scope_id,
        source_root_order=provenance.source_root_order,
        content_origin=provenance.content_origin,
        opaque_locator=provenance.opaque_locator,
        discovery_fingerprint=fingerprint_catalog_value(
            "loushang.resource-legacy-discovery/v2",
            {
                "discoveryRequestFingerprint": discovery_request_fingerprint,
                "identity": identity.to_payload(),
                "opaqueLocator": provenance.opaque_locator,
                "scopeId": provenance.scope_id,
                "sourceClass": provenance.source_class,
                "sourceGeneration": provenance.source_generation_ref.to_payload(),
                "sourceRootOrder": provenance.source_root_order,
            },
        ),
        expected_content_digest=expected_digest,
        expected_content_length=expected_length,
        diagnostics=candidate_diagnostics,
    )


def _descriptor_body(descriptor: LegacyDescriptor) -> str | None:
    if isinstance(descriptor, PromptFragmentDescriptor):
        return descriptor.text
    if isinstance(descriptor, SkillDescriptor | ThemeDescriptor):
        return descriptor.content
    return None


def _media_type(resource_kind: str) -> str:
    if resource_kind == "theme":
        return "application/json"
    return "text/markdown"


def _adapt_diagnostic(
    diagnostic: DiagnosticDraft,
    *,
    source_id: str,
    identity: ResourceIdentity | None = None,
) -> ResourceCatalogDiagnostic:
    return ResourceCatalogDiagnostic(
        code=diagnostic.code,
        reason="legacy_diagnostic",
        identity=identity,
        source_id=source_id,
    )


def _source_generation_sort_key(
    source_ref: ResourceSourceGenerationRef,
) -> str:
    return fingerprint_catalog_value(
        "loushang.resource-source-generation-ref/v2",
        source_ref.to_payload(),
    )


__all__ = [
    "LegacyCandidateProvenance",
    "LegacyShadowAdaptation",
    "LegacyShadowAdaptationError",
    "LegacyShadowCandidateBinding",
    "LegacyShadowEffectiveEntry",
    "ResourceCatalogShadowReport",
    "ResourceShadowDifference",
    "adapt_legacy_resource_snapshot",
    "compare_legacy_resource_snapshot",
    "project_shadow_compatibility_bundle",
]
