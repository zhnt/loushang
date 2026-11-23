"""Coding-owned foreground Product edge for the G12 hosted application."""

from __future__ import annotations

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
    AppHostRuntimeV1,
    AppHostSessionLeaseV1,
    AppHostShutdownBudgetV1,
    ProductCandidateValidatorV1,
    ProductDescriptorV1,
    ProductProfileBindingV1,
    ProductRegistrationV1,
    ProfileDescriptorV1,
    ProfileLeaseV1,
    ProfileRegistrationV1,
    SessionBindingKeyV1,
    SessionIdentityCatalogPortV1,
)
from loushang.apphost import (
    OpenedProductCandidateV1 as OpenedProductCandidateV1,
)
from loushang.apphost import (
    ScopedProductRuntimeV1 as ScopedProductRuntimeV1,
)
from loushang.apphost._ownership import (
    _construct_product_apphost,
)
from loushang.apphost.application import (
    HostedApplicationActivationV1,
    HostedApplicationRequestV1,
    HostedApplicationRuntimeV1,
    _method_descriptor,
    create_hosted_application_runtime,
)
from loushang.apphost.integrations.session_control import (
    _validate_foreground_binding,
)
from loushang.apphost.integrations.session_product import (
    _BorrowedProfileLease,
    _ForegroundProductFactory,
    _LeasedForegroundBindingMethods,
    attach_canonical_foreground_session,
    bind_foreground_session_lease,
)
from loushang.appserver.protocol import (
    SessionIdentityV1,
    SessionOpenSpecV1,
)
from loushang.appservice import HostedSessionPortV1
from loushang.appservice.discovery_ports import (
    HostedSessionDiscoveryBindingV1,
    HostedSessionDiscoveryScopeV1,
    require_admitted_scopes,
    require_discovery_context,
)
from loushang.appservice.execution_service import HostedExecutionServiceBindingV1
from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
from loushang.appservice.ports import (
    HostedSessionResolutionErrorV1,
    HostedSessionResolutionFailureV1,
    HostedWorkspacePort,
)
from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.hosted._goal_config import HostedGoalSetup
from loushang.coding.hosted._method_config import CodingHostedMethodV1
from loushang.coding.hosted.service_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSessionBindingV1,
    CodingHostedSessionV1,
    CodingHostedSnapshotProjectionV1,
)
from loushang.harness.runtime import await_owned_task

CODING_HOSTED_APPLICATION_PROFILE_ID = "coding.hosted-mux"
CODING_MANAGED_APPLICATION_PROFILE_ID = "coding.managed-mux"
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


class CodingHostedSessionOwnerV1(Protocol):
    """Product-selected catalog resources, separate from delivered Sessions."""

    def fence(self) -> None: ...

    async def close(self) -> None: ...


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
    discovery: HostedSessionDiscoveryBindingV1 | None = field(default=None, repr=False)
    admitted_scopes: tuple[HostedSessionDiscoveryScopeV1, ...] | None = None
    execution: HostedExecutionServiceBindingV1 | None = field(default=None, repr=False)
    workspaces: HostedWorkspacePort | None = field(default=None, repr=False)
    method: CodingHostedMethodV1 | None = field(default=None, repr=False, kw_only=True)
    goal: HostedGoalSetup | None = field(default=None, repr=False, kw_only=True)
    session_owner: CodingHostedSessionOwnerV1 | None = field(default=None, repr=False)
    managed_selection: bool = False
    managed_mux: ManagedMuxServiceBindingV1 | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.method is not None and (type(self.method) is not CodingHostedMethodV1
                or self.execution is None or self.execution.select_work_port is None):
            raise ValueError("hosted Method requires its explicit execution capability")
        if self.method is None and self.execution is not None and self.execution.select_work_port is not None:
            raise ValueError("Work capability requires a fixed hosted Method")
        if self.goal is not None and (type(self.goal) is not HostedGoalSetup or self.method is not None
                or self.execution is None or self.execution.select_goal_port is None):
            raise ValueError("hosted Goal requires its exclusive execution capability")
        if self.goal is None and self.execution is not None and self.execution.select_goal_port is not None:
            raise ValueError("Goal capability requires fixed hosted Goal configuration")
        _require_managed_selection(self.managed_selection, self.sessions, self.profile_id, self.admitted_scopes)
        if self.managed_selection and self.session_owner is not self.sessions:
            raise ValueError("managed Session catalog must retain its shutdown owner")
        if self.managed_selection and self.execution is not None:
            from loushang.coding.hosted.execution import _select_coding_execution_port

            if (type(self.execution) is not HostedExecutionServiceBindingV1
                    or self.execution.select_port is not _select_coding_execution_port
                    or self.method is not None or self.goal is not None):
                raise ValueError("managed selection requires the Coding execution adapter")
        if self.managed_mux is not None and (type(self.managed_mux) is not ManagedMuxServiceBindingV1
                                            or not self.managed_selection):
            raise ValueError("managed Mux requires managed Coding selection")
        if self.session_owner is not None:
            _require_async_method(self.session_owner, "close")
            fence = inspect.getattr_static(type(self.session_owner), "fence", None)
            if not callable(fence) or inspect.iscoroutinefunction(fence):
                raise TypeError("invalid Coding Session owner fence")
        require_discovery_context(self.discovery, CODING_PRODUCT_ID, self.generation_id)
        if self.execution is not None and type(self.execution) is not HostedExecutionServiceBindingV1:
            raise TypeError("invalid Coding execution activation")
        require_admitted_scopes(self.admitted_scopes, CODING_PRODUCT_ID)
        if self.discovery is not None and self.discovery.scopes != self.admitted_scopes:
            raise ValueError("discovery and resolver scopes must agree")
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


