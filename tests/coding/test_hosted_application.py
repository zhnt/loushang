from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from typing import cast

import pytest

from loushang.apphost import (
    AdmissionIdentityV1,
    AppHostAdmissionSubjectKind,
    AppHostShutdownBudgetV1,
    ClaimedSessionCandidateV1,
    OpenedProductCandidateV1,
    SessionBindingKeyV1,
    SessionCandidateMode,
    SessionCandidateRefV1,
    SessionCreateIntentV1,
    SessionCreateRequestV1,
    SessionDiscoveryScope,
    SessionIdentityEnvelopeV1,
    SessionIdentityProjectionV1,
)
from loushang.apphost.application import (
    HostedApplicationActivationV1,
    HostedApplicationRuntimeV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxCloseV1,
    MuxCreateV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
)
from loushang.coding.appservice_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSnapshotProjectionV1,
    coding_hosted_identity_from_envelope,
)
from loushang.coding.hosted_application import (
    CODING_HOSTED_APPLICATION_PROFILE_ID,
    CodingForegroundHostedApplicationRequestV1,
    create_coding_foreground_hosted_application,
)
from loushang.harness.events import RuntimeEvent
from loushang.harnesstui.mux import open_hosted_mux_profile

_CWD_FINGERPRINT = "a" * 64
_HOME_FINGERPRINT = "b" * 64
_GENERATION = "generation-12"
_COMPATIBILITY = "coding-hosted-v1"


def _async_test(
    function: Callable[[], Awaitable[None]],
) -> Callable[[], None]:
    @wraps(function)
    def wrapper() -> None:
        asyncio.run(function())

    return wrapper


class _Pin:
    def __init__(self, identity: AdmissionIdentityV1, events: list[str]) -> None:
        self._identity = identity
        self._events = events
        self.closed = False

    @property
    def identity(self) -> AdmissionIdentityV1:
        return self._identity

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._events.append(f"pin.close:{self._identity.subject_id}")


class _AdmissionSource:
    def __init__(
        self,
        kind: AppHostAdmissionSubjectKind,
        subject_id: str,
        events: list[str],
    ) -> None:
        self.identity = AdmissionIdentityV1(_GENERATION, kind, subject_id)
        self.events = events
        self.pins: list[_Pin] = []

    async def acquire_pin(self) -> _Pin:
        pin = _Pin(self.identity, self.events)
        self.pins.append(pin)
        return pin


@dataclass(frozen=True)
class _Payload:
    envelope: SessionIdentityEnvelopeV1
    scope: SessionDiscoveryScope
    scope_fingerprint: str


@dataclass(frozen=True)
class _Record:
    projection: SessionIdentityProjectionV1
    payload: _Payload


class _Claimed:
    def __init__(self, record: _Record) -> None:
        self._record = record
        self.closed = False

    @property
    def reference(self) -> SessionCandidateRefV1:
        return self._record.projection.reference

    @property
    def opaque_binding(self) -> object:
        return self._record.payload

    async def close(self) -> None:
        self.closed = True


class _Candidate:
    def __init__(self, record: _Record) -> None:
        self._record = record
        self.closed = False

    @property
    def projection(self) -> SessionIdentityProjectionV1:
        return self._record.projection

    async def verify_current(self) -> None:
        return None

    async def claim(self) -> ClaimedSessionCandidateV1:
        return _Claimed(self._record)

    async def close(self) -> None:
        self.closed = True


