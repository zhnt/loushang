from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

import pytest

from loushang.apphost import (
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostCatalogInputV1,
    AppHostCatalogV1,
    AppHostFailureCategory,
    AppHostRouterV1,
    CleanupIncompleteError,
    GenerationRetiredError,
    PreparedProductRouteV1,
    ProductDescriptorV1,
    ProductIdentityRequiredError,
    ProductIncompatibleError,
    ProductRegistrationV1,
    ProductUnavailableError,
    ProfileDescriptorV1,
    ProfileRegistrationV1,
    SessionBindingKeyV1,
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionCandidateStaleError,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)


class _Pin:
    def __init__(self, identity: AdmissionIdentityV1, events: list[str]) -> None:
        self._identity = identity
        self.events = events
        self.closed = 0

    @property
    def identity(self) -> AdmissionIdentityV1:
        return self._identity

    async def close(self) -> None:
        self.closed += 1
        self.events.append(f"pin.close:{self._identity.subject_id}")


class _Source:
    def __init__(self, identity: AdmissionIdentityV1, events: list[str]) -> None:
        self.identity = identity
        self.events = events
        self.pins: list[_Pin] = []

    async def acquire_pin(self) -> _Pin:
        self.events.append(f"pin.acquire:{self.identity.subject_id}")
        pin = _Pin(self.identity, self.events)
        self.pins.append(pin)
        return pin


class _Factory:
    def __init__(self) -> None:
        self.calls = 0

    async def create_runtime(self, candidate: object) -> Any:
        self.calls += 1
        raise AssertionError("A0.2 router must not invoke Product factories")


class _Opened:
    def __init__(self, key: SessionBindingKeyV1, events: list[str]) -> None:
        self._key = key
        self.events = events
        self.closed = 0
        self.fail_first_close = False

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._key

    @property
    def opaque_binding(self) -> object:
        return self

    async def close(self) -> None:
        self.closed += 1
        self.events.append("opened.close")
        if self.fail_first_close and self.closed == 1:
            raise RuntimeError("secret opened cleanup detail")


class _Validator:
    def __init__(self, kind: str, events: list[str]) -> None:
        self.kind = kind
        self.events = events
        self.calls = 0
        self.cancel = False
        self.fail = False
        self.fail_opened_close = False
        self.opened: list[_Opened] = []
        self.entered: asyncio.Event | None = None
        self.release: asyncio.Event | None = None

    async def open_product_candidate(
        self, candidate: object, envelope: SessionIdentityEnvelopeV1
    ) -> _Opened:
        self.calls += 1
        self.events.append(f"validator:{self.kind}")
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.cancel:
            raise asyncio.CancelledError
        if self.fail:
            raise RuntimeError("secret validator failure")
        assert getattr(candidate, "opaque_binding")["kind"] == self.kind
        opened = _Opened(
            SessionBindingKeyV1(
                envelope.product_id, envelope.continuity_id, envelope.session_id
            ),
            self.events,
        )
        opened.fail_first_close = self.fail_opened_close
        self.opened.append(opened)
        return opened


class _Importer:
    def __init__(self, kind: str, events: list[str]) -> None:
        self.kind = kind
        self.events = events
        self.payloads: list[object] = []
        self.invalid_result = False

    async def import_candidate(self, candidate: object) -> object:
        payload = getattr(candidate, "opaque_binding")
        assert payload["kind"] == self.kind
        self.payloads.append(payload["payload"])
        self.events.append(f"importer:{self.kind}")
        if self.invalid_result:
            return object()
        return SessionCandidateRefV1(
            source_id="canonical-owner",
            candidate_id=f"imported-{self.kind}",
            revision="revision-1",
        )


class _ProfileFactory:
    async def bind_profile(self, runtime: object) -> Any:
        raise AssertionError("profile is outside A0.2")


class _Claimed:
    def __init__(
        self, reference: SessionCandidateRefV1, payload: object, events: list[str]
    ) -> None:
        self._reference = reference
        self._payload = payload
        self.events = events
        self.closed = 0

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference

    @property
    def opaque_binding(self) -> object:
        return self._payload

    async def close(self) -> None:
        self.closed += 1
        self.events.append("claimed.close")


