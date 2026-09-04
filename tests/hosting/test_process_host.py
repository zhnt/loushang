from __future__ import annotations

import asyncio
import inspect
import sys
from collections import deque
from collections.abc import Awaitable, Callable
from functools import wraps
from pathlib import Path
from typing import TypeVar

import pytest

from loushang.hosting import (
    HostingError,
    HostingFailureCategory,
    HostingLifecycleTransition,
    HostingObservation,
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting._process_backend import _ProcessInheritance, _ProcessTransport
from loushang.hosting._process_host import (
    _CleanupError,
    _CleanupPhase,
    _ProcessHost,
    _ProcessHostLimits,
    _Timeouts,
)

_T = TypeVar("_T")


def _async_test(
    function: Callable[[], Awaitable[None]],
) -> Callable[[], None]:
    @wraps(function)
    def run() -> None:
        asyncio.run(function())

    return run


def _request(
    *,
    stdin: ProcessStdinMode = ProcessStdinMode.PIPE,
    stdout: ProcessStdoutMode = ProcessStdoutMode.PIPE,
    stderr: ProcessStderrMode = ProcessStderrMode.CAPTURE_TAIL,
) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(sys.executable, "--attached"),
        cwd=str(Path.cwd().resolve()),
        effective_environment=(("PATH", "/usr/bin"),),
        streams=ProcessStreamSpec(stdin=stdin, stdout=stdout, stderr=stderr),
    )


class _FakePreparationLease:
    def __init__(
        self,
        request: ProcessLaunchRequest,
        *,
        verify_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.request = request
        self.verify_error = verify_error
        self.close_error = close_error
        self.verify_calls = 0
        self.close_calls = 0

    async def verify_current(self) -> None:
        self.verify_calls += 1
        if self.verify_error is not None:
            raise self.verify_error

    async def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class _FakePreparationPort:
    def __init__(
        self,
        lease: _FakePreparationLease,
        *,
        prepare_error: BaseException | None = None,
        block: bool = False,
    ) -> None:
        self.lease = lease
        self.prepare_error = prepare_error
        self.prepare_calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not block:
            self.release.set()

    async def prepare(
        self, request: ProcessLaunchRequest
    ) -> _FakePreparationLease:
        self.prepare_calls += 1
        self.entered.set()
        await self.release.wait()
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.lease


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout: tuple[bytes, ...] = (),
        stderr: tuple[bytes, ...] = (),
        return_code: int | None = None,
    ) -> None:
        self._stdout = deque((*stdout, b""))
        self._stderr = deque((*stderr, b""))
        self._return_code = return_code
        self._exited = asyncio.Event()
        self._tree_exited = asyncio.Event()
        if return_code is not None:
            self._exited.set()
            self._tree_exited.set()
        self.stdin_writes: list[bytes] = []
        self.close_stdin_calls = 0
        self.wait_calls = 0
        self.close_stdin_error: BaseException | None = None
        self.oversized_stdout = False

    @property
    def return_code(self) -> int | None:
        return self._return_code

    async def read_stdout(self, max_bytes: int) -> bytes:
        if self.oversized_stdout:
            return b"x" * (max_bytes + 1)
        return self._stdout.popleft()

    async def read_stderr(self, max_bytes: int) -> bytes:
        return self._stderr.popleft()

    async def write_stdin(self, data: bytes) -> None:
        self.stdin_writes.append(data)

    async def close_stdin(self) -> None:
        self.close_stdin_calls += 1
        if self.close_stdin_error is not None:
            raise self.close_stdin_error

    async def wait(self) -> int:
        self.wait_calls += 1
        await self._exited.wait()
        assert self._return_code is not None
        return self._return_code

    def exit(self, return_code: int, *, tree: bool = True) -> None:
        if self._return_code is None:
            self._return_code = return_code
            self._exited.set()
        if tree:
            self._tree_exited.set()

    def settle_tree(self) -> None:
        self._tree_exited.set()


