"""Private Coding Host for one owner-admitted read-only Worker Provider."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from hashlib import sha256

from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
    CapabilityWorkerProviderBindingSpec,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)
from loushang.harness.capabilities.provider_selection import ResolvedCapabilityProvider
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
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


class _WorkerAttemptRelease:
    def __init__(self, release_attempt: Callable[[], Awaitable[None]]) -> None:
        self._release_attempt = release_attempt
        self._lock = asyncio.Lock()
        self._released = False

    async def release_once(self) -> bool:
        async with self._lock:
            if self._released:
                return False
            await self._release_attempt()
            self._released = True
            return True


@dataclass(frozen=True, slots=True)
class CodingPreparedWorkerProvider:
    binding: CapabilityBundleProviderBinding
    facet: CapabilityWorkerReadOnlyFacetProxy
    receipt_fingerprint: str
    worker_admission_fingerprint: str
    _release: _WorkerAttemptRelease = field(repr=False, compare=False)
    _commit: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    def commit_after_graph_publication(self) -> None:
        if self.facet.state != "visible":
            raise CodingWorkerProviderHostError(
                "coding_worker_provider_publication_missing"
            )
        if self._commit is not None:
            self._commit()

    async def abort_uncommitted(self) -> bool:
        self.facet.retire()
        return await self._release.release_once()


def prepare_coding_worker_provider_binding(
    *,
    resolved: ResolvedCapabilityProvider,
    receipt_owner: (
        CodingWorkerProductReceiptOwner | CodingWindowsWorkerProductReceiptOwner
    ),
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

    if (
        not isinstance(resolved, ResolvedCapabilityProvider)
        or type(receipt_owner)
        not in (
            CodingWorkerProductReceiptOwner,
            CodingWindowsWorkerProductReceiptOwner,
        )
        or not isinstance(receipt, ProductWorkerActivationReceiptV1)
        or not isinstance(capability_authority, CodingProductWorkerCapabilityAuthority)
        or not isinstance(adapter, CapabilityQueryWorkerAdapter)
        or not isinstance(worker_admission, CapabilityWorkerAdmissionV1)
        or type(graph_generation) is not int
        or graph_generation < 1
        or not callable(clock)
        or not callable(release_attempt)
        or (on_graph_publication is not None and not callable(on_graph_publication))
        or (
            renewing_provider_owner is not None
            and not isinstance(renewing_provider_owner, CapabilityProviderOwnerAuthority)
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
        or spec.native_platform
        != _native_platform_for_receipt_owner(receipt_owner)
        or authority.owner_policy_revision != resolved.admission.owner_policy_revision
        or authority.revocation_epoch != resolved.admission.revocation_epoch
        or authority.plugin_revision_digest != receipt.policy.plugin_revision_digest
        or authority.declaration_fingerprint != receipt.policy.declaration_fingerprint
        or authority.product_policy_revision != receipt.policy.product_policy_revision
        or binding.plugin_id != spec.plugin_id
        or binding.contribution_id != spec.contribution_id
        or binding.product_id != receipt.policy.product_id
        or binding.scope_id != receipt.policy.product_scope_id
        or binding.owner_id != spec.owner_id
        or resolved.capability_id not in binding.allowed_capability_ids
        or adapter.binding != binding
        or adapter.admission != worker_admission
        or len(resolved.provider.facets) != 1
    ):
        raise CodingWorkerProviderHostError("coding_worker_provider_host_mismatch")
    adapter.assert_admitted_current(worker_admission)
    admission_window = (
        resolved.admission.expires_at - resolved.admission.issued_at
    )
    last_grant_time = resolved.admission.issued_at

    def issue_grant():
        nonlocal last_grant_time
        now = clock()
        if type(now) is not int or now < last_grant_time:
            raise CodingWorkerProviderHostError(
                "coding_worker_provider_admission_expired"
            )
        if renewing_provider_owner is None:
            if now >= resolved.admission.expires_at:
                raise CodingWorkerProviderHostError(
                    "coding_worker_provider_admission_expired"
                )
        else:
            current_candidate = prepare_coding_selected_worker_provider_candidate(
                receipt_owner=receipt_owner,
                receipt=receipt,
                definition=resolved.definition,
                provider=resolved.provider,
                base_policy_binding=base_policy_binding,
            )
            owner_snapshot = renewing_provider_owner.snapshot()
            if (
                current_candidate != candidate
                or owner_snapshot.capability_id != resolved.capability_id
                or owner_snapshot.policy_revision
                != resolved.admission.owner_policy_revision
                or owner_snapshot.revocation_epoch
                != resolved.admission.revocation_epoch
                or admission_window <= 0
            ):
                raise CodingWorkerProviderHostError(
                    "coding_worker_provider_renewal_changed"
                )
            eligibility = renewing_provider_owner.grant_eligibility(
                current_candidate,
                issued_at=now,
                expires_at=now + admission_window,
            )
            renewed = renewing_provider_owner.admit(
                current_candidate,
                eligibility=eligibility,
                issued_at=now,
                expires_at=now + admission_window,
            )
            if (
                renewed.candidate_fingerprint
                != resolved.admission.candidate_fingerprint
                or renewed.owner_policy_revision
                != resolved.admission.owner_policy_revision
                or renewed.revocation_epoch != resolved.admission.revocation_epoch
            ):
                raise CodingWorkerProviderHostError(
                    "coding_worker_provider_renewal_changed"
                )
        if base_policy_binding is not None:
            base_policy_binding.assert_current()
        grant = capability_authority.issue_read_only_facet(
            capability_id=resolved.capability_id,
            facet_id=facet_id,
        )
        last_grant_time = now
        return grant

    facet_id = resolved.provider.facets[0]
    issue_grant()
    facet = CapabilityWorkerReadOnlyFacetProxy(
        adapter=adapter,
        admission=worker_admission,
        capability_id=resolved.capability_id,
        facet_id=facet_id,
        owner_generation=binding.authority.owner_generation,
        graph_generation=graph_generation,
        issue_grant=issue_grant,
    )
    release = _WorkerAttemptRelease(release_attempt)

    def create(context: CapabilityProviderContext) -> CapabilityBundleValue:
        if (
            context.generation != graph_generation
            or context.product_id != receipt.policy.product_id
            or context.dependencies
        ):
            raise CodingWorkerProviderHostError("coding_worker_provider_graph_mismatch")
        return CapabilityBundleValue((CapabilityFacetBinding(facet_id, facet),))

    async def dispose(value: CapabilityBundleValue) -> None:
        if value.require(facet_id) is not facet or facet.state != "retired":
            raise CodingWorkerProviderHostError(
                "coding_worker_provider_retirement_stale"
            )
        await release.release_once()

    binding_fingerprint = sha256(
        b"loushang.coding-worker-provider-binding/v1\0"
        + resolved.admission.fingerprint.encode("ascii")
        + b"\0"
        + worker_admission.fingerprint.encode("ascii")
    ).hexdigest()
    graph_binding = CapabilityBundleProviderBinding(
        provider=resolved.provider,
        scope_instance_id=(
            f"{receipt.policy.product_scope_id}:{worker_admission.worker_attempt_id}"
        ),
        binding_input_fingerprint=binding_fingerprint,
        create=create,
        dispose=dispose,
        visibility_gates=(facet.visibility_gate,),
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
