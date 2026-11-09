"""Private Product-root assembly from finalized Plugin selection to compilation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol, cast

from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCapabilityConsumerRequirementPreview,
    ProductCapabilityOptionalRequirementChoice,
    ProductCompositionAuthorityContext,
    ProductCompositionCompilation,
    ProductCompositionCompiler,
)
from loushang.harness.capabilities.contracts import (
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.contribution_admission import (
    CatalogConsumerContributionSpec,
    OwnerContributionAdmissionRecord,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionKind,
    ResourceContributionSpec,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderAdmissionRecord,
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerSnapshot,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
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
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.plugin_authoring.provider_admission import (
    prepare_capability_provider_candidate,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources.plugins.contribution_types import (
    PLUGIN_OWNER_CONTRIBUTION_KINDS,
)
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
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
    SessionCapabilityWorkerComponentRequest,
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


@dataclass(frozen=True, slots=True)
class _WorkerSessionComposition:
    """Join one admitted Worker without replacing ordinary Session facts.

    Product policy supplies only its identity, Consumer contract and legacy
    errors. Compilation, selection and closure retain their existing owners.
    This object owns no activation, process or graph-publication lifetime.
    """

    product_id: str
    worker_requirement: CapabilityRequirement
    error_type: type[RuntimeError]
    error_prefix: str
    invalid_composition_inputs: str
    invalid_session_inputs: str

    def compose(
        self,
        *,
        ordinary: SessionCapabilityCompositionInputs,
        worker: SessionCapabilityCompositionInputs,
        definitions: tuple[CapabilityDefinition, ...],
        workspace_binding: CapabilityBundleProviderBinding,
    ) -> SessionCapabilityCompositionInputs:
        """Recompile one Product graph containing ordinary and selected Worker facts.

        The Worker-only query graph cannot be spliced into an ordinary Session. This
        function retains both sets of owner-issued admissions, resolves their
        Providers together, and returns requests bound to that single resolution.
        It does not activate a Worker or authorize an ordinary Session route.
        """

        if (
            not isinstance(ordinary, SessionCapabilityCompositionInputs)
            or not isinstance(worker, SessionCapabilityCompositionInputs)
            or not isinstance(workspace_binding, CapabilityBundleProviderBinding)
            or workspace_binding.provider.capability_id
            != WORKSPACE_CAPABILITY_DEFINITION.capability_id
            or any(not isinstance(item, CapabilityDefinition) for item in definitions)
        ):
            raise TypeError(self.invalid_composition_inputs)
        base_context = ordinary.product_composition.authority_context
        worker_context = worker.product_composition.authority_context
        worker_request = (
            worker.component_requests[0]
            if len(worker.component_requests) == 1
            else None
        )
        if (
            base_context.product_id != self.product_id
            or worker_context.product_id != self.product_id
            or base_context.scope_id != worker_context.scope_id
            or base_context.product_policy_revision
            != worker_context.product_policy_revision
            or base_context.evaluated_at != worker_context.evaluated_at
            or ordinary.resolved_providers.evaluated_at
            != worker.resolved_providers.evaluated_at
            or ordinary.resolved_providers.evaluated_at != base_context.evaluated_at
            or not isinstance(worker_request, SessionCapabilityWorkerComponentRequest)
            or worker.resolved_providers.prebound_providers
            or worker.product_composition.resource_admissions
            or worker.product_composition.catalog_admissions
            or worker.product_composition.consumer_requirements.optional_choices
            or worker.product_composition.consumer_requirements.entries
            or worker_context.owner_snapshots
            or worker_context.trust_snapshots != (worker_request.trust_snapshot,)
        ):
            raise self._failure("ordinary_composition_authority_mismatch")
        assert isinstance(worker_request, SessionCapabilityWorkerComponentRequest)
        worker_id = worker_request.capability_id
        worker_roots = worker.product_composition.consumer_requirements
        if (
            worker_roots.mandatory_roots
            != tuple(
                sorted((MODEL_INPUT_CAPABILITY_DEFINITION.capability_id, worker_id))
            )
            or worker_roots.roots != worker_roots.mandatory_roots
            or worker_id in ordinary.product_composition.consumer_requirements.roots
            or worker_id
            in {item.capability_id for item in ordinary.resolved_providers.entries}
            or worker.resolved_providers.roots != (worker_id,)
        ):
            raise self._failure("ordinary_composition_overlap")
        self._validate_closure(
            ordinary.product_composition, ordinary.resolved_providers, workspace_binding
        )
        base_requirements = ordinary.product_composition.consumer_requirements
        if (
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id
            not in base_requirements.mandatory_roots
            or WORKSPACE_CAPABILITY_DEFINITION.capability_id
            not in base_requirements.roots
        ):
            raise self._failure("ordinary_composition_base_missing")
        trust_by_key = {
            (item.plugin_id, item.package_source_identity): item
            for item in base_context.trust_snapshots
        }
        worker_trust = worker_request.trust_snapshot
        trust_key = (worker_trust.plugin_id, worker_trust.package_source_identity)
        if trust_key in trust_by_key and trust_by_key[trust_key] != worker_trust:
            raise self._failure("ordinary_composition_trust_changed")
        trust_by_key[trust_key] = worker_trust
        combined_context = replace(
            base_context, trust_snapshots=tuple(trust_by_key.values())
        )
        definition_by_id = {item.capability_id: item for item in definitions}
        if (
            len(definition_by_id) != len(definitions)
            or definition_by_id.get(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id)
            != MODEL_INPUT_CAPABILITY_DEFINITION
            or definition_by_id.get(WORKSPACE_CAPABILITY_DEFINITION.capability_id)
            != WORKSPACE_CAPABILITY_DEFINITION
            or any(
                definition_by_id.get(item.capability_id) != item.definition
                for item in (
                    *ordinary.resolved_providers.entries,
                    *worker.resolved_providers.entries,
                )
            )
        ):
            raise self._failure("ordinary_composition_definition_mismatch")
        compilation = ProductCompositionCompiler().compile(
            authority_context=combined_context,
            mandatory_roots=tuple(
                sorted((*base_requirements.mandatory_roots, worker_id))
            ),
            admissions=(
                *ordinary.product_composition.resource_admissions,
                *ordinary.product_composition.catalog_admissions,
            ),
            definitions=definitions,
            optional_choices=base_requirements.optional_choices,
        )
        prior_entries = (
            *ordinary.resolved_providers.entries,
            *worker.resolved_providers.entries,
        )
        roots = tuple(sorted((*ordinary.resolved_providers.roots, worker_id)))
        resolved = ProductCapabilityProviderResolver().resolve(
            ProductCapabilityProviderSelectionPlanV1(
                product_id=self.product_id,
                roots=roots,
                choices=tuple(
                    sorted(
                        (item.choice for item in prior_entries),
                        key=lambda item: item.capability_id,
                    )
                ),
                policy_revision=base_context.product_policy_revision,
            ),
            definitions=definitions,
            admissions=tuple(item.admission for item in prior_entries),
            owner_snapshots=tuple(
                item.owner_snapshot
                for item in (*ordinary.component_requests, *worker.component_requests)
            ),
            evaluated_at=base_context.evaluated_at,
            prebound_providers=ordinary.resolved_providers.prebound_providers,
        )
        selected = {item.capability_id: item for item in resolved.entries}
        if (
            any(selected.get(item.capability_id) != item for item in prior_entries)
            or resolved.prebound_providers
            != ordinary.resolved_providers.prebound_providers
            or not set(ordinary.resolved_providers.optional_decisions).issubset(
                resolved.optional_decisions
            )
            or not set(worker.resolved_providers.optional_decisions).issubset(
                resolved.optional_decisions
            )
            or compilation.resource_admissions
            != ordinary.product_composition.resource_admissions
            or compilation.catalog_admissions
            != ordinary.product_composition.catalog_admissions
            or compilation.consumer_requirements.entries != base_requirements.entries
        ):
            raise self._failure("ordinary_composition_selection_changed")
        self._validate_closure(compilation, resolved, workspace_binding)
        requests = tuple(
            sorted(
                (
                    replace(item, resolved=selected[item.capability_id])
                    for item in (
                        *ordinary.component_requests,
                        *worker.component_requests,
                    )
                ),
                key=lambda item: item.capability_id,
            )
        )
        return SessionCapabilityCompositionInputs(
            product_composition=compilation,
            resolved_providers=resolved,
            component_requests=requests,
            host_consumer_requirements=tuple(
                sorted(
                    (
                        *ordinary.host_consumer_requirements,
                        *worker.host_consumer_requirements,
                    ),
                    key=lambda item: item.capability,
                )
            ),
        )

    def validate(
        self,
        *,
        ordinary: SessionCapabilityCompositionInputs,
        combined: SessionCapabilityCompositionInputs,
        workspace_binding: CapabilityBundleProviderBinding,
    ) -> None:
        """Require one Worker addition while retaining every ordinary Product fact."""

        if (
            not isinstance(ordinary, SessionCapabilityCompositionInputs)
            or not isinstance(combined, SessionCapabilityCompositionInputs)
            or not isinstance(workspace_binding, CapabilityBundleProviderBinding)
        ):
            raise TypeError(self.invalid_session_inputs)
        base = ordinary.product_composition
        merged = combined.product_composition
        base_context = base.authority_context
        merged_context = merged.authority_context
        base_requirements = base.consumer_requirements
        merged_requirements = merged.consumer_requirements
        base_entries = ordinary.resolved_providers.entries
        merged_entries = combined.resolved_providers.entries
        worker_requests = tuple(
            item
            for item in combined.component_requests
            if isinstance(item, SessionCapabilityWorkerComponentRequest)
        )
        base_requests = tuple(
            item
            for item in combined.component_requests
            if not isinstance(item, SessionCapabilityWorkerComponentRequest)
        )
        worker_id = self.worker_requirement.capability
        expected_roots = tuple(sorted((*base_requirements.roots, worker_id)))
        expected_mandatory = tuple(
            sorted((*base_requirements.mandatory_roots, worker_id))
        )
        expected_provider_roots = tuple(
            sorted((*ordinary.resolved_providers.roots, worker_id))
        )
        merged_by_id = {item.capability_id: item for item in merged_entries}
        base_trust = {
            (item.plugin_id, item.package_source_identity): item
            for item in base_context.trust_snapshots
        }
        merged_trust = {
            (item.plugin_id, item.package_source_identity): item
            for item in merged_context.trust_snapshots
        }
        if (
            base_context.product_id != self.product_id
            or base_context.scope_id != merged_context.scope_id
            or base_context.product_policy_revision
            != merged_context.product_policy_revision
            or base_context.evaluated_at != merged_context.evaluated_at
            or base_context.owner_snapshots != merged_context.owner_snapshots
            or len(base_trust) != len(base_context.trust_snapshots)
            or len(merged_trust) != len(merged_context.trust_snapshots)
            or any(merged_trust.get(key) != value for key, value in base_trust.items())
            or len(worker_requests) != 1
            or worker_requests[0].capability_id != worker_id
            or any(
                isinstance(item, SessionCapabilityWorkerComponentRequest)
                for item in ordinary.component_requests
            )
            or len(merged_trust) > len(base_trust) + 1
            or merged_trust.get(
                (
                    worker_requests[0].trust_snapshot.plugin_id,
                    worker_requests[0].trust_snapshot.package_source_identity,
                )
            )
            != worker_requests[0].trust_snapshot
            or merged.resource_admissions != base.resource_admissions
            or merged.catalog_admissions != base.catalog_admissions
            or merged_requirements.entries != base_requirements.entries
            or merged_requirements.optional_choices
            != base_requirements.optional_choices
            or merged_requirements.roots != expected_roots
            or merged_requirements.mandatory_roots != expected_mandatory
            or combined.resolved_providers.product_id
            != ordinary.resolved_providers.product_id
            or combined.resolved_providers.product_policy_revision
            != ordinary.resolved_providers.product_policy_revision
            or combined.resolved_providers.evaluated_at
            != ordinary.resolved_providers.evaluated_at
            or combined.resolved_providers.roots != expected_provider_roots
            or len(merged_entries) != len(base_entries) + 1
            or any(
                merged_by_id.get(item.capability_id) != item for item in base_entries
            )
            or merged_by_id.get(worker_id) is not worker_requests[0].resolved
            or combined.resolved_providers.prebound_providers
            != ordinary.resolved_providers.prebound_providers
            or combined.resolved_providers.optional_decisions
            != ordinary.resolved_providers.optional_decisions
            or len(base_requests) != len(ordinary.component_requests)
            or any(
                request is not original
                and (request != original or request.package is not original.package)
                for request, original in zip(
                    base_requests, ordinary.component_requests, strict=True
                )
            )
            or combined.host_consumer_requirements
            != tuple(
                sorted(
                    (*ordinary.host_consumer_requirements, self.worker_requirement),
                    key=lambda item: item.capability,
                )
            )
        ):
            raise self._failure("ordinary_session_facts_changed")
        self._validate_closure(merged, combined.resolved_providers, workspace_binding)

    def _failure(self, suffix: str) -> RuntimeError:
        return self.error_type(f"{self.error_prefix}_{suffix}")

    @staticmethod
    def _validate_closure(
        compilation: ProductCompositionCompilation,
        resolved: ResolvedCapabilityProviderSet,
        workspace_binding: CapabilityBundleProviderBinding,
    ) -> None:
        validate_session_capability_composition_closure(
            compilation,
            resolved,
            host_capability_ids=(
                MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
                WORKSPACE_CAPABILITY_DEFINITION.capability_id,
            ),
            host_providers=(workspace_binding.provider,),
        )


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
    owner_candidates: tuple[OwnerContributionCandidateEnvelope, ...] | None = field(
        default=None,
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
        if self.owner_candidates is not None:
            candidates = tuple(self.owner_candidates)
            if any(
                not isinstance(item, OwnerContributionCandidateEnvelope)
                for item in candidates
            ):
                raise TypeError("Product projected owner candidates are invalid")
            object.__setattr__(self, "owner_candidates", candidates)
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


OwnerCompletionRejection = Literal[
    "invalid_package_resource_declaration",
    "invalid_product_owner_binding_kind",
    "duplicate_product_owner_binding",
    "product_owner_binding_extra",
]


class ProductContributionOwnerResolver(Protocol):
    """Product policy for one grouped owner's exact binding or default."""

    def __call__(
        self,
        *,
        owner_id: str,
        contribution_kind: OwnerContributionKind,
        trust_classes: set[str],
        collection_ids: set[str],
        supplied_binding: ProductContributionOwnerBinding | None,
    ) -> ProductContributionOwnerBinding: ...


