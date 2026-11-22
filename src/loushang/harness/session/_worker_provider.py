"""Session graph integration for an owner-admitted Worker Provider."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from functools import partial
from hashlib import sha256
from typing import TYPE_CHECKING, ClassVar, Generic, Protocol, Self, TypeVar, cast

from loushang.harness.capabilities import MODEL_INPUT_CAPABILITY_DEFINITION
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionAuthorityContext,
    ProductCompositionCompiler,
)
from loushang.harness.capabilities.contracts import (
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderCandidateEnvelope,
    CapabilityProviderOwnerAuthority,
    CapabilityWorkerProviderBindingSpec,
    _admit_provider_for_duration,
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
from loushang.harness.resume_effects import ResumeEffectParentContextV1
from loushang.harness.session.capability_composition_inputs import (
    PreparedSessionWorkerCapabilityComponent,
    SessionCapabilityCompositionInputs,
    SessionCapabilityWorkerComponentRequest,
)
from loushang.harness.worker._ordinary_prepare import (
    _NativeWorkerAttempt,
    _ResumeBinding,
)
from loushang.harness.worker.capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    CapabilityWorkerFacetGrantV1,
    _admission_for_worker,
    _binding_for_worker,
    bind_capability_query_worker_adapter,
)
from loushang.harness.worker.facet_proxy import CapabilityWorkerReadOnlyFacetProxy
from loushang.harness.worker.payload._selected_payload import _PendingPayload
from loushang.harness.worker.product_activation import ProductWorkerActivationReceiptV1

if TYPE_CHECKING:
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
    )


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
            renewed = _admit_provider_for_duration(
                renewing_provider_owner,
                current_candidate,
                issued_at=now,
                eligibility_duration=admission_window,
                admission_duration=admission_window,
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


_ReceiptOwnerT = TypeVar("_ReceiptOwnerT")
_QueryAuthorityT = TypeVar("_QueryAuthorityT", bound=_QueryAuthority)
_BasePolicyT = TypeVar("_BasePolicyT", bound=_BasePolicyGuard)
_ReceiptOwnerCo = TypeVar("_ReceiptOwnerCo", covariant=True)
_BasePolicyCo = TypeVar("_BasePolicyCo", bound=_BasePolicyGuard, covariant=True)


class _PendingProviderInputs(Protocol[_ReceiptOwnerCo, _BasePolicyCo]):
    @property
    def receipt_owner(self) -> _ReceiptOwnerCo: ...
    @property
    def receipt(self) -> ProductWorkerActivationReceiptV1: ...
    @property
    def pending_launch(self) -> _PendingPayload: ...
    @property
    def expected_admission(self) -> CapabilityWorkerAdmissionV1: ...
    @property
    def resolved_providers(self) -> ResolvedCapabilityProviderSet: ...
    @property
    def provider_owner(self) -> CapabilityProviderOwnerAuthority: ...
    @property
    def binding(self) -> CapabilityWorkerBindingV1: ...
    @property
    def base_policy_binding(self) -> _BasePolicyCo: ...
    @property
    def clock(self) -> Callable[[], int]: ...
    @property
    def resume_parent_context(self) -> ResumeEffectParentContextV1 | None: ...
    @property
    def resume_settlement(self) -> _ResumeBinding | None: ...


class _PreparedWorkerProviderMethods(
    Generic[_ReceiptOwnerT, _QueryAuthorityT, _BasePolicyT]
):
    """Operations on the caller's existing prepared value, without extra state."""

    __slots__ = ()
    facet: CapabilityWorkerReadOnlyFacetProxy
    _release: _WorkerAttemptRelease
    _commit: Callable[[], None] | None
    _provider_error_type: ClassVar[type[RuntimeError]]
    _provider_error_prefix: ClassVar[str]
    _provider_fingerprint_namespace: ClassVar[bytes]
    _provider_release_type: ClassVar[type[_WorkerAttemptRelease]]
    _provider_read_inputs: ClassVar[
        Callable[
            ..., tuple[CapabilityProviderCandidateEnvelope, CapabilityWorkerBindingV1]
        ]
    ]
    _provider_read_candidate: ClassVar[
        Callable[..., CapabilityProviderCandidateEnvelope]
    ]

    def commit_after_graph_publication(self) -> None:
        _commit_worker_provider(
            self.facet,
            self._commit,
            self._provider_error_type,
            self._provider_error_prefix,
        )

    async def abort_uncommitted(self) -> bool:
        return await _abort_worker_provider(self.facet, self._release)

    def require_current_activation(self) -> None:
        _require_current_worker_provider(
            self.facet,
            self._release,
            self._provider_error_type,
            self._provider_error_prefix,
        )

    @classmethod
    def _prepare(
        cls,
        *,
        resolved: ResolvedCapabilityProvider,
        receipt_owner: _ReceiptOwnerT,
        receipt: ProductWorkerActivationReceiptV1,
        capability_authority: _QueryAuthorityT,
        adapter: CapabilityQueryWorkerAdapter,
        worker_admission: CapabilityWorkerAdmissionV1,
        graph_generation: int,
        clock: Callable[[], int],
        release_attempt: Callable[[], Awaitable[None]],
        base_policy_binding: _BasePolicyT | None = None,
        renewing_provider_owner: CapabilityProviderOwnerAuthority | None = None,
        on_graph_publication: Callable[[], None] | None = None,
    ) -> Self:
        """Prepare a graph binding only for an exact current Product/owner selection."""
        candidate, binding = cls._provider_read_inputs(
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
            return cls._provider_read_candidate(
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
            error_type=cls._provider_error_type,
            error_prefix=cls._provider_error_prefix,
            fingerprint_namespace=cls._provider_fingerprint_namespace,
            release_type=cls._provider_release_type,
        )
        return cast(Callable[..., Self], cls)(
            binding=graph_binding,
            facet=facet,
            receipt_fingerprint=receipt.fingerprint,
            worker_admission_fingerprint=worker_admission.fingerprint,
            _release=release,
            _commit=on_graph_publication,
        )

    @classmethod
    async def _prepare_pending(
        cls,
        host: _PendingProviderInputs[_ReceiptOwnerT, _BasePolicyT],
        graph_generation: int,
        *,
        policy: PendingWorkerSessionPolicy,
        native_prepare: Callable[..., Coroutine[None, None, _NativeWorkerAttempt]],
        bind_authority: Callable[..., _QueryAuthorityT],
        capability_id: str,
        facet_id: str,
        parent_failure: Callable[[str], RuntimeError],
        require_recovered: Callable[[], None] | None = None,
    ) -> Self:
        """Check the admitted host before letting graph preparation start native effects."""
        if type(graph_generation) is not int or graph_generation < 1:
            raise TypeError(policy.invalid_generation)
        if require_recovered is not None or host.base_policy_binding is not None:
            host.base_policy_binding.assert_current()
        if require_recovered is not None:
            require_recovered()
        return await cls._prepare_native(
            prepare_native=partial(
                native_prepare,
                launch_source=host.receipt_owner,
                activation=host.receipt_owner,
                pending_launch=host.pending_launch,
                receipt=host.receipt,
                resume_parent_context=host.resume_parent_context,
                resume_settlement=host.resume_settlement,
                failure=policy.failure,
                parent_failure=parent_failure,
                failure_code_prefix=policy.error_prefix,
                task_name_prefix=policy.task_name_prefix,
                cleanup_note=policy.cleanup_note,
                correlation_id=policy.correlation_id,
            ),
            bind_authority=partial(
                bind_authority,
                receipt_owner=host.receipt_owner,
                receipt=host.receipt,
                binding=host.binding,
                provider_owner=host.provider_owner,
            ),
            capability_id=capability_id,
            facet_id=facet_id,
            receipt_owner=host.receipt_owner,
            receipt=host.receipt,
            resolved_providers=host.resolved_providers,
            expected_admission=host.expected_admission,
            graph_generation=graph_generation,
            clock=host.clock,
            base_policy_binding=host.base_policy_binding,
            renewing_provider_owner=host.provider_owner,
            pending_failure=policy.failure,
            cleanup_note=policy.cleanup_note,
        )

    @classmethod
    async def _prepare_native(
        cls,
        *,
        prepare_native: Callable[[], Coroutine[None, None, _NativeWorkerAttempt]],
        bind_authority: Callable[..., _QueryAuthorityT],
        capability_id: str,
        facet_id: str,
        receipt_owner: _ReceiptOwnerT,
        receipt: ProductWorkerActivationReceiptV1,
        resolved_providers: ResolvedCapabilityProviderSet,
        expected_admission: CapabilityWorkerAdmissionV1,
        graph_generation: int,
        clock: Callable[[], int],
        base_policy_binding: _BasePolicyT | None,
        renewing_provider_owner: CapabilityProviderOwnerAuthority,
        pending_failure: Callable[[str], RuntimeError],
        cleanup_note: str,
    ) -> Self:
        attempt: _NativeWorkerAttempt | None = None
        try:
            attempt = await prepare_native()
            authority = bind_authority(request=attempt.request)
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
                or descriptors[0].capability_id != capability_id
                or descriptors[0].facet_ids != (facet_id,)
            ):
                raise pending_failure("descriptor_mismatch")
            [resolved] = resolved_providers.entries
            return cls._prepare(
                resolved=resolved,
                receipt_owner=receipt_owner,
                receipt=receipt,
                capability_authority=authority,
                adapter=adapter,
                worker_admission=admitted,
                graph_generation=graph_generation,
                clock=clock,
                release_attempt=attempt.release,
                base_policy_binding=base_policy_binding,
                renewing_provider_owner=renewing_provider_owner,
                on_graph_publication=attempt.commit_activation,
            )
        except BaseException as error:
            if attempt is not None:
                try:
                    await attempt.release()
                except BaseException as cleanup_error:
                    error.add_note(cleanup_note + type(cleanup_error).__name__)
            raise


