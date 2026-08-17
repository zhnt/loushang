from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from loushang.harness.workspace.process import ProcessLaunchRequest
from loushang.harness.workspace.process import local as local_process
from loushang.harness.workspace.process.host import (
    ProcessHost,
    ProcessHostCapacityError,
    ProcessHostClosedError,
    ProcessHostError,
    ProcessWriteLimitError,
)
from loushang.harness.workspace.process.local import (
    ProcessContainmentPlan,
    ProcessTransport,
    SpawnAttachment,
)


class _FakeReader:
    def __init__(self) -> None:
        self._chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._remainder = b""

    def feed(self, content: bytes) -> None:
        self._chunks.put_nowait(content)

    def close(self) -> None:
        self._chunks.put_nowait(None)

    async def read(self, max_bytes: int = -1) -> bytes:
        if not self._remainder:
            chunk = await self._chunks.get()
            if chunk is None:
                return b""
            self._remainder = chunk
        if max_bytes < 0:
            content, self._remainder = self._remainder, b""
            return content
        content, self._remainder = (
            self._remainder[:max_bytes],
            self._remainder[max_bytes:],
        )
        return content


class _FailingReader:
    def close(self) -> None:
        return None

    async def read(self, max_bytes: int = -1) -> bytes:
        del max_bytes
        raise OSError("synthetic stderr failure")


class _FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise BrokenPipeError
        self.writes.append(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        await asyncio.sleep(0)


class _FailingCloseWriter(_FakeWriter):
    async def wait_closed(self) -> None:
        raise OSError("synthetic stdin close failure")


class _FakeTransport:
    pid = None

    def __init__(self, *, terminate_immediately: bool = True) -> None:
        self.returncode: int | None = None
        self.stdin = _FakeWriter()
        self.stdout = _FakeReader()
        self.stderr = _FakeReader()
        self.terminate_immediately = terminate_immediately
        self.terminate_calls = 0
        self.kill_calls = 0
        self._exit: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def wait(self) -> int:
        return await asyncio.shield(self._exit)

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.terminate_immediately:
            self.finish(-15)

    def kill(self) -> None:
        self.kill_calls += 1
        self.finish(-9)

    def finish(self, return_code: int, *, stderr: bytes = b"") -> None:
        if self._exit.done():
            return
        self.returncode = return_code
        if stderr:
            self.stderr.feed(stderr)
        self.stdout.close()
        self.stderr.close()
        self._exit.set_result(return_code)


class _FakeSpawner:
    def __init__(
        self,
        *,
        pause_before_create: bool = False,
        pause_after_attach: bool = False,
        transport_factory: Callable[[], _FakeTransport] = _FakeTransport,
    ) -> None:
        self.pause_before_create = pause_before_create
        self.pause_after_attach = pause_after_attach
        self.transport_factory = transport_factory
        self.entered = asyncio.Event()
        self.allow_create = asyncio.Event()
        self.attached = asyncio.Event()
        self.allow_return = asyncio.Event()
        self.transports: list[_FakeTransport] = []
        if not pause_before_create:
            self.allow_create.set()
        if not pause_after_attach:
            self.allow_return.set()

    async def __call__(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: SpawnAttachment,
    ) -> ProcessTransport:
        del request
        self.entered.set()
        await self.allow_create.wait()
        transport = self.transport_factory()
        self.transports.append(transport)
        on_spawn(transport)
        self.attached.set()
        await self.allow_return.wait()
        return transport


class _FailOnceSpawner(_FakeSpawner):
    def __init__(self) -> None:
        super().__init__()
        self._failed = False

    async def __call__(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: SpawnAttachment,
    ) -> ProcessTransport:
        if not self._failed:
            self._failed = True
            raise OSError("synthetic spawn failure")
        return await super().__call__(request, on_spawn=on_spawn)


def _request(tmp_path: Path) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        command=("language-server", "--stdio"),
        cwd=str(tmp_path),
        effective_environment=(),
    )


