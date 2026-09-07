from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from pathlib import Path

import pytest

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxAttachV1,
    MuxCloseV1,
    MuxCreateV1,
    MuxDetachV1,
    MuxMemberCloseV1,
    MuxMemberOpenV1,
    MuxReadV1,
    MuxSelectorV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotV1,
)
from loushang.appservice import (
    ApplicationContinuityError,
    ApplicationContinuityErrorCodeV1,
    ApplicationContinuityRecordV1,
    AppServiceRecoveryRequestV1,
    JsonFileApplicationContinuityStoreV1,
    MuxMemberContinuityV1,
    MuxSpaceContinuityV1,
    create_appservice_recovery_attempt,
)

_FINGERPRINT = "a" * 64


def _async_test(
    function: Callable[..., Awaitable[None]],
) -> Callable[..., None]:
    @wraps(function)
    def wrapper(*args: object, **kwargs: object) -> None:
        asyncio.run(function(*args, **kwargs))

    return wrapper


class _Session:
    def __init__(
        self,
        identity: SessionIdentityV1,
        events: list[str],
        *,
        fail_close_once: bool = False,
    ) -> None:
        self.identity = identity
        self._events = events
        self._fail_close_once = fail_close_once

    async def snapshot(self) -> SessionSnapshotV1:
        return SessionSnapshotV1(self.identity, "Session", 0, 0, False)

    def subscribe(self, listener: object) -> Callable[[], None]:
        del listener
        return lambda: None

    async def start_turn(self, text: str) -> None:
        del text

    def steer_turn(self, text: str) -> None:
        del text

    def follow_up_turn(self, text: str) -> None:
        del text

    def interrupt_turn(self) -> bool:
        return False

    async def respond_interaction(self, interaction_id: str, outcome: object) -> bool:
        del interaction_id, outcome
        return False

    async def close(self) -> None:
        self._events.append(f"close:{self.identity.session_id}")
        if self._fail_close_once:
            self._fail_close_once = False
            raise RuntimeError("hidden")


class _Resolver:
    def __init__(
        self,
        events: list[str],
        *,
        fail_session_id: str | None = None,
        mismatch_session_id: str | None = None,
        fail_close_once: bool = False,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.events = events
        self.requests: list[SessionOpenSpecV1] = []
        self.sessions: list[_Session] = []
        self.fail_session_id = fail_session_id
        self.mismatch_session_id = mismatch_session_id
        self.fail_close_once = fail_close_once
        self.gate = gate
        self.counter = 0

    async def open_session(self, request: SessionOpenSpecV1) -> _Session:
        self.requests.append(request)
        if self.gate is not None:
            await self.gate.wait()
        if (
            self.fail_session_id is not None
            and request.session_id == self.fail_session_id
        ):
            raise RuntimeError("hidden")
        self.counter += 1
        session_id = request.session_id or f"session-{self.counter}"
        if (
            self.mismatch_session_id is not None
            and request.session_id == self.mismatch_session_id
        ):
            session_id = "wrong-session"
        identity = SessionIdentityV1(
            request.product_id,
            request.continuity_id,
            session_id,
            request.scope,
            request.scope_fingerprint,
        )
        session = _Session(
            identity,
            self.events,
            fail_close_once=self.fail_close_once,
        )
        self.fail_close_once = False
        self.sessions.append(session)
        return session


class _BrokenSession(_Session):
    def subscribe(self, listener: object) -> Callable[[], None]:
        del listener
        raise RuntimeError("hidden")


class _BrokenResolver:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.fail_close_once = True

    async def open_session(self, request: SessionOpenSpecV1) -> _Session:
        identity = SessionIdentityV1(
            request.product_id,
            request.continuity_id,
            request.session_id or "session-new",
            request.scope,
            request.scope_fingerprint,
        )
        session = _BrokenSession(
            identity,
            self.events,
            fail_close_once=self.fail_close_once,
        )
        self.fail_close_once = False
        return session


class _MemoryLease:
    def __init__(
        self,
        record: ApplicationContinuityRecordV1 | None = None,
        *,
        commit_error: ApplicationContinuityErrorCodeV1 | None = None,
        commit_gate: asyncio.Event | None = None,
        load_error: bool = False,
    ) -> None:
        self.application_id = "coding.default"
        self.owner_epoch = "epoch-1"
        self.record = record
        self.commit_error = commit_error
        self.commit_gate = commit_gate
        self.load_error = load_error
        self.commits: list[ApplicationContinuityRecordV1] = []
        self.closed = False

    async def load(self) -> ApplicationContinuityRecordV1 | None:
        if self.load_error:
            raise RuntimeError("hidden")
        return self.record

    async def commit(
        self,
        *,
        expected_revision: int | None,
        record: ApplicationContinuityRecordV1,
    ) -> None:
        if self.commit_gate is not None:
            await self.commit_gate.wait()
        if self.commit_error is not None:
            raise ApplicationContinuityError(self.commit_error)
        current = None if self.record is None else self.record.record_revision
        if current != expected_revision:
            raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CONFLICT)
        self.record = record
        self.commits.append(record)

    async def delete(self, *, expected_revision: int) -> None:
        if self.record is None or self.record.record_revision != expected_revision:
            raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CONFLICT)
        self.record = None

    async def close(self) -> None:
        self.closed = True


