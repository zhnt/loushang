from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from loushang.apphost import (
    APPHOST_CONTRACT_VERSION,
    AdmissionGenerationSourceV1,
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostCatalogInputV1,
    AppHostComponent,
    AppHostError,
    AppHostFailureCategory,
    AppHostLifecycleTransition,
    AppHostObservationV1,
    AppHostShutdownBudgetV1,
    AppHostShutdownPhase,
    AppHostShutdownReportV1,
    InvalidAppHostContractError,
    InvalidAppHostContractReason,
    ProductDescriptorV1,
    ProductRegistrationV1,
    ProfileDescriptorV1,
    ProfileRegistrationV1,
    SessionBindingKeyV1,
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)


class _AdmissionLease:
    def __init__(self, identity: AdmissionIdentityV1) -> None:
        self._identity = identity
        self.closed = 0

    @property
    def identity(self) -> AdmissionIdentityV1:
        return self._identity

    async def close(self) -> None:
        self.closed += 1


class _AdmissionSource:
    def __init__(self, identity: AdmissionIdentityV1) -> None:
        self._identity = identity
        self.acquire_calls = 0

    async def acquire_pin(self) -> _AdmissionLease:
        self.acquire_calls += 1
        return _AdmissionLease(self._identity)


class _Factory:
    def __init__(self) -> None:
        self.calls = 0

    async def create_runtime(self, candidate: object) -> Any:
        self.calls += 1
        raise AssertionError("A0.1 must not invoke Product factories")


class _Validator:
    def __init__(self) -> None:
        self.calls = 0

    async def open_product_candidate(
        self, candidate: object, envelope: SessionIdentityEnvelopeV1
    ) -> Any:
        self.calls += 1
        raise AssertionError("A0.1 must not invoke Product validators")


class _Importer:
    def __init__(self) -> None:
        self.calls = 0

    async def import_candidate(self, candidate: object) -> SessionCandidateRefV1:
        self.calls += 1
        raise AssertionError("A0.1 must not invoke Product importers")


class _ProfileFactory:
    def __init__(self) -> None:
        self.calls = 0

    async def bind_profile(self, runtime: object) -> Any:
        self.calls += 1
        raise AssertionError("A0.1 must not invoke profile factories")


class _NonCallableFactory:
    create_runtime = 42


class _SyncFactory:
    def create_runtime(self, candidate: object) -> object:
        return candidate


class _SyncValidator:
    def open_product_candidate(
        self, candidate: object, envelope: SessionIdentityEnvelopeV1
    ) -> object:
        return candidate


class _SyncImporter:
    def import_candidate(self, candidate: object) -> object:
        return candidate


class _SyncProfileFactory:
    def bind_profile(self, runtime: object) -> object:
        return runtime


class _SyncAdmissionSource:
    def acquire_pin(self) -> object:
        return object()


class _PropertyAdmissionSource:
    def __init__(self) -> None:
        self.property_reads = 0

    @property
    def acquire_pin(self) -> object:
        self.property_reads += 1

        async def _acquire() -> object:
            return object()

        return _acquire


class _DynamicAdmissionSource:
    def __init__(self) -> None:
        self.dynamic_reads = 0

    def __getattribute__(self, name: str) -> object:
        if name == "acquire_pin":
            object.__setattr__(
                self,
                "dynamic_reads",
                object.__getattribute__(self, "dynamic_reads") + 1,
            )

            return 42
        return object.__getattribute__(self, name)

    async def acquire_pin(self) -> object:
        return object()


def _profile(
    *, generation_id: str = "generation-1", profile_id: str = "embedded-tui"
) -> tuple[ProfileRegistrationV1, _ProfileFactory, _AdmissionSource]:
    factory = _ProfileFactory()
    admission_identity = AdmissionIdentityV1(
        generation_id=generation_id,
        subject_kind=AppHostAdmissionSubjectKind.PROFILE,
        subject_id=profile_id,
    )
    admission = _AdmissionSource(admission_identity)
    registration = ProfileRegistrationV1(
        descriptor=ProfileDescriptorV1(
            profile_id=profile_id,
            profile_version="1.0.0",
        ),
        factory=factory,
        admission_identity=admission_identity,
        admission_source=admission,
    )
    return registration, factory, admission


