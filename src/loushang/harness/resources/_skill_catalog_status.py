"""Catalog-owned body-free status projection for every admitted Skill candidate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.resources._catalog_projection import (
    ResourceProjectionDescriptorBinding,
)
from loushang.harness.resources._catalog_records import (
    ResourceCandidateSummary,
    ResourceCatalogDiagnostic,
    ResourceCatalogSnapshot,
    ResourceEffectiveEntry,
    ResourceIdentity,
    ResourceMergeDecision,
)
from loushang.harness.resources.types import (
    ResourceSourceKind,
    ResourceSourceScope,
    RevisionResourceRef,
    SkillDescriptor,
)

SkillCandidateStatus = Literal[
    "effective",
    "inactive_activation",
    "inactive_declaration",
    "shadowed",
    "rejected_conflict",
]
_SKILL_CANDIDATE_STATUSES = frozenset(
    {
        "effective",
        "inactive_activation",
        "inactive_declaration",
        "shadowed",
        "rejected_conflict",
    }
)


class SkillCatalogStatusProjectionError(RuntimeError):
    """Fail-closed owner-generation status projection failure."""


@dataclass(frozen=True, slots=True)
class SkillCatalogStatusSummary:
    """Body-free status and provenance for one exact Skill candidate."""

    catalog_generation: int
    catalog_snapshot_fingerprint: str
    candidate_fingerprint: str
    identity: ResourceIdentity
    name: str
    canonical_name: str
    description: str | None
    declared_enabled: bool
    declared_model_invocable: bool
    effective: bool
    primary: bool
    model_invocable: bool
    status: SkillCandidateStatus
    status_reason: str
    media_type: str
    expected_content_digest: str
    expected_content_length: int
    source_path: Path
    source_root: Path | None
    source_kind: ResourceSourceKind
    source_scope: ResourceSourceScope
    source_root_order: int
    source: str
    diagnostics: tuple[ResourceCatalogDiagnostic, ...]
    declared_id: str | None
    revision_ref: RevisionResourceRef | None

    def __post_init__(self) -> None:
        boolean_facts = (
            self.declared_enabled,
            self.declared_model_invocable,
            self.effective,
            self.primary,
            self.model_invocable,
        )
        if any(type(value) is not bool for value in boolean_facts):
            raise TypeError("Skill status boolean facts must be bool")
        if self.catalog_generation < 1:
            raise ValueError("Skill status Catalog generation must be positive")
        _require_digest(
            self.catalog_snapshot_fingerprint,
            name="Skill status Catalog snapshot fingerprint",
        )
        _require_digest(
            self.candidate_fingerprint,
            name="Skill status candidate fingerprint",
        )
        if self.identity.resource_kind != "skill":
            raise ValueError("Skill status identity must name a Skill")
        if not self.name or not self.canonical_name:
            raise ValueError("Skill status names must not be empty")
        if not self.status_reason:
            raise ValueError("Skill status reason must not be empty")
        if self.status not in _SKILL_CANDIDATE_STATUSES:
            raise ValueError("Skill candidate status is unsupported")
        if self.expected_content_length < 0:
            raise ValueError("Skill status body length cannot be negative")
        _require_digest(
            self.expected_content_digest,
            name="Skill status expected content digest",
        )
        if self.effective != (self.status == "effective"):
            raise ValueError("Skill status effective fact is inconsistent")
        if self.declared_enabled != (self.status != "inactive_declaration"):
            raise ValueError("Skill status declaration fact is inconsistent")
        if self.primary and not self.effective:
            raise ValueError("Only an effective Skill status can be primary")
        if self.model_invocable and not self.effective:
            raise ValueError("Only an effective Skill status can be model-invocable")
        if self.model_invocable and not self.declared_model_invocable:
            raise ValueError(
                "A model-invocable Skill status must declare model invocation"
            )

    @property
    def id(self) -> str:
        return self.identity.public_id


@dataclass(frozen=True, slots=True)
class SkillCatalogStatusProjection:
    """All admitted Skill candidate statuses from one exact Catalog generation."""

    catalog_generation: int
    catalog_snapshot_fingerprint: str
    skills: tuple[SkillCatalogStatusSummary, ...]

    def __post_init__(self) -> None:
        if self.catalog_generation < 1:
            raise ValueError("Skill status projection generation must be positive")
        _require_digest(
            self.catalog_snapshot_fingerprint,
            name="Skill status projection Catalog snapshot fingerprint",
        )
        if any(
            not isinstance(skill, SkillCatalogStatusSummary) for skill in self.skills
        ):
            raise TypeError("Skill status projection summaries must be typed")
        if any(
            skill.catalog_generation != self.catalog_generation
            or skill.catalog_snapshot_fingerprint
            != self.catalog_snapshot_fingerprint
            for skill in self.skills
        ):
            raise ValueError("Skill statuses must share one Catalog generation")
        candidates = tuple(skill.candidate_fingerprint for skill in self.skills)
        if len(set(candidates)) != len(candidates):
            raise ValueError("Skill status candidates must be unique")
        statuses_by_identity: dict[
            ResourceIdentity,
            list[SkillCatalogStatusSummary],
        ] = {}
        for skill in self.skills:
            statuses_by_identity.setdefault(skill.identity, []).append(skill)
        for statuses in statuses_by_identity.values():
            effective = tuple(status for status in statuses if status.effective)
            if effective and sum(status.primary for status in effective) != 1:
                raise ValueError(
                    "Effective Skill statuses must have exactly one primary"
                )
            if len({status.model_invocable for status in effective}) > 1:
                raise ValueError(
                    "Effective Skill statuses must share model invocation state"
                )


def build_skill_catalog_status_projection(
    *,
    snapshot: ResourceCatalogSnapshot,
    descriptor_bindings: tuple[ResourceProjectionDescriptorBinding, ...],
) -> SkillCatalogStatusProjection:
    """Project status without re-running Catalog selection or activation policy."""

    if not isinstance(snapshot, ResourceCatalogSnapshot):
        raise TypeError("Skill status projection requires a Catalog snapshot")
    if not snapshot.complete:
        raise SkillCatalogStatusProjectionError(
            "Skill status projection Catalog is incomplete"
        )
    if any(
        not isinstance(binding, ResourceProjectionDescriptorBinding)
        for binding in descriptor_bindings
    ):
        raise TypeError("Skill status projection bindings must be typed")

    skill_candidates = {
        candidate.candidate_fingerprint: candidate
        for candidate in snapshot.candidate_summaries
        if candidate.identity.resource_kind == "skill"
    }
    skill_bindings: dict[str, ResourceProjectionDescriptorBinding] = {}
    for binding in descriptor_bindings:
        if binding.resource_kind != "skill":
            continue
        fingerprint = binding.candidate_fingerprint
        if fingerprint not in skill_candidates:
            raise SkillCatalogStatusProjectionError(
                "Skill status projection contains a foreign descriptor binding"
            )
        if fingerprint in skill_bindings:
            raise SkillCatalogStatusProjectionError(
                "Skill status projection contains a duplicate descriptor binding"
            )
        skill_bindings[fingerprint] = binding
    if set(skill_bindings) != set(skill_candidates):
        raise SkillCatalogStatusProjectionError(
            "Skill status projection does not cover every Catalog candidate"
        )

    effective_by_identity = {
        entry.identity: entry
        for entry in snapshot.effective_entries
        if entry.identity.resource_kind == "skill"
    }
    summaries: list[SkillCatalogStatusSummary] = []
    for decision in snapshot.merge_decisions:
        if decision.identity.resource_kind != "skill":
            continue
        effective = effective_by_identity.get(decision.identity)
        for fingerprint in decision.candidate_fingerprints:
            candidate = skill_candidates[fingerprint]
            descriptor = _validated_skill_descriptor(
                candidate,
                skill_bindings[fingerprint],
            )
            summaries.append(
                _project_status_summary(
                    snapshot=snapshot,
                    candidate=candidate,
                    descriptor=descriptor,
                    decision=decision,
                    effective_entry=effective,
                )
            )
    if len(summaries) != len(skill_candidates):
        raise SkillCatalogStatusProjectionError(
            "Catalog decisions do not account for every Skill candidate"
        )
    return SkillCatalogStatusProjection(
        catalog_generation=snapshot.catalog_generation,
        catalog_snapshot_fingerprint=snapshot.snapshot_fingerprint,
        skills=tuple(summaries),
    )


def _project_status_summary(
    *,
    snapshot: ResourceCatalogSnapshot,
    candidate: ResourceCandidateSummary,
    descriptor: SkillDescriptor,
    decision: ResourceMergeDecision,
    effective_entry: ResourceEffectiveEntry | None,
) -> SkillCatalogStatusSummary:
    fingerprint = candidate.candidate_fingerprint
    is_effective = fingerprint in decision.effective_candidate_fingerprints
    is_primary = fingerprint == decision.winner_candidate_fingerprint
    status = _candidate_status(
        candidate=candidate,
        decision=decision,
        effective=is_effective,
    )
    if candidate.expected_content_digest is None or (
        candidate.expected_content_length is None
    ):
        raise SkillCatalogStatusProjectionError(
            "Skill status candidate has no body identity"
        )
    if is_effective and effective_entry is None:
        raise SkillCatalogStatusProjectionError(
            "Effective Skill status has no Catalog effective entry"
        )
    model_invocable = bool(
        is_effective
        and effective_entry is not None
        and effective_entry.model_invocable
    )
    return SkillCatalogStatusSummary(
        catalog_generation=snapshot.catalog_generation,
        catalog_snapshot_fingerprint=snapshot.snapshot_fingerprint,
        candidate_fingerprint=fingerprint,
        identity=candidate.identity,
        name=descriptor.name,
        canonical_name=descriptor.canonical_name or descriptor.name,
        description=descriptor.description,
        declared_enabled=candidate.invocation_policy.enabled,
        declared_model_invocable=candidate.invocation_policy.model_invocable,
        effective=is_effective,
        primary=is_primary,
        model_invocable=model_invocable,
        status=status,
        status_reason=decision.reason,
        media_type=candidate.media_type,
        expected_content_digest=candidate.expected_content_digest,
        expected_content_length=candidate.expected_content_length,
        source_path=descriptor.source_path,
        source_root=descriptor.source_root,
        source_kind=descriptor.source_kind,
        source_scope=descriptor.source_scope,
        source_root_order=descriptor.source_root_order,
        source=descriptor.source,
        diagnostics=candidate.diagnostics,
        declared_id=descriptor.declared_id,
        revision_ref=descriptor.revision_ref,
    )


def _candidate_status(
    *,
    candidate: ResourceCandidateSummary,
    decision: ResourceMergeDecision,
    effective: bool,
) -> SkillCandidateStatus:
    if effective:
        return "effective"
    if not candidate.invocation_policy.enabled:
        return "inactive_declaration"
    if decision.reason == "activation_disabled":
        return "inactive_activation"
    if decision.rejected:
        return "rejected_conflict"
    return "shadowed"


def _validated_skill_descriptor(
    candidate: ResourceCandidateSummary,
    binding: ResourceProjectionDescriptorBinding,
) -> SkillDescriptor:
    try:
        verified_binding = ResourceProjectionDescriptorBinding(
            candidate_fingerprint=binding.candidate_fingerprint,
            resource_kind=binding.resource_kind,
            descriptor=binding.descriptor,
            descriptor_fingerprint=binding.descriptor_fingerprint,
        )
    except (TypeError, ValueError) as error:
        raise SkillCatalogStatusProjectionError(
            "Skill status descriptor binding evidence is invalid"
        ) from error
    descriptor = verified_binding.descriptor
    if not isinstance(descriptor, SkillDescriptor):
        raise SkillCatalogStatusProjectionError(
            "Skill status descriptor binding has the wrong type"
        )
    if (
        binding.candidate_fingerprint != candidate.candidate_fingerprint
        or (descriptor.id or descriptor.name) != candidate.identity.public_id
        or (descriptor.canonical_name or descriptor.name)
        != candidate.canonical_name
        or descriptor.description != candidate.description
        or descriptor.enabled != candidate.invocation_policy.enabled
        or (not descriptor.disable_model_invocation)
        != candidate.invocation_policy.model_invocable
        or descriptor.source_kind != candidate.source_class
        or descriptor.source_scope != candidate.scope_id
        or descriptor.source_root_order != candidate.source_root_order
    ):
        raise SkillCatalogStatusProjectionError(
            "Skill status descriptor facts do not match the Catalog candidate"
        )
    return descriptor


def _require_digest(value: str, *, name: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be SHA-256")


__all__ = [
    "SkillCandidateStatus",
    "SkillCatalogStatusProjection",
    "SkillCatalogStatusProjectionError",
    "SkillCatalogStatusSummary",
    "build_skill_catalog_status_projection",
]
