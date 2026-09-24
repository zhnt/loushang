"""Catalog source for immutable Resources selected by a Package Product owner."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import NoReturn

from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    ResourceContributionSpec,
)
from loushang.harness.resources._catalog_package_source import (
    PackageResourceDiscoveryRequest,
)
from loushang.harness.resources._catalog_projection import (
    ResourceProjectionDescriptorBinding,
    build_resource_projection_binding,
)
from loushang.harness.resources._catalog_records import (
    ResourceBodyRead,
    ResourceCandidateSummary,
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
from loushang.harness.resources._resource_item_projection import project_catalog_item
from loushang.harness.resources.packages.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    RevisionResourceRef,
    SkillDescriptor,
)


class ProductSnapshotResourceSourceError(RuntimeError):
    def __init__(self, *, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True, slots=True)
class ProductSelectedResourceInput:
    """One owner admission paired with bytes from its selected Store capture."""

    admission: OwnerContributionAdmissionRecord
    selected_manifest: PackageProductSelectedPluginManifestV1 = field(
        repr=False, compare=False
    )
    relative_path: str
    source_root_order: int = 0
    _body: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.admission, OwnerContributionAdmissionRecord):
            raise TypeError("Product Resource requires an owner admission")
        resource = self.admission.candidate.contribution
        if (
            self.admission.contribution_kind != "resource_item"
            or not isinstance(resource, ResourceContributionSpec)
            or resource.resource_kind not in {"prompt", "skill"}
            or resource.managed_skill_actions
        ):
            raise ValueError("Product Resource must be a supported data-only admission")
        if self.admission.owner_id != f"resources.{resource.resource_kind}":
            raise ValueError("Product Resource admission owner is invalid")
        if not isinstance(self.selected_manifest, PackageProductSelectedPluginManifestV1):
            raise TypeError("Product Resource requires a selected Store manifest")
        manifest = self.selected_manifest.verified_manifest()
        snapshot = self.selected_manifest.snapshot
        candidate = self.admission.candidate
        if (
            self.admission.product_id != snapshot.installation_key.product_id
            or self.admission.plugin_id != manifest.name
            or candidate.instance_revision_ref != snapshot.instance_revision_ref
            or candidate.package_content_digest
            != snapshot.package_revision.package_content_digest
            or candidate.dependency_lock_digest
            != snapshot.package_revision.dependency_lock_digest
            or candidate.package_source_identity
            != snapshot.package_revision.package_source_identity
        ):
            raise ValueError("Product Resource admission changed selected Store identity")
        expected_path = (
            f"{resource.locator}/SKILL.md"
            if resource.locator_kind == "directory"
            and resource.resource_kind == "skill"
            else resource.locator
        )
        if self.relative_path != expected_path:
            raise ValueError("Product Resource path changed the admitted locator")
        root = manifest.root_relative_path.as_posix()
        captured_path = (
            self.relative_path if root == "." else f"{root}/{self.relative_path}"
        )
        body = dict(snapshot.files).get(captured_path)
        if body is None:
            raise ValueError("Product Resource body is absent from selected Store bytes")
        object.__setattr__(self, "_body", body)
        if type(self.source_root_order) is not int or self.source_root_order < 0:
            raise ValueError("Product Resource root order must be non-negative")

    @property
    def body(self) -> bytes:
        return self._body

    def policy_payload(self) -> dict[str, object]:
        return {
            "admissionFingerprint": self.admission.fingerprint,
            "bodyDigest": sha256(self.body).hexdigest(),
            "bodyLength": len(self.body),
            "relativePath": self.relative_path,
            "sourceRootOrder": self.source_root_order,
        }


def product_snapshot_source_policy_fingerprint(
    *, product_id: str, resources: tuple[ProductSelectedResourceInput, ...]
) -> str:
    return fingerprint_catalog_value(
        "loushang.product-snapshot-resource-source-policy/v1",
        {
            "productId": product_id,
            "resources": [
                item.policy_payload()
                for item in sorted(
                    resources, key=lambda value: value.admission.fingerprint
                )
            ],
        },
    )


class ProductSelectedResourceSource:
    """Read admitted Product bytes without a publisher or ambient path lookup."""

    def __init__(
        self,
        *,
        source_generation_ref: ResourceSourceGenerationRef,
        resources: tuple[ProductSelectedResourceInput, ...],
    ) -> None:
        if not isinstance(source_generation_ref, ResourceSourceGenerationRef):
            raise TypeError("Product Resource source requires a generation ref")
        if any(
            not isinstance(item, ProductSelectedResourceInput) for item in resources
        ):
            raise TypeError("Product Resource source requires typed inputs")
        if len({item.admission.fingerprint for item in resources}) != len(resources):
            raise ValueError("Product Resource admissions must not repeat")
        if any(
            item.admission.product_id != source_generation_ref.product_id
            for item in resources
        ):
            raise ValueError("Product Resource admissions must match Product")
        if (
            source_generation_ref.source_policy_fingerprint
            != product_snapshot_source_policy_fingerprint(
                product_id=source_generation_ref.product_id, resources=resources
            )
        ):
            raise ValueError("Product Resource source policy changed")
        self._source_generation_ref = source_generation_ref
        self._resources = {item.admission.fingerprint: item for item in resources}
        self._snapshot: ResourceSourceSnapshot | None = None
        self._bindings: tuple[ResourceProjectionDescriptorBinding, ...] = ()
        self._bodies: dict[str, tuple[str, bytes]] = {}
        self._disposed = False

    @property
    def source_generation_ref(self) -> ResourceSourceGenerationRef:
        return self._source_generation_ref

    @property
    def projection_bindings(self) -> tuple[ResourceProjectionDescriptorBinding, ...]:
        self._require_live()
        return self._bindings

    def discover_initial(
        self, request: ResourceDiscoveryRequest
    ) -> ResourceSourceSnapshot:
        self._require_live()
        if not isinstance(request, PackageResourceDiscoveryRequest):
            raise TypeError(
                "Product Resource discovery requires a typed package request"
            )
        if (
            request.product_id != self._source_generation_ref.product_id
            or request.source_generation_ref != self._source_generation_ref
        ):
            self._fail("resource_source_stale", "foreign_source_generation")
        if request.admission_fingerprints != tuple(sorted(self._resources)):
            self._fail("resource_source_snapshot_invalid", "admission_set_mismatch")
        if self._snapshot is not None:
            if (
                self._snapshot.discovery_request_fingerprint
                != request.request_fingerprint
            ):
                self._fail("resource_source_stale", "discovery_request_changed")
            return self._snapshot
        if len(self._resources) > request.budget.maximum_items:
            self._fail("resource_source_budget_exceeded", "item_count_exceeded")
        metadata_bytes = 0
        candidates: list[ResourceCandidateSummary] = []
        bindings: list[ResourceProjectionDescriptorBinding] = []
        bodies: dict[str, tuple[str, bytes]] = {}
        for fingerprint in request.admission_fingerprints:
            self._check_request(request)
            item = self._resources[fingerprint]
            resource = item.admission.candidate.contribution
            assert isinstance(resource, ResourceContributionSpec)
            metadata_bytes += len(item.body)
            if metadata_bytes > request.budget.maximum_metadata_bytes:
                self._fail("resource_source_budget_exceeded", "metadata_bytes_exceeded")
            logical_path = PurePosixPath(item.relative_path)
            projection = project_catalog_item(
                resource_kind=resource.resource_kind,
                logical_path=logical_path,
                body=item.body,
                fallback_public_id=item.admission.contribution_id,
                source_kind="external_package",
                source_scope="package",
                source_label="product_selected_snapshot",
                source_root_order=item.source_root_order,
            )
            if (
                projection is None
                or not projection.valid
                or projection.descriptor is None
            ):
                self._fail("resource_source_snapshot_invalid", "invalid_resource_body")
            candidate_ref = item.admission.candidate
            instance = candidate_ref.instance_revision_ref
            instance_text = (
                f"{instance.instance_id}:{instance.plugin_id}@{instance.revision}"
            )
            identity = ResourceIdentity(
                resource_kind=resource.resource_kind,
                schema_id=resource.schema_id,
                schema_version=resource.schema_version,
                public_id=projection.public_id,
            )
            digest = sha256(item.body).hexdigest()
            opaque_locator = f"{fingerprint}/{item.relative_path}"
            discovery_fingerprint = fingerprint_catalog_value(
                "loushang.product-snapshot-resource-discovery/v1",
                {
                    "admissionFingerprint": fingerprint,
                    "bodyDigest": digest,
                    "bodyLength": len(item.body),
                    "identity": identity.to_payload(),
                    "requestFingerprint": request.request_fingerprint,
                },
            )
            candidate = build_candidate_summary(
                identity=identity,
                canonical_name=projection.canonical_name,
                description=projection.description,
                media_type=resource.media_type,
                invocation_policy=ResourceInvocationPolicy(
                    enabled=True,
                    model_invocable=projection.model_invocable,
                    reason="product_selected_resource",
                ),
                source_generation_ref=self._source_generation_ref,
                source_class="external_package",
                scope_id="package",
                source_root_order=item.source_root_order,
                content_origin=VerifiedPluginResourceOrigin(
                    resource_contribution_id=item.admission.contribution_id,
                    resource_admission_fingerprint=fingerprint,
                    plugin_instance_revision_ref=instance_text,
                    package_content_digest=candidate_ref.package_content_digest,
                ),
                opaque_locator=opaque_locator,
                discovery_fingerprint=discovery_fingerprint,
                expected_content_digest=digest,
                expected_content_length=len(item.body),
            )
            descriptor = projection.descriptor
            assert isinstance(descriptor, PromptFragmentDescriptor | SkillDescriptor)
            # This is a logical package path for display and sorting; the source
            # never resolves it or reads it from the host filesystem.
            descriptor = replace(
                descriptor,
                source_path=Path(item.relative_path),
                source_root=Path("."),
                revision_ref=RevisionResourceRef(
                    content_digest=candidate_ref.package_content_digest,
                    relative_path=item.relative_path,
                ),
            )
            bindings.append(
                build_resource_projection_binding(
                    candidate=candidate, descriptor=descriptor, body=item.body
                )
            )
            candidates.append(candidate)
            bodies[opaque_locator] = (candidate.candidate_fingerprint, item.body)
        snapshot = build_source_snapshot(
            source_generation_ref=self._source_generation_ref,
            discovery_request_fingerprint=request.request_fingerprint,
            candidate_summaries=candidates,
        )
        self._snapshot = snapshot
        self._bindings = tuple(
            sorted(bindings, key=lambda value: value.candidate_fingerprint)
        )
        self._bodies = bodies
        return snapshot

    @staticmethod
    def _check_request(request: PackageResourceDiscoveryRequest) -> None:
        probe = request.cancellation_probe
        if probe is not None and probe():
            raise asyncio.CancelledError
        deadline = request.deadline_monotonic_ns
        if deadline is not None and time.monotonic_ns() >= deadline:
            ProductSelectedResourceSource._fail(
                "resource_source_budget_exceeded", "deadline_exceeded"
            )

    def load(self, handle: ResourceLoadHandle) -> ResourceBodyRead:
        self._require_live()
        if not isinstance(handle, ResourceLoadHandle):
            raise TypeError("Product Resource load requires a Catalog handle")
        if handle.source_generation_ref != self._source_generation_ref:
            self._fail("resource_source_stale", "foreign_source_generation")
        stored = self._bodies.get(handle.opaque_locator)
        if stored is None:
            self._fail("resource_body_read_failed", "unknown_opaque_locator")
        fingerprint, body = stored
        digest = sha256(body).hexdigest()
        if (
            handle.candidate_fingerprint != fingerprint
            or handle.expected_content_digest != digest
            or handle.expected_content_length != len(body)
        ):
            self._fail(
                "resource_body_identity_mismatch", "load_handle_identity_mismatch"
            )
        return ResourceBodyRead(
            source_generation_ref=self._source_generation_ref,
            opaque_locator=handle.opaque_locator,
            body=body,
            observed_content_digest=digest,
            observed_content_length=len(body),
        )

    def dispose(self) -> None:
        self._disposed = True
        self._resources.clear()
        self._bodies.clear()
        self._bindings = ()
        self._snapshot = None

    def _require_live(self) -> None:
        if self._disposed:
            self._fail("resource_source_stale", "source_disposed")

    @staticmethod
    def _fail(code: str, reason: str) -> NoReturn:
        raise ProductSnapshotResourceSourceError(code=code, reason=reason)


__all__ = [
    "ProductSelectedResourceInput",
    "ProductSelectedResourceSource",
    "ProductSnapshotResourceSourceError",
    "product_snapshot_source_policy_fingerprint",
]
