from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from functools import wraps
from pathlib import Path
from typing import ParamSpec

import pytest

from loushang.hosting import (
    ChildSessionRequest,
    HostingComponent,
    HostingError,
    HostingFailureCategory,
    HostingLifecycleTransition,
    HostingObservation,
    LaunchPreparationPort,
    ProcessLaunchRequest,
    ProcessLease,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
    create_child_session_host,
)
from loushang.hosting._child_session_host import _ChildSessionHost
from loushang.hosting._endpoint_backend import (
    _PlatformEndpointPair,
    _SingleUseProcessInheritance,
)
from loushang.hosting._endpoint_host import _InheritedEndpointHost
from loushang.hosting._process_backend import (
    _ProcessInheritance,
    _ProcessTransport,
)
from loushang.hosting._process_host import _ProcessHost, _ProcessHostLimits

_P = ParamSpec("_P")


def _async_test(
    function: Callable[_P, Awaitable[None]],
) -> Callable[_P, None]:
    @wraps(function)
    def run(*args: _P.args, **kwargs: _P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


def _process_request(tmp_path: Path | None = None) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(sys.executable, "-c", "pass"),
        cwd=str((tmp_path or Path.cwd()).resolve()),
        effective_environment=tuple(os.environ.items()),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.CAPTURE_TAIL,
        ),
    )


class _Preparation:
    def __init__(
        self,
        request: ProcessLaunchRequest,
        events: list[str],
        *,
        verify_error: BaseException | None = None,
    ) -> None:
        self.request = request
        self.events = events
        self.verify_error = verify_error
        self.close_calls = 0

    async def verify_current(self) -> None:
        self.events.append("verify")
        if self.verify_error is not None:
            raise self.verify_error

    async def close(self) -> None:
        self.events.append("preparation-close")
        self.close_calls += 1


class _PreparationPort:
    def __init__(
        self,
        preparation: _Preparation,
        events: list[str],
        *,
        prepare_error: BaseException | None = None,
    ) -> None:
        self.preparation = preparation
        self.events = events
        self.prepare_error = prepare_error
        self.prepare_calls = 0

    async def prepare(self, request: ProcessLaunchRequest) -> _Preparation:
        self.events.append("prepare")
        self.prepare_calls += 1
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.preparation


class _EndpointTransport:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.close_calls = 0
        self.close_error_once: BaseException | None = None
        self.close_entered = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_release.set()

    async def read(self, max_bytes: int) -> bytes:
        return b""

    async def write(self, data: bytes) -> None:
        return

    async def close(self) -> None:
        self.events.append("endpoint-close")
        self.close_calls += 1
        self.close_entered.set()
        await self.close_release.wait()
        if self.close_error_once is not None:
            error = self.close_error_once
            self.close_error_once = None
            raise error


class _EndpointBackend:
    backend_id = "fake-endpoint-v1"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.create_error: BaseException | None = None
        self.create_error_after_attach: BaseException | None = None
        self.transport_close_error_once: BaseException | None = None
        self.inheritance_backend_id = "fake-process-v1"
        self.transports: list[_EndpointTransport] = []
        self.child_close_calls = 0
        self.close_calls = 0

    async def create_pair(
        self,
        *,
        on_create: Callable[[_PlatformEndpointPair], None],
    ) -> _PlatformEndpointPair:
        self.events.append("endpoint-create")
        if self.create_error is not None:
            raise self.create_error
        transport = _EndpointTransport(self.events)
        transport.close_error_once = self.transport_close_error_once
        self.transports.append(transport)

        def close_child() -> None:
            self.events.append("child-copy-close")
            self.child_close_calls += 1

        pair = _PlatformEndpointPair(
            transport,
            _SingleUseProcessInheritance(
                backend_id=self.inheritance_backend_id,
                values=(51, 51),
                close_values=close_child,
            ),
        )
        on_create(pair)
        if self.create_error_after_attach is not None:
            raise self.create_error_after_attach
        return pair

    async def close_backend(self) -> None:
        self.close_calls += 1


