from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from loushang.apphost import (
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostCatalogInputV1,
    AppHostCatalogV1,
    AppHostError,
    AppHostFailureCategory,
    AppHostRuntimeV1,
    AppHostSessionLeaseV1,
    AppHostShutdownBudgetV1,
    AppHostShutdownPhase,
    CleanupIncompleteError,
    GenerationConflictError,
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
from loushang.apphost.hosted import AppHostHostedBinderV1, HostedProductSessionV1
from loushang.appserver import AppServerProductPortsV1, AppServerSessionIdentityV1


class _Pin:
    def __init__(self, identity: AdmissionIdentityV1) -> None:
        self._identity = identity
        self.closed = 0
        self.fail_close = 0

    @property
    def identity(self) -> AdmissionIdentityV1:
        return self._identity

    async def close(self) -> None:
        self.closed += 1
        if self.fail_close:
            self.fail_close -= 1
            raise RuntimeError("sentinel pin close")


class _Source:
    def __init__(self, identity: AdmissionIdentityV1) -> None:
        self.identity = identity
        self.pins: list[_Pin] = []

    async def acquire_pin(self) -> _Pin:
        pin = _Pin(self.identity)
        self.pins.append(pin)
        return pin


class _Claimed:
    def __init__(self, reference: SessionCandidateRefV1, marker: object) -> None:
        self._reference = reference
        self._marker = marker
        self.closed = 0

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._reference

    @property
    def opaque_binding(self) -> object:
        return self._marker

    async def close(self) -> None:
        self.closed += 1


class _Candidate:
    def __init__(self, envelope: SessionIdentityEnvelopeV1, revision: str) -> None:
        self.envelope = envelope
        self._projection = SessionIdentityProjectionV1(
            reference=SessionCandidateRefV1("canonical", envelope.session_id, revision),
            scope=SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
            mode=SessionCandidateMode.CANONICAL,
            envelope=envelope,
        )
        self.closed = 0
        self.verified = 0
        self.claimed: list[_Claimed] = []

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._projection

    async def verify_current(self) -> None:
        self.verified += 1

    async def claim(self) -> _Claimed:
        claimed = _Claimed(self._projection.reference, self)
        self.claimed.append(claimed)
        return claimed

    async def close(self) -> None:
        self.closed += 1


class _Opened:
    def __init__(self, key: SessionBindingKeyV1, marker: object) -> None:
        self._key = key
        self._marker = marker
        self.closed = 0

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._key

    @property
    def opaque_binding(self) -> object:
        return self._marker

    async def close(self) -> None:
        self.closed += 1


class _SessionPort:
    def __init__(self, candidates: dict[str, _Candidate]) -> None:
        self.candidates = candidates
        self.created: dict[tuple[str, str, str], str] = {}
        self.events: list[str] = []

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        return tuple(candidate.projection for candidate in self.candidates.values())[:limit]

    async def open_candidate(self, reference: SessionCandidateRefV1) -> _Candidate:
        self.events.append("open")
        return self.candidates[reference.candidate_id]

    async def find_created_candidate(
        self, request: SessionCreateRequestV1
    ) -> _Candidate | None:
        self.events.append("find")
        key = (request.product_id, request.creator_scope_id, request.operation_id)
        session_id = self.created.get(key)
        return None if session_id is None else self.candidates[session_id]

    async def create_candidate(self, intent: SessionCreateIntentV1) -> _Candidate:
        self.events.append("create")
        request = intent.request
        key = (request.product_id, request.creator_scope_id, request.operation_id)
        session_id = self.created.setdefault(key, f"created-{len(self.created) + 1}")
        candidate = self.candidates.get(session_id)
        if candidate is None:
            candidate = _Candidate(
                _envelope(
                    product_id=request.product_id,
                    compatibility_id=intent.product_compatibility_id,
                    session_id=session_id,
                ),
                f"revision-{len(self.created)}",
            )
            self.candidates[session_id] = candidate
        return candidate


class _Validator:
    def __init__(self) -> None:
        self.calls = 0
        self.opened: list[_Opened] = []

    async def open_product_candidate(
        self,
        candidate: object,
        envelope: SessionIdentityEnvelopeV1,
    ) -> _Opened:
        self.calls += 1
        key = SessionBindingKeyV1(
            envelope.product_id,
            envelope.continuity_id,
            envelope.session_id,
        )
        opened = _Opened(key, candidate)
        self.opened.append(opened)
        return opened


class _ProfileView:
    def __init__(self, key: SessionBindingKeyV1, opaque: object) -> None:
        self._key = key
        self._opaque = opaque

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._key

    @property
    def opaque_binding(self) -> object:
        return self._opaque


class _ProductRuntime:
    def __init__(self, key: SessionBindingKeyV1) -> None:
        self._key = key
        self._profile = _ProfileView(key, self)
        self.closed = 0
        self.fail_close = 0
        self.reenter: AppHostRuntimeV1 | None = None
        self.reentry_failure: AppHostFailureCategory | None = None

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        return self._key

    @property
    def profile_binding(self) -> _ProfileView:
        return self._profile

    async def close(self) -> None:
        self.closed += 1
        if self.reenter is not None:
            try:
                await self.reenter.close()
            except AppHostError as error:
                self.reentry_failure = error.category
        if self.fail_close:
            self.fail_close -= 1
            raise RuntimeError("sentinel runtime close")


class _MalformedRuntime:
    def __init__(self) -> None:
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


class _MalformedProfile:
    def __init__(self, *, fail_close: int = 0) -> None:
        self.closed = 0
        self.fail_close = fail_close

    async def close(self) -> None:
        self.closed += 1
        if self.fail_close:
            self.fail_close -= 1
            raise RuntimeError("sentinel malformed profile close")


class _Factory:
    def __init__(self) -> None:
        self.calls = 0
        self.runtimes: list[_ProductRuntime] = []
        self.entered: asyncio.Event | None = None
        self.release: asyncio.Event | None = None
        self.fail = 0
        self.malformed = 0
        self.reenter: AppHostRuntimeV1 | None = None
        self.reentry_failure: AppHostFailureCategory | None = None

    async def create_runtime(self, candidate: object) -> Any:
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.reenter is not None:
            try:
                await self.reenter.close()
            except AppHostError as error:
                self.reentry_failure = error.category
        if self.fail:
            self.fail -= 1
            raise RuntimeError("sentinel factory failure")
        if self.malformed:
            self.malformed -= 1
            value = _MalformedRuntime()
            self.last_malformed = value
            return value
        key = candidate.binding_key
        runtime = _ProductRuntime(key)
        self.runtimes.append(runtime)
        return runtime


class _ProfileLease:
    def __init__(
        self,
        profile_id: str,
        profile_binding: object,
        *,
        close_entered: asyncio.Event | None = None,
        close_release: asyncio.Event | None = None,
    ) -> None:
        self._profile_id = profile_id
        self._profile_binding = profile_binding
        self.closed = 0
        self.fail_close = 0
        self.close_entered = close_entered
        self.close_release = close_release
        self.reenter: AppHostRuntimeV1 | None = None
        self.reentry_failure: AppHostFailureCategory | None = None

    @property
    def profile_id(self) -> str:
        return self._profile_id

    @property
    def profile_binding(self) -> object:
        return self._profile_binding

    async def close(self) -> None:
        self.closed += 1
        if self.close_entered is not None:
            self.close_entered.set()
        if self.close_release is not None:
            await self.close_release.wait()
        if self.reenter is not None:
            try:
                await self.reenter.close()
            except AppHostError as error:
                self.reentry_failure = error.category
        if self.fail_close:
            self.fail_close -= 1
            raise RuntimeError("sentinel profile close")


class _ProfileFactory:
    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        self.calls = 0
        self.leases: list[_ProfileLease] = []
        self.close_entered: asyncio.Event | None = None
        self.close_release: asyncio.Event | None = None
        self.bind_entered: asyncio.Event | None = None
        self.bind_release: asyncio.Event | None = None
        self.fail = 0
        self.malformed = 0
        self.malformed_fail_close = 0
        self.last_malformed: _MalformedProfile | None = None
        self.lease_fail_close = 0
        self.binding_factory: Any = lambda runtime: (self.profile_id, runtime)

    async def bind_profile(self, runtime: object) -> Any:
        self.calls += 1
        if self.bind_entered is not None:
            self.bind_entered.set()
        if self.bind_release is not None:
            await self.bind_release.wait()
        if self.fail:
            self.fail -= 1
            raise RuntimeError("sentinel profile failure")
        if self.malformed:
            self.malformed -= 1
            malformed = _MalformedProfile(fail_close=self.malformed_fail_close)
            self.last_malformed = malformed
            return malformed
        lease = _ProfileLease(
            self.profile_id,
            self.binding_factory(runtime),
            close_entered=self.close_entered,
            close_release=self.close_release,
        )
        lease.fail_close = self.lease_fail_close
        self.leases.append(lease)
        return lease


@dataclass
class _Generation:
    catalog: AppHostCatalogV1
    catalog_input: AppHostCatalogInputV1
    sources: dict[str, _Source]
    factories: dict[str, _Factory]
    validators: dict[str, _Validator]
    profiles: dict[str, _ProfileFactory]


def _envelope(
    *,
    product_id: str = "coding",
    compatibility_id: str = "compat-1",
    session_id: str = "session-1",
) -> SessionIdentityEnvelopeV1:
    return SessionIdentityEnvelopeV1(
        product_id=product_id,
        product_compatibility_id=compatibility_id,
        continuity_id=f"continuity-{session_id}",
        session_id=session_id,
        provider_id="canonical",
        locator_token=f"locator-{session_id}",
    )


async def _generation(
    generation_id: str,
    *,
    product_ids: tuple[str, ...] = ("coding",),
    profile_ids: tuple[str, ...] = ("embedded-tui", "hosted-app"),
    compatibility_id: str = "compat-1",
) -> _Generation:
    sources: dict[str, _Source] = {}
    factories: dict[str, _Factory] = {}
    validators: dict[str, _Validator] = {}
    profiles: dict[str, _ProfileFactory] = {}
    product_regs = []
    for product_id in product_ids:
        identity = AdmissionIdentityV1(
            generation_id,
            AppHostAdmissionSubjectKind.PRODUCT,
            product_id,
        )
        source = _Source(identity)
        factory = _Factory()
        validator = _Validator()
        sources[product_id] = source
        factories[product_id] = factory
        validators[product_id] = validator
        product_regs.append(
            ProductRegistrationV1(
                descriptor=ProductDescriptorV1(
                    product_id,
                    "1.0",
                    compatibility_id,
                    profile_ids,
                ),
                factory=factory,
                candidate_validator=validator,
                admission_identity=identity,
                admission_source=source,
            )
        )
    profile_regs = []
    for profile_id in profile_ids:
        identity = AdmissionIdentityV1(
            generation_id,
            AppHostAdmissionSubjectKind.PROFILE,
            profile_id,
        )
        source = _Source(identity)
        factory = _ProfileFactory(profile_id)
        sources[profile_id] = source
        profiles[profile_id] = factory
        profile_regs.append(
            ProfileRegistrationV1(
                descriptor=ProfileDescriptorV1(profile_id, "1.0"),
                factory=factory,
                admission_identity=identity,
                admission_source=source,
            )
        )
    catalog_input = AppHostCatalogInputV1(
        generation_id=generation_id,
        products=tuple(product_regs),
        profiles=tuple(profile_regs),
    )
    catalog = await AppHostCatalogV1.admit(catalog_input)
    return _Generation(
        catalog,
        catalog_input,
        sources,
        factories,
        validators,
        profiles,
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_single_flight_multi_profile_and_explicit_session_close() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        envelope = _envelope()
        candidate = _Candidate(envelope, "revision-1")
        sessions = _SessionPort({envelope.session_id: candidate})
        runtime = AppHostRuntimeV1(generation.catalog, sessions)
        factory = generation.factories["coding"]
        factory.entered = asyncio.Event()
        factory.release = asyncio.Event()

        first = asyncio.create_task(
            runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            )
        )
        await factory.entered.wait()
        second = asyncio.create_task(
            runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="hosted-app",
            )
        )
        factory.release.set()
        first_lease, second_lease = await asyncio.gather(first, second)

        assert isinstance(first_lease, AppHostSessionLeaseV1)
        assert first_lease.binding_key == second_lease.binding_key
        assert factory.calls == 1
        assert generation.validators["coding"].calls == 2
        assert generation.profiles["embedded-tui"].calls == 1
        assert generation.profiles["hosted-app"].calls == 1
        product_runtime = factory.runtimes[0]

        await first_lease.close()
        await first_lease.close()
        assert product_runtime.closed == 0
        await second_lease.close()
        assert product_runtime.closed == 0
        await runtime.close_session(first_lease.binding_key)
        assert product_runtime.closed == 1
        await runtime.close()

    _run(scenario())


