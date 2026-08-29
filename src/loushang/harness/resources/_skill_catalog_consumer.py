"""Exact-generation typed Skill projection over the Resource Catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._catalog_records import (
    LoadedResource,
    ResourceCatalogSnapshot,
    ResourceIdentity,
    ResourceLoadHandle,
    ResourceLoadReceipt,
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
    def projection(self) -> ResourceCatalogProjection: ...

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
    metadata: Mapping[str, object]
    diagnostics: tuple[DiagnosticDraft, ...]
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

    def to_metadata_descriptor(self) -> SkillDescriptor:
        """Project a body-free legacy shape without granting body authority."""

        return SkillDescriptor(
            name=self.name,
            source_path=self.source_path,
            content=None,
            description=self.description,
            disable_model_invocation=not self.model_invocable,
            source=self.source,
            enabled=self.enabled,
            metadata=self.metadata,
            diagnostics=self.diagnostics,
            id=self.identity.public_id,
            source_kind=self.source_kind,
            source_scope=self.source_scope,
            canonical_name=self.canonical_name,
            declared_id=self.declared_id,
            source_root=self.source_root,
            source_root_order=self.source_root_order,
            revision_ref=self.revision_ref,
        )


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
        if self.body.decode("utf-8") != self.content:
            raise ValueError("Loaded Skill content does not match its bytes")


class SkillCatalogConsumer:
    """Read-only Skill view derived from one captured Resource generation."""

    def __init__(self, catalog: _ResourceCatalogLoadConsumer) -> None:
        snapshot = catalog.snapshot
        projection = catalog.projection
        if not isinstance(snapshot, ResourceCatalogSnapshot):
            raise TypeError("Skill Consumer requires a Resource Catalog snapshot")
        if not isinstance(projection, ResourceCatalogProjection):
            raise TypeError("Skill Consumer requires a Resource Catalog projection")
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
        self._skills = _project_skill_summaries(
            snapshot=snapshot,
            projection=projection,
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
        handle = self._catalog.load_handle(summary.identity)
        if handle.candidate_fingerprint != summary.candidate_fingerprint:
            raise SkillCatalogConsumerError(
                "Catalog load handle selected another Skill candidate"
            )
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
        loaded = await self._catalog.load(handle.resource_handle)
        if loaded.receipt.candidate_fingerprint != summary.candidate_fingerprint:
            raise SkillCatalogConsumerError("Loaded Resource is not the selected Skill")
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


def _project_skill_summaries(
    *,
    snapshot: ResourceCatalogSnapshot,
    projection: ResourceCatalogProjection,
) -> tuple[SkillCatalogSummary, ...]:
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
        metadata_descriptor = replace(
            descriptor,
            content=None,
            enabled=effective.enabled,
            disable_model_invocation=not effective.model_invocable,
        )
        summaries.append(
            SkillCatalogSummary(
                catalog_generation=snapshot.catalog_generation,
                catalog_snapshot_fingerprint=snapshot.snapshot_fingerprint,
                candidate_fingerprint=candidate.candidate_fingerprint,
                identity=candidate.identity,
                name=metadata_descriptor.name,
                canonical_name=(
                    metadata_descriptor.canonical_name or metadata_descriptor.name
                ),
                description=metadata_descriptor.description,
                enabled=metadata_descriptor.enabled,
                model_invocable=not metadata_descriptor.disable_model_invocation,
                media_type=candidate.media_type,
                expected_content_digest=candidate.expected_content_digest,
                expected_content_length=candidate.expected_content_length,
                source_path=metadata_descriptor.source_path,
                source_root=metadata_descriptor.source_root,
                source_kind=metadata_descriptor.source_kind,
                source_scope=metadata_descriptor.source_scope,
                source_root_order=metadata_descriptor.source_root_order,
                source=metadata_descriptor.source,
                metadata=metadata_descriptor.metadata,
                diagnostics=metadata_descriptor.diagnostics,
                declared_id=metadata_descriptor.declared_id,
                revision_ref=metadata_descriptor.revision_ref,
            )
        )
    if len(summaries) != len(effective_by_identity):
        raise SkillCatalogConsumerError(
            "Catalog Skill selection and projection do not match"
        )
    return tuple(summaries)


__all__ = [
    "LoadedSkillBody",
    "SkillCatalogConsumer",
    "SkillCatalogConsumerError",
    "SkillCatalogLoadHandle",
    "SkillCatalogSummary",
]
