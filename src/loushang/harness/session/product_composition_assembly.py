"""Private Product-root assembly from finalized Plugin selection to compilation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from loushang.harness.capabilities.consumer_requirements import (
    ProductCapabilityConsumerRequirementPreview,
    ProductCapabilityOptionalRequirementChoice,
    ProductCompositionAuthorityContext,
    ProductCompositionCompilation,
    ProductCompositionCompiler,
)
from loushang.harness.capabilities.contracts import CapabilityDefinition
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionRecord,
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerSnapshot,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderChoice,
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
    ResolvedCapabilityProvider,
    ResolvedCapabilityProviderSet,
)
from loushang.harness.capabilities.providers import CapabilityBundleProvider
from loushang.harness.plugin_authoring.contribution_admission import (
    prepare_owner_contribution_candidate,
)
from loushang.harness.plugin_authoring.provider_admission import (
    prepare_capability_provider_candidate,
)
from loushang.harness.resources.plugins.selection import (
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
    PublishedPluginPackage,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityComponentRequest,
    SessionCapabilityCompositionInputs,
    validate_session_capability_composition_closure,
)

ProductOptionalRequirementSelector = Callable[
    [ProductCapabilityConsumerRequirementPreview],
    tuple[ProductCapabilityOptionalRequirementChoice, ...],
]
ProductCapabilityProviderSelector = Callable[
    [tuple[CapabilityProviderAdmissionRecord, ...]],
    tuple[ProductCapabilityProviderChoice, ...],
]
_EXTERNAL_CONTRIBUTION_KINDS = frozenset({"resource_item", "tool_pack", "command_pack"})


class ProductCompositionAssemblyError(RuntimeError):
    """Stable Product-visible failure before contribution admission completes."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        owner_keys: tuple[tuple[str, str, str], ...] = (),
        capability_ids: tuple[str, ...] = (),
    ) -> None:
        self.code = code
        self.owner_keys = tuple(sorted(owner_keys))
        self.capability_ids = tuple(sorted(capability_ids))
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ProductContributionOwnerBinding:
    """One explicitly supplied exact owner plus its bounded admission lifetime."""

    authority: OwnerContributionAuthority = field(repr=False, compare=False)
    admission_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        if not isinstance(self.authority, OwnerContributionAuthority):
            raise TypeError("Product contribution owner authority is invalid")
        if isinstance(self.admission_ttl_seconds, bool) or not isinstance(
            self.admission_ttl_seconds,
            int,
        ):
            raise TypeError("Product contribution admission TTL must be an integer")
        if self.admission_ttl_seconds < 1:
            raise ValueError("Product contribution admission TTL must be positive")

    @property
    def owner_key(self) -> tuple[str, str, str]:
        policy = self.authority.policy
        return (policy.owner_id, policy.contribution_kind, policy.product_id)

    def admit(
        self,
        candidate: OwnerContributionCandidateEnvelope,
        *,
        evaluated_at: int,
    ) -> OwnerContributionAdmissionRecord:
        return self.authority.admit(
            candidate,
            issued_at=evaluated_at,
            expires_at=evaluated_at + self.admission_ttl_seconds * 1_000,
        )


@dataclass(frozen=True, slots=True)
class ProductCompositionAssemblyRequest:
    """Product-owned inert inputs for one exact contribution compilation."""

    selection: PluginSelection
    owner_bindings: tuple[ProductContributionOwnerBinding, ...]
    mandatory_roots: tuple[str, ...]
    definitions: tuple[CapabilityDefinition, ...]
    select_optional_requirements: ProductOptionalRequirementSelector = field(
        default=lambda _preview: (),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.selection, PluginSelection):
            raise TypeError("Product composition assembly requires PluginSelection")
        bindings = tuple(self.owner_bindings)
        if any(
            not isinstance(item, ProductContributionOwnerBinding) for item in bindings
        ):
            raise TypeError("Product composition owner bindings are invalid")
        if len({item.owner_key for item in bindings}) != len(bindings):
            raise ValueError("Product composition owner bindings must be unique")
        mandatory_roots = tuple(self.mandatory_roots)
        definitions = tuple(self.definitions)
        if any(not isinstance(item, str) for item in mandatory_roots):
            raise TypeError("Product composition mandatory roots are invalid")
        if any(not isinstance(item, CapabilityDefinition) for item in definitions):
            raise TypeError("Product composition Definitions are invalid")
        if not callable(self.select_optional_requirements):
            raise TypeError("Product optional requirement selector must be callable")
        object.__setattr__(self, "owner_bindings", bindings)
        object.__setattr__(self, "mandatory_roots", mandatory_roots)
        object.__setattr__(self, "definitions", definitions)


