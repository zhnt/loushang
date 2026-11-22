"""Private foreground Product ownership over an admitted hosted Session.

The Product supplies its existing Session factory and catalog owner.  This
adapter owns only the returned Session until the AppHost runtime adopts it.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar, cast

from loushang.apphost.application import (
    _method_descriptor,
    _observe_background_result,
)
from loushang.apphost.application import (
    _phase_task_failed as _void_task_needs_retry,
)
from loushang.apphost.contracts import (
    AppHostSessionLeaseV1,
    OpenedProductCandidateV1,
    ProductProfileBindingV1,
    ScopedProductRuntimeV1,
    SessionBindingKeyV1,
)
from loushang.apphost.runtime import AppHostRuntimeV1, _BoundProfileView
from loushang.appserver.protocol import SessionIdentityV1
from loushang.harness.events import RuntimeEvent
from loushang.harness.runtime import await_owned_task
from loushang.harness.runtime._owned_tasks import _UnpublishedProductOwners
from loushang.harness.session import SessionControlPort

from .session_control import (
    EventT,
    SnapshotT,
    _EventProjection,
    _HostedBinding,
    _SnapshotProjection,
    _validate_foreground_binding,
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
            task = self._close_task
            if task is None or _void_task_needs_retry(task):
                task = asyncio.create_task(self._close_once())
                task.add_done_callback(_observe_background_result)
                self._close_task = task
        await await_owned_task(task)

    async def _close_once(self) -> None:
        if not self._lease_closed:
            await self._lease.close()
            self._lease_closed = True
        if not self._runtime_closed:
            await self._runtime.close_session(self._lease.binding_key)
            self._runtime_closed = True


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
            task = self._close_task
            if task is None or _void_task_needs_retry(task):
                task = asyncio.create_task(self.binding.close())
                task.add_done_callback(_observe_background_result)
                self._close_task = task
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
