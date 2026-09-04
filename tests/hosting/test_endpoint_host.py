from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec

import pytest

from loushang.hosting import HostingError, HostingFailureCategory
from loushang.hosting._endpoint_backend import (
    _PlatformEndpointPair,
    _SingleUseProcessInheritance,
)
from loushang.hosting._endpoint_host import _InheritedEndpointHost

_P = ParamSpec("_P")


def _async_test(
    function: Callable[_P, Awaitable[None]],
) -> Callable[_P, None]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


class _Transport:
    def __init__(self) -> None:
        self.reads: asyncio.Queue[bytes | BaseException] = asyncio.Queue()
        self.writes: list[bytes] = []
        self.close_calls = 0
        self.close_error: BaseException | None = None
        self.close_entered = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_release.set()

    async def read(self, max_bytes: int) -> bytes:
        result = await self.reads.get()
        if isinstance(result, BaseException):
            raise result
        return result

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def close(self) -> None:
        self.close_calls += 1
        self.close_entered.set()
        await self.close_release.wait()
        if self.close_error is not None:
            raise self.close_error


class _Backend:
    backend_id = "fake-endpoint-v1"

    def __init__(self) -> None:
        self.transports: list[_Transport] = []
        self.child_close_calls = 0
        self.create_entered = asyncio.Event()
        self.create_release = asyncio.Event()
        self.create_release.set()
        self.close_calls = 0

    async def create_pair(
        self,
        *,
        on_create: Callable[[_PlatformEndpointPair], None],
    ) -> _PlatformEndpointPair:
        self.create_entered.set()
        await self.create_release.wait()
        transport = _Transport()
        self.transports.append(transport)

        def close_child() -> None:
            self.child_close_calls += 1

        pair = _PlatformEndpointPair(
            transport,
            _SingleUseProcessInheritance(
                backend_id="fake-process-v1",
                values=(41, 42),
                close_values=close_child,
            ),
        )
        on_create(pair)
        return pair

    async def close_backend(self) -> None:
        self.close_calls += 1


@_async_test
async def test_endpoint_host_enforces_capacity_and_byte_bounds() -> None:
    backend = _Backend()
    host = _InheritedEndpointHost(
        backend,
        max_endpoints=1,
        max_read_bytes=4,
        max_write_bytes=5,
    )
    lease = await host.create()

    with pytest.raises(HostingError) as capacity:
        await host.create()
    assert capacity.value.category is HostingFailureCategory.CAPACITY_EXHAUSTED
    with pytest.raises(HostingError) as read_bound:
        await lease.endpoint.read(5)
    assert read_bound.value.category is HostingFailureCategory.READ_BOUND_EXCEEDED
    with pytest.raises(HostingError) as write_bound:
        await lease.endpoint.write(b"123456")
    assert write_bound.value.category is HostingFailureCategory.WRITE_BOUND_EXCEEDED

    backend.transports[0].reads.put_nowait(b"pong")
    assert await lease.endpoint.read(4) == b"pong"
    await lease.endpoint.write(b"hello")
    assert backend.transports[0].writes == [b"hello"]

    await lease.close()
    replacement = await host.create()
    await replacement.close()
    await host.close()

    assert backend.child_close_calls == 2
    assert backend.close_calls == 1


@_async_test
async def test_endpoint_close_is_shared_and_maps_peer_closure() -> None:
    backend = _Backend()
    host = _InheritedEndpointHost(backend)
    lease = await host.create()
    transport = backend.transports[0]
    transport.reads.put_nowait(ConnectionResetError("peer gone"))

    assert await lease.endpoint.read(8) == b""
    transport.write = _raise_broken_pipe  # type: ignore[method-assign]
    with pytest.raises(HostingError) as peer_closed:
        await lease.endpoint.write(b"x")
    assert peer_closed.value.category is HostingFailureCategory.PEER_CLOSED

    await asyncio.gather(lease.close(), lease.close(), lease.endpoint.close())
    assert transport.close_calls == 1
    await host.close()


