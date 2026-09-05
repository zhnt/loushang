"""Immutable standard-library contracts for the AppHost A0 boundary."""

from __future__ import annotations

import inspect
import math
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, TypeVar, runtime_checkable

from .errors import (
    AppHostFailureCategory,
    InvalidAppHostContractError,
    InvalidAppHostContractReason,
)

APPHOST_CONTRACT_VERSION = "loushang.apphost/v1"
SESSION_IDENTITY_ENVELOPE_VERSION = "loushang.session-identity/v1"

_MAX_ID_LENGTH = 128
_MAX_OPAQUE_LENGTH = 512
_MAX_REGISTRATIONS = 256
_MAX_PROFILE_IDS_PER_PRODUCT = 64
_STABLE_ID = re.compile(
    rf"[a-z0-9](?:[a-z0-9._-]{{0,{_MAX_ID_LENGTH - 1}}})\Z"
)
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._~-]{0,511})\Z")
_RegistrationT = TypeVar("_RegistrationT")


class SessionDiscoveryScope(str, Enum):
    """Caller-selected discovery authority; it is never resolved to a path here."""

    CURRENT_DIRECTORY = "current_directory"
    USER_GLOBAL_LEGACY = "user_global_legacy"
    USER_GLOBAL_CANONICAL = "user_global_canonical"


class SessionCandidateMode(str, Enum):
    """Whether a projected candidate can resume or requires explicit import."""

    CANONICAL = "canonical"
    MIGRATION_REQUIRED = "migration_required"


class AppHostAdmissionSubjectKind(str, Enum):
    """Closed kind of one Product/OEM-admitted registration subject."""

    PRODUCT = "product"
    PROFILE = "profile"


class AppHostComponent(str, Enum):
    CONTRACT = "contract"
    CATALOG = "catalog"
    ROUTER = "router"
    RUNTIME = "runtime"
    PROFILE = "profile"
    PROCESS = "process"


class AppHostLifecycleTransition(str, Enum):
    VALIDATED = "validated"
    ADMITTED = "admitted"
    PINNED = "pinned"
    OPENING = "opening"
    PUBLISHED = "published"
    FENCED = "fenced"
    DRAINING = "draining"
    CLOSED = "closed"
    FAILED = "failed"


class AppHostShutdownPhase(str, Enum):
    """Closed process-local phases owned by the A0.3 runtime."""

    ADMISSION = "admission"
    BINDINGS = "bindings"
    ROUTER = "router"
    CATALOG = "catalog"


@dataclass(frozen=True, slots=True)
class AdmissionIdentityV1:
    """Concrete immutable identity of one admitted Product/profile subject."""

    generation_id: str
    subject_kind: AppHostAdmissionSubjectKind
    subject_id: str

    def __post_init__(self) -> None:
        _opaque_token("generation_id", self.generation_id)
        _enum("subject_kind", self.subject_kind, AppHostAdmissionSubjectKind)
        _stable_id("subject_id", self.subject_id)


@dataclass(frozen=True, slots=True)
class SessionIdentityEnvelopeV1:
    """Generic bounded routing header persisted by the canonical Session owner."""

    product_id: str
    product_compatibility_id: str
    continuity_id: str
    session_id: str
    provider_id: str
    locator_token: str = field(repr=False)
    version: str = SESSION_IDENTITY_ENVELOPE_VERSION

    def __post_init__(self) -> None:
        _contract_version("version", self.version, SESSION_IDENTITY_ENVELOPE_VERSION)
        _stable_id("product_id", self.product_id)
        _opaque_token("product_compatibility_id", self.product_compatibility_id)
        _opaque_token("continuity_id", self.continuity_id)
        _opaque_token("session_id", self.session_id)
        _stable_id("provider_id", self.provider_id)
        _opaque_token("locator_token", self.locator_token)


@dataclass(frozen=True, slots=True)
class SessionBindingKeyV1:
    """Canonical process-local identity for one future Product Runtime binding."""

    product_id: str
    continuity_id: str
    session_id: str

    def __post_init__(self) -> None:
        _stable_id("product_id", self.product_id)
        _opaque_token("continuity_id", self.continuity_id)
        _opaque_token("session_id", self.session_id)