class _FakeBackend:
    backend_id = "fake-process-v1"

    def __init__(self, processes: tuple[_FakeProcess, ...]) -> None:
        self._processes = deque(processes)
        self.spawn_requests: list[ProcessLaunchRequest] = []
        self.events: list[str] = []
        self.spawn_error: BaseException | None = None
        self.skip_attachment = False
        self.block_spawn = False
        self.spawn_attached = asyncio.Event()
        self.release_spawn = asyncio.Event()
        self.terminate_exits = True
        self.kill_exits = True
        self.terminate_error: BaseException | None = None
        self.kill_error: BaseException | None = None
        self.handles_error: BaseException | None = None
        self.tree_exited_error: BaseException | None = None
        self.close_handles_started = asyncio.Event()
        self.release_close_handles = asyncio.Event()
        self.release_close_handles.set()
        self.terminate_calls = 0
        self.kill_calls = 0
        self.close_handles_calls = 0
        self.close_backend_calls = 0

    async def spawn(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None = None,
    ) -> _FakeProcess:
        assert inheritance is None
        self.spawn_requests.append(request)
        self.events.append("spawn")
        if self.spawn_error is not None:
            raise self.spawn_error
        process = self._processes.popleft()
        if not self.skip_attachment:
            on_spawn(process)
        self.spawn_attached.set()
        if self.block_spawn:
            await self.release_spawn.wait()
        return process

    async def terminate_tree(self, process: _ProcessTransport) -> None:
        self.terminate_calls += 1
        self.events.append("terminate")
        if self.terminate_exits:
            assert isinstance(process, _FakeProcess)
            process.exit(-15)
        if self.terminate_error is not None:
            raise self.terminate_error

    def tree_exited(self, process: _ProcessTransport) -> bool:
        if self.tree_exited_error is not None:
            raise self.tree_exited_error
        assert isinstance(process, _FakeProcess)
        return process._tree_exited.is_set()

    async def wait_tree(self, process: _ProcessTransport) -> None:
        assert isinstance(process, _FakeProcess)
        await process._tree_exited.wait()

    async def kill_tree(self, process: _ProcessTransport) -> None:
        self.kill_calls += 1
        self.events.append("kill")
        if self.kill_exits:
            assert isinstance(process, _FakeProcess)
            process.exit(-9)
        if self.kill_error is not None:
            raise self.kill_error

    async def close_process_handles(self, process: _ProcessTransport) -> None:
        self.close_handles_calls += 1
        self.events.append("handles")
        self.close_handles_started.set()
        await self.release_close_handles.wait()
        if self.handles_error is not None:
            raise self.handles_error

    async def close_backend(self) -> None:
        self.close_backend_calls += 1


class _Observations:
    def __init__(self, *, fail: bool = False) -> None:
        self.items: list[HostingObservation] = []
        self.fail = fail

    def observe(self, observation: HostingObservation) -> None:
        self.items.append(observation)
        if self.fail:
            raise RuntimeError("observation sink must be isolated")


class _ForceTimeouts(_Timeouts):
    def __init__(self, count: int = 1) -> None:
        self.remaining = count
        self.calls = 0

    async def wait(self, operation: Awaitable[_T], seconds: float) -> _T:
        self.calls += 1
        if self.remaining:
            self.remaining -= 1
            task = asyncio.ensure_future(operation)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise TimeoutError
        return await operation


async def _wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not settle")


@_async_test
async def test_natural_exit_releases_capacity_after_owned_cleanup() -> None:
    first = _FakeProcess(stderr=(b"abc", b"def"))
    second = _FakeProcess()
    backend = _FakeBackend((first, second))
    first_preparation = _FakePreparationLease(_request())
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(max_processes=1, stderr_tail_bytes=4),
    )

    lease = await host.start(_request(), _FakePreparationPort(first_preparation))
    blocked_preparation = _FakePreparationPort(_FakePreparationLease(_request()))
    with pytest.raises(HostingError) as capacity:
        await host.start(_request(), blocked_preparation)
    assert capacity.value.category is HostingFailureCategory.CAPACITY_EXHAUSTED
    assert blocked_preparation.prepare_calls == 0

    first.exit(7)
    assert (await lease.wait()).return_code == 7
    await _wait_until(lambda: not host._leases)
    assert lease.stderr_tail().content == b"cdef"
    assert lease.stderr_tail().truncated is True
    assert first_preparation.close_calls == 1
    assert backend.close_handles_calls == 1

    second_lease = await host.start(
        _request(), _FakePreparationPort(_FakePreparationLease(_request()))
    )
    await second_lease.close()
    await host.close()