def _product(
    *,
    generation_id: str = "generation-1",
    product_id: str = "coding",
    profile_ids: tuple[str, ...] = ("embedded-tui",),
) -> tuple[
    ProductRegistrationV1,
    _Factory,
    _Validator,
    _Importer,
    _AdmissionSource,
]:
    factory = _Factory()
    validator = _Validator()
    importer = _Importer()
    admission_identity = AdmissionIdentityV1(
        generation_id=generation_id,
        subject_kind=AppHostAdmissionSubjectKind.PRODUCT,
        subject_id=product_id,
    )
    admission = _AdmissionSource(admission_identity)
    registration = ProductRegistrationV1(
        descriptor=ProductDescriptorV1(
            product_id=product_id,
            product_version="1.0.0",
            compatibility_id=f"{product_id}-session-v1",
            supported_profile_ids=profile_ids,
        ),
        factory=factory,
        candidate_validator=validator,
        admission_identity=admission_identity,
        importer=importer,
        admission_source=admission,
    )
    return registration, factory, validator, importer, admission


def test_a0_values_are_frozen_and_validate_exact_contract_versions() -> None:
    descriptor = ProductDescriptorV1(
        product_id="coding",
        product_version="1.0.0",
        compatibility_id="coding-session-v1",
        supported_profile_ids=("embedded-tui",),
    )

    with pytest.raises(FrozenInstanceError):
        descriptor.product_id = "ppt"  # type: ignore[misc]
    with pytest.raises(InvalidAppHostContractError) as error:
        ProductDescriptorV1(
            product_id="coding",
            product_version="1.0.0",
            compatibility_id="coding-session-v1",
            supported_profile_ids=("embedded-tui",),
            contract_version="loushang.apphost/v2",
        )
    assert error.value.category is AppHostFailureCategory.INVALID_CONTRACT
    assert error.value.field == "contract_version"
    assert APPHOST_CONTRACT_VERSION == "loushang.apphost/v1"


@pytest.mark.parametrize(
    "product_id",
    ("", "Coding", "coding product", "coding/../../other", "-coding", "a" * 129),
)
def test_product_identity_is_bounded_and_canonical(product_id: str) -> None:
    with pytest.raises(InvalidAppHostContractError) as error:
        ProductDescriptorV1(
            product_id=product_id,
            product_version="1.0.0",
            compatibility_id="coding-session-v1",
            supported_profile_ids=("embedded-tui",),
        )
    assert error.value.field == "product_id"


def test_opaque_values_are_bounded_and_reject_unicode_controls() -> None:
    descriptor = ProductDescriptorV1(
        product_id="coding",
        product_version="v" * 512,
        compatibility_id="coding-session-v1",
        supported_profile_ids=("embedded-tui",),
    )
    assert len(descriptor.product_version) == 512

    with pytest.raises(InvalidAppHostContractError):
        ProductDescriptorV1(
            product_id="coding",
            product_version="v" * 513,
            compatibility_id="coding-session-v1",
            supported_profile_ids=("embedded-tui",),
        )
    with pytest.raises(InvalidAppHostContractError):
        ProductDescriptorV1(
            product_id="coding",
            product_version="safe\u202eevil",
            compatibility_id="coding-session-v1",
            supported_profile_ids=("embedded-tui",),
        )
    with pytest.raises(InvalidAppHostContractError):
        SessionBindingKeyV1(
            product_id="coding",
            continuity_id="continuity\u0085hidden",
            session_id="session-1",
        )
    with pytest.raises(InvalidAppHostContractError):
        SessionCandidateRefV1(
            source_id="cwd-canonical",
            candidate_id="../../session.json",
            revision="revision-1",
        )


def test_product_profile_ids_have_exact_uniqueness_and_count_bounds() -> None:
    maximum = tuple(f"profile-{index}" for index in range(64))
    descriptor = ProductDescriptorV1(
        product_id="coding",
        product_version="1",
        compatibility_id="coding-session-v1",
        supported_profile_ids=maximum,
    )
    assert len(descriptor.supported_profile_ids) == 64

    for invalid in ((), ("embedded-tui", "embedded-tui"), (*maximum, "overflow")):
        with pytest.raises(InvalidAppHostContractError):
            ProductDescriptorV1(
                product_id="coding",
                product_version="1",
                compatibility_id="coding-session-v1",
                supported_profile_ids=invalid,
            )


