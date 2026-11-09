"""Explicit Coding Product Session composition for one selected Worker.

The caller owns the contained Worker attempt until a Session publishes this
request or aborts it. This module neither selects a default route nor starts a
Worker. Product selection, Capability admission, and the live attempt must
already exist; their exact facts are rejoined before a Session may prepare.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
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
    ResolvedCapabilityProviderSet,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
    SessionCapabilityWorkerComponentRequest,
)
from loushang.harness.session.product_composition_assembly import (
    _WorkerSessionComposition,
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
from .package_product_worker_resume import CodingWorkerResumeSettlementBinding
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)


class CodingWorkerSessionCompositionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_WORKER_SESSION_COMPOSITION = _WorkerSessionComposition(
    product_id="coding",
    worker_requirement=CODING_WORKER_QUERY_REQUIREMENT,
    error_type=CodingWorkerSessionCompositionError,
    error_prefix="coding_worker",
    invalid_composition_inputs="Coding Worker ordinary composition inputs are invalid",
    invalid_session_inputs="Coding Worker ordinary Session inputs are invalid",
)


def prepare_coding_product_worker_session_inputs(
    *,
    resolved_providers: ResolvedCapabilityProviderSet,
    provider_owner: CapabilityProviderOwnerAuthority,
    receipt_owner: (
        CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner
    ),
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
        or type(receipt_owner)
        not in (
            CodingWorkerProductReceiptOwner,
            CodingWindowsWorkerProductReceiptOwner,
        )
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

    return _WORKER_SESSION_COMPOSITION.compose(
        ordinary=ordinary,
        worker=worker,
        definitions=definitions,
        workspace_binding=workspace_binding,
    )


def validate_coding_product_worker_ordinary_session_inputs(
    *,
    ordinary: SessionCapabilityCompositionInputs,
    combined: SessionCapabilityCompositionInputs,
    workspace_binding: CapabilityBundleProviderBinding,
) -> None:
    """Require one Worker addition while retaining every ordinary Product fact."""

    _WORKER_SESSION_COMPOSITION.validate(
        ordinary=ordinary,
        combined=combined,
        workspace_binding=workspace_binding,
    )


@dataclass(frozen=True, slots=True)
class CodingProductWorkerOrdinarySessionBinding:
    """Exact ordinary and Worker graph facts accepted by one Coding Session."""

    ordinary: SessionCapabilityCompositionInputs
    combined: SessionCapabilityCompositionInputs
    workspace_binding: CapabilityBundleProviderBinding
    selected_worker_manifest: PackageProductSelectedPluginManifestV1 | None = None
    activation_receipt: ProductWorkerActivationReceiptV1 | None = None
    resume_settlement: CodingWorkerResumeSettlementBinding | None = None

    def __post_init__(self) -> None:
        validate_coding_product_worker_ordinary_session_inputs(
            ordinary=self.ordinary,
            combined=self.combined,
            workspace_binding=self.workspace_binding,
        )
        selected = self.selected_worker_manifest
        receipt = self.activation_receipt
        if (selected is None) != (receipt is None):
            raise ValueError("Coding Worker selection evidence is incomplete")
        if self.resume_settlement is not None and receipt is None:
            raise ValueError("Coding Worker Resume settlement lacks a receipt")
        if (
            selected is not None
            and receipt is not None
            and (
                selected.snapshot.installation_key.plugin_id != receipt.policy.plugin_id
                or selected.snapshot.root_ref.artifact_digest
                != receipt.policy.plugin_revision_digest
            )
        ):
            raise ValueError("Coding Worker selection evidence changed")


__all__ = [
    "CodingProductWorkerOrdinarySessionBinding",
    "CodingWorkerSessionCompositionError",
    "compose_coding_product_worker_with_ordinary_session",
    "prepare_coding_product_worker_session_inputs",
    "validate_coding_product_worker_ordinary_session_inputs",
]