def test_catalog_replacement_existing_binding_uses_retained_generation() -> None:
    async def scenario() -> None:
        first = await _generation("generation-1")
        envelope = _envelope()
        candidate = _Candidate(envelope, "revision-1")
        runtime = AppHostRuntimeV1(first.catalog, _SessionPort({"session-1": candidate}))
        original = await runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )

        second = await _generation("generation-2", compatibility_id="compat-2")
        await first.catalog.replace(
            second.catalog_input,
            expected_generation_id="generation-1",
        )
        await second.catalog.close()
        retained = await runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="hosted-app",
        )
        assert retained.generation_id == "generation-1"
        assert first.factories["coding"].calls == 1
        assert first.validators["coding"].calls == 2
        assert second.factories["coding"].calls == 0
        assert second.validators["coding"].calls == 0
        assert first.profiles["hosted-app"].calls == 1
        assert second.profiles["hosted-app"].calls == 0

        await asyncio.gather(original.close(), retained.close())
        await runtime.close()

    _run(scenario())


def test_cancel_after_single_flight_publication_closes_only_cancelled_attachment() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        factory = generation.factories["coding"]
        factory.entered = asyncio.Event()
        factory.release = asyncio.Event()
        task = asyncio.create_task(
            runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            )
        )
        await factory.entered.wait()
        task.cancel()
        factory.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert generation.profiles["embedded-tui"].leases[0].closed == 1
        assert factory.runtimes[0].closed == 0
        await runtime.close_session(
            SessionBindingKeyV1("coding", "continuity-session-1", "session-1")
        )
        assert factory.runtimes[0].closed == 1
        await runtime.close()

    _run(scenario())