@dataclass(frozen=True, slots=True)
class ProductPluginPlanSeed:
    """Inert Product plan plus exact package and owner evidence.

    This value deliberately carries no :class:`PluginSelection`. Products may
    merge plan fragments while packages are still being discovered, then run
    the declaration host exactly once after the complete package set is known.
    """

    plan: PluginSelectionPlanV2
    packages: tuple[PublishedPluginPackage, ...]
    bindings: tuple[PluginSourceBinding, ...]
    owner_bindings: tuple[ProductContributionOwnerBinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan, PluginSelectionPlanV2):
            raise TypeError("Product Plugin seed plan is invalid")
        packages, bindings, owners = _validate_product_plugin_seed_evidence(
            plugin_ids=self.plan.selected_plugin_ids,
            packages=self.packages,
            bindings=self.bindings,
            owner_bindings=self.owner_bindings,
        )
        object.__setattr__(self, "packages", packages)
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "owner_bindings", owners)


@dataclass(frozen=True, slots=True)
class ProductPluginSelectionSeed:
    """One finalized selection plus its exact package and owner evidence."""

    selection: PluginSelection
    packages: tuple[PublishedPluginPackage, ...]
    bindings: tuple[PluginSourceBinding, ...]
    owner_bindings: tuple[ProductContributionOwnerBinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.selection, PluginSelection):
            raise TypeError("Product Plugin seed selection is invalid")
        packages, bindings, owners = _validate_product_plugin_seed_evidence(
            plugin_ids=self.selection.plan.selected_plugin_ids,
            packages=self.packages,
            bindings=self.bindings,
            owner_bindings=self.owner_bindings,
        )
        object.__setattr__(self, "packages", packages)
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "owner_bindings", owners)


def _validate_product_plugin_seed_evidence(
    *,
    plugin_ids: tuple[str, ...],
    packages: tuple[PublishedPluginPackage, ...],
    bindings: tuple[PluginSourceBinding, ...],
    owner_bindings: tuple[ProductContributionOwnerBinding, ...],
) -> tuple[
    tuple[PublishedPluginPackage, ...],
    tuple[PluginSourceBinding, ...],
    tuple[ProductContributionOwnerBinding, ...],
]:
    """Validate lineage shared by inert and finalized Product seeds."""

    packages = tuple(packages)
    bindings = tuple(bindings)
    owners = tuple(owner_bindings)
    if not packages or any(
        not isinstance(item, PublishedPluginPackage) for item in packages
    ):
        raise TypeError("Product Plugin seed packages are invalid")
    if len(packages) != len(bindings) or any(
        not isinstance(item, PluginSourceBinding) for item in bindings
    ):
        raise TypeError("Product Plugin seed bindings are invalid")
    if tuple(item.manifest.name for item in packages) != plugin_ids:
        raise ValueError("Product Plugin seed packages do not match plan")
    if tuple(item.plugin_id for item in bindings) != plugin_ids:
        raise ValueError("Product Plugin seed bindings do not match plan")
    for package, binding in zip(packages, bindings, strict=True):
        if (
            binding.content_digest != package.content_digest
            or binding.manifest_digest != package.manifest_digest
            or binding.dependency_lock != package.dependency_lock
        ):
            raise ValueError("Product Plugin seed binding lineage is invalid")
    if any(
        not isinstance(item, ProductContributionOwnerBinding) for item in owners
    ):
        raise TypeError("Product Plugin seed contribution owners are invalid")
    owner_keys = tuple(item.owner_key for item in owners)
    if len(owner_keys) != len(set(owner_keys)):
        raise ValueError("Product Plugin seed contribution owners repeat")
    return packages, bindings, owners


