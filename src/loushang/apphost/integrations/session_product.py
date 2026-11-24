"""Private Product Session bindings for AppHost.

AppHost adopts the foreground Session returned by a Product factory. A Product
with no transcript storage can supply one static Session identity instead.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, cast

from loushang.apphost._ownership import (
    _ClaimedCandidateView,
    _method_descriptor,
    _OpenedCandidateView,
    _settle_owned_closes,
)
from loushang.apphost.contracts import (
    AppHostSessionLeaseV1,
    OpenedProductCandidateV1,
    ProductProfileBindingV1,
    ScopedProductRuntimeV1,
    SessionBindingKeyV1,
    SessionCandidateRefV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityCatalogPortV1,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.apphost.runtime import AppHostRuntimeV1, _BoundProfileView
from loushang.appserver.protocol import SessionIdentityV1, SessionOpenSpecV1
from loushang.harness.events import RuntimeEvent
from loushang.harness.runtime import await_owned_task
from loushang.harness.runtime._owned_tasks import (
    _get_close_task,
    _UnpublishedProductOwners,
)
from loushang.harness.session import SessionControlPort

from ._canonical_transcript_catalog import (
    _WorkspaceTranscriptCatalogMethods,
    canonical_discovery_scope,
    session_identity_matches_open,
)
from .session_control import (
    EventT,
    SnapshotT,
    _EventProjection,
    _HostedBinding,
    _SnapshotProjection,
    _validate_foreground_binding,
    canonical_resume_reference,
)

BindingT = TypeVar(
    "BindingT", bound=_HostedBinding[_SnapshotProjection, _EventProjection]
)
BindingCo = TypeVar(
    "BindingCo",
    bound=_HostedBinding[_SnapshotProjection, _EventProjection],
    covariant=True,
)


class _SessionFactory(Protocol[BindingCo]):
    async def create_session(
        self, *, binding_key: SessionBindingKeyV1, opaque_session_binding: object
    ) -> BindingCo: ...


class _SessionCatalogOwner(Protocol):
    def fence(self) -> None: ...
    async def close(self) -> None: ...


class _BorrowedProfileLease:
    """Detach a profile view while its runtime retains Session ownership."""

    __slots__ = ("_binding", "_closed", "_profile_id")

    def __init__(self, profile_id: str, binding: object) -> None:
        self._profile_id = profile_id
        self._binding = binding
        self._closed = False

    @property
    def profile_id(self) -> str:
        return self._profile_id

    @property
    def profile_binding(self) -> object:
        return self._binding

    async def close(self) -> None:
        self._closed = True


class _StaticClaimedCandidate(_ClaimedCandidateView[object]):
    __slots__ = ()

    def __init__(self, reference: SessionCandidateRefV1) -> None:
        super().__init__(reference, None)

    @property
    def opaque_binding(self) -> object:
        return self

    async def close(self) -> None:
        return None


class _StaticOpenedCandidate(_OpenedCandidateView[object]):
    __slots__ = ()

    def __init__(self, envelope: SessionIdentityEnvelopeV1) -> None:
        super().__init__(
            SessionBindingKeyV1(
                envelope.product_id, envelope.continuity_id, envelope.session_id
            ),
            None,
        )

    @property
    def opaque_binding(self) -> object:
        return self

    async def close(self) -> None:
        return None


class _StaticSessionCatalog:
    """Expose one preselected identity for a Product without transcript storage."""

    __slots__ = ("_projection", "_error")

    def __init__(
        self,
        projection: SessionIdentityProjectionV1,
        *,
        error: Callable[[str], Exception],
    ) -> None:
        self._projection = projection
        self._error = error

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._projection

    async def list_identities(
        self, scopes: tuple[SessionDiscoveryScope, ...], *, limit: int
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        if self._projection.scope not in scopes or limit < 1:
            return ()
        return (self._projection,)

    async def open_candidate(
        self, reference: SessionCandidateRefV1
    ) -> _StaticSessionCatalog:
        if reference != self._projection.reference:
            raise self._error("candidate_stale")
        return self

    async def find_created_candidate(
        self, request: SessionCreateRequestV1
    ) -> _StaticSessionCatalog | None:
        return None

    async def create_candidate(
        self, intent: SessionCreateIntentV1
    ) -> _StaticSessionCatalog:
        raise self._error("create_forbidden")

    async def verify_current(self) -> None:
        return None

    async def claim(self) -> _StaticClaimedCandidate:
        return _StaticClaimedCandidate(self._projection.reference)

    async def close(self) -> None:
        return None

    async def open_product_candidate(
        self, candidate: object, envelope: SessionIdentityEnvelopeV1
    ) -> _StaticOpenedCandidate:
        claimed = getattr(candidate, "opaque_binding", None)
        selected = self._projection.envelope
        if (
            not isinstance(claimed, _StaticClaimedCandidate)
            or selected is None
            or envelope.product_id != selected.product_id
            or envelope.product_compatibility_id != selected.product_compatibility_id
            or claimed.reference.candidate_id != envelope.session_id
        ):
            raise self._error("candidate_rejected")
        return _StaticOpenedCandidate(envelope)


class _LeasedForegroundBindingMethods(Generic[SnapshotT, EventT]):
    """Own the profile lease and the exact Session that it was issued for."""

    if not TYPE_CHECKING:
        __slots__ = ()

    _binding: _HostedBinding[SnapshotT, EventT]
    _close_lock: asyncio.Lock
    _close_task: asyncio.Task[None] | None
    _identity: SessionIdentityV1 | None
    _lease: AppHostSessionLeaseV1
    _lease_closed: bool
    _runtime: AppHostRuntimeV1
    _runtime_closed: bool

    def __init__(
        self,
        *,
        runtime: AppHostRuntimeV1,
        lease: AppHostSessionLeaseV1,
        binding: _HostedBinding[SnapshotT, EventT],
        identity: SessionIdentityV1 | None = None,
    ) -> None:
        self._runtime = runtime
        self._lease = lease
        self._binding = binding
        self._identity = identity
        self._lease_closed = False
        self._runtime_closed = False
        self._close_lock = asyncio.Lock()
        self._close_task = None

    @property
    def identity(self) -> SessionIdentityV1:
        return self._binding.identity if self._identity is None else self._identity

    @property
    def control(self) -> SessionControlPort | None:
        return self._binding.control

    def project_snapshot(self) -> SnapshotT:
        return self._binding.project_snapshot()

    def project_event(self, event: RuntimeEvent[object]) -> EventT | None:
        return self._binding.project_event(event)

    async def respond_interaction(self, interaction_id: str, outcome: str) -> bool:
        return await self._binding.respond_interaction(interaction_id, outcome)

    async def close(self) -> None:
        async with self._close_lock:
            if self._runtime_closed:
                return
            task = self._close_task = _get_close_task(
                self._close_task, self._close_once
            )
        await await_owned_task(task)

    async def _close_once(self) -> None:
        if not self._lease_closed:
            await self._lease.close()
            self._lease_closed = True
        if not self._runtime_closed:
            await self._runtime.close_session(self._lease.binding_key)
            self._runtime_closed = True


async def attach_canonical_foreground_session(
    runtime: AppHostRuntimeV1,
    request: SessionOpenSpecV1,
    *,
    sessions: SessionIdentityCatalogPortV1,
    workspace_catalog: _WorkspaceTranscriptCatalogMethods[Any] | None,
    profile_id: str,
    operation_id_factory: Callable[[], str],
    limit: int,
    missing_is_authoritative: bool,
    label: str,
) -> AppHostSessionLeaseV1:
    """Attach through the canonical candidate route after Product scope admission."""
    if request.session_id is None:
        operation_id = operation_id_factory()
        return await runtime.attach_create(
            SessionCreateRequestV1(
                product_id=request.product_id,
                creator_scope_id=request.scope_fingerprint,
                operation_id=operation_id,
                requested_continuity_id=request.continuity_id,
                requested_scope=canonical_discovery_scope(request.scope),
            ),
            profile_id=profile_id,
        )
    scope = canonical_discovery_scope(request.scope)
    if workspace_catalog is None:
        projections = await sessions.list_identities((scope,), limit=limit)
    else:
        projections = await workspace_catalog.workspace_identities(
            request.scope_fingerprint,
            scope,
            limit=limit,
        )
    reference = canonical_resume_reference(
        request,
        projections,
        scope=scope,
        limit=limit,
        missing_is_authoritative=missing_is_authoritative,
        label=label,
    )
    return await runtime.attach_resume(
        product_id=request.product_id,
        reference=reference,
        profile_id=profile_id,
    )


LeasedBindingT = TypeVar(
    "LeasedBindingT", bound=_LeasedForegroundBindingMethods[Any, Any]
)


@asynccontextmanager
async def bind_foreground_session_lease(
    runtime: AppHostRuntimeV1,
    lease: AppHostSessionLeaseV1,
    request: SessionOpenSpecV1,
    *,
    owner_type: type[LeasedBindingT],
    managed_selection: bool,
    after_cleanup: Callable[[], None],
    cleanup_error: str,
    label: str,
) -> AsyncIterator[LeasedBindingT]:
    """Validate and transfer one lease or settle both owners on failed delivery."""
    owner: LeasedBindingT | None = None
    try:
        binding = lease.profile_binding
        _validate_foreground_binding(binding, lease.binding_key, label=label)
        binding = cast(_HostedBinding[Any, Any], binding)
        original = binding.identity
        identity = None
        if managed_selection:
            if (
                original.product_id != request.product_id
                or original.continuity_id != request.continuity_id
                or (
                    request.session_id is not None
                    and original.session_id != request.session_id
                )
            ):
                raise ValueError("managed canonical identity mismatch")
            # AppHost keeps the canonical identity and projects only the admitted scope.
            identity = replace(
                original,
                scope=request.scope,
                scope_fingerprint=request.scope_fingerprint,
            )
        owner = owner_type(
            runtime=runtime, lease=lease, binding=binding, identity=identity
        )
        if not session_identity_matches_open(request, owner.identity):
            raise ValueError(f"{label} hosted binding identity mismatch")
        yield owner
    except BaseException:
        if owner is None:
            await _settle_owned_closes(
                lambda: lease.close(),
                lambda: runtime.close_session(lease.binding_key),
                failure=RuntimeError(cleanup_error),
                join_owned=await_owned_task,
            )
        else:
            await owner.close()
        after_cleanup()
        raise


class _ForegroundSessionOwner(Generic[BindingT]):
    """Adopt one Product Session before inspecting its public surface."""

    __slots__ = (
        "_binding",
        "_binding_key",
        "_profile",
        "_close_lock",
        "_close_task",
        "_closed",
    )

    def __init__(
        self, binding: object, key: SessionBindingKeyV1, *, label: str
    ) -> None:
        close = getattr(binding, "close", None)
        if not inspect.iscoroutinefunction(close):
            raise TypeError(f"{label} foreground Session has no close owner")
        self._binding = binding
        self._binding_key = key
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def binding(self) -> BindingT:
        return cast(BindingT, self._binding)

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            task = self._close_task = _get_close_task(
                self._close_task, lambda: self.binding.close()
            )
        await await_owned_task(task)
        async with self._close_lock:
            if self._close_task is task:
                self._closed = True
                self._close_task = None

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding_key

    @property
    def opaque_binding(self) -> object:
        return self.binding

    @property
    def profile_binding(self) -> ProductProfileBindingV1:
        return self._profile

    def _publish(self) -> None:
        self._profile = _BoundProfileView(self, self._binding_key)


class _ForegroundProductFactory(Generic[BindingT]):
    """Create foreground Product Sessions without a Hosting/Worker owner."""

    _product_id: str
    _product_label: str

    __slots__ = (
        "_create_session",
        "_unpublished",
        "_session_factory",
        "_session_owner",
    )

    def __init__(
        self,
        factory: _SessionFactory[BindingT],
        *,
        session_owner: _SessionCatalogOwner | None = None,
    ) -> None:
        if not inspect.iscoroutinefunction(
            _method_descriptor(factory, "create_session")
        ):
            raise TypeError(
                f"{self._product_label} hosted application create_session port is invalid"
            )
        self._create_session = factory.create_session
        self._session_factory = factory
        self._unpublished = _UnpublishedProductOwners[_ForegroundSessionOwner[BindingT]]()
        self._session_owner = session_owner

    async def create_runtime(
        self,
        candidate: OpenedProductCandidateV1,
    ) -> ScopedProductRuntimeV1:
        await self.settle_pending_cleanup()
        try:
            key = candidate.binding_key
            opaque = candidate.opaque_binding
        except BaseException:
            raise RuntimeError(
                f"{self._product_id}_foreground_candidate_invalid"
            ) from None
        if type(key) is not SessionBindingKeyV1 or key.product_id != self._product_id:
            raise RuntimeError(f"{self._product_id}_foreground_candidate_invalid")
        raw = await self._create_session(
            binding_key=key,
            opaque_session_binding=opaque,
        )
        try:
            owner: _ForegroundSessionOwner[BindingT] = _ForegroundSessionOwner(
                raw, key, label=self._product_label
            )
        except BaseException:
            raise RuntimeError(
                f"{self._product_id}_foreground_session_unowned"
            ) from None
        self._unpublished.adopt(owner)
        try:
            _validate_foreground_binding(owner.binding, key, label=self._product_label)
        except BaseException:
            await self._unpublished.abort(
                owner, failure=RuntimeError(f"{self._product_id}_foreground_cleanup_incomplete")
            )
            raise RuntimeError(
                f"{self._product_id}_foreground_session_invalid"
            ) from None
        self._unpublished.publish(owner)
        owner._publish()
        return owner

    async def settle_pending_cleanup(self) -> None:
        if not await self._unpublished.retry_cleanup() or self._unpublished.active:
            raise RuntimeError(f"{self._product_id}_foreground_cleanup_incomplete")

    async def close(self) -> None:
        failures: list[Exception] = []
        if self._session_owner is not None:
            try:
                self._session_owner.fence()
            except Exception as error:
                failures.append(error)
        try:
            await self.settle_pending_cleanup()
        except Exception as error:
            failures.append(error)
        if self._session_owner is not None:
            try:
                await self._session_owner.close()
            except Exception as error:
                failures.append(error)
        close_factory = getattr(self._session_factory, "close", None)
        if inspect.iscoroutinefunction(close_factory):
            try:
                await close_factory()
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]

__all__: list[str] = []