def test_failed_construction_is_not_cached_and_malformed_runtime_is_closed() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        factory = generation.factories["coding"]
        factory.fail = 1
        with pytest.raises(AppHostError) as first:
            await runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            )
        assert first.value.category is AppHostFailureCategory.RUNTIME_UNAVAILABLE

        factory.malformed = 1
        with pytest.raises(AppHostError):
            await runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            )
        assert factory.last_malformed.closed == 1

        lease = await runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        assert factory.calls == 3
        await lease.close()
        await runtime.close()

    _run(scenario())


def test_create_is_idempotent_and_joins_the_known_live_key() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        sessions = _SessionPort({})
        runtime = AppHostRuntimeV1(generation.catalog, sessions)
        request = SessionCreateRequestV1(
            "coding",
            "creator-1",
            "0123456789abcdefghijkl",
        )
        first = await runtime.attach_create(request, profile_id="embedded-tui")
        second = await runtime.attach_create(request, profile_id="embedded-tui")
        assert first.binding_key == second.binding_key
        assert generation.factories["coding"].calls == 1
        assert sessions.events[:2] == ["find", "create"]
        assert sessions.events[2:4] == ["find", "open"]
        await asyncio.gather(first.close(), second.close())
        await runtime.close()

    _run(scenario())


def test_close_session_fences_attach_and_stale_detach_cannot_close_successor() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        profile = generation.profiles["embedded-tui"]
        first = await runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        profile.close_entered = asyncio.Event()
        profile.close_release = asyncio.Event()
        # The existing lease was built before the blocking close configuration.
        profile.leases[0].close_entered = profile.close_entered
        profile.leases[0].close_release = profile.close_release
        closing = asyncio.create_task(runtime.close_session(first.binding_key))
        await profile.close_entered.wait()
        with pytest.raises(GenerationConflictError):
            await runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            )
        profile.close_release.set()
        await closing

        successor = await runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        assert generation.factories["coding"].calls == 2
        await first.close()
        assert generation.factories["coding"].runtimes[-1].closed == 0
        await successor.close()
        await runtime.close()

    _run(scenario())