class _Candidate:
    def __init__(
        self,
        projection: SessionIdentityProjectionV1,
        payload: object,
        events: list[str],
        *,
        stale: bool = False,
    ) -> None:
        self._projection = projection
        self.payload = payload
        self.events = events
        self.stale = stale
        self.verify_calls = 0
        self.claim_calls = 0
        self.closed = 0
        self.fail_first_close = False
        self.claimed: list[_Claimed] = []

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._projection

    async def verify_current(self) -> None:
        self.verify_calls += 1
        self.events.append("candidate.verify")
        if self.stale:
            raise SessionCandidateStaleError()

    async def claim(self) -> _Claimed:
        self.claim_calls += 1
        self.events.append("candidate.claim")
        claimed = _Claimed(self._projection.reference, self.payload, self.events)
        self.claimed.append(claimed)
        return claimed

    async def close(self) -> None:
        self.closed += 1
        self.events.append("candidate.close")
        if self.fail_first_close and self.closed == 1:
            raise RuntimeError("secret candidate cleanup failure")


class _Sessions:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.by_reference: dict[SessionCandidateRefV1, _Candidate] = {}
        self.created: dict[tuple[str, str, str], _Candidate] = {}
        self.create_calls = 0
        self.cancel_after_commit = False

    async def list_identities(self, scopes: tuple[object, ...], *, limit: int) -> tuple:
        return ()

    async def open_candidate(self, reference: SessionCandidateRefV1) -> _Candidate:
        self.events.append("sessions.open")
        return self.by_reference[reference]

    async def find_created_candidate(self, request: SessionCreateRequestV1) -> _Candidate | None:
        self.events.append("sessions.find")
        return self.created.get(
            (request.product_id, request.creator_scope_id, request.operation_id)
        )

    async def create_candidate(self, intent: object) -> _Candidate:
        self.create_calls += 1
        self.events.append("sessions.create")
        request = getattr(intent, "request")
        compatibility = getattr(intent, "product_compatibility_id")
        key = (request.product_id, request.creator_scope_id, request.operation_id)
        existing = self.created.get(key)
        if existing is not None:
            if existing.projection.envelope.product_compatibility_id != compatibility:
                raise ProductIncompatibleError()
            return existing
        candidate = _canonical_candidate(
            request.product_id,
            {"kind": request.product_id, "payload": {"new": True}},
            self.events,
            compatibility=compatibility,
            suffix=str(len(self.created) + 1),
        )
        self.created[key] = candidate
        self.by_reference[candidate.projection.reference] = candidate
        if self.cancel_after_commit:
            self.cancel_after_commit = False
            raise asyncio.CancelledError
        return candidate


@dataclass
class _ProductOwners:
    factory: _Factory
    validator: _Validator
    importer: _Importer
    source: _Source


def _catalog_input(
    generation: str,
    events: list[str],
    *,
    product_ids: tuple[str, ...] = ("coding", "slides"),
) -> tuple[AppHostCatalogInputV1, dict[str, _ProductOwners]]:
    profile_id = "embedded-tui"
    profile_identity = AdmissionIdentityV1(
        generation, AppHostAdmissionSubjectKind.PROFILE, profile_id
    )
    profile_source = _Source(profile_identity, events)
    products = []
    owners = {}
    for product_id in product_ids:
        identity = AdmissionIdentityV1(
            generation, AppHostAdmissionSubjectKind.PRODUCT, product_id
        )
        factory = _Factory()
        validator = _Validator(product_id, events)
        importer = _Importer(product_id, events)
        source = _Source(identity, events)
        owners[product_id] = _ProductOwners(factory, validator, importer, source)
        products.append(
            ProductRegistrationV1(
                descriptor=ProductDescriptorV1(
                    product_id,
                    "1",
                    f"{product_id}-session-v1",
                    (profile_id,),
                ),
                factory=factory,
                candidate_validator=validator,
                importer=importer,
                admission_identity=identity,
                admission_source=source,
            )
        )
    return (
        AppHostCatalogInputV1(
            generation,
            tuple(products),
            (
                ProfileRegistrationV1(
                    ProfileDescriptorV1(profile_id, "1"),
                    _ProfileFactory(),
                    profile_identity,
                    profile_source,
                ),
            ),
        ),
        owners,
    )


