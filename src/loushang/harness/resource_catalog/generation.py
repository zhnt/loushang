"""Prepared Resource owner generation for the RCP4 Provider handoff."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from loushang.harness.capabilities.composition_runtime import (
    StagedResourceCompositionCandidate,
)
from loushang.harness.resource_catalog.inputs import AdmittedPackageResource
from loushang.harness.resource_catalog.shadow import (
    UnpublishedResourceCatalogShadowGeneration,
    run_first_party_resource_catalog_shadow,
)
from loushang.harness.resources._catalog_embedded_source import (
    EmbeddedResourceCollectionHandle,
    EmbeddedResourceDiscoveryBudget,
)
from loushang.harness.resources._catalog_native_source import (
    NativeResourceDiscoveryBudget,
    NativeResourceRootHandle,
)
from loushang.harness.resources._catalog_package_source import (
    PackageResourceDiscoveryBudget,
)
from loushang.harness.resources._catalog_records import (
    LoadedResource,
    ResourceActivationPolicySnapshot,
    ResourceCatalogSnapshot,
    ResourceIdentity,
    ResourceLoadHandle,
    ResourceMergePolicySnapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
)

ResourceOwnerGenerationState = Literal[
    "root_owned",
    "graph_constructing",
    "graph_owned",
    "retiring",
    "disposed",
]


class ResourceOwnerGenerationDisposalError(RuntimeError):
    """Retryable retirement debt retained by the exact current owner."""

    def __init__(self, diagnostic_codes: tuple[str, ...]) -> None:
        self.diagnostic_codes = tuple(sorted(set(diagnostic_codes)))
        super().__init__(
            "Resource owner generation disposal failed: "
            + ", ".join(self.diagnostic_codes)
        )


@dataclass(slots=True)
class PreparedResourceOwnerGeneration:
    """One unpublished Catalog generation with exactly one transfer path.

    Instances are created only by the preparation function below and are
    immediately attached to a ``StagedResourceCompositionCandidate``.  The
    concrete object is deliberately not returned as a peer cleanup handle.
    """

    _shadow: UnpublishedResourceCatalogShadowGeneration = field(repr=False)
    provider_binding_fingerprint: str
    _ownership: ResourceOwnerGenerationState = field(
        default="root_owned",
        init=False,
        repr=False,
    )
    _retirement_owner: Literal["root", "graph"] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @classmethod
    def _from_shadow(
        cls,
        shadow: UnpublishedResourceCatalogShadowGeneration,
    ) -> PreparedResourceOwnerGeneration:
        resolution = shadow.resolution
        fingerprint = fingerprint_catalog_value(
            "loushang.resource-owner-generation-provider-binding/v1",
            {
                "componentBindingFingerprints": sorted(
                    binding.binding_fingerprint for binding in resolution.bindings
                ),
                "resolvedComponentSetFingerprint": (
                    resolution.resolved_set.fingerprint
                ),
            },
        )
        return cls(
            _shadow=shadow,
            provider_binding_fingerprint=fingerprint,
        )

    @property
    def ownership_state(self) -> str:
        return self._ownership

    @property
    def catalog_snapshot(self) -> ResourceCatalogSnapshot:
        if self._ownership not in {
            "root_owned",
            "graph_constructing",
            "graph_owned",
        }:
            raise RuntimeError("Resource owner generation is retiring or disposed")
        return self._shadow.catalog_snapshot

    def load_handle(self, identity: ResourceIdentity) -> ResourceLoadHandle:
        self._require_graph_owned()
        return self._shadow.load_handle(identity)

    async def load(self, handle: ResourceLoadHandle) -> LoadedResource:
        self._require_graph_owned()
        return await self._shadow.load(handle)

    def _begin_graph_construction(self) -> None:
        if self._ownership != "root_owned":
            raise RuntimeError("Resource owner generation is not available for claim")
        self._ownership = "graph_constructing"

    def _commit_graph_ownership(self) -> None:
        if self._ownership != "graph_constructing":
            raise RuntimeError("Resource owner generation claim was not started")
        self._ownership = "graph_owned"

    def _restore_root_ownership(self) -> None:
        if self._ownership != "graph_constructing":
            raise RuntimeError("Resource owner generation claim is not in progress")
        self._ownership = "root_owned"

    async def dispose_root_owned(self) -> None:
        await self._dispose(owner="root")

    async def _dispose_graph_owned(self) -> None:
        await self._dispose(owner="graph")

    def _require_graph_owned(self) -> None:
        if self._ownership != "graph_owned":
            raise RuntimeError("Resource owner generation is not graph-owned")

    async def _dispose(self, *, owner: Literal["root", "graph"]) -> None:
        if self._ownership == "disposed":
            return
        expected = "root_owned" if owner == "root" else "graph_owned"
        if self._ownership == expected:
            self._ownership = "retiring"
            self._retirement_owner = owner
        elif not (self._ownership == "retiring" and self._retirement_owner == owner):
            raise RuntimeError(
                f"{owner.title()} cannot dispose a Resource generation it does not own"
            )

        codes = await self._shadow.dispose()
        if codes or not self._shadow.is_disposed:
            raise ResourceOwnerGenerationDisposalError(
                codes or ("resource_owner_generation_retirement_pending",)
            )
        self._ownership = "disposed"
        self._retirement_owner = None


async def prepare_first_party_resource_owner_generation(
    *,
    staged_candidate: StagedResourceCompositionCandidate,
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
) -> None:
    """Prepare and attach one first-party generation without publishing it."""

    if not isinstance(staged_candidate, StagedResourceCompositionCandidate):
        raise TypeError("Resource owner preparation requires its staged candidate")
    staged_candidate._assert_can_attach_prepared_owner_generation()
    shadow = await run_first_party_resource_catalog_shadow(
        product_id=product_id,
        scope_id=scope_id,
        runtime_id=runtime_id,
        product_policy_revision=product_policy_revision,
        root_handles=root_handles,
        package_resources=package_resources,
        embedded_collections=embedded_collections,
        issued_at=issued_at,
        expires_at=expires_at,
        now=now,
        discovery_budget=discovery_budget,
        discovery_deadline_monotonic_ns=discovery_deadline_monotonic_ns,
        discovery_cancellation_probe=discovery_cancellation_probe,
        package_discovery_budget=package_discovery_budget,
        embedded_discovery_budget=embedded_discovery_budget,
        context_file_names=context_file_names,
        merge_policy=merge_policy,
        activation_policy=activation_policy,
    )
    prepared = PreparedResourceOwnerGeneration._from_shadow(shadow)
    try:
        staged_candidate._attach_prepared_owner_generation(prepared)
    except BaseException:
        await prepared.dispose_root_owned()
        raise


__all__ = [
    "PreparedResourceOwnerGeneration",
    "ResourceOwnerGenerationDisposalError",
    "ResourceOwnerGenerationState",
    "prepare_first_party_resource_owner_generation",
]