class _Process:
    def __init__(self, events: list[str], *, early_exit: bool = False) -> None:
        self.events = events
        self._return_code: int | None = 0 if early_exit else None
        self._exited = asyncio.Event()
        self._tree_exited = asyncio.Event()
        if early_exit:
            self._exited.set()
            self._tree_exited.set()

    @property
    def return_code(self) -> int | None:
        return self._return_code

    async def read_stdout(self, max_bytes: int) -> bytes:
        return b""

    async def read_stderr(self, max_bytes: int) -> bytes:
        return b""

    async def write_stdin(self, data: bytes) -> None:
        raise AssertionError("session process stdin is reserved by endpoint")

    async def close_stdin(self) -> None:
        self.events.append("process-stdin-close")

    async def wait(self) -> int:
        await self._exited.wait()
        assert self._return_code is not None
        return self._return_code

    def exit(self, return_code: int = 0) -> None:
        self._return_code = return_code
        self._exited.set()
        self._tree_exited.set()


class _ProcessBackend:
    backend_id = "fake-process-v1"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.processes: list[_Process] = []
        self.spawn_error: BaseException | None = None
        self.early_exit = False
        self.block_spawn = False
        self.spawn_attached = asyncio.Event()
        self.spawn_release = asyncio.Event()
        self.close_handle_calls = 0
        self.close_handle_error_once: BaseException | None = None
        self.close_calls = 0

    async def spawn(
        self,
        request: ProcessLaunchRequest,
        *,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None = None,
    ) -> _Process:
        self.events.append("spawn")
        if self.spawn_error is not None:
            raise self.spawn_error
        assert inheritance is not None
        assert inheritance.claim(backend_id=self.backend_id) == (51, 51)
        process = _Process(self.events, early_exit=self.early_exit)
        self.processes.append(process)
        inheritance.mark_transferred()
        on_spawn(process)
        self.spawn_attached.set()
        if self.block_spawn:
            await self.spawn_release.wait()
        return process

    def tree_exited(self, process: _ProcessTransport) -> bool:
        assert isinstance(process, _Process)
        return process._tree_exited.is_set()

    async def wait_tree(self, process: _ProcessTransport) -> None:
        assert isinstance(process, _Process)
        await process._tree_exited.wait()

    async def terminate_tree(self, process: _ProcessTransport) -> None:
        self.events.append("process-terminate")
        assert isinstance(process, _Process)
        process.exit(-15)

    async def kill_tree(self, process: _ProcessTransport) -> None:
        self.events.append("process-kill")
        assert isinstance(process, _Process)
        process.exit(-9)

    async def close_process_handles(self, process: _ProcessTransport) -> None:
        self.events.append("process-handles-close")
        self.close_handle_calls += 1
        if self.close_handle_error_once is not None:
            error = self.close_handle_error_once
            self.close_handle_error_once = None
            raise error

    async def close_backend(self) -> None:
        self.close_calls += 1


def _fake_host(
    events: list[str],
    *,
    max_sessions: int = 1,
) -> tuple[_ChildSessionHost, _ProcessBackend, _EndpointBackend]:
    process_backend = _ProcessBackend(events)
    endpoint_backend = _EndpointBackend(events)
    process_host = _ProcessHost(
        process_backend,
        limits=_ProcessHostLimits(max_processes=max_sessions),
    )
    endpoint_host = _InheritedEndpointHost(
        endpoint_backend,
        max_endpoints=max_sessions,
    )
    return (
        _ChildSessionHost(
            process_host,
            endpoint_host,
            max_sessions=max_sessions,
        ),
        process_backend,
        endpoint_backend,
    )


async def _wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not settle")