def _canonical_candidate(
    product_id: str,
    payload: object,
    events: list[str],
    *,
    compatibility: str | None = None,
    suffix: str = "1",
    stale: bool = False,
) -> _Candidate:
    reference = SessionCandidateRefV1(
        "canonical-owner", f"candidate-{product_id}-{suffix}", f"revision-{suffix}"
    )
    envelope = SessionIdentityEnvelopeV1(
        product_id,
        compatibility or f"{product_id}-session-v1",
        f"continuity-{suffix}",
        f"session-{suffix}",
        "canonical-owner",
        f"locator-{suffix}",
    )
    return _Candidate(
        SessionIdentityProjectionV1(
            reference,
            SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
            SessionCandidateMode.CANONICAL,
            envelope,
        ),
        payload,
        events,
        stale=stale,
    )


def _legacy_candidate(kind: str, payload: object, events: list[str]) -> _Candidate:
    reference = SessionCandidateRefV1(
        f"{kind}-legacy", f"candidate-{kind}", "revision-1"
    )
    return _Candidate(
        SessionIdentityProjectionV1(
            reference,
            SessionDiscoveryScope.USER_GLOBAL_LEGACY,
            SessionCandidateMode.MIGRATION_REQUIRED,
            None,
        ),
        {"kind": kind, "payload": payload},
        events,
    )


def _request(product_id: str = "coding", scope: str = "user-1") -> SessionCreateRequestV1:
    return SessionCreateRequestV1(
        product_id,
        scope,
        "01K4J8F3N3J7M9Q2R6T5V8W0XY",
    )


def test_two_unrelated_products_resume_without_factory_or_default() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        router = AppHostRouterV1(catalog, sessions)
        for index, product_id in enumerate(("coding", "slides"), 1):
            candidate = _canonical_candidate(
                product_id,
                {"kind": product_id, "payload": {"fixture": product_id}},
                events,
                suffix=str(index),
            )
            sessions.by_reference[candidate.projection.reference] = candidate
            route = await router.prepare_resume(
                product_id=product_id, reference=candidate.projection.reference
            )
            assert isinstance(route, PreparedProductRouteV1)
            assert route.binding_key.product_id == product_id
            assert not hasattr(route, "factory")
            assert not hasattr(route, "opened")
            assert route.generation_id == "generation-1"
            with pytest.raises(AttributeError):
                route.generation_id = "generation-2"  # type: ignore[misc]
            await route.close()
            assert events[-4:] == [
                "opened.close",
                "claimed.close",
                "candidate.close",
                f"pin.close:{product_id}",
            ]
        assert all(owner.factory.calls == 0 for owner in owners.values())
        with pytest.raises(ProductIdentityRequiredError):
            await router.prepare_resume(
                product_id="", reference=next(iter(sessions.by_reference))
            )
        await catalog.close()

    asyncio.run(exercise())


def test_create_recovery_never_duplicates_when_current_product_changes_or_retires() -> None:
    async def exercise() -> None:
        events: list[str] = []
        first, _ = _catalog_input("generation-1", events)
        catalog = await AppHostCatalogV1.admit(first)
        sessions = _Sessions(events)
        router = AppHostRouterV1(catalog, sessions)
        request = _request()
        prepared = await router.prepare_create(request)
        await prepared.close()
        assert sessions.create_calls == 1

        changed, changed_owners = _catalog_input("generation-2", events)
        coding = changed.products[0]
        changed = replace(
            changed,
            products=(
                replace(
                    coding,
                    descriptor=replace(
                        coding.descriptor,
                        compatibility_id="coding-session-v2",
                    ),
                ),
                *changed.products[1:],
            ),
        )
        await catalog.replace(changed, expected_generation_id="generation-1")
        with pytest.raises(ProductIncompatibleError):
            await router.prepare_create(request)
        assert sessions.create_calls == 1
        assert changed_owners["coding"].validator.calls == 0

        slides_only, _ = _catalog_input(
            "generation-3", events, product_ids=("slides",)
        )
        await catalog.replace(slides_only, expected_generation_id="generation-2")
        with pytest.raises(ProductUnavailableError):
            await router.prepare_create(request)
        assert sessions.create_calls == 1

        await catalog.close()
        with pytest.raises(GenerationRetiredError):
            await router.prepare_create(request)
        assert sessions.create_calls == 1

    asyncio.run(exercise())


