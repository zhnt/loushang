"""Explicit Coding Product Session composition for one selected Worker.

The caller owns the contained Worker attempt until a Session publishes this
request or aborts it. This module neither selects a default route nor starts a
Worker. Product selection, Capability admission, and the live attempt must
already exist; their exact facts are rejoined before a Session may prepare.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionAuthorityContext,
    ProductCompositionCompiler,
)
from loushang.harness.capabilities.contracts import (
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
    CapabilityWorkerProviderBindingSpec,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ProductCapabilityProviderResolver,
    ProductCapabilityProviderSelectionPlanV1,
    ResolvedCapabilityProviderSet,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
    SessionCapabilityWorkerComponentRequest,
    validate_session_capability_composition_closure,
)
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
)
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .package_product_worker_capability import CodingProductWorkerCapabilityAuthority
from .package_product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
    prepare_coding_selected_worker_provider_candidate,
)
from .package_product_worker_provider_host import (
    CodingPreparedWorkerProvider,
    prepare_coding_worker_provider_binding,
)
from .package_product_worker_query_consumer import (
    CODING_WORKER_QUERY_CAPABILITY_ID,
    CODING_WORKER_QUERY_DEFINITION,
    CODING_WORKER_QUERY_REQUIREMENT,
    coding_worker_query_owner_authority,
)
from .package_product_worker_receipt import CodingWorkerProductReceiptOwner


class CodingWorkerSessionCompositionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def prepare_coding_product_worker_session_inputs(
    *,
    resolved_providers: ResolvedCapabilityProviderSet,
    provider_owner: CapabilityProviderOwnerAuthority,
    receipt_owner: CodingWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    capability_authority: CodingProductWorkerCapabilityAuthority | None,
    adapter: CapabilityQueryWorkerAdapter | None,
    worker_admission: CapabilityWorkerAdmissionV1,
    evaluated_at: int,
    clock: Callable[[], int],
    release_attempt: Callable[[], Awaitable[None]] | None,
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding | None = None,
    deferred_prepare: (
        Callable[[int], Awaitable[CodingPreparedWorkerProvider]] | None
    ) = None,
) -> SessionCapabilityCompositionInputs:
    """Compile one explicit, current Worker into a Session graph input.

    The Product-selected receipt is reread here and again by the Worker Host at
    graph preparation. The returned callback owns no activation authority of
    its own; its prepared attempt is released on graph abort or disposal.
    """

    if (
        not isinstance(resolved_providers, ResolvedCapabilityProviderSet)
        or not isinstance(provider_owner, CapabilityProviderOwnerAuthority)
        or not isinstance(receipt_owner, CodingWorkerProductReceiptOwner)
        or not isinstance(receipt, ProductWorkerActivationReceiptV1)
        or not isinstance(worker_admission, CapabilityWorkerAdmissionV1)
        or type(evaluated_at) is not int
        or evaluated_at < 0
        or not callable(clock)
        or (
            deferred_prepare is None
            and (
                not isinstance(
                    capability_authority, CodingProductWorkerCapabilityAuthority
                )
                or not isinstance(adapter, CapabilityQueryWorkerAdapter)
                or not callable(release_attempt)
            )
        )
        or (
            deferred_prepare is not None
            and (
                not callable(deferred_prepare)
                or capability_authority is not None
                or adapter is not None
                or release_attempt is not None
            )
        )
    ):
        raise TypeError("Coding Worker Session composition inputs are invalid")
    if (
        len(resolved_providers.entries) != 1
        or resolved_providers.roots != (resolved_providers.entries[0].capability_id,)
        or resolved_providers.prebound_providers
        or resolved_providers.optional_decisions
    ):
        raise CodingWorkerSessionCompositionError(
            "coding_worker_session_provider_closure_invalid"
        )
    resolved = resolved_providers.entries[0]
    spec = resolved.binding_spec
    if not isinstance(spec, CapabilityWorkerProviderBindingSpec):
        raise CodingWorkerSessionCompositionError(
            "coding_worker_session_provider_not_worker"
        )
    candidate = prepare_coding_selected_worker_provider_candidate(
        receipt_owner=receipt_owner,
        receipt=receipt,
        definition=resolved.definition,
        provider=resolved.provider,
        base_policy_binding=base_policy_binding,
    )
    owner_snapshot = provider_owner.snapshot()
    selected = receipt_owner.current_selected_manifest(receipt)
    trust = selected.source_trust_snapshot
    if (
        candidate != resolved.admission.candidate
        or candidate.binding_spec != spec
        or owner_snapshot.capability_id != resolved.capability_id
        or owner_snapshot.policy_revision != resolved.admission.owner_policy_revision
        or owner_snapshot.revocation_epoch != resolved.admission.revocation_epoch
        or trust is None
        or not trust.trusted
        or trust.plugin_id != spec.plugin_id
        or trust.package_source_identity != candidate.package_source_identity
        or trust.source_trust_class != candidate.source_trust_class
        or trust.source_trust_policy_revision != candidate.source_trust_policy_revision
        or not resolved.admission.issued_at
        <= evaluated_at
        < resolved.admission.expires_at
        or (adapter is not None and adapter.admission != worker_admission)
        or resolved_providers.product_id != receipt.policy.product_id
        or resolved_providers.product_policy_revision
        != candidate.product_policy_revision
        or resolved_providers.evaluated_at != evaluated_at
    ):
        raise CodingWorkerSessionCompositionError(
            "coding_worker_session_selection_stale"
        )
    host_consumer_requirements: tuple[CapabilityRequirement, ...] = ()
    if resolved.capability_id == CODING_WORKER_QUERY_CAPABILITY_ID:
        if (
            resolved.definition != CODING_WORKER_QUERY_DEFINITION
            or provider_owner.policy != coding_worker_query_owner_authority().policy
        ):
            raise CodingWorkerSessionCompositionError(
                "coding_worker_query_owner_contract_mismatch"
            )
        host_consumer_requirements = (CODING_WORKER_QUERY_REQUIREMENT,)
    # The same Product policy and scope enter the Consumer compiler. No second
    # enablement, provider, or owner decision is inferred from the manifest.
    composition = ProductCompositionCompiler().compile(
        authority_context=ProductCompositionAuthorityContext(
            product_id=receipt.policy.product_id,
            scope_id=candidate.scope_id,
            product_policy_revision=candidate.product_policy_revision,
            evaluated_at=evaluated_at,
            owner_snapshots=(),
            trust_snapshots=(trust,),
        ),
        mandatory_roots=(
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
            resolved.capability_id,
        ),
        admissions=(),
        definitions=(MODEL_INPUT_CAPABILITY_DEFINITION, resolved.definition),
        optional_choices=(),
    )

    async def prepare(graph_generation: int):
        if deferred_prepare is not None:
            return await deferred_prepare(graph_generation)
        assert capability_authority is not None
        assert adapter is not None
        assert release_attempt is not None
        return prepare_coding_worker_provider_binding(
            resolved=resolved,
            receipt_owner=receipt_owner,
            receipt=receipt,
            capability_authority=capability_authority,
            adapter=adapter,
            worker_admission=worker_admission,
            graph_generation=graph_generation,
            clock=clock,
            release_attempt=release_attempt,
            base_policy_binding=base_policy_binding,
        )

    return SessionCapabilityCompositionInputs(
        product_composition=composition,
        resolved_providers=resolved_providers,
        host_consumer_requirements=host_consumer_requirements,
        component_requests=(
            SessionCapabilityWorkerComponentRequest(
                resolved=resolved,
                owner_snapshot=owner_snapshot,
                trust_snapshot=trust,
                receipt_fingerprint=receipt.fingerprint,
                worker_admission_fingerprint=worker_admission.fingerprint,
                prepare=prepare,
            ),
        ),
    )


def compose_coding_product_worker_with_ordinary_session(
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
        raise TypeError("Coding Worker ordinary composition inputs are invalid")
    base_context = ordinary.product_composition.authority_context
    worker_context = worker.product_composition.authority_context
    worker_request = (
        worker.component_requests[0] if len(worker.component_requests) == 1 else None
    )
    if (
        base_context.product_id != "coding"
        or worker_context.product_id != "coding"
        or base_context.scope_id != worker_context.scope_id
        or base_context.product_policy_revision
        != worker_context.product_policy_revision
        or base_context.evaluated_at != worker_context.evaluated_at
        or ordinary.resolved_providers.evaluated_at
        != worker.resolved_providers.evaluated_at
        or ordinary.resolved_providers.evaluated_at
        != base_context.evaluated_at
        or not isinstance(worker_request, SessionCapabilityWorkerComponentRequest)
        or worker.resolved_providers.prebound_providers
        or worker.product_composition.resource_admissions
        or worker.product_composition.catalog_admissions
        or worker.product_composition.consumer_requirements.optional_choices
        or worker.product_composition.consumer_requirements.entries
        or worker_context.owner_snapshots
        or worker_context.trust_snapshots != (worker_request.trust_snapshot,)
    ):
        raise CodingWorkerSessionCompositionError(
            "coding_worker_ordinary_composition_authority_mismatch"
        )
    assert isinstance(worker_request, SessionCapabilityWorkerComponentRequest)
    worker_id = worker_request.capability_id
    worker_roots = worker.product_composition.consumer_requirements
    if (
        worker_roots.mandatory_roots
        != tuple(sorted((MODEL_INPUT_CAPABILITY_DEFINITION.capability_id, worker_id)))
        or worker_roots.roots != worker_roots.mandatory_roots
        or worker_id in ordinary.product_composition.consumer_requirements.roots
        or worker_id in {
            item.capability_id for item in ordinary.resolved_providers.entries
        }
        or worker.resolved_providers.roots != (worker_id,)
    ):
        raise CodingWorkerSessionCompositionError(
            "coding_worker_ordinary_composition_overlap"
        )
    validate_session_capability_composition_closure(
        ordinary.product_composition,
        ordinary.resolved_providers,
        host_capability_ids=(
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
            WORKSPACE_CAPABILITY_DEFINITION.capability_id,
        ),
        host_providers=(workspace_binding.provider,),
    )
    base_requirements = ordinary.product_composition.consumer_requirements
    if (
        MODEL_INPUT_CAPABILITY_DEFINITION.capability_id
        not in base_requirements.mandatory_roots
        or WORKSPACE_CAPABILITY_DEFINITION.capability_id
        not in base_requirements.roots
    ):
        raise CodingWorkerSessionCompositionError(
            "coding_worker_ordinary_composition_base_missing"
        )
    trust_by_key = {
        (item.plugin_id, item.package_source_identity): item
        for item in base_context.trust_snapshots
    }
    worker_trust = worker_request.trust_snapshot
    trust_key = (worker_trust.plugin_id, worker_trust.package_source_identity)
    if trust_key in trust_by_key and trust_by_key[trust_key] != worker_trust:
        raise CodingWorkerSessionCompositionError(
            "coding_worker_ordinary_composition_trust_changed"
        )
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
        raise CodingWorkerSessionCompositionError(
            "coding_worker_ordinary_composition_definition_mismatch"
        )
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
    roots = tuple(
        sorted((*ordinary.resolved_providers.roots, worker_id))
    )
    resolved = ProductCapabilityProviderResolver().resolve(
        ProductCapabilityProviderSelectionPlanV1(
            product_id="coding",
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
        raise CodingWorkerSessionCompositionError(
            "coding_worker_ordinary_composition_selection_changed"
        )
    validate_session_capability_composition_closure(
        compilation,
        resolved,
        host_capability_ids=(
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
            WORKSPACE_CAPABILITY_DEFINITION.capability_id,
        ),
        host_providers=(workspace_binding.provider,),
    )
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


def validate_coding_product_worker_ordinary_session_inputs(
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
        raise TypeError("Coding Worker ordinary Session inputs are invalid")
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
    worker_id = CODING_WORKER_QUERY_CAPABILITY_ID
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
        base_context.product_id != "coding"
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
        or any(merged_by_id.get(item.capability_id) != item for item in base_entries)
        or merged_by_id.get(worker_id) is not worker_requests[0].resolved
        or combined.resolved_providers.prebound_providers
        != ordinary.resolved_providers.prebound_providers
        or combined.resolved_providers.optional_decisions
        != ordinary.resolved_providers.optional_decisions
        or len(base_requests) != len(ordinary.component_requests)
        or any(
            request is not original
            and (
                request != original
                or request.package is not original.package
            )
            for request, original in zip(
                base_requests, ordinary.component_requests, strict=True
            )
        )
        or combined.host_consumer_requirements
        != tuple(
            sorted(
                (*ordinary.host_consumer_requirements, CODING_WORKER_QUERY_REQUIREMENT),
                key=lambda item: item.capability,
            )
        )
    ):
        raise CodingWorkerSessionCompositionError(
            "coding_worker_ordinary_session_facts_changed"
        )
    validate_session_capability_composition_closure(
        merged,
        combined.resolved_providers,
        host_capability_ids=(
            MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,
            WORKSPACE_CAPABILITY_DEFINITION.capability_id,
        ),
        host_providers=(workspace_binding.provider,),
    )


@dataclass(frozen=True, slots=True)
class CodingProductWorkerOrdinarySessionBinding:
    """Exact ordinary and Worker graph facts accepted by one Coding Session."""

    ordinary: SessionCapabilityCompositionInputs
    combined: SessionCapabilityCompositionInputs
    workspace_binding: CapabilityBundleProviderBinding

    def __post_init__(self) -> None:
        validate_coding_product_worker_ordinary_session_inputs(
            ordinary=self.ordinary,
            combined=self.combined,
            workspace_binding=self.workspace_binding,
        )


__all__ = [
    "CodingProductWorkerOrdinarySessionBinding",
    "CodingWorkerSessionCompositionError",
    "compose_coding_product_worker_with_ordinary_session",
    "prepare_coding_product_worker_session_inputs",
    "validate_coding_product_worker_ordinary_session_inputs",
]
