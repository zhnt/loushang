from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from functools import wraps

import pytest

from loushang.appserver.client import AppClientV1
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InteractionOutcomeV1,
    InteractionRespondV1,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSelectorV1,
    SessionEventKindV1,
    SessionEventV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotRequestV1,
    SessionSnapshotV1,
    TranscriptRecordV1,
    TurnInterruptV1,
    TurnTextV1,
)
from loushang.appservice import AppServiceV1, InProcessAppClientV1

FINGERPRINT = "b" * 64
EventListener = Callable[[SessionEventV1], Awaitable[None] | None]


def _async_test(
    function: Callable[[], Awaitable[None]],
) -> Callable[[], None]:
    @wraps(function)
    def wrapper() -> None:
        asyncio.run(function())

    return wrapper


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"id-{self.value}"


class _FakeSession:
    def __init__(self, identity: SessionIdentityV1, title: str) -> None:
        self._identity = identity
        self.title = title
        self.cursor = 0
        self.revision = 0
        self.records: list[TranscriptRecordV1] = []
        self.listener: EventListener | None = None
        self.snapshot_entered: asyncio.Event | None = None
        self.snapshot_release: asyncio.Event | None = None
        self.turn_entered: asyncio.Event | None = None
        self.turn_release: asyncio.Event | None = None
        self.calls: list[tuple[str, object]] = []
        self.closed = 0

    @property
    def identity(self) -> SessionIdentityV1:
        return self._identity

    async def snapshot(self) -> SessionSnapshotV1:
        cursor = self.cursor
        revision = self.revision
        records = tuple(self.records)
        if self.snapshot_entered is not None:
            self.snapshot_entered.set()
        if self.snapshot_release is not None:
            await self.snapshot_release.wait()
        return SessionSnapshotV1(
            identity=self.identity,
            title=self.title,
            cursor=cursor,
            revision=revision,
            running=False,
            records=records,
        )

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        assert self.listener is None
        self.listener = listener

        def unsubscribe() -> None:
            self.calls.append(("unsubscribe", ""))
            self.listener = None

        return unsubscribe

    async def emit(
        self,
        kind: SessionEventKindV1 = SessionEventKindV1.STATUS,
        text: str = "event",
        *,
        cursor: int | None = None,
    ) -> None:
        self.cursor = self.cursor + 1 if cursor is None else cursor
        event = SessionEventV1(
            session_id=self.identity.session_id,
            cursor=self.cursor,
            kind=kind,
            text=text,
        )
        listener = self.listener
        if listener is not None:
            result = listener(event)
            if result is not None:
                await result

    async def start_turn(self, text: str) -> None:
        self.calls.append(("start", text))
        if self.turn_entered is not None:
            self.turn_entered.set()
        if self.turn_release is not None:
            await self.turn_release.wait()

    def steer_turn(self, text: str) -> None:
        self.calls.append(("steer", text))

    def follow_up_turn(self, text: str) -> None:
        self.calls.append(("follow_up", text))

    def interrupt_turn(self) -> bool:
        self.calls.append(("interrupt", ""))
        return True

    async def respond_interaction(
        self,
        interaction_id: str,
        outcome: InteractionOutcomeV1,
    ) -> bool:
        self.calls.append(("interaction", (interaction_id, outcome)))
        return True

    async def close(self) -> None:
        self.closed += 1
        self.calls.append(("close", ""))


class _Resolver:
    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []
        self.requests: list[SessionOpenSpecV1] = []
        self.block_title: str | None = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def open_session(self, request: SessionOpenSpecV1) -> _FakeSession:
        self.requests.append(request)
        if request.title == self.block_title:
            self.entered.set()
            await self.release.wait()
        session_id = request.session_id or f"session-{len(self.sessions) + 1}"
        session = _FakeSession(
            SessionIdentityV1(
                product_id=request.product_id,
                continuity_id=request.continuity_id,
                session_id=session_id,
                scope=request.scope,
                scope_fingerprint=request.scope_fingerprint,
            ),
            request.title,
        )
        self.sessions.append(session)
        return session


def _spec(
    title: str = "one",
    *,
    session_id: str | None = None,
    scope: SessionScopeV1 = SessionScopeV1.CWD,
) -> SessionOpenSpecV1:
    return SessionOpenSpecV1(
        product_id="coding",
        continuity_id=f"continuity-{title}",
        session_id=session_id,
        scope=scope,
        scope_fingerprint=FINGERPRINT,
        title=title,
    )


async def _service() -> tuple[AppServiceV1, InProcessAppClientV1, _Resolver]:
    resolver = _Resolver()
    service = AppServiceV1(product_id="coding", resolver=resolver, id_factory=_Ids())
    return service, InProcessAppClientV1(service), resolver


async def _mux_with_member(
    client: InProcessAppClientV1,
    *,
    name: str = "dev",
    title: str = "one",
) -> tuple[object, object]:
    mux = await client.create_mux(MuxCreateV1(name))
    mux = await client.open_member(
        MuxMemberOpenV1(MuxSelectorV1(name=name), _spec(title))
    )
    return mux, mux.members[0]


