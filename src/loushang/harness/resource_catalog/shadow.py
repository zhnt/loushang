"""Unpublished Resource owner-generation runner for RCP2 shadow verification."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field

from loushang.harness.capabilities.component_runtime import (
    CapabilityOwnerComponentBinder,
    CapabilityOwnerComponentRuntime,
)
from loushang.harness.resource_catalog.components import (
    EMBEDDED_RESOURCE_SOURCE_COMPONENT_ID,
    NATIVE_RESOURCE_SOURCE_COMPONENT_ID,
    PACKAGE_RESOURCE_SOURCE_COMPONENT_ID,
    RESOURCE_CATALOG_ENGINE_COMPONENT_KIND,
    RESOURCE_SOURCE_COMPONENT_KIND,
    FirstPartyResourceComponentResolution,
    ResourceCatalogEngineComponent,
    ResourceSourceComponent,
    resolve_first_party_resource_components,
    validate_resource_catalog_proposal,
)
from loushang.harness.resource_catalog.inputs import AdmittedPackageResource
from loushang.harness.resources._catalog_embedded_source import (
    EmbeddedResourceCollectionHandle,
    EmbeddedResourceDiscoveryBudget,
    build_embedded_resource_discovery_request,
)
from loushang.harness.resources._catalog_engine import default_resource_merge_policy
from loushang.harness.resources._catalog_native_source import (
    NativeResourceDiscoveryBudget,
    NativeResourceRootHandle,
    build_native_resource_discovery_request,
)
from loushang.harness.resources._catalog_package_source import (
    PackageResourceDiscoveryBudget,
    build_package_resource_discovery_request,
)
from loushang.harness.resources._catalog_records import (
    ExtensionOwnerProducer,
    LoadedResource,
    ResourceActivationPolicySnapshot,
    ResourceCatalogHandle,
    ResourceCatalogSnapshot,
    ResourceIdentity,
    ResourceLoadHandle,
    ResourceLoadReceipt,
    ResourceMergePolicySnapshot,
    ResourceSourceSnapshot,
    build_activation_policy_snapshot,
)
from loushang.harness.resources._catalog_source_contracts import (
    BorrowedResourceSourceGeneration,
    ResourceDiscoveryRequest,
)
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
)


@dataclass(slots=True)
class UnpublishedResourceCatalogShadowGeneration:
    """Pinned owner generation that is never adopted by the live Resource Provider."""

    resolution: FirstPartyResourceComponentResolution
    catalog_snapshot: ResourceCatalogSnapshot
    source_snapshots: tuple[ResourceSourceSnapshot, ...]
    _runtime: CapabilityOwnerComponentRuntime = field(repr=False)
    _binder: CapabilityOwnerComponentBinder = field(repr=False)
    _extension_source_generation: BorrowedResourceSourceGeneration | None = field(
        default=None,
        repr=False,
    )
    _disposed: bool = field(default=False, init=False, repr=False)

    @property
    def owner_generation(self) -> int:
        return self._runtime.generation

    @property
    def is_disposed(self) -> bool:
        return self._disposed

    def load_handle(self, identity: ResourceIdentity) -> ResourceLoadHandle:
        """Mint a narrow load handle for one effective, body-bearing candidate."""

        if self._disposed or self._runtime.is_closed:
            raise RuntimeError(
                "Unpublished Resource shadow generation is retiring or disposed"
            )
        effective = next(
            (
                entry
                for entry in self.catalog_snapshot.effective_entries
                if entry.identity == identity
            ),
            None,
        )
        if effective is None:
            raise KeyError(identity)
        candidate = self.catalog_snapshot.candidate_by_fingerprint(
            effective.primary_candidate_fingerprint
        )
        catalog_handle = ResourceCatalogHandle(
            catalog_generation=self.catalog_snapshot.catalog_generation,
            snapshot_fingerprint=self.catalog_snapshot.snapshot_fingerprint,
            identity=identity,
            candidate_fingerprint=candidate.candidate_fingerprint,
        )
        return ResourceLoadHandle.from_catalog(
            catalog_handle=catalog_handle,
            candidate=candidate,
        )

    async def load(self, handle: ResourceLoadHandle) -> LoadedResource:
        """Pin the owner generation, call its exact source, then validate a receipt."""

        if self._disposed or self._runtime.is_closed:
            raise RuntimeError(
                "Unpublished Resource shadow generation is retiring or disposed"
            )
        if (
            handle.catalog_generation != self.catalog_snapshot.catalog_generation
            or handle.snapshot_fingerprint != self.catalog_snapshot.snapshot_fingerprint
        ):
            raise ValueError("Resource load handle targets another Catalog generation")
        candidate = self.catalog_snapshot.candidate_by_fingerprint(
            handle.candidate_fingerprint
        )
        if candidate.identity != handle.identity:
            raise ValueError("Resource load handle identity is inconsistent")
        selected = any(
            handle.candidate_fingerprint in entry.candidate_fingerprints
            for entry in self.catalog_snapshot.effective_entries
            if entry.identity == handle.identity
        )
        if not selected:
            raise ValueError(
                "Resource load handle does not select an effective candidate"
            )

        borrowed = self._extension_source_generation
        if (
            borrowed is not None
            and borrowed.source_generation_ref != handle.source_generation_ref
        ):
            borrowed = None
        if borrowed is not None:
            body_read = borrowed.load(handle)
            if inspect.isawaitable(body_read):
                body_read = await body_read
            receipt = ResourceLoadReceipt.from_validated_read(
                load_handle=handle,
                body_read=body_read,
            )
            return LoadedResource(receipt=receipt, body=body_read.body)

        leases = self._runtime.capture_all(RESOURCE_SOURCE_COMPONENT_KIND)
        try:
            source: ResourceSourceComponent | None = None
            for lease in leases:
                payload = lease.require()
                if not isinstance(payload, ResourceSourceComponent):
                    raise TypeError("Mounted Resource source payload is invalid")
                if payload.source_generation_ref == handle.source_generation_ref:
                    source = payload
                    break
            if source is None:
                raise ValueError(
                    "Resource load handle names an unmounted source generation"
                )
            body_read = source.load(handle)
            if inspect.isawaitable(body_read):
                body_read = await body_read
            receipt = ResourceLoadReceipt.from_validated_read(
                load_handle=handle,
                body_read=body_read,
            )
            return LoadedResource(receipt=receipt, body=body_read.body)
        finally:
            for lease in reversed(leases):
                await lease.aclose()

    async def dispose(self) -> tuple[str, ...]:
        if self._disposed:
            return ()
        codes = await self._binder.dispose(self._runtime)
        self._disposed = not self._runtime.has_pending_retirements
        if self._disposed:
            self._extension_source_generation = None
        return codes


async def run_first_party_resource_catalog_shadow(
    *,
    product_id: str,
    scope_id: str,
    runtime_id: str,
    product_policy_revision: str,
    root_handles: tuple[NativeResourceRootHandle, ...],
    package_resources: tuple[AdmittedPackageResource, ...] = (),
    embedded_collections: tuple[EmbeddedResourceCollectionHandle, ...] = (),
    issued_at: int,
    expires_at: int,
    now: int,
    discovery_budget: NativeResourceDiscoveryBudget | None = None,
    discovery_deadline_monotonic_ns: int | None = None,
    discovery_cancellation_probe: Callable[[], bool] | None = None,
    package_discovery_budget: PackageResourceDiscoveryBudget | None = None,
    embedded_discovery_budget: EmbeddedResourceDiscoveryBudget | None = None,
    context_file_names: tuple[str, ...] = DEFAULT_CONTEXT_FILE_NAMES,
    merge_policy: ResourceMergePolicySnapshot | None = None,
    activation_policy: ResourceActivationPolicySnapshot | None = None,
    extension_source_generation: BorrowedResourceSourceGeneration | None = None,
) -> UnpublishedResourceCatalogShadowGeneration:
    """Bind, discover, compose, validate, and retain one unpublished generation."""

    if extension_source_generation is not None and not isinstance(
        extension_source_generation,
        BorrowedResourceSourceGeneration,
    ):
        raise TypeError("Extension Resource input must be a borrowed source generation")
    extension_snapshot = (
        extension_source_generation.source_snapshot
        if extension_source_generation is not None
        else None
    )
    if extension_snapshot is not None and (
        extension_snapshot.source_generation_ref.source_id
        != "harness.extensions.resources"
        or not isinstance(
            extension_snapshot.source_generation_ref.producer,
            ExtensionOwnerProducer,
        )
    ):
        raise ValueError(
            "Only exact Extension-owner snapshots may bypass mounted source components"
        )
    if extension_snapshot is not None and not extension_snapshot.complete:
        raise ValueError("Extension-owner Resource snapshots must be complete")
    if (
        extension_source_generation is not None
        and extension_snapshot is not None
        and extension_source_generation.source_generation_ref
        != extension_snapshot.source_generation_ref
    ):
        raise ValueError("Borrowed Resource body reader must match its snapshot")
    if (
        extension_snapshot is not None
        and extension_snapshot.source_generation_ref.product_id != product_id
    ):
        raise ValueError("Extension Resource source generation must match Product")

    resolution = resolve_first_party_resource_components(
        product_id=product_id,
        scope_id=scope_id,
        product_policy_revision=product_policy_revision,
        root_handles=root_handles,
        package_resources=package_resources,
        embedded_collections=embedded_collections,
        issued_at=issued_at,
        expires_at=expires_at,
        now=now,
    )
    runtime = CapabilityOwnerComponentRuntime(
        capability_id="harness.resources",
        owner_id="harness",
        product_id=product_id,
        runtime_id=runtime_id,
    )
    binder = CapabilityOwnerComponentBinder()
    try:
        bind_result = await binder.bind(
            runtime,
            resolution.resolved_set,
            resolution.bindings,
        )
    except BaseException:
        # Passing the prepared inputs into Binding transfers their narrow leases to
        # this owner generation. A failure before publication must return custody
        # even when no source component was constructed for a given input.
        for resource in package_resources:
            resource.close()
        for collection in embedded_collections:
            collection.close()
        raise
    engine_lease = runtime.capture_one(RESOURCE_CATALOG_ENGINE_COMPONENT_KIND)
    source_leases = runtime.capture_all(RESOURCE_SOURCE_COMPONENT_KIND)
    try:
        engine = engine_lease.require()
        if not isinstance(engine, ResourceCatalogEngineComponent):
            raise TypeError("Mounted Catalog engine payload is invalid")
        source_snapshots: list[ResourceSourceSnapshot] = []
        for lease in source_leases:
            source = lease.require()
            if not isinstance(source, ResourceSourceComponent):
                raise TypeError("Mounted Resource source payload is invalid")
            request: ResourceDiscoveryRequest
            if lease.component_id == NATIVE_RESOURCE_SOURCE_COMPONENT_ID:
                request = build_native_resource_discovery_request(
                    product_id=product_id,
                    source_generation_ref=source.source_generation_ref,
                    root_handle_ids=tuple(item.handle_id for item in root_handles),
                    context_file_names=context_file_names,
                    budget=discovery_budget,
                    deadline_monotonic_ns=discovery_deadline_monotonic_ns,
                    cancellation_probe=discovery_cancellation_probe,
                )
            elif lease.component_id == PACKAGE_RESOURCE_SOURCE_COMPONENT_ID:
                request = build_package_resource_discovery_request(
                    product_id=product_id,
                    source_generation_ref=source.source_generation_ref,
                    admission_fingerprints=tuple(
                        item.admission.fingerprint for item in package_resources
                    ),
                    budget=package_discovery_budget,
                    deadline_monotonic_ns=discovery_deadline_monotonic_ns,
                    cancellation_probe=discovery_cancellation_probe,
                )
            elif lease.component_id == EMBEDDED_RESOURCE_SOURCE_COMPONENT_ID:
                request = build_embedded_resource_discovery_request(
                    product_id=product_id,
                    source_generation_ref=source.source_generation_ref,
                    collection_handle_ids=tuple(
                        item.handle_id for item in embedded_collections
                    ),
                    budget=embedded_discovery_budget,
                    deadline_monotonic_ns=discovery_deadline_monotonic_ns,
                    cancellation_probe=discovery_cancellation_probe,
                )
            else:
                raise TypeError("Unknown Resource source component")
            source_snapshots.append(source.discover_initial(request))
        if extension_snapshot is not None:
            source_snapshots.append(extension_snapshot)
        source_refs = tuple(
            snapshot.source_generation_ref for snapshot in source_snapshots
        )
        if len(set(source_refs)) != len(source_refs):
            raise ValueError("Resource source generations must not repeat")
        effective_merge_policy = merge_policy or default_resource_merge_policy()
        effective_activation_policy = activation_policy or (
            build_activation_policy_snapshot(
                policy_revision="resource-activation-policy-v2-rcp2-shadow"
            )
        )
        proposal = engine.compose(
            source_snapshots,
            catalog_generation=bind_result.snapshot.generation,
            merge_policy=effective_merge_policy,
            activation_policy=effective_activation_policy,
        )
        validate_resource_catalog_proposal(
            proposal,
            source_snapshots=source_snapshots,
            catalog_generation=bind_result.snapshot.generation,
            engine_binding_fingerprint=engine.binding_fingerprint,
            merge_policy=effective_merge_policy,
            activation_policy=effective_activation_policy,
        )
    except BaseException:
        await engine_lease.aclose()
        for lease in reversed(source_leases):
            await lease.aclose()
        await binder.dispose(runtime)
        raise
    await engine_lease.aclose()
    for lease in reversed(source_leases):
        await lease.aclose()
    return UnpublishedResourceCatalogShadowGeneration(
        resolution=resolution,
        catalog_snapshot=proposal,
        source_snapshots=tuple(source_snapshots),
        _runtime=runtime,
        _binder=binder,
        _extension_source_generation=extension_source_generation,
    )


__all__ = [
    "UnpublishedResourceCatalogShadowGeneration",
    "run_first_party_resource_catalog_shadow",
]