@_async_test
async def test_child_session_orders_transaction_and_natural_exit_releases_all() -> None:
    events: list[str] = []
    host, process_backend, endpoint_backend = _fake_host(events)
    request = _process_request()
    preparation = _Preparation(request, events)

    lease = await host.start(
        ChildSessionRequest(request), _PreparationPort(preparation, events)
    )

    assert events.index("prepare") < events.index("endpoint-create")
    assert events.index("endpoint-create") < events.index("verify")
    assert events.index("verify") < events.index("spawn")
    assert events.index("spawn") < events.index("child-copy-close")
    process_backend.processes[0].exit(7)
    assert (await lease.process.wait()).return_code == 7
    await _wait_until(lambda: preparation.close_calls == 1)
    await _wait_until(lambda: endpoint_backend.transports[0].close_calls == 1)
    await _wait_until(lambda: not host._leases)

    replacement_preparation = _Preparation(request, events)
    replacement = await host.start(
        ChildSessionRequest(request),
        _PreparationPort(replacement_preparation, events),
    )
    await replacement.close()
    await host.close()

    assert process_backend.close_calls == 1
    assert endpoint_backend.close_calls == 1


@_async_test
async def test_child_session_capacity_precedes_caller_preparation() -> None:
    events: list[str] = []
    host, _, _ = _fake_host(events)
    request = _process_request()
    first = await host.start(
        ChildSessionRequest(request),
        _PreparationPort(_Preparation(request, events), events),
    )
    blocked = _PreparationPort(_Preparation(request, events), events)

    with pytest.raises(HostingError) as capacity:
        await host.start(ChildSessionRequest(request), blocked)
    assert capacity.value.category is HostingFailureCategory.CAPACITY_EXHAUSTED
    assert blocked.prepare_calls == 0

    await first.close()
    await host.close()


@_async_test
async def test_child_session_validates_initial_topology_before_capacity() -> None:
    events: list[str] = []
    host, process_backend, endpoint_backend = _fake_host(events)
    valid = _process_request()
    invalid = ProcessLaunchRequest(
        argv=valid.argv,
        cwd=valid.cwd,
        effective_environment=valid.effective_environment,
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.PIPE,
            stdout=ProcessStdoutMode.PIPE,
            stderr=valid.streams.stderr,
        ),
    )
    port = _PreparationPort(_Preparation(invalid, events), events)

    with pytest.raises(HostingError) as failure:
        await host.start(ChildSessionRequest(invalid), port)

    assert failure.value.category is HostingFailureCategory.ENDPOINT_TRANSFER_FAILED
    assert port.prepare_calls == 0
    assert not host._reservations
    assert not process_backend.processes
    assert not endpoint_backend.transports
    await host.close()


@_async_test
async def test_child_session_revalidates_prepared_topology_before_endpoint() -> None:
    events: list[str] = []
    host, process_backend, endpoint_backend = _fake_host(events)
    request = _process_request()
    prepared_request = ProcessLaunchRequest(
        argv=request.argv,
        cwd=request.cwd,
        effective_environment=request.effective_environment,
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.PIPE,
            stdout=ProcessStdoutMode.PIPE,
            stderr=request.streams.stderr,
        ),
    )
    preparation = _Preparation(prepared_request, events)

    with pytest.raises(HostingError) as failure:
        await host.start(
            ChildSessionRequest(request),
            _PreparationPort(preparation, events),
        )

    assert failure.value.category is HostingFailureCategory.ENDPOINT_TRANSFER_FAILED
    assert preparation.close_calls == 1
    assert not process_backend.processes
    assert not endpoint_backend.transports
    await host.close()


@pytest.mark.parametrize(
    ("failure_point", "expected_category"),
    (
        ("prepare", HostingFailureCategory.PREPARATION_FAILED),
        ("endpoint", HostingFailureCategory.ENDPOINT_UNAVAILABLE),
        ("verify", HostingFailureCategory.PREPARATION_FAILED),
        ("spawn", HostingFailureCategory.SPAWN_FAILED),
        ("early", HostingFailureCategory.CHILD_EXITED_EARLY),
    ),
)
@_async_test
async def test_child_session_failure_matrix_publishes_neither_and_reclaims_all(
    failure_point: str,
    expected_category: HostingFailureCategory,
) -> None:
    events: list[str] = []
    host, process_backend, endpoint_backend = _fake_host(events)
    request = _process_request()
    preparation = _Preparation(
        request,
        events,
        verify_error=OSError("verify") if failure_point == "verify" else None,
    )
    port = _PreparationPort(
        preparation,
        events,
        prepare_error=OSError("prepare") if failure_point == "prepare" else None,
    )
    if failure_point == "endpoint":
        endpoint_backend.create_error = HostingError(
            HostingFailureCategory.ENDPOINT_UNAVAILABLE,
            "endpoint unavailable",
        )
    if failure_point == "spawn":
        process_backend.spawn_error = OSError("spawn")
    if failure_point == "early":
        process_backend.early_exit = True

    with pytest.raises(HostingError) as failure:
        await host.start(ChildSessionRequest(request), port)
    assert failure.value.category is expected_category
    await host.close()

    assert not host._leases
    assert not host._reservations
    if failure_point != "prepare":
        assert preparation.close_calls == 1
    if failure_point in {"verify", "spawn", "early"}:
        assert endpoint_backend.transports[0].close_calls == 1
    if failure_point == "early":
        assert process_backend.close_handle_calls == 1