class _CanonicalSessions:
    def __init__(self) -> None:
        self.records: dict[SessionCandidateRefV1, _Record] = {}
        self.created: dict[SessionCreateRequestV1, SessionCandidateRefV1] = {}
        self.create_intents: list[SessionCreateIntentV1] = []
        self.list_scopes: list[tuple[SessionDiscoveryScope, ...]] = []
        self.counter = 0
        self.created_continuity_override: str | None = None
        self.created_scope_override: SessionDiscoveryScope | None = None

    def add(
        self,
        *,
        session_id: str,
        continuity_id: str,
        scope: SessionDiscoveryScope,
        scope_fingerprint: str,
        mode: SessionCandidateMode = SessionCandidateMode.CANONICAL,
        candidate_id: str | None = None,
    ) -> SessionCandidateRefV1:
        self.counter += 1
        reference = SessionCandidateRefV1(
            "canonical",
            candidate_id or f"candidate-{self.counter}",
            f"revision-{self.counter}",
        )
        envelope = SessionIdentityEnvelopeV1(
            product_id="coding",
            product_compatibility_id=_COMPATIBILITY,
            continuity_id=continuity_id,
            session_id=session_id,
            provider_id="canonical-store",
            locator_token=f"opaque-{self.counter}",
        )
        projection = SessionIdentityProjectionV1(
            reference,
            scope,
            mode,
            envelope if mode is SessionCandidateMode.CANONICAL else None,
        )
        self.records[reference] = _Record(
            projection,
            _Payload(envelope, scope, scope_fingerprint),
        )
        return reference

    async def list_identities(
        self,
        scopes: tuple[SessionDiscoveryScope, ...],
        *,
        limit: int,
    ) -> tuple[SessionIdentityProjectionV1, ...]:
        self.list_scopes.append(scopes)
        return tuple(
            record.projection
            for record in self.records.values()
            if record.projection.scope in scopes
        )[:limit]

    async def open_candidate(self, reference: SessionCandidateRefV1) -> _Candidate:
        return _Candidate(self.records[reference])

    async def find_created_candidate(
        self,
        request: SessionCreateRequestV1,
    ) -> _Candidate | None:
        reference = self.created.get(request)
        return None if reference is None else _Candidate(self.records[reference])

    async def create_candidate(self, intent: SessionCreateIntentV1) -> _Candidate:
        self.create_intents.append(intent)
        request = intent.request
        assert request.requested_continuity_id is not None
        assert request.requested_scope is not None
        reference = self.add(
            session_id=f"created-{self.counter + 1}",
            continuity_id=(
                self.created_continuity_override
                or request.requested_continuity_id
            ),
            scope=self.created_scope_override or request.requested_scope,
            scope_fingerprint=request.creator_scope_id,
        )
        self.created[request] = reference
        return _Candidate(self.records[reference])


class _Opened:
    def __init__(self, payload: _Payload) -> None:
        self._payload = payload
        self.closed = False

    @property
    def binding_key(self) -> SessionBindingKeyV1:
        envelope = self._payload.envelope
        return SessionBindingKeyV1(
            envelope.product_id,
            envelope.continuity_id,
            envelope.session_id,
        )

    @property
    def opaque_binding(self) -> object:
        return self._payload

    async def close(self) -> None:
        self.closed = True


class _CandidateValidator:
    async def open_product_candidate(
        self,
        candidate: ClaimedSessionCandidateV1,
        envelope: SessionIdentityEnvelopeV1,
    ) -> OpenedProductCandidateV1:
        payload = candidate.opaque_binding
        assert isinstance(payload, _Payload)
        assert payload.envelope == envelope
        return _Opened(payload)


class _Control:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.session_name = "Coding hosted"
        self.listener: Callable[[RuntimeEvent[object]], Awaitable[None] | None] | None = (
            None
        )
        self.prompts: list[str] = []

    def subscribe_runtime_events(
        self,
        listener: Callable[[RuntimeEvent[object]], Awaitable[None] | None],
    ) -> Callable[[], None]:
        self.listener = listener

        def unsubscribe() -> None:
            self.listener = None

        return unsubscribe

    async def prompt(self, text: str, **kwargs: object) -> None:
        del kwargs
        self.prompts.append(text)
        listener = self.listener
        assert listener is not None
        result = listener(
            RuntimeEvent(
                event_id=f"event-{len(self.prompts)}",
                kind="assistant",
                stream_id=f"session:{self.session_id}",
                sequence=len(self.prompts),
                occurred_at=datetime.now(UTC),
                payload=text,
                session_id=self.session_id,
            )
        )
        if result is not None:
            await result

    async def wait_for_idle(self) -> None:
        return None

    def steer(self, text: str, **kwargs: object) -> None:
        del text, kwargs

    def follow_up(self, text: str, **kwargs: object) -> None:
        del text, kwargs

    def abort(self) -> bool:
        return True


class _Binding:
    def __init__(
        self,
        payload: _Payload,
        events: list[str],
        *,
        fail_close_once: bool = False,
    ) -> None:
        self._payload = payload
        self._events = events
        self._control = _Control(payload.envelope.session_id)
        self.closed = 0
        self._fail_close_once = fail_close_once

    @property
    def identity(self) -> SessionIdentityV1:
        return coding_hosted_identity_from_envelope(
            self._payload.envelope,
            discovery_scope=self._payload.scope,
            scope_fingerprint=self._payload.scope_fingerprint,
        )

    @property
    def control(self) -> _Control:
        return self._control

    def project_snapshot(self) -> CodingHostedSnapshotProjectionV1:
        return CodingHostedSnapshotProjectionV1(
            title="Coding hosted",
            revision=1,
            running=False,
            records=(TranscriptRecordV1(TranscriptRecordKindV1.STATUS, "ready"),),
        )

    def project_event(
        self,
        event: RuntimeEvent[object],
    ) -> CodingHostedEventProjectionV1 | None:
        return CodingHostedEventProjectionV1(
            SessionEventKindV1.ASSISTANT_MESSAGE,
            cast(str, event.payload),
        )

    async def respond_interaction(self, interaction_id: str, outcome: str) -> bool:
        del interaction_id, outcome
        return True

    async def close(self) -> None:
        self.closed += 1
        self._events.append(f"session.close:{self.identity.session_id}")
        if self._fail_close_once:
            self._fail_close_once = False
            raise RuntimeError("hidden")