def test_envelope_and_projection_preserve_product_before_parser_routing() -> None:
    envelope = SessionIdentityEnvelopeV1(
        product_id="coding",
        product_compatibility_id="coding-session-v1",
        continuity_id="continuity-42",
        session_id="session-42",
        provider_id="canonical-session-store",
        locator_token="opaque-locator-42",
    )
    reference = SessionCandidateRefV1(
        source_id="cwd-canonical",
        candidate_id="candidate-42",
        revision="sha256-abc",
    )

    projection = SessionIdentityProjectionV1(
        reference=reference,
        scope=SessionDiscoveryScope.CURRENT_DIRECTORY,
        mode=SessionCandidateMode.CANONICAL,
        envelope=envelope,
    )

    assert projection.envelope is envelope
    assert projection.envelope.product_id == "coding"
    assert "opaque-locator-42" not in repr(envelope)


def test_create_request_requires_explicit_product_and_operation_identity() -> None:
    request = SessionCreateRequestV1(
        product_id="coding",
        creator_scope_id="local-user-01",
        operation_id="01K4J8F3N3J7M9Q2R6T5V8W0XY",
    )

    assert request.product_id == "coding"
    with pytest.raises(InvalidAppHostContractError):
        SessionCreateRequestV1(
            product_id="",
            creator_scope_id="local-user-01",
            operation_id="01K4J8F3N3J7M9Q2R6T5V8W0XY",
        )
    with pytest.raises(InvalidAppHostContractError):
        SessionCreateRequestV1(
            product_id="coding",
            creator_scope_id="local-user-01",
            operation_id="short",
        )

    other_scope = SessionCreateRequestV1(
        product_id="coding",
        creator_scope_id="tenant-02",
        operation_id=request.operation_id,
    )
    assert other_scope != request
    intent = SessionCreateIntentV1(
        request=request,
        product_compatibility_id="coding-session-v1",
    )
    assert intent.request is request


def test_create_request_accepts_optional_hosted_continuity_and_scope() -> None:
    request = SessionCreateRequestV1(
        product_id="coding",
        creator_scope_id="scope-fingerprint",
        operation_id="01K4J8F3N3J7M9Q2R6T5V8W0XY",
        requested_continuity_id="continuity-hosted",
        requested_scope=SessionDiscoveryScope.CURRENT_DIRECTORY,
    )

    assert request.requested_continuity_id == "continuity-hosted"
    assert request.requested_scope is SessionDiscoveryScope.CURRENT_DIRECTORY
    with pytest.raises(InvalidAppHostContractError):
        SessionCreateRequestV1(
            product_id="coding",
            creator_scope_id="scope-fingerprint",
            operation_id="01K4J8F3N3J7M9Q2R6T5V8W0XY",
            requested_continuity_id="bad continuity",
        )
    with pytest.raises(InvalidAppHostContractError):
        SessionCreateRequestV1(
            product_id="coding",
            creator_scope_id="scope-fingerprint",
            operation_id="01K4J8F3N3J7M9Q2R6T5V8W0XY",
            requested_scope="cwd",  # type: ignore[arg-type]
        )


def test_migration_candidate_cannot_imply_or_omit_product_identity_incorrectly() -> None:
    reference = SessionCandidateRefV1(
        source_id="home-legacy",
        candidate_id="candidate-legacy",
        revision="revision-1",
    )
    envelope = SessionIdentityEnvelopeV1(
        product_id="coding",
        product_compatibility_id="coding-session-v1",
        continuity_id="continuity-legacy",
        session_id="session-legacy",
        provider_id="legacy-store",
        locator_token="opaque-legacy",
    )

    with pytest.raises(InvalidAppHostContractError):
        SessionIdentityProjectionV1(
            reference=reference,
            scope=SessionDiscoveryScope.USER_GLOBAL_LEGACY,
            mode=SessionCandidateMode.MIGRATION_REQUIRED,
            envelope=envelope,
        )
    with pytest.raises(InvalidAppHostContractError):
        SessionIdentityProjectionV1(
            reference=reference,
            scope=SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
            mode=SessionCandidateMode.CANONICAL,
            envelope=None,
        )


