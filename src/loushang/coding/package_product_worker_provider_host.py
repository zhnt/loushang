"""Private Coding Host for one owner-admitted read-only Worker Provider."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
    CapabilityWorkerProviderBindingSpec,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.provider_selection import ResolvedCapabilityProvider
from loushang.harness.session._worker_provider import (
    _abort_worker_provider,
    _commit_worker_provider,
    _prepare_worker_provider_binding,
    _require_current_worker_provider,
)
from loushang.harness.session._worker_provider import (
    _WorkerAttemptRelease as _SessionWorkerAttemptRelease,
)
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerBindingV1,
)
from loushang.harness.worker.facet_proxy import CapabilityWorkerReadOnlyFacetProxy
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

from .package_product_worker_capability import CodingProductWorkerCapabilityAuthority
from .package_product_worker_provider import (
    CodingWorkerBaseCompositionPolicyBinding,
    _native_platform_for_receipt_owner,
    prepare_coding_selected_worker_provider_candidate,
)
from .package_product_worker_receipt import CodingWorkerProductReceiptOwner
from .package_product_worker_windows_receipt import (
    CodingWindowsWorkerProductReceiptOwner,
)


class CodingWorkerProviderHostError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _WorkerAttemptRelease(_SessionWorkerAttemptRelease):
    pass


@dataclass(frozen=True, slots=True)
class CodingPreparedWorkerProvider:
    binding: CapabilityBundleProviderBinding
    facet: CapabilityWorkerReadOnlyFacetProxy
    receipt_fingerprint: str
    worker_admission_fingerprint: str
    _release: _WorkerAttemptRelease = field(repr=False, compare=False)
    _commit: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    def commit_after_graph_publication(self) -> None:
        _commit_worker_provider(
            self.facet,
            self._commit,
            CodingWorkerProviderHostError,
            "coding_worker_provider",
        )

    async def abort_uncommitted(self) -> bool:
        return await _abort_worker_provider(self.facet, self._release)

    def require_current_activation(self) -> None:
        _require_current_worker_provider(
            self.facet,
            self._release,
            CodingWorkerProviderHostError,
            "coding_worker_provider",
        )


def prepare_coding_worker_provider_binding(
    *,
    resolved: ResolvedCapabilityProvider,
    receipt_owner: CodingWorkerProductReceiptOwner
    | CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    capability_authority: CodingProductWorkerCapabilityAuthority,
    adapter: CapabilityQueryWorkerAdapter,
    worker_admission: CapabilityWorkerAdmissionV1,
    graph_generation: int,
    clock: Callable[[], int],
    release_attempt: Callable[[], Awaitable[None]],
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding | None = None,
    renewing_provider_owner: CapabilityProviderOwnerAuthority | None = None,
    on_graph_publication: Callable[[], None] | None = None,
) -> CodingPreparedWorkerProvider:
    """Prepare a graph binding only for an exact current Product/owner selection."""
    candidate, binding = _read_coding_worker_provider_inputs(
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
        renewing_provider_owner=renewing_provider_owner,
        on_graph_publication=on_graph_publication,
    )

    def read_candidate():
        return prepare_coding_selected_worker_provider_candidate(
            receipt_owner=receipt_owner,
            receipt=receipt,
            definition=resolved.definition,
            provider=resolved.provider,
            base_policy_binding=base_policy_binding,
        )

    graph_binding, facet, release = _prepare_worker_provider_binding(
        resolved=resolved,
        receipt=receipt,
        binding=binding,
        capability_authority=capability_authority,
        adapter=adapter,
        worker_admission=worker_admission,
        graph_generation=graph_generation,
        clock=clock,
        release_attempt=release_attempt,
        candidate=candidate,
        read_candidate=read_candidate,
        base_policy_binding=base_policy_binding,
        renewing_provider_owner=renewing_provider_owner,
        error_type=CodingWorkerProviderHostError,
        error_prefix="coding_worker_provider",
        fingerprint_namespace=b"loushang.coding-worker-provider-binding/v1\x00",
        release_type=_WorkerAttemptRelease,
    )
    return CodingPreparedWorkerProvider(
        binding=graph_binding,
        facet=facet,
        receipt_fingerprint=receipt.fingerprint,
        worker_admission_fingerprint=worker_admission.fingerprint,
        _release=release,
        _commit=on_graph_publication,
    )


__all__ = [
    "CodingPreparedWorkerProvider",
    "CodingWorkerProviderHostError",
    "prepare_coding_worker_provider_binding",
]


def _read_coding_worker_provider_inputs(
    *,
    resolved: ResolvedCapabilityProvider,
    receipt_owner: CodingWorkerProductReceiptOwner
    | CodingWindowsWorkerProductReceiptOwner,
    receipt: ProductWorkerActivationReceiptV1,
    capability_authority: CodingProductWorkerCapabilityAuthority,
    adapter: CapabilityQueryWorkerAdapter,
    worker_admission: CapabilityWorkerAdmissionV1,
    graph_generation: int,
    clock: Callable[[], int],
    release_attempt: Callable[[], Awaitable[None]],
    base_policy_binding: CodingWorkerBaseCompositionPolicyBinding | None = None,
    renewing_provider_owner: CapabilityProviderOwnerAuthority | None = None,
    on_graph_publication: Callable[[], None] | None = None,
) -> tuple[CapabilityProviderCandidateEnvelope, CapabilityWorkerBindingV1]:
    """Prepare a graph binding only for an exact current Product/owner selection."""
    if (
        not isinstance(resolved, ResolvedCapabilityProvider)
        or type(receipt_owner)
        not in (CodingWorkerProductReceiptOwner, CodingWindowsWorkerProductReceiptOwner)
        or (not isinstance(receipt, ProductWorkerActivationReceiptV1))
        or (
            not isinstance(capability_authority, CodingProductWorkerCapabilityAuthority)
        )
        or (not isinstance(adapter, CapabilityQueryWorkerAdapter))
        or (not isinstance(worker_admission, CapabilityWorkerAdmissionV1))
        or (type(graph_generation) is not int)
        or (graph_generation < 1)
        or (not callable(clock))
        or (not callable(release_attempt))
        or (on_graph_publication is not None and (not callable(on_graph_publication)))
        or (
            renewing_provider_owner is not None
            and (
                not isinstance(
                    renewing_provider_owner, CapabilityProviderOwnerAuthority
                )
            )
        )
    ):
        raise TypeError("Coding Worker Provider Host inputs are invalid")
    spec = resolved.binding_spec
    if not isinstance(spec, CapabilityWorkerProviderBindingSpec):
        raise CodingWorkerProviderHostError("coding_worker_provider_binding_not_worker")
    candidate = prepare_coding_selected_worker_provider_candidate(
        receipt_owner=receipt_owner,
        receipt=receipt,
        definition=resolved.definition,
        provider=resolved.provider,
        base_policy_binding=base_policy_binding,
    )
    authority = capability_authority.current_authority()
    binding = capability_authority.binding
    if (
        candidate != resolved.admission.candidate
        or candidate.binding_spec != spec
        or spec.native_platform != _native_platform_for_receipt_owner(receipt_owner)
        or (authority.owner_policy_revision != resolved.admission.owner_policy_revision)
        or (authority.revocation_epoch != resolved.admission.revocation_epoch)
        or (authority.plugin_revision_digest != receipt.policy.plugin_revision_digest)
        or (authority.declaration_fingerprint != receipt.policy.declaration_fingerprint)
        or (authority.product_policy_revision != receipt.policy.product_policy_revision)
        or (binding.plugin_id != spec.plugin_id)
        or (binding.contribution_id != spec.contribution_id)
        or (binding.product_id != receipt.policy.product_id)
        or (binding.scope_id != receipt.policy.product_scope_id)
        or (binding.owner_id != spec.owner_id)
        or (resolved.capability_id not in binding.allowed_capability_ids)
        or (adapter.binding != binding)
        or (adapter.admission != worker_admission)
        or (len(resolved.provider.facets) != 1)
    ):
        raise CodingWorkerProviderHostError("coding_worker_provider_host_mismatch")
    adapter.assert_admitted_current(worker_admission)
    return (candidate, binding)