def test_shutdown_timeout_is_typed_and_retry_joins_retained_phase() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        lease = await runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        profile = generation.profiles["embedded-tui"].leases[0]
        profile.close_entered = asyncio.Event()
        profile.close_release = asyncio.Event()
        report = await runtime.shutdown(AppHostShutdownBudgetV1(0.05, 0.02))
        assert report.completed is False
        assert report.timed_out_phases == (AppHostShutdownPhase.BINDINGS,)
        assert AppHostShutdownPhase.CATALOG not in report.failed_phases
        assert all(pin.closed == 0 for pin in generation.sources["coding"].pins[1:])

        profile.close_release.set()
        report = await runtime.shutdown(AppHostShutdownBudgetV1(1.0, 0.5))
        assert report.completed is True
        await lease.close()

    _run(scenario())


def test_runtime_close_failure_fences_admission_until_retry() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        lease = await runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        product_runtime = generation.factories["coding"].runtimes[0]
        product_runtime.fail_close = 1
        await lease.close()
        first = await runtime.shutdown(AppHostShutdownBudgetV1(1.0, 0.5))
        assert first.failed_phases == (AppHostShutdownPhase.BINDINGS,)
        runtime_pins = generation.sources["coding"].pins[1:]
        assert runtime_pins and all(pin.closed == 0 for pin in runtime_pins)
        second = await runtime.shutdown(AppHostShutdownBudgetV1(1.0, 0.5))
        assert second.completed is True
        assert product_runtime.closed == 2
        assert all(pin.closed == 1 for pin in runtime_pins)

    _run(scenario())