def test_catalog_input_accepts_two_products_without_effect_bearing_port_calls() -> None:
    profile, profile_factory, profile_admission = _profile()
    coding, coding_factory, coding_validator, coding_importer, coding_admission = (
        _product(product_id="coding")
    )
    ppt, ppt_factory, ppt_validator, ppt_importer, ppt_admission = _product(
        product_id="ppt"
    )

    catalog = AppHostCatalogInputV1(
        generation_id="generation-1",
        products=(coding, ppt),
        profiles=(profile,),
    )

    assert tuple(item.descriptor.product_id for item in catalog.products) == (
        "coding",
        "ppt",
    )
    assert isinstance(coding_admission, AdmissionGenerationSourceV1)
    assert all(
        owner.calls == 0
        for owner in (
            coding_factory,
            coding_validator,
            coding_importer,
            ppt_factory,
            ppt_validator,
            ppt_importer,
            profile_factory,
        )
    )
    assert coding_admission.acquire_calls == 0
    assert ppt_admission.acquire_calls == 0
    assert profile_admission.acquire_calls == 0


def test_catalog_input_requires_exact_immutable_registration_tuples() -> None:
    profile, _, _ = _profile()
    product, *_ = _product()

    with pytest.raises(InvalidAppHostContractError) as error:
        AppHostCatalogInputV1(
            generation_id="generation-1",
            products=[product],  # type: ignore[arg-type]
            profiles=(profile,),
        )
    assert error.value.field == "products"

    with pytest.raises(InvalidAppHostContractError):
        AppHostCatalogInputV1(
            generation_id="generation-1",
            products=(),
            profiles=(profile,),
        )
    with pytest.raises(InvalidAppHostContractError):
        AppHostCatalogInputV1(
            generation_id="generation-1",
            products=(product,),
            profiles=(),
        )


def test_catalog_registration_count_is_bounded_at_256() -> None:
    profile, _, _ = _profile()
    products = tuple(
        _product(product_id=f"product-{index}")[0] for index in range(257)
    )

    catalog = AppHostCatalogInputV1(
        generation_id="generation-1",
        products=products[:256],
        profiles=(profile,),
    )
    assert len(catalog.products) == 256
    with pytest.raises(InvalidAppHostContractError) as error:
        AppHostCatalogInputV1(
            generation_id="generation-1",
            products=products,
            profiles=(profile,),
        )
    assert error.value.field == "products"


def test_catalog_input_rejects_duplicate_ids_generation_mix_and_missing_profiles() -> None:
    profile, _, _ = _profile()
    product, *_ = _product()
    duplicate, *_ = _product()
    wrong_generation, *_ = _product(generation_id="generation-2")
    missing_profile, *_ = _product(profile_ids=("web-ui",))

    with pytest.raises(InvalidAppHostContractError) as duplicate_error:
        AppHostCatalogInputV1(
            generation_id="generation-1",
            products=(product, duplicate),
            profiles=(profile,),
        )
    assert duplicate_error.value.field == "products"

    with pytest.raises(InvalidAppHostContractError) as generation_error:
        AppHostCatalogInputV1(
            generation_id="generation-1",
            products=(wrong_generation,),
            profiles=(profile,),
        )
    assert generation_error.value.field == "admission.generation_id"

    with pytest.raises(InvalidAppHostContractError) as profile_error:
        AppHostCatalogInputV1(
            generation_id="generation-1",
            products=(missing_profile,),
            profiles=(profile,),
        )
    assert profile_error.value.field == "supported_profile_ids"


def test_registration_rejects_admission_for_another_subject() -> None:
    factory = _Factory()
    validator = _Validator()
    wrong_identity = AdmissionIdentityV1(
        generation_id="generation-1",
        subject_kind=AppHostAdmissionSubjectKind.PRODUCT,
        subject_id="ppt",
    )
    source = _AdmissionSource(wrong_identity)

    with pytest.raises(InvalidAppHostContractError) as error:
        ProductRegistrationV1(
            descriptor=ProductDescriptorV1(
                product_id="coding",
                product_version="1.0.0",
                compatibility_id="coding-session-v1",
                supported_profile_ids=("embedded-tui",),
            ),
            factory=factory,
            candidate_validator=validator,
            admission_identity=wrong_identity,
            admission_source=source,
        )
    assert error.value.field == "admission.subject"


