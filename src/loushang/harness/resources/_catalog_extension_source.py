"""Exact-generation Resource snapshot retained by the Extension owner.

This private RCP4 adapter does not run hooks or publish Extension state.  The
Extension owner supplies one already-routed pass of neutral descriptor output;
the adapter freezes its provenance and body bytes so the Resource owner can use
the same Catalog ingress and load receipt path as mounted source components.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._catalog_projection import (
    ResourceProjectionDescriptorBinding,
    build_resource_projection_binding,
)
from loushang.harness.resources._catalog_records import (
    NO_BODY_MEDIA_TYPE,
    ExtensionOutputOrigin,
    ExtensionOwnerProducer,
    ResourceBodyRead,
    ResourceCandidateSummary,
    ResourceCatalogDiagnostic,
    ResourceIdentity,
    ResourceInvocationPolicy,
    ResourceLoadHandle,
    ResourceSourceGenerationRef,
    ResourceSourceSnapshot,
    build_candidate_summary,
    build_source_snapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceSourceKind,
    SkillDescriptor,
    ThemeDescriptor,
)

ExtensionResourceDescriptor: TypeAlias = (
    PromptFragmentDescriptor | SkillDescriptor | ExtensionDescriptor | ThemeDescriptor
)
_MAX_METADATA_DEPTH = 16
_MAX_METADATA_CONTAINER_ITEMS = 1024


class ExtensionResourceSourceError(RuntimeError):
    """Stable failure raised while freezing or reading Extension output."""

    def __init__(self, *, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True, slots=True)
class ExtensionResourceRouteContribution:
    """One routed hook result with owner-supplied, non-launderable source facts."""

    extension_id: str
    route_id: str
    source_class: ResourceSourceKind
    scope_id: str
    source_root_order: int
    route_order: int
    prompt_descriptors: tuple[PromptFragmentDescriptor, ...] = ()
    skills: tuple[SkillDescriptor, ...] = ()
    skill_bodies: tuple[bytes | None, ...] = ()
    extensions: tuple[ExtensionDescriptor, ...] = ()
    prompts: tuple[PromptFragmentDescriptor, ...] = ()
    themes: tuple[ThemeDescriptor, ...] = ()
    diagnostics: tuple[DiagnosticDraft, ...] = ()

    def __post_init__(self) -> None:
        if not self.extension_id:
            raise ValueError("Extension Resource contribution id must not be empty")
        if not self.route_id:
            raise ValueError("Extension Resource route id must not be empty")
        if self.source_class not in {
            "built_in",
            "external_package",
            "project_local",
            "temporary",
            "user_global",
        }:
            raise ValueError("Extension Resource source class is unsupported")
        if not self.scope_id:
            raise ValueError("Extension Resource scope id must not be empty")
        if (
            isinstance(self.source_root_order, bool)
            or not isinstance(self.source_root_order, int)
            or self.source_root_order < 0
        ):
            raise ValueError("Extension Resource root order must be non-negative")
        if (
            isinstance(self.route_order, bool)
            or not isinstance(self.route_order, int)
            or self.route_order < 0
        ):
            raise ValueError("Extension Resource route order must be non-negative")
        typed_groups = (
            (self.prompt_descriptors, PromptFragmentDescriptor),
            (self.skills, SkillDescriptor),
            (self.extensions, ExtensionDescriptor),
            (self.prompts, PromptFragmentDescriptor),
            (self.themes, ThemeDescriptor),
            (self.diagnostics, DiagnosticDraft),
        )
        if any(
            not isinstance(item, expected)
            for values, expected in typed_groups
            for item in values
        ):
            raise TypeError("Extension Resource contribution contains an invalid value")
        if len(self.skill_bodies) != len(self.skills):
            raise ValueError(
                "Extension Resource Skill descriptors and bodies must align"
            )
        if any(body is not None and not isinstance(body, bytes) for body in self.skill_bodies):
            raise TypeError("Extension Resource Skill bodies must use bytes")
        if any(skill.content is not None for skill in self.skills):
            raise ValueError(
                "Extension Resource Catalog Skill descriptors must be body-free"
            )
        if any("body" in skill.metadata for skill in self.skills):
            raise ValueError(
                "Extension Resource Catalog Skill metadata must be body-free"
            )


ExtensionResourceDescriptorBinding: TypeAlias = ResourceProjectionDescriptorBinding


@dataclass(frozen=True, slots=True)
class _RetainedExtensionBody:
    candidate_fingerprint: str
    content_digest: str
    body: bytes


class ExtensionResourceSourceGeneration:
    """Extension-owned snapshot plus immutable body reads for one generation."""

    def __init__(
        self,
        *,
        source_snapshot: ResourceSourceSnapshot,
        retained_bodies: Mapping[str, _RetainedExtensionBody],
        descriptor_bindings: tuple[ExtensionResourceDescriptorBinding, ...],
    ) -> None:
        self._source_snapshot = source_snapshot
        self._retained_bodies = dict(retained_bodies)
        self._descriptor_bindings = descriptor_bindings
        self._borrow_count = 0
        self._retiring = False
        self._disposed = False

    @property
    def source_generation_ref(self) -> ResourceSourceGenerationRef:
        return self._source_snapshot.source_generation_ref

    @property
    def source_snapshot(self) -> ResourceSourceSnapshot:
        if self._disposed:
            self._raise_stale("source_disposed")
        return self._source_snapshot

    @property
    def descriptor_bindings(self) -> tuple[ExtensionResourceDescriptorBinding, ...]:
        if self._disposed:
            self._raise_stale("source_disposed")
        return self._descriptor_bindings

    @property
    def projection_bindings(
        self,
    ) -> tuple[ResourceProjectionDescriptorBinding, ...]:
        return self.descriptor_bindings

    @property
    def is_disposed(self) -> bool:
        return self._disposed

    @property
    def is_retiring(self) -> bool:
        return self._retiring and not self._disposed

    def borrow(self) -> ExtensionResourceSourceLease:
        """Mint one exact lease that can drain after owner retirement starts."""

        if self._disposed:
            self._raise_stale("source_disposed")
        if self._retiring:
            self._raise_stale("source_retiring")
        self._borrow_count += 1
        return ExtensionResourceSourceLease(self)

    def load(self, handle: ResourceLoadHandle) -> ResourceBodyRead:
        if self._disposed:
            self._raise_stale("source_disposed")
        if self._retiring:
            self._raise_stale("source_retiring")
        return self._load_retained(handle)

    def _load_borrowed(
        self,
        lease: ExtensionResourceSourceLease,
        handle: ResourceLoadHandle,
    ) -> ResourceBodyRead:
        if lease._owner is not self or lease.is_released:
            self._raise_stale("source_lease_released")
        if self._disposed:
            self._raise_stale("source_disposed")
        return self._load_retained(handle)

    def _load_retained(self, handle: ResourceLoadHandle) -> ResourceBodyRead:
        if not isinstance(handle, ResourceLoadHandle):
            raise TypeError("Extension Resource load requires a ResourceLoadHandle")
        if handle.source_generation_ref != self.source_generation_ref:
            self._raise_stale("foreign_source_generation")
        retained = self._retained_bodies.get(handle.opaque_locator)
        if retained is None:
            raise ExtensionResourceSourceError(
                code="resource_body_read_failed",
                reason="unknown_opaque_locator",
            )
        if (
            retained.candidate_fingerprint != handle.candidate_fingerprint
            or retained.content_digest != handle.expected_content_digest
            or len(retained.body) != handle.expected_content_length
        ):
            raise ExtensionResourceSourceError(
                code="resource_body_identity_mismatch",
                reason="load_handle_identity_mismatch",
            )
        return ResourceBodyRead(
            source_generation_ref=self.source_generation_ref,
            opaque_locator=handle.opaque_locator,
            body=retained.body,
            observed_content_digest=retained.content_digest,
            observed_content_length=len(retained.body),
        )

    def dispose(self) -> None:
        if self._disposed or self._retiring:
            return
        self._retiring = True
        self._finalize_if_drained()

    def _release_borrow(self, lease: ExtensionResourceSourceLease) -> None:
        if lease._owner is not self:
            raise ValueError("Extension Resource lease belongs to another generation")
        if self._borrow_count < 1:
            raise RuntimeError("Extension Resource borrow accounting is corrupt")
        self._borrow_count -= 1
        self._finalize_if_drained()

    def _finalize_if_drained(self) -> None:
        if not self._retiring or self._borrow_count:
            return
        self._retained_bodies.clear()
        self._descriptor_bindings = ()
        self._retiring = False
        self._disposed = True

    @staticmethod
    def _raise_stale(reason: str) -> None:
        raise ExtensionResourceSourceError(
            code="resource_body_read_failed",
            reason=reason,
        )


class ExtensionResourceSourceLease:
    """One releasable Resource-owner borrow of an Extension source generation."""

    def __init__(self, owner: ExtensionResourceSourceGeneration) -> None:
        self._owner = owner
        self._ownership = "offered"

    @property
    def source_generation_ref(self) -> ResourceSourceGenerationRef:
        self._require_active()
        return self._owner.source_generation_ref

    @property
    def source_snapshot(self) -> ResourceSourceSnapshot:
        self._require_active()
        return self._owner.source_snapshot

    @property
    def projection_bindings(
        self,
    ) -> tuple[ResourceProjectionDescriptorBinding, ...]:
        self._require_active()
        return self._owner.projection_bindings

    @property
    def is_released(self) -> bool:
        return self._ownership == "released"

    @property
    def ownership_state(self) -> str:
        return self._ownership

    def load(self, handle: ResourceLoadHandle) -> ResourceBodyRead:
        self._require_active()
        if self._ownership != "borrowed":
            raise ExtensionResourceSourceError(
                code="resource_body_read_failed",
                reason="source_lease_not_claimed",
            )
        return self._owner._load_borrowed(self, handle)

    def claim(self) -> None:
        if self._ownership != "offered":
            raise ExtensionResourceSourceError(
                code="resource_body_read_failed",
                reason="source_lease_not_offered",
            )
        self._ownership = "borrowed"

    def release(self) -> None:
        if self.is_released:
            return
        self._ownership = "released"
        self._owner._release_borrow(self)

    def _require_active(self) -> None:
        if self.is_released:
            raise ExtensionResourceSourceError(
                code="resource_body_read_failed",
                reason="source_lease_released",
            )


def freeze_extension_resource_source_generation(
    *,
    product_id: str,
    runtime_id: str,
    extension_generation: int,
    extension_set_fingerprint: str,
    route_contributions: tuple[ExtensionResourceRouteContribution, ...],
) -> ExtensionResourceSourceGeneration:
    """Normalize one non-recursive Extension hook pass without publishing it."""

    if not product_id:
        raise ValueError("Extension Resource Product id must not be empty")
    if not runtime_id:
        raise ValueError("Extension Resource runtime id must not be empty")
    if (
        isinstance(extension_generation, bool)
        or not isinstance(extension_generation, int)
        or extension_generation < 1
    ):
        raise ValueError("Extension Resource generation must be positive")
    _require_digest(extension_set_fingerprint, name="Extension set fingerprint")
    if any(
        not isinstance(item, ExtensionResourceRouteContribution)
        for item in route_contributions
    ):
        raise TypeError("Extension Resource routes must be typed contributions")
    route_keys = tuple(
        (item.extension_id, item.route_id) for item in route_contributions
    )
    if len(set(route_keys)) != len(route_keys):
        raise ExtensionResourceSourceError(
            code="resource_source_snapshot_invalid",
            reason="duplicate_extension_route",
        )
    route_orders = tuple(item.route_order for item in route_contributions)
    if set(route_orders) != set(range(len(route_contributions))):
        raise ExtensionResourceSourceError(
            code="resource_source_snapshot_invalid",
            reason="extension_route_order_invalid",
        )

    canonical_routes = tuple(
        sorted(
            route_contributions,
            key=lambda item: (item.route_order, item.extension_id, item.route_id),
        )
    )
    route_set_fingerprint = fingerprint_catalog_value(
        "loushang.extension-resource-route-set/v1",
        [_route_fingerprint_payload(item) for item in canonical_routes],
    )
    output_records = tuple(
        record for route in canonical_routes for record in _descriptor_records(route)
    )
    hook_snapshot_fingerprint = fingerprint_catalog_value(
        "loushang.extension-resource-hook-snapshot/v1",
        {
            "extensionGeneration": extension_generation,
            "extensionSetFingerprint": extension_set_fingerprint,
            "outputs": [record.fingerprint_payload for record in output_records],
            "routeDiagnostics": [
                {
                    "code": diagnostic.code,
                    "extensionId": route.extension_id,
                    "routeId": route.route_id,
                }
                for route in canonical_routes
                for diagnostic in route.diagnostics
            ],
            "routeSetFingerprint": route_set_fingerprint,
            "runtimeId": runtime_id,
        },
    )
    generation_ref = str(extension_generation)
    extension_owner_fingerprint = fingerprint_catalog_value(
        "loushang.extension-resource-owner/v1",
        {
            "extensionGeneration": generation_ref,
            "extensionSetFingerprint": extension_set_fingerprint,
            "routeSetFingerprint": route_set_fingerprint,
            "runtimeId": runtime_id,
        },
    )
    source_ref = ResourceSourceGenerationRef(
        source_id="harness.extensions.resources",
        product_id=product_id,
        generation=generation_ref,
        source_policy_fingerprint=fingerprint_catalog_value(
            "loushang.extension-resource-source-policy/v1",
            {
                "extensionOwnerFingerprint": extension_owner_fingerprint,
                "hookSnapshotFingerprint": hook_snapshot_fingerprint,
                "productId": product_id,
                "routeSetFingerprint": route_set_fingerprint,
            },
        ),
        producer=ExtensionOwnerProducer(
            runtime_id=runtime_id,
            extension_generation=generation_ref,
            extension_set_fingerprint=extension_set_fingerprint,
            extension_owner_fingerprint=extension_owner_fingerprint,
        ),
    )
    discovery_request_fingerprint = fingerprint_catalog_value(
        "loushang.extension-resource-discovery-request/v1",
        {
            "hookSnapshotFingerprint": hook_snapshot_fingerprint,
            "sourceGenerationRef": source_ref.to_payload(),
        },
    )

    candidates: list[ResourceCandidateSummary] = []
    bodies: dict[str, _RetainedExtensionBody] = {}
    bindings: list[ExtensionResourceDescriptorBinding] = []
    for record in output_records:
        candidate = _build_candidate(
            record,
            source_ref=source_ref,
            route_set_fingerprint=route_set_fingerprint,
            hook_snapshot_fingerprint=hook_snapshot_fingerprint,
            discovery_request_fingerprint=discovery_request_fingerprint,
        )
        if candidate.opaque_locator in bodies:
            raise ExtensionResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="duplicate_opaque_locator",
            )
        candidates.append(candidate)
        bindings.append(
            build_resource_projection_binding(
                candidate=candidate,
                descriptor=record.descriptor,
                body=record.body,
            )
        )
        if record.body is not None:
            digest = hashlib.sha256(record.body).hexdigest()
            bodies[candidate.opaque_locator] = _RetainedExtensionBody(
                candidate_fingerprint=candidate.candidate_fingerprint,
                content_digest=digest,
                body=bytes(record.body),
            )

    source_diagnostics = tuple(
        ResourceCatalogDiagnostic(
            code=diagnostic.code,
            reason="extension_hook_diagnostic",
            source_id=source_ref.source_id,
            details=(
                ("extensionId", route.extension_id),
                ("routeId", route.route_id),
            ),
        )
        for route in canonical_routes
        for diagnostic in route.diagnostics
    )
    try:
        snapshot = build_source_snapshot(
            source_generation_ref=source_ref,
            discovery_request_fingerprint=discovery_request_fingerprint,
            candidate_summaries=candidates,
            diagnostics=source_diagnostics,
        )
    except (TypeError, ValueError) as exc:
        raise ExtensionResourceSourceError(
            code="resource_source_snapshot_invalid",
            reason="snapshot_validation_failed",
        ) from exc
    return ExtensionResourceSourceGeneration(
        source_snapshot=snapshot,
        retained_bodies=bodies,
        descriptor_bindings=tuple(
            sorted(bindings, key=lambda item: item.candidate_fingerprint)
        ),
    )


@dataclass(frozen=True, slots=True)
class _DescriptorRecord:
    route: ExtensionResourceRouteContribution
    resource_kind: str
    contribution_slot: str
    contribution_index: int
    descriptor: ExtensionResourceDescriptor
    body: bytes | None
    fingerprint_payload: dict[str, object]


def _descriptor_records(
    route: ExtensionResourceRouteContribution,
) -> tuple[_DescriptorRecord, ...]:
    groups: tuple[tuple[str, str, tuple[ExtensionResourceDescriptor, ...]], ...] = (
        ("prompt", "prompt_descriptors", route.prompt_descriptors),
        ("skill", "skills", route.skills),
        ("extension", "extensions", route.extensions),
        ("prompt", "prompts", route.prompts),
        ("theme", "themes", route.themes),
    )
    records = []
    for resource_kind, slot, descriptors in groups:
        for index, descriptor in enumerate(descriptors):
            descriptor = _replace_descriptor_metadata(
                descriptor,
                _freeze_metadata(descriptor.metadata),
            )
            _validate_descriptor_source_facts(route, descriptor)
            body = _descriptor_body(
                route,
                resource_kind,
                slot,
                index,
                descriptor,
            )
            records.append(
                _DescriptorRecord(
                    route=route,
                    resource_kind=resource_kind,
                    contribution_slot=slot,
                    contribution_index=index,
                    descriptor=descriptor,
                    body=body,
                    fingerprint_payload=_descriptor_fingerprint_payload(
                        route=route,
                        resource_kind=resource_kind,
                        slot=slot,
                        index=index,
                        descriptor=descriptor,
                        body=body,
                    ),
                )
            )
    return tuple(records)


def _build_candidate(
    record: _DescriptorRecord,
    *,
    source_ref: ResourceSourceGenerationRef,
    route_set_fingerprint: str,
    hook_snapshot_fingerprint: str,
    discovery_request_fingerprint: str,
) -> ResourceCandidateSummary:
    descriptor = record.descriptor
    identity = ResourceIdentity(
        resource_kind=record.resource_kind,
        schema_id=f"loushang.resource.{record.resource_kind}",
        schema_version=1,
        public_id=descriptor.id or descriptor.name,
    )
    body_digest = (
        hashlib.sha256(record.body).hexdigest() if record.body is not None else None
    )
    body_length = len(record.body) if record.body is not None else None
    locator = "extension-output/" + fingerprint_catalog_value(
        "loushang.extension-resource-locator/v1",
        {
            "contributionIndex": record.contribution_index,
            "contributionSlot": record.contribution_slot,
            "hookSnapshotFingerprint": hook_snapshot_fingerprint,
            "identity": identity.to_payload(),
            "routeId": record.route.route_id,
        },
    )
    diagnostics = tuple(
        ResourceCatalogDiagnostic(
            code=diagnostic.code,
            reason="extension_descriptor_diagnostic",
            identity=identity,
            source_id=source_ref.source_id,
        )
        for diagnostic in descriptor.diagnostics
    )
    return build_candidate_summary(
        identity=identity,
        canonical_name=descriptor.canonical_name or descriptor.name,
        description=getattr(descriptor, "description", None),
        media_type=(
            NO_BODY_MEDIA_TYPE
            if record.body is None
            else "application/json"
            if record.resource_kind == "theme"
            else "text/markdown"
        ),
        invocation_policy=ResourceInvocationPolicy(
            enabled=descriptor.enabled,
            model_invocable=(
                record.resource_kind in {"prompt", "skill"}
                and not (
                    isinstance(descriptor, SkillDescriptor)
                    and descriptor.disable_model_invocation
                )
            ),
            reason="extension_generation_snapshot",
        ),
        source_generation_ref=source_ref,
        source_class=record.route.source_class,
        scope_id=record.route.scope_id,
        source_root_order=record.route.source_root_order,
        content_origin=ExtensionOutputOrigin(
            extension_generation_ref=source_ref.generation,
            extension_id=record.route.extension_id,
            route_id=record.route.route_id,
            route_set_fingerprint=route_set_fingerprint,
            hook_snapshot_fingerprint=hook_snapshot_fingerprint,
        ),
        opaque_locator=locator,
        discovery_fingerprint=fingerprint_catalog_value(
            "loushang.extension-resource-discovery/v1",
            {
                "discoveryRequestFingerprint": discovery_request_fingerprint,
                "output": record.fingerprint_payload,
                "sourceGenerationRef": source_ref.to_payload(),
            },
        ),
        expected_content_digest=body_digest,
        expected_content_length=body_length,
        diagnostics=diagnostics,
    )


def _validate_descriptor_source_facts(
    route: ExtensionResourceRouteContribution,
    descriptor: ExtensionResourceDescriptor,
) -> None:
    if (
        descriptor.source_kind != route.source_class
        or descriptor.source_scope != route.scope_id
        or descriptor.source_root_order != route.source_root_order
    ):
        raise ExtensionResourceSourceError(
            code="resource_source_snapshot_invalid",
            reason="extension_source_facts_mismatch",
        )


def _descriptor_body(
    route: ExtensionResourceRouteContribution,
    resource_kind: str,
    slot: str,
    index: int,
    descriptor: ExtensionResourceDescriptor,
) -> bytes | None:
    if isinstance(descriptor, PromptFragmentDescriptor):
        return descriptor.text.encode("utf-8")
    if isinstance(descriptor, SkillDescriptor):
        if slot != "skills":
            raise ExtensionResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="extension_skill_body_slot_invalid",
            )
        body = route.skill_bodies[index]
        if body is None:
            raise ExtensionResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="extension_body_identity_missing",
            )
        return body
    if isinstance(descriptor, ThemeDescriptor) and descriptor.content is not None:
        return descriptor.content.encode("utf-8")
    if resource_kind not in {"extension", "theme"}:
        raise ExtensionResourceSourceError(
            code="resource_source_snapshot_invalid",
            reason="extension_body_identity_missing",
        )
    return None


def _route_fingerprint_payload(
    route: ExtensionResourceRouteContribution,
) -> dict[str, object]:
    return {
        "extensionId": route.extension_id,
        "routeId": route.route_id,
        "routeOrder": route.route_order,
        "scopeId": route.scope_id,
        "sourceClass": route.source_class,
        "sourceRootOrder": route.source_root_order,
    }


def _descriptor_fingerprint_payload(
    *,
    route: ExtensionResourceRouteContribution,
    resource_kind: str,
    slot: str,
    index: int,
    descriptor: ExtensionResourceDescriptor,
    body: bytes | None,
) -> dict[str, object]:
    return {
        "bodyDigest": hashlib.sha256(body).hexdigest() if body is not None else None,
        "bodyLength": len(body) if body is not None else None,
        "canonicalName": descriptor.canonical_name or descriptor.name,
        "contributionIndex": index,
        "contributionSlot": slot,
        "declaredId": descriptor.declared_id,
        "description": getattr(descriptor, "description", None),
        "diagnosticCodes": sorted(item.code for item in descriptor.diagnostics),
        "enabled": descriptor.enabled,
        "extensionId": route.extension_id,
        "metadata": _canonical_metadata(descriptor.metadata),
        "name": descriptor.name,
        "resourceKind": resource_kind,
        "routeId": route.route_id,
        "routeOrder": route.route_order,
        "scopeId": route.scope_id,
        "sourceClass": route.source_class,
        "sourcePathFingerprint": fingerprint_catalog_value(
            "loushang.extension-resource-source-path/v1",
            {"path": descriptor.source_path.as_posix()},
        ),
        "sourceRootOrder": route.source_root_order,
        "typeFacts": _descriptor_type_facts(descriptor),
    }


def _descriptor_type_facts(
    descriptor: ExtensionResourceDescriptor,
) -> dict[str, object]:
    if isinstance(descriptor, PromptFragmentDescriptor):
        return {
            "argumentHint": descriptor.argument_hint,
            "promptKind": descriptor.prompt_kind,
        }
    if isinstance(descriptor, SkillDescriptor):
        return {"disableModelInvocation": descriptor.disable_model_invocation}
    if isinstance(descriptor, ExtensionDescriptor):
        return {
            "entryPathFingerprint": (
                fingerprint_catalog_value(
                    "loushang.extension-resource-entry-path/v1",
                    {"path": descriptor.entry_path.as_posix()},
                )
                if descriptor.entry_path is not None
                else None
            )
        }
    return {}


def _canonical_metadata(value: object) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ExtensionResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="extension_metadata_not_canonical",
            )
        return value
    if isinstance(value, Path):
        return {
            "pathFingerprint": fingerprint_catalog_value(
                "loushang.extension-resource-metadata-path/v1",
                {"path": value.as_posix()},
            )
        }
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ExtensionResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="extension_metadata_not_canonical",
            )
        return {key: _canonical_metadata(item) for key, item in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_canonical_metadata(item) for item in value]
    raise ExtensionResourceSourceError(
        code="resource_source_snapshot_invalid",
        reason="extension_metadata_not_canonical",
    )


def _freeze_metadata(
    value: object,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> object:
    if depth > _MAX_METADATA_DEPTH:
        raise ExtensionResourceSourceError(
            code="resource_source_snapshot_invalid",
            reason="extension_metadata_budget_exceeded",
        )
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ExtensionResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="extension_metadata_not_canonical",
            )
        return value
    if isinstance(value, Path):
        return value
    if isinstance(value, Mapping | list | tuple):
        if len(value) > _MAX_METADATA_CONTAINER_ITEMS:
            raise ExtensionResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="extension_metadata_budget_exceeded",
            )
        active = seen if seen is not None else set()
        identity = id(value)
        if identity in active:
            raise ExtensionResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="extension_metadata_not_canonical",
            )
        active.add(identity)
        try:
            if isinstance(value, Mapping):
                if not all(isinstance(key, str) for key in value):
                    raise ExtensionResourceSourceError(
                        code="resource_source_snapshot_invalid",
                        reason="extension_metadata_not_canonical",
                    )
                return MappingProxyType(
                    {
                        key: _freeze_metadata(
                            item,
                            depth=depth + 1,
                            seen=active,
                        )
                        for key, item in sorted(value.items())
                    }
                )
            return tuple(
                _freeze_metadata(item, depth=depth + 1, seen=active) for item in value
            )
        finally:
            active.remove(identity)
    raise ExtensionResourceSourceError(
        code="resource_source_snapshot_invalid",
        reason="extension_metadata_not_canonical",
    )


def _replace_descriptor_metadata(
    descriptor: ExtensionResourceDescriptor,
    metadata: object,
) -> ExtensionResourceDescriptor:
    if not isinstance(metadata, Mapping):
        raise TypeError("Extension Resource descriptor metadata must be a mapping")
    return replace(descriptor, metadata=metadata)


def _require_digest(value: str, *, name: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a SHA-256 digest")


__all__ = [
    "ExtensionResourceDescriptorBinding",
    "ExtensionResourceRouteContribution",
    "ExtensionResourceSourceError",
    "ExtensionResourceSourceGeneration",
    "ExtensionResourceSourceLease",
    "freeze_extension_resource_source_generation",
]