class CodingForegroundProductFactoryV1(_ForegroundProductFactory[CodingHostedSessionBindingV1]):
    """Create foreground Product Sessions without a Hosting/Worker owner."""

    __slots__ = ()
    _product_id = CODING_PRODUCT_ID
    _product_label = "Coding"

    def __init__(self, factory: CodingForegroundSessionFactoryV1, *, session_owner: CodingHostedSessionOwnerV1 | None = None) -> None:
        super().__init__(factory, session_owner=session_owner)


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
        from loushang.coding.hosted.session import CodingRealHostedSessionV1

        if type(binding) is CodingRealHostedSessionV1 and binding.execution_claimed:
            raise RuntimeError("Coding Session already has an execution owner")
        return _BorrowedProfileLease(
            self._profile_id,
            cast(CodingHostedSessionBindingV1, binding),
        )


class _LeasedCodingHostedBinding(
    _LeasedForegroundBindingMethods[
        CodingHostedSnapshotProjectionV1, CodingHostedEventProjectionV1
    ]
):
    """Give AppService exact profile-detach and binding-close authority."""

    __slots__ = (
        "_binding",
        "_close_lock",
        "_close_task",
        "_lease",
        "_lease_closed",
        "_runtime",
        "_runtime_closed",
        "_identity",
        "_execution_projection",
    )

    def __init__(
        self,
        *,
        runtime: AppHostRuntimeV1,
        lease: AppHostSessionLeaseV1,
        binding: CodingHostedSessionBindingV1,
        identity: SessionIdentityV1 | None = None,
    ) -> None:
        super().__init__(runtime=runtime, lease=lease, binding=binding, identity=identity)
        self._execution_projection: tuple[object, ...] | None = None