def test_create_is_lookup_first_idempotent_and_recovers_commit_before_cancel() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        router = AppHostRouterV1(catalog, sessions)
        request = _request()
        baseline_acquires = len(owners["coding"].source.pins)
        sessions.cancel_after_commit = True
        with pytest.raises(asyncio.CancelledError):
            await router.prepare_create(request)
        assert sessions.create_calls == 1
        assert events.index("sessions.find") < events.index(
            "pin.acquire:coding", baseline_acquires
        )

        route = await router.prepare_create(request)
        assert sessions.create_calls == 1
        assert route.binding_key.session_id == "session-1"
        assert owners["coding"].factory.calls == 0
        await route.close()
        await catalog.close()

    asyncio.run(exercise())


def test_create_same_operation_in_different_creator_scope_never_aliases() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, _ = _catalog_input("generation-1", events)
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        router = AppHostRouterV1(catalog, sessions)
        first = await router.prepare_create(_request(scope="user-a"))
        second = await router.prepare_create(_request(scope="user-b"))
        assert first.binding_key != second.binding_key
        assert sessions.create_calls == 2
        await first.close()
        await second.close()
        await catalog.close()

    asyncio.run(exercise())


def test_resume_rejects_wrong_product_compatibility_stale_and_removed_product() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        router = AppHostRouterV1(catalog, sessions)

        wrong = _canonical_candidate("coding", {"kind": "coding"}, events)
        sessions.by_reference[wrong.projection.reference] = wrong
        with pytest.raises(ProductIncompatibleError):
            await router.prepare_resume(
                product_id="slides", reference=wrong.projection.reference
            )
        assert owners["slides"].validator.calls == 0

        incompatible = _canonical_candidate(
            "coding",
            {"kind": "coding"},
            events,
            compatibility="coding-session-v2",
            suffix="2",
        )
        sessions.by_reference[incompatible.projection.reference] = incompatible
        with pytest.raises(ProductIncompatibleError):
            await router.prepare_resume(
                product_id="coding", reference=incompatible.projection.reference
            )
        assert owners["coding"].validator.calls == 0

        stale = _canonical_candidate(
            "coding", {"kind": "coding"}, events, suffix="3", stale=True
        )
        sessions.by_reference[stale.projection.reference] = stale
        with pytest.raises(SessionCandidateStaleError):
            await router.prepare_resume(
                product_id="coding", reference=stale.projection.reference
            )
        assert stale.closed == 1
        assert owners["coding"].validator.calls == 0

        # Unknown identities are rejected by the catalog before Product parsing.
        unknown = _canonical_candidate("unknown", {"kind": "unknown"}, events)
        sessions.by_reference[unknown.projection.reference] = unknown
        with pytest.raises(ProductUnavailableError):
            await router.prepare_resume(
                product_id="unknown", reference=unknown.projection.reference
            )
        await catalog.close()

    asyncio.run(exercise())


def test_explicit_import_routes_coding_and_external_shapes_without_mutating_source() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        router = AppHostRouterV1(catalog, sessions)
        fixtures = (
            ("coding", {"type": "session_meta", "payload": {"id": "abc"}}),
            ("slides", {"sessionId": "xyz", "messages": [{"role": "user"}]}),
        )
        for product_id, source in fixtures:
            original = repr(source)
            candidate = _legacy_candidate(product_id, source, events)
            sessions.by_reference[candidate.projection.reference] = candidate
            imported = await router.import_candidate(
                product_id=product_id,
                reference=candidate.projection.reference,
            )
            assert imported.candidate_id == f"imported-{product_id}"
            assert repr(source) == original
            assert candidate.closed == 1
        assert owners["coding"].importer.payloads == [fixtures[0][1]]
        assert owners["slides"].importer.payloads == [fixtures[1][1]]
        assert all(owner.factory.calls == 0 for owner in owners.values())
        await catalog.close()

    asyncio.run(exercise())