@dataclass(frozen=True, slots=True)
class SessionCandidateRefV1:
    """Path-free reference to one exact discovery candidate revision."""

    source_id: str
    candidate_id: str
    revision: str

    def __post_init__(self) -> None:
        _stable_id("source_id", self.source_id)
        _opaque_token("candidate_id", self.candidate_id)
        _opaque_token("revision", self.revision)


@dataclass(frozen=True, slots=True)
class SessionIdentityProjectionV1:
    """Bounded list result; migration candidates intentionally omit an envelope."""

    reference: SessionCandidateRefV1
    scope: SessionDiscoveryScope
    mode: SessionCandidateMode
    envelope: SessionIdentityEnvelopeV1 | None

    def __post_init__(self) -> None:
        _instance("reference", self.reference, SessionCandidateRefV1)
        _enum("scope", self.scope, SessionDiscoveryScope)
        _enum("mode", self.mode, SessionCandidateMode)
        if self.mode is SessionCandidateMode.CANONICAL:
            if not isinstance(self.envelope, SessionIdentityEnvelopeV1):
                raise InvalidAppHostContractError(
                    "envelope",
                    InvalidAppHostContractReason.CANONICAL_ENVELOPE_REQUIRED,
                )
        elif self.envelope is not None:
            raise InvalidAppHostContractError(
                "envelope",
                InvalidAppHostContractReason.MIGRATION_ENVELOPE_FORBIDDEN,
            )


@dataclass(frozen=True, slots=True)
class SessionCreateRequestV1:
    """Scoped idempotent request for the Session owner to mint an identity."""

    product_id: str
    creator_scope_id: str
    operation_id: str
    contract_version: str = APPHOST_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract_version("contract_version", self.contract_version, APPHOST_CONTRACT_VERSION)
        _stable_id("product_id", self.product_id)
        _opaque_token("creator_scope_id", self.creator_scope_id)
        _operation_id("operation_id", self.operation_id)


@dataclass(frozen=True, slots=True)
class SessionCreateIntentV1:
    """AppHost-selected compatibility identity for one create-if-absent call."""

    request: SessionCreateRequestV1
    product_compatibility_id: str
    contract_version: str = APPHOST_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract_version("contract_version", self.contract_version, APPHOST_CONTRACT_VERSION)
        _instance("request", self.request, SessionCreateRequestV1)
        _opaque_token("product_compatibility_id", self.product_compatibility_id)


@dataclass(frozen=True, slots=True)
class ProductDescriptorV1:
    """Data-only identity for one admitted Product compatibility boundary."""

    product_id: str
    product_version: str
    compatibility_id: str
    supported_profile_ids: tuple[str, ...]
    contract_version: str = APPHOST_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract_version("contract_version", self.contract_version, APPHOST_CONTRACT_VERSION)
        _stable_id("product_id", self.product_id)
        _opaque("product_version", self.product_version)
        _opaque_token("compatibility_id", self.compatibility_id)
        _stable_id_tuple(
            "supported_profile_ids",
            self.supported_profile_ids,
            maximum=_MAX_PROFILE_IDS_PER_PRODUCT,
            allow_empty=False,
        )


@dataclass(frozen=True, slots=True)
class ProfileDescriptorV1:
    """Data-only identity for one Product-orthogonal delivery profile."""

    profile_id: str
    profile_version: str
    contract_version: str = APPHOST_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract_version("contract_version", self.contract_version, APPHOST_CONTRACT_VERSION)
        _stable_id("profile_id", self.profile_id)
        _opaque("profile_version", self.profile_version)


@runtime_checkable
class PreparedProductRouteV1(Protocol):
    """Read-only prepared identity plus independently owned cleanup."""

    @property
    def descriptor(self) -> ProductDescriptorV1: ...

    @property
    def generation_id(self) -> str: ...

    @property
    def binding_key(self) -> SessionBindingKeyV1: ...

    async def close(self) -> None: ...


@runtime_checkable
class AdmissionGenerationLeaseV1(Protocol):
    """Independently owned, idempotently closed subject-bound admission pin."""

    @property
    def identity(self) -> AdmissionIdentityV1: ...

    async def close(self) -> None: ...


