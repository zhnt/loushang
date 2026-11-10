from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from loushang.agent import Agent
from loushang.ai.model import ModelSelection
from loushang.apphost import SessionDiscoveryScope, SessionIdentityEnvelopeV1
from loushang.appserver.protocol import (
    InteractionOutcomeV1,
    MuxAttachV1,
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    TranscriptRecordKindV1,
    TranscriptRecordV1,
    TurnTextV1,
)
from loushang.appservice import AppServiceV1, InProcessAppClientV1
from loushang.coding.appservice_adapter import (
    CodingHostedEventProjectionV1,
    CodingHostedSessionResolverV1,
    CodingHostedSessionV1,
    CodingHostedSnapshotProjectionV1,
    coding_hosted_identity_from_envelope,
)
from loushang.harness.events import RuntimeEvent

FINGERPRINT = "c" * 64


@pytest.mark.parametrize("catalog_size", [0, 1, 257])
@pytest.mark.parametrize("fallback", [None, "unknown", "valid"])
def test_model_catalog_excludes_unconfigured_agent_placeholder(
    monkeypatch, catalog_size, fallback,
) -> None:
    async def scenario() -> None:
        binding = _Binding(_spec(), "fresh-session")
        control = binding.control
        agent = Agent()
        initial_model = agent.model
        selected = (
            ModelSelection("provider", "endpoint", "selected")
            if fallback == "valid" else agent.model if fallback == "unknown" else None
        )
        catalog = [
            ModelSelection("provider", "endpoint", f"model-{index}")
            for index in range(catalog_size)
        ]
        monkeypatch.setattr(control, "agent", agent, raising=False)
        monkeypatch.setattr(control, "get_model_selection", lambda: selected, raising=False)
        monkeypatch.setattr(
            control, "get_available_model_details", lambda: [*catalog, agent.model],
            raising=False,
        )
        monkeypatch.setattr(control, "thinking_level", "off", raising=False)
        monkeypatch.setattr(
            control, "get_available_thinking_levels", lambda: ["off", "high"],
            raising=False,
        )
        hosted = CodingHostedSessionV1(binding)
        try:
            result = await hosted.list_models()
            assert all(choice.provider != "unknown" for choice in result.models)
            assert len(result.models) == min(catalog_size + (fallback == "valid"), 256)
            if fallback == "valid":
                assert result.current_id == "provider:endpoint:selected"
                assert any(choice.id == result.current_id for choice in result.models)
            else:
                assert result.current_id is None
                assert result.thinking is None
            assert agent.model is initial_model
        finally:
            await hosted.close()

    _run(scenario())


def test_model_catalog_preserves_valid_active_model_outside_registry(monkeypatch) -> None:
    async def scenario() -> None:
        binding = _Binding(_spec(), "active-session")
        active = ModelSelection("provider", "endpoint", "active")
        monkeypatch.setattr(
            binding.control, "agent", SimpleNamespace(model=active), raising=False,
        )
        hosted = CodingHostedSessionV1(binding)
        try:
            result = await hosted.list_models()
            assert result.current_id == "provider:endpoint:active"
            assert [choice.id for choice in result.models] == [result.current_id]
        finally:
            await hosted.close()

    _run(scenario())


def _run(coroutine: Awaitable[object]) -> object:
    return asyncio.run(coroutine)


class _Control:
    def get_model_selection(self) -> ModelSelection:
        return ModelSelection("provider", "endpoint", "model")

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.session_name = "Coding session"
        self.listener: Callable[[RuntimeEvent[object]], Awaitable[None] | None] | None = (
            None
        )
        self.calls: list[tuple[str, object]] = []

    def subscribe_runtime_events(
        self,
        listener: Callable[[RuntimeEvent[object]], Awaitable[None] | None],
    ) -> Callable[[], None]:
        self.listener = listener

        def unsubscribe() -> None:
            self.calls.append(("unsubscribe", ""))
            self.listener = None

        return unsubscribe

    async def emit(self, kind: str = "assistant") -> None:
        assert self.listener is not None
        result = self.listener(
            RuntimeEvent(
                event_id="event-1",
                kind=kind,
                stream_id=f"session:{self.session_id}",
                sequence=1,
                occurred_at=datetime.now(UTC),
                payload=object(),
                session_id=self.session_id,
            )
        )
        if result is not None:
            await result

    async def prompt(self, text: str, **kwargs: object) -> None:
        self.calls.append(("prompt", (text, kwargs)))

    async def wait_for_idle(self) -> None:
        self.calls.append(("idle", ""))

    def steer(self, text: str, **_kwargs: object) -> None:
        self.calls.append(("steer", text))

    def follow_up(self, text: str, **_kwargs: object) -> None:
        self.calls.append(("follow_up", text))

    def abort(self) -> bool:
        self.calls.append(("abort", ""))
        return True