class _SessionFactory:
    def __init__(self, events: list[str], *, fail_close_once: bool = False) -> None:
        self.events = events
        self.bindings: list[_Binding] = []
        self._fail_close_once = fail_close_once

    async def create_session(
        self,
        *,
        binding_key: SessionBindingKeyV1,
        opaque_session_binding: object,
    ) -> _Binding:
        assert isinstance(opaque_session_binding, _Payload)
        assert binding_key.session_id == opaque_session_binding.envelope.session_id
        binding = _Binding(
            opaque_session_binding,
            self.events,
            fail_close_once=self._fail_close_once,
        )
        self._fail_close_once = False
        self.bindings.append(binding)
        return binding


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"g12-{self.value}"


@dataclass
class _Environment:
    app: HostedApplicationRuntimeV1
    sessions: _CanonicalSessions
    session_factory: _SessionFactory
    events: list[str]


async def _environment(*, fail_close_once: bool = False) -> _Environment:
    events: list[str] = []
    sessions = _CanonicalSessions()
    product_source = _AdmissionSource(
        AppHostAdmissionSubjectKind.PRODUCT,
        "coding",
        events,
    )
    profile_source = _AdmissionSource(
        AppHostAdmissionSubjectKind.PROFILE,
        CODING_HOSTED_APPLICATION_PROFILE_ID,
        events,
    )
    session_factory = _SessionFactory(events, fail_close_once=fail_close_once)
    ids = _Ids()
    app = await create_coding_foreground_hosted_application(
        CodingForegroundHostedApplicationRequestV1(
            activation=HostedApplicationActivationV1(),
            generation_id=_GENERATION,
            product_version="1",
            compatibility_id=_COMPATIBILITY,
            product_admission_source=product_source,
            profile_admission_source=profile_source,
            candidate_validator=_CandidateValidator(),
            sessions=sessions,
            session_factory=session_factory,
            shutdown_budget=AppHostShutdownBudgetV1(2.0, 1.0),
            operation_id_factory=lambda: f"operation-{ids.value:022d}",
            service_id_factory=ids,
        )
    )
    return _Environment(app, sessions, session_factory, events)


def _spec(
    *,
    session_id: str | None = None,
    scope: SessionScopeV1 = SessionScopeV1.CWD,
    continuity_id: str = "continuity-cwd",
) -> SessionOpenSpecV1:
    return SessionOpenSpecV1(
        product_id="coding",
        continuity_id=continuity_id,
        session_id=session_id,
        scope=scope,
        scope_fingerprint=(
            _CWD_FINGERPRINT if scope is SessionScopeV1.CWD else _HOME_FINGERPRINT
        ),
        title="Coding hosted",
    )


@_async_test
async def test_G12_VERTICAL_CANARY_crosses_real_composition_create_turn_resume_close() -> None:
    environment = await _environment()
    app = environment.app
    client = app.client
    await client.create_mux(MuxCreateV1("dev"))
    controller = await open_hosted_mux_profile(
        client,
        selector=MuxSelectorV1(name="dev"),
    )

    state = await controller.open_member(_spec())
    created_id = state.windows[0].session_id
    assert app.generation_id == _GENERATION
    assert environment.sessions.create_intents[0].request.requested_scope is (
        SessionDiscoveryScope.CURRENT_DIRECTORY
    )
    assert environment.sessions.create_intents[0].request.requested_continuity_id == (
        "continuity-cwd"
    )

    await controller.submit("hello hosted")
    await controller.poll()
    assert controller.state is not None
    assert controller.state.windows[0].records[-1] == TranscriptRecordV1(
        TranscriptRecordKindV1.ASSISTANT,
        "hello hosted",
    )

    await controller.close_active_member(close_session=True)
    assert environment.session_factory.bindings[0].closed == 1
    state = await controller.open_member(_spec(session_id=created_id))
    assert state.windows[0].session_id == created_id
    assert environment.sessions.list_scopes[-1] == (
        SessionDiscoveryScope.CURRENT_DIRECTORY,
    )

    await controller.close()
    await client.close_mux(MuxCloseV1(MuxSelectorV1(name="dev")))
    report = await app.shutdown()
    assert report.completed is True
    assert environment.session_factory.bindings[1].closed == 1
    assert environment.events[-2:] == [
        f"pin.close:{CODING_HOSTED_APPLICATION_PROFILE_ID}",
        "pin.close:coding",
    ]