def _read_worker_provider_inputs(
    *,
    resolved: ResolvedCapabilityProvider,
    receipt_owner: object,
    receipt: ProductWorkerActivationReceiptV1,
    capability_authority: _QueryAuthority,
    adapter: CapabilityQueryWorkerAdapter,
    worker_admission: CapabilityWorkerAdmissionV1,
    graph_generation: int,
    clock: Callable[[], int],
    release_attempt: Callable[[], Awaitable[None]],
    base_policy_binding: _BasePolicyGuard | None = None,
    renewing_provider_owner: CapabilityProviderOwnerAuthority | None = None,
    on_graph_publication: Callable[[], None] | None = None,
    receipt_owner_types: tuple[type[object], ...],
    capability_authority_type: type[_QueryAuthority],
    read_candidate: Callable[..., CapabilityProviderCandidateEnvelope],
    native_platform_for_owner: Callable[..., str],
    error_type: type[RuntimeError],
    error_prefix: str,
    invalid_inputs: str,
) -> tuple[CapabilityProviderCandidateEnvelope, CapabilityWorkerBindingV1]:
    """Prepare a graph binding only for an exact current Product/owner selection."""
    if (
        not isinstance(resolved, ResolvedCapabilityProvider)
        or type(receipt_owner) not in receipt_owner_types
        or (not isinstance(receipt, ProductWorkerActivationReceiptV1))
        or (not isinstance(capability_authority, capability_authority_type))
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
        raise TypeError(invalid_inputs)
    spec = resolved.binding_spec
    if not isinstance(spec, CapabilityWorkerProviderBindingSpec):
        raise error_type(error_prefix + "_binding_not_worker")
    candidate = read_candidate(
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
        or spec.native_platform != native_platform_for_owner(receipt_owner)
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
        raise error_type(error_prefix + "_host_mismatch")
    adapter.assert_admitted_current(worker_admission)
    return (candidate, binding)


class _SelectedWorkerManifestOwner(Protocol):
    def current_selected_manifest(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PackageProductSelectedPluginManifestV1: ...


@dataclass(frozen=True, slots=True)
class PendingWorkerSessionPolicy:
    invalid_generation: str
    error_type: type[RuntimeError]
    error_prefix: str
    task_name_prefix: str
    correlation_id: str
    cleanup_note: str

    def failure(self, code: str) -> RuntimeError:
        return self.error_type(f"{self.error_prefix}_pending_{code}")


class _PendingWorkerHost(Protocol):
    def prepare(
        self, graph_generation: int
    ) -> Awaitable[PreparedSessionWorkerCapabilityComponent]: ...


_ResumeSettlementT = TypeVar("_ResumeSettlementT")


def _prepare_pending_worker_session_inputs(
    *,
    resolved_providers: ResolvedCapabilityProviderSet,
    provider_owner: CapabilityProviderOwnerAuthority,
    receipt_owner: object,
    receipt: ProductWorkerActivationReceiptV1,
    pending_launch: _PendingPayload,
    evaluated_at: int,
    clock: Callable[[], int],
    base_policy_binding: _BasePolicyGuard,
    resume_parent_context: ResumeEffectParentContextV1 | None,
    resume_settlement: _ResumeSettlementT,
    resume_matches: Callable[
        [
            ProductWorkerActivationReceiptV1,
            ResumeEffectParentContextV1 | None,
            _ResumeSettlementT,
        ],
        bool,
    ],
    definition: CapabilityDefinition,
    expected_provider_owner: Callable[[], CapabilityProviderOwnerAuthority],
    owner_policy_revision: str,
    base_policy_type: type[_BasePolicyGuard],
    host_type: Callable[..., _PendingWorkerHost],
    prepare_session_inputs: Callable[..., SessionCapabilityCompositionInputs],
    policy: PendingWorkerSessionPolicy,
    require_bound_receipt_owner: bool = False,
) -> SessionCapabilityCompositionInputs:
    """Join the receipt, owner and Resume facts before deferred native preparation."""
    if (
        not resume_matches(receipt, resume_parent_context, resume_settlement)
        or pending_launch.receipt_fingerprint != receipt.fingerprint
        or not isinstance(base_policy_binding, base_policy_type)
        or (
            require_bound_receipt_owner
            and getattr(base_policy_binding, "receipt_owner") is not receipt_owner
        )
        or len(resolved_providers.entries) != 1
        or resolved_providers.entries[0].capability_id != definition.capability_id
        or resolved_providers.entries[0].definition != definition
        or provider_owner.policy != expected_provider_owner().policy
    ):
        raise policy.failure("selection_invalid")
    base_policy_binding.assert_current()
    identity = pending_launch.identity
    binding = _binding_for_worker(
        identity,
        allowed_capability_ids=(definition.capability_id,),
        product_policy_revision=lambda: receipt.policy.product_policy_revision,
        owner_policy_revision=owner_policy_revision,
        revocation_epoch=0,
    )
    admission = _admission_for_worker(binding, identity)
    host = host_type(
        resolved_providers=resolved_providers,
        provider_owner=provider_owner,
        receipt_owner=receipt_owner,
        receipt=receipt,
        pending_launch=pending_launch,
        expected_admission=admission,
        binding=binding,
        base_policy_binding=base_policy_binding,
        clock=clock,
        resume_parent_context=resume_parent_context,
        resume_settlement=resume_settlement,
    )
    return prepare_session_inputs(
        resolved_providers=resolved_providers,
        provider_owner=provider_owner,
        receipt_owner=receipt_owner,
        receipt=receipt,
        capability_authority=None,
        adapter=None,
        worker_admission=admission,
        evaluated_at=evaluated_at,
        clock=clock,
        release_attempt=None,
        base_policy_binding=base_policy_binding,
        deferred_prepare=host.prepare,
    )


def _prepare_worker_session_inputs(
    *,
    resolved_providers: ResolvedCapabilityProviderSet,
    provider_owner: CapabilityProviderOwnerAuthority,
    receipt_owner: _SelectedWorkerManifestOwner,
    receipt: ProductWorkerActivationReceiptV1,
    capability_authority: _QueryAuthority | None,
    adapter: CapabilityQueryWorkerAdapter | None,
    worker_admission: CapabilityWorkerAdmissionV1,
    evaluated_at: int,
    clock: Callable[[], int],
    release_attempt: Callable[[], Awaitable[None]] | None,
    base_policy_binding: _BasePolicyGuard | None = None,
    deferred_prepare: Callable[
        [int], Awaitable[PreparedSessionWorkerCapabilityComponent]
    ]
    | None = None,
    read_candidate: Callable[..., CapabilityProviderCandidateEnvelope],
    prepare_binding: Callable[..., PreparedSessionWorkerCapabilityComponent],
    consumer_requirements: Callable[
        [ResolvedCapabilityProvider, CapabilityProviderOwnerAuthority],
        tuple[CapabilityRequirement, ...],
    ],
    error_type: type[RuntimeError],
    error_prefix: str,
    receipt_owner_types: tuple[type[object], ...],
    capability_authority_type: type[object],
    invalid_inputs_message: str,
) -> SessionCapabilityCompositionInputs:
    """Rejoin exact Worker facts and compile the existing Session request."""
    if (
        not isinstance(resolved_providers, ResolvedCapabilityProviderSet)
        or not isinstance(provider_owner, CapabilityProviderOwnerAuthority)
        or type(receipt_owner) not in receipt_owner_types
        or (not isinstance(receipt, ProductWorkerActivationReceiptV1))
        or (not isinstance(worker_admission, CapabilityWorkerAdmissionV1))
        or (type(evaluated_at) is not int)
        or (evaluated_at < 0)
        or (not callable(clock))
        or (
            deferred_prepare is None
            and (
                not isinstance(capability_authority, capability_authority_type)
                or not isinstance(adapter, CapabilityQueryWorkerAdapter)
                or (not callable(release_attempt))
            )
        )
        or (
            deferred_prepare is not None
            and (
                not callable(deferred_prepare)
                or capability_authority is not None
                or adapter is not None
                or (release_attempt is not None)
            )
        )
    ):
        raise TypeError(invalid_inputs_message)
    if (
        len(resolved_providers.entries) != 1
        or resolved_providers.roots != (resolved_providers.entries[0].capability_id,)
        or resolved_providers.prebound_providers
        or resolved_providers.optional_decisions
    ):
        raise error_type(error_prefix + "_session_provider_closure_invalid")
    resolved = resolved_providers.entries[0]
    spec = resolved.binding_spec
    if not isinstance(spec, CapabilityWorkerProviderBindingSpec):
        raise error_type(error_prefix + "_session_provider_not_worker")
    candidate = read_candidate(
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
        or (owner_snapshot.policy_revision != resolved.admission.owner_policy_revision)
        or (owner_snapshot.revocation_epoch != resolved.admission.revocation_epoch)
        or (trust is None)
        or (not trust.trusted)
        or (trust.plugin_id != spec.plugin_id)
        or (trust.package_source_identity != candidate.package_source_identity)
        or (trust.source_trust_class != candidate.source_trust_class)
        or (
            trust.source_trust_policy_revision != candidate.source_trust_policy_revision
        )
        or (
            not resolved.admission.issued_at
            <= evaluated_at
            < resolved.admission.expires_at
        )
        or (adapter is not None and adapter.admission != worker_admission)
        or (resolved_providers.product_id != receipt.policy.product_id)
        or (
            resolved_providers.product_policy_revision
            != candidate.product_policy_revision
        )
        or (resolved_providers.evaluated_at != evaluated_at)
    ):
        raise error_type(error_prefix + "_session_selection_stale")
    host_consumer_requirements = consumer_requirements(resolved, provider_owner)
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
        return prepare_binding(
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