class _Binding:
    def __init__(self, request: SessionOpenSpecV1, session_id: str) -> None:
        envelope = SessionIdentityEnvelopeV1(
            product_id=request.product_id,
            product_compatibility_id="coding-v1",
            continuity_id=request.continuity_id,
            session_id=session_id,
            provider_id="jsonl",
            locator_token="opaque-locator",
        )
        self._identity = coding_hosted_identity_from_envelope(
            envelope,
            discovery_scope=(
                SessionDiscoveryScope.CURRENT_DIRECTORY
                if request.scope is SessionScopeV1.CWD
                else SessionDiscoveryScope.USER_GLOBAL_CANONICAL
            ),
            scope_fingerprint=request.scope_fingerprint,
        )
        self._control = _Control(session_id)
        self.closed = 0
        self.fail_close = 0
        self.interactions: list[tuple[str, str]] = []

    @property
    def identity(self) -> SessionIdentityV1:
        return self._identity

    @property
    def control(self) -> _Control:
        return self._control

    def project_snapshot(self) -> CodingHostedSnapshotProjectionV1:
        return CodingHostedSnapshotProjectionV1(
            title="Coding session",
            revision=7,
            running=False,
            records=(
                TranscriptRecordV1(TranscriptRecordKindV1.USER, "hello"),
            ),
        )

    def project_event(
        self,
        event: RuntimeEvent[object],
    ) -> CodingHostedEventProjectionV1 | None:
        if event.kind == "ignored":
            return None
        return CodingHostedEventProjectionV1(
            SessionEventKindV1.ASSISTANT_MESSAGE,
            "projected",
        )

    async def respond_interaction(self, interaction_id: str, outcome: str) -> bool:
        self.interactions.append((interaction_id, outcome))
        return True

    async def close(self) -> None:
        self.closed += 1
        if self.fail_close:
            self.fail_close -= 1
            raise RuntimeError("sentinel close failure")


class _Factory:
    def __init__(self) -> None:
        self.create_requests: list[SessionOpenSpecV1] = []
        self.resume_requests: list[SessionOpenSpecV1] = []
        self.bindings: list[_Binding] = []

    async def create(self, request: SessionOpenSpecV1) -> _Binding:
        self.create_requests.append(request)
        binding = _Binding(request, f"created-{len(self.bindings) + 1}")
        self.bindings.append(binding)
        return binding

    async def resume(self, request: SessionOpenSpecV1) -> _Binding:
        self.resume_requests.append(request)
        assert request.session_id is not None
        binding = _Binding(request, request.session_id)
        self.bindings.append(binding)
        return binding


def _spec(
    *,
    session_id: str | None = None,
    scope: SessionScopeV1 = SessionScopeV1.CWD,
) -> SessionOpenSpecV1:
    return SessionOpenSpecV1(
        product_id="coding",
        continuity_id="continuity-1",
        session_id=session_id,
        scope=scope,
        scope_fingerprint=FINGERPRINT,
        title="Coding session",
    )


def test_G11_PRODUCT_ADAPTER_routes_create_and_resume_with_exact_scope() -> None:
    async def scenario() -> None:
        factory = _Factory()
        resolver = CodingHostedSessionResolverV1(
            create=factory.create,
            resume=factory.resume,
        )

        created = await resolver.open_session(_spec(scope=SessionScopeV1.USER_HOME))
        resumed = await resolver.open_session(
            _spec(session_id="persisted-1", scope=SessionScopeV1.USER_HOME)
        )

        assert created.identity.scope is SessionScopeV1.USER_HOME
        assert resumed.identity.session_id == "persisted-1"
        assert factory.create_requests == [_spec(scope=SessionScopeV1.USER_HOME)]
        assert factory.resume_requests == [
            _spec(session_id="persisted-1", scope=SessionScopeV1.USER_HOME)
        ]
        await created.close()
        await resumed.close()

    _run(scenario())


def test_G11_SCOPE_COMPAT_projects_canonical_envelope_without_locator() -> None:
    envelope = SessionIdentityEnvelopeV1(
        product_id="coding",
        product_compatibility_id="coding-v1",
        continuity_id="continuity-1",
        session_id="session-1",
        provider_id="jsonl",
        locator_token="private-locator",
    )

    cwd = coding_hosted_identity_from_envelope(
        envelope,
        discovery_scope=SessionDiscoveryScope.CURRENT_DIRECTORY,
        scope_fingerprint=FINGERPRINT,
    )
    user = coding_hosted_identity_from_envelope(
        envelope,
        discovery_scope=SessionDiscoveryScope.USER_GLOBAL_LEGACY,
        scope_fingerprint=FINGERPRINT,
    )

    assert cwd.scope is SessionScopeV1.CWD
    assert user.scope is SessionScopeV1.USER_HOME
    assert "private-locator" not in repr(cwd)


