"""First-party Resource owner-component contributions for RCP2 shadow use."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from loushang.harness.capabilities.component_admission import (
    CapabilityComponentAdmission,
    CapabilityComponentCandidate,
    CapabilityComponentOwnerAuthority,
    CapabilityComponentOwnerPolicy,
)
from loushang.harness.capabilities.component_binding import (
    CapabilityOwnerComponentBinding,
    CapabilityOwnerComponentContext,
    CapabilityOwnerComponentValue,
    owner_component_binding_fingerprint,
)
from loushang.harness.capabilities.component_contracts import (
    CapabilityComponentBindingSpec,
    CapabilityComponentDefinition,
)
from loushang.harness.capabilities.component_selection import (
    CapabilityComponentSelectionChoice,
    CapabilityComponentSelectionPlan,
    ProductCapabilityComponentResolver,
    ResolvedCapabilityComponent,
    ResolvedCapabilityComponentSet,
)
from loushang.harness.capabilities.contracts import CapabilityContractRange
from loushang.harness.resources._catalog_engine import compose_resource_catalog
from loushang.harness.resources._catalog_native_source import (
    NativeFilesystemResourceSource,
    NativeResourceDiscoveryRequest,
    NativeResourceRootHandle,
    build_native_source_generation_ref,
)
from loushang.harness.resources._catalog_records import (
    ResourceActivationPolicySnapshot,
    ResourceBodyRead,
    ResourceCatalogSnapshot,
    ResourceComponentProducer,
    ResourceLoadHandle,
    ResourceMergePolicySnapshot,
    ResourceSourceGenerationRef,
    ResourceSourceSnapshot,
    fingerprint_catalog_value,
)

RESOURCE_CATALOG_ENGINE_COMPONENT_KIND = "resource.catalog_engine"
RESOURCE_SOURCE_COMPONENT_KIND = "resource.source"
STANDARD_CATALOG_ENGINE_COMPONENT_ID = "harness.resources.catalog.standard"
NATIVE_RESOURCE_SOURCE_COMPONENT_ID = "harness.resources.source.native"

_CAPABILITY_ID = "harness.resources"
_OWNER_ID = "harness"
_FIRST_PARTY_SOURCE_ID = "loushang"
_TRUST_CLASS = "host_builtin"
_TRUST_POLICY_REVISION = "harness-first-party-components-v1"
_ENGINE_REVISION = "builtin:harness.resources.catalog.standard@1"
_SOURCE_REVISION = "builtin:harness.resources.source.native@1"
_CONTAINED_READ_AUTHORITY = "filesystem.read.contained"


class ResourceCatalogComponentError(RuntimeError):
    """Stable Resource owner-component failure with a finite reason."""

    def __init__(self, *, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


@dataclass(frozen=True, slots=True)
class ResourceCatalogCompositionControl:
    """Owner-supplied cancellation/deadline facts excluded from fingerprints."""

    cancelled: bool = False
    deadline_exceeded: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.cancelled, bool):
            raise TypeError("Catalog composition cancellation fact must be a bool")
        if not isinstance(self.deadline_exceeded, bool):
            raise TypeError("Catalog composition deadline fact must be a bool")

    def check(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError
        if self.deadline_exceeded:
            raise ResourceCatalogComponentError(
                code="resource_catalog_proposal_invalid",
                reason="deadline_exceeded",
            )


@runtime_checkable
class ResourceCatalogEngineComponent(Protocol):
    @property
    def binding_fingerprint(self) -> str: ...

    def compose(
        self,
        source_snapshots: Sequence[ResourceSourceSnapshot],
        *,
        catalog_generation: int,
        merge_policy: ResourceMergePolicySnapshot,
        activation_policy: ResourceActivationPolicySnapshot,
        control: ResourceCatalogCompositionControl | None = None,
    ) -> ResourceCatalogSnapshot: ...


@runtime_checkable
class ResourceSourceComponent(Protocol):
    @property
    def source_generation_ref(self) -> ResourceSourceGenerationRef: ...

    def discover_initial(
        self,
        request: NativeResourceDiscoveryRequest,
    ) -> ResourceSourceSnapshot: ...

    def load(
        self,
        handle: ResourceLoadHandle,
    ) -> ResourceBodyRead | Awaitable[ResourceBodyRead]: ...


@dataclass(frozen=True, slots=True)
class StandardResourceCatalogEngine:
    """Executable wrapper around the pure standard Catalog algorithm."""

    binding_fingerprint: str

    def compose(
        self,
        source_snapshots: Sequence[ResourceSourceSnapshot],
        *,
        catalog_generation: int,
        merge_policy: ResourceMergePolicySnapshot,
        activation_policy: ResourceActivationPolicySnapshot,
        control: ResourceCatalogCompositionControl | None = None,
    ) -> ResourceCatalogSnapshot:
        effective_control = control or ResourceCatalogCompositionControl()
        effective_control.check()
        proposal = compose_resource_catalog(
            source_snapshots,
            catalog_generation=catalog_generation,
            engine_binding_fingerprint=self.binding_fingerprint,
            merge_policy=merge_policy,
            activation_policy=activation_policy,
        )
        effective_control.check()
        return proposal


def validate_resource_catalog_proposal(
    proposal: ResourceCatalogSnapshot,
    *,
    source_snapshots: Sequence[ResourceSourceSnapshot],
    catalog_generation: int,
    engine_binding_fingerprint: str,
    merge_policy: ResourceMergePolicySnapshot,
    activation_policy: ResourceActivationPolicySnapshot,
) -> None:
    """Independently enforce owner policy without holding Catalog state or I/O."""

    if not isinstance(proposal, ResourceCatalogSnapshot):
        raise ResourceCatalogComponentError(
            code="resource_catalog_proposal_invalid",
            reason="untyped_proposal",
        )
    try:
        expected = compose_resource_catalog(
            source_snapshots,
            catalog_generation=catalog_generation,
            engine_binding_fingerprint=engine_binding_fingerprint,
            merge_policy=merge_policy,
            activation_policy=activation_policy,
        )
    except (TypeError, ValueError) as exc:
        raise ResourceCatalogComponentError(
            code="resource_catalog_proposal_invalid",
            reason="owner_recomposition_failed",
        ) from exc
    if proposal != expected:
        raise ResourceCatalogComponentError(
            code="resource_catalog_proposal_invalid",
            reason="owner_policy_mismatch",
        )


RESOURCE_CATALOG_ENGINE_DEFINITION = CapabilityComponentDefinition(
    capability_id=_CAPABILITY_ID,
    owner_id=_OWNER_ID,
    component_kind=RESOURCE_CATALOG_ENGINE_COMPONENT_KIND,
    payload_schema_id="loushang.resource.catalog-engine",
    payload_schema_version=1,
    compatible_bundle_contract=CapabilityContractRange.exact(1),
    multiplicity="exclusive",
    selection_policy="exactly_one",
    minimum_count=1,
    maximum_count=1,
    disposer_contract="optional",
)

RESOURCE_SOURCE_DEFINITION = CapabilityComponentDefinition(
    capability_id=_CAPABILITY_ID,
    owner_id=_OWNER_ID,
    component_kind=RESOURCE_SOURCE_COMPONENT_KIND,
    payload_schema_id="loushang.resource.source",
    payload_schema_version=1,
    compatible_bundle_contract=CapabilityContractRange.exact(1),
    multiplicity="aggregate",
    selection_policy="ordered_unique",
    minimum_count=1,
    maximum_count=None,
    disposer_contract="required",
)


@dataclass(frozen=True, slots=True)
class FirstPartyResourceComponentResolution:
    """Complete inert chain and exact first-party Bindings for one shadow run."""

    definitions: tuple[CapabilityComponentDefinition, ...]
    authorities: tuple[CapabilityComponentOwnerAuthority, ...] = field(
        repr=False,
        compare=False,
    )
    candidates: tuple[CapabilityComponentCandidate, ...]
    admissions: tuple[CapabilityComponentAdmission, ...] = field(repr=False)
    resolved_set: ResolvedCapabilityComponentSet
    bindings: tuple[CapabilityOwnerComponentBinding, ...] = field(
        repr=False,
        compare=False,
    )


def resolve_first_party_resource_components(
    *,
    product_id: str,
    scope_id: str,
    product_policy_revision: str,
    root_handles: tuple[NativeResourceRootHandle, ...],
    issued_at: int,
    expires_at: int,
    now: int,
) -> FirstPartyResourceComponentResolution:
    """Build Definition -> admission -> selection -> Binding without publication."""

    canonical_roots = tuple(sorted(root_handles, key=lambda item: item.handle_id))
    if len({item.handle_id for item in canonical_roots}) != len(canonical_roots):
        raise ValueError("First-party native root handles must not repeat")
    definitions = (
        RESOURCE_CATALOG_ENGINE_DEFINITION,
        RESOURCE_SOURCE_DEFINITION,
    )
    engine_authority = CapabilityComponentOwnerAuthority(
        RESOURCE_CATALOG_ENGINE_DEFINITION,
        CapabilityComponentOwnerPolicy(
            capability_id=_CAPABILITY_ID,
            owner_id=_OWNER_ID,
            component_kind=RESOURCE_CATALOG_ENGINE_COMPONENT_KIND,
            policy_revision="harness-resource-catalog-engine-owner-v1",
            revocation_epoch=0,
            allowed_component_ids=(STANDARD_CATALOG_ENGINE_COMPONENT_ID,),
            allowed_source_trust_classes=(_TRUST_CLASS,),
        ),
    )
    source_authority = CapabilityComponentOwnerAuthority(
        RESOURCE_SOURCE_DEFINITION,
        CapabilityComponentOwnerPolicy(
            capability_id=_CAPABILITY_ID,
            owner_id=_OWNER_ID,
            component_kind=RESOURCE_SOURCE_COMPONENT_KIND,
            policy_revision="harness-resource-source-owner-v1",
            revocation_epoch=0,
            allowed_component_ids=(NATIVE_RESOURCE_SOURCE_COMPONENT_ID,),
            allowed_source_trust_classes=(_TRUST_CLASS,),
            authority_ceiling=(_CONTAINED_READ_AUTHORITY,),
        ),
    )
    engine_spec = CapabilityComponentBindingSpec(
        source_kind="first_party",
        source_id=_FIRST_PARTY_SOURCE_ID,
        contribution_id=STANDARD_CATALOG_ENGINE_COMPONENT_ID,
        source_revision_ref=_ENGINE_REVISION,
        content_digest=fingerprint_catalog_value(
            "loushang.first-party-resource-component/v1",
            {"implementation": _ENGINE_REVISION},
        ),
        binding_inputs={"algorithmRevision": "resource-catalog-v2"},
    )
    source_spec = CapabilityComponentBindingSpec(
        source_kind="first_party",
        source_id=_FIRST_PARTY_SOURCE_ID,
        contribution_id=NATIVE_RESOURCE_SOURCE_COMPONENT_ID,
        source_revision_ref=_SOURCE_REVISION,
        content_digest=fingerprint_catalog_value(
            "loushang.first-party-resource-component/v1",
            {"implementation": _SOURCE_REVISION},
        ),
        binding_inputs={
            "rootPolicies": [item.policy_payload() for item in canonical_roots],
            "sourceContractRevision": "native-resource-source-v1",
        },
    )
    engine_candidate = _candidate(
        definition=RESOURCE_CATALOG_ENGINE_DEFINITION,
        component_id=STANDARD_CATALOG_ENGINE_COMPONENT_ID,
        binding_spec=engine_spec,
        product_id=product_id,
        scope_id=scope_id,
        product_policy_revision=product_policy_revision,
    )
    source_candidate = _candidate(
        definition=RESOURCE_SOURCE_DEFINITION,
        component_id=NATIVE_RESOURCE_SOURCE_COMPONENT_ID,
        binding_spec=source_spec,
        product_id=product_id,
        scope_id=scope_id,
        product_policy_revision=product_policy_revision,
        requested_authorities=(_CONTAINED_READ_AUTHORITY,),
    )
    engine_admission = engine_authority.admit(
        engine_candidate,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    source_admission = source_authority.admit(
        source_candidate,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    admissions = (engine_admission, source_admission)
    plan = CapabilityComponentSelectionPlan(
        product_id=product_id,
        scope_id=scope_id,
        capability_id=_CAPABILITY_ID,
        owner_id=_OWNER_ID,
        product_policy_revision=product_policy_revision,
        choices=(
            CapabilityComponentSelectionChoice(
                component_kind=RESOURCE_CATALOG_ENGINE_COMPONENT_KIND,
                admission_fingerprints=(engine_admission.fingerprint,),
            ),
            CapabilityComponentSelectionChoice(
                component_kind=RESOURCE_SOURCE_COMPONENT_KIND,
                admission_fingerprints=(source_admission.fingerprint,),
            ),
        ),
    )
    resolved = ProductCapabilityComponentResolver().resolve(
        plan,
        definitions=definitions,
        admissions=admissions,
        owner_snapshots=(
            engine_authority.snapshot(),
            source_authority.snapshot(),
        ),
        now=now,
    )
    bindings = tuple(
        _first_party_binding(component, root_handles=canonical_roots)
        for component in resolved.components
    )
    return FirstPartyResourceComponentResolution(
        definitions=definitions,
        authorities=(engine_authority, source_authority),
        candidates=(engine_candidate, source_candidate),
        admissions=admissions,
        resolved_set=resolved,
        bindings=bindings,
    )


def _candidate(
    *,
    definition: CapabilityComponentDefinition,
    component_id: str,
    binding_spec: CapabilityComponentBindingSpec,
    product_id: str,
    scope_id: str,
    product_policy_revision: str,
    requested_authorities: tuple[str, ...] = (),
) -> CapabilityComponentCandidate:
    return CapabilityComponentCandidate(
        definition=definition,
        component_id=component_id,
        binding_spec=binding_spec,
        product_id=product_id,
        scope_id=scope_id,
        product_policy_revision=product_policy_revision,
        source_trust_class=_TRUST_CLASS,
        source_trust_policy_revision=_TRUST_POLICY_REVISION,
        source_trusted=True,
        requested_authorities=requested_authorities,
    )


def _first_party_binding(
    component: ResolvedCapabilityComponent,
    *,
    root_handles: tuple[NativeResourceRootHandle, ...],
) -> CapabilityOwnerComponentBinding:
    if not isinstance(component, ResolvedCapabilityComponent):
        raise TypeError("First-party Binding requires a resolved component")
    binding_fingerprint = owner_component_binding_fingerprint(component)
    if component.definition.component_kind == RESOURCE_CATALOG_ENGINE_COMPONENT_KIND:

        def create_engine(
            _context: CapabilityOwnerComponentContext,
        ) -> StandardResourceCatalogEngine:
            return StandardResourceCatalogEngine(binding_fingerprint)

        return CapabilityOwnerComponentBinding(
            resolved=component,
            binding_fingerprint=binding_fingerprint,
            create=create_engine,
            validate_payload=_validate_engine_payload,
        )
    if component.definition.component_kind != RESOURCE_SOURCE_COMPONENT_KIND:
        raise ValueError("Unknown first-party Resource component kind")

    def create_source(
        context: CapabilityOwnerComponentContext,
    ) -> NativeFilesystemResourceSource:
        candidate = context.resolved.admission.candidate
        producer = ResourceComponentProducer(
            component_contribution_id=candidate.binding_spec.contribution_id,
            component_candidate_fingerprint=candidate.fingerprint,
            component_admission_fingerprint=context.resolved.admission_fingerprint,
            binding_fingerprint=binding_fingerprint,
            # RCP1 froze this legacy field name before first-party components
            # existed.  The value is an explicit first-party revision, never a
            # PluginInstanceRevisionRef or package provenance claim.
            plugin_instance_revision_ref=candidate.binding_spec.source_revision_ref,
            package_content_digest=candidate.binding_spec.content_digest,
        )
        source_ref = build_native_source_generation_ref(
            source_id=NATIVE_RESOURCE_SOURCE_COMPONENT_ID,
            product_id=context.product_id,
            runtime_id=context.runtime_id,
            owner_generation=context.owner_generation,
            producer=producer,
            component_binding_fingerprint=binding_fingerprint,
            root_handles=root_handles,
        )
        return NativeFilesystemResourceSource(
            source_generation_ref=source_ref,
            root_handles=root_handles,
        )

    def dispose_source(value: CapabilityOwnerComponentValue) -> None:
        payload = value.payload
        _validate_source_payload(payload)
        assert isinstance(payload, NativeFilesystemResourceSource)
        payload.dispose()

    return CapabilityOwnerComponentBinding(
        resolved=component,
        binding_fingerprint=binding_fingerprint,
        create=create_source,
        validate_payload=_validate_source_payload,
        dispose=dispose_source,
    )


def _validate_engine_payload(payload: object) -> None:
    if not isinstance(payload, ResourceCatalogEngineComponent):
        raise TypeError("Catalog engine payload does not implement its protocol")


def _validate_source_payload(payload: object) -> None:
    if not isinstance(payload, ResourceSourceComponent):
        raise TypeError("Resource source payload does not implement its protocol")


__all__ = [
    "FirstPartyResourceComponentResolution",
    "NATIVE_RESOURCE_SOURCE_COMPONENT_ID",
    "RESOURCE_CATALOG_ENGINE_COMPONENT_KIND",
    "RESOURCE_CATALOG_ENGINE_DEFINITION",
    "RESOURCE_SOURCE_COMPONENT_KIND",
    "RESOURCE_SOURCE_DEFINITION",
    "ResourceCatalogComponentError",
    "ResourceCatalogCompositionControl",
    "ResourceCatalogEngineComponent",
    "ResourceSourceComponent",
    "STANDARD_CATALOG_ENGINE_COMPONENT_ID",
    "StandardResourceCatalogEngine",
    "resolve_first_party_resource_components",
    "validate_resource_catalog_proposal",
]