def _complete_product_plugin_selection_seed(
    seed: ProductPluginPlanSeed,
    *,
    selection: PluginSelection,
    candidates: tuple[OwnerContributionCandidateEnvelope, ...],
    resolve_owner: ProductContributionOwnerResolver,
    reject: Callable[[OwnerCompletionRejection], Exception],
) -> ProductPluginSelectionSeed:
    """Group already-projected inputs without making Product policy decisions."""

    owner_collections: dict[tuple[str, OwnerContributionKind], set[str]] = {}
    owner_trust_classes: dict[tuple[str, OwnerContributionKind], set[str]] = {}
    for candidate in candidates:
        contribution = candidate.contribution
        if not isinstance(
            contribution,
            ResourceContributionSpec | CatalogConsumerContributionSpec,
        ):
            raise reject("invalid_package_resource_declaration")
        owner_key = (candidate.owner_id, candidate.contribution_kind)
        owner_collections.setdefault(owner_key, set()).add(contribution.collection_id)
        owner_trust_classes.setdefault(owner_key, set()).add(
            candidate.source_trust_class
        )
    supplied: dict[
        tuple[str, OwnerContributionKind], ProductContributionOwnerBinding
    ] = {}
    for binding in seed.owner_bindings:
        owner_id, raw_contribution_kind, _ = binding.owner_key
        if raw_contribution_kind not in PLUGIN_OWNER_CONTRIBUTION_KINDS:
            raise reject("invalid_product_owner_binding_kind")
        contribution_kind = cast(OwnerContributionKind, raw_contribution_kind)
        owner_key = (owner_id, contribution_kind)
        if owner_key in supplied:
            raise reject("duplicate_product_owner_binding")
        supplied[owner_key] = binding

    if set(supplied) - set(owner_collections):
        raise reject("product_owner_binding_extra")

    owner_bindings_list: list[ProductContributionOwnerBinding] = []
    for owner_key, collection_ids in sorted(owner_collections.items()):
        owner_bindings_list.append(
            resolve_owner(
                owner_id=owner_key[0],
                contribution_kind=owner_key[1],
                trust_classes=owner_trust_classes[owner_key],
                collection_ids=collection_ids,
                supplied_binding=supplied.get(owner_key),
            )
        )
    owner_bindings = tuple(owner_bindings_list)
    return ProductPluginSelectionSeed(
        selection=selection,
        packages=seed.packages,
        bindings=seed.bindings,
        owner_bindings=owner_bindings,
    )


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
    if any(not isinstance(item, ProductContributionOwnerBinding) for item in owners):
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
        if item.declaration.kind in PLUGIN_OWNER_CONTRIBUTION_KINDS
    )
    if request.owner_candidates is not None:
        projected = request.owner_candidates
        if len(projected) != len(candidates) or any(
            actual
            != replace(
                expected,
                dependency_lock_digest=actual.dependency_lock_digest,
            )
            for expected, actual in zip(candidates, projected, strict=True)
        ):
            raise ProductCompositionAssemblyError(
                "Product owner projection changed Plugin selection facts.",
                code="product_contribution_candidate_projection_mismatch",
            )
        candidates = projected
    return _assemble_product_contribution_candidates(
        plan=selection.plan,
        candidates=candidates,
        owner_bindings=request.owner_bindings,
        mandatory_roots=request.mandatory_roots,
        definitions=request.definitions,
        select_optional_requirements=request.select_optional_requirements,
        evaluated_at=evaluated_at,
    )