@dataclass(frozen=True, slots=True)
class ProductCapabilityProviderOwnerBinding:
    """One exact Capability owner plus bounded eligibility/admission lifetimes."""

    authority: CapabilityProviderOwnerAuthority = field(repr=False, compare=False)
    eligibility_ttl_seconds: int = 300
    admission_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        if not isinstance(self.authority, CapabilityProviderOwnerAuthority):
            raise TypeError("Product Capability Provider owner authority is invalid")
        for name, value in (
            ("eligibility", self.eligibility_ttl_seconds),
            ("admission", self.admission_ttl_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"Product Provider {name} TTL must be an integer")
            if value < 1:
                raise ValueError(f"Product Provider {name} TTL must be positive")
        if self.admission_ttl_seconds > self.eligibility_ttl_seconds:
            raise ValueError(
                "Product Provider admission TTL cannot exceed eligibility TTL"
            )

    @property
    def capability_id(self) -> str:
        return self.authority.policy.capability_id

    def admit(
        self,
        candidate: CapabilityProviderCandidateEnvelope,
        *,
        evaluated_at: int,
    ) -> CapabilityProviderAdmissionRecord:
        eligibility = self.authority.grant_eligibility(
            candidate,
            issued_at=evaluated_at,
            expires_at=evaluated_at + self.eligibility_ttl_seconds * 1_000,
        )
        return self.authority.admit(
            candidate,
            eligibility=eligibility,
            issued_at=evaluated_at,
            expires_at=evaluated_at + self.admission_ttl_seconds * 1_000,
        )


@dataclass(frozen=True, slots=True)
class ProductPluginCompositionAssemblyRequest:
    """Product-owned exact Provider and external-contribution assembly inputs."""

    contribution_request: ProductCompositionAssemblyRequest
    provider_owner_bindings: tuple[ProductCapabilityProviderOwnerBinding, ...]
    provider_roots: tuple[str, ...]
    host_capability_ids: tuple[str, ...]
    select_capability_providers: ProductCapabilityProviderSelector = field(
        repr=False,
        compare=False,
    )
    prebound_providers: tuple[CapabilityBundleProvider, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.contribution_request,
            ProductCompositionAssemblyRequest,
        ):
            raise TypeError("Product Plugin composition request is invalid")
        bindings = tuple(self.provider_owner_bindings)
        if any(
            not isinstance(item, ProductCapabilityProviderOwnerBinding)
            for item in bindings
        ):
            raise TypeError("Product Capability Provider owner bindings are invalid")
        if len({item.capability_id for item in bindings}) != len(bindings):
            raise ValueError(
                "Product Capability Provider owner bindings must be unique"
            )
        roots = tuple(self.provider_roots)
        if any(not isinstance(item, str) for item in roots):
            raise TypeError("Product Capability Provider roots are invalid")
        host_ids = tuple(self.host_capability_ids)
        if any(not isinstance(item, str) for item in host_ids):
            raise TypeError("Product host Capability ids are invalid")
        host_ids = tuple(sorted(item.strip() for item in host_ids))
        if any(not item for item in host_ids):
            raise ValueError("Product host Capability ids must not be empty")
        if len(host_ids) != len(set(host_ids)):
            raise ValueError("Product host Capability ids must be unique")
        prebound = tuple(self.prebound_providers)
        if any(not isinstance(item, CapabilityBundleProvider) for item in prebound):
            raise TypeError("Product prebound Capability Providers are invalid")
        if not callable(self.select_capability_providers):
            raise TypeError("Product Capability Provider selector must be callable")
        object.__setattr__(self, "provider_owner_bindings", bindings)
        object.__setattr__(self, "provider_roots", roots)
        object.__setattr__(self, "host_capability_ids", host_ids)
        object.__setattr__(self, "prebound_providers", prebound)


@dataclass(frozen=True, slots=True)
class ProductCapabilityComponentCandidate:
    """Resolved Provider facts awaiting one Approval-owner activation decision."""

    resolved: ResolvedCapabilityProvider
    package: PublishedPluginPackage = field(repr=False, compare=False)
    owner_snapshot: CapabilityProviderOwnerSnapshot
    trust_snapshot: PluginSourceTrustSnapshotV1

    def __post_init__(self) -> None:
        if not isinstance(self.resolved, ResolvedCapabilityProvider):
            raise TypeError("Product component candidate requires a Provider")
        if not isinstance(self.package, PublishedPluginPackage):
            raise TypeError("Product component candidate requires a package")
        if not isinstance(self.owner_snapshot, CapabilityProviderOwnerSnapshot):
            raise TypeError("Product component candidate owner snapshot is invalid")
        if not isinstance(self.trust_snapshot, PluginSourceTrustSnapshotV1):
            raise TypeError("Product component candidate trust snapshot is invalid")

    @property
    def capability_id(self) -> str:
        return self.resolved.capability_id

    def bind_activation(self, decision_id: str) -> SessionCapabilityComponentRequest:
        return SessionCapabilityComponentRequest(
            resolved=self.resolved,
            package=self.package,
            owner_snapshot=self.owner_snapshot,
            trust_snapshot=self.trust_snapshot,
            activation_decision_id=decision_id,
        )


@dataclass(frozen=True, slots=True)
class ProductPluginCompositionAssembly:
    """Compiled Product closure awaiting exact activation-decision binding."""

    product_composition: ProductCompositionCompilation
    resolved_providers: ResolvedCapabilityProviderSet
    component_candidates: tuple[ProductCapabilityComponentCandidate, ...]
    contribution_request: ProductCompositionAssemblyRequest = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.product_composition, ProductCompositionCompilation):
            raise TypeError("Product Plugin composition compilation is invalid")
        if not isinstance(self.resolved_providers, ResolvedCapabilityProviderSet):
            raise TypeError("Product Plugin resolved Providers are invalid")
        if not isinstance(self.contribution_request, ProductCompositionAssemblyRequest):
            raise TypeError("Product Plugin contribution request is invalid")
        selection_context = self.contribution_request.selection.plan.context
        authority_context = self.product_composition.authority_context
        if (
            selection_context.product_id != authority_context.product_id
            or selection_context.scope_id != authority_context.scope_id
            or selection_context.policy_revision
            != authority_context.product_policy_revision
        ):
            raise ValueError("Product Plugin request does not match compilation")
        candidates = tuple(self.component_candidates)
        if any(
            not isinstance(item, ProductCapabilityComponentCandidate)
            for item in candidates
        ):
            raise TypeError("Product Capability component candidates are invalid")
        if tuple(item.resolved for item in candidates) != (
            self.resolved_providers.entries
        ):
            raise ValueError(
                "Product component candidates must retain exact resolved Providers"
            )
        object.__setattr__(self, "component_candidates", candidates)

    def bind_session_inputs(
        self,
        activation_decision_ids: Mapping[str, str],
    ) -> SessionCapabilityCompositionInputs:
        """Bind exact Approval-owner decisions without issuing or inferring them."""

        if not isinstance(activation_decision_ids, Mapping):
            raise TypeError("Product activation decisions must be a mapping")
        if any(not isinstance(item, str) for item in activation_decision_ids):
            raise TypeError("Product activation decision Capability ids are invalid")
        supplied = set(activation_decision_ids)
        required = {item.capability_id for item in self.component_candidates}
        if missing := required - supplied:
            raise ProductCompositionAssemblyError(
                "Product composition is missing a Provider activation decision.",
                code="product_provider_activation_missing",
                capability_ids=tuple(missing),
            )
        if extra := supplied - required:
            raise ProductCompositionAssemblyError(
                "Product composition supplied an unused Provider activation decision.",
                code="product_provider_activation_extra",
                capability_ids=tuple(extra),
            )
        return SessionCapabilityCompositionInputs(
            product_composition=self.product_composition,
            resolved_providers=self.resolved_providers,
            component_requests=tuple(
                item.bind_activation(activation_decision_ids[item.capability_id])
                for item in self.component_candidates
            ),
        )