@_async_test
async def test_preparation_is_verified_at_final_point_and_closed_on_failure() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    verify_error = RuntimeError("stale material")
    preparation = _FakePreparationLease(_request(), verify_error=verify_error)
    observations = _Observations()
    host = _ProcessHost(backend, observation_sink=observations)

    with pytest.raises(HostingError) as caught:
        await host.start(_request(), _FakePreparationPort(preparation))

    assert caught.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert preparation.verify_calls == 1
    assert preparation.close_calls == 1
    assert not backend.spawn_requests
    assert [item.transition for item in observations.items] == [
        HostingLifecycleTransition.CAPACITY_RESERVED,
        HostingLifecycleTransition.PREPARING,
        HostingLifecycleTransition.FAILED,
        HostingLifecycleTransition.CLEANING,
        HostingLifecycleTransition.CLOSED,
    ]
    await host.close()


@_async_test
async def test_spawn_failure_and_early_exit_rollback_without_leaks() -> None:
    spawn_backend = _FakeBackend(())
    spawn_backend.spawn_error = OSError("private backend detail")
    spawn_preparation = _FakePreparationLease(_request())
    spawn_host = _ProcessHost(spawn_backend)
    with pytest.raises(HostingError) as spawn_failure:
        await spawn_host.start(_request(), _FakePreparationPort(spawn_preparation))
    assert spawn_failure.value.category is HostingFailureCategory.SPAWN_FAILED
    assert spawn_preparation.close_calls == 1

    early = _FakeProcess(return_code=2)
    early_backend = _FakeBackend((early,))
    early_preparation = _FakePreparationLease(_request())
    early_host = _ProcessHost(early_backend)
    with pytest.raises(HostingError) as early_failure:
        await early_host.start(_request(), _FakePreparationPort(early_preparation))
    assert early_failure.value.category is HostingFailureCategory.CHILD_EXITED_EARLY
    assert early_backend.terminate_calls == 0
    assert early_backend.kill_calls == 0
    assert early_backend.close_handles_calls == 1
    assert early_preparation.close_calls == 1
    await spawn_host.close()
    await early_host.close()


@_async_test
async def test_failed_start_retains_cleanup_debt_until_host_close_retries() -> None:
    process = _FakeProcess(return_code=2)
    backend = _FakeBackend((process,))
    backend.handles_error = OSError("transient handle cleanup")
    preparation = _FakePreparationLease(_request())
    host = _ProcessHost(backend)

    with pytest.raises(HostingError) as failure:
        await host.start(_request(), _FakePreparationPort(preparation))

    assert failure.value.category is HostingFailureCategory.CHILD_EXITED_EARLY
    assert isinstance(failure.value.__cause__, _CleanupError)
    assert host._state == "faulted"
    assert len(host._reservations) == 1
    with pytest.raises(HostingError) as faulted:
        await host.start(
            _request(), _FakePreparationPort(_FakePreparationLease(_request()))
        )
    assert faulted.value.category is HostingFailureCategory.HOST_CLOSED

    backend.handles_error = None
    await host.close()

    assert backend.close_handles_calls == 2
    assert not host._reservations
    assert preparation.close_calls == 1