def _assemble_product_contribution_candidates(
    *,
    plan: PluginSelectionPlanV2,
    candidates: tuple[OwnerContributionCandidateEnvelope, ...],
    owner_bindings: tuple[ProductContributionOwnerBinding, ...],
    mandatory_roots: tuple[str, ...],
    definitions: tuple[CapabilityDefinition, ...],
    select_optional_requirements: ProductOptionalRequirementSelector,
    evaluated_at: int,
) -> ProductCompositionCompilation:
    """Compile exact owner candidates without requiring a legacy package handle."""

    if not isinstance(plan, PluginSelectionPlanV2):
        raise TypeError("Product contribution plan is invalid")
    if any(
        not isinstance(item, OwnerContributionCandidateEnvelope) for item in candidates
    ):
        raise TypeError("Product contribution candidates are invalid")
    if any(
        not isinstance(item, ProductContributionOwnerBinding) for item in owner_bindings
    ):
        raise TypeError("Product contribution owner bindings are invalid")
    if not callable(select_optional_requirements):
        raise TypeError("Product optional requirement selector must be callable")
    if isinstance(evaluated_at, bool) or not isinstance(evaluated_at, int):
        raise TypeError("Product composition evaluation time must be an integer")
    if evaluated_at < 0:
        raise ValueError("Product composition evaluation time cannot be negative")
    context = plan.context
    selected_refs = set(plan.selected_contributions)
    candidate_refs = tuple(
        PluginContributionRef(item.plugin_id, item.contribution_id)
        for item in candidates
    )
    trust_by_id = {item.plugin_id: item for item in plan.source_trust_snapshots}
    instance_by_id = {item.plugin_id: item for item in context.instance_revision_refs}
    if len(candidate_refs) != len(set(candidate_refs)) or any(
        ref not in selected_refs
        or candidate.product_id != context.product_id
        or candidate.scope_id != context.scope_id
        or candidate.product_policy_revision != context.policy_revision
        or candidate.instance_revision_ref != instance_by_id.get(candidate.plugin_id)
        or (trust := trust_by_id.get(candidate.plugin_id)) is None
        or candidate.package_source_identity != trust.package_source_identity
        or candidate.source_trust_class != trust.source_trust_class
        or candidate.source_trust_policy_revision != trust.source_trust_policy_revision
        or candidate.source_trusted != trust.trusted
        for ref, candidate in zip(candidate_refs, candidates, strict=True)
    ):
        raise ProductCompositionAssemblyError(
            "Product contribution candidates changed their selection provenance.",
            code="product_contribution_candidate_mismatch",
        )
    bindings_by_key = {item.owner_key: item for item in owner_bindings}
    if len(bindings_by_key) != len(owner_bindings):
        raise ValueError("Product contribution owner bindings must be unique")
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
    owner_snapshots = tuple(item.authority.snapshot() for item in owner_bindings)
    authority_context = ProductCompositionAuthorityContext(
        product_id=context.product_id,
        scope_id=context.scope_id,
        product_policy_revision=context.policy_revision,
        evaluated_at=evaluated_at,
        owner_snapshots=owner_snapshots,
        trust_snapshots=plan.source_trust_snapshots,
    )
    compiler = ProductCompositionCompiler()
    preview = compiler.preview_optional_choices(
        authority_context=authority_context,
        mandatory_roots=mandatory_roots,
        admissions=admissions,
        definitions=definitions,
    )
    optional_choices = tuple(select_optional_requirements(preview))
    return compiler.compile(
        authority_context=authority_context,
        mandatory_roots=mandatory_roots,
        admissions=admissions,
        definitions=definitions,
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


def _prepare_catalog_plugin_plan_seed(
    receipt: ResourceCatalogInputReceipt,
    *,
    product_scope_id: str | None,
    evaluated_at: int,
    product_selection: PluginSelection | None = None,
    plan_seed: ProductPluginPlanSeed | None = None,
    include_configured_resource_plugins: bool = True,
    product_id: str,
    product_policy_revision: str,
    configured_trust_class: str,
    configured_trust_policy_revision: str,
    reject: Callable[[Sequence[str]], Exception],
    product_label: str,
) -> ProductPluginPlanSeed | None:
    """Merge package facts into an inert plan without finalizing selection."""
    seed_plan: PluginSelectionPlanV2 | None
    if plan_seed is not None:
        if not isinstance(plan_seed, ProductPluginPlanSeed):
            raise TypeError(f"{product_label} package Product plan seed is invalid")
        if product_selection is not None:
            raise ValueError(
                f"{product_label} package selection received two Product seeds"
            )
        seed_plan = plan_seed.plan
    else:
        seed_plan = product_selection.plan if product_selection is not None else None
    package_inputs = receipt.catalog_plugin_package_inputs
    if not package_inputs:
        return None
    if isinstance(evaluated_at, bool) or not isinstance(evaluated_at, int):
        raise TypeError(
            f"{product_label} package Resource admission time must be an integer"
        )
    if not isinstance(include_configured_resource_plugins, bool):
        raise TypeError("Configured Resource Plugin selection flag must be a boolean")
    seed_plugin_ids = (
        tuple(seed_plan.selected_plugin_ids) if seed_plan is not None else ()
    )
    selected_inputs = tuple(
        sorted(
            (
                item
                for item in package_inputs
                if item.package.manifest.name in seed_plugin_ids
                or (
                    include_configured_resource_plugins
                    and any(
                        (
                            reservation.kind == "resource_item"
                            for reservation in item.package.contribution_index.items
                        )
                    )
                )
            ),
            key=lambda item: item.package.manifest.name,
        )
    )
    if not selected_inputs:
        return None
    selected_input_by_id = {
        item.package.manifest.name: item for item in selected_inputs
    }
    seed_selected_contributions = (
        {
            (item.plugin_id, item.contribution_id)
            for item in seed_plan.selected_contributions
        }
        if seed_plan is not None
        else set()
    )
    seed_configuration_by_ref = (
        {
            (item.plugin_id, item.contribution_id): item.configuration
            for item in seed_plan.effective_configuration_set.entries
        }
        if seed_plan is not None
        else {}
    )

    def selected_reservation(plugin_id: str, contribution_id: str, kind: str) -> bool:
        if plugin_id in seed_plugin_ids:
            return (plugin_id, contribution_id) in seed_selected_contributions
        return kind == "resource_item"

    selected_source_fingerprints = {
        item.package.manifest.name: {
            reservation.source_descriptor_fingerprint
            for reservation in item.package.contribution_index.items
            if selected_reservation(
                item.package.manifest.name,
                reservation.contribution_id,
                reservation.kind,
            )
        }
        for item in selected_inputs
    }
    missing_seed_plugins = sorted(set(seed_plugin_ids) - set(selected_input_by_id))
    if missing_seed_plugins:
        raise reject(("product_selected_package_missing",))
    if seed_plan is not None:
        if plan_seed is not None:
            selected_seed_digests = {
                package.manifest.name: package.content_digest
                for package in plan_seed.packages
            }
        else:
            assert product_selection is not None
            selected_seed_digests = {
                candidate.package.manifest.name: candidate.package.content_digest
                for candidate in product_selection.candidates
            }
        if any(
            (
                selected_input_by_id[plugin_id].package.content_digest
                != selected_seed_digests.get(plugin_id)
                for plugin_id in seed_plugin_ids
            )
        ):
            raise reject(("product_selected_package_revision_mismatch",))
    scope_id = (
        seed_plan.context.scope_id
        if seed_plan is not None
        else product_scope_id.strip()
        if product_scope_id
        else f"session:{receipt.cwd}"
    )
    seed_instance_refs = (
        {item.plugin_id: item for item in seed_plan.context.instance_revision_refs}
        if seed_plan is not None
        else {}
    )
    seed_trust = (
        {item.plugin_id: item for item in seed_plan.source_trust_snapshots}
        if seed_plan is not None
        else {}
    )
    context = (
        seed_plan.context
        if seed_plan is not None
        else PluginPreflightContextV1(
            product_id=product_id,
            scope_id=scope_id,
            policy_revision=product_policy_revision,
            instance_revision_refs=tuple(
                (
                    PluginInstanceRevisionRef(
                        instance_id=f"{item.package.manifest.name}@{scope_id}",
                        plugin_id=item.package.manifest.name,
                        revision=1,
                    )
                    for item in selected_inputs
                )
            ),
        )
    )
    plan = PluginSelectionPlanV2(
        context=replace(
            context,
            instance_revision_refs=tuple(
                (
                    seed_instance_refs.get(item.package.manifest.name)
                    or PluginInstanceRevisionRef(
                        instance_id=f"{item.package.manifest.name}@{scope_id}",
                        plugin_id=item.package.manifest.name,
                        revision=1,
                    )
                    for item in selected_inputs
                )
            ),
        ),
        selected_plugin_ids=tuple(
            (item.package.manifest.name for item in selected_inputs)
        ),
        selected_contributions=tuple(
            (
                PluginContributionRef(
                    item.package.manifest.name, reservation.contribution_id
                )
                for item in selected_inputs
                for reservation in item.package.contribution_index.items
                if selected_reservation(
                    item.package.manifest.name,
                    reservation.contribution_id,
                    reservation.kind,
                )
            )
        ),
        source_trust_snapshots=tuple(
            (
                seed_trust.get(item.package.manifest.name)
                or PluginSourceTrustSnapshotV1(
                    plugin_id=item.package.manifest.name,
                    package_source_identity=item.binding.source_identity,
                    source_trust_class=configured_trust_class,
                    source_trust_policy_revision=configured_trust_policy_revision,
                    trusted=True,
                )
                for item in selected_inputs
            )
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                (
                    PluginEffectiveConfigurationEntry(
                        plugin_id=item.package.manifest.name,
                        contribution_id=reservation.contribution_id,
                        configuration=seed_configuration_by_ref.get(
                            (item.package.manifest.name, reservation.contribution_id),
                            reservation.configuration,
                        ),
                    )
                    for item in selected_inputs
                    for reservation in item.package.contribution_index.items
                    if reservation.source_descriptor_fingerprint
                    in selected_source_fingerprints[item.package.manifest.name]
                )
            )
        ),
        allowed_authority_ceiling=seed_plan.allowed_authority_ceiling
        if seed_plan is not None
        else (),
    )
    configured_resource_owners = {
        reservation.owner
        for item in selected_inputs
        if item.package.manifest.name not in seed_plugin_ids
        for reservation in item.package.contribution_index.items
        if reservation.kind == "resource_item"
    }
    owner_bindings = tuple(
        (
            _extend_configured_resource_owner_binding(
                item, configured_trust_class=configured_trust_class
            )
            if item.owner_key[0] in configured_resource_owners
            and item.owner_key[1] == "resource_item"
            else item
            for item in (plan_seed.owner_bindings if plan_seed is not None else ())
        )
    )
    return ProductPluginPlanSeed(
        plan=plan,
        packages=tuple((item.package for item in selected_inputs)),
        bindings=tuple((item.binding for item in selected_inputs)),
        owner_bindings=owner_bindings,
    )