@dataclass(frozen=True, slots=True)
class _PreparedCapabilityProviderCandidate:
    candidate: CapabilityProviderCandidateEnvelope
    package: PublishedPluginPackage = field(repr=False, compare=False)
    trust_snapshot: PluginSourceTrustSnapshotV1


@dataclass(frozen=True, slots=True)
class ProductPluginCompositionPreparation:
    """One compiled Product closure awaiting only host Provider bindings.

    Product contribution admission and compilation happen exactly once.  A
    Product may then construct its host-owned Provider values and bind them to
    the already compiled closure without rebuilding or merging composition
    evidence.
    """

    request: ProductPluginCompositionAssemblyRequest = field(
        repr=False,
        compare=False,
    )
    product_composition: ProductCompositionCompilation
    provider_admissions: tuple[CapabilityProviderAdmissionRecord, ...]
    provider_candidates: tuple[_PreparedCapabilityProviderCandidate, ...] = field(
        repr=False,
        compare=False,
    )
    provider_choices: tuple[ProductCapabilityProviderChoice, ...]
    evaluated_at: int

    def bind_host_providers(
        self,
        prebound_providers: tuple[CapabilityBundleProvider, ...] | None = None,
    ) -> ProductPluginCompositionAssembly:
        """Resolve the exact prepared closure against Product host Providers."""

        request = self.request
        supplied_prebound = (
            request.prebound_providers
            if prebound_providers is None
            else tuple(prebound_providers)
        )
        if any(
            not isinstance(item, CapabilityBundleProvider) for item in supplied_prebound
        ):
            raise TypeError("Product prebound Capability Providers are invalid")
        contribution_request = request.contribution_request
        selection = contribution_request.selection
        resolved = ProductCapabilityProviderResolver().resolve(
            ProductCapabilityProviderSelectionPlanV1(
                product_id=selection.plan.context.product_id,
                roots=request.provider_roots,
                choices=self.provider_choices,
                policy_revision=selection.plan.context.policy_revision,
            ),
            definitions=contribution_request.definitions,
            admissions=self.provider_admissions,
            owner_snapshots=tuple(
                item.authority.snapshot() for item in request.provider_owner_bindings
            ),
            evaluated_at=self.evaluated_at,
            prebound_providers=supplied_prebound,
        )
        validate_session_capability_composition_closure(
            self.product_composition,
            resolved,
            host_capability_ids=request.host_capability_ids,
            host_providers=supplied_prebound,
        )
        bindings_by_capability = {
            item.capability_id: item for item in request.provider_owner_bindings
        }
        component_facts = {
            admission.candidate_fingerprint: (
                prepared.package,
                bindings_by_capability[admission.capability_id].authority.snapshot(),
                prepared.trust_snapshot,
            )
            for admission, prepared in zip(
                self.provider_admissions,
                self.provider_candidates,
                strict=True,
            )
        }
        return ProductPluginCompositionAssembly(
            product_composition=self.product_composition,
            resolved_providers=resolved,
            component_candidates=tuple(
                ProductCapabilityComponentCandidate(
                    resolved=item,
                    package=component_facts[item.admission.candidate_fingerprint][0],
                    owner_snapshot=component_facts[
                        item.admission.candidate_fingerprint
                    ][1],
                    trust_snapshot=component_facts[
                        item.admission.candidate_fingerprint
                    ][2],
                )
                for item in resolved.entries
            ),
            contribution_request=contribution_request,
        )


