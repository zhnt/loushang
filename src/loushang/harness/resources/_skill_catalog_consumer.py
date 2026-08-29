"""Exact-generation typed Skill projection over the Resource Catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._catalog_records import (
    LoadedResource,
    ResourceCandidateSummary,
    ResourceCatalogDiagnostic,
    ResourceCatalogSnapshot,
    ResourceIdentity,
    ResourceLoadHandle,
    ResourceLoadReceipt,
)
from loushang.harness.resources._skill_catalog_status import (
    SkillCatalogStatusProjection,
    SkillCatalogStatusSummary,
)
from loushang.harness.resources.types import (
    ResourceSourceKind,
    ResourceSourceScope,
    RevisionResourceRef,
    SkillDescriptor,
)


class SkillCatalogConsumerError(RuntimeError):
    """Fail-closed typed Skill projection or load failure."""


class _ResourceCatalogLoadConsumer(Protocol):
    @property
    def snapshot(self) -> ResourceCatalogSnapshot: ...

    @property
    def skill_projection(self) -> EffectiveSkillCatalogProjection: ...

    def load_handle(self, identity: ResourceIdentity) -> ResourceLoadHandle: ...

    async def load(self, handle: ResourceLoadHandle) -> LoadedResource: ...


@dataclass(frozen=True, slots=True)
class SkillCatalogSummary:
    """Body-free Skill metadata pinned to one exact Catalog generation."""

    catalog_generation: int
    catalog_snapshot_fingerprint: str
    candidate_fingerprint: str
    identity: ResourceIdentity
    name: str
    canonical_name: str
    description: str | None
    enabled: bool
    model_invocable: bool
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
        if self.catalog_generation < 1:
            raise ValueError("Skill summary Catalog generation must be positive")
        if self.identity.resource_kind != "skill":
            raise ValueError("Skill summary identity must name a Skill")
        if self.identity.public_id == "":
            raise ValueError("Skill summary public id must not be empty")
        if not self.name or not self.canonical_name:
            raise ValueError("Skill summary names must not be empty")
        if self.expected_content_length < 0:
            raise ValueError("Skill summary body length cannot be negative")

    @property
    def id(self) -> str:
        return self.identity.public_id

    @property
    def disable_model_invocation(self) -> bool:
        return not self.model_invocable



@dataclass(frozen=True, slots=True)
class EffectiveSkillCatalogProjection:
    """Body-free effective Skill view owned by one Catalog generation."""

    catalog_generation: int
    catalog_snapshot_fingerprint: str
    skills: tuple[SkillCatalogSummary, ...]

    def __post_init__(self) -> None:
        if self.catalog_generation < 1:
            raise ValueError("Skill projection Catalog generation must be positive")
        if any(
            skill.catalog_generation != self.catalog_generation
            or skill.catalog_snapshot_fingerprint
            != self.catalog_snapshot_fingerprint
            for skill in self.skills
        ):
            raise ValueError("Skill projection summaries must share one Catalog")
        identities = tuple(skill.identity for skill in self.skills)
        candidates = tuple(skill.candidate_fingerprint for skill in self.skills)
        if len(set(identities)) != len(identities):
            raise ValueError("Skill projection identities must be unique")
        if len(set(candidates)) != len(candidates):
            raise ValueError("Skill projection candidates must be unique")


@dataclass(frozen=True, slots=True)
class SkillCatalogLoadHandle:
    """Skill-narrowed wrapper around one owner-minted Resource load handle."""

    catalog_generation: int
    catalog_snapshot_fingerprint: str
    candidate_fingerprint: str
    identity: ResourceIdentity
    resource_handle: ResourceLoadHandle

    def __post_init__(self) -> None:
        if self.identity.resource_kind != "skill":
            raise ValueError("Skill load handle must name a Skill")
        handle = self.resource_handle
        if (
            handle.catalog_generation != self.catalog_generation
            or handle.snapshot_fingerprint != self.catalog_snapshot_fingerprint
            or handle.candidate_fingerprint != self.candidate_fingerprint
            or handle.identity != self.identity
        ):
            raise ValueError("Skill load handle does not match its Resource handle")


@dataclass(frozen=True, slots=True)
class LoadedSkillBody:
    """Validated Skill bytes, UTF-8 content, and exact Resource receipt."""

    summary: SkillCatalogSummary
    receipt: ResourceLoadReceipt
    body: bytes
    content: str

    def __post_init__(self) -> None:
        if self.receipt.candidate_fingerprint != self.summary.candidate_fingerprint:
            raise ValueError("Loaded Skill receipt names another candidate")
        if self.receipt.catalog_generation != self.summary.catalog_generation:
            raise ValueError("Loaded Skill receipt names another generation")
        if (
            self.receipt.snapshot_fingerprint
            != self.summary.catalog_snapshot_fingerprint
        ):
            raise ValueError("Loaded Skill receipt names another Catalog snapshot")
        if (
            self.receipt.schema_id != self.summary.identity.schema_id
            or self.receipt.schema_version != self.summary.identity.schema_version
        ):
            raise ValueError("Loaded Skill receipt names another schema")
        if self.receipt.media_type != self.summary.media_type:
            raise ValueError("Loaded Skill receipt names another media type")
        if (
            self.receipt.content_digest != self.summary.expected_content_digest
            or self.receipt.content_length != self.summary.expected_content_length
        ):
            raise ValueError("Loaded Skill receipt names another body identity")
        if self.body.decode("utf-8") != self.content:
            raise ValueError("Loaded Skill content does not match its bytes")


class SkillCatalogConsumer:
    """Read-only Skill view derived from one captured Resource generation."""

    def __init__(self, catalog: _ResourceCatalogLoadConsumer) -> None:
        snapshot = catalog.snapshot
        projection = catalog.skill_projection
        if not isinstance(snapshot, ResourceCatalogSnapshot):
            raise TypeError("Skill Consumer requires a Resource Catalog snapshot")
        if not isinstance(projection, EffectiveSkillCatalogProjection):
            raise TypeError("Skill Consumer requires a body-free Skill projection")
        if (
            projection.catalog_generation != snapshot.catalog_generation
            or projection.catalog_snapshot_fingerprint
            != snapshot.snapshot_fingerprint
        ):
            raise SkillCatalogConsumerError(
                "Skill projection belongs to another Catalog generation"
            )
        self._catalog = catalog
        self._catalog_generation = snapshot.catalog_generation
        self._snapshot_fingerprint = snapshot.snapshot_fingerprint
        self._skills = projection.skills
        self._candidates = _bind_projection_to_snapshot(
            snapshot=snapshot,
            projection=projection,
        )
        status_projection = getattr(catalog, "skill_status_projection", None)
        if status_projection is None:
            self._skill_statuses: tuple[SkillCatalogStatusSummary, ...] | None = None
        else:
            if not isinstance(status_projection, SkillCatalogStatusProjection):
                raise TypeError(
                    "Skill Consumer requires a body-free Skill status projection"
                )
            self._skill_statuses = _bind_status_projection_to_snapshot(
                snapshot=snapshot,
                effective_projection=projection,
                status_projection=status_projection,
            )

    @property
    def catalog_generation(self) -> int:
        return self._catalog_generation

    @property
    def catalog_snapshot_fingerprint(self) -> str:
        return self._snapshot_fingerprint

    def list_effective_skills(self) -> tuple[SkillCatalogSummary, ...]:
        """Return only Catalog-effective Skills from this first read slice."""

        return self._skills

    def list_skill_statuses(self) -> tuple[SkillCatalogStatusSummary, ...]:
        """Return every Catalog Skill candidate from an exact-v4 capture."""

        statuses = self._skill_statuses
        if statuses is None:
            raise SkillCatalogConsumerError(
                "Skill status projection is not available from this Catalog capture"
            )
        return statuses

    def get_effective_skill(self, name: str) -> SkillCatalogSummary | None:
        if not isinstance(name, str) or not name:
            raise ValueError("Skill lookup name must not be empty")
        matches = tuple(
            skill
            for skill in self._skills
            if name
            in {
                skill.name,
                skill.id,
                skill.canonical_name,
                str(skill.source_path),
            }
        )
        if len(matches) > 1:
            raise SkillCatalogConsumerError("Skill lookup is ambiguous")
        return matches[0] if matches else None

    def load_handle(
        self,
        skill: SkillCatalogSummary | str,
    ) -> SkillCatalogLoadHandle:
        summary = self._resolve_owned_summary(skill)
        candidate = self._candidate_for_summary(summary)
        handle = self._catalog.load_handle(summary.identity)
        _validate_resource_handle(summary, candidate, handle)
        return SkillCatalogLoadHandle(
            catalog_generation=summary.catalog_generation,
            catalog_snapshot_fingerprint=summary.catalog_snapshot_fingerprint,
            candidate_fingerprint=summary.candidate_fingerprint,
            identity=summary.identity,
            resource_handle=handle,
        )

    async def load(self, handle: SkillCatalogLoadHandle) -> LoadedSkillBody:
        if not isinstance(handle, SkillCatalogLoadHandle):
            raise TypeError("Skill Consumer requires a Skill load handle")
        if (
            handle.catalog_generation != self._catalog_generation
            or handle.catalog_snapshot_fingerprint != self._snapshot_fingerprint
        ):
            raise SkillCatalogConsumerError(
                "Skill load handle belongs to another Catalog generation"
            )
        summary = self._summary_by_candidate(handle.candidate_fingerprint)
        if summary.identity != handle.identity:
            raise SkillCatalogConsumerError("Skill load handle identity is inconsistent")
        candidate = self._candidate_for_summary(summary)
        _validate_resource_handle(summary, candidate, handle.resource_handle)
        canonical_handle = self._catalog.load_handle(summary.identity)
        _validate_resource_handle(summary, candidate, canonical_handle)
        if canonical_handle != handle.resource_handle:
            raise SkillCatalogConsumerError(
                "Skill load handle is not the owner-minted exact handle"
            )
        loaded = await self._catalog.load(handle.resource_handle)
        _validate_loaded_resource(summary, handle.resource_handle, loaded)
        try:
            content = loaded.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SkillCatalogConsumerError("Skill body is not valid UTF-8") from error
        return LoadedSkillBody(
            summary=summary,
            receipt=loaded.receipt,
            body=loaded.body,
            content=content,
        )

    def _resolve_owned_summary(
        self,
        skill: SkillCatalogSummary | str,
    ) -> SkillCatalogSummary:
        if isinstance(skill, str):
            summary = self.get_effective_skill(skill)
            if summary is None:
                raise KeyError(skill)
            return summary
        if not isinstance(skill, SkillCatalogSummary):
            raise TypeError("Skill load requires a Skill summary or name")
        owned = self._summary_by_candidate(skill.candidate_fingerprint)
        if owned != skill:
            raise SkillCatalogConsumerError(
                "Skill summary belongs to another Catalog projection"
            )
        return owned

    def _summary_by_candidate(self, fingerprint: str) -> SkillCatalogSummary:
        for summary in self._skills:
            if summary.candidate_fingerprint == fingerprint:
                return summary
        raise SkillCatalogConsumerError("Skill candidate is not selected")

    def _candidate_for_summary(
        self,
        summary: SkillCatalogSummary,
    ) -> ResourceCandidateSummary:
        try:
            return self._candidates[summary.candidate_fingerprint]
        except KeyError as error:
            raise SkillCatalogConsumerError(
                "Skill candidate is not bound to the captured Catalog"
            ) from error


def build_effective_skill_catalog_projection(
    *,
    snapshot: ResourceCatalogSnapshot,
    projection: ResourceCatalogProjection,
) -> EffectiveSkillCatalogProjection:
    if not isinstance(snapshot, ResourceCatalogSnapshot):
        raise TypeError("Skill projection requires a Resource Catalog snapshot")
    if not isinstance(projection, ResourceCatalogProjection):
        raise TypeError("Skill projection requires a compatibility projection")
    if not snapshot.complete:
        raise SkillCatalogConsumerError("Skill projection Catalog is incomplete")
    if (
        projection.catalog_generation != snapshot.catalog_generation
        or projection.catalog_snapshot_fingerprint != snapshot.snapshot_fingerprint
    ):
        raise SkillCatalogConsumerError(
            "Skill compatibility projection belongs to another Catalog generation"
        )
    effective_by_identity = {
        entry.identity: entry
        for entry in snapshot.effective_entries
        if entry.identity.resource_kind == "skill"
    }
    summaries: list[SkillCatalogSummary] = []
    for binding in projection.selected_bindings:
        if binding.resource_kind != "skill":
            continue
        descriptor = binding.descriptor
        if not isinstance(descriptor, SkillDescriptor):
            raise SkillCatalogConsumerError("Skill projection descriptor is invalid")
        candidate = snapshot.candidate_by_fingerprint(
            binding.candidate_fingerprint
        )
        effective = effective_by_identity.get(candidate.identity)
        if (
            effective is None
            or candidate.candidate_fingerprint
            != effective.primary_candidate_fingerprint
            or candidate.candidate_fingerprint
            not in effective.candidate_fingerprints
        ):
            raise SkillCatalogConsumerError(
                "Skill projection is not effective in its Catalog"
            )
        if (
            candidate.expected_content_digest is None
            or candidate.expected_content_length is None
        ):
            raise SkillCatalogConsumerError("Selected Skill has no body identity")
        summaries.append(
            SkillCatalogSummary(
                catalog_generation=snapshot.catalog_generation,
                catalog_snapshot_fingerprint=snapshot.snapshot_fingerprint,
                candidate_fingerprint=candidate.candidate_fingerprint,
                identity=candidate.identity,
                name=descriptor.name,
                canonical_name=(descriptor.canonical_name or descriptor.name),
                description=descriptor.description,
                enabled=effective.enabled,
                model_invocable=effective.model_invocable,
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
        )
    if len(summaries) != len(effective_by_identity):
        raise SkillCatalogConsumerError(
            "Catalog Skill selection and projection do not match"
        )
    return EffectiveSkillCatalogProjection(
        catalog_generation=snapshot.catalog_generation,
        catalog_snapshot_fingerprint=snapshot.snapshot_fingerprint,
        skills=tuple(summaries),
    )


def _validate_resource_handle(
    summary: SkillCatalogSummary,
    candidate: ResourceCandidateSummary,
    handle: ResourceLoadHandle,
) -> None:
    if (
        handle.catalog_generation != summary.catalog_generation
        or handle.snapshot_fingerprint != summary.catalog_snapshot_fingerprint
        or handle.candidate_fingerprint != summary.candidate_fingerprint
        or handle.identity != summary.identity
        or handle.schema_id != summary.identity.schema_id
        or handle.schema_version != summary.identity.schema_version
        or handle.media_type != summary.media_type
        or handle.expected_content_digest != summary.expected_content_digest
        or handle.expected_content_length != summary.expected_content_length
        or handle.source_generation_ref != candidate.source_generation_ref
        or handle.opaque_locator != candidate.opaque_locator
    ):
        raise SkillCatalogConsumerError(
            "Resource load handle does not match the selected Skill"
        )


def _bind_projection_to_snapshot(
    *,
    snapshot: ResourceCatalogSnapshot,
    projection: EffectiveSkillCatalogProjection,
) -> dict[str, ResourceCandidateSummary]:
    effective_by_identity = {
        entry.identity: entry
        for entry in snapshot.effective_entries
        if entry.identity.resource_kind == "skill"
    }
    candidates: dict[str, ResourceCandidateSummary] = {}
    for summary in projection.skills:
        try:
            candidate = snapshot.candidate_by_fingerprint(
                summary.candidate_fingerprint
            )
        except KeyError as error:
            raise SkillCatalogConsumerError(
                "Skill projection names a foreign Catalog candidate"
            ) from error
        effective = effective_by_identity.get(summary.identity)
        if (
            effective is None
            or effective.primary_candidate_fingerprint
            != summary.candidate_fingerprint
            or candidate.identity != summary.identity
            or candidate.canonical_name != summary.canonical_name
            or candidate.description != summary.description
            or candidate.media_type != summary.media_type
            or candidate.expected_content_digest
            != summary.expected_content_digest
            or candidate.expected_content_length != summary.expected_content_length
            or candidate.source_class != summary.source_kind
            or candidate.scope_id != summary.source_scope
            or candidate.source_root_order != summary.source_root_order
            or candidate.diagnostics != summary.diagnostics
            or effective.enabled != summary.enabled
            or effective.model_invocable != summary.model_invocable
        ):
            raise SkillCatalogConsumerError(
                "Skill projection facts do not match the captured Catalog"
            )
        candidates[candidate.candidate_fingerprint] = candidate
    if len(candidates) != len(effective_by_identity):
        raise SkillCatalogConsumerError(
            "Skill projection does not cover the effective Catalog Skills"
        )
    return candidates


def _bind_status_projection_to_snapshot(
    *,
    snapshot: ResourceCatalogSnapshot,
    effective_projection: EffectiveSkillCatalogProjection,
    status_projection: SkillCatalogStatusProjection,
) -> tuple[SkillCatalogStatusSummary, ...]:
    if (
        status_projection.catalog_generation != snapshot.catalog_generation
        or status_projection.catalog_snapshot_fingerprint
        != snapshot.snapshot_fingerprint
    ):
        raise SkillCatalogConsumerError(
            "Skill status projection belongs to another Catalog generation"
        )
    skill_candidates = {
        candidate.candidate_fingerprint: candidate
        for candidate in snapshot.candidate_summaries
        if candidate.identity.resource_kind == "skill"
    }
    decisions_by_candidate = {
        fingerprint: decision
        for decision in snapshot.merge_decisions
        if decision.identity.resource_kind == "skill"
        for fingerprint in decision.candidate_fingerprints
    }
    effective_by_identity = {
        entry.identity: entry
        for entry in snapshot.effective_entries
        if entry.identity.resource_kind == "skill"
    }
    seen: set[str] = set()
    for status in status_projection.skills:
        candidate = skill_candidates.get(status.candidate_fingerprint)
        decision = decisions_by_candidate.get(status.candidate_fingerprint)
        if candidate is None or decision is None:
            raise SkillCatalogConsumerError(
                "Skill status projection names a foreign Catalog candidate"
            )
        effective = effective_by_identity.get(candidate.identity)
        expected_effective = (
            status.candidate_fingerprint
            in decision.effective_candidate_fingerprints
        )
        expected_primary = (
            status.candidate_fingerprint == decision.winner_candidate_fingerprint
        )
        expected_model_invocable = bool(
            expected_effective
            and effective is not None
            and effective.model_invocable
        )
        if (
            status.identity != candidate.identity
            or status.canonical_name != candidate.canonical_name
            or status.description != candidate.description
            or status.declared_enabled != candidate.invocation_policy.enabled
            or status.declared_model_invocable
            != candidate.invocation_policy.model_invocable
            or status.effective != expected_effective
            or status.primary != expected_primary
            or status.model_invocable != expected_model_invocable
            or status.status_reason != decision.reason
            or status.media_type != candidate.media_type
            or status.expected_content_digest
            != candidate.expected_content_digest
            or status.expected_content_length
            != candidate.expected_content_length
            or status.source_kind != candidate.source_class
            or status.source_scope != candidate.scope_id
            or status.source_root_order != candidate.source_root_order
            or status.diagnostics != candidate.diagnostics
        ):
            raise SkillCatalogConsumerError(
                "Skill status facts do not match the captured Catalog"
            )
        seen.add(status.candidate_fingerprint)
    if seen != set(skill_candidates):
        raise SkillCatalogConsumerError(
            "Skill status projection does not cover the Catalog candidates"
        )
    effective_candidates = {
        status.candidate_fingerprint
        for status in status_projection.skills
        if status.effective and status.primary
    }
    if effective_candidates != {
        summary.candidate_fingerprint for summary in effective_projection.skills
    }:
        raise SkillCatalogConsumerError(
            "Skill status and effective projections do not select the same Skills"
        )
    return status_projection.skills


def _validate_loaded_resource(
    summary: SkillCatalogSummary,
    handle: ResourceLoadHandle,
    loaded: LoadedResource,
) -> None:
    receipt = loaded.receipt
    if (
        receipt.catalog_generation != handle.catalog_generation
        or receipt.snapshot_fingerprint != handle.snapshot_fingerprint
        or receipt.candidate_fingerprint != handle.candidate_fingerprint
        or receipt.source_generation_ref != handle.source_generation_ref
        or receipt.schema_id != handle.schema_id
        or receipt.schema_version != handle.schema_version
        or receipt.media_type != handle.media_type
        or receipt.content_digest != handle.expected_content_digest
        or receipt.content_length != handle.expected_content_length
    ):
        raise SkillCatalogConsumerError(
            "Loaded Resource receipt does not match the owner-minted Skill handle"
        )
    if (
        receipt.content_digest != summary.expected_content_digest
        or receipt.content_length != summary.expected_content_length
    ):
        raise SkillCatalogConsumerError(
            "Loaded Resource receipt does not match the selected Skill body"
        )


__all__ = [
    "LoadedSkillBody",
    "EffectiveSkillCatalogProjection",
    "SkillCatalogConsumer",
    "SkillCatalogConsumerError",
    "SkillCatalogLoadHandle",
    "SkillCatalogSummary",
    "build_effective_skill_catalog_projection",
]