class CodingAppHostHostedSessionResolverV1:
    """Resolve G11 Session requests exclusively through canonical AppHost routes."""

    __slots__ = ("_operation_id", "_profile_id", "_runtime", "_sessions", "_scopes", "_execution", "_managed_selection", "_method", "_method_used", "_goal")

    def __init__(
        self,
        *,
        runtime: AppHostRuntimeV1,
        sessions: SessionIdentityCatalogPortV1,
        profile_id: str,
        operation_id_factory: Callable[[], str],
        admitted_scopes: tuple[HostedSessionDiscoveryScopeV1, ...] | None = None,
        execution: bool = False,
        method: CodingHostedMethodV1 | None = None,
        goal: HostedGoalSetup | None = None,
        managed_selection: bool = False,
    ) -> None:
        if type(runtime) is not AppHostRuntimeV1:
            raise TypeError("Coding hosted resolver AppHost Runtime is invalid")
        if not callable(operation_id_factory):
            raise TypeError("Coding hosted resolver operation factory is invalid")
        require_admitted_scopes(admitted_scopes, CODING_PRODUCT_ID)
        _require_managed_selection(managed_selection, sessions, profile_id, admitted_scopes)
        self._managed_selection = managed_selection
        if type(execution) is not bool:
            raise TypeError("invalid Coding execution activation")
        if method is not None and (type(method) is not CodingHostedMethodV1 or not execution):
            raise ValueError("invalid hosted Method resolver configuration")
        self._goal = goal
        self._method = method
        self._method_used = False
        self._execution = execution
        self._runtime = runtime
        self._sessions = sessions
        self._profile_id = profile_id
        self._operation_id = operation_id_factory
        self._scopes = admitted_scopes

    def admits(self, request: SessionOpenSpecV1) -> bool:
        from loushang.coding.hosted.workspace_catalog import CodingWorkspaceCatalog

        scope = HostedSessionDiscoveryScopeV1(
            request.product_id, request.scope, request.scope_fingerprint,
        )
        if type(self._sessions) is CodingWorkspaceCatalog:
            return self._sessions.admits(scope)
        return self._scopes is None or scope in self._scopes

    async def open_session(self, request: SessionOpenSpecV1) -> HostedSessionPortV1:
        if type(request) is not SessionOpenSpecV1 or request.product_id != (
            CODING_PRODUCT_ID
        ):
            raise ValueError("Coding hosted open request is invalid")
        if not self.admits(request):
            raise HostedSessionResolutionErrorV1(HostedSessionResolutionFailureV1.UNAVAILABLE)
        if self._method is not None or self._goal is not None:
            if request.session_id is not None or self._method_used:
                raise HostedSessionResolutionErrorV1(HostedSessionResolutionFailureV1.UNAVAILABLE)
            self._method_used = True
        try:
            from loushang.coding.hosted.workspace_catalog import CodingWorkspaceCatalog

            sessions = self._sessions
            lease = await attach_canonical_foreground_session(
                self._runtime,
                request,
                sessions=sessions,
                workspace_catalog=sessions if type(sessions) is CodingWorkspaceCatalog else None,
                profile_id=self._profile_id,
                operation_id_factory=self._operation_id,
                limit=CODING_HOSTED_APPLICATION_MAX_CANDIDATES,
                missing_is_authoritative=self._scopes is not None,
                label="Coding",
            )
        except BaseException:
            self._method_used = False
            raise
        from loushang.coding.hosted.session import CodingRealHostedSessionV1

        existing = lease.profile_binding
        if type(existing) is CodingRealHostedSessionV1 and existing.execution_claimed:
            # Detach only this rejected lease; never close the original owner.
            await lease.close()
            raise ValueError("Coding Session already has an execution owner")
        async with bind_foreground_session_lease(
            self._runtime,
            lease,
            request,
            owner_type=_LeasedCodingHostedBinding,
            managed_selection=self._managed_selection,
            after_cleanup=self._reset_method_attempt,
            cleanup_error="coding_foreground_cleanup_incomplete",
            label="Coding",
        ) as wrapper:
            binding = cast(CodingHostedSessionBindingV1, wrapper._binding)
            if self._goal is not None:
                from loushang.coding.hosted.goal import CodingHostedGoalSessionV1

                if type(binding) is not CodingRealHostedSessionV1:
                    raise TypeError("hosted Goal requires a fresh Coding Session")
                return CodingHostedGoalSessionV1(binding, self._goal, owner=wrapper)
            if self._method is not None:
                from loushang.coding.hosted.method import CodingHostedMethodSessionV1

                if type(binding) is not CodingRealHostedSessionV1:
                    raise TypeError("hosted Method requires a fresh Coding Session")
                return CodingHostedMethodSessionV1(binding, self._method, owner=wrapper)
            if self._execution:
                from loushang.coding.hosted.execution import (
                    _admit_execution_projection,
                    create_leased_coding_execution_session,
                )

                if self._managed_selection:
                    _admit_execution_projection(wrapper, self, request)
                return create_leased_coding_execution_session(binding, wrapper)
            return CodingHostedSessionV1(wrapper)

    def _reset_method_attempt(self) -> None:
        self._method_used = False