@runtime_checkable
class AdmissionGenerationSourceV1(Protocol):
    """Borrowed admitted subject able to mint an independent catalog pin."""

    async def acquire_pin(self) -> AdmissionGenerationLeaseV1: ...


@runtime_checkable
class ClaimedSessionCandidateV1(Protocol):
    """Independently owned exact candidate claimed after the final fence.

    ``close`` is idempotent.  A Product validator borrows this handle; it never
    consumes or closes it.
    """

    @property
    def reference(self) -> SessionCandidateRefV1: ...

    @property
    def opaque_binding(self) -> object: ...

    async def close(self) -> None: ...


@runtime_checkable
class SessionCandidateLeaseV1(Protocol):
    """Request-bound candidate supporting one final verify and one claim.

    A successful claim returns a separately owned handle and does not consume
    this lease.  The caller closes both handles exactly once, in reverse
    acquisition order, on success, failure, or cancellation.
    """

    @property
    def projection(self) -> SessionIdentityProjectionV1: ...

    async def verify_current(self) -> None: ...

    async def claim(self) -> ClaimedSessionCandidateV1: ...

    async def close(self) -> None: ...


@runtime_checkable
class SessionIdentityCatalogPortV1(Protocol):
    """Injected path-free bounded canonical Session identity/candidate owner.

    ``create_candidate`` is create-if-absent and idempotent by the intent's
    request Product/creator-scope/operation identity. The selected compatibility
    identity is atomically persisted in the envelope; a different intent for
    the same key conflicts. ``find_created_candidate`` is a read-only recovery
    lookup by the original request. A retry after commit-before-return
    cancellation or crash returns the same exact candidate revision and never
    mints a duplicate.
    """

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]: ...

    async def open_candidate(
        self, reference: SessionCandidateRefV1
    ) -> SessionCandidateLeaseV1: ...

    async def find_created_candidate(
        self, request: SessionCreateRequestV1
    ) -> SessionCandidateLeaseV1 | None: ...

    async def create_candidate(
        self, intent: SessionCreateIntentV1
    ) -> SessionCandidateLeaseV1: ...


@runtime_checkable
class OpenedProductCandidateV1(Protocol):
    """Independently owned Product-opened candidate for one factory effect.

    The factory borrows this handle and never consumes or closes it.  ``close``
    is idempotent and remains the caller's responsibility.
    """

    @property
    def binding_key(self) -> SessionBindingKeyV1: ...

    @property
    def opaque_binding(self) -> object: ...

    async def close(self) -> None: ...


@runtime_checkable
class ProductCandidateValidatorV1(Protocol):
    """Product-owned validator/opener for a claimed create or resume candidate."""

    async def open_product_candidate(
        self,
        candidate: ClaimedSessionCandidateV1,
        envelope: SessionIdentityEnvelopeV1,
    ) -> OpenedProductCandidateV1: ...


@runtime_checkable
class ScopedProductRuntimeV1(Protocol):
    """Owned per-Session Product Runtime handle for the A0.3 live registry.

    The returned profile binding is deliberately non-owning and cannot close
    this runtime.  ``close`` is idempotent and is reserved to the registry.
    """

    @property
    def binding_key(self) -> SessionBindingKeyV1: ...

    @property
    def profile_binding(self) -> ProductProfileBindingV1: ...

    async def close(self) -> None: ...


@runtime_checkable
class ProductProfileBindingV1(Protocol):
    """Restricted non-owning Product view supplied to one profile factory."""

    @property
    def binding_key(self) -> SessionBindingKeyV1: ...

    @property
    def opaque_binding(self) -> object: ...


@runtime_checkable
class ProductFactoryV1(Protocol):
    """Admitted Product factory borrowing one opened candidate.

    Success returns a separately owned runtime.  Failure or cancellation
    returns no handle and must settle any unpublished partial resources; it
    never closes the borrowed candidate.
    """

    async def create_runtime(
        self, candidate: OpenedProductCandidateV1
    ) -> ScopedProductRuntimeV1: ...


@runtime_checkable
class ProductCompatibilityImporterV1(Protocol):
    """Product-owned copy-first importer borrowing one claimed candidate."""

    async def import_candidate(
        self, candidate: ClaimedSessionCandidateV1
    ) -> SessionCandidateRefV1: ...