def _identity(session_id: str) -> SessionIdentityV1:
    return SessionIdentityV1(
        "coding",
        "continuity-1",
        session_id,
        SessionScopeV1.CWD,
        _FINGERPRINT,
    )


def _record(*session_ids: str) -> ApplicationContinuityRecordV1:
    members = tuple(
        MuxMemberContinuityV1(
            f"member-{index}",
            f"Session {index}",
            index,
            _identity(session_id),
        )
        for index, session_id in enumerate(session_ids, 1)
    )
    return ApplicationContinuityRecordV1(
        "coding.default",
        "coding",
        1,
        (MuxSpaceContinuityV1("mux-1", "dev", len(members) + 1, members),),
    )


async def _recover(
    lease: object,
    resolver: _Resolver,
    *,
    ids: tuple[str, ...] = ("mux-new", "member-new", "attachment-new"),
):  # type: ignore[no-untyped-def]
    iterator = iter(ids)
    attempt = create_appservice_recovery_attempt(
        AppServiceRecoveryRequestV1(
            product_id="coding",
            resolver=resolver,
            continuity_lease=lease,  # type: ignore[arg-type]
            id_factory=lambda: next(iterator),
        )
    )
    return attempt, await attempt.open()


@_async_test
async def test_G13_CANONICAL_RECOVERY_restores_complete_mux_and_sessions() -> None:
    events: list[str] = []
    resolver = _Resolver(events)
    lease = _MemoryLease(_record("session-1", "session-2"))

    attempt, service = await _recover(lease, resolver)

    muxes = await service.list_muxes()
    assert len(muxes.mux_spaces) == 1
    mux = muxes.mux_spaces[0]
    assert (mux.mux_space_id, mux.name, mux.revision) == ("mux-1", "dev", 3)
    assert tuple(member.session.session_id for member in mux.members) == (
        "session-1",
        "session-2",
    )
    assert tuple(request.session_id for request in resolver.requests) == (
        "session-1",
        "session-2",
    )
    assert service.continuity_revision == 1
    await service.close()
    await attempt.close()


@_async_test
async def test_G13_ALL_OR_NOTHING_rejects_mismatch_and_closes_every_owner() -> None:
    events: list[str] = []
    resolver = _Resolver(events, mismatch_session_id="session-2")
    lease = _MemoryLease(_record("session-1", "session-2"))
    attempt = create_appservice_recovery_attempt(
        AppServiceRecoveryRequestV1("coding", resolver, lease)
    )

    with pytest.raises(AppServiceError) as caught:
        await attempt.open()

    assert caught.value.code is AppErrorCodeV1.PRODUCT_MISMATCH
    assert sorted(events) == ["close:session-1", "close:wrong-session"]
    assert attempt.cleanup_pending is False
    await attempt.close()


@_async_test
async def test_G13_ALL_OR_NOTHING_retains_retryable_cleanup_debt() -> None:
    events: list[str] = []
    resolver = _Resolver(
        events,
        mismatch_session_id="session-1",
        fail_close_once=True,
    )
    lease = _MemoryLease(_record("session-1"))
    attempt = create_appservice_recovery_attempt(
        AppServiceRecoveryRequestV1("coding", resolver, lease)
    )

    with pytest.raises(AppServiceError) as caught:
        await attempt.open()
    assert caught.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
    assert attempt.cleanup_pending is True

    await attempt.close()
    assert events == ["close:wrong-session", "close:wrong-session"]
    assert attempt.cleanup_pending is False