@_async_test
async def test_child_session_backend_mismatch_reclaims_before_spawn() -> None:
    events: list[str] = []
    host, process_backend, endpoint_backend = _fake_host(events)
    endpoint_backend.inheritance_backend_id = "foreign-process-v1"
    request = _process_request()
    preparation = _Preparation(request, events)

    with pytest.raises(HostingError) as failure:
        await host.start(
            ChildSessionRequest(request),
            _PreparationPort(preparation, events),
        )

    assert failure.value.category is HostingFailureCategory.ENDPOINT_TRANSFER_FAILED
    assert preparation.close_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1
    assert process_backend.processes == []
    await host.close()


@_async_test
async def test_child_session_retains_nested_endpoint_acquisition_debt() -> None:
    events: list[str] = []
    host, process_backend, endpoint_backend = _fake_host(events)
    endpoint_backend.create_error_after_attach = HostingError(
        HostingFailureCategory.ENDPOINT_UNAVAILABLE,
        "endpoint failed after attachment",
    )
    endpoint_backend.transport_close_error_once = OSError("transient endpoint close")
    request = _process_request()

    with pytest.raises(HostingError) as failure:
        await host.start(
            ChildSessionRequest(request),
            _PreparationPort(_Preparation(request, events), events),
        )

    assert failure.value.category is HostingFailureCategory.ENDPOINT_UNAVAILABLE
    assert host._state == "faulted"
    assert len(host._reservations) == 1
    assert process_backend.processes == []
    with pytest.raises(BaseExceptionGroup):
        await host.close()
    assert endpoint_backend.transports[0].close_calls == 2
    assert not host._endpoint_host._reservations


@_async_test
async def test_child_session_retains_nested_process_rollback_debt() -> None:
    events: list[str] = []
    host, process_backend, endpoint_backend = _fake_host(events)
    process_backend.early_exit = True
    process_backend.close_handle_error_once = OSError("transient process handles")
    request = _process_request()

    with pytest.raises(HostingError) as failure:
        await host.start(
            ChildSessionRequest(request),
            _PreparationPort(_Preparation(request, events), events),
        )

    assert failure.value.category is HostingFailureCategory.CHILD_EXITED_EARLY
    assert host._state == "faulted"
    assert len(host._reservations) == 1
    with pytest.raises(BaseExceptionGroup):
        await host.close()
    assert process_backend.close_handle_calls == 2
    assert endpoint_backend.transports[0].close_calls == 1
    assert not host._process_host._reservations


@_async_test
async def test_child_session_cancellation_after_process_attachment_rolls_back() -> None:
    events: list[str] = []
    host, process_backend, endpoint_backend = _fake_host(events)
    process_backend.block_spawn = True
    request = _process_request()
    preparation = _Preparation(request, events)
    start = asyncio.create_task(
        host.start(
            ChildSessionRequest(request),
            _PreparationPort(preparation, events),
        )
    )
    await process_backend.spawn_attached.wait()

    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start
    await host.close()

    assert preparation.close_calls == 1
    assert process_backend.close_handle_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1