@runtime_checkable
class ProfileLeaseV1(Protocol):
    """Independent profile attachment with a non-owning consumer view."""

    @property
    def profile_id(self) -> str: ...

    @property
    def profile_binding(self) -> object: ...

    async def close(self) -> None: ...


@runtime_checkable
class AppHostSessionLeaseV1(Protocol):
    """One independently owned attachment to a canonical live binding.

    ``profile_binding`` is borrowed and has no Product Runtime close authority.
    Closing this lease settles only its exact profile attachment.  The live
    registry remains the sole owner of the scoped Product Runtime.
    """

    @property
    def descriptor(self) -> ProductDescriptorV1: ...

    @property
    def generation_id(self) -> str: ...

    @property
    def binding_key(self) -> SessionBindingKeyV1: ...

    @property
    def profile_id(self) -> str: ...

    @property
    def profile_binding(self) -> object: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class AppHostShutdownBudgetV1:
    """Finite monotonic budget selected by trusted outer composition."""

    overall_timeout_seconds: float
    phase_timeout_seconds: float
    contract_version: str = APPHOST_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract_version("contract_version", self.contract_version, APPHOST_CONTRACT_VERSION)
        _finite_timeout("overall_timeout_seconds", self.overall_timeout_seconds)
        _finite_timeout("phase_timeout_seconds", self.phase_timeout_seconds)
        if self.phase_timeout_seconds > self.overall_timeout_seconds:
            raise InvalidAppHostContractError(
                "phase_timeout_seconds",
                InvalidAppHostContractReason.TIMEOUT_INVALID,
            )


@dataclass(frozen=True, slots=True)
class AppHostShutdownReportV1:
    """Bounded phase facts; it never promotes one owner's evidence to another."""

    completed: bool
    timed_out_phases: tuple[AppHostShutdownPhase, ...]
    failed_phases: tuple[AppHostShutdownPhase, ...]
    contract_version: str = APPHOST_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract_version("contract_version", self.contract_version, APPHOST_CONTRACT_VERSION)
        if type(self.completed) is not bool:
            raise InvalidAppHostContractError(
                "completed",
                InvalidAppHostContractReason.BOOLEAN_REQUIRED,
            )
        timed_out = _enum_tuple(
            "timed_out_phases",
            self.timed_out_phases,
            AppHostShutdownPhase,
        )
        failed = _enum_tuple(
            "failed_phases",
            self.failed_phases,
            AppHostShutdownPhase,
        )
        if set(timed_out).intersection(failed):
            raise InvalidAppHostContractError(
                "failed_phases",
                InvalidAppHostContractReason.DUPLICATE_ITEM,
            )
        if self.completed != (not timed_out and not failed):
            raise InvalidAppHostContractError(
                "completed",
                InvalidAppHostContractReason.COMPLETION_MISMATCH,
            )


@runtime_checkable
class ProfileFactoryV1(Protocol):
    """Admitted profile binder borrowing a restricted non-owning Product view."""

    async def bind_profile(
        self, runtime: ProductProfileBindingV1
    ) -> ProfileLeaseV1: ...


@dataclass(frozen=True, slots=True)
class ProductRegistrationV1:
    """Admitted Product ports plus concrete identity and borrowed pin source."""

    descriptor: ProductDescriptorV1
    factory: ProductFactoryV1 = field(repr=False)
    candidate_validator: ProductCandidateValidatorV1 = field(repr=False)
    admission_identity: AdmissionIdentityV1
    admission_source: AdmissionGenerationSourceV1 = field(repr=False)
    importer: ProductCompatibilityImporterV1 | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _instance("descriptor", self.descriptor, ProductDescriptorV1)
        _async_port_method("factory", self.factory, "create_runtime")
        _async_port_method(
            "candidate_validator",
            self.candidate_validator,
            "open_product_candidate",
        )
        _async_port_method("admission_source", self.admission_source, "acquire_pin")
        _admission_subject(
            self.admission_identity,
            AppHostAdmissionSubjectKind.PRODUCT,
            self.descriptor.product_id,
        )
        if self.importer is not None:
            _async_port_method("importer", self.importer, "import_candidate")