@_async_test
async def test_G13_ALL_OR_NOTHING_retains_unadapted_port_cleanup_debt() -> None:
    events: list[str] = []
    resolver = _BrokenResolver(events)
    lease = _MemoryLease(_record("session-1"))
    attempt = create_appservice_recovery_attempt(
        AppServiceRecoveryRequestV1("coding", resolver, lease)
    )

    with pytest.raises(AppServiceError) as caught:
        await attempt.open()

    assert caught.value.code is AppErrorCodeV1.CLEANUP_INCOMPLETE
    assert attempt.cleanup_pending is True
    await attempt.close()
    assert events == ["close:session-1", "close:session-1"]
    assert attempt.cleanup_pending is False


@_async_test
async def test_G13_ALL_OR_NOTHING_redacts_unexpected_store_failure() -> None:
    attempt = create_appservice_recovery_attempt(
        AppServiceRecoveryRequestV1(
            "coding", _Resolver([]), _MemoryLease(load_error=True)
        )
    )

    with pytest.raises(AppServiceError) as caught:
        await attempt.open()

    assert caught.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
    assert str(caught.value) == AppErrorCodeV1.OPERATION_UNAVAILABLE.value
    await attempt.close()


@_async_test
async def test_G13_ALL_OR_NOTHING_close_wins_race_before_publication() -> None:
    events: list[str] = []
    gate = asyncio.Event()
    attempt = create_appservice_recovery_attempt(
        AppServiceRecoveryRequestV1(
            "coding",
            _Resolver(events, gate=gate),
            _MemoryLease(_record("session-1")),
        )
    )
    open_task = asyncio.create_task(attempt.open())
    await asyncio.sleep(0)
    close_task = asyncio.create_task(attempt.close())
    await asyncio.sleep(0)
    gate.set()

    await close_task
    with pytest.raises(AppServiceError) as caught:
        await open_task

    assert caught.value.code is AppErrorCodeV1.SERVICE_CLOSED
    assert events == ["close:session-1"]
    assert attempt.cleanup_pending is False


@_async_test
async def test_G13_ATOMIC_MUTATION_persists_all_mux_member_transitions() -> None:
    events: list[str] = []
    resolver = _Resolver(events)
    lease = _MemoryLease()
    _attempt, service = await _recover(lease, resolver)

    mux = await service.create_mux(MuxCreateV1("dev"))
    assert lease.record is not None
    assert lease.record.record_revision == 1
    opened = await service.open_member(
        MuxMemberOpenV1(
            MuxSelectorV1(mux_space_id=mux.mux_space_id),
            SessionOpenSpecV1(
                "coding",
                "continuity-1",
                SessionScopeV1.CWD,
                _FINGERPRINT,
                "Session",
            ),
        )
    )
    assert lease.record.record_revision == 2
    assert lease.record.mux_spaces[0].members[0].session.session_id == "session-1"

    attachment = await service.attach_mux(
        MuxAttachV1(MuxSelectorV1(mux_space_id=mux.mux_space_id))
    )
    await service.detach_mux(
        MuxDetachV1(
            attachment.attachment_id,
            attachment.controller_generation,
        )
    )
    assert lease.record.record_revision == 2
    assert events == []

    with pytest.raises(AppServiceError) as orphaned:
        await service.close_member(
            MuxMemberCloseV1(
                MuxSelectorV1(mux_space_id=mux.mux_space_id),
                opened.members[0].member_id,
                close_session=False,
            )
        )
    assert orphaned.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
    assert lease.record.record_revision == 2

    await service.close_member(
        MuxMemberCloseV1(
            MuxSelectorV1(mux_space_id=mux.mux_space_id),
            opened.members[0].member_id,
        )
    )
    assert lease.record.record_revision == 3
    assert lease.record.mux_spaces[0].members == ()
    await service.close_mux(MuxCloseV1(MuxSelectorV1(name="dev")))
    assert lease.record.record_revision == 4
    assert lease.record.mux_spaces == ()
    assert service.continuity_revision == 4
    await service.close()


@_async_test
async def test_G13_ATOMIC_MUTATION_store_failure_changes_no_live_state() -> None:
    events: list[str] = []
    resolver = _Resolver(events)
    lease = _MemoryLease(commit_error=ApplicationContinuityErrorCodeV1.UNAVAILABLE)
    _attempt, service = await _recover(lease, resolver)

    with pytest.raises(AppServiceError) as caught:
        await service.create_mux(MuxCreateV1("dev"))

    assert caught.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
    assert (await service.list_muxes()).mux_spaces == ()
    assert service.continuity_revision is None
    await service.close()