@_async_test
async def test_host_close_waits_for_session_transaction_not_callers_later_work() -> None:
    events: list[str] = []
    host, process_backend, endpoint_backend = _fake_host(events)
    process_backend.block_spawn = True
    request = _process_request()
    caller_continued = asyncio.Event()
    caller_release = asyncio.Event()

    async def caller() -> None:
        try:
            await host.start(
                ChildSessionRequest(request),
                _PreparationPort(_Preparation(request, events), events),
            )
        except asyncio.CancelledError:
            caller_continued.set()
            await caller_release.wait()

    caller_task = asyncio.create_task(caller())
    await process_backend.spawn_attached.wait()

    await asyncio.wait_for(host.close(), 1.0)
    assert caller_continued.is_set()
    assert not caller_task.done()
    assert process_backend.close_handle_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1

    caller_release.set()
    await caller_task


@_async_test
async def test_host_close_fences_aggregate_publication_after_process_publication() -> None:
    events: list[str] = []
    process_backend = _ProcessBackend(events)
    endpoint_backend = _EndpointBackend(events)

    class _PublicationFenceProcessHost(_ProcessHost):
        def __init__(self) -> None:
            super().__init__(
                process_backend,
                limits=_ProcessHostLimits(max_processes=1),
            )
            self.process_published = asyncio.Event()
            self.release = asyncio.Event()

        async def _start_with_inheritance(
            self,
            request: ProcessLaunchRequest,
            preparation: LaunchPreparationPort,
            *,
            inheritance: _ProcessInheritance | None,
            session_id: str | None,
        ) -> ProcessLease:
            lease = await super()._start_with_inheritance(
                request,
                preparation,
                inheritance=inheritance,
                session_id=session_id,
            )
            self.process_published.set()
            await self.release.wait()
            return lease

    process_host = _PublicationFenceProcessHost()
    host = _ChildSessionHost(
        process_host,
        _InheritedEndpointHost(endpoint_backend, max_endpoints=1),
        max_sessions=1,
    )
    request = _process_request()
    preparation = _Preparation(request, events)
    start = asyncio.create_task(
        host.start(
            ChildSessionRequest(request),
            _PreparationPort(preparation, events),
        )
    )
    await process_host.process_published.wait()

    await host.close()
    with pytest.raises(asyncio.CancelledError):
        await start

    assert not host._leases
    assert not process_host._leases
    assert preparation.close_calls == 1
    assert process_backend.close_handle_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1


@_async_test
async def test_child_session_observations_share_correlation_and_cannot_veto() -> None:
    events: list[str] = []
    observations: list[HostingObservation] = []

    class _Sink:
        def observe(self, observation: HostingObservation) -> None:
            observations.append(observation)
            raise RuntimeError("observer cannot veto lifecycle")

    process_backend = _ProcessBackend(events)
    endpoint_backend = _EndpointBackend(events)
    sink = _Sink()
    host = _ChildSessionHost(
        _ProcessHost(
            process_backend,
            limits=_ProcessHostLimits(max_processes=1),
            observation_sink=sink,
        ),
        _InheritedEndpointHost(
            endpoint_backend,
            max_endpoints=1,
            observation_sink=sink,
        ),
        max_sessions=1,
        observation_sink=sink,
    )
    request = _process_request()
    lease = await host.start(
        ChildSessionRequest(request),
        _PreparationPort(_Preparation(request, events), events),
    )
    await asyncio.gather(lease.close(), lease.close())
    await host.close()

    correlated = [item for item in observations if item.session_id == lease.session_id]
    assert {item.component for item in correlated} == {
        HostingComponent.PROCESS,
        HostingComponent.ENDPOINT,
        HostingComponent.SESSION,
    }