@_async_test
async def test_natural_root_exit_reclaims_lingering_owned_tree_before_capacity() -> None:
    first = _FakeProcess()
    second = _FakeProcess()
    backend = _FakeBackend((first, second))
    backend.terminate_exits = False
    first_preparation = _FakePreparationLease(_request())
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(max_processes=1),
        timeouts=_ForceTimeouts(),
    )
    lease = await host.start(
        _request(), _FakePreparationPort(first_preparation)
    )

    first.exit(0, tree=False)
    assert (await lease.wait()).return_code == 0
    with pytest.raises(HostingError) as capacity:
        await host.start(
            _request(), _FakePreparationPort(_FakePreparationLease(_request()))
        )
    assert capacity.value.category is HostingFailureCategory.CAPACITY_EXHAUSTED
    await _wait_until(lambda: not host._leases)
    assert first_preparation.close_calls == 1
    assert backend.terminate_calls == 1
    assert backend.kill_calls == 1

    backend.terminate_exits = True
    second_lease = await host.start(
        _request(), _FakePreparationPort(_FakePreparationLease(_request()))
    )
    await second_lease.close()
    await host.close()


@_async_test
async def test_backend_missing_attachment_fails_closed_and_salvages_cleanup() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    backend.skip_attachment = True
    preparation = _FakePreparationLease(_request())
    host = _ProcessHost(backend)

    with pytest.raises(HostingError) as caught:
        await host.start(_request(), _FakePreparationPort(preparation))

    assert caught.value.category is HostingFailureCategory.SPAWN_FAILED
    assert process.return_code == -15
    assert backend.close_handles_calls == 1
    assert preparation.close_calls == 1
    await host.close()


@_async_test
async def test_terminate_uses_grace_then_kill_and_all_waiters_share_exit() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    backend.terminate_exits = False
    timeouts = _ForceTimeouts()
    preparation = _FakePreparationLease(_request())
    host = _ProcessHost(backend, timeouts=timeouts)
    lease = await host.start(_request(), _FakePreparationPort(preparation))

    first, second, waited = await asyncio.gather(
        lease.terminate(), lease.terminate(), lease.wait()
    )
    assert first == second == waited
    assert first.return_code == -9
    assert backend.terminate_calls == 1
    assert backend.kill_calls == 1
    assert backend.events.index("terminate") < backend.events.index("kill")
    await lease.close()
    assert process.close_stdin_calls == 1
    assert preparation.close_calls == 1
    await host.close()


@_async_test
async def test_close_aggregates_faults_but_attempts_every_reachable_cleanup() -> None:
    process = _FakeProcess()
    process.close_stdin_error = OSError("stdin fault")
    backend = _FakeBackend((process,))
    backend.terminate_exits = False
    backend.terminate_error = OSError("terminate fault")
    backend.kill_error = OSError("kill fault")
    backend.handles_error = OSError("handle fault")
    preparation = _FakePreparationLease(
        _request(), close_error=OSError("preparation fault")
    )
    host = _ProcessHost(backend, timeouts=_ForceTimeouts())
    lease = await host.start(_request(), _FakePreparationPort(preparation))

    with pytest.raises(_CleanupError) as caught:
        await lease.close()

    phases = {failure.phase for failure in caught.value.failures}
    assert {
        _CleanupPhase.STDIN,
        _CleanupPhase.TERMINATE,
        _CleanupPhase.KILL,
        _CleanupPhase.PROCESS_HANDLES,
    }.issubset(phases)
    assert backend.kill_calls == 1
    assert backend.close_handles_calls == 1
    assert preparation.close_calls == 1
    assert lease in host._leases

    backend.terminate_exits = True
    backend.terminate_error = None
    backend.kill_error = None
    backend.handles_error = None
    preparation.close_error = None
    await lease.close()
    assert backend.close_handles_calls == 2
    assert preparation.close_calls == 2
    assert lease not in host._leases
    await host.close()


@_async_test
async def test_tree_query_failure_still_reclaims_handles_and_preparation() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    backend.tree_exited_error = OSError("tree query fault")
    preparation = _FakePreparationLease(_request())
    host = _ProcessHost(backend)
    lease = await host.start(_request(), _FakePreparationPort(preparation))

    with pytest.raises(HostingError) as caught:
        await lease.close()

    assert caught.value.category is HostingFailureCategory.CLEANUP_FAILED
    assert backend.terminate_calls == 1
    assert backend.close_handles_calls == 1
    assert preparation.close_calls == 1
    await host.close()


