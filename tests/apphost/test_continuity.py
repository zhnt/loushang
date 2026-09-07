from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps

import pytest

from loushang.apphost import AppHostShutdownBudgetV1, AppHostShutdownReportV1
from loushang.apphost.application import (
    HostedApplicationActivationV1,
    HostedApplicationError,
    HostedApplicationRequestV1,
)
from loushang.apphost.continuity import (
    HostedApplicationContinuityActivationV1,
    HostedApplicationContinuityPhase,
    HostedApplicationContinuityRequestV1,
    HostedApplicationContinuityRuntimeV1,
    create_hosted_application_continuity_attempt,
)
from loushang.appserver.protocol import (
    AppServiceError,
    MuxListResultV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotV1,
)
from loushang.appservice import (
    ApplicationContinuityError,
    ApplicationContinuityErrorCodeV1,
    ApplicationContinuityRecordV1,
    ApplicationContinuitySummaryV1,
    MuxMemberContinuityV1,
    MuxSpaceContinuityV1,
)

_FINGERPRINT = "a" * 64


def _async_test(
    function: Callable[[], Awaitable[None]],
) -> Callable[[], None]:
    @wraps(function)
    def wrapper() -> None:
        asyncio.run(function())

    return wrapper


class _Session:
    def __init__(
        self,
        events: list[str],
        *,
        session_id: str = "session-1",
    ) -> None:
        self.identity = SessionIdentityV1(
            "coding",
            "continuity-1",
            session_id,
            SessionScopeV1.CWD,
            _FINGERPRINT,
        )
        self.events = events

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
        self.events.append("service")


class _Resolver:
    def __init__(self, events: list[str], *, mismatch: bool = False) -> None:
        self.events = events
        self.mismatch = mismatch
        self.requests: list[SessionOpenSpecV1] = []

    async def open_session(self, request: SessionOpenSpecV1) -> _Session:
        self.requests.append(request)
        return _Session(
            self.events,
            session_id="wrong-session"
            if self.mismatch
            else request.session_id or "new",
        )


class _AppHost:
    def __init__(
        self,
        events: list[str],
        *,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.events = events
        self.gate = gate

    async def shutdown(
        self,
        budget: AppHostShutdownBudgetV1,
    ) -> AppHostShutdownReportV1:
        del budget
        self.events.append("apphost")
        if self.gate is not None:
            await self.gate.wait()
        return AppHostShutdownReportV1(True, (), ())


class _Product:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def close(self) -> None:
        self.events.append("product")


class _Lease:
    def __init__(
        self,
        events: list[str],
        record: ApplicationContinuityRecordV1 | None,
        *,
        fail_delete_once: bool = False,
    ) -> None:
        self.application_id = "coding.default"
        self.owner_epoch = "epoch-1"
        self.events = events
        self.record = record
        self.fail_delete_once = fail_delete_once
        self.closed = False

    async def load(self) -> ApplicationContinuityRecordV1 | None:
        return self.record

    async def commit(
        self,
        *,
        expected_revision: int | None,
        record: ApplicationContinuityRecordV1,
    ) -> None:
        current = None if self.record is None else self.record.record_revision
        if current != expected_revision:
            raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CONFLICT)
        self.record = record

    async def delete(self, *, expected_revision: int) -> None:
        self.events.append("record.delete")
        if self.fail_delete_once:
            self.fail_delete_once = False
            raise ApplicationContinuityError(
                ApplicationContinuityErrorCodeV1.UNAVAILABLE
            )
        if self.record is None or self.record.record_revision != expected_revision:
            raise ApplicationContinuityError(ApplicationContinuityErrorCodeV1.CONFLICT)
        self.record = None

    async def close(self) -> None:
        self.events.append("lease")
        self.closed = True


class _Store:
    def __init__(self, lease: _Lease) -> None:
        self.lease = lease
        self.acquisitions: list[tuple[str, str]] = []

    async def acquire(self, *, application_id: str, owner_epoch: str) -> _Lease:
        self.acquisitions.append((application_id, owner_epoch))
        return self.lease

    async def list_applications(
        self,
        *,
        limit: int = 128,
    ) -> tuple[ApplicationContinuitySummaryV1, ...]:
        del limit
        return ()


def _record() -> ApplicationContinuityRecordV1:
    identity = SessionIdentityV1(
        "coding",
        "continuity-1",
        "session-1",
        SessionScopeV1.CWD,
        _FINGERPRINT,
    )
    return ApplicationContinuityRecordV1(
        "coding.default",
        "coding",
        1,
        (
            MuxSpaceContinuityV1(
                "mux-1",
                "dev",
                2,
                (MuxMemberContinuityV1("member-1", "Session", 1, identity),),
            ),
        ),
    )