def assemble_product_composition(
    request: ProductCompositionAssemblyRequest,
    *,
    evaluated_at: int,
) -> ProductCompositionCompilation:
    """Admit one finalized selection through exact owners, then compile once."""

    if not isinstance(request, ProductCompositionAssemblyRequest):
        raise TypeError("Product composition assembly request is invalid")
    if isinstance(evaluated_at, bool) or not isinstance(evaluated_at, int):
        raise TypeError("Product composition evaluation time must be an integer")
    if evaluated_at < 0:
        raise ValueError("Product composition evaluation time cannot be negative")

    selection = request.selection
    candidates = tuple(
        prepare_owner_contribution_candidate(selection, item)
        for item in selection.candidates
        if item.declaration.kind in _EXTERNAL_CONTRIBUTION_KINDS
    )
    bindings_by_key = {item.owner_key: item for item in request.owner_bindings}
    required_keys = {
        (item.owner_id, item.contribution_kind, item.product_id) for item in candidates
    }
    supplied_keys = set(bindings_by_key)
    if missing := required_keys - supplied_keys:
        raise ProductCompositionAssemblyError(
            "Product composition is missing an exact contribution owner.",
            code="product_contribution_owner_missing",
            owner_keys=tuple(missing),
        )
    if extra := supplied_keys - required_keys:
        raise ProductCompositionAssemblyError(
            "Product composition supplied an unused contribution owner.",
            code="product_contribution_owner_extra",
            owner_keys=tuple(extra),
        )

    admissions = tuple(
        bindings_by_key[
            (candidate.owner_id, candidate.contribution_kind, candidate.product_id)
        ].admit(candidate, evaluated_at=evaluated_at)
        for candidate in candidates
    )
    owner_snapshots = tuple(
        item.authority.snapshot() for item in request.owner_bindings
    )
    context = selection.plan.context
    authority_context = ProductCompositionAuthorityContext(
        product_id=context.product_id,
        scope_id=context.scope_id,
        product_policy_revision=context.policy_revision,
        evaluated_at=evaluated_at,
        owner_snapshots=owner_snapshots,
        trust_snapshots=selection.plan.source_trust_snapshots,
    )
    compiler = ProductCompositionCompiler()
    preview = compiler.preview_optional_choices(
        authority_context=authority_context,
        mandatory_roots=request.mandatory_roots,
        admissions=admissions,
        definitions=request.definitions,
    )
    optional_choices = tuple(request.select_optional_requirements(preview))
    return compiler.compile(
        authority_context=authority_context,
        mandatory_roots=request.mandatory_roots,
        admissions=admissions,
        definitions=request.definitions,
        optional_choices=optional_choices,
    )