@_async_test
async def test_G11_MUX_IDENTITY_create_list_open_and_unique_name() -> None:
    service, client, resolver = await _service()

    mux, member = await _mux_with_member(client)

    assert mux.name == "dev"
    assert mux.revision == 2
    assert member.position == 1
    assert member.session.product_id == "coding"
    assert (await client.list_muxes()).mux_spaces == (mux,)
    assert await client.read_mux(MuxReadV1(MuxSelectorV1(name="dev"))) == mux
    with pytest.raises(AppServiceError) as duplicate:
        await client.create_mux(MuxCreateV1("dev"))
    assert duplicate.value.code is AppErrorCodeV1.ALREADY_EXISTS
    assert resolver.requests == [_spec()]
    await service.close()


@_async_test
async def test_G11_ATTACH_BARRIER_delivers_only_events_after_snapshot_cursor() -> None:
    service, client, resolver = await _service()
    _mux, _member = await _mux_with_member(client)
    session = resolver.sessions[0]
    session.snapshot_entered = asyncio.Event()
    session.snapshot_release = asyncio.Event()

    attach_task = asyncio.create_task(
        client.attach_mux(MuxAttachV1(MuxSelectorV1(name="dev")))
    )
    await session.snapshot_entered.wait()
    await session.emit(text="after barrier")
    session.snapshot_release.set()
    attachment = await attach_task

    assert attachment.sessions[0].snapshot.cursor == 0
    events = await client.read_events(
        attachment_id=attachment.attachment_id,
        controller_generation=attachment.controller_generation,
    )
    assert [item.event.text for item in events] == ["after barrier"]
    await service.close()


@_async_test
async def test_G11_ATTACH_BARRIER_membership_change_returns_typed_conflict() -> None:
    service, client, resolver = await _service()
    await _mux_with_member(client)
    session = resolver.sessions[0]
    session.snapshot_entered = asyncio.Event()
    session.snapshot_release = asyncio.Event()

    attach_task = asyncio.create_task(
        client.attach_mux(MuxAttachV1(MuxSelectorV1(name="dev")))
    )
    await session.snapshot_entered.wait()
    await client.open_member(
        MuxMemberOpenV1(MuxSelectorV1(name="dev"), _spec("two"))
    )
    session.snapshot_release.set()

    with pytest.raises(AppServiceError) as conflict:
        await attach_task
    assert conflict.value.code is AppErrorCodeV1.REVISION_CONFLICT
    await service.close()


@_async_test
async def test_G11_MAILBOX_BOUND_isolates_one_lagged_attachment() -> None:
    service, client, resolver = await _service()
    await _mux_with_member(client)
    first = await client.attach_mux(
        MuxAttachV1(MuxSelectorV1(name="dev"), mailbox_capacity=8)
    )
    second = await client.attach_mux(
        MuxAttachV1(MuxSelectorV1(name="dev"), mailbox_capacity=32)
    )

    for index in range(9):
        await resolver.sessions[0].emit(text=f"event-{index}")

    with pytest.raises(AppServiceError) as lagged:
        await client.read_events(
            attachment_id=first.attachment_id,
            controller_generation=first.controller_generation,
        )
    assert lagged.value.code is AppErrorCodeV1.ATTACHMENT_LAGGED
    second_events = await client.read_events(
        attachment_id=second.attachment_id,
        controller_generation=second.controller_generation,
    )
    assert len(second_events) == 9
    await service.close()


@_async_test
async def test_G11_AGGREGATE_CONCURRENCY_blocked_product_open_does_not_lock_muxes() -> None:
    service, client, resolver = await _service()
    await client.create_mux(MuxCreateV1("one"))
    await client.create_mux(MuxCreateV1("two"))
    resolver.block_title = "blocked"

    blocked = asyncio.create_task(
        client.open_member(
            MuxMemberOpenV1(MuxSelectorV1(name="one"), _spec("blocked"))
        )
    )
    await resolver.entered.wait()
    second = await asyncio.wait_for(
        client.open_member(
            MuxMemberOpenV1(MuxSelectorV1(name="two"), _spec("free"))
        ),
        timeout=0.2,
    )

    assert second.members[0].title == "free"
    resolver.release.set()
    await blocked
    await service.close()