@_async_test
async def test_cancelled_endpoint_close_waiter_does_not_repeat_successful_owner() -> None:
    backend = _Backend()
    host = _InheritedEndpointHost(backend)
    lease = await host.create()
    transport = backend.transports[0]
    transport.close_release.clear()

    close = asyncio.create_task(lease.endpoint.close())
    await transport.close_entered.wait()
    close.cancel()
    await asyncio.sleep(0)
    assert not close.done()
    transport.close_release.set()

    with pytest.raises(asyncio.CancelledError):
        await close
    await lease.endpoint.close()
    await lease.close()
    await host.close()
    assert transport.close_calls == 1


@_async_test
async def test_cancelled_endpoint_lease_waiter_does_not_repeat_successful_owner() -> None:
    backend = _Backend()
    host = _InheritedEndpointHost(backend)
    lease = await host.create()
    transport = backend.transports[0]
    transport.close_release.clear()

    close = asyncio.create_task(lease.close())
    await transport.close_entered.wait()
    close.cancel()
    await asyncio.sleep(0)
    assert not close.done()
    transport.close_release.set()

    with pytest.raises(asyncio.CancelledError):
        await close
    await lease.close()
    await host.close()
    assert transport.close_calls == 1
    assert backend.child_close_calls == 1


async def _raise_broken_pipe(data: bytes) -> None:
    del data
    raise BrokenPipeError("peer gone")


@_async_test
async def test_host_close_cancels_pending_creation_and_reclaims_attachment() -> None:
    backend = _Backend()
    backend.create_release.clear()
    host = _InheritedEndpointHost(backend)
    creation = asyncio.create_task(host.create())
    await backend.create_entered.wait()

    await host.close()
    with pytest.raises(asyncio.CancelledError):
        await creation

    assert backend.transports == []
    assert backend.close_calls == 1


@_async_test
async def test_host_close_waits_for_create_transaction_not_callers_later_work() -> None:
    backend = _Backend()
    backend.create_release.clear()
    host = _InheritedEndpointHost(backend)
    cancellation_caught = asyncio.Event()
    caller_release = asyncio.Event()

    async def caller() -> None:
        try:
            await host.create()
        except asyncio.CancelledError:
            cancellation_caught.set()
            await caller_release.wait()

    caller_task = asyncio.create_task(caller())
    await backend.create_entered.wait()

    await asyncio.wait_for(host.close(), 1.0)
    await cancellation_caught.wait()
    assert not caller_task.done()
    caller_release.set()
    await caller_task

    assert backend.close_calls == 1


@_async_test
async def test_cancellation_after_attachment_delays_until_pair_cleanup() -> None:
    attached = asyncio.Event()
    release = asyncio.Event()

    class _AttachedBackend(_Backend):
        async def create_pair(
            self,
            *,
            on_create: Callable[[_PlatformEndpointPair], None],
        ) -> _PlatformEndpointPair:
            pair = await super().create_pair(on_create=on_create)
            attached.set()
            await release.wait()
            return pair

    backend = _AttachedBackend()
    host = _InheritedEndpointHost(backend)
    creation = asyncio.create_task(host.create())
    await attached.wait()
    creation.cancel()

    with pytest.raises(asyncio.CancelledError):
        await creation
    assert backend.transports[0].close_calls == 1
    assert backend.child_close_calls == 1
    await host.close()


@_async_test
async def test_cleanup_failures_do_not_skip_capacity_release_or_backend_close() -> None:
    backend = _Backend()
    host = _InheritedEndpointHost(backend, max_endpoints=1)
    lease = await host.create()
    backend.transports[0].close_error = OSError("transport close")

    with pytest.raises(BaseExceptionGroup):
        await lease.close()
    with pytest.raises(HostingError) as faulted:
        await host.create()
    assert faulted.value.category is HostingFailureCategory.HOST_CLOSED
    with pytest.raises(BaseExceptionGroup):
        await host.close()

    assert backend.close_calls == 1