def test_product_callback_reentry_fails_fast_without_deadlock() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        factory = generation.factories["coding"]
        factory.reenter = runtime
        lease = await asyncio.wait_for(
            runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            ),
            timeout=1.0,
        )
        assert factory.reentry_failure is AppHostFailureCategory.RUNTIME_UNAVAILABLE
        await lease.close()
        await runtime.close()

    _run(scenario())


def test_cleanup_callback_reentry_fails_fast_without_owner_self_wait() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        lease = await runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        profile = generation.profiles["embedded-tui"].leases[0]
        profile.reenter = runtime
        product_runtime = generation.factories["coding"].runtimes[0]
        product_runtime.reenter = runtime

        report = await asyncio.wait_for(
            runtime.shutdown(AppHostShutdownBudgetV1(1.0, 0.5)),
            timeout=1.0,
        )

        assert report.completed is True
        assert profile.reentry_failure is AppHostFailureCategory.RUNTIME_UNAVAILABLE
        assert product_runtime.reentry_failure is AppHostFailureCategory.RUNTIME_UNAVAILABLE
        await lease.close()

    _run(scenario())


def test_close_session_drains_an_admitted_profile_bind_before_runtime_close() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        profile = generation.profiles["embedded-tui"]
        profile.bind_entered = asyncio.Event()
        profile.bind_release = asyncio.Event()
        key = SessionBindingKeyV1("coding", "continuity-session-1", "session-1")

        attaching = asyncio.create_task(
            runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            )
        )
        await profile.bind_entered.wait()
        closing = asyncio.create_task(runtime.close_session(key))
        await asyncio.sleep(0)
        assert not closing.done()

        profile.bind_release.set()
        lease, _ = await asyncio.gather(attaching, closing)
        assert profile.leases[0].closed == 1
        assert generation.factories["coding"].runtimes[0].closed == 1
        await lease.close()
        await runtime.close()

    _run(scenario())


def test_unrelated_products_build_independently() -> None:
    async def scenario() -> None:
        generation = await _generation(
            "generation-1",
            product_ids=("coding", "slides"),
        )
        coding_candidate = _Candidate(_envelope(session_id="coding-1"), "revision-1")
        slides_candidate = _Candidate(
            _envelope(product_id="slides", session_id="slides-1"),
            "revision-2",
        )
        runtime = AppHostRuntimeV1(
            generation.catalog,
            _SessionPort(
                {
                    "coding-1": coding_candidate,
                    "slides-1": slides_candidate,
                }
            ),
        )
        coding_factory = generation.factories["coding"]
        coding_factory.entered = asyncio.Event()
        coding_factory.release = asyncio.Event()
        blocked = asyncio.create_task(
            runtime.attach_resume(
                product_id="coding",
                reference=coding_candidate.projection.reference,
                profile_id="embedded-tui",
            )
        )
        await coding_factory.entered.wait()

        independent = await asyncio.wait_for(
            runtime.attach_resume(
                product_id="slides",
                reference=slides_candidate.projection.reference,
                profile_id="embedded-tui",
            ),
            timeout=0.5,
        )
        assert generation.factories["slides"].calls == 1
        assert not blocked.done()

        coding_factory.release.set()
        coding = await blocked
        await asyncio.gather(coding.close(), independent.close())
        await runtime.close()

    _run(scenario())