@_async_test
async def test_cancelled_session_close_waiter_does_not_repeat_successful_owner() -> None:
    events: list[str] = []
    observations: list[HostingObservation] = []

    class _Sink:
        def observe(self, observation: HostingObservation) -> None:
            observations.append(observation)

    process_backend = _ProcessBackend(events)
    endpoint_backend = _EndpointBackend(events)
    sink = _Sink()
    host = _ChildSessionHost(
        _ProcessHost(
            process_backend,
            limits=_ProcessHostLimits(max_processes=1),
            observation_sink=sink,
        ),
        _InheritedEndpointHost(
            endpoint_backend,
            max_endpoints=1,
            observation_sink=sink,
        ),
        max_sessions=1,
        observation_sink=sink,
    )
    request = _process_request()
    preparation = _Preparation(request, events)
    lease = await host.start(
        ChildSessionRequest(request),
        _PreparationPort(preparation, events),
    )
    transport = endpoint_backend.transports[0]
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

    session_transitions = [
        item.transition
        for item in observations
        if item.component is HostingComponent.SESSION
        and item.session_id == lease.session_id
    ]
    assert session_transitions.count(HostingLifecycleTransition.CLEANING) == 1
    assert session_transitions.count(HostingLifecycleTransition.CLOSED) == 1
    assert process_backend.close_handle_calls == 1
    assert transport.close_calls == 1
    assert preparation.close_calls == 1


@_async_test
async def test_child_session_cleanup_failure_faults_host_and_is_retryable() -> None:
    events: list[str] = []
    host, _, endpoint_backend = _fake_host(events)
    request = _process_request()
    lease = await host.start(
        ChildSessionRequest(request),
        _PreparationPort(_Preparation(request, events), events),
    )
    endpoint_backend.transports[0].close_error_once = OSError("endpoint close")

    with pytest.raises(BaseExceptionGroup):
        await lease.close()
    blocked = _PreparationPort(_Preparation(request, events), events)
    with pytest.raises(HostingError) as faulted:
        await host.start(ChildSessionRequest(request), blocked)
    assert faulted.value.category is HostingFailureCategory.HOST_CLOSED
    assert blocked.prepare_calls == 0

    await lease.close()
    await host.close()
    assert endpoint_backend.transports[0].close_calls == 2


@_async_test
async def test_child_session_rollback_failure_retains_capacity_debt() -> None:
    events: list[str] = []
    host, _, endpoint_backend = _fake_host(events)
    request = _process_request()
    preparation = _Preparation(request, events, verify_error=OSError("stale"))
    endpoint_backend.transport_close_error_once = OSError("endpoint close")
    with pytest.raises(HostingError):
        await host.start(
            ChildSessionRequest(request),
            _PreparationPort(preparation, events),
        )

    assert host._state == "faulted"
    assert len(host._reservations) == 1
    with pytest.raises(HostingError) as faulted:
        await host.start(
            ChildSessionRequest(request),
            _PreparationPort(_Preparation(request, events), events),
        )
    assert faulted.value.category is HostingFailureCategory.HOST_CLOSED
    with pytest.raises(BaseExceptionGroup):
        await host.close()


@pytest.mark.skipif(os.name != "posix", reason="native POSIX child session")
@_async_test
async def test_public_posix_child_session_round_trip(tmp_path: Path) -> None:
    request = ProcessLaunchRequest(
        argv=(
            sys.executable,
            "-c",
            (
                "import sys; data=sys.stdin.buffer.read(4); "
                "sys.stdout.buffer.write(data.upper()); sys.stdout.buffer.flush()"
            ),
        ),
        cwd=str(tmp_path.resolve()),
        effective_environment=tuple(os.environ.items()),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.CAPTURE_TAIL,
        ),
    )
    preparation = _Preparation(request, [])
    host = create_child_session_host(max_sessions=1)
    lease = await host.start(
        ChildSessionRequest(request), _PreparationPort(preparation, [])
    )

    await lease.endpoint.write(b"ping")
    assert await lease.endpoint.read(4) == b"PING"
    assert (await lease.process.wait()).return_code == 0
    await lease.close()
    await host.close()

    assert preparation.close_calls == 1


@pytest.mark.parametrize(
    "overrides",
    (
        {"max_sessions": 0},
        {"max_read_bytes": 0},
        {"max_write_bytes": 0},
        {"stderr_tail_bytes": 0},
        {"termination_grace_seconds": float("inf")},
        {"stderr_drain_seconds": 0.0},
        {"endpoint_io_settlement_seconds": True},
    ),
)
def test_child_session_factory_rejects_invalid_bounds(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        create_child_session_host(**overrides)  # type: ignore[arg-type]