@_async_test
async def test_force_settlement_timeout_is_bounded_and_releases_ownership() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    backend.terminate_exits = False
    backend.kill_exits = False
    preparation = _FakePreparationLease(_request())
    host = _ProcessHost(backend, timeouts=_ForceTimeouts(count=2))
    lease = await host.start(_request(), _FakePreparationPort(preparation))
    process.exit(0, tree=False)

    with pytest.raises(HostingError) as caught:
        await lease.close()

    assert caught.value.category is HostingFailureCategory.CLEANUP_FAILED
    assert backend.kill_calls == 1
    assert backend.close_handles_calls == 1
    assert preparation.close_calls == 1
    await host.close()
    # The lease close is the owner of this already-settled aggregate. The host
    # does not retain an unbounded historical error journal after releasing it.
    await host.close()


@_async_test
async def test_start_cancellation_after_attachment_is_shielded_until_reclaimed() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    backend.block_spawn = True
    preparation = _FakePreparationLease(_request())
    host = _ProcessHost(backend)

    start = asyncio.create_task(
        host.start(_request(), _FakePreparationPort(preparation))
    )
    await backend.spawn_attached.wait()
    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start

    assert process.return_code == -15
    assert backend.terminate_calls == 1
    assert backend.close_handles_calls == 1
    assert preparation.close_calls == 1
    await host.close()


@_async_test
async def test_cancellation_during_failed_start_rollback_takes_precedence() -> None:
    process = _FakeProcess(return_code=3)
    backend = _FakeBackend((process,))
    backend.release_close_handles.clear()
    preparation = _FakePreparationLease(_request())
    host = _ProcessHost(backend)
    start = asyncio.create_task(
        host.start(_request(), _FakePreparationPort(preparation))
    )
    await backend.close_handles_started.wait()

    start.cancel()
    await asyncio.sleep(0)
    assert not start.done()
    backend.release_close_handles.set()
    with pytest.raises(asyncio.CancelledError):
        await start

    assert backend.close_handles_calls == 1
    assert preparation.close_calls == 1
    await host.close()


@_async_test
async def test_host_close_fences_and_cancels_pending_start_before_returning() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    preparation = _FakePreparationLease(_request())
    port = _FakePreparationPort(preparation, block=True)
    host = _ProcessHost(backend)
    start = asyncio.create_task(host.start(_request(), port))
    await port.entered.wait()

    await asyncio.gather(host.close(), host.close())
    with pytest.raises(asyncio.CancelledError):
        await start
    assert preparation.close_calls == 0
    assert not backend.spawn_requests
    with pytest.raises(HostingError) as closed:
        await host.start(_request(), _FakePreparationPort(preparation))
    assert closed.value.category is HostingFailureCategory.HOST_CLOSED


@_async_test
async def test_reentrant_host_close_from_preparation_fails_without_deadlock() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    host = _ProcessHost(backend)
    preparation = _FakePreparationLease(_request())

    class _ReentrantPreparation:
        async def prepare(
            self, request: ProcessLaunchRequest
        ) -> _FakePreparationLease:
            await host.close()
            return preparation

    with pytest.raises(HostingError) as caught:
        await host.start(_request(), _ReentrantPreparation())
    assert caught.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert not backend.spawn_requests

    lease = await host.start(_request(), _FakePreparationPort(preparation))
    await lease.close()
    await host.close()