def _attempt(
    events: list[str],
    lease: _Lease,
    *,
    mismatch: bool = False,
    apphost: _AppHost | None = None,
):  # type: ignore[no-untyped-def]
    resolver = _Resolver(events, mismatch=mismatch)
    attempt = create_hosted_application_continuity_attempt(
        HostedApplicationContinuityRequestV1(
            activation=HostedApplicationContinuityActivationV1(),
            application=HostedApplicationRequestV1(
                activation=HostedApplicationActivationV1(),
                product_id="coding",
                generation_id="generation-current",
                apphost=apphost or _AppHost(events),
                resolver=resolver,
                product_owner=_Product(events),
                shutdown_budget=AppHostShutdownBudgetV1(1.0, 0.5),
                service_id_factory=iter(("mux-new", "member-new")).__next__,
            ),
            application_id="coding.default",
            owner_epoch="epoch-1",
            store=_Store(lease),
        )
    )
    return attempt, resolver


def test_G13_EXPLICIT_CONTINUITY_rejects_direct_runtime_construction() -> None:
    with pytest.raises(TypeError, match="requires its attempt"):
        HostedApplicationContinuityRuntimeV1(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            phase_timeout_seconds=1.0,
        )


@_async_test
async def test_G13_LEASE_OWNER_recovers_and_releases_after_g12_shutdown() -> None:
    events: list[str] = []
    lease = _Lease(events, _record())
    attempt, resolver = _attempt(events, lease)

    runtime = await attempt.open()
    result = await runtime.client.list_muxes()
    report = await runtime.shutdown()

    assert type(result) is MuxListResultV1
    assert result.mux_spaces[0].name == "dev"
    assert resolver.requests[0].session_id == "session-1"
    assert report.completed is True
    assert report.retired is False
    assert report.record_retired is False
    assert lease.record is not None
    assert events == ["service", "apphost", "product", "lease"]
    await attempt.close()


@_async_test
async def test_G13_RETIRE_deletes_record_between_application_and_lease() -> None:
    events: list[str] = []
    lease = _Lease(events, _record())
    attempt, _resolver = _attempt(events, lease)
    runtime = await attempt.open()

    report = await runtime.retire()

    assert report.completed is True
    assert report.retired is True
    assert report.record_retired is True
    assert lease.record is None
    assert events == ["service", "apphost", "product", "record.delete", "lease"]


@_async_test
async def test_G13_RETIRE_retries_delete_without_releasing_lease_early() -> None:
    events: list[str] = []
    lease = _Lease(events, _record(), fail_delete_once=True)
    attempt, _resolver = _attempt(events, lease)
    runtime = await attempt.open()

    first = await runtime.retire()
    assert first.completed is False
    assert first.failed_phases == (HostedApplicationContinuityPhase.RECORD,)
    assert lease.closed is False
    assert events == ["service", "apphost", "product", "record.delete"]

    second = await runtime.retire()
    assert second.completed is True
    assert events == [
        "service",
        "apphost",
        "product",
        "record.delete",
        "record.delete",
        "lease",
    ]


@_async_test
async def test_G13_SETTLEMENT_rejects_shutdown_retire_intent_change() -> None:
    events: list[str] = []
    lease = _Lease(events, _record())
    attempt, _resolver = _attempt(events, lease)
    runtime = await attempt.open()
    assert (await runtime.shutdown()).completed is True

    with pytest.raises(HostedApplicationError) as caught:
        await runtime.retire()

    assert caught.value.code == "hosted_continuity_intent_conflict"
    assert lease.record is not None


@_async_test
async def test_G13_ATTEMPT_failure_retains_and_settles_every_owner_lease_last() -> None:
    events: list[str] = []
    lease = _Lease(events, _record())
    attempt, _resolver = _attempt(events, lease, mismatch=True)

    with pytest.raises(AppServiceError):
        await attempt.open()
    assert attempt.cleanup_pending is True

    await attempt.close()
    assert attempt.cleanup_pending is False
    assert lease.record is not None
    assert events == ["service", "apphost", "product", "lease"]


@_async_test
async def test_G13_SHUTDOWN_cancellation_joins_through_lease_release() -> None:
    events: list[str] = []
    gate = asyncio.Event()
    lease = _Lease(events, _record())
    attempt, _resolver = _attempt(
        events,
        lease,
        apphost=_AppHost(events, gate=gate),
    )
    runtime = await attempt.open()
    shutdown = asyncio.create_task(runtime.shutdown())
    await asyncio.sleep(0)
    shutdown.cancel()
    gate.set()

    with pytest.raises(asyncio.CancelledError):
        await shutdown

    assert events == ["service", "apphost", "product", "lease"]
    assert (await runtime.shutdown()).completed is True