@_async_test
async def test_attached_pair_cleanup_debt_faults_host_and_is_retried() -> None:
    class _AttachedFailingBackend(_Backend):
        async def create_pair(
            self,
            *,
            on_create: Callable[[_PlatformEndpointPair], None],
        ) -> _PlatformEndpointPair:
            await super().create_pair(on_create=on_create)
            self.transports[-1].close_error = OSError("transient pair cleanup")
            raise HostingError(
                HostingFailureCategory.ENDPOINT_UNAVAILABLE,
                "endpoint failed after owner attachment",
            )

    backend = _AttachedFailingBackend()
    host = _InheritedEndpointHost(backend)

    with pytest.raises(HostingError) as failure:
        await host.create()

    assert failure.value.category is HostingFailureCategory.ENDPOINT_UNAVAILABLE
    assert isinstance(failure.value.__cause__, HostingError)
    assert failure.value.__cause__.category is HostingFailureCategory.CLEANUP_FAILED
    assert host._state == "faulted"
    assert len(host._reservations) == 1

    backend.transports[0].close_error = None
    await host.close()

    assert backend.transports[0].close_calls == 2
    assert not host._reservations
    assert backend.close_calls == 1


@_async_test
async def test_single_use_inheritance_is_backend_bound_and_retry_closable() -> None:
    closes = 0
    fail_once = True

    def close_values() -> None:
        nonlocal closes, fail_once
        closes += 1
        if fail_once:
            fail_once = False
            raise OSError("transient close")

    inheritance = _SingleUseProcessInheritance(
        backend_id="target-v1",
        values=(7, 8),
        close_values=close_values,
    )
    with pytest.raises(HostingError) as mismatch:
        inheritance.claim(backend_id="wrong-v1")
    assert mismatch.value.category is HostingFailureCategory.ENDPOINT_TRANSFER_FAILED
    assert inheritance.claim(backend_id="target-v1") == (7, 8)
    with pytest.raises(HostingError):
        inheritance.claim(backend_id="target-v1")
    with pytest.raises(HostingError) as transfer:
        inheritance.mark_transferred()
    assert transfer.value.category is HostingFailureCategory.ENDPOINT_TRANSFER_FAILED
    await inheritance.close()

    assert closes == 2


@_async_test
async def test_provider_returning_foreign_pair_reclaims_both_pairs() -> None:
    closed: list[str] = []

    class _NamedTransport(_Transport):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

        async def close(self) -> None:
            closed.append(self.name)

    def pair(name: str, value: int) -> _PlatformEndpointPair:
        return _PlatformEndpointPair(
            _NamedTransport(name),
            _SingleUseProcessInheritance(
                backend_id="fake-process-v1",
                values=(value,),
                close_values=lambda: closed.append(f"{name}-child"),
            ),
        )

    class _BrokenBackend(_Backend):
        async def create_pair(
            self,
            *,
            on_create: Callable[[_PlatformEndpointPair], None],
        ) -> _PlatformEndpointPair:
            attached = pair("attached", 1)
            returned = pair("returned", 2)
            on_create(attached)
            return returned

    host = _InheritedEndpointHost(_BrokenBackend())
    with pytest.raises(RuntimeError, match="already owns"):
        await host.create()
    await host.close()

    assert set(closed) == {
        "attached",
        "attached-child",
        "returned",
        "returned-child",
    }


@_async_test
async def test_endpoint_observations_are_bounded_and_non_owning() -> None:
    observations: list[object] = []

    class _Sink:
        def observe(self, observation: object) -> None:
            observations.append(observation)
            raise RuntimeError("observer cannot veto")

    backend = _Backend()
    host = _InheritedEndpointHost(backend, observation_sink=_Sink())
    lease = await host.create(session_id="session-1")
    await lease.close()
    await host.close()

    assert len(observations) >= 4
    assert all(getattr(item, "session_id") == "session-1" for item in observations)