@_async_test
async def test_G12_SCOPE_COMPAT_resumes_canonical_user_home_only() -> None:
    environment = await _environment()
    reference = environment.sessions.add(
        session_id="home-session",
        continuity_id="continuity-home",
        scope=SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
        scope_fingerprint=_HOME_FINGERPRINT,
    )
    environment.sessions.add(
        session_id="legacy-session",
        continuity_id="continuity-home",
        scope=SessionDiscoveryScope.USER_GLOBAL_LEGACY,
        scope_fingerprint=_HOME_FINGERPRINT,
        mode=SessionCandidateMode.MIGRATION_REQUIRED,
    )
    client = environment.app.client
    await client.create_mux(MuxCreateV1("home"))
    controller = await open_hosted_mux_profile(
        client,
        selector=MuxSelectorV1(name="home"),
    )

    state = await controller.open_member(
        _spec(
            session_id="home-session",
            scope=SessionScopeV1.USER_HOME,
            continuity_id="continuity-home",
        )
    )

    assert state.windows[0].session_id == "home-session"
    assert environment.sessions.list_scopes[-1] == (
        SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
    )
    assert reference in environment.sessions.records
    await controller.close()
    await environment.app.close()


@_async_test
async def test_G12_SCOPE_COMPAT_rejects_legacy_and_ambiguous_candidates() -> None:
    environment = await _environment()
    environment.sessions.add(
        session_id="legacy-session",
        continuity_id="continuity-home",
        scope=SessionDiscoveryScope.USER_GLOBAL_LEGACY,
        scope_fingerprint=_HOME_FINGERPRINT,
        mode=SessionCandidateMode.MIGRATION_REQUIRED,
    )
    environment.sessions.add(
        session_id="ambiguous-session",
        continuity_id="continuity-home",
        scope=SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
        scope_fingerprint=_HOME_FINGERPRINT,
        candidate_id="exact",
    )
    environment.sessions.add(
        session_id="ambiguous-session",
        continuity_id="conflicting-continuity",
        scope=SessionDiscoveryScope.USER_GLOBAL_CANONICAL,
        scope_fingerprint=_HOME_FINGERPRINT,
        candidate_id="conflict",
    )
    client = environment.app.client
    await client.create_mux(MuxCreateV1("home"))
    controller = await open_hosted_mux_profile(
        client,
        selector=MuxSelectorV1(name="home"),
    )

    with pytest.raises(AppServiceError) as legacy:
        await controller.open_member(
            _spec(
                session_id="legacy-session",
                scope=SessionScopeV1.USER_HOME,
                continuity_id="continuity-home",
            )
        )
    assert legacy.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
    with pytest.raises(AppServiceError) as ambiguous:
        await controller.open_member(
            _spec(
                session_id="ambiguous-session",
                scope=SessionScopeV1.USER_HOME,
                continuity_id="continuity-home",
            )
        )
    assert ambiguous.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
    assert environment.session_factory.bindings == []
    await controller.close()
    await environment.app.close()


@_async_test
async def test_G12_CANONICAL_ROUTING_rejects_bad_create_identity_before_factory() -> None:
    for field in ("continuity", "scope"):
        environment = await _environment()
        if field == "continuity":
            environment.sessions.created_continuity_override = "wrong-continuity"
        else:
            environment.sessions.created_scope_override = (
                SessionDiscoveryScope.USER_GLOBAL_CANONICAL
            )
        client = environment.app.client
        await client.create_mux(MuxCreateV1(f"bad-{field}"))
        controller = await open_hosted_mux_profile(
            client,
            selector=MuxSelectorV1(name=f"bad-{field}"),
        )

        with pytest.raises(AppServiceError) as rejected:
            await controller.open_member(_spec())

        assert rejected.value.code is AppErrorCodeV1.SESSION_UNAVAILABLE
        assert environment.session_factory.bindings == []
        await controller.close()
        await environment.app.close()


@_async_test
async def test_G12_LEASE_CLOSE_retains_exact_binding_cleanup_debt() -> None:
    environment = await _environment(fail_close_once=True)
    client = environment.app.client
    mux = await client.create_mux(MuxCreateV1("retry-close"))
    controller = await open_hosted_mux_profile(
        client,
        selector=MuxSelectorV1(mux_space_id=mux.mux_space_id),
    )
    await controller.open_member(_spec())

    with pytest.raises(AppServiceError) as incomplete:
        await controller.close_active_member(close_session=True)

    assert incomplete.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
    assert environment.session_factory.bindings[0].closed == 1
    await controller.close()
    report = await environment.app.shutdown()
    assert report.completed is True
    assert environment.session_factory.bindings[0].closed == 2