def test_router_close_is_shared_and_retries_only_unsettled_owner() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        owners["coding"].validator.fail_opened_close = True
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        candidate = _canonical_candidate(
            "coding", {"kind": "coding", "payload": {}}, events
        )
        sessions.by_reference[candidate.projection.reference] = candidate
        route = await AppHostRouterV1(catalog, sessions).prepare_resume(
            product_id="coding", reference=candidate.projection.reference
        )
        opened = owners["coding"].validator.opened[0]
        claimed = candidate.claimed[0]
        route_pin = owners["coding"].source.pins[-1]

        with pytest.raises(CleanupIncompleteError):
            await asyncio.gather(route.close(), route.close())
        assert (opened.closed, claimed.closed, candidate.closed, route_pin.closed) == (
            1,
            1,
            1,
            1,
        )
        await route.close()
        await route.close()
        assert (opened.closed, claimed.closed, candidate.closed, route_pin.closed) == (
            2,
            1,
            1,
            1,
        )
        await catalog.close()

    asyncio.run(exercise())


def test_router_cancelled_validator_unwinds_actual_stack_in_reverse_order() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        owners["coding"].validator.cancel = True
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        candidate = _canonical_candidate(
            "coding", {"kind": "coding", "payload": {}}, events
        )
        sessions.by_reference[candidate.projection.reference] = candidate

        with pytest.raises(asyncio.CancelledError):
            await AppHostRouterV1(catalog, sessions).prepare_resume(
                product_id="coding", reference=candidate.projection.reference
            )
        assert events[-3:] == [
            "claimed.close",
            "candidate.close",
            "pin.close:coding",
        ]
        await catalog.close()

    asyncio.run(exercise())


def test_router_redacts_external_session_and_product_failures() -> None:
    class _SecretSessions(_Sessions):
        async def open_candidate(
            self, reference: SessionCandidateRefV1
        ) -> _Candidate:
            raise RuntimeError("token-secret /private/candidate")

    class _SecretValidator(_Validator):
        async def open_product_candidate(
            self, candidate: object, envelope: SessionIdentityEnvelopeV1
        ) -> _Opened:
            raise RuntimeError("token-secret /private/product")

    async def exercise() -> None:
        events: list[str] = []
        value, _ = _catalog_input("generation-1", events)
        secret_validator = _SecretValidator("coding", events)
        value = replace(
            value,
            products=(
                replace(value.products[0], candidate_validator=secret_validator),
                *value.products[1:],
            ),
        )
        catalog = await AppHostCatalogV1.admit(value)
        candidate = _canonical_candidate(
            "coding", {"kind": "coding", "payload": {}}, events
        )

        with pytest.raises(SessionCandidateStaleError) as session_error:
            await AppHostRouterV1(catalog, _SecretSessions(events)).prepare_resume(
                product_id="coding", reference=candidate.projection.reference
            )
        assert session_error.value.__cause__ is None
        assert "secret" not in repr(session_error.value)

        sessions = _Sessions(events)
        sessions.by_reference[candidate.projection.reference] = candidate
        with pytest.raises(ProductIncompatibleError) as product_error:
            await AppHostRouterV1(catalog, sessions).prepare_resume(
                product_id="coding", reference=candidate.projection.reference
            )
        assert product_error.value.__cause__ is None
        assert "private" not in repr(product_error.value)
        await catalog.close()

    asyncio.run(exercise())