@_async_test
async def test_concurrent_lease_close_has_one_owner_and_delays_cancellation() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    backend.release_close_handles.clear()
    preparation = _FakePreparationLease(_request())
    host = _ProcessHost(backend)
    lease = await host.start(_request(), _FakePreparationPort(preparation))

    first = asyncio.create_task(lease.close())
    second = asyncio.create_task(lease.close())
    await backend.close_handles_started.wait()
    first.cancel()
    first.cancel()
    await asyncio.sleep(0)
    assert not first.done()
    backend.release_close_handles.set()

    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert backend.terminate_calls == 1
    assert backend.close_handles_calls == 1
    assert process.close_stdin_calls == 1
    assert preparation.close_calls == 1
    await host.close()


@_async_test
async def test_host_close_is_shared_and_delays_repeated_cancellation() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    backend.release_close_handles.clear()
    preparation = _FakePreparationLease(_request())
    host = _ProcessHost(backend)
    await host.start(_request(), _FakePreparationPort(preparation))

    first = asyncio.create_task(host.close())
    second = asyncio.create_task(host.close())
    await backend.close_handles_started.wait()
    first.cancel()
    first.cancel()
    await asyncio.sleep(0)
    assert not first.done()
    backend.release_close_handles.set()

    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    await host.close()
    assert backend.terminate_calls == 1
    assert backend.close_handles_calls == 1
    assert preparation.close_calls == 1


@_async_test
async def test_stream_modes_and_read_write_bounds_are_enforced() -> None:
    request = _request(stderr=ProcessStderrMode.PIPE)
    process = _FakeProcess(stdout=(b"out",), stderr=(b"error",))
    backend = _FakeBackend((process,))
    host = _ProcessHost(
        backend,
        limits=_ProcessHostLimits(max_read_bytes=5, max_write_bytes=3),
    )
    lease = await host.start(
        request, _FakePreparationPort(_FakePreparationLease(request))
    )

    assert await lease.read_stdout(3) == b"out"
    assert await lease.read_stderr(5) == b"error"
    await lease.write_stdin(b"abc")
    assert process.stdin_writes == [b"abc"]
    for invalid in (0, 6, True):
        with pytest.raises(HostingError) as read_bound:
            await lease.read_stdout(invalid)  # type: ignore[arg-type]
        assert read_bound.value.category is HostingFailureCategory.READ_BOUND_EXCEEDED
    with pytest.raises(HostingError) as write_bound:
        await lease.write_stdin(b"abcd")
    assert write_bound.value.category is HostingFailureCategory.WRITE_BOUND_EXCEEDED
    process.oversized_stdout = True
    with pytest.raises(HostingError) as backend_bound:
        await lease.read_stdout(5)
    assert backend_bound.value.category is HostingFailureCategory.READ_BOUND_EXCEEDED
    await lease.close()
    await host.close()


@_async_test
async def test_observation_failure_cannot_control_process_lifecycle() -> None:
    process = _FakeProcess()
    backend = _FakeBackend((process,))
    observations = _Observations(fail=True)
    host = _ProcessHost(backend, observation_sink=observations)

    lease = await host.start(
        _request(), _FakePreparationPort(_FakePreparationLease(_request()))
    )
    await lease.close()
    await host.close()

    assert observations.items
    assert all(item.backend_id == "fake-process-v1" for item in observations.items)
    assert all(item.session_id is None for item in observations.items)
    assert all(not hasattr(item, "payload") for item in observations.items)


def test_limits_are_strictly_finite_and_positive() -> None:
    for kwargs in (
        {"max_processes": 0},
        {"max_read_bytes": True},
        {"max_write_bytes": 0},
        {"stderr_tail_bytes": 0},
        {"termination_grace_seconds": float("inf")},
        {"stderr_drain_seconds": 0},
    ):
        with pytest.raises(ValueError):
            _ProcessHostLimits(**kwargs)  # type: ignore[arg-type]


def test_h1_runtime_contains_no_real_process_creation_primitive() -> None:
    from loushang.hosting import _process_backend, _process_host

    source = inspect.getsource(_process_backend) + inspect.getsource(_process_host)
    for forbidden in (
        "asyncio.create_subprocess_exec",
        "subprocess.Popen",
        "os.fork",
        "CreateProcess",
    ):
        assert forbidden not in source