def test_G11_PRODUCT_ADAPTER_projects_events_and_forwards_public_controls() -> None:
    async def scenario() -> None:
        factory = _Factory()
        resolver = CodingHostedSessionResolverV1(
            create=factory.create,
            resume=factory.resume,
        )
        session = await resolver.open_session(_spec())
        events = []
        session.subscribe(events.append)

        snapshot = await session.snapshot()
        await session.start_turn("go")
        session.steer_turn("steer")
        session.follow_up_turn("follow")
        assert session.interrupt_turn() is True
        assert await session.respond_interaction(
            "interaction-1",
            InteractionOutcomeV1.APPROVE,
        )
        await factory.bindings[0].control.emit()

        assert snapshot.cursor == 0
        assert snapshot.records[0].text == "hello"
        assert [(event.cursor, event.text) for event in events] == [(1, "projected")]
        assert factory.bindings[0].control.calls[:5] == [
            ("prompt", ("go", {"streaming_behavior": None, "source": "appservice"})),
            ("idle", ""),
            ("steer", "steer"),
            ("follow_up", "follow"),
            ("abort", ""),
        ]
        assert factory.bindings[0].interactions == [
            ("interaction-1", "allow_once")
        ]
        await session.close()
        assert factory.bindings[0].control.calls[-1] == ("unsubscribe", "")
        assert factory.bindings[0].closed == 1

    _run(scenario())


def test_G11_PRODUCT_ADAPTER_runs_through_appservice_without_product_imports() -> None:
    async def scenario() -> None:
        factory = _Factory()
        resolver = CodingHostedSessionResolverV1(
            create=factory.create,
            resume=factory.resume,
        )
        service = AppServiceV1(
            product_id="coding",
            resolver=resolver,
            id_factory=iter((f"id-{index}" for index in range(1, 20))).__next__,
        )
        client = InProcessAppClientV1(service)
        await client.create_mux(MuxCreateV1("dev"))
        mux = await client.open_member(
            MuxMemberOpenV1(MuxSelectorV1(name="dev"), _spec())
        )
        attachment = await client.attach_mux(
            MuxAttachV1(MuxSelectorV1(name="dev"))
        )

        await client.start_turn(
            TurnTextV1(
                attachment.attachment_id,
                attachment.controller_generation,
                mux.members[0].member_id,
                "go",
            )
        )
        await factory.bindings[0].control.emit()
        events = await client.read_events(
            attachment_id=attachment.attachment_id,
            controller_generation=attachment.controller_generation,
        )

        assert events[0].event.kind is SessionEventKindV1.ASSISTANT_MESSAGE
        assert events[0].member_id == mux.members[0].member_id
        await service.close()
        assert factory.bindings[0].closed == 1

    _run(scenario())


def test_event_projection_failures_are_redacted_and_ignored_events_keep_cursor(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        factory = _Factory()
        resolver = CodingHostedSessionResolverV1(
            create=factory.create, resume=factory.resume,
        )
        session = await resolver.open_session(_spec())
        binding = factory.bindings[0]
        events = []
        session.subscribe(events.append)
        try:
            await binding.control.emit("ignored")
            assert events == []

            def failed_projection(event):
                raise RuntimeError("private projection detail")

            monkeypatch.setattr(binding, "project_event", failed_projection)
            await binding.control.emit()
            monkeypatch.setattr(binding, "project_event", lambda event: object())
            await binding.control.emit()
            assert [(event.cursor, event.kind, event.text) for event in events] == [
                (1, SessionEventKindV1.ERROR, "event_projection_unavailable"),
                (2, SessionEventKindV1.ERROR, "event_projection_unavailable"),
            ]
        finally:
            await session.close()

    _run(scenario())


def test_interaction_outcomes_map_to_existing_harness_approval_vocabulary() -> None:
    async def scenario() -> None:
        factory = _Factory()
        resolver = CodingHostedSessionResolverV1(
            create=factory.create,
            resume=factory.resume,
        )
        session = await resolver.open_session(_spec())

        for outcome in InteractionOutcomeV1:
            assert await session.respond_interaction("interaction-1", outcome)

        assert factory.bindings[0].interactions == [
            ("interaction-1", "allow_once"),
            ("interaction-1", "deny"),
            ("interaction-1", "abort"),
        ]
        await session.close()

    _run(scenario())


def test_product_close_failure_fences_operations_and_retains_retry_authority() -> None:
    async def scenario() -> None:
        factory = _Factory()
        resolver = CodingHostedSessionResolverV1(
            create=factory.create,
            resume=factory.resume,
        )
        session = await resolver.open_session(_spec())
        factory.bindings[0].fail_close = 1

        try:
            await session.close()
        except RuntimeError as error:
            assert str(error) == "sentinel close failure"
        else:
            raise AssertionError("first close must fail")

        assert session.closed is True
        try:
            await session.start_turn("denied")
        except RuntimeError as error:
            assert str(error) == "coding_hosted_session_closed"
        else:
            raise AssertionError("closed Session must reject operations")
        await session.close()
        assert factory.bindings[0].closed == 2

    _run(scenario())