def test_registration_rejects_non_callable_structural_port_member() -> None:
    identity = AdmissionIdentityV1(
        generation_id="generation-1",
        subject_kind=AppHostAdmissionSubjectKind.PRODUCT,
        subject_id="coding",
    )
    admission = _AdmissionSource(identity)

    with pytest.raises(InvalidAppHostContractError) as error:
        ProductRegistrationV1(
            descriptor=ProductDescriptorV1(
                product_id="coding",
                product_version="1.0.0",
                compatibility_id="coding-session-v1",
                supported_profile_ids=("embedded-tui",),
            ),
            factory=_NonCallableFactory(),  # type: ignore[arg-type]
            candidate_validator=_Validator(),
            admission_identity=identity,
            admission_source=admission,
        )
    assert error.value.field == "factory"


def test_registrations_reject_sync_implementations_of_async_ports() -> None:
    product_identity = AdmissionIdentityV1(
        generation_id="generation-1",
        subject_kind=AppHostAdmissionSubjectKind.PRODUCT,
        subject_id="coding",
    )
    profile_identity = AdmissionIdentityV1(
        generation_id="generation-1",
        subject_kind=AppHostAdmissionSubjectKind.PROFILE,
        subject_id="embedded-tui",
    )
    descriptor = ProductDescriptorV1(
        product_id="coding",
        product_version="1.0.0",
        compatibility_id="coding-session-v1",
        supported_profile_ids=("embedded-tui",),
    )
    valid_source = _AdmissionSource(product_identity)
    cases = (
        ("factory", _SyncFactory(), _Validator(), None, valid_source),
        ("candidate_validator", _Factory(), _SyncValidator(), None, valid_source),
        ("importer", _Factory(), _Validator(), _SyncImporter(), valid_source),
        (
            "admission_source",
            _Factory(),
            _Validator(),
            None,
            _SyncAdmissionSource(),
        ),
    )
    for field, factory, validator, importer, source in cases:
        with pytest.raises(InvalidAppHostContractError) as error:
            ProductRegistrationV1(
                descriptor=descriptor,
                factory=factory,  # type: ignore[arg-type]
                candidate_validator=validator,  # type: ignore[arg-type]
                admission_identity=product_identity,
                admission_source=source,  # type: ignore[arg-type]
                importer=importer,  # type: ignore[arg-type]
            )
        assert error.value.field == field

    with pytest.raises(InvalidAppHostContractError) as profile_error:
        ProfileRegistrationV1(
            descriptor=ProfileDescriptorV1(
                profile_id="embedded-tui",
                profile_version="1.0.0",
            ),
            factory=_SyncProfileFactory(),  # type: ignore[arg-type]
            admission_identity=profile_identity,
            admission_source=_AdmissionSource(profile_identity),
        )
    assert profile_error.value.field == "factory"


def test_registration_async_check_does_not_invoke_a_property_descriptor() -> None:
    identity = AdmissionIdentityV1(
        generation_id="generation-1",
        subject_kind=AppHostAdmissionSubjectKind.PRODUCT,
        subject_id="coding",
    )
    source = _PropertyAdmissionSource()

    with pytest.raises(InvalidAppHostContractError) as error:
        ProductRegistrationV1(
            descriptor=ProductDescriptorV1(
                product_id="coding",
                product_version="1.0.0",
                compatibility_id="coding-session-v1",
                supported_profile_ids=("embedded-tui",),
            ),
            factory=_Factory(),
            candidate_validator=_Validator(),
            admission_identity=identity,
            admission_source=source,  # type: ignore[arg-type]
        )
    assert error.value.field == "admission_source"
    assert source.property_reads == 0


def test_registration_rejects_an_instance_shadowing_an_async_port() -> None:
    identity = AdmissionIdentityV1(
        generation_id="generation-1",
        subject_kind=AppHostAdmissionSubjectKind.PRODUCT,
        subject_id="coding",
    )
    source = _AdmissionSource(identity)
    source.acquire_pin = 42  # type: ignore[assignment,method-assign]

    with pytest.raises(InvalidAppHostContractError) as error:
        ProductRegistrationV1(
            descriptor=ProductDescriptorV1(
                product_id="coding",
                product_version="1.0.0",
                compatibility_id="coding-session-v1",
                supported_profile_ids=("embedded-tui",),
            ),
            factory=_Factory(),
            candidate_validator=_Validator(),
            admission_identity=identity,
            admission_source=source,
        )
    assert error.value.field == "admission_source"


