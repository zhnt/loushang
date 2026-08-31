"""Prepared Resource owner generation for the RCP4 Provider handoff."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loushang.harness.capabilities.composition_runtime import (
    StagedResourceCompositionCandidate,
    _PreparedResourceOwnerGeneration,
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
from loushang.harness.resources._catalog_projection import ResourceCatalogProjection
from loushang.harness.resources._catalog_records import (
    LoadedResource,
    ResourceActivationPolicySnapshot,
    ResourceCatalogSnapshot,
    ResourceIdentity,
    ResourceLoadHandle,
    ResourceMergePolicySnapshot,
    fingerprint_catalog_value,
)
from loushang.harness.resources._catalog_source_contracts import (
    BorrowedResourceSourceGenerationLease,
)
from loushang.harness.resources._discovery_conventions import (
    DEFAULT_CONTEXT_FILE_NAMES,
)
from loushang.harness.resources._skill_action_authority import (
    _begin_catalog_action_owner_generation,
    _cancel_catalog_action_owner_binding,
    _CatalogActionOwnerAttachmentReceipt,
    _CatalogActionOwnerGenerationLifecycle,
    _commit_catalog_action_owner_generation,
    _consume_catalog_action_owner_attachment,
    _prepare_catalog_action_owner_binding,
    _restore_catalog_action_owner_generation,
    _retire_catalog_action_owner_generation,
)
from loushang.harness.resources._skill_catalog_consumer import (
    EffectiveSkillCatalogProjection,
    SkillCatalogConsumer,
    build_effective_skill_catalog_projection,
)
from loushang.harness.resources._skill_catalog_status import (
    SkillCatalogStatusProjection,
)
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
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


@dataclass(frozen=True, slots=True)
class _PreparedSkillCatalogOwnerView:
    """Exact owner-derived inputs used while constructing one Skill consumer."""

    _generation: PreparedResourceOwnerGeneration = field(repr=False, compare=False)
    snapshot: ResourceCatalogSnapshot
    skill_projection: EffectiveSkillCatalogProjection
    skill_status_projection: SkillCatalogStatusProjection | None = None

    def load_handle(self, identity: ResourceIdentity) -> ResourceLoadHandle:
        return self._generation.load_handle(identity)

    async def load(self, handle: ResourceLoadHandle) -> LoadedResource:
        return await self._generation.load(handle)


@dataclass(slots=True, weakref_slot=True)
class PreparedResourceOwnerGeneration(_PreparedResourceOwnerGeneration):
    """One unpublished Catalog generation with exactly one transfer path.

    Instances are created only by the preparation function below and are
    immediately attached to a ``StagedResourceCompositionCandidate``.  The
    concrete object is deliberately not returned as a peer cleanup handle.
    """

    _shadow: UnpublishedResourceCatalogShadowGeneration = field(repr=False)
    runtime_id: str
    catalog_generation: int
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
    _skill_action_owner_lifecycle: _CatalogActionOwnerGenerationLifecycle | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @classmethod
    def _from_shadow(
        cls,
        shadow: UnpublishedResourceCatalogShadowGeneration,
        *,
        runtime_id: str,
        catalog_generation: int,
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
        generation = cls(
            _shadow=shadow,
            runtime_id=runtime_id,
            catalog_generation=catalog_generation,
            provider_binding_fingerprint=fingerprint,
        )
        return generation

    def _accept_candidate_attachment(self, receipt: object) -> None:
        if self._ownership != "root_owned":
            raise RuntimeError("Resource owner generation is not root-owned")
        if self._skill_action_owner_lifecycle is not None:
            raise RuntimeError("Resource owner generation is already attached")
        if type(receipt) is not _CatalogActionOwnerAttachmentReceipt:
            raise TypeError("Resource owner attachment receipt is invalid")
        self._skill_action_owner_lifecycle = (
            _consume_catalog_action_owner_attachment(receipt, owner=self)
        )

    def retirement_receipt(
        self,
        *,
        contribution_ids: tuple[str, ...],
    ) -> OwnerGenerationRetirementReceipt:
        if self._ownership not in {
            "root_owned",
            "graph_constructing",
            "graph_owned",
        }:
            raise RuntimeError(
                "Resource owner retirement evidence requires a live generation"
            )
        owner_reference = f"resource-catalog-owner:{self.runtime_id}"
        return OwnerGenerationRetirementReceipt(
            owner_reference=owner_reference,
            owner_generation_reference=(
                f"{owner_reference}:generation:{self.catalog_generation}:"
                f"{self.provider_binding_fingerprint}"
            ),
            retirement_handle=(
                "resource-catalog-generation:"
                f"{self.provider_binding_fingerprint}"
            ),
            contribution_ids=contribution_ids,
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

    @property
    def catalog_projection(self) -> ResourceCatalogProjection | None:
        if self._ownership not in {
            "root_owned",
            "graph_constructing",
            "graph_owned",
        }:
            raise RuntimeError("Resource owner generation is retiring or disposed")
        return self._shadow.catalog_projection

    @property
    def _skill_status_projection(self) -> SkillCatalogStatusProjection:
        if self._ownership not in {
            "root_owned",
            "graph_constructing",
            "graph_owned",
        }:
            raise RuntimeError("Resource owner generation is retiring or disposed")
        return self._shadow.skill_status_projection

    def load_handle(self, identity: ResourceIdentity) -> ResourceLoadHandle:
        self._require_graph_owned()
        return self._shadow.load_handle(identity)

    async def load(self, handle: ResourceLoadHandle) -> LoadedResource:
        self._require_graph_owned()
        return await self._shadow.load(handle)

    def _construct_skill_catalog_consumer(
        self,
        *,
        include_status: bool,
    ) -> SkillCatalogConsumer:
        """Atomically construct and owner-bind one exact Skill consumer."""

        self._require_graph_owned()
        snapshot = self.catalog_snapshot
        projection = self.catalog_projection
        if not isinstance(projection, ResourceCatalogProjection):
            raise TypeError("Resource owner has no Skill Catalog projection")
        effective = build_effective_skill_catalog_projection(
            snapshot=snapshot,
            projection=projection,
        )
        status = self._skill_status_projection if include_status else None
        view = _PreparedSkillCatalogOwnerView(
            _generation=self,
            snapshot=snapshot,
            skill_projection=effective,
            skill_status_projection=status,
        )
        if not effective.managed_action_sources:
            return SkillCatalogConsumer._from_resource_owner(view)
        binding = _prepare_catalog_action_owner_binding(
            self._require_skill_action_owner_lifecycle(),
            owner=self,
            projection=effective,
        )
        try:
            return SkillCatalogConsumer._from_resource_owner(
                view,
                _action_owner_binding=binding,
            )
        except BaseException:
            _cancel_catalog_action_owner_binding(binding)
            raise

    def _borrows_extension_source_lease(self, source: object) -> bool:
        return self._shadow._borrows_extension_source_lease(source)

    def _begin_graph_construction(self) -> None:
        if self._ownership != "root_owned":
            raise RuntimeError("Resource owner generation is not available for claim")
        _begin_catalog_action_owner_generation(
            self._require_skill_action_owner_lifecycle(),
            owner=self,
        )
        self._ownership = "graph_constructing"

    def _commit_graph_ownership(self) -> None:
        if self._ownership != "graph_constructing":
            raise RuntimeError("Resource owner generation claim was not started")
        _commit_catalog_action_owner_generation(
            self._require_skill_action_owner_lifecycle(),
            owner=self,
        )
        self._ownership = "graph_owned"

    def _restore_root_ownership(self) -> None:
        if self._ownership != "graph_constructing":
            raise RuntimeError("Resource owner generation claim is not in progress")
        _restore_catalog_action_owner_generation(
            self._require_skill_action_owner_lifecycle(),
            owner=self,
        )
        self._ownership = "root_owned"

    async def dispose_root_owned(self) -> None:
        await self._dispose(owner="root")

    async def _dispose_graph_owned(self) -> None:
        await self._dispose(owner="graph")

    def _require_graph_owned(self) -> None:
        if self._ownership != "graph_owned":
            raise RuntimeError("Resource owner generation is not graph-owned")

    def _require_skill_action_owner_lifecycle(
        self,
    ) -> _CatalogActionOwnerGenerationLifecycle:
        lifecycle = self._skill_action_owner_lifecycle
        if type(lifecycle) is not _CatalogActionOwnerGenerationLifecycle:
            raise RuntimeError("Resource owner generation is not candidate-attached")
        return lifecycle

    async def _dispose(self, *, owner: Literal["root", "graph"]) -> None:
        if self._ownership == "disposed":
            return
        expected = "root_owned" if owner == "root" else "graph_owned"
        if self._ownership == expected:
            lifecycle = self._skill_action_owner_lifecycle
            if lifecycle is not None:
                _retire_catalog_action_owner_generation(
                    lifecycle,
                    owner=self,
                )
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
    catalog_generation: int = 1,
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
    extension_source_lease: BorrowedResourceSourceGenerationLease | None = None,
    projection_cwd: Path | None = None,
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
        catalog_generation=catalog_generation,
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
        extension_source_lease=extension_source_lease,
        projection_cwd=projection_cwd,
    )
    prepared = PreparedResourceOwnerGeneration._from_shadow(
        shadow,
        runtime_id=runtime_id,
        catalog_generation=catalog_generation,
    )
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