def _extend_configured_resource_owner_binding(
    binding: ProductContributionOwnerBinding, *, configured_trust_class: str
) -> ProductContributionOwnerBinding:
    """Make configured-package trust explicit while the plan is still inert."""
    policy = binding.authority.policy
    if configured_trust_class in policy.allowed_source_trust_classes:
        return binding
    return ProductContributionOwnerBinding(
        authority=OwnerContributionAuthority(
            replace(
                policy,
                policy_revision=f"{policy.policy_revision}+configured-resources",
                allowed_source_trust_classes=tuple(
                    sorted(
                        (*policy.allowed_source_trust_classes, configured_trust_class)
                    )
                ),
            )
        ),
        admission_ttl_seconds=binding.admission_ttl_seconds,
    )


def _finalize_catalog_plugin_plan_seed(
    seed: ProductPluginPlanSeed,
    *,
    resolve: Callable[[ProductPluginPlanSeed], PluginSelection] | None = None,
    resolve_owner: ProductContributionOwnerResolver,
    reject: Callable[[Sequence[str]], Exception],
    product_label: str,
) -> ProductPluginSelectionSeed:
    """Finalize a complete package plan exactly once, then bind its owners."""
    if not isinstance(seed, ProductPluginPlanSeed):
        raise TypeError(f"{product_label} package Product plan seed is invalid")
    if resolve is None:
        outcome = PluginDeclarationHost().resolve(
            seed.packages,
            bindings=seed.bindings,
            plan=seed.plan,
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        if not isinstance(outcome, PluginSelection):
            raise reject(("package_declaration_selection_incomplete",))
        selection = outcome
    else:
        if not callable(resolve):
            raise TypeError(
                f"{product_label} package Product selection resolver is invalid"
            )
        selection = resolve(seed)
        if not isinstance(selection, PluginSelection) or selection.plan != seed.plan:
            raise reject(("package_declaration_selection_mismatch",))
    return _complete_catalog_plugin_selection_seed(
        seed,
        selection=selection,
        resolve_owner=resolve_owner,
        reject=reject,
        product_label=product_label,
    )


def _complete_catalog_plugin_selection_seed(
    seed: ProductPluginPlanSeed,
    *,
    selection: PluginSelection,
    resolve_owner: ProductContributionOwnerResolver,
    reject: Callable[[Sequence[str]], Exception],
    product_label: str,
) -> ProductPluginSelectionSeed:
    """Attach exact contribution owners to one already-finalized selection."""
    if not isinstance(seed, ProductPluginPlanSeed):
        raise TypeError(f"{product_label} package Product plan seed is invalid")
    if not isinstance(selection, PluginSelection) or selection.plan != seed.plan:
        raise ValueError(
            f"{product_label} package Product selection does not match its plan"
        )
    candidates = tuple(
        (
            prepare_owner_contribution_candidate(selection, item)
            for item in selection.candidates
            if item.declaration.kind in PLUGIN_OWNER_CONTRIBUTION_KINDS
        )
    )
    return _complete_product_plugin_selection_seed(
        seed,
        selection=selection,
        candidates=candidates,
        resolve_owner=resolve_owner,
        reject=lambda reason: reject((reason,)),
    )