def test_registration_async_check_does_not_invoke_dynamic_dispatch() -> None:
    identity = AdmissionIdentityV1(
        generation_id="generation-1",
        subject_kind=AppHostAdmissionSubjectKind.PRODUCT,
        subject_id="coding",
    )
    source = _DynamicAdmissionSource()

    with pytest.raises(InvalidAppHostContractError) as error:
        ProductRegistrationV1(
            descriptor=ProductDescriptorV1(
                product_id="coding",
                product_version="1.0.0",
                compatibility_id="coding-session-v1",
                supported_profile_ids=("embedded-tui",),
            ),
            factory=_Factory(),
            candidate_validator=_Validator(),
            admission_identity=identity,
            admission_source=source,  # type: ignore[arg-type]
        )
    assert error.value.field == "admission_source"
    assert source.dynamic_reads == 0


def test_observation_failure_is_closed_and_payload_free() -> None:
    observation = AppHostObservationV1(
        component=AppHostComponent.CONTRACT,
        transition=AppHostLifecycleTransition.FAILED,
        generation_id="generation-1",
        product_id="coding",
        failure=AppHostFailureCategory.INVALID_CONTRACT,
    )

    assert observation.failure is AppHostFailureCategory.INVALID_CONTRACT
    assert not hasattr(observation, "payload")
    assert not hasattr(observation, "details")
    assert not hasattr(observation, "path")

    with pytest.raises(InvalidAppHostContractError):
        AppHostObservationV1(
            component=AppHostComponent.CONTRACT,
            transition=AppHostLifecycleTransition.FAILED,
            generation_id="generation-1",
        )
    with pytest.raises(InvalidAppHostContractError):
        AppHostObservationV1(
            component=AppHostComponent.CONTRACT,
            transition=AppHostLifecycleTransition.VALIDATED,
            generation_id="generation-1",
            failure=AppHostFailureCategory.INVALID_CONTRACT,
        )


def test_failure_text_and_invalid_reason_are_bounded_and_closed() -> None:
    with pytest.raises(TypeError):
        AppHostError(
            AppHostFailureCategory.RUNTIME_UNAVAILABLE,
            "secret api_key sk_live_ABC123",  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        InvalidAppHostContractError(
            "product_id",
            "arbitrary reason",  # type: ignore[arg-type]
        )

    error = InvalidAppHostContractError(
        "product_id",
        InvalidAppHostContractReason.STABLE_ID_REQUIRED,
    )
    assert error.reason is InvalidAppHostContractReason.STABLE_ID_REQUIRED
    base = AppHostError(AppHostFailureCategory.RUNTIME_UNAVAILABLE)
    assert str(base) == "runtime_unavailable"


def test_shutdown_budget_and_report_are_finite_closed_values() -> None:
    budget = AppHostShutdownBudgetV1(10.0, 2.0)
    assert budget.overall_timeout_seconds == 10.0
    report = AppHostShutdownReportV1(True, (), ())
    assert report.completed is True

    for overall, phase in (
        (float("nan"), 1.0),
        (1.0, float("inf")),
        (0.0, 0.001),
        (1.0, 2.0),
    ):
        with pytest.raises(InvalidAppHostContractError) as error:
            AppHostShutdownBudgetV1(overall, phase)
        assert error.value.reason is InvalidAppHostContractReason.TIMEOUT_INVALID

    with pytest.raises(InvalidAppHostContractError) as error:
        AppHostShutdownReportV1(
            True,
            (AppHostShutdownPhase.BINDINGS,),
            (),
        )
    assert error.value.reason is InvalidAppHostContractReason.COMPLETION_MISMATCH
    with pytest.raises(InvalidAppHostContractError) as error:
        AppHostShutdownReportV1(
            False,
            (AppHostShutdownPhase.BINDINGS,),
            (AppHostShutdownPhase.BINDINGS,),
        )
    assert error.value.reason is InvalidAppHostContractReason.DUPLICATE_ITEM
