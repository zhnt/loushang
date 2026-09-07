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
    HostedApplicationRuntimeV1,
    HostedApplicationShutdownPhase,
    create_hosted_application_runtime,
)
from loushang.appserver.protocol import (
    MuxCreateV1,
    MuxMemberOpenV1,
    MuxSelectorV1,
    SessionIdentityV1,
    SessionOpenSpecV1,
    SessionScopeV1,
    SessionSnapshotV1,
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
    def __init__(self, events: list[str], *, fail_close_once: bool = False) -> None:
        self.identity = SessionIdentityV1(
            "coding",
            "continuity",
            "session",
            SessionScopeV1.CWD,
            _FINGERPRINT,
        )
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
        self._events.append("service")
        if self._fail_close_once:
            self._fail_close_once = False
            raise RuntimeError("hidden")


class _Resolver:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def open_session(self, request: SessionOpenSpecV1) -> _Session:
        del request
        return self.session


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
    def __init__(self, events: list[str], *, fail_close_once: bool = False) -> None:
        self.events = events
        self._fail_close_once = fail_close_once

    async def close(self) -> None:
        self.events.append("product")
        if self._fail_close_once:
            self._fail_close_once = False
            raise RuntimeError("hidden")


def _runtime(
    events: list[str],
    *,
    session: _Session | None = None,
    apphost: _AppHost | None = None,
    product: _Product | None = None,
    timeout: float = 1.0,
) -> HostedApplicationRuntimeV1:
    ids = iter(("mux", "member"))
    return create_hosted_application_runtime(
        HostedApplicationRequestV1(
            activation=HostedApplicationActivationV1(),
            product_id="coding",
            generation_id="generation-1",
            apphost=apphost or _AppHost(events),
            resolver=_Resolver(session or _Session(events)),
            product_owner=product or _Product(events),
            shutdown_budget=AppHostShutdownBudgetV1(1.0, 0.5),
            phase_timeout_seconds=timeout,
            service_id_factory=lambda: next(ids),
        )
    )


async def _open_session(runtime: HostedApplicationRuntimeV1) -> None:
    client = runtime.client
    mux = await client.create_mux(MuxCreateV1("dev"))
    await client.open_member(
        MuxMemberOpenV1(
            MuxSelectorV1(mux_space_id=mux.mux_space_id),
            SessionOpenSpecV1(
                "coding",
                "continuity",
                SessionScopeV1.CWD,
                _FINGERPRINT,
                "Session",
            ),
        )
    )


def test_G12_EXPLICIT_ACTIVATION_rejects_an_activation_subclass() -> None:
    class _Activation(HostedApplicationActivationV1):
        pass

    events: list[str] = []
    with pytest.raises(TypeError, match="explicit activation"):
        HostedApplicationRequestV1(
            activation=_Activation(),
            product_id="coding",
            generation_id="generation-1",
            apphost=_AppHost(events),
            resolver=_Resolver(_Session(events)),
            product_owner=_Product(events),
            shutdown_budget=AppHostShutdownBudgetV1(1.0, 0.5),
        )


@_async_test
async def test_G12_OPTIONAL_EDGE_accepts_a_product_neutral_owner() -> None:
    events: list[str] = []
    runtime = create_hosted_application_runtime(
        HostedApplicationRequestV1(
            activation=HostedApplicationActivationV1(),
            product_id="slides",
            generation_id="slides-generation-1",
            apphost=_AppHost(events),
            resolver=_Resolver(_Session(events)),
            product_owner=_Product(events),
            shutdown_budget=AppHostShutdownBudgetV1(1.0, 0.5),
        )
    )

    report = await runtime.shutdown()

    assert runtime.product_id == "slides"
    assert report.completed is True
    assert events == ["apphost", "product"]


@_async_test
async def test_G12_APPLICATION_CLOSE_orders_service_apphost_and_product() -> None:
    events: list[str] = []
    runtime = _runtime(events)
    await _open_session(runtime)

    report = await runtime.shutdown()

    assert report.completed is True
    assert report.apphost_shutdown == AppHostShutdownReportV1(True, (), ())
    assert report.product_cleanup_complete is True
    assert events == ["service", "apphost", "product"]
    assert runtime.accepting is False
    await runtime.close()
    assert events == ["service", "apphost", "product"]


@_async_test
async def test_G12_APPLICATION_CLOSE_retries_service_debt_before_dependents() -> None:
    events: list[str] = []
    runtime = _runtime(events, session=_Session(events, fail_close_once=True))
    await _open_session(runtime)

    first = await runtime.shutdown()
    assert first.completed is False
    assert first.failed_phases == (HostedApplicationShutdownPhase.SERVICE,)
    assert events == ["service"]

    second = await runtime.shutdown()
    assert second.completed is True
    assert events == ["service", "service", "apphost", "product"]


@_async_test
async def test_G12_APPLICATION_CLOSE_retains_timed_out_apphost_task() -> None:
    events: list[str] = []
    gate = asyncio.Event()
    runtime = _runtime(
        events,
        apphost=_AppHost(events, gate=gate),
        timeout=0.01,
    )

    first = await runtime.shutdown()
    assert first.timed_out_phases == (HostedApplicationShutdownPhase.APPHOST,)
    assert events == ["apphost"]

    gate.set()
    second = await runtime.shutdown()
    assert second.completed is True
    assert events == ["apphost", "product"]


@_async_test
async def test_G12_APPLICATION_CLOSE_retries_product_debt_only() -> None:
    events: list[str] = []
    runtime = _runtime(events, product=_Product(events, fail_close_once=True))

    first = await runtime.shutdown()
    assert first.completed is False
    assert first.failed_phases == (HostedApplicationShutdownPhase.PRODUCT,)
    assert events == ["apphost", "product"]

    second = await runtime.shutdown()
    assert second.completed is True
    assert events == ["apphost", "product", "product"]


@_async_test
async def test_G12_CANCELLATION_joins_adopted_shutdown_before_propagating() -> None:
    events: list[str] = []
    gate = asyncio.Event()
    runtime = _runtime(events, apphost=_AppHost(events, gate=gate))
    close = asyncio.create_task(runtime.shutdown())
    await asyncio.sleep(0)
    close.cancel()
    gate.set()

    with pytest.raises(asyncio.CancelledError):
        await close
    assert events == ["apphost", "product"]
    report = await runtime.shutdown()
    assert report.completed is True


@_async_test
async def test_close_raises_stable_error_when_settlement_is_incomplete() -> None:
    events: list[str] = []
    runtime = _runtime(
        events,
        session=_Session(events, fail_close_once=True),
    )
    await _open_session(runtime)

    with pytest.raises(HostedApplicationError) as raised:
        await runtime.close()
    assert raised.value.code == "hosted_application_cleanup_incomplete"
