"""Verified-package ``resource.source`` adapter for RCP3 shadow composition."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from loushang.harness.resources._catalog_projection import (
    ResourceProjectionDescriptor,
    ResourceProjectionDescriptorBinding,
    build_resource_projection_binding,
)
from loushang.harness.resources._catalog_records import (
    NO_BODY_MEDIA_TYPE,
    ResourceBodyRead,
    ResourceCandidateSummary,
    ResourceCatalogDiagnostic,
    ResourceComponentProducer,
    ResourceIdentity,
    ResourceInvocationPolicy,
    ResourceLoadHandle,
    ResourceSourceGenerationRef,
    ResourceSourceSnapshot,
    VerifiedPluginResourceOrigin,
    build_candidate_summary,
    build_source_snapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources._catalog_source_contracts import (
    ResourceDiscoveryRequest,
)
from loushang.harness.resources._resource_item_projection import (
    CatalogItemProjection,
    project_catalog_item,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionError,
    VerifiedRevisionHandle,
)
from loushang.harness.resources.types import ThemeDescriptor

_RESOURCE_KINDS = frozenset({"asset", "method", "prompt", "skill", "source", "theme"})


class PackageResourceSourceError(RuntimeError):
    """Finite owner-visible failure from the admitted-package source."""

    def __init__(self, *, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True, slots=True)
class VerifiedPackageResourceInput:
    """Capability-neutral exact admission evidence plus one owned revision lease."""

    product_id: str
    resource_contribution_id: str
    resource_admission_fingerprint: str
    plugin_instance_revision_ref: str
    package_content_digest: str
    resource_kind: str
    locator: str
    locator_kind: str
    media_type: str
    schema_id: str
    schema_version: int
    revision_handle: VerifiedRevisionHandle = field(repr=False, compare=False)
    source_root_order: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("Package Resource Product id", self.product_id),
            ("Package Resource contribution id", self.resource_contribution_id),
            ("Package Resource instance revision", self.plugin_instance_revision_ref),
            ("Package Resource media type", self.media_type),
            ("Package Resource schema id", self.schema_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        for name, value in (
            ("Package Resource admission", self.resource_admission_fingerprint),
            ("Package content", self.package_content_digest),
        ):
            if len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise ValueError(f"{name} fingerprint must be SHA-256")
        if self.resource_kind not in _RESOURCE_KINDS:
            raise ValueError("Package Resource kind is unsupported")
        if self.locator_kind not in {"directory", "file"}:
            raise ValueError("Package Resource locator kind is unsupported")
        locator = canonical_plugin_relative_path(self.locator)
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version < 1
        ):
            raise ValueError("Package Resource schema version must be positive")
        if not isinstance(self.revision_handle, VerifiedRevisionHandle):
            raise TypeError("Package Resource requires a verified revision handle")
        if self.revision_handle.closed:
            raise ValueError("Package Resource revision handle must be live")
        if self.package_content_digest != self.revision_handle.content_digest:
            raise ValueError("Package Resource admission must match its revision")
        if isinstance(self.source_root_order, bool) or not isinstance(
            self.source_root_order, int
        ):
            raise TypeError("Package Resource root order must be an integer")
        if self.source_root_order < 0:
            raise ValueError("Package Resource root order cannot be negative")
        object.__setattr__(self, "locator", locator.as_posix())

    def policy_payload(self) -> dict[str, object]:
        return {
            "admissionFingerprint": self.resource_admission_fingerprint,
            "contributionId": self.resource_contribution_id,
            "instanceRevisionRef": self.plugin_instance_revision_ref,
            "locator": self.locator,
            "locatorKind": self.locator_kind,
            "packageContentDigest": self.package_content_digest,
            "sourceRootOrder": self.source_root_order,
        }


def acquire_verified_package_resource_input(
    *,
    revision_handle: VerifiedRevisionHandle,
    product_id: str,
    resource_contribution_id: str,
    resource_admission_fingerprint: str,
    plugin_instance_revision_ref: str,
    resource_kind: str,
    locator: str,
    locator_kind: str,
    media_type: str,
    schema_id: str,
    schema_version: int,
    source_root_order: int,
) -> VerifiedPackageResourceInput:
    """Acquire the source-owned revision lease without consuming package custody."""

    owned_handle = revision_handle.acquire()
    try:
        return VerifiedPackageResourceInput(
            product_id=product_id,
            resource_contribution_id=resource_contribution_id,
            resource_admission_fingerprint=resource_admission_fingerprint,
            plugin_instance_revision_ref=plugin_instance_revision_ref,
            package_content_digest=revision_handle.content_digest,
            resource_kind=resource_kind,
            locator=locator,
            locator_kind=locator_kind,
            media_type=media_type,
            schema_id=schema_id,
            schema_version=schema_version,
            revision_handle=owned_handle,
            source_root_order=source_root_order,
        )
    except Exception:
        owned_handle.close()
        raise


@dataclass(frozen=True, slots=True)
class PackageResourceDiscoveryBudget:
    maximum_items: int = 1024
    maximum_metadata_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        for name, value in (
            ("items", self.maximum_items),
            ("metadata bytes", self.maximum_metadata_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Package discovery {name} must be an integer")
            if value < 1:
                raise ValueError(f"Package discovery {name} must be positive")

    def to_payload(self) -> dict[str, int]:
        return {
            "maximumItems": self.maximum_items,
            "maximumMetadataBytes": self.maximum_metadata_bytes,
        }


@dataclass(frozen=True, slots=True)
class PackageResourceDiscoveryRequest:
    product_id: str
    source_generation_ref: ResourceSourceGenerationRef
    admission_fingerprints: tuple[str, ...]
    budget: PackageResourceDiscoveryBudget
    request_fingerprint: str
    deadline_monotonic_ns: int | None = field(default=None, repr=False, compare=False)
    cancellation_probe: Callable[[], bool] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.product_id.strip():
            raise ValueError("Package discovery Product id must not be empty")
        if not isinstance(self.source_generation_ref, ResourceSourceGenerationRef):
            raise TypeError("Package discovery requires a source generation ref")
        if (
            tuple(sorted(set(self.admission_fingerprints)))
            != self.admission_fingerprints
        ):
            raise ValueError("Package discovery admissions must be canonical")
        if not isinstance(self.budget, PackageResourceDiscoveryBudget):
            raise TypeError("Package discovery requires a typed budget")
        expected = _request_fingerprint(
            product_id=self.product_id,
            source_generation_ref=self.source_generation_ref,
            admission_fingerprints=self.admission_fingerprints,
            budget=self.budget,
        )
        if self.request_fingerprint != expected:
            raise ValueError("Package discovery request fingerprint is invalid")
        if self.deadline_monotonic_ns is not None and (
            isinstance(self.deadline_monotonic_ns, bool)
            or not isinstance(self.deadline_monotonic_ns, int)
            or self.deadline_monotonic_ns < 0
        ):
            raise ValueError("Package discovery deadline must be monotonic nanoseconds")
        if self.cancellation_probe is not None and not callable(
            self.cancellation_probe
        ):
            raise TypeError("Package discovery cancellation probe must be callable")


def build_package_resource_discovery_request(
    *,
    product_id: str,
    source_generation_ref: ResourceSourceGenerationRef,
    admission_fingerprints: tuple[str, ...],
    budget: PackageResourceDiscoveryBudget | None = None,
    deadline_monotonic_ns: int | None = None,
    cancellation_probe: Callable[[], bool] | None = None,
) -> PackageResourceDiscoveryRequest:
    effective_budget = budget or PackageResourceDiscoveryBudget()
    canonical = tuple(sorted(set(admission_fingerprints)))
    return PackageResourceDiscoveryRequest(
        product_id=product_id,
        source_generation_ref=source_generation_ref,
        admission_fingerprints=canonical,
        budget=effective_budget,
        request_fingerprint=_request_fingerprint(
            product_id=product_id,
            source_generation_ref=source_generation_ref,
            admission_fingerprints=canonical,
            budget=effective_budget,
        ),
        deadline_monotonic_ns=deadline_monotonic_ns,
        cancellation_probe=cancellation_probe,
    )


@dataclass(slots=True)
class _DiscoveryControl:
    request: PackageResourceDiscoveryRequest
    item_count: int = 0
    metadata_bytes: int = 0

    def check(self) -> None:
        probe = self.request.cancellation_probe
        if probe is not None and probe():
            raise asyncio.CancelledError
        deadline = self.request.deadline_monotonic_ns
        if deadline is not None and time.monotonic_ns() >= deadline:
            _raise_budget("deadline_exceeded")

    def consume_item(self) -> None:
        self.check()
        self.item_count += 1
        if self.item_count > self.request.budget.maximum_items:
            _raise_budget("item_count_exceeded")

    def reserve_metadata(self, length: int) -> None:
        self.check()
        if self.metadata_bytes + length > self.request.budget.maximum_metadata_bytes:
            _raise_budget("metadata_bytes_exceeded")
        self.metadata_bytes += length


@dataclass(frozen=True, slots=True)
class _PackageBody:
    handle: VerifiedRevisionHandle = field(repr=False, compare=False)
    relative_path: str
    candidate_fingerprint: str
    content_digest: str
    content_length: int


class AdmittedPackageResourceSource:
    """One disposable generation over owner-admitted package locators only."""

    def __init__(
        self,
        *,
        source_generation_ref: ResourceSourceGenerationRef,
        resources: tuple[VerifiedPackageResourceInput, ...],
    ) -> None:
        if not isinstance(source_generation_ref, ResourceSourceGenerationRef):
            raise TypeError("Package source requires a source generation ref")
        if any(
            not isinstance(item, VerifiedPackageResourceInput) for item in resources
        ):
            raise TypeError("Package source requires admitted Resource handles")
        ordered = tuple(
            sorted(resources, key=lambda item: item.resource_admission_fingerprint)
        )
        fingerprints = tuple(item.resource_admission_fingerprint for item in ordered)
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("Package source admissions must not repeat")
        if any(item.revision_handle.closed for item in ordered):
            raise ValueError("Package source revision handles must be live")
        if any(item.product_id != source_generation_ref.product_id for item in ordered):
            raise ValueError("Package source admissions must match the Product")
        self._source_generation_ref = source_generation_ref
        self._resources = {
            item.resource_admission_fingerprint: item for item in ordered
        }
        self._snapshot: ResourceSourceSnapshot | None = None
        self._bodies: dict[str, _PackageBody] = {}
        self._projection_bindings: tuple[
            ResourceProjectionDescriptorBinding, ...
        ] = ()
        self._disposed = False

    @property
    def source_generation_ref(self) -> ResourceSourceGenerationRef:
        return self._source_generation_ref

    @property
    def is_disposed(self) -> bool:
        return self._disposed

    @property
    def projection_bindings(
        self,
    ) -> tuple[ResourceProjectionDescriptorBinding, ...]:
        if self._disposed:
            _raise_stale("source_disposed")
        return self._projection_bindings

    def discover_initial(
        self,
        request: ResourceDiscoveryRequest,
    ) -> ResourceSourceSnapshot:
        if self._disposed:
            _raise_stale("source_disposed")
        if not isinstance(request, PackageResourceDiscoveryRequest):
            raise TypeError("Package source discovery requires a typed request")
        if (
            request.product_id != self._source_generation_ref.product_id
            or request.source_generation_ref != self._source_generation_ref
        ):
            _raise_stale("foreign_source_generation")
        expected_admissions = tuple(sorted(self._resources))
        if request.admission_fingerprints != expected_admissions:
            raise PackageResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="admission_set_mismatch",
            )
        if self._snapshot is not None:
            if (
                self._snapshot.discovery_request_fingerprint
                != request.request_fingerprint
            ):
                _raise_stale("discovery_request_changed")
            return self._snapshot

        control = _DiscoveryControl(request)
        candidates: list[ResourceCandidateSummary] = []
        diagnostics: list[ResourceCatalogDiagnostic] = []
        bodies: dict[str, _PackageBody] = {}
        projection_bindings: list[ResourceProjectionDescriptorBinding] = []
        for fingerprint in request.admission_fingerprints:
            control.consume_item()
            resource = self._resources[fingerprint]
            try:
                resource.revision_handle.verify()
                candidate, candidate_diagnostics, body, projection_binding = (
                    _discover_resource(
                        resource,
                        request=request,
                        control=control,
                        source_generation_ref=self._source_generation_ref,
                    )
                )
            except PluginRevisionError as exc:
                raise PackageResourceSourceError(
                    code="resource_source_discovery_failed",
                    reason=exc.code,
                ) from exc
            diagnostics.extend(candidate_diagnostics)
            if candidate is None:
                continue
            candidates.append(candidate)
            if projection_binding is not None:
                projection_bindings.append(projection_binding)
            if body is not None:
                if candidate.opaque_locator in bodies:
                    raise PackageResourceSourceError(
                        code="resource_source_snapshot_invalid",
                        reason="duplicate_opaque_locator",
                    )
                bodies[candidate.opaque_locator] = body
        try:
            snapshot = build_source_snapshot(
                source_generation_ref=self._source_generation_ref,
                discovery_request_fingerprint=request.request_fingerprint,
                candidate_summaries=candidates,
                diagnostics=diagnostics,
            )
        except (TypeError, ValueError) as exc:
            raise PackageResourceSourceError(
                code="resource_source_snapshot_invalid",
                reason="snapshot_validation_failed",
            ) from exc
        self._snapshot = snapshot
        self._bodies = bodies
        self._projection_bindings = tuple(
            sorted(
                projection_bindings,
                key=lambda item: item.candidate_fingerprint,
            )
        )
        return snapshot

    def load(self, handle: ResourceLoadHandle) -> ResourceBodyRead:
        if self._disposed:
            _raise_stale("source_disposed")
        if not isinstance(handle, ResourceLoadHandle):
            raise TypeError("Package source load requires a Resource load handle")
        if handle.source_generation_ref != self._source_generation_ref:
            _raise_stale("foreign_source_generation")
        body_ref = self._bodies.get(handle.opaque_locator)
        if body_ref is None:
            raise PackageResourceSourceError(
                code="resource_body_read_failed",
                reason="unknown_opaque_locator",
            )
        if (
            body_ref.candidate_fingerprint != handle.candidate_fingerprint
            or body_ref.content_digest != handle.expected_content_digest
            or body_ref.content_length != handle.expected_content_length
        ):
            raise PackageResourceSourceError(
                code="resource_body_identity_mismatch",
                reason="load_handle_identity_mismatch",
            )
        try:
            with body_ref.handle.open_file(body_ref.relative_path) as stream:
                body = stream.read()
        except PluginRevisionError as exc:
            raise PackageResourceSourceError(
                code="resource_body_read_failed",
                reason=exc.code,
            ) from exc
        digest = hashlib.sha256(body).hexdigest()
        if digest != body_ref.content_digest or len(body) != body_ref.content_length:
            raise PackageResourceSourceError(
                code="resource_body_identity_mismatch",
                reason="verified_body_identity_mismatch",
            )
        return ResourceBodyRead(
            source_generation_ref=self._source_generation_ref,
            opaque_locator=handle.opaque_locator,
            body=body,
            observed_content_digest=digest,
            observed_content_length=len(body),
        )

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        handles = {
            id(item.revision_handle): item.revision_handle
            for item in self._resources.values()
        }
        for handle in handles.values():
            handle.close()
        self._resources.clear()
        self._bodies.clear()
        self._projection_bindings = ()
        self._snapshot = None


def package_source_policy_fingerprint(
    *,
    product_id: str,
    component_binding_fingerprint: str,
    resources: tuple[VerifiedPackageResourceInput, ...],
) -> str:
    return fingerprint_catalog_value(
        "loushang.package-resource-source-policy/v1",
        {
            "componentBindingFingerprint": component_binding_fingerprint,
            "productId": product_id,
            "resources": [
                item.policy_payload()
                for item in sorted(
                    resources,
                    key=lambda value: value.resource_admission_fingerprint,
                )
            ],
        },
    )


def build_package_source_generation_ref(
    *,
    source_id: str,
    product_id: str,
    runtime_id: str,
    owner_generation: int,
    producer: ResourceComponentProducer,
    component_binding_fingerprint: str,
    resources: tuple[VerifiedPackageResourceInput, ...],
) -> ResourceSourceGenerationRef:
    return ResourceSourceGenerationRef(
        source_id=source_id,
        product_id=product_id,
        generation=f"{runtime_id}:{owner_generation}",
        source_policy_fingerprint=package_source_policy_fingerprint(
            product_id=product_id,
            component_binding_fingerprint=component_binding_fingerprint,
            resources=resources,
        ),
        producer=producer,
    )


def _request_fingerprint(
    *,
    product_id: str,
    source_generation_ref: ResourceSourceGenerationRef,
    admission_fingerprints: tuple[str, ...],
    budget: PackageResourceDiscoveryBudget,
) -> str:
    return fingerprint_catalog_value(
        "loushang.package-resource-discovery-request/v1",
        {
            "admissionFingerprints": list(admission_fingerprints),
            "budget": budget.to_payload(),
            "productId": product_id,
            "sourceGenerationRef": source_generation_ref.to_payload(),
        },
    )


def _discover_resource(
    resource: VerifiedPackageResourceInput,
    *,
    request: PackageResourceDiscoveryRequest,
    control: _DiscoveryControl,
    source_generation_ref: ResourceSourceGenerationRef,
) -> tuple[
    ResourceCandidateSummary | None,
    tuple[ResourceCatalogDiagnostic, ...],
    _PackageBody | None,
    ResourceProjectionDescriptorBinding | None,
]:
    locator = PurePosixPath(resource.locator)
    body_path: PurePosixPath | None = locator
    if resource.locator_kind == "directory":
        body_path = locator / "SKILL.md" if resource.resource_kind == "skill" else None
    body_digest: str | None = None
    body_length: int | None = None
    parsed_body: bytes | None = None
    if body_path is not None:
        body_digest, body_length = resource.revision_handle.file_identity(body_path)
        if resource.resource_kind in {"prompt", "skill", "theme"}:
            control.reserve_metadata(body_length)
            with resource.revision_handle.open_file(body_path) as stream:
                parsed_body = stream.read()

    projection = project_catalog_item(
        resource_kind=resource.resource_kind,
        logical_path=body_path or locator,
        body=parsed_body,
        fallback_public_id=resource.resource_contribution_id,
        source_kind="external_package",
        source_scope="package",
        source_label="verified_package",
        source_root_order=resource.source_root_order,
    )
    if projection is None:
        return (
            None,
            _parser_diagnostics(
                resource,
                ("missing_resource_body",),
                source_generation_ref,
            ),
            None,
            None,
        )
    if not projection.valid:
        return (
            None,
            _parser_diagnostics(
                resource,
                projection.diagnostic_reasons,
                source_generation_ref,
            ),
            None,
            None,
        )
    candidate_diagnostics = _parser_diagnostics(
        resource,
        projection.diagnostic_reasons,
        source_generation_ref,
    )

    identity = ResourceIdentity(
        resource_kind=resource.resource_kind,
        schema_id=resource.schema_id,
        schema_version=resource.schema_version,
        public_id=projection.public_id,
    )
    opaque_locator = f"{resource.resource_admission_fingerprint}/{body_path or locator}"
    discovery_fingerprint = fingerprint_catalog_value(
        "loushang.package-resource-discovery/v1",
        {
            "admissionFingerprint": resource.resource_admission_fingerprint,
            "bodyDigest": body_digest,
            "bodyLength": body_length,
            "discoveryRequestFingerprint": request.request_fingerprint,
            "identity": identity.to_payload(),
            "opaqueLocator": opaque_locator,
            "packageContentDigest": resource.revision_handle.content_digest,
        },
    )
    candidate = build_candidate_summary(
        identity=identity,
        canonical_name=projection.canonical_name,
        description=projection.description,
        media_type=resource.media_type if body_path is not None else NO_BODY_MEDIA_TYPE,
        invocation_policy=ResourceInvocationPolicy(
            enabled=True,
            model_invocable=projection.model_invocable,
            reason="admitted_package_resource",
        ),
        source_generation_ref=source_generation_ref,
        source_class="external_package",
        scope_id="package",
        source_root_order=resource.source_root_order,
        content_origin=VerifiedPluginResourceOrigin(
            resource_contribution_id=resource.resource_contribution_id,
            resource_admission_fingerprint=resource.resource_admission_fingerprint,
            plugin_instance_revision_ref=resource.plugin_instance_revision_ref,
            package_content_digest=resource.package_content_digest,
        ),
        opaque_locator=opaque_locator,
        discovery_fingerprint=discovery_fingerprint,
        expected_content_digest=body_digest,
        expected_content_length=body_length,
        diagnostics=candidate_diagnostics,
    )
    body_ref = (
        _PackageBody(
            handle=resource.revision_handle,
            relative_path=body_path.as_posix(),
            candidate_fingerprint=candidate.candidate_fingerprint,
            content_digest=body_digest,
            content_length=body_length,
        )
        if body_path is not None and body_digest is not None and body_length is not None
        else None
    )
    descriptor = _package_projection_descriptor(
        resource=resource,
        projection=projection,
        logical_path=body_path or locator,
        body=parsed_body,
    )
    projection_binding = (
        build_resource_projection_binding(
            candidate=candidate,
            descriptor=descriptor,
            body=parsed_body,
        )
        if descriptor is not None
        else None
    )
    return candidate, (), body_ref, projection_binding


def _package_projection_descriptor(
    *,
    resource: VerifiedPackageResourceInput,
    projection: CatalogItemProjection,
    logical_path: PurePosixPath,
    body: bytes | None,
) -> ResourceProjectionDescriptor | None:
    if projection.descriptor is not None:
        return projection.descriptor
    if resource.resource_kind != "theme":
        return None
    try:
        content = body.decode("utf-8") if body is not None else None
    except UnicodeDecodeError as exc:
        raise PackageResourceSourceError(
            code="resource_source_snapshot_invalid",
            reason="invalid_theme_encoding",
        ) from exc
    return ThemeDescriptor(
        name=projection.canonical_name,
        id=projection.public_id,
        canonical_name=projection.canonical_name,
        content=content,
        source_path=resource.revision_handle.root / logical_path,
        source="verified_package",
        source_kind="external_package",
        source_scope="package",
        source_root=resource.revision_handle.root,
        source_root_order=resource.source_root_order,
    )


def _parser_diagnostics(
    resource: VerifiedPackageResourceInput,
    reasons: tuple[str, ...],
    source_generation_ref: ResourceSourceGenerationRef,
) -> tuple[ResourceCatalogDiagnostic, ...]:
    return tuple(
        sorted(
            (
                ResourceCatalogDiagnostic(
                    code="resource_source_discovery_failed",
                    reason=reason,
                    source_id=source_generation_ref.source_id,
                    details=(("contribution_id", resource.resource_contribution_id),),
                )
                for reason in reasons
            ),
            key=lambda item: item.canonical_sort_key(),
        )
    )


def _raise_budget(reason: str) -> None:
    raise PackageResourceSourceError(
        code="resource_source_discovery_budget_exceeded",
        reason=reason,
    )


def _raise_stale(reason: str) -> None:
    raise PackageResourceSourceError(
        code="resource_catalog_generation_stale",
        reason=reason,
    )


__all__ = [
    "AdmittedPackageResourceSource",
    "PackageResourceDiscoveryBudget",
    "PackageResourceDiscoveryRequest",
    "PackageResourceSourceError",
    "VerifiedPackageResourceInput",
    "acquire_verified_package_resource_input",
    "build_package_resource_discovery_request",
    "build_package_source_generation_ref",
]
