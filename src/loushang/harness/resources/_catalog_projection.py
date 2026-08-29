"""Catalog-bound immutable compatibility projection for RCP4."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import NoReturn, TypeAlias, cast

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._catalog_records import (
    ResourceCandidateSummary,
    ResourceCatalogSnapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceBundle,
    ResourceSnapshot,
    SkillDescriptor,
    ThemeDescriptor,
)

ResourceProjectionDescriptor: TypeAlias = (
    PromptFragmentDescriptor | SkillDescriptor | ExtensionDescriptor | ThemeDescriptor
)
_PROJECTED_RESOURCE_KINDS = frozenset(
    {"context", "extension", "prompt", "skill", "theme"}
)
_CONTEXT_SOURCE_ORDER = {
    "user_global": 0,
    "project_local": 1,
    "temporary": 2,
    "external_package": 3,
    "built_in": 4,
}
_MAX_METADATA_DEPTH = 16
_MAX_METADATA_ITEMS = 1024


class ResourceCatalogProjectionError(RuntimeError):
    """Finite owner-visible failure while deriving a compatibility projection."""

    def __init__(self, *, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True, slots=True)
class ResourceProjectionDescriptorBinding:
    """Body-free descriptor sidecar with no effective-selection authority."""

    candidate_fingerprint: str
    resource_kind: str
    descriptor: ResourceProjectionDescriptor
    descriptor_fingerprint: str

    def __post_init__(self) -> None:
        _require_digest(self.candidate_fingerprint, name="candidate fingerprint")
        _require_digest(self.descriptor_fingerprint, name="descriptor fingerprint")
        if self.resource_kind not in _PROJECTED_RESOURCE_KINDS:
            raise ValueError("Projection descriptor kind is unsupported")
        _require_descriptor_type(self.resource_kind, self.descriptor)
        expected = _descriptor_fingerprint(
            candidate_fingerprint=self.candidate_fingerprint,
            resource_kind=self.resource_kind,
            descriptor=self.descriptor,
        )
        if self.descriptor_fingerprint != expected:
            raise ValueError("Projection descriptor fingerprint is invalid")

    def fingerprint_payload(self) -> dict[str, object]:
        return {
            "candidateFingerprint": self.candidate_fingerprint,
            "descriptorFingerprint": self.descriptor_fingerprint,
            "resourceKind": self.resource_kind,
        }


@dataclass(frozen=True, slots=True)
class ResourceCatalogProjection:
    """Immutable descriptor view derived from one exact Catalog snapshot."""

    catalog_generation: int
    catalog_snapshot_fingerprint: str
    cwd: Path
    selected_bindings: tuple[ResourceProjectionDescriptorBinding, ...]
    projection_fingerprint: str

    def __post_init__(self) -> None:
        if self.catalog_generation < 1:
            raise ValueError("Projection Catalog generation must be positive")
        _require_digest(
            self.catalog_snapshot_fingerprint,
            name="Catalog snapshot fingerprint",
        )
        if not isinstance(self.cwd, Path):
            raise TypeError("Resource projection cwd must be a Path")
        if any(
            not isinstance(item, ResourceProjectionDescriptorBinding)
            for item in self.selected_bindings
        ):
            raise TypeError("Resource projection bindings must be typed")
        selected = [item.candidate_fingerprint for item in self.selected_bindings]
        if len(set(selected)) != len(selected):
            raise ValueError("Resource projection candidates must be unique")
        _require_digest(self.projection_fingerprint, name="projection fingerprint")
        expected = _projection_fingerprint(
            catalog_generation=self.catalog_generation,
            catalog_snapshot_fingerprint=self.catalog_snapshot_fingerprint,
            cwd=self.cwd,
            selected_bindings=self.selected_bindings,
        )
        if self.projection_fingerprint != expected:
            raise ValueError("Resource projection fingerprint is invalid")

    def to_compatibility_bundle(self) -> ResourceBundle:
        """Return a fresh mutable legacy copy without granting write authority."""

        contexts: list[PromptFragmentDescriptor] = []
        prompts: list[PromptFragmentDescriptor] = []
        skills: list[SkillDescriptor] = []
        extensions: list[ExtensionDescriptor] = []
        themes: list[ThemeDescriptor] = []
        diagnostics: list[DiagnosticDraft] = []
        for binding in self.selected_bindings:
            descriptor = binding.descriptor
            diagnostics.extend(descriptor.diagnostics)
            if binding.resource_kind == "context":
                contexts.append(cast(PromptFragmentDescriptor, descriptor))
            elif binding.resource_kind == "prompt":
                prompts.append(cast(PromptFragmentDescriptor, descriptor))
            elif binding.resource_kind == "skill":
                skills.append(cast(SkillDescriptor, descriptor))
            elif binding.resource_kind == "extension":
                extensions.append(cast(ExtensionDescriptor, descriptor))
            elif binding.resource_kind == "theme":
                themes.append(cast(ThemeDescriptor, descriptor))
        return ResourceSnapshot(
            cwd=self.cwd,
            active_context_descriptors=tuple(contexts),
            active_prompt_descriptors=tuple(prompts),
            active_skill_descriptors=tuple(skills),
            active_extension_descriptors=tuple(extensions),
            active_theme_descriptors=tuple(themes),
            diagnostics=tuple(diagnostics),
        ).to_bundle()


def build_resource_projection_binding(
    *,
    candidate: ResourceCandidateSummary,
    descriptor: ResourceProjectionDescriptor,
    body: bytes | None,
) -> ResourceProjectionDescriptorBinding:
    """Freeze and bind one source descriptor to its exact candidate summary."""

    if not isinstance(candidate, ResourceCandidateSummary):
        raise TypeError("Projection binding requires a Resource candidate")
    resource_kind = candidate.identity.resource_kind
    if resource_kind not in _PROJECTED_RESOURCE_KINDS:
        raise ValueError("Candidate kind has no ResourceBundle projection")
    if body is not None and not isinstance(body, bytes):
        raise TypeError("Projection binding body identity must use bytes")
    _validate_body_identity(candidate, body)
    frozen = _freeze_descriptor(descriptor)
    _validate_descriptor_facts(candidate, frozen)
    descriptor_fingerprint = _descriptor_fingerprint(
        candidate_fingerprint=candidate.candidate_fingerprint,
        resource_kind=resource_kind,
        descriptor=frozen,
    )
    return ResourceProjectionDescriptorBinding(
        candidate_fingerprint=candidate.candidate_fingerprint,
        resource_kind=resource_kind,
        descriptor=frozen,
        descriptor_fingerprint=descriptor_fingerprint,
    )


def project_resource_catalog(
    *,
    catalog_snapshot: ResourceCatalogSnapshot,
    cwd: Path,
    descriptor_bindings: tuple[ResourceProjectionDescriptorBinding, ...],
) -> ResourceCatalogProjection:
    """Derive one immutable view exclusively from Catalog effective entries."""

    if not isinstance(catalog_snapshot, ResourceCatalogSnapshot):
        raise TypeError("Resource projection requires a Catalog snapshot")
    if not catalog_snapshot.complete:
        _raise_projection("incomplete_catalog_snapshot")
    if not isinstance(cwd, Path):
        raise TypeError("Resource projection cwd must be a Path")
    if any(
        not isinstance(item, ResourceProjectionDescriptorBinding)
        for item in descriptor_bindings
    ):
        raise TypeError("Resource projection bindings must be typed")
    binding_by_candidate: dict[str, ResourceProjectionDescriptorBinding] = {}
    for binding in descriptor_bindings:
        if binding.candidate_fingerprint in binding_by_candidate:
            _raise_projection("duplicate_descriptor_binding")
        binding_by_candidate[binding.candidate_fingerprint] = binding

    candidate_by_fingerprint = {
        candidate.candidate_fingerprint: candidate
        for candidate in catalog_snapshot.candidate_summaries
    }
    for fingerprint, binding in binding_by_candidate.items():
        candidate = candidate_by_fingerprint.get(fingerprint)
        if candidate is None:
            _raise_projection("foreign_descriptor_binding")
        _validate_descriptor_facts(candidate, binding.descriptor)
        if binding.resource_kind != candidate.identity.resource_kind:
            _raise_projection("descriptor_kind_mismatch")

    selected_by_kind: dict[str, list[ResourceProjectionDescriptorBinding]] = {
        kind: [] for kind in _PROJECTED_RESOURCE_KINDS
    }
    for entry in catalog_snapshot.effective_entries:
        if entry.identity.resource_kind not in _PROJECTED_RESOURCE_KINDS:
            continue
        for fingerprint in entry.candidate_fingerprints:
            selected_binding = binding_by_candidate.get(fingerprint)
            if selected_binding is None:
                _raise_projection("missing_effective_descriptor_binding")
            selected_by_kind[entry.identity.resource_kind].append(selected_binding)

    selected_by_kind["context"].sort(key=_context_projection_sort_key)
    selected_tuple = tuple(
        binding
        for kind in ("context", "prompt", "skill", "extension", "theme")
        for binding in selected_by_kind[kind]
    )
    return ResourceCatalogProjection(
        catalog_generation=catalog_snapshot.catalog_generation,
        catalog_snapshot_fingerprint=catalog_snapshot.snapshot_fingerprint,
        cwd=cwd,
        selected_bindings=selected_tuple,
        projection_fingerprint=_projection_fingerprint(
            catalog_generation=catalog_snapshot.catalog_generation,
            catalog_snapshot_fingerprint=catalog_snapshot.snapshot_fingerprint,
            cwd=cwd,
            selected_bindings=selected_tuple,
        ),
    )


def _validate_descriptor_facts(
    candidate: ResourceCandidateSummary,
    descriptor: ResourceProjectionDescriptor,
) -> None:
    resource_kind = candidate.identity.resource_kind
    try:
        _require_descriptor_type(resource_kind, descriptor)
    except (TypeError, ValueError) as exc:
        raise ResourceCatalogProjectionError(
            code="resource_catalog_projection_invalid",
            reason="descriptor_type_mismatch",
        ) from exc
    if (
        (descriptor.id or descriptor.name) != candidate.identity.public_id
        or (descriptor.canonical_name or descriptor.name)
        != candidate.canonical_name
        or getattr(descriptor, "description", None) != candidate.description
        or descriptor.enabled != candidate.invocation_policy.enabled
        or descriptor.source_kind != candidate.source_class
        or descriptor.source_scope != candidate.scope_id
        or descriptor.source_root_order != candidate.source_root_order
        or _descriptor_model_invocable(resource_kind, descriptor)
        != candidate.invocation_policy.model_invocable
    ):
        _raise_projection("descriptor_candidate_facts_mismatch")


def _validate_body_identity(
    candidate: ResourceCandidateSummary,
    body: bytes | None,
) -> None:
    if candidate.has_body:
        if body is None:
            _raise_projection("descriptor_body_identity_missing")
        assert candidate.expected_content_digest is not None
        assert candidate.expected_content_length is not None
        if (
            hashlib.sha256(body).hexdigest() != candidate.expected_content_digest
            or len(body) != candidate.expected_content_length
        ):
            _raise_projection("descriptor_body_identity_mismatch")
    elif body is not None:
        _raise_projection("unexpected_descriptor_body_identity")


def _require_descriptor_type(
    resource_kind: str,
    descriptor: ResourceProjectionDescriptor,
) -> None:
    expected: type[object]
    if resource_kind in {"context", "prompt"}:
        expected = PromptFragmentDescriptor
    elif resource_kind == "skill":
        expected = SkillDescriptor
    elif resource_kind == "extension":
        expected = ExtensionDescriptor
    elif resource_kind == "theme":
        expected = ThemeDescriptor
    else:
        raise ValueError("Candidate kind has no ResourceBundle projection")
    if not isinstance(descriptor, expected):
        raise TypeError("Projection descriptor type does not match Resource kind")


def _descriptor_model_invocable(
    resource_kind: str,
    descriptor: ResourceProjectionDescriptor,
) -> bool:
    if resource_kind in {"context", "prompt"}:
        return True
    if resource_kind == "skill":
        return not cast(SkillDescriptor, descriptor).disable_model_invocation
    return False


def _freeze_descriptor(
    descriptor: ResourceProjectionDescriptor,
) -> ResourceProjectionDescriptor:
    if not isinstance(
        descriptor,
        PromptFragmentDescriptor | SkillDescriptor | ExtensionDescriptor | ThemeDescriptor,
    ):
        raise TypeError("Resource projection descriptor is unsupported")
    metadata_source: Mapping[str, object] = descriptor.metadata
    if isinstance(descriptor, SkillDescriptor):
        # Parser compatibility metadata historically duplicated the parsed
        # body.  Keeping it would merely hide a second eager body authority
        # after clearing SkillDescriptor.content.
        metadata_source = {
            key: value
            for key, value in descriptor.metadata.items()
            if key != "body"
        }
    metadata = _freeze_mapping(metadata_source)
    diagnostics = tuple(_freeze_diagnostic(item) for item in descriptor.diagnostics)
    if isinstance(descriptor, SkillDescriptor):
        # A Catalog projection is a metadata compatibility view, not a second
        # Skill body store.  The source generation retains the exact bytes and
        # serves them only through an owner-minted load handle and receipt.
        return replace(
            descriptor,
            content=None,
            metadata=metadata,
            diagnostics=diagnostics,
        )
    return replace(descriptor, metadata=metadata, diagnostics=diagnostics)


def _freeze_diagnostic(diagnostic: DiagnosticDraft) -> DiagnosticDraft:
    if not isinstance(diagnostic, DiagnosticDraft):
        raise TypeError("Projection descriptor diagnostics must be typed")
    return replace(diagnostic, details=_freeze_mapping(diagnostic.details))


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("Projection descriptor metadata must be a mapping")
    frozen = _freeze_value(value, depth=0, active=set())
    if not isinstance(frozen, Mapping):  # pragma: no cover - guarded above
        raise TypeError("Projection descriptor metadata must remain a mapping")
    return frozen


def _freeze_value(
    value: object,
    *,
    depth: int,
    active: set[int],
) -> object:
    if depth > _MAX_METADATA_DEPTH:
        _raise_projection("descriptor_metadata_depth_exceeded")
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(cast(float, value)):
            _raise_projection("descriptor_metadata_not_canonical")
        return value
    if isinstance(value, Path):
        return value
    if isinstance(value, Mapping):
        marker = id(value)
        if marker in active or len(value) > _MAX_METADATA_ITEMS:
            _raise_projection("descriptor_metadata_not_canonical")
        active.add(marker)
        try:
            if any(not isinstance(key, str) for key in value):
                _raise_projection("descriptor_metadata_not_canonical")
            return MappingProxyType(
                {
                    key: _freeze_value(item, depth=depth + 1, active=active)
                    for key, item in sorted(value.items())
                }
            )
        finally:
            active.remove(marker)
    if isinstance(value, list | tuple):
        marker = id(value)
        if marker in active or len(value) > _MAX_METADATA_ITEMS:
            _raise_projection("descriptor_metadata_not_canonical")
        active.add(marker)
        try:
            return tuple(
                _freeze_value(item, depth=depth + 1, active=active) for item in value
            )
        finally:
            active.remove(marker)
    _raise_projection("descriptor_metadata_not_canonical")


def _descriptor_fingerprint(
    *,
    candidate_fingerprint: str,
    resource_kind: str,
    descriptor: ResourceProjectionDescriptor,
) -> str:
    payload: dict[str, object] = {
        "candidateFingerprint": candidate_fingerprint,
        "canonicalName": descriptor.canonical_name or descriptor.name,
        "declaredId": descriptor.declared_id,
        "description": getattr(descriptor, "description", None),
        "diagnostics": [
            {
                "code": item.code,
                "details": _canonical_value(item.details),
                "message": item.message,
                "sourcePath": (
                    item.source_path.as_posix()
                    if item.source_path is not None
                    else None
                ),
            }
            for item in descriptor.diagnostics
        ],
        "enabled": descriptor.enabled,
        "id": descriptor.id,
        "metadata": _canonical_value(descriptor.metadata),
        "name": descriptor.name,
        "resourceKind": resource_kind,
        "revisionRef": (
            {
                "contentDigest": descriptor.revision_ref.content_digest,
                "kind": descriptor.revision_ref.kind,
                "relativePath": descriptor.revision_ref.relative_path,
            }
            if descriptor.revision_ref is not None
            else None
        ),
        "source": descriptor.source,
        "sourceKind": descriptor.source_kind,
        "sourcePath": descriptor.source_path.as_posix(),
        "sourceRoot": (
            descriptor.source_root.as_posix()
            if descriptor.source_root is not None
            else None
        ),
        "sourceRootOrder": descriptor.source_root_order,
        "sourceScope": descriptor.source_scope,
    }
    if isinstance(descriptor, PromptFragmentDescriptor):
        payload["typeFacts"] = {
            "argumentHint": descriptor.argument_hint,
            "promptKind": descriptor.prompt_kind,
            "text": descriptor.text,
        }
    elif isinstance(descriptor, SkillDescriptor):
        payload["typeFacts"] = {
            "disableModelInvocation": descriptor.disable_model_invocation,
        }
    elif isinstance(descriptor, ExtensionDescriptor):
        payload["typeFacts"] = {
            "entryPath": (
                descriptor.entry_path.as_posix()
                if descriptor.entry_path is not None
                else None
            )
        }
    else:
        payload["typeFacts"] = {"content": descriptor.content}
    return fingerprint_catalog_value(
        "loushang.resource-catalog-projection-descriptor/v2",
        payload,
    )


def _context_projection_sort_key(
    binding: ResourceProjectionDescriptorBinding,
) -> tuple[object, ...]:
    descriptor = binding.descriptor
    if binding.resource_kind != "context":
        raise TypeError("Only context projections have a local ordering rule")
    return (
        _CONTEXT_SOURCE_ORDER[descriptor.source_kind],
        descriptor.source_root_order,
        descriptor.canonical_name or descriptor.name,
        binding.candidate_fingerprint,
    )


def _projection_fingerprint(
    *,
    catalog_generation: int,
    catalog_snapshot_fingerprint: str,
    cwd: Path,
    selected_bindings: tuple[ResourceProjectionDescriptorBinding, ...],
) -> str:
    return fingerprint_catalog_value(
        "loushang.resource-catalog-projection/v1",
        {
            "catalogGeneration": catalog_generation,
            "catalogSnapshotFingerprint": catalog_snapshot_fingerprint,
            "cwd": cwd.as_posix(),
            "selectedBindings": [
                item.fingerprint_payload() for item in selected_bindings
            ],
        },
    )


def _canonical_value(value: object) -> object:
    if isinstance(value, Path):
        return {"path": value.as_posix()}
    if isinstance(value, Mapping):
        return {key: _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    return value


def _require_digest(value: str, *, name: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"Resource projection {name} must be SHA-256")


def _raise_projection(reason: str) -> NoReturn:
    raise ResourceCatalogProjectionError(
        code="resource_catalog_projection_invalid",
        reason=reason,
    )


__all__ = [
    "ResourceCatalogProjection",
    "ResourceCatalogProjectionError",
    "ResourceProjectionDescriptor",
    "ResourceProjectionDescriptorBinding",
    "build_resource_projection_binding",
    "project_resource_catalog",
]