def test_pending_start_reserves_capacity_and_close_rejects_new_work(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        spawner = _FakeSpawner(pause_before_create=True)
        host = ProcessHost(spawner=spawner, max_processes=1)
        start_task = asyncio.create_task(host.start(_request(tmp_path)))
        await spawner.entered.wait()

        with pytest.raises(ProcessHostCapacityError):
            await host.start(_request(tmp_path))

        await host.close()
        with pytest.raises(asyncio.CancelledError):
            await start_task
        assert spawner.transports == []
        with pytest.raises(ProcessHostClosedError):
            await host.start(_request(tmp_path))

    asyncio.run(scenario())


def test_close_racing_attached_start_reclaims_unpublished_child(tmp_path: Path) -> None:
    async def scenario() -> None:
        spawner = _FakeSpawner(pause_after_attach=True)
        host = ProcessHost(spawner=spawner, max_processes=1)
        start_task = asyncio.create_task(host.start(_request(tmp_path)))
        await spawner.attached.wait()

        await host.close()

        with pytest.raises(asyncio.CancelledError):
            await start_task
        transport = spawner.transports[0]
        assert transport.stdin.closed is True
        assert transport.terminate_calls == 1
        assert transport.returncode == -15

    asyncio.run(scenario())


def test_close_racing_spawn_reclaims_attached_containment(tmp_path: Path) -> None:
    async def scenario() -> None:
        spawner = _FakeSpawner(pause_before_create=True)
        close_count = 0

        async def close_containment() -> None:
            nonlocal close_count
            close_count += 1

        async def plan(request: ProcessLaunchRequest) -> ProcessContainmentPlan:
            return ProcessContainmentPlan(request, close=close_containment)

        host = ProcessHost(spawner=spawner)
        start_task = asyncio.create_task(
            host.start(_request(tmp_path), containment_planner=plan)
        )
        await spawner.entered.wait()

        await host.close()

        with pytest.raises(asyncio.CancelledError):
            await start_task
        assert close_count == 1

    asyncio.run(scenario())


def test_natural_exit_releases_capacity_and_preserves_bounded_stderr(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        spawner = _FakeSpawner()
        host = ProcessHost(spawner=spawner, max_processes=1, stderr_max_bytes=4)
        first = await host.start(_request(tmp_path))
        transport = spawner.transports[0]
        transport.stdout.feed(b"a")
        transport.stdout.feed(b"bc")

        assert await first.read_stdout(2) == b"a"
        assert await first.read_stdout(2) == b"bc"
        with pytest.raises(ProcessHostCapacityError):
            await host.start(_request(tmp_path))

        transport.finish(7, stderr=b"abcdef")
        first_exit, second_exit = await asyncio.gather(first.wait(), first.wait())
        assert first_exit is second_exit
        assert first_exit.return_code == 7
        assert first.stderr_tail().content == b"cdef"
        assert first.stderr_tail().truncated is True

        second = await host.start(_request(tmp_path))
        await second.close()
        await host.close()

    asyncio.run(scenario())


def test_natural_exit_closes_containment_exactly_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        spawner = _FakeSpawner()
        close_count = 0

        async def close_containment() -> None:
            nonlocal close_count
            close_count += 1

        async def plan(request: ProcessLaunchRequest) -> ProcessContainmentPlan:
            return ProcessContainmentPlan(request, close=close_containment)

        host = ProcessHost(spawner=spawner)
        handle = await host.start(_request(tmp_path), containment_planner=plan)
        spawner.transports[0].finish(0)

        assert (await handle.wait()).return_code == 0
        await handle.close()
        await host.close()
        assert close_count == 1

    asyncio.run(scenario())


def test_stderr_failure_does_not_skip_containment_or_registration_release(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        def failing_transport() -> _FakeTransport:
            transport = _FakeTransport()
            transport.stderr = _FailingReader()
            return transport

        spawner = _FakeSpawner(transport_factory=failing_transport)
        close_count = 0

        async def close_containment() -> None:
            nonlocal close_count
            close_count += 1

        async def plan(request: ProcessLaunchRequest) -> ProcessContainmentPlan:
            return ProcessContainmentPlan(request, close=close_containment)

        host = ProcessHost(spawner=spawner, max_processes=1)
        handle = await host.start(_request(tmp_path), containment_planner=plan)
        spawner.transports[0].finish(0)

        with pytest.raises(OSError, match="synthetic stderr failure"):
            await handle.wait()
        assert close_count == 1
        await host.close()

    asyncio.run(scenario())


def test_write_limit_and_terminate_close_race_settle_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        spawner = _FakeSpawner()
        host = ProcessHost(spawner=spawner, max_write_bytes=3)
        handle = await host.start(_request(tmp_path))

        with pytest.raises(ProcessWriteLimitError):
            await handle.write_stdin(b"four")
        await handle.write_stdin(b"abc")
        assert spawner.transports[0].stdin.writes == [b"abc"]

        termination, _ = await asyncio.gather(handle.terminate(), handle.close())
        assert termination.return_code == -15
        assert spawner.transports[0].terminate_calls == 1
        assert (await handle.wait()) is termination
        await host.close()

    asyncio.run(scenario())


def test_published_close_reports_stdin_failure_after_process_settlement(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        def failing_transport() -> _FakeTransport:
            transport = _FakeTransport()
            transport.stdin = _FailingCloseWriter()
            return transport

        spawner = _FakeSpawner(transport_factory=failing_transport)
        host = ProcessHost(spawner=spawner)
        handle = await host.start(_request(tmp_path))

        with pytest.raises(OSError, match="synthetic stdin close failure"):
            await handle.close()
        transport = spawner.transports[0]
        assert transport.terminate_calls == 1
        assert transport.returncode == -15
        assert (await handle.wait()).return_code == -15
        await host.close()

    asyncio.run(scenario())


def test_unpublished_close_reports_cleanup_failure_without_leaking_child(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        def failing_transport() -> _FakeTransport:
            transport = _FakeTransport()
            transport.stdin = _FailingCloseWriter()
            return transport

        spawner = _FakeSpawner(
            pause_after_attach=True,
            transport_factory=failing_transport,
        )
        host = ProcessHost(spawner=spawner)
        start_task = asyncio.create_task(host.start(_request(tmp_path)))
        await spawner.attached.wait()

        with pytest.raises(ProcessHostError, match="failed to close"):
            await host.close()
        with pytest.raises(asyncio.CancelledError):
            await start_task
        transport = spawner.transports[0]
        assert transport.terminate_calls == 1
        assert transport.returncode == -15

    asyncio.run(scenario())


def test_spawn_failure_rolls_back_reserved_capacity(tmp_path: Path) -> None:
    async def scenario() -> None:
        spawner = _FailOnceSpawner()
        host = ProcessHost(spawner=spawner, max_processes=1)

        with pytest.raises(OSError, match="synthetic spawn failure"):
            await host.start(_request(tmp_path))

        handle = await host.start(_request(tmp_path))
        await handle.close()
        await host.close()

    asyncio.run(scenario())


def test_local_spawner_reclaims_child_before_repeated_cancellation_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        spawn_entered = asyncio.Event()
        allow_spawn = asyncio.Event()
        transport = _FakeTransport(terminate_immediately=False)

        async def delayed_spawn(**kwargs: object) -> _FakeTransport:
            del kwargs
            spawn_entered.set()
            await allow_spawn.wait()
            return transport

        monkeypatch.setattr(local_process, "spawn_local_process", delayed_spawn)
        attached: list[ProcessTransport] = []
        spawn_task = asyncio.create_task(
            local_process.LocalProcessSpawner()(
                _request(tmp_path),
                on_spawn=attached.append,
            )
        )
        await spawn_entered.wait()

        spawn_task.cancel()
        await asyncio.sleep(0)
        spawn_task.cancel()
        allow_spawn.set()

        with pytest.raises(asyncio.CancelledError):
            await spawn_task
        assert attached == [transport]
        assert transport.kill_calls == 1
        assert transport.returncode == -9

    asyncio.run(scenario())


def test_host_close_continues_after_caller_cancellation(tmp_path: Path) -> None:
    async def scenario() -> None:
        spawner = _FakeSpawner(
            transport_factory=lambda: _FakeTransport(terminate_immediately=False)
        )
        host = ProcessHost(spawner=spawner, termination_grace_seconds=0.01)
        await host.start(_request(tmp_path))

        interrupted_close = asyncio.create_task(host.close())
        await asyncio.sleep(0)
        interrupted_close.cancel()
        with pytest.raises(asyncio.CancelledError):
            await interrupted_close

        transport = spawner.transports[0]
        assert transport.terminate_calls == 1
        assert transport.kill_calls == 1
        await host.close()

    asyncio.run(scenario())


def test_local_host_preserves_raw_stdio_and_bounded_stderr(tmp_path: Path) -> None:
    async def scenario() -> None:
        host = ProcessHost(stderr_max_bytes=4)
        request = ProcessLaunchRequest(
            command=(
                sys.executable,
                "-c",
                (
                    "import sys; data=sys.stdin.buffer.read(); "
                    "sys.stdout.buffer.write(b'A'+data+b'B'); "
                    "sys.stderr.buffer.write(b'0123456789')"
                ),
            ),
            cwd=str(tmp_path),
            effective_environment=tuple(os.environ.items()),
        )
        handle = await host.start(request)
        await handle.write_stdin(b"xyz")
        await handle.close_stdin()

        output = bytearray()
        while chunk := await handle.read_stdout(2):
            output.extend(chunk)
        assert bytes(output) == b"AxyzB"
        assert (await handle.wait()).return_code == 0
        assert handle.stderr_tail().content == b"6789"
        assert handle.stderr_tail().truncated is True
        await host.close()

    asyncio.run(scenario())
