"""Coding-owned foreground Product edge for the G12 hosted application."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from secrets import token_hex
from typing import Protocol, cast

from loushang.apphost import (
    AdmissionGenerationSourceV1,
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostCatalogInputV1,
    AppHostCatalogV1,
    AppHostRuntimeV1,
    AppHostSessionLeaseV1,
    AppHostShutdownBudgetV1,
    OpenedProductCandidateV1,
    ProductCandidateValidatorV1,
    ProductDescriptorV1,
    ProductProfileBindingV1,
    ProductRegistrationV1,
    ProfileDescriptorV1,
    ProfileLeaseV1,
    ProfileRegistrationV1,
    ScopedProductRuntimeV1,
    SessionBindingKeyV1,
    SessionCandidateMode,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityCatalogPortV1,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.apphost.application import (
    HostedApplicationActivationV1,
    HostedApplicationRequestV1,
    HostedApplicationRuntimeV1,
    create_hosted_application_runtime,
)
from loushang.appserver.protocol import (
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
)
from loushang.appservice import HostedSessionPortV1

from .appservice_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSessionBindingV1,
    CodingHostedSessionV1,
    CodingHostedSnapshotProjectionV1,
)
from .product_plan import CODING_PRODUCT_ID

CODING_HOSTED_APPLICATION_PROFILE_ID = "coding.hosted-mux"
CODING_HOSTED_APPLICATION_PROFILE_VERSION = "1"
CODING_HOSTED_APPLICATION_MAX_CANDIDATES = 256

_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,511})\Z")
_STABLE_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,127})\Z")


class CodingForegroundSessionFactoryV1(Protocol):
    """Create one independently owned Coding Session from an opened candidate."""

    async def create_session(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        opaque_session_binding: object,
    ) -> CodingHostedSessionBindingV1: ...


@dataclass(frozen=True, slots=True)
class CodingForegroundHostedApplicationRequestV1:
    """Complete explicit input for one Coding foreground hosted application."""

    activation: HostedApplicationActivationV1
    generation_id: str
    product_version: str
    compatibility_id: str
    product_admission_source: AdmissionGenerationSourceV1 = field(repr=False)
    profile_admission_source: AdmissionGenerationSourceV1 = field(repr=False)
    candidate_validator: ProductCandidateValidatorV1 = field(repr=False)
    sessions: SessionIdentityCatalogPortV1 = field(repr=False)
    session_factory: CodingForegroundSessionFactoryV1 = field(repr=False)
    shutdown_budget: AppHostShutdownBudgetV1
    profile_id: str = CODING_HOSTED_APPLICATION_PROFILE_ID
    profile_version: str = CODING_HOSTED_APPLICATION_PROFILE_VERSION
    operation_id_factory: Callable[[], str] = field(
        default=lambda: token_hex(16),
        repr=False,
    )
    service_id_factory: Callable[[], str] | None = field(default=None, repr=False)
    phase_timeout_seconds: float = 10.0
    service_close_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if type(self.activation) is not HostedApplicationActivationV1:
            raise TypeError("Coding hosted application requires explicit activation")
        for name, value in (
            ("generation_id", self.generation_id),
            ("product_version", self.product_version),
            ("compatibility_id", self.compatibility_id),
            ("profile_version", self.profile_version),
        ):
            if not isinstance(value, str) or _OPAQUE_TOKEN.fullmatch(value) is None:
                raise ValueError(f"Coding hosted application {name} is invalid")
        if _STABLE_ID.fullmatch(self.profile_id) is None:
            raise ValueError("Coding hosted application profile_id is invalid")
        for admission_source in (
            self.product_admission_source,
            self.profile_admission_source,
        ):
            _require_async_method(admission_source, "acquire_pin")
        _require_async_method(self.candidate_validator, "open_product_candidate")
        for method in (
            "list_identities",
            "open_candidate",
            "find_created_candidate",
            "create_candidate",
        ):
            _require_async_method(self.sessions, method)
        _require_async_method(self.session_factory, "create_session")
        if type(self.shutdown_budget) is not AppHostShutdownBudgetV1:
            raise TypeError("Coding hosted application shutdown budget is invalid")
        if not callable(self.operation_id_factory) or (
            self.service_id_factory is not None
            and not callable(self.service_id_factory)
        ):
            raise TypeError("Coding hosted application ID factory is invalid")


class _ForegroundSessionOwner:
    """Adopt one Product Session before inspecting its public surface."""

    __slots__ = ("_binding", "_close_lock", "_close_task", "_closed")

    def __init__(self, binding: object) -> None:
        close = getattr(binding, "close", None)
        if not inspect.iscoroutinefunction(close):
            raise TypeError("Coding foreground Session has no close owner")
        self._binding = binding
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def binding(self) -> CodingHostedSessionBindingV1:
        return cast(CodingHostedSessionBindingV1, self._binding)

    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            task = self._close_task
            if task is None or _void_task_needs_retry(task):
                task = asyncio.create_task(self.binding.close())
                task.add_done_callback(_observe_background_result)
                self._close_task = task
        await _join_void_owner(task)
        async with self._close_lock:
            if self._close_task is task:
                self._closed = True
                self._close_task = None


class _ForegroundProfileBinding:
    __slots__ = ("_binding_key", "_session")

    def __init__(
        self,
        binding_key: SessionBindingKeyV1,
        session: _ForegroundSessionOwner,
    ) -> None:
        self._binding_key = binding_key
        self._session = session

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding_key

    @property
    def opaque_binding(self) -> object:
        return self._session.binding


class _ForegroundProductRuntime:
    __slots__ = ("_binding_key", "_profile", "_session")

    def __init__(
        self,
        binding_key: SessionBindingKeyV1,
        session: _ForegroundSessionOwner,
    ) -> None:
        self._binding_key = binding_key
        self._session = session
        self._profile = _ForegroundProfileBinding(binding_key, session)

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._binding_key

    @property
    def profile_binding(self) -> ProductProfileBindingV1:
        return self._profile

    async def close(self) -> None:
        await self._session.close()


class CodingForegroundProductFactoryV1:
    """Create foreground Product Sessions without a Hosting/Worker owner."""

    __slots__ = ("_active", "_create_session", "_debt")

    def __init__(self, factory: CodingForegroundSessionFactoryV1) -> None:
        _require_async_method(factory, "create_session")
        self._create_session = factory.create_session
        self._active: set[_ForegroundSessionOwner] = set()
        self._debt: set[_ForegroundSessionOwner] = set()

    async def create_runtime(
        self,
        candidate: OpenedProductCandidateV1,
    ) -> ScopedProductRuntimeV1:
        await self.settle_pending_cleanup()
        try:
            key = candidate.binding_key
            opaque = candidate.opaque_binding
        except BaseException:
            raise RuntimeError("coding_foreground_candidate_invalid") from None
        if type(key) is not SessionBindingKeyV1 or key.product_id != CODING_PRODUCT_ID:
            raise RuntimeError("coding_foreground_candidate_invalid")
        raw = await self._create_session(
            binding_key=key,
            opaque_session_binding=opaque,
        )
        try:
            owner = _ForegroundSessionOwner(raw)
        except BaseException:
            raise RuntimeError("coding_foreground_session_unowned") from None
        self._active.add(owner)
        try:
            _validate_hosted_binding(owner.binding, key)
        except BaseException:
            await self._settle_unpublished(owner)
            raise RuntimeError("coding_foreground_session_invalid") from None
        self._active.discard(owner)
        return _ForegroundProductRuntime(key, owner)

    async def settle_pending_cleanup(self) -> None:
        debt = tuple(self._debt)
        if debt:
            results = await asyncio.gather(
                *(owner.close() for owner in debt),
                return_exceptions=True,
            )
            for owner, result in zip(debt, results, strict=True):
                if result is None:
                    self._debt.discard(owner)
        if self._debt or self._active:
            raise RuntimeError("coding_foreground_cleanup_incomplete")

    async def close(self) -> None:
        await self.settle_pending_cleanup()

    async def _settle_unpublished(self, owner: _ForegroundSessionOwner) -> None:
        try:
            await owner.close()
        except asyncio.CancelledError:
            self._active.discard(owner)
            self._debt.discard(owner)
            raise
        except BaseException:
            self._active.discard(owner)
            self._debt.add(owner)
            raise RuntimeError("coding_foreground_cleanup_incomplete") from None
        self._active.discard(owner)
        self._debt.discard(owner)


class _HostedProfileLease:
    __slots__ = ("_binding", "_closed", "_profile_id")

    def __init__(self, profile_id: str, binding: CodingHostedSessionBindingV1) -> None:
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


class CodingHostedProfileFactoryV1:
    """Bind the borrowed foreground Session view to one AppHost profile lease."""

    __slots__ = ("_profile_id",)

    def __init__(self, profile_id: str = CODING_HOSTED_APPLICATION_PROFILE_ID) -> None:
        if not isinstance(profile_id, str) or _STABLE_ID.fullmatch(profile_id) is None:
            raise ValueError("Coding hosted profile identity is invalid")
        self._profile_id = profile_id

    async def bind_profile(self, runtime: ProductProfileBindingV1) -> ProfileLeaseV1:
        try:
            key = runtime.binding_key
            binding = runtime.opaque_binding
        except BaseException:
            raise RuntimeError("coding_hosted_profile_invalid") from None
        if type(key) is not SessionBindingKeyV1:
            raise RuntimeError("coding_hosted_profile_invalid")
        _validate_hosted_binding(binding, key)
        return _HostedProfileLease(
            self._profile_id,
            cast(CodingHostedSessionBindingV1, binding),
        )


class _LeasedCodingHostedBinding:
    """Give AppService exact profile-detach and binding-close authority."""

    __slots__ = (
        "_binding",
        "_close_lock",
        "_close_task",
        "_lease",
        "_lease_closed",
        "_runtime",
        "_runtime_closed",
    )

    def __init__(
        self,
        *,
        runtime: AppHostRuntimeV1,
        lease: AppHostSessionLeaseV1,
        binding: CodingHostedSessionBindingV1,
    ) -> None:
        self._runtime = runtime
        self._lease = lease
        self._binding = binding
        self._lease_closed = False
        self._runtime_closed = False
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None

    @property
    def identity(self) -> SessionIdentityV1:
        return self._binding.identity

    @property
    def control(self):  # type: ignore[no-untyped-def]
        return self._binding.control

    def project_snapshot(self) -> CodingHostedSnapshotProjectionV1:
        return self._binding.project_snapshot()

    def project_event(self, event: object) -> CodingHostedEventProjectionV1 | None:
        return self._binding.project_event(event)  # type: ignore[arg-type]

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
        await _join_void_owner(task)

    async def _close_once(self) -> None:
        if not self._lease_closed:
            await self._lease.close()
            self._lease_closed = True
        if not self._runtime_closed:
            await self._runtime.close_session(self._lease.binding_key)
            self._runtime_closed = True


class CodingAppHostHostedSessionResolverV1:
    """Resolve G11 Session requests exclusively through canonical AppHost routes."""

    __slots__ = ("_operation_id", "_profile_id", "_runtime", "_sessions")

    def __init__(
        self,
        *,
        runtime: AppHostRuntimeV1,
        sessions: SessionIdentityCatalogPortV1,
        profile_id: str,
        operation_id_factory: Callable[[], str],
    ) -> None:
        if type(runtime) is not AppHostRuntimeV1:
            raise TypeError("Coding hosted resolver AppHost Runtime is invalid")
        if not callable(operation_id_factory):
            raise TypeError("Coding hosted resolver operation factory is invalid")
        self._runtime = runtime
        self._sessions = sessions
        self._profile_id = profile_id
        self._operation_id = operation_id_factory

    async def open_session(self, request: SessionOpenSpecV1) -> HostedSessionPortV1:
        if type(request) is not SessionOpenSpecV1 or request.product_id != (
            CODING_PRODUCT_ID
        ):
            raise ValueError("Coding hosted open request is invalid")
        lease = (
            await self._attach_create(request)
            if request.session_id is None
            else await self._attach_resume(request)
        )
        wrapper: _LeasedCodingHostedBinding | None = None
        try:
            binding = lease.profile_binding
            _validate_hosted_binding(binding, lease.binding_key)
            wrapper = _LeasedCodingHostedBinding(
                runtime=self._runtime,
                lease=lease,
                binding=cast(CodingHostedSessionBindingV1, binding),
            )
            if not _identity_matches_open(request, wrapper.identity):
                raise ValueError("Coding hosted binding identity mismatch")
            return CodingHostedSessionV1(wrapper)
        except BaseException:
            if wrapper is not None:
                await wrapper.close()
            else:
                await _close_rejected_lease(self._runtime, lease)
            raise

    async def _attach_create(
        self,
        request: SessionOpenSpecV1,
    ) -> AppHostSessionLeaseV1:
        operation_id = self._operation_id()
        return await self._runtime.attach_create(
            SessionCreateRequestV1(
                product_id=CODING_PRODUCT_ID,
                creator_scope_id=request.scope_fingerprint,
                operation_id=operation_id,
                requested_continuity_id=request.continuity_id,
                requested_scope=_apphost_scope(request.scope),
            ),
            profile_id=self._profile_id,
        )

    async def _attach_resume(
        self,
        request: SessionOpenSpecV1,
    ) -> AppHostSessionLeaseV1:
        scope = _apphost_scope(request.scope)
        projections = await self._sessions.list_identities(
            (scope,),
            limit=CODING_HOSTED_APPLICATION_MAX_CANDIDATES,
        )
        if (
            not isinstance(projections, tuple)
            or len(projections) > CODING_HOSTED_APPLICATION_MAX_CANDIDATES
            or any(type(item) is not SessionIdentityProjectionV1 for item in projections)
        ):
            raise ValueError("Coding hosted candidate catalog is invalid")
        same_session = tuple(
            item
            for item in projections
            if item.scope is scope
            and item.mode is SessionCandidateMode.CANONICAL
            and type(item.envelope) is SessionIdentityEnvelopeV1
            and item.envelope.session_id == request.session_id
        )
        matching = tuple(
            item
            for item in same_session
            if _envelope_matches(request, item.envelope)
        )
        if len(same_session) != 1 or len(matching) != 1:
            raise ValueError("Coding hosted Session candidate is unavailable")
        return await self._runtime.attach_resume(
            product_id=CODING_PRODUCT_ID,
            reference=matching[0].reference,
            profile_id=self._profile_id,
        )


async def create_coding_foreground_hosted_application(
    request: CodingForegroundHostedApplicationRequestV1,
) -> HostedApplicationRuntimeV1:
    """Compose one explicit Coding/AppHost/AppService foreground application."""

    if type(request) is not CodingForegroundHostedApplicationRequestV1:
        raise TypeError("Coding foreground hosted application request is invalid")
    product_factory = CodingForegroundProductFactoryV1(request.session_factory)
    catalog: AppHostCatalogV1 | None = None
    runtime: AppHostRuntimeV1 | None = None
    try:
        product = ProductRegistrationV1(
            descriptor=ProductDescriptorV1(
                product_id=CODING_PRODUCT_ID,
                product_version=request.product_version,
                compatibility_id=request.compatibility_id,
                supported_profile_ids=(request.profile_id,),
            ),
            factory=product_factory,
            candidate_validator=request.candidate_validator,
            admission_identity=AdmissionIdentityV1(
                request.generation_id,
                AppHostAdmissionSubjectKind.PRODUCT,
                CODING_PRODUCT_ID,
            ),
            admission_source=request.product_admission_source,
        )
        profile = ProfileRegistrationV1(
            descriptor=ProfileDescriptorV1(
                request.profile_id,
                request.profile_version,
            ),
            factory=CodingHostedProfileFactoryV1(request.profile_id),
            admission_identity=AdmissionIdentityV1(
                request.generation_id,
                AppHostAdmissionSubjectKind.PROFILE,
                request.profile_id,
            ),
            admission_source=request.profile_admission_source,
        )
        catalog = await AppHostCatalogV1.admit(
            AppHostCatalogInputV1(
                generation_id=request.generation_id,
                products=(product,),
                profiles=(profile,),
            )
        )
        runtime = AppHostRuntimeV1(catalog, request.sessions)
        resolver = CodingAppHostHostedSessionResolverV1(
            runtime=runtime,
            sessions=request.sessions,
            profile_id=request.profile_id,
            operation_id_factory=request.operation_id_factory,
        )
        return create_hosted_application_runtime(
            HostedApplicationRequestV1(
                activation=request.activation,
                product_id=CODING_PRODUCT_ID,
                generation_id=request.generation_id,
                apphost=runtime,
                resolver=resolver,
                product_owner=product_factory,
                shutdown_budget=request.shutdown_budget,
                phase_timeout_seconds=request.phase_timeout_seconds,
                service_close_timeout_seconds=request.service_close_timeout_seconds,
                service_id_factory=request.service_id_factory,
            )
        )
    except BaseException:
        await _settle_failed_construction(runtime, catalog, product_factory)
        raise


async def _settle_failed_construction(
    runtime: AppHostRuntimeV1 | None,
    catalog: AppHostCatalogV1 | None,
    product_factory: CodingForegroundProductFactoryV1,
) -> None:
    async def settle() -> None:
        failures: list[BaseException] = []
        if runtime is not None:
            try:
                await runtime.close()
            except BaseException as error:
                failures.append(error)
        elif catalog is not None:
            try:
                await catalog.close()
            except BaseException as error:
                failures.append(error)
        try:
            await product_factory.close()
        except BaseException as error:
            failures.append(error)
        if failures:
            raise RuntimeError("coding_foreground_cleanup_incomplete") from None

    task = asyncio.create_task(settle())
    await _join_void_owner(task)


async def _close_rejected_lease(
    runtime: AppHostRuntimeV1,
    lease: AppHostSessionLeaseV1,
) -> None:
    async def settle() -> None:
        failures: list[BaseException] = []
        try:
            await lease.close()
        except BaseException as error:
            failures.append(error)
        try:
            await runtime.close_session(lease.binding_key)
        except BaseException as error:
            failures.append(error)
        if failures:
            raise RuntimeError("coding_foreground_cleanup_incomplete") from None

    await _join_void_owner(asyncio.create_task(settle()))


def _validate_hosted_binding(
    binding: object,
    key: SessionBindingKeyV1,
) -> None:
    try:
        identity = cast(CodingHostedSessionBindingV1, binding).identity
        control = cast(CodingHostedSessionBindingV1, binding).control
    except BaseException:
        raise TypeError("Coding hosted Session binding is invalid") from None
    if (
        type(identity) is not SessionIdentityV1
        or identity.product_id != key.product_id
        or identity.continuity_id != key.continuity_id
        or identity.session_id != key.session_id
    ):
        raise TypeError("Coding hosted Session identity is invalid")
    for name in ("project_snapshot", "project_event"):
        if not callable(getattr(binding, name, None)):
            raise TypeError("Coding hosted Session binding is invalid")
    for name in ("respond_interaction", "close"):
        if not inspect.iscoroutinefunction(_method_descriptor(binding, name)):
            raise TypeError("Coding hosted Session binding is invalid")
    for name in (
        "subscribe_runtime_events",
        "prompt",
        "wait_for_idle",
        "steer",
        "follow_up",
        "abort",
    ):
        if not callable(getattr(control, name, None)):
            raise TypeError("Coding hosted Session control is invalid")


def _identity_matches_open(
    request: SessionOpenSpecV1,
    identity: SessionIdentityV1,
) -> bool:
    return (
        identity.product_id == request.product_id
        and identity.continuity_id == request.continuity_id
        and identity.scope is request.scope
        and identity.scope_fingerprint == request.scope_fingerprint
        and (request.session_id is None or identity.session_id == request.session_id)
    )


def _envelope_matches(
    request: SessionOpenSpecV1,
    envelope: SessionIdentityEnvelopeV1 | None,
) -> bool:
    return (
        type(envelope) is SessionIdentityEnvelopeV1
        and envelope.product_id == request.product_id
        and envelope.continuity_id == request.continuity_id
        and envelope.session_id == request.session_id
    )


def _apphost_scope(scope: SessionScopeV1) -> SessionDiscoveryScope:
    return (
        SessionDiscoveryScope.CURRENT_DIRECTORY
        if scope is SessionScopeV1.CWD
        else SessionDiscoveryScope.USER_GLOBAL_CANONICAL
    )


def _method_descriptor(value: object, name: str) -> object:
    descriptor = inspect.getattr_static(type(value), name, None)
    if isinstance(descriptor, (classmethod, staticmethod)):
        return descriptor.__func__
    return descriptor


def _require_async_method(value: object, name: str) -> None:
    if not inspect.iscoroutinefunction(_method_descriptor(value, name)):
        raise TypeError(f"Coding hosted application {name} port is invalid")


async def _join_void_owner(task: asyncio.Task[None]) -> None:
    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if caller is None or caller.cancelling() == 0:
                return task.result()
            cancellation = error
    task.result()
    if cancellation is not None:
        raise cancellation


def _observe_background_result(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


def _void_task_needs_retry(task: asyncio.Task[None]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


__all__ = [
    "CODING_HOSTED_APPLICATION_MAX_CANDIDATES",
    "CODING_HOSTED_APPLICATION_PROFILE_ID",
    "CODING_HOSTED_APPLICATION_PROFILE_VERSION",
    "CodingAppHostHostedSessionResolverV1",
    "CodingForegroundHostedApplicationRequestV1",
    "CodingForegroundProductFactoryV1",
    "CodingForegroundSessionFactoryV1",
    "CodingHostedProfileFactoryV1",
    "create_coding_foreground_hosted_application",
]