@dataclass(frozen=True, slots=True)
class ProfileRegistrationV1:
    """Admitted profile port plus concrete identity and borrowed pin source."""

    descriptor: ProfileDescriptorV1
    factory: ProfileFactoryV1 = field(repr=False)
    admission_identity: AdmissionIdentityV1
    admission_source: AdmissionGenerationSourceV1 = field(repr=False)

    def __post_init__(self) -> None:
        _instance("descriptor", self.descriptor, ProfileDescriptorV1)
        _async_port_method("factory", self.factory, "bind_profile")
        _async_port_method("admission_source", self.admission_source, "acquire_pin")
        _admission_subject(
            self.admission_identity,
            AppHostAdmissionSubjectKind.PROFILE,
            self.descriptor.profile_id,
        )


@dataclass(frozen=True, slots=True)
class AppHostCatalogInputV1:
    """Validated immutable generation input; not a live registry or router."""

    generation_id: str
    products: tuple[ProductRegistrationV1, ...]
    profiles: tuple[ProfileRegistrationV1, ...]
    contract_version: str = APPHOST_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _contract_version("contract_version", self.contract_version, APPHOST_CONTRACT_VERSION)
        _opaque_token("generation_id", self.generation_id)
        products = _registration_tuple(
            "products", self.products, ProductRegistrationV1
        )
        profiles = _registration_tuple(
            "profiles", self.profiles, ProfileRegistrationV1
        )
        _unique(
            "products",
            tuple(product.descriptor.product_id for product in products),
        )
        _unique(
            "profiles",
            tuple(profile.descriptor.profile_id for profile in profiles),
        )
        for product in products:
            _admission_generation(product.admission_identity, self.generation_id)
        for profile in profiles:
            _admission_generation(profile.admission_identity, self.generation_id)
        admitted_profiles = {
            profile.descriptor.profile_id for profile in profiles
        }
        for product in products:
            missing = set(product.descriptor.supported_profile_ids) - admitted_profiles
            if missing:
                raise InvalidAppHostContractError(
                    "supported_profile_ids",
                    InvalidAppHostContractReason.PROFILE_REFERENCE_MISSING,
                )


@dataclass(frozen=True, slots=True)
class AppHostObservationV1:
    """Bounded owner fact without payload, path, environment, or authority claims."""

    component: AppHostComponent
    transition: AppHostLifecycleTransition
    generation_id: str
    product_id: str | None = None
    profile_id: str | None = None
    session_id: str | None = None
    failure: AppHostFailureCategory | None = None

    def __post_init__(self) -> None:
        _enum("component", self.component, AppHostComponent)
        _enum("transition", self.transition, AppHostLifecycleTransition)
        _opaque_token("generation_id", self.generation_id)
        _optional_stable_id("product_id", self.product_id)
        _optional_stable_id("profile_id", self.profile_id)
        _optional_opaque_token("session_id", self.session_id)
        if self.transition is AppHostLifecycleTransition.FAILED:
            if not isinstance(self.failure, AppHostFailureCategory):
                raise InvalidAppHostContractError(
                    "failure",
                    InvalidAppHostContractReason.FAILURE_CATEGORY_REQUIRED,
                )
        elif self.failure is not None:
            raise InvalidAppHostContractError(
                "failure",
                InvalidAppHostContractReason.FAILURE_CATEGORY_UNEXPECTED,
            )


@runtime_checkable
class AppHostObservationSinkV1(Protocol):
    """Non-owning sink; it cannot control lifecycle or supply routing data."""

    def observe(self, observation: AppHostObservationV1) -> None: ...


def _contract_version(field_name: str, value: object, expected: str) -> None:
    if value != expected:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.CONTRACT_VERSION_MISMATCH,
        )


def _admission_generation(identity: AdmissionIdentityV1, generation_id: str) -> None:
    _instance("admission_identity", identity, AdmissionIdentityV1)
    if identity.generation_id != generation_id:
        raise InvalidAppHostContractError(
            "admission.generation_id",
            InvalidAppHostContractReason.ADMISSION_GENERATION_MISMATCH,
        )