@_async_test
async def test_G11_operations_forward_only_after_attachment_generation_fence() -> None:
    service, client, resolver = await _service()
    _mux, member = await _mux_with_member(client)
    attachment = await client.attach_mux(MuxAttachV1(MuxSelectorV1(name="dev")))
    prefix = (attachment.attachment_id, attachment.controller_generation, member.member_id)

    await client.start_turn(TurnTextV1(*prefix, "start"))
    await client.steer_turn(TurnTextV1(*prefix, "steer"))
    await client.follow_up_turn(TurnTextV1(*prefix, "follow"))
    await client.interrupt_turn(TurnInterruptV1(*prefix))
    await client.respond_interaction(
        InteractionRespondV1(
            *prefix,
            "interaction-1",
            InteractionOutcomeV1.DENY,
        )
    )
    snapshot = await client.snapshot_session(SessionSnapshotRequestV1(*prefix))

    assert snapshot.identity == member.session
    assert resolver.sessions[0].calls[:5] == [
        ("start", "start"),
        ("steer", "steer"),
        ("follow_up", "follow"),
        ("interrupt", ""),
        ("interaction", ("interaction-1", InteractionOutcomeV1.DENY)),
    ]
    with pytest.raises(AppServiceError) as stale:
        await client.start_turn(
            TurnTextV1(attachment.attachment_id, 999, member.member_id, "denied")
        )
    assert stale.value.code is AppErrorCodeV1.STALE_ATTACHMENT
    await service.close()


@_async_test
async def test_G11_CLOSE_ORDER_detach_does_not_close_mux_or_session() -> None:
    service, client, resolver = await _service()
    mux, _member = await _mux_with_member(client)
    attachment = await client.attach_mux(MuxAttachV1(MuxSelectorV1(name="dev")))

    await client.detach_mux(
        MuxDetachV1(attachment.attachment_id, attachment.controller_generation)
    )

    assert resolver.sessions[0].closed == 0
    assert (await client.read_mux(MuxReadV1(MuxSelectorV1(name="dev")))) == mux
    with pytest.raises(AppServiceError) as stale:
        await client.read_events(
            attachment_id=attachment.attachment_id,
            controller_generation=attachment.controller_generation,
        )
    assert stale.value.code is AppErrorCodeV1.STALE_ATTACHMENT
    await service.close()
    assert resolver.sessions[0].closed == 1


@_async_test
async def test_G11_CLOSE_ORDER_member_remove_and_session_close_are_separate() -> None:
    service, client, resolver = await _service()
    _mux, member = await _mux_with_member(client)

    empty = await client.close_member(
        MuxMemberCloseV1(
            MuxSelectorV1(name="dev"),
            member.member_id,
            close_session=False,
        )
    )

    assert empty.members == ()
    assert resolver.sessions[0].closed == 0
    await service.close()
    assert resolver.sessions[0].closed == 1


@_async_test
async def test_G11_CLOSE_ORDER_mux_close_settles_attachments_then_sessions() -> None:
    service, client, resolver = await _service()
    await _mux_with_member(client)
    attachment = await client.attach_mux(MuxAttachV1(MuxSelectorV1(name="dev")))

    await client.close_mux(MuxCloseV1(MuxSelectorV1(name="dev")))

    assert resolver.sessions[0].calls[-2:] == [("unsubscribe", ""), ("close", "")]
    assert resolver.sessions[0].closed == 1
    with pytest.raises(AppServiceError) as missing:
        await client.read_events(
            attachment_id=attachment.attachment_id,
            controller_generation=attachment.controller_generation,
        )
    assert missing.value.code is AppErrorCodeV1.STALE_ATTACHMENT
    await service.close()


@_async_test
async def test_G11_SCOPE_COMPAT_create_and_resume_preserve_scope_identity() -> None:
    service, client, resolver = await _service()
    await client.create_mux(MuxCreateV1("dev"))
    created = await client.open_member(
        MuxMemberOpenV1(
            MuxSelectorV1(name="dev"),
            _spec("home", scope=SessionScopeV1.USER_HOME),
        )
    )
    await client.close_member(
        MuxMemberCloseV1(
            MuxSelectorV1(name="dev"),
            created.members[0].member_id,
        )
    )
    resumed = await client.open_member(
        MuxMemberOpenV1(
            MuxSelectorV1(name="dev"),
            _spec(
                "home",
                session_id=created.members[0].session.session_id,
                scope=SessionScopeV1.USER_HOME,
            ),
        )
    )

    assert resumed.members[0].session == created.members[0].session
    assert resolver.requests[-1].session_id == created.members[0].session.session_id
    await service.close()


@_async_test
async def test_product_mismatch_fails_before_resolver_effect() -> None:
    service, client, resolver = await _service()
    await client.create_mux(MuxCreateV1("dev"))
    request = MuxMemberOpenV1(
        MuxSelectorV1(name="dev"),
        replace(_spec(), product_id="design"),
    )

    with pytest.raises(AppServiceError) as mismatch:
        await client.open_member(request)

    assert mismatch.value.code is AppErrorCodeV1.PRODUCT_MISMATCH
    assert resolver.requests == []
    await service.close()


def test_in_process_client_satisfies_transport_neutral_contract() -> None:
    assert AppClientV1.__name__ == "AppClientV1"
    for method in (
        "create_mux",
        "list_muxes",
        "read_mux",
        "attach_mux",
        "detach_mux",
        "close_mux",
        "open_member",
        "close_member",
        "snapshot_session",
        "start_turn",
        "steer_turn",
        "follow_up_turn",
        "interrupt_turn",
        "respond_interaction",
        "read_events",
    ):
        assert callable(getattr(InProcessAppClientV1, method))