@_async_test
async def test_G13_ATOMIC_MUTATION_failed_member_commit_compensates_owner() -> None:
    events: list[str] = []
    resolver = _Resolver(events)
    lease = _MemoryLease()
    _attempt, service = await _recover(lease, resolver)
    mux = await service.create_mux(MuxCreateV1("dev"))
    lease.commit_error = ApplicationContinuityErrorCodeV1.UNAVAILABLE

    with pytest.raises(AppServiceError) as caught:
        await service.open_member(
            MuxMemberOpenV1(
                MuxSelectorV1(mux_space_id=mux.mux_space_id),
                SessionOpenSpecV1(
                    "coding",
                    "continuity-1",
                    SessionScopeV1.CWD,
                    _FINGERPRINT,
                    "Session",
                ),
            )
        )

    assert caught.value.code is AppErrorCodeV1.OPERATION_UNAVAILABLE
    assert events == ["close:session-1"]
    assert (await service.read_mux(MuxReadV1(MuxSelectorV1(name="dev")))).members == ()
    assert lease.record is not None and lease.record.record_revision == 1
    await service.close()


@_async_test
async def test_G13_ATOMIC_MUTATION_cancellation_finishes_commit_and_publish() -> None:
    events: list[str] = []
    resolver = _Resolver(events)
    gate = asyncio.Event()
    lease = _MemoryLease(commit_gate=gate)
    _attempt, service = await _recover(lease, resolver)
    task = asyncio.create_task(service.create_mux(MuxCreateV1("dev")))
    await asyncio.sleep(0)
    task.cancel()
    gate.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert lease.record is not None
    assert tuple(mux.name for mux in (await service.list_muxes()).mux_spaces) == (
        "dev",
    )
    await service.close()


@_async_test
async def test_G13_RESTART_CANARY_reopens_file_record_after_service_loss(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    store = JsonFileApplicationContinuityStoreV1(tmp_path / "continuity")
    first_lease = await store.acquire(
        application_id="coding.default",
        owner_epoch="epoch-1",
    )
    first_resolver = _Resolver(events)
    _first_attempt, first = await _recover(first_lease, first_resolver)
    mux = await first.create_mux(MuxCreateV1("dev"))
    opened = await first.open_member(
        MuxMemberOpenV1(
            MuxSelectorV1(mux_space_id=mux.mux_space_id),
            SessionOpenSpecV1(
                "coding",
                "continuity-1",
                SessionScopeV1.CWD,
                _FINGERPRINT,
                "Session",
            ),
        )
    )
    await first.close()

    second_store = JsonFileApplicationContinuityStoreV1(tmp_path / "continuity")
    with pytest.raises(ApplicationContinuityError) as locked:
        await second_store.acquire(
            application_id="coding.default",
            owner_epoch="epoch-2",
        )
    assert locked.value.code is ApplicationContinuityErrorCodeV1.LOCKED
    await first_lease.close()

    second_lease = await second_store.acquire(
        application_id="coding.default",
        owner_epoch="epoch-2",
    )
    second_resolver = _Resolver(events)
    _second_attempt, second = await _recover(second_lease, second_resolver)

    recovered = (await second.list_muxes()).mux_spaces[0]
    assert recovered.name == "dev"
    assert recovered.members == opened.members
    assert second_resolver.requests[0].session_id == "session-1"
    await second.close()
    await second_lease.close()


@_async_test
async def test_G13_FRESH_AUTHORITY_epoch_fences_replayed_live_ids() -> None:
    events: list[str] = []
    first_lease = _MemoryLease(_record("session-1"))
    first = create_appservice_recovery_attempt(
        AppServiceRecoveryRequestV1(
            "coding",
            _Resolver(events),
            first_lease,
            id_factory=lambda: "replayed-id",
        )
    )
    first_service = await first.open()
    first_attachment = await first_service.attach_mux(
        MuxAttachV1(MuxSelectorV1(name="dev"))
    )
    await first_service.close()

    second_lease = _MemoryLease(first_lease.record)
    second_lease.owner_epoch = "epoch-2"
    second = create_appservice_recovery_attempt(
        AppServiceRecoveryRequestV1(
            "coding",
            _Resolver(events),
            second_lease,
            id_factory=lambda: "replayed-id",
        )
    )
    second_service = await second.open()
    second_attachment = await second_service.attach_mux(
        MuxAttachV1(MuxSelectorV1(name="dev"))
    )

    assert second_attachment.attachment_id != first_attachment.attachment_id
    with pytest.raises(AppServiceError) as stale:
        await second_service.detach_mux(
            MuxDetachV1(
                first_attachment.attachment_id,
                first_attachment.controller_generation,
            )
        )
    assert stale.value.code is AppErrorCodeV1.STALE_ATTACHMENT
    await second_service.close()