def _admission_subject(
    identity: AdmissionIdentityV1,
    expected_kind: AppHostAdmissionSubjectKind,
    expected_id: str,
) -> None:
    _instance("admission_identity", identity, AdmissionIdentityV1)
    if identity.subject_kind is not expected_kind or identity.subject_id != expected_id:
        raise InvalidAppHostContractError(
            "admission.subject",
            InvalidAppHostContractReason.ADMISSION_SUBJECT_MISMATCH,
        )


def _stable_id(field_name: str, value: object) -> None:
    if not isinstance(value, str) or _STABLE_ID.fullmatch(value) is None:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.STABLE_ID_REQUIRED,
        )


def _optional_stable_id(field_name: str, value: object) -> None:
    if value is not None:
        _stable_id(field_name, value)


def _opaque(field_name: str, value: object) -> None:
    if not isinstance(value, str) or not value or len(value) > _MAX_OPAQUE_LENGTH:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.BOUNDED_TEXT_REQUIRED,
        )
    if any(
        (category := unicodedata.category(character)).startswith("C")
        or category in {"Zl", "Zp"}
        for character in value
    ):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.CONTROL_CHARACTER_FORBIDDEN,
        )


def _opaque_token(field_name: str, value: object) -> None:
    if not isinstance(value, str) or _OPAQUE_TOKEN.fullmatch(value) is None:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.OPAQUE_TOKEN_REQUIRED,
        )


def _optional_opaque_token(field_name: str, value: object) -> None:
    if value is not None:
        _opaque_token(field_name, value)


def _finite_timeout(field_name: str, value: object) -> None:
    if type(value) not in {int, float}:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.TIMEOUT_INVALID,
        )
    assert isinstance(value, (int, float))
    timeout = float(value)
    if not math.isfinite(timeout) or not 0.001 <= timeout <= 300.0:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.TIMEOUT_INVALID,
        )


def _enum_tuple(
    field_name: str,
    value: object,
    expected: type[Enum],
) -> tuple[Enum, ...]:
    if not isinstance(value, tuple):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.IMMUTABLE_TUPLE_REQUIRED,
        )
    if len(value) > len(expected):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.ITEM_COUNT_INVALID,
        )
    for item in value:
        _enum(field_name, item, expected)
    if len(value) != len(set(value)):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.DUPLICATE_ITEM,
        )
    return value


def _enum(field_name: str, value: object, expected: type[Enum]) -> None:
    if not isinstance(value, expected):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.ENUM_VALUE_REQUIRED,
        )


def _instance(field_name: str, value: object, expected: type[object]) -> None:
    if not isinstance(value, expected):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.INSTANCE_REQUIRED,
        )


def _async_port_method(field_name: str, value: object, method_name: str) -> None:
    getattribute = inspect.getattr_static(
        type(value), "__getattribute__", object.__getattribute__
    )
    if getattribute is not object.__getattribute__:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.NATIVE_ASYNC_METHOD_REQUIRED,
        )
    method = inspect.getattr_static(value, method_name, None)
    if isinstance(method, (classmethod, staticmethod)):
        method = method.__func__
    if not inspect.iscoroutinefunction(method):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.NATIVE_ASYNC_METHOD_REQUIRED,
        )


def _operation_id(field_name: str, value: object) -> None:
    _opaque_token(field_name, value)
    assert isinstance(value, str)
    if len(value) < 22:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.OPAQUE_TOKEN_REQUIRED,
        )


def _stable_id_tuple(
    field_name: str,
    value: object,
    *,
    maximum: int,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.IMMUTABLE_TUPLE_REQUIRED,
        )
    if (not allow_empty and not value) or len(value) > maximum:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.ITEM_COUNT_INVALID,
        )
    for item in value:
        _stable_id(field_name, item)
    _unique(field_name, value)
    return value


def _registration_tuple(
    field_name: str,
    value: object,
    expected: type[_RegistrationT],
) -> tuple[_RegistrationT, ...]:
    if not isinstance(value, tuple):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.IMMUTABLE_TUPLE_REQUIRED,
        )
    if not value or len(value) > _MAX_REGISTRATIONS:
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.ITEM_COUNT_INVALID,
        )
    for item in value:
        _instance(field_name, item, expected)
    return value


def _unique(field_name: str, values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise InvalidAppHostContractError(
            field_name,
            InvalidAppHostContractReason.DUPLICATE_ITEM,
        )
