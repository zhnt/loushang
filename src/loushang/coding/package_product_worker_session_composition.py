"""Explicit Coding Product Session composition for one selected Worker.

The caller owns the contained Worker attempt until a Session publishes this
request or aborts it. This module neither selects a default route nor starts a
Worker. Product selection, Capability admission, and the live attempt must
already exist; their exact facts are rejoined before a Session may prepare.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

from loushang.harness.capabilities.contracts import (
    CapabilityRequirement,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProvider,
    ResolvedCapabilityProviderSet,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.session._worker_provider import _prepare_worker_session_inputs
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityCompositionInputs,
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


def _coding_worker_session_consumer_requirements(
    resolved: ResolvedCapabilityProvider,
    provider_owner: CapabilityProviderOwnerAuthority,
) -> tuple[CapabilityRequirement, ...]:
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
    return host_consumer_requirements


_PREPARE_WORKER_SESSION_INPUTS = partial(
    _prepare_worker_session_inputs,
    read_candidate=prepare_coding_selected_worker_provider_candidate,
    prepare_binding=prepare_coding_worker_provider_binding,
    consumer_requirements=_coding_worker_session_consumer_requirements,
    error_type=CodingWorkerSessionCompositionError,
    error_prefix="coding_worker",
    invalid_inputs_message="Coding Worker Session composition inputs are invalid",
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

    return _PREPARE_WORKER_SESSION_INPUTS(
        receipt_owner_types=(
            CodingWorkerProductReceiptOwner,
            CodingWindowsWorkerProductReceiptOwner,
        ),
        capability_authority_type=CodingProductWorkerCapabilityAuthority,
        resolved_providers=resolved_providers,
        provider_owner=provider_owner,
        receipt_owner=receipt_owner,
        receipt=receipt,
        capability_authority=capability_authority,
        adapter=adapter,
        worker_admission=worker_admission,
        evaluated_at=evaluated_at,
        clock=clock,
        release_attempt=release_attempt,
        base_policy_binding=base_policy_binding,
        deferred_prepare=deferred_prepare,
    )


compose_coding_product_worker_with_ordinary_session = (
    _WORKER_SESSION_COMPOSITION.compose
)


validate_coding_product_worker_ordinary_session_inputs = (
    _WORKER_SESSION_COMPOSITION.validate
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