def test_malformed_profile_cleanup_debt_is_retained_and_retryable() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        profile = generation.profiles["embedded-tui"]
        profile.malformed = 1
        profile.malformed_fail_close = 1

        with pytest.raises(AppHostError) as rejected:
            await runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            )
        assert rejected.value.category is AppHostFailureCategory.CLEANUP_INCOMPLETE
        assert isinstance(rejected.value, CleanupIncompleteError)
        assert (
            rejected.value.primary_category
            is AppHostFailureCategory.PROFILE_UNAVAILABLE
        )
        assert profile.last_malformed is not None
        assert profile.last_malformed.closed == 1

        await runtime.settle_pending_cleanup()
        assert profile.last_malformed.closed == 2
        lease = await runtime.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
            profile_id="embedded-tui",
        )
        assert generation.factories["coding"].calls == 1
        await lease.close()
        await runtime.close()

    _run(scenario())


def test_shutdown_admission_timeout_joins_the_inflight_attach_on_retry() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        profile = generation.profiles["embedded-tui"]
        profile.bind_entered = asyncio.Event()
        profile.bind_release = asyncio.Event()
        attaching = asyncio.create_task(
            runtime.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
                profile_id="embedded-tui",
            )
        )
        await profile.bind_entered.wait()

        first = await runtime.shutdown(AppHostShutdownBudgetV1(0.05, 0.02))
        assert first.timed_out_phases == (AppHostShutdownPhase.ADMISSION,)
        profile.bind_release.set()
        lease = await attaching
        second = await runtime.shutdown(AppHostShutdownBudgetV1(1.0, 0.5))
        assert second.completed is True
        assert profile.leases[0].closed == 1
        await lease.close()

    _run(scenario())


def test_shutdown_closes_unrelated_bindings_while_one_profile_is_blocked() -> None:
    async def scenario() -> None:
        generation = await _generation(
            "generation-1",
            product_ids=("coding", "slides"),
        )
        coding_candidate = _Candidate(_envelope(session_id="coding-1"), "revision-1")
        slides_candidate = _Candidate(
            _envelope(product_id="slides", session_id="slides-1"),
            "revision-2",
        )
        runtime = AppHostRuntimeV1(
            generation.catalog,
            _SessionPort(
                {
                    "coding-1": coding_candidate,
                    "slides-1": slides_candidate,
                }
            ),
        )
        coding = await runtime.attach_resume(
            product_id="coding",
            reference=coding_candidate.projection.reference,
            profile_id="embedded-tui",
        )
        slides = await runtime.attach_resume(
            product_id="slides",
            reference=slides_candidate.projection.reference,
            profile_id="embedded-tui",
        )
        profile = generation.profiles["embedded-tui"]
        profile.leases[0].close_entered = asyncio.Event()
        profile.leases[0].close_release = asyncio.Event()

        first = await runtime.shutdown(AppHostShutdownBudgetV1(0.05, 0.02))
        assert first.timed_out_phases == (AppHostShutdownPhase.BINDINGS,)
        assert profile.leases[1].closed == 1
        assert generation.factories["slides"].runtimes[0].closed == 1
        assert generation.factories["coding"].runtimes[0].closed == 0

        profile.leases[0].close_release.set()
        second = await runtime.shutdown(AppHostShutdownBudgetV1(1.0, 0.5))
        assert second.completed is True
        await asyncio.gather(coding.close(), slides.close())

    _run(scenario())