async def create_coding_foreground_hosted_application(
    request: CodingForegroundHostedApplicationRequestV1,
) -> HostedApplicationRuntimeV1:
    """Compose one explicit Coding/AppHost/AppService foreground application."""

    if type(request) is not CodingForegroundHostedApplicationRequestV1:
        raise TypeError("Coding foreground hosted application request is invalid")
    if request.managed_mux is not None:
        raise ValueError("managed Mux requires Coding application continuity")
    from loushang.coding.hosted.workspace_catalog import CodingWorkspaceCatalog

    if type(request.sessions) is CodingWorkspaceCatalog:
        await request.sessions.load()
    product_factory = CodingForegroundProductFactoryV1(request.session_factory, session_owner=request.session_owner)

    def catalog_input() -> AppHostCatalogInputV1:
        product, profile = _coding_hosted_registrations(request, product_factory)
        return AppHostCatalogInputV1(
            generation_id=request.generation_id,
            products=(product,),
            profiles=(profile,),
        )

    def bind(runtime: AppHostRuntimeV1) -> HostedApplicationRuntimeV1:
        resolver = CodingAppHostHostedSessionResolverV1(
            runtime=runtime,
            sessions=request.sessions,
            profile_id=request.profile_id,
            operation_id_factory=request.operation_id_factory,
            admitted_scopes=request.admitted_scopes,
            execution=request.execution is not None,
            method=request.method,
            goal=request.goal,
            managed_selection=request.managed_selection,
        )
        return create_hosted_application_runtime(
            _coding_hosted_application_request(
                request,
                product_factory=product_factory,
                runtime=runtime,
                resolver=resolver,
            )
        )

    return await _construct_product_apphost(
        catalog_input,
        request.sessions,
        product_factory,
        bind,
        cleanup_failure=RuntimeError("coding_foreground_cleanup_incomplete"),
        join_owned=await_owned_task,
    )


def _coding_hosted_registrations(
    request: CodingForegroundHostedApplicationRequestV1,
    product_factory: CodingForegroundProductFactoryV1,
) -> tuple[ProductRegistrationV1, ProfileRegistrationV1]:
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
    return product, profile


def _coding_hosted_application_request(
    request: CodingForegroundHostedApplicationRequestV1,
    *,
    product_factory: CodingForegroundProductFactoryV1,
    runtime: AppHostRuntimeV1,
    resolver: CodingAppHostHostedSessionResolverV1,
) -> HostedApplicationRequestV1:
    return HostedApplicationRequestV1(
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
        discovery=request.discovery,
        execution=request.execution,
        managed_mux=request.managed_mux,
        workspaces=request.workspaces,
    )


def _validate_hosted_binding(
    binding: object,
    key: SessionBindingKeyV1,
) -> None:
    _validate_foreground_binding(binding, key, label="Coding")


def _require_managed_selection(
    enabled: bool, sessions: object, profile_id: str,
    scopes: tuple[HostedSessionDiscoveryScopeV1, ...] | None,
) -> None:
    if type(enabled) is not bool or (profile_id == CODING_MANAGED_APPLICATION_PROFILE_ID) != enabled:
        raise ValueError("invalid managed selection activation")
    if not enabled:
        return
    from loushang.coding.hosted.managed.catalog import CodingManagedSessionCatalogV1
    from loushang.coding.hosted.workspace_catalog import CodingWorkspaceCatalog

    if type(sessions) is CodingWorkspaceCatalog:
        if scopes is None:
            raise ValueError("workspace selection requires explicit scopes")
        return
    if type(sessions) is not CodingManagedSessionCatalogV1 or scopes != tuple(
        HostedSessionDiscoveryScopeV1("coding", scope.scope, scope.fingerprint) for scope in sessions.scopes
    ):
        raise ValueError("managed selection requires the exact owned canonical catalog and scopes")


def _require_async_method(value: object, name: str) -> None:
    if not inspect.iscoroutinefunction(_method_descriptor(value, name)):
        raise TypeError(f"Coding hosted application {name} port is invalid")


__all__ = [
    "CodingHostedSessionOwnerV1",
    "CODING_HOSTED_APPLICATION_MAX_CANDIDATES",
    "CODING_HOSTED_APPLICATION_PROFILE_ID",
    "CODING_HOSTED_APPLICATION_PROFILE_VERSION",
    "CODING_MANAGED_APPLICATION_PROFILE_ID",
    "CodingAppHostHostedSessionResolverV1",
    "CodingForegroundHostedApplicationRequestV1",
    "CodingForegroundProductFactoryV1",
    "CodingForegroundSessionFactoryV1",
    "CodingHostedProfileFactoryV1",
    "create_coding_foreground_hosted_application",
]
