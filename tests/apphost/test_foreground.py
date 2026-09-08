from __future__ import annotations

import asyncio
from typing import cast

import pytest

from loushang.apphost.application import HostedApplicationError
from loushang.apphost.continuity import HostedApplicationContinuityRuntimeV1
from loushang.apphost.foreground import HostedForegroundRuntimeV1
from loushang.appserver.client import AppClientV1
from loushang.appserver.framing import AppConnectionClosedError, AppFramedStreamV1
from loushang.appserver.protocol import AckV1, InvalidAppMessageError, TurnTextV1
from loushang.appserver.remote_client import StdioAppClientV1


class _Pipe:
    def __init__(self) -> None:
        self.reader = asyncio.StreamReader()
        self.peer: _Pipe
        self.closed = False

    async def read(self, size: int) -> bytes:
        return await self.reader.read(size)

    async def write(self, data: bytes) -> None:
        if self.closed:
            raise OSError("closed")
        self.peer.reader.feed_data(data)

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.peer.reader.feed_eof()


class _Application:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.entered = asyncio.Event()
        self.fail_close_once = False
        self.close_gate: asyncio.Event | None = None

    @property
    def client(self) -> AppClientV1:
        return cast(AppClientV1, self)

    async def start_turn(self, request: TurnTextV1) -> AckV1:
        del request
        self.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.events.append("request.settled")
        return AckV1()

    async def close(self) -> None:
        self.events.append("application.close")
        if self.fail_close_once:
            self.fail_close_once = False
            raise RuntimeError("private failure")
        if self.close_gate is not None:
            await self.close_gate.wait()
        self.events.append("lease.released")


def _owner(
    app: _Application,
    *,
    timeout: float = 1.0,
) -> tuple[HostedForegroundRuntimeV1, StdioAppClientV1, _Pipe]:
    left, right = _Pipe(), _Pipe()
    left.peer, right.peer = right, left
    owner = HostedForegroundRuntimeV1(
        cast(HostedApplicationContinuityRuntimeV1, app),
        right,
        connection_timeout=timeout,
        settlement_timeout=timeout,
    )
    return owner, StdioAppClientV1(AppFramedStreamV1(left)), right


def test_G14_OWNERSHIP_foreground_eof_settles_requests_before_application() -> None:
    async def scenario() -> None:
        app = _Application()
        owner, client, pipe = _owner(app)
        running = asyncio.create_task(owner.run())
        await client.start()
        prompt = asyncio.create_task(client.start_turn(TurnTextV1("a", 1, "m", "hi")))
        await app.entered.wait()
        await client.close()
        with pytest.raises(AppConnectionClosedError):
            await prompt
        await running
        assert app.events == ["request.settled", "application.close", "lease.released"]
        assert pipe.closed and not owner.cleanup_pending
        await owner.close()
        assert app.events.count("application.close") == 1
        with pytest.raises(HostedApplicationError, match="hosted_foreground_closed"):
            await owner.run()

    asyncio.run(asyncio.wait_for(scenario(), 5))


@pytest.mark.parametrize("cancel_caller", [False, True])
def test_G14_OWNERSHIP_close_or_cancellation_settles_handshake(
    cancel_caller: bool,
) -> None:
    async def scenario() -> None:
        app = _Application()
        owner, client, pipe = _owner(app)
        running = asyncio.create_task(owner.run())
        # Reading hello proves serve has started; do not answer the handshake.
        assert await AppFramedStreamV1(pipe.peer).receive()
        if cancel_caller:
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            await owner.close()
            await running
        assert not owner.cleanup_pending and pipe.closed
        assert app.events == ["application.close", "lease.released"]
        await client.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G14_OWNERSHIP_failed_application_close_remains_retryable() -> None:
    async def scenario() -> None:
        app = _Application()
        app.fail_close_once = True
        owner, client, pipe = _owner(app)
        with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
            await owner.close()
        assert owner.cleanup_pending and pipe.closed
        assert "lease.released" not in app.events
        await owner.close()
        assert not owner.cleanup_pending
        assert app.events == [
            "application.close",
            "application.close",
            "lease.released",
        ]
        await client.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G14_OWNERSHIP_timed_out_close_joins_same_task_on_retry() -> None:
    async def scenario() -> None:
        app = _Application()
        app.close_gate = asyncio.Event()
        owner, client, _ = _owner(app, timeout=0.02)
        for _ in range(2):
            with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
                await owner.close()
        assert app.events == ["application.close"]
        assert owner.cleanup_pending
        app.close_gate.set()
        await owner.close()
        assert app.events == ["application.close", "lease.released"]
        assert not owner.cleanup_pending
        await client.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G14_OWNERSHIP_unsettled_connection_cannot_release_application_lease() -> None:
    class StubbornApplication(_Application):
        def __init__(self) -> None:
            super().__init__()
            self.release = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def start_turn(self, request: TurnTextV1) -> AckV1:
            del request
            self.entered.set()
            while not self.release.is_set():
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
            self.events.append("request.settled")
            return AckV1()

    async def scenario() -> None:
        app = StubbornApplication()
        owner, client, _ = _owner(app, timeout=0.02)
        running = asyncio.create_task(owner.run())
        await client.start()
        prompt = asyncio.create_task(client.start_turn(TurnTextV1("a", 1, "m", "hi")))
        await app.entered.wait()
        await client.close()
        with pytest.raises(AppConnectionClosedError):
            await prompt
        await app.cancelled.wait()
        with pytest.raises(HostedApplicationError, match="cleanup_incomplete"):
            await running
        assert owner.cleanup_pending and app.events == []
        app.release.set()
        # Observe the retained phase finish; retry must then settle the same
        # connection before it can progress to the application.
        await asyncio.gather(*owner._phases.values(), return_exceptions=True)
        await owner.close()
        assert app.events == ["request.settled", "application.close", "lease.released"]
        assert not owner.cleanup_pending

    asyncio.run(asyncio.wait_for(scenario(), 5))


def test_G14_OWNERSHIP_handshake_fault_is_reported_after_application_cleanup() -> None:
    async def scenario() -> None:
        app = _Application()
        owner, client, pipe = _owner(app)
        running = asyncio.create_task(owner.run())
        peer = AppFramedStreamV1(pipe.peer)
        assert await peer.receive()
        await peer.send(b"{}")
        with pytest.raises(InvalidAppMessageError):
            await running
        assert app.events == ["application.close", "lease.released"]
        assert not owner.cleanup_pending and pipe.closed
        await client.close()

    asyncio.run(asyncio.wait_for(scenario(), 5))
