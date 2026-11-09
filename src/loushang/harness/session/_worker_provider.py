"""Session graph integration for an owner-admitted Worker Provider."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from hashlib import sha256
from typing import Protocol, TypeVar

from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
    CapabilityBundleValue,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)
from loushang.harness.capabilities.provider_selection import (
    ResolvedCapabilityProvider,
    ResolvedCapabilityProviderSet,
)
from loushang.harness.worker._ordinary_prepare import _NativeWorkerAttempt
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    CapabilityWorkerFacetGrantV1,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.facet_proxy import CapabilityWorkerReadOnlyFacetProxy
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1


class _FacetGrantAuthority(Protocol):
    def issue_read_only_facet(
        self, *, capability_id: str, facet_id: str
    ) -> tuple[CapabilityWorkerFacetGrantV1, Callable[[object], object]]: ...


class _BasePolicyGuard(Protocol):
    def assert_current(self) -> None: ...


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


_ReleaseT = TypeVar("_ReleaseT", bound=_WorkerAttemptRelease)


def _prepare_worker_provider_binding(
    *,
    resolved: ResolvedCapabilityProvider,
    receipt: ProductWorkerActivationReceiptV1,
    binding: CapabilityWorkerBindingV1,
    capability_authority: _FacetGrantAuthority,
    adapter: CapabilityQueryWorkerAdapter,
    worker_admission: CapabilityWorkerAdmissionV1,
    graph_generation: int,
    clock: Callable[[], int],
    release_attempt: Callable[[], Awaitable[None]],
    candidate: CapabilityProviderCandidateEnvelope,
    read_candidate: Callable[[], CapabilityProviderCandidateEnvelope],
    base_policy_binding: _BasePolicyGuard | None,
    renewing_provider_owner: CapabilityProviderOwnerAuthority | None,
    error_type: Callable[[str], RuntimeError],
    error_prefix: str,
    fingerprint_namespace: bytes,
    release_type: type[_ReleaseT],
) -> tuple[
    CapabilityBundleProviderBinding, CapabilityWorkerReadOnlyFacetProxy, _ReleaseT
]:
    """Bind approved facts; Product rechecks may perform IO at the original grant point."""
    admission_window = resolved.admission.expires_at - resolved.admission.issued_at
    last_grant_time = resolved.admission.issued_at

    def issue_grant():
        nonlocal last_grant_time
        now = clock()
        if type(now) is not int or now < last_grant_time:
            raise error_type(f"{error_prefix}_admission_expired")
        if renewing_provider_owner is None:
            if now >= resolved.admission.expires_at:
                raise error_type(f"{error_prefix}_admission_expired")
        else:
            current_candidate = read_candidate()
            owner_snapshot = renewing_provider_owner.snapshot()
            if (
                current_candidate != candidate
                or owner_snapshot.capability_id != resolved.capability_id
                or owner_snapshot.policy_revision
                != resolved.admission.owner_policy_revision
                or (
                    owner_snapshot.revocation_epoch
                    != resolved.admission.revocation_epoch
                )
                or (admission_window <= 0)
            ):
                raise error_type(f"{error_prefix}_renewal_changed")
            eligibility = renewing_provider_owner.grant_eligibility(
                current_candidate, issued_at=now, expires_at=now + admission_window
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
                raise error_type(f"{error_prefix}_renewal_changed")
        if base_policy_binding is not None:
            base_policy_binding.assert_current()
        grant = capability_authority.issue_read_only_facet(
            capability_id=resolved.capability_id, facet_id=facet_id
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
    release = release_type(release_attempt)

    def create(context: CapabilityProviderContext) -> CapabilityBundleValue:
        if (
            context.generation != graph_generation
            or context.product_id != receipt.policy.product_id
            or context.dependencies
        ):
            raise error_type(f"{error_prefix}_graph_mismatch")
        return CapabilityBundleValue((CapabilityFacetBinding(facet_id, facet),))

    async def dispose(value: CapabilityBundleValue) -> None:
        if value.require(facet_id) is not facet or facet.state != "retired":
            raise error_type(f"{error_prefix}_retirement_stale")
        await release.release_once()

    binding_fingerprint = sha256(
        fingerprint_namespace
        + resolved.admission.fingerprint.encode("ascii")
        + b"\x00"
        + worker_admission.fingerprint.encode("ascii")
    ).hexdigest()
    graph_binding = CapabilityBundleProviderBinding(
        provider=resolved.provider,
        scope_instance_id=f"{receipt.policy.product_scope_id}:{worker_admission.worker_attempt_id}",
        binding_input_fingerprint=binding_fingerprint,
        create=create,
        dispose=dispose,
        visibility_gates=(facet.visibility_gate,),
    )
    return (graph_binding, facet, release)


def _commit_worker_provider(
    facet: CapabilityWorkerReadOnlyFacetProxy,
    commit: Callable[[], None] | None,
    error_type: Callable[[str], RuntimeError],
    error_prefix: str,
) -> None:
    if facet.state != "visible":
        raise error_type(f"{error_prefix}_publication_missing")
    if commit is not None:
        commit()


async def _abort_worker_provider(
    facet: CapabilityWorkerReadOnlyFacetProxy, release: _WorkerAttemptRelease
) -> bool:
    facet.retire()
    return await release.release_once()


def _require_current_worker_provider(
    facet: CapabilityWorkerReadOnlyFacetProxy,
    release: _WorkerAttemptRelease,
    error_type: Callable[[str], RuntimeError],
    error_prefix: str,
) -> None:
    if facet.state != "visible" or release._released:
        raise error_type(f"{error_prefix}_activation_not_current")
    facet.require_current_publication()


class _QueryAuthority(_FacetGrantAuthority, Protocol):
    @property
    def binding(self) -> CapabilityWorkerBindingV1: ...

    def current_authority(self) -> CapabilityWorkerAuthorityV1: ...


class _ProviderSelectionPolicy(Protocol):
    @property
    def capability_id(self) -> str: ...

    @property
    def facet_id(self) -> str: ...

    def bind_authority(
        self, request: ManagedWorkerLaunchRequestV1
    ) -> _QueryAuthority: ...

    def capture(
        self,
        *,
        resolved: ResolvedCapabilityProvider,
        capability_authority: _QueryAuthority,
        adapter: CapabilityQueryWorkerAdapter,
        worker_admission: CapabilityWorkerAdmissionV1,
        graph_generation: int,
        release_attempt: Callable[[], Awaitable[None]],
        on_graph_publication: Callable[[], None],
    ) -> tuple[CapabilityProviderCandidateEnvelope, CapabilityWorkerBindingV1]: ...

    def read_candidate(
        self, resolved: ResolvedCapabilityProvider
    ) -> CapabilityProviderCandidateEnvelope: ...


_PreparedT = TypeVar("_PreparedT")
_PreparedCo = TypeVar("_PreparedCo", covariant=True)
_ReleaseContra = TypeVar(
    "_ReleaseContra", bound=_WorkerAttemptRelease, contravariant=True
)


class _PreparedFactory(Protocol[_ReleaseContra, _PreparedCo]):
    def __call__(
        self,
        *,
        binding: CapabilityBundleProviderBinding,
        facet: CapabilityWorkerReadOnlyFacetProxy,
        receipt_fingerprint: str,
        worker_admission_fingerprint: str,
        _release: _ReleaseContra,
        _commit: Callable[[], None] | None,
    ) -> _PreparedCo: ...


async def _prepare_native_worker_component(
    *,
    prepare_native: Callable[[], Coroutine[None, None, _NativeWorkerAttempt]],
    policy: _ProviderSelectionPolicy,
    receipt: ProductWorkerActivationReceiptV1,
    resolved_providers: ResolvedCapabilityProviderSet,
    expected_admission: CapabilityWorkerAdmissionV1,
    graph_generation: int,
    clock: Callable[[], int],
    base_policy_binding: _BasePolicyGuard | None,
    renewing_provider_owner: CapabilityProviderOwnerAuthority,
    release_type: type[_ReleaseT],
    prepared_factory: _PreparedFactory[_ReleaseT, _PreparedT],
    pending_failure: Callable[[str], RuntimeError],
    provider_error_type: Callable[[str], RuntimeError],
    provider_error_prefix: str,
    fingerprint_namespace: bytes,
    cleanup_note: str,
) -> _PreparedT:
    attempt: _NativeWorkerAttempt | None = None
    try:
        attempt = await prepare_native()
        authority = policy.bind_authority(attempt.request)
        adapter = bind_capability_query_worker_adapter(
            supervisor=attempt.supervisor,
            binding=authority.binding,
            authority_reader=authority.current_authority,
            enabled=True,
        )
        admitted = adapter.admit()
        if admitted != expected_admission:
            raise pending_failure("admission_changed")
        descriptors = await adapter.describe()
        if (
            len(descriptors) != 1
            or descriptors[0].capability_id != policy.capability_id
            or descriptors[0].facet_ids != (policy.facet_id,)
        ):
            raise pending_failure("descriptor_mismatch")
        [resolved] = resolved_providers.entries
        candidate, binding = policy.capture(
            resolved=resolved,
            capability_authority=authority,
            adapter=adapter,
            worker_admission=admitted,
            graph_generation=graph_generation,
            release_attempt=attempt.release,
            on_graph_publication=attempt.commit_activation,
        )
        graph_binding, facet, release = _prepare_worker_provider_binding(
            resolved=resolved,
            receipt=receipt,
            binding=binding,
            capability_authority=authority,
            adapter=adapter,
            worker_admission=admitted,
            graph_generation=graph_generation,
            clock=clock,
            release_attempt=attempt.release,
            candidate=candidate,
            read_candidate=lambda: policy.read_candidate(resolved),
            base_policy_binding=base_policy_binding,
            renewing_provider_owner=renewing_provider_owner,
            error_type=provider_error_type,
            error_prefix=provider_error_prefix,
            fingerprint_namespace=fingerprint_namespace,
            release_type=release_type,
        )
        return prepared_factory(
            binding=graph_binding,
            facet=facet,
            receipt_fingerprint=receipt.fingerprint,
            worker_admission_fingerprint=admitted.fingerprint,
            _release=release,
            _commit=attempt.commit_activation,
        )
    except BaseException as error:
        if attempt is not None:
            try:
                await attempt.release()
            except BaseException as cleanup_error:
                error.add_note(cleanup_note + type(cleanup_error).__name__)
        raise