def test_hosted_binder_projects_exact_appserver_ports_without_owning_semantics() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        session_port = object()
        projection_port = object()

        def bind_ports(profile: Any) -> AppServerProductPortsV1[object, object, object, object]:
            key = profile.binding_key
            return AppServerProductPortsV1(
                identity=AppServerSessionIdentityV1(
                    key.product_id,
                    key.continuity_id,
                    key.session_id,
                ),
                session=session_port,
                projection=projection_port,
            )

        generation.profiles["hosted-app"].binding_factory = bind_ports
        binder: AppHostHostedBinderV1[object, object, object, object] = (
            AppHostHostedBinderV1(runtime, profile_id="hosted-app")
        )
        hosted = await binder.attach_resume(
            product_id="coding",
            reference=candidate.projection.reference,
        )
        assert isinstance(hosted, HostedProductSessionV1)
        assert hosted.ports.session is session_port
        assert hosted.ports.projection is projection_port
        assert hosted.ports.identity.session_id == "session-1"
        product_runtime = generation.factories["coding"].runtimes[0]
        await hosted.close()
        assert product_runtime.closed == 0
        await runtime.close()
        assert product_runtime.closed == 1

    _run(scenario())


def test_hosted_binder_rejects_foreign_identity_and_closes_attachment() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        generation.profiles["hosted-app"].binding_factory = lambda _: (
            AppServerProductPortsV1(
                identity=AppServerSessionIdentityV1(
                    "coding",
                    "foreign-continuity",
                    "foreign-session",
                ),
                session=object(),
                projection=object(),
            )
        )
        binder: AppHostHostedBinderV1[object, object, object, object] = (
            AppHostHostedBinderV1(runtime, profile_id="hosted-app")
        )
        with pytest.raises(AppHostError) as error:
            await binder.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
            )
        assert error.value.category is AppHostFailureCategory.PROFILE_UNAVAILABLE
        assert generation.profiles["hosted-app"].leases[0].closed == 1
        await runtime.close()

    _run(scenario())


def test_hosted_cancellation_preserves_profile_cleanup_debt() -> None:
    async def scenario() -> None:
        generation = await _generation("generation-1")
        candidate = _Candidate(_envelope(), "revision-1")
        runtime = AppHostRuntimeV1(generation.catalog, _SessionPort({"session-1": candidate}))
        profile = generation.profiles["hosted-app"]
        profile.bind_entered = asyncio.Event()
        profile.bind_release = asyncio.Event()
        profile.lease_fail_close = 1
        binder: AppHostHostedBinderV1[object, object, object, object] = (
            AppHostHostedBinderV1(runtime, profile_id="hosted-app")
        )
        task = asyncio.create_task(
            binder.attach_resume(
                product_id="coding",
                reference=candidate.projection.reference,
            )
        )
        await profile.bind_entered.wait()
        task.cancel()
        profile.bind_release.set()

        with pytest.raises(AppHostError) as error:
            await task
        assert error.value.category is AppHostFailureCategory.CLEANUP_INCOMPLETE
        assert profile.leases[0].closed == 1
        await runtime.close()
        assert profile.leases[0].closed == 2

    _run(scenario())


def test_appserver_structural_port_values_are_frozen_and_validate_identity() -> None:
    class _StringSubclass(str):
        pass

    class _IdentitySubclass(AppServerSessionIdentityV1):
        pass

    identity = AppServerSessionIdentityV1(
        "coding",
        "continuity-1",
        "session-1",
    )
    ports = AppServerProductPortsV1(
        identity=identity,
        session="session-port",
        projection="projection-port",
    )
    assert ports.work is None
    assert ports.interaction is None
    with pytest.raises(AttributeError):
        ports.session = "replacement"  # type: ignore[misc]
    with pytest.raises(ValueError, match="invalid appserver product ports contract"):
        AppServerSessionIdentityV1("Coding", "continuity-1", "session-1")
    with pytest.raises(ValueError, match="invalid appserver product ports contract"):
        AppServerSessionIdentityV1(
            _StringSubclass("coding"),
            "continuity-1",
            "session-1",
        )
    with pytest.raises(ValueError, match="invalid appserver product ports contract"):
        AppServerProductPortsV1(
            identity=identity,
            session=None,
            projection="projection-port",
        )
    with pytest.raises(ValueError, match="invalid appserver product ports contract"):
        AppServerProductPortsV1(
            identity=_IdentitySubclass("coding", "continuity-1", "session-1"),
            session="session-port",
            projection="projection-port",
        )