def prepare_product_plugin_composition(
    request: ProductPluginCompositionAssemblyRequest,
    *,
    evaluated_at: int,
) -> ProductPluginCompositionPreparation:
    """Compile and admit once before Product host Providers are constructed."""

    if not isinstance(request, ProductPluginCompositionAssemblyRequest):
        raise TypeError("Product Plugin composition assembly request is invalid")
    if isinstance(evaluated_at, bool) or not isinstance(evaluated_at, int):
        raise TypeError("Product Plugin composition time must be an integer")
    if evaluated_at < 0:
        raise ValueError("Product Plugin composition time cannot be negative")

    contribution_request = request.contribution_request
    selection = contribution_request.selection
    definitions_by_id = {
        item.capability_id: item for item in contribution_request.definitions
    }
    if len(definitions_by_id) != len(contribution_request.definitions):
        raise ValueError("Product Plugin Capability definitions must be unique")
    trust_by_plugin = {
        item.plugin_id: item for item in selection.plan.source_trust_snapshots
    }
    provider_candidates: list[
        tuple[
            CapabilityProviderCandidateEnvelope,
            PublishedPluginPackage,
            PluginSourceTrustSnapshotV1,
        ]
    ] = []
    for selected in selection.candidates:
        if selected.declaration.kind != "capability_provider":
            continue
        capability_id = selected.declaration.owner
        definition = definitions_by_id.get(capability_id)
        if definition is None:
            raise ProductCompositionAssemblyError(
                "Product composition has no Definition for a selected Provider.",
                code="product_provider_definition_missing",
                capability_ids=(capability_id,),
            )
        candidate = prepare_capability_provider_candidate(
            selection,
            selected,
            definition=definition,
        )
        trust = trust_by_plugin.get(candidate.binding_spec.plugin_id)
        if trust is None:
            raise ProductCompositionAssemblyError(
                "Product composition Provider trust provenance is missing.",
                code="product_provider_trust_missing",
                capability_ids=(candidate.provider.capability_id,),
            )
        provider_candidates.append((candidate, selected.package, trust))

    bindings_by_capability = {
        item.capability_id: item for item in request.provider_owner_bindings
    }
    required_capabilities = {
        item.provider.capability_id for item, _package, _trust in provider_candidates
    }
    supplied_capabilities = set(bindings_by_capability)
    if missing := required_capabilities - supplied_capabilities:
        raise ProductCompositionAssemblyError(
            "Product composition is missing an exact Capability Provider owner.",
            code="product_provider_owner_missing",
            capability_ids=tuple(missing),
        )
    if extra := supplied_capabilities - required_capabilities:
        raise ProductCompositionAssemblyError(
            "Product composition supplied an unused Capability Provider owner.",
            code="product_provider_owner_extra",
            capability_ids=tuple(extra),
        )

    product_composition = assemble_product_composition(
        contribution_request,
        evaluated_at=evaluated_at,
    )
    provider_admissions = tuple(
        bindings_by_capability[candidate.provider.capability_id].admit(
            candidate,
            evaluated_at=evaluated_at,
        )
        for candidate, _package, _trust in provider_candidates
    )
    return ProductPluginCompositionPreparation(
        request=request,
        product_composition=product_composition,
        provider_admissions=provider_admissions,
        provider_candidates=tuple(
            _PreparedCapabilityProviderCandidate(
                candidate=candidate,
                package=package,
                trust_snapshot=trust,
            )
            for candidate, package, trust in provider_candidates
        ),
        provider_choices=tuple(
            request.select_capability_providers(provider_admissions)
        ),
        evaluated_at=evaluated_at,
    )


def assemble_product_plugin_composition(
    request: ProductPluginCompositionAssemblyRequest,
    *,
    evaluated_at: int,
) -> ProductPluginCompositionAssembly:
    """Compile external Consumers and bind Product host Providers atomically."""

    return prepare_product_plugin_composition(
        request,
        evaluated_at=evaluated_at,
    ).bind_host_providers()


__all__: list[str] = []