def test_router_statically_rejects_invalid_import_result_and_unwinds() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        owners["coding"].importer.invalid_result = True
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        candidate = _legacy_candidate("coding", {"legacy": True}, events)
        sessions.by_reference[candidate.projection.reference] = candidate
        with pytest.raises(SessionCandidateStaleError):
            await AppHostRouterV1(catalog, sessions).import_candidate(
                product_id="coding", reference=candidate.projection.reference
            )
        assert events[-3:] == [
            "claimed.close",
            "candidate.close",
            "pin.close:coding",
        ]
        await catalog.close()

    asyncio.run(exercise())


def test_router_retains_failed_unwind_and_concurrently_retries_only_debt() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        owners["coding"].validator.fail = True
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        candidate = _canonical_candidate(
            "coding", {"kind": "coding", "payload": {}}, events
        )
        candidate.fail_first_close = True
        sessions.by_reference[candidate.projection.reference] = candidate
        router = AppHostRouterV1(catalog, sessions)

        with pytest.raises(CleanupIncompleteError) as caught:
            await router.prepare_resume(
                product_id="coding", reference=candidate.projection.reference
            )
        assert caught.value.primary_category is AppHostFailureCategory.PRODUCT_INCOMPATIBLE
        claimed = candidate.claimed[0]
        route_pin = owners["coding"].source.pins[-1]
        assert (claimed.closed, candidate.closed, route_pin.closed) == (1, 1, 1)

        await asyncio.gather(
            router.settle_pending_cleanup(),
            router.settle_pending_cleanup(),
        )
        assert (claimed.closed, candidate.closed, route_pin.closed) == (1, 2, 1)
        await router.close()
        await catalog.close()

    asyncio.run(exercise())


def test_router_close_joins_cancelled_primary_cleanup_debt_and_fences_routes() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        owners["coding"].validator.cancel = True
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        candidate = _canonical_candidate(
            "coding", {"kind": "coding", "payload": {}}, events
        )
        candidate.fail_first_close = True
        sessions.by_reference[candidate.projection.reference] = candidate
        router = AppHostRouterV1(catalog, sessions)

        with pytest.raises(CleanupIncompleteError) as caught:
            await router.prepare_resume(
                product_id="coding", reference=candidate.projection.reference
            )
        assert caught.value.primary_category is None
        await router.close()
        assert candidate.closed == 2
        with pytest.raises(GenerationRetiredError):
            await router.prepare_resume(
                product_id="coding", reference=candidate.projection.reference
            )
        await catalog.close()

    asyncio.run(exercise())


def test_router_close_fences_and_joins_an_inflight_preparation() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        validator = owners["coding"].validator
        validator.entered = asyncio.Event()
        validator.release = asyncio.Event()
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        candidate = _canonical_candidate(
            "coding", {"kind": "coding", "payload": {}}, events
        )
        sessions.by_reference[candidate.projection.reference] = candidate
        router = AppHostRouterV1(catalog, sessions)
        preparation = asyncio.create_task(
            router.prepare_resume(
                product_id="coding", reference=candidate.projection.reference
            )
        )
        await validator.entered.wait()
        closing = asyncio.create_task(router.close())
        await asyncio.sleep(0)
        assert not closing.done()
        validator.release.set()
        route = await preparation
        await closing
        await route.close()
        await catalog.close()

    asyncio.run(exercise())


def test_router_retains_import_failure_cleanup_debt() -> None:
    async def exercise() -> None:
        events: list[str] = []
        value, owners = _catalog_input("generation-1", events)
        owners["coding"].importer.invalid_result = True
        catalog = await AppHostCatalogV1.admit(value)
        sessions = _Sessions(events)
        candidate = _legacy_candidate("coding", {"legacy": True}, events)
        candidate.fail_first_close = True
        sessions.by_reference[candidate.projection.reference] = candidate
        router = AppHostRouterV1(catalog, sessions)
        with pytest.raises(CleanupIncompleteError) as caught:
            await router.import_candidate(
                product_id="coding", reference=candidate.projection.reference
            )
        assert caught.value.primary_category is AppHostFailureCategory.SESSION_CANDIDATE_STALE
        await router.settle_pending_cleanup()
        assert candidate.closed == 2
        await router.close()
        await catalog.close()

    asyncio.run(exercise())
