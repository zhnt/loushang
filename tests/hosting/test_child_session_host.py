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
from loushang.hosting._launch_preparation import (
    _CapturedLaunchMaterial,
    _LaunchCaptureBackend,
    _LaunchCapturePort,
    _LaunchCaptureSpec,
    _ManagedLaunchPreparationPort,
    _ManagedLaunchPreparationResult,
    _ManagedSpawnEffect,
    _OpaqueLaunchBinding,
    _ReservationLaunchCapture,
)
from loushang.hosting._process_backend import (
    _ProcessBackend as _ProcessBackendPort,
)
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
        self.close_error_once: BaseException | None = None
        self.close_calls = 0

    async def verify_current(self) -> None:
        self.events.append("verify")
        if self.verify_error is not None:
            raise self.verify_error

    async def close(self) -> None:
        self.events.append("preparation-close")
        self.close_calls += 1
        if self.close_error_once is not None:
            error = self.close_error_once
            self.close_error_once = None
            raise error


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
        self.skip_managed_attachment = False
        self.return_different_managed_process = False
        self.managed_process_created = asyncio.Event()
        self.block_after_managed_claim = False
        self.managed_claimed = asyncio.Event()
        self.managed_claim_release = asyncio.Event()
        self.managed_claim_release.set()
        self.ambiguous_spawn_error: BaseException | None = None
        self.not_created_after_effect_error: BaseException | None = None
        self.skip_managed_effect_gate = False
        self.callback_error_as_not_created = False
        self.spawn_attached = asyncio.Event()
        self.spawn_release = asyncio.Event()
        self.close_handle_calls = 0
        self.close_handle_error_once: BaseException | None = None
        self.close_calls = 0
        self.expected_inheritance = (51, 51)

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
        inherited = inheritance.claim(backend_id=self.backend_id)
        self.events.append("inheritance-claimed")
        assert inherited == self.expected_inheritance
        self.events.append("process-create")
        process = _Process(self.events, early_exit=self.early_exit)
        self.processes.append(process)
        inheritance.mark_transferred()
        on_spawn(process)
        self.spawn_attached.set()
        if self.block_spawn:
            await self.spawn_release.wait()
        return process

    async def spawn_managed(
        self,
        request: ProcessLaunchRequest,
        *,
        material: _CapturedMaterial,
        effect: _ManagedSpawnEffect,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None,
    ) -> _Process:
        self.events.append("spawn")
        if self.spawn_error is not None:
            raise effect.not_created(self.spawn_error)
        assert inheritance is not None
        endpoint_values = inheritance.claim(backend_id=self.backend_id)
        preparation_values = material.claim_for_spawn(backend_id=self.backend_id)
        if (
            len(preparation_values) != material.inherited_slot_count
            or any(type(value) is not int or value < 0 for value in preparation_values)
            or len(set(preparation_values)) != len(preparation_values)
        ):
            raise effect.not_created(
                HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "managed preparation returned an invalid inheritance manifest",
                )
            )
        if set(endpoint_values) & set(preparation_values):
            raise effect.not_created(
                HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "endpoint and preparation inheritance slots collide",
                )
            )
        inherited = (*endpoint_values, *preparation_values)
        self.events.append("inheritance-claimed")
        assert inherited == self.expected_inheritance
        self.managed_claimed.set()
        if self.block_after_managed_claim:
            await self.managed_claim_release.wait()
        if self.ambiguous_spawn_error is not None:
            raise self.ambiguous_spawn_error
        if not self.skip_managed_effect_gate:
            effect.begin_effect()
        self.events.append("process-create")
        process = _Process(self.events, early_exit=self.early_exit)
        self.processes.append(process)
        self.managed_process_created.set()
        if self.not_created_after_effect_error is not None:
            raise effect.not_created(self.not_created_after_effect_error)
        if not self.skip_managed_attachment:
            try:
                on_spawn(process)
            except BaseException as callback_error:
                if self.callback_error_as_not_created:
                    raise effect.not_created(callback_error) from callback_error
                raise
        inheritance.mark_transferred()
        material.mark_transferred()
        self.spawn_attached.set()
        if self.block_spawn:
            await self.spawn_release.wait()
        if self.return_different_managed_process:
            different = _Process(self.events, early_exit=self.early_exit)
            self.processes.append(different)
            return different
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


class _CapturedMaterial:
    backend_id = "fake-process-v1"

    def __init__(
        self,
        request: ProcessLaunchRequest,
        attempt_id: str,
        attempt_token: object,
        events: list[str],
        *,
        slots: tuple[int, ...] = (61, 62),
        profile_id: str = "fake-profile-v1",
        execution_closure: tuple[str, ...] = (
            "launcher:fake-v1",
            "payload:fake-v1",
        ),
    ) -> None:
        self.request = request
        self.attempt_id = attempt_id
        self.attempt_token = attempt_token
        self.events = events
        self.slots = slots
        self.profile_id = profile_id
        self.execution_closure = execution_closure
        self.verify_error: BaseException | None = None
        self.close_error_once: BaseException | None = None
        self.transfer_error: BaseException | None = None
        self.block_verify = False
        self.verify_entered = asyncio.Event()
        self.verify_release = asyncio.Event()
        self.verify_release.set()
        self.claim_calls = 0
        self.transfer_calls = 0
        self.close_calls = 0

    @property
    def inherited_slot_count(self) -> int:
        return len(self.slots)

    async def verify_current(self, request: ProcessLaunchRequest) -> None:
        self.events.append("native-verify")
        assert request == self.request
        self.verify_entered.set()
        if self.block_verify:
            await self.verify_release.wait()
        if self.verify_error is not None:
            raise self.verify_error

    def claim_for_spawn(self, *, backend_id: str) -> tuple[int, ...]:
        self.events.append("native-claim")
        self.claim_calls += 1
        assert backend_id == self.backend_id
        return self.slots

    def mark_transferred(self) -> None:
        self.events.append("native-transfer")
        self.transfer_calls += 1
        if self.transfer_error is not None:
            raise self.transfer_error

    async def spawn(
        self,
        backend: _ProcessBackendPort,
        request: ProcessLaunchRequest,
        *,
        effect: _ManagedSpawnEffect,
        on_spawn: Callable[[_ProcessTransport], None],
        inheritance: _ProcessInheritance | None,
    ) -> _ProcessTransport:
        if not isinstance(backend, _ProcessBackend):
            raise effect.not_created(
                HostingError(
                    HostingFailureCategory.ENDPOINT_TRANSFER_FAILED,
                    "fake material received a mismatched backend",
                )
            )
        return await backend.spawn_managed(
            request,
            material=self,
            effect=effect,
            on_spawn=on_spawn,
            inheritance=inheritance,
        )

    async def close(self) -> None:
        self.events.append("native-close")
        self.close_calls += 1
        if self.close_error_once is not None:
            error = self.close_error_once
            self.close_error_once = None
            raise error


class _CaptureBackend:
    backend_id = "fake-process-v1"

    def __init__(
        self,
        events: list[str],
        *,
        slots: tuple[int, ...] = (61, 62),
    ) -> None:
        self.events = events
        self.slots = slots
        self.materials: list[_CapturedMaterial] = []
        self.skip_attachment = False
        self.return_different = False
        self.different_close_error_once: BaseException | None = None
        self.error_before_attachment: BaseException | None = None
        self.replay_material: _CapturedMaterial | None = None
        self.error_after_attachment: BaseException | None = None
        self.block_after_attachment = False
        self.attached = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def capture(
        self,
        spec: _LaunchCaptureSpec,
        *,
        attempt_id: str,
        attempt_token: object,
        on_capture: Callable[[_CapturedLaunchMaterial], None],
    ) -> _CapturedMaterial:
        self.events.append("native-capture")
        if self.error_before_attachment is not None:
            raise self.error_before_attachment
        if self.replay_material is not None:
            on_capture(self.replay_material)
            return self.replay_material
        material = _CapturedMaterial(
            spec.request,
            attempt_id,
            attempt_token,
            self.events,
            slots=self.slots,
            profile_id=spec.profile_id,
            execution_closure=spec.execution_closure,
        )
        self.materials.append(material)
        if not self.skip_attachment:
            try:
                on_capture(material)
            except BaseException:
                await material.close()
                raise
            self.events.append("native-attached")
            self.attached.set()
        if self.block_after_attachment:
            await self.release.wait()
        if self.error_after_attachment is not None:
            raise self.error_after_attachment
        if self.return_different:
            different = _CapturedMaterial(
                spec.request,
                attempt_id,
                attempt_token,
                self.events,
                slots=self.slots,
                profile_id=spec.profile_id,
                execution_closure=spec.execution_closure,
            )
            self.materials.append(different)
            different.close_error_once = self.different_close_error_once
            return different
        return material


class _ManagedPreparationPort(_ManagedLaunchPreparationPort):
    def __init__(
        self,
        request: ProcessLaunchRequest,
        events: list[str],
        *,
        profile_id: str = "fake-profile-v1",
        execution_closure: tuple[str, ...] = (
            "launcher:fake-v1",
            "payload:fake-v1",
        ),
    ) -> None:
        self.preparation = _Preparation(request, events)
        self.events = events
        self.profile_id = profile_id
        self.execution_closure = execution_closure
        self.capture_returned = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.error_after_capture: BaseException | None = None
        self.return_request: ProcessLaunchRequest | None = None
        self.binding_override: _OpaqueLaunchBinding | None = None

    async def prepare(self, request: ProcessLaunchRequest) -> _Preparation:
        raise AssertionError("managed preparation must use its private port")

    async def prepare_managed(
        self,
        request: ProcessLaunchRequest,
        capture: _LaunchCapturePort,
    ) -> _ManagedLaunchPreparationResult:
        returned = False
        try:
            self.events.append("managed-prepare")
            binding = await capture.capture(
                _LaunchCaptureSpec(
                    request=request,
                    profile_id=self.profile_id,
                    execution_closure=self.execution_closure,
                )
            )
            self.events.append("capture-returned")
            self.capture_returned.set()
            await self.release.wait()
            if self.error_after_capture is not None:
                raise self.error_after_capture
            if self.return_request is not None:
                self.preparation.request = self.return_request
            result = _ManagedLaunchPreparationResult(
                self.preparation,
                self.binding_override or binding,
            )
            returned = True
            return result
        finally:
            if not returned:
                cleanup = asyncio.create_task(self.preparation.close())
                await asyncio.shield(cleanup)


def _fake_host(
    events: list[str],
    *,
    max_sessions: int = 1,
    launch_capture_backend: _LaunchCaptureBackend | None = None,
    max_capture_slots: int = 8,
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
            launch_capture_backend=launch_capture_backend,
            max_capture_slots=max_capture_slots,
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


@_async_test
async def test_managed_launch_joins_opaque_material_into_one_spawn_manifest() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)

    lease = await host.start(ChildSessionRequest(request), preparation)

    material = capture_backend.materials[0]
    ordered = (
        "managed-prepare",
        "native-capture",
        "native-attached",
        "capture-returned",
        "endpoint-create",
        "verify",
        "native-verify",
        "spawn",
        "native-claim",
        "process-create",
        "child-copy-close",
        "native-transfer",
    )
    assert tuple(sorted(ordered, key=events.index)) == ordered
    assert material.claim_calls == 1
    assert material.transfer_calls == 1

    await lease.close()
    await host.close()

    assert preparation.preparation.close_calls == 1
    assert material.close_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1


@_async_test
async def test_managed_launch_callback_failure_after_capture_reclaims_before_endpoint() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)
    preparation.error_after_capture = OSError("caller failed after capture")

    with pytest.raises(HostingError) as failure:
        await host.start(ChildSessionRequest(request), preparation)

    assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert preparation.preparation.close_calls == 1
    assert capture_backend.materials[0].close_calls == 1
    assert process_backend.processes == []
    assert endpoint_backend.transports == []
    await host.close()


@_async_test
async def test_managed_launch_cancellation_after_capture_reclaims_reservation() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)
    preparation.release.clear()
    start = asyncio.create_task(
        host.start(ChildSessionRequest(request), preparation)
    )
    await preparation.capture_returned.wait()

    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start
    await host.close()

    assert capture_backend.materials[0].close_calls == 1
    assert preparation.preparation.close_calls == 1
    assert process_backend.processes == []
    assert endpoint_backend.transports == []


@_async_test
async def test_managed_launch_capture_is_single_use_under_concurrency() -> None:
    events: list[str] = []
    backend = _CaptureBackend(events)
    request = _process_request()
    attached: list[_CapturedLaunchMaterial] = []
    capture = _ReservationLaunchCapture(
        backend,
        attempt_id="attempt-1",
        max_inherited_slots=8,
        on_capture=attached.append,
        on_orphan=attached.append,
    )
    spec = _LaunchCaptureSpec(
        request=request,
        profile_id="fake-profile-v1",
        execution_closure=("launcher:fake-v1", "payload:fake-v1"),
    )
    backend.block_after_attachment = True
    backend.release.clear()
    first = asyncio.create_task(capture.capture(spec))
    second = asyncio.create_task(capture.capture(spec))
    await backend.attached.wait()
    assert not first.done()
    assert not second.done()
    backend.release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert sum(isinstance(result, _OpaqueLaunchBinding) for result in results) == 1
    failures = [result for result in results if isinstance(result, HostingError)]
    assert len(failures) == 1
    assert failures[0].category is HostingFailureCategory.PREPARATION_FAILED
    assert len(backend.materials) == 1
    assert attached == [backend.materials[0]]
    await backend.materials[0].close()


@_async_test
async def test_managed_launch_rejects_retarget_before_endpoint_acquisition() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)
    preparation.return_request = ProcessLaunchRequest(
        argv=(sys.executable, "-c", "raise SystemExit(3)"),
        cwd=request.cwd,
        effective_environment=request.effective_environment,
        streams=request.streams,
    )

    with pytest.raises(HostingError) as failure:
        await host.start(ChildSessionRequest(request), preparation)

    assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert preparation.preparation.close_calls == 1
    assert capture_backend.materials[0].close_calls == 1
    assert process_backend.processes == []
    assert endpoint_backend.transports == []
    await host.close()


@_async_test
async def test_managed_launch_rejects_cross_reservation_binding() -> None:
    events: list[str] = []
    request = _process_request()
    backend = _CaptureBackend(events)
    first_materials: list[_CapturedLaunchMaterial] = []
    second_materials: list[_CapturedLaunchMaterial] = []
    first = _ReservationLaunchCapture(
        backend,
        attempt_id="attempt-1",
        max_inherited_slots=8,
        on_capture=first_materials.append,
        on_orphan=first_materials.append,
    )
    second = _ReservationLaunchCapture(
        backend,
        attempt_id="attempt-2",
        max_inherited_slots=8,
        on_capture=second_materials.append,
        on_orphan=second_materials.append,
    )
    spec = _LaunchCaptureSpec(
        request=request,
        profile_id="fake-profile-v1",
        execution_closure=("launcher:fake-v1", "payload:fake-v1"),
    )
    binding = await first.capture(spec)
    await second.capture(spec)

    with pytest.raises(HostingError) as failure:
        second.bind_result(
            _ManagedLaunchPreparationResult(_Preparation(request, events), binding)
        )

    assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED
    await asyncio.gather(first_materials[0].close(), second_materials[0].close())


@_async_test
async def test_managed_launch_slot_bound_and_collision_fail_closed() -> None:
    for slots, expected_category in (
        (tuple(range(9)), HostingFailureCategory.CAPACITY_EXHAUSTED),
        ((51, 61), HostingFailureCategory.ENDPOINT_TRANSFER_FAILED),
        ((-1, 61), HostingFailureCategory.ENDPOINT_TRANSFER_FAILED),
        ((61, 61), HostingFailureCategory.ENDPOINT_TRANSFER_FAILED),
    ):
        events: list[str] = []
        capture_backend = _CaptureBackend(events, slots=slots)
        host, process_backend, endpoint_backend = _fake_host(
            events,
            launch_capture_backend=capture_backend,
            max_capture_slots=8,
        )
        request = _process_request()

        with pytest.raises(HostingError) as failure:
            await host.start(
                ChildSessionRequest(request),
                _ManagedPreparationPort(request, events),
            )

        assert failure.value.category is expected_category
        assert capture_backend.materials[0].close_calls == 1
        assert process_backend.processes == []
        if len(slots) <= 8:
            assert endpoint_backend.transports[0].close_calls == 1
        else:
            assert endpoint_backend.transports == []
        await host.close()


@_async_test
async def test_managed_launch_native_verify_failure_prevents_spawn() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)
    capture_backend.block_after_attachment = True
    capture_backend.release.clear()
    start = asyncio.create_task(host.start(ChildSessionRequest(request), preparation))
    await capture_backend.attached.wait()
    capture_backend.materials[0].verify_error = OSError("native identity changed")
    capture_backend.release.set()

    with pytest.raises(HostingError) as failure:
        await start

    assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert capture_backend.materials[0].close_calls == 1
    assert process_backend.processes == []
    assert endpoint_backend.transports[0].close_calls == 1
    await host.close()


@_async_test
async def test_managed_launch_backend_contract_mismatch_closes_both_materials() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    capture_backend.return_different = True
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()

    with pytest.raises(HostingError):
        await host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )

    assert [material.close_calls for material in capture_backend.materials] == [1, 1]
    assert process_backend.processes == []
    assert endpoint_backend.transports == []
    await host.close()


@_async_test
async def test_managed_launch_cancelled_different_capture_retains_both_materials() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    capture_backend.block_after_attachment = True
    capture_backend.return_different = True
    capture_backend.release.clear()
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()
    start = asyncio.create_task(
        host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )
    )
    await capture_backend.attached.wait()

    start.cancel()
    capture_backend.release.set()
    with pytest.raises(asyncio.CancelledError):
        await start

    assert len(capture_backend.materials) == 2
    assert [material.close_calls for material in capture_backend.materials] == [1, 1]
    assert process_backend.processes == []
    assert endpoint_backend.transports == []
    await host.close()


@_async_test
async def test_managed_launch_missing_attachment_is_salvaged_then_rejected() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    capture_backend.skip_attachment = True
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()

    with pytest.raises(HostingError):
        await host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )

    assert capture_backend.materials[0].close_calls == 1
    assert process_backend.processes == []
    assert endpoint_backend.transports == []
    await host.close()


@_async_test
async def test_managed_launch_close_waits_for_claimed_spawn_and_rejects_replay() -> None:
    events: list[str] = []
    request = _process_request()
    capture_backend = _CaptureBackend(events)
    process_backend = _ProcessBackend(events)
    attached: list[_CapturedLaunchMaterial] = []
    capture = _ReservationLaunchCapture(
        capture_backend,
        attempt_id="attempt-close-race",
        max_inherited_slots=8,
        on_capture=attached.append,
        on_orphan=attached.append,
    )
    binding = await capture.capture(
        _LaunchCaptureSpec(
            request=request,
            profile_id="fake-profile-v1",
            execution_closure=("launcher:fake-v1", "payload:fake-v1"),
        )
    )
    managed = capture.bind_result(
        _ManagedLaunchPreparationResult(_Preparation(request, events), binding)
    )
    await managed.verify_current()
    process_backend.expected_inheritance = (51, 51, 61, 62)
    process_backend.block_after_managed_claim = True
    process_backend.managed_claim_release.clear()
    inheritance = _SingleUseProcessInheritance(
        backend_id=process_backend.backend_id,
        values=(51, 51),
        close_values=lambda: None,
    )
    spawned: list[_ProcessTransport] = []
    orphaned: list[_ProcessTransport] = []
    spawn = asyncio.create_task(
        managed.spawn_prepared(
            process_backend,
            request,
            on_spawn=spawned.append,
            on_orphan_spawn=orphaned.append,
            inheritance=inheritance,
        )
    )
    await process_backend.managed_claimed.wait()

    close = asyncio.create_task(managed.close())
    await asyncio.sleep(0)
    assert capture.state == "claimed"
    assert not close.done()
    assert attached[0].close_calls == 0
    process_backend.managed_claim_release.set()
    process = await spawn
    await close
    with pytest.raises(HostingError):
        await managed.spawn_prepared(
            process_backend,
            request,
            on_spawn=spawned.append,
            on_orphan_spawn=orphaned.append,
            inheritance=inheritance,
        )
    assert spawned == [process]
    assert attached[0].claim_calls == 1
    assert attached[0].close_calls == 1


@_async_test
async def test_managed_launch_verify_and_close_share_one_owner_operation() -> None:
    events: list[str] = []
    request = _process_request()
    backend = _CaptureBackend(events)
    attached: list[_CapturedLaunchMaterial] = []
    capture = _ReservationLaunchCapture(
        backend,
        attempt_id="attempt-verify-close",
        max_inherited_slots=8,
        on_capture=attached.append,
        on_orphan=attached.append,
    )
    binding = await capture.capture(
        _LaunchCaptureSpec(
            request=request,
            profile_id="fake-profile-v1",
            execution_closure=("launcher:fake-v1", "payload:fake-v1"),
        )
    )
    material = backend.materials[0]
    material.block_verify = True
    material.verify_release.clear()
    managed = capture.bind_result(
        _ManagedLaunchPreparationResult(_Preparation(request, events), binding)
    )
    verify = asyncio.create_task(managed.verify_current())
    await material.verify_entered.wait()
    close = asyncio.create_task(managed.close())
    await asyncio.sleep(0)
    assert not close.done()

    material.verify_release.set()
    await verify
    await close

    assert material.close_calls == 1
    assert capture.state == "closed"


@_async_test
async def test_managed_launch_final_fence_cancellation_prevents_spawn() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)
    capture_backend.block_after_attachment = True
    capture_backend.release.clear()
    start = asyncio.create_task(host.start(ChildSessionRequest(request), preparation))
    await capture_backend.attached.wait()
    material = capture_backend.materials[0]
    material.block_verify = True
    material.verify_release.clear()
    capture_backend.release.set()
    await material.verify_entered.wait()

    start.cancel()
    await asyncio.sleep(0)
    assert not start.done()
    material.verify_release.set()
    with pytest.raises(asyncio.CancelledError):
        await start

    assert process_backend.processes == []
    assert material.close_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1
    await host.close()


@_async_test
async def test_managed_launch_ambiguous_spawn_cancellation_reclaims_every_owner() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    process_backend.block_spawn = True
    request = _process_request()
    start = asyncio.create_task(
        host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )
    )
    await process_backend.spawn_attached.wait()

    start.cancel()
    await asyncio.sleep(0)
    assert not start.done()
    process_backend.spawn_release.set()
    with pytest.raises(asyncio.CancelledError):
        await start

    assert process_backend.close_handle_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1
    assert capture_backend.materials[0].close_calls == 1
    await host.close()


@_async_test
async def test_managed_launch_host_close_waits_for_attached_capture() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    capture_backend.block_after_attachment = True
    capture_backend.release.clear()
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()
    start = asyncio.create_task(
        host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )
    )
    await capture_backend.attached.wait()

    close = asyncio.create_task(host.close())
    await asyncio.sleep(0)
    assert not close.done()
    assert not start.done()
    capture_backend.release.set()
    with pytest.raises(asyncio.CancelledError):
        await start
    await close

    assert capture_backend.materials[0].close_calls == 1
    assert process_backend.processes == []
    assert endpoint_backend.transports == []


@_async_test
async def test_managed_launch_cleanup_debt_is_retained_and_retried_on_host_close() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, _, _ = _fake_host(events, launch_capture_backend=capture_backend)
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)
    preparation.error_after_capture = OSError("caller failed")
    capture_backend.block_after_attachment = True
    capture_backend.release.clear()
    start = asyncio.create_task(host.start(ChildSessionRequest(request), preparation))
    await capture_backend.attached.wait()
    material = capture_backend.materials[0]
    material.close_error_once = OSError("native close failed")
    capture_backend.release.set()

    with pytest.raises(HostingError):
        await start

    assert host._state == "faulted"
    assert material.close_calls == 1
    with pytest.raises(BaseExceptionGroup):
        await host.close()
    assert material.close_calls == 2
    assert not host._reservations


@_async_test
async def test_managed_launch_joined_owner_survives_endpoint_failure() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    capture_backend.block_after_attachment = True
    capture_backend.release.clear()
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    endpoint_backend.create_error_after_attach = HostingError(
        HostingFailureCategory.ENDPOINT_UNAVAILABLE,
        "endpoint failed after managed preparation joined",
    )
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)
    start = asyncio.create_task(host.start(ChildSessionRequest(request), preparation))
    await capture_backend.attached.wait()
    material = capture_backend.materials[0]
    material.close_error_once = OSError("transient joined native cleanup")
    capture_backend.release.set()

    with pytest.raises(HostingError) as failure:
        await start

    assert failure.value.category is HostingFailureCategory.ENDPOINT_UNAVAILABLE
    assert process_backend.processes == []
    assert endpoint_backend.transports[0].close_calls == 1
    assert material.close_calls == 1
    assert preparation.preparation.close_calls == 1
    assert len(host._reservations) == 1
    with pytest.raises(BaseExceptionGroup):
        await host.close()
    assert material.close_calls == 2
    assert preparation.preparation.close_calls == 1
    assert not host._reservations


@_async_test
async def test_managed_launch_binding_is_consumed_by_the_first_bind() -> None:
    events: list[str] = []
    request = _process_request()
    backend = _CaptureBackend(events)
    attached: list[_CapturedLaunchMaterial] = []
    capture = _ReservationLaunchCapture(
        backend,
        attempt_id="attempt-binding",
        max_inherited_slots=8,
        on_capture=attached.append,
        on_orphan=attached.append,
    )
    binding = await capture.capture(
        _LaunchCaptureSpec(
            request=request,
            profile_id="fake-profile-v1",
            execution_closure=("launcher:fake-v1", "payload:fake-v1"),
        )
    )
    result = _ManagedLaunchPreparationResult(_Preparation(request, events), binding)

    managed = capture.bind_result(result)
    with pytest.raises(HostingError) as replay:
        capture.bind_result(result)

    assert replay.value.category is HostingFailureCategory.PREPARATION_FAILED
    await managed.close()
    assert attached[0].close_calls == 1


@_async_test
async def test_managed_launch_attached_then_capture_error_reclaims_both_owners() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    capture_backend.error_after_attachment = OSError("capture failed after attach")
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)

    with pytest.raises(HostingError) as failure:
        await host.start(ChildSessionRequest(request), preparation)

    assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert preparation.preparation.close_calls == 1
    assert capture_backend.materials[0].close_calls == 1
    assert process_backend.processes == []
    assert endpoint_backend.transports == []
    await host.close()


@_async_test
async def test_managed_launch_pre_attachment_error_acquires_no_native_owner() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    capture_backend.error_before_attachment = OSError("capture did not acquire")
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()
    preparation = _ManagedPreparationPort(request, events)

    with pytest.raises(HostingError) as failure:
        await host.start(ChildSessionRequest(request), preparation)

    assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert preparation.preparation.close_calls == 1
    assert capture_backend.materials == []
    assert process_backend.processes == []
    assert endpoint_backend.transports == []
    await host.close()


@_async_test
async def test_managed_launch_orphan_cleanup_failure_is_owned_and_retried() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    capture_backend.return_different = True
    capture_backend.different_close_error_once = OSError("orphan close failed")
    host, _, _ = _fake_host(events, launch_capture_backend=capture_backend)
    request = _process_request()

    with pytest.raises(HostingError):
        await host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )

    assert host._state == "faulted"
    assert [material.close_calls for material in capture_backend.materials] == [1, 1]
    assert len(host._reservations) == 1
    with pytest.raises(BaseExceptionGroup):
        await host.close()
    assert [material.close_calls for material in capture_backend.materials] == [1, 2]
    assert not host._reservations


@_async_test
async def test_managed_launch_attempt_identity_is_unique_across_hosts() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    first_host, first_process, _ = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    second_host, second_process, _ = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    first_process.expected_inheritance = (51, 51, 61, 62)
    second_process.expected_inheritance = (51, 51, 61, 62)
    request = _process_request()

    first = await first_host.start(
        ChildSessionRequest(request),
        _ManagedPreparationPort(request, events),
    )
    second = await second_host.start(
        ChildSessionRequest(request),
        _ManagedPreparationPort(request, events),
    )

    first_material, second_material = capture_backend.materials
    assert first_material.attempt_id != second_material.attempt_id
    assert first_material.attempt_token is not second_material.attempt_token
    await first.close()
    await second.close()
    await first_host.close()
    await second_host.close()


@_async_test
async def test_managed_launch_cached_material_cannot_cross_attempt_tokens() -> None:
    events: list[str] = []
    request = _process_request()
    backend = _CaptureBackend(events)
    first_owned: list[_CapturedLaunchMaterial] = []
    second_owned: list[_CapturedLaunchMaterial] = []
    first = _ReservationLaunchCapture(
        backend,
        attempt_id="host-a-attempt-1",
        max_inherited_slots=8,
        on_capture=first_owned.append,
        on_orphan=first_owned.append,
    )
    second = _ReservationLaunchCapture(
        backend,
        attempt_id="host-b-attempt-1",
        max_inherited_slots=8,
        on_capture=second_owned.append,
        on_orphan=second_owned.append,
    )
    spec = _LaunchCaptureSpec(
        request=request,
        profile_id="fake-profile-v1",
        execution_closure=("launcher:fake-v1", "payload:fake-v1"),
    )
    await first.capture(spec)
    backend.replay_material = backend.materials[0]

    with pytest.raises(HostingError) as replay:
        await second.capture(spec)

    assert replay.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert first_owned == [backend.materials[0]]
    assert second_owned == []
    assert backend.materials[0].close_calls == 0
    await backend.materials[0].close()


@pytest.mark.parametrize(
    "identity_field",
    (
        "request",
        "backend_id",
        "attempt_id",
        "attempt_token",
        "profile_id",
        "execution_closure",
    ),
)
@_async_test
async def test_managed_launch_revalidates_identity_immediately_before_spawn(
    identity_field: str,
) -> None:
    events: list[str] = []
    request = _process_request()
    capture_backend = _CaptureBackend(events)
    attached: list[_CapturedLaunchMaterial] = []
    capture = _ReservationLaunchCapture(
        capture_backend,
        attempt_id="attempt-final-identity",
        max_inherited_slots=8,
        on_capture=attached.append,
        on_orphan=attached.append,
    )
    binding = await capture.capture(
        _LaunchCaptureSpec(
            request=request,
            profile_id="fake-profile-v1",
            execution_closure=("launcher:fake-v1", "payload:fake-v1"),
        )
    )
    managed = capture.bind_result(
        _ManagedLaunchPreparationResult(_Preparation(request, events), binding)
    )
    await managed.verify_current()
    material = capture_backend.materials[0]
    replacements: dict[str, object] = {
        "request": ProcessLaunchRequest(
            argv=(sys.executable, "-c", "raise SystemExit(9)"),
            cwd=request.cwd,
            effective_environment=request.effective_environment,
            streams=request.streams,
        ),
        "backend_id": "foreign-process-v1",
        "attempt_id": "foreign-attempt",
        "attempt_token": object(),
        "profile_id": "foreign-profile-v1",
        "execution_closure": ("launcher:foreign", "payload:foreign"),
    }
    setattr(material, identity_field, replacements[identity_field])

    with pytest.raises(HostingError) as failure:
        await managed.spawn_prepared(
            _ProcessBackend(events),
            request,
            on_spawn=lambda process: None,
            on_orphan_spawn=lambda process: None,
            inheritance=_SingleUseProcessInheritance(
                backend_id="fake-process-v1",
                values=(51, 51),
                close_values=lambda: None,
            ),
        )

    assert failure.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert material.claim_calls == 0
    await managed.close()


@_async_test
async def test_managed_launch_concurrent_verify_is_one_use() -> None:
    events: list[str] = []
    request = _process_request()
    backend = _CaptureBackend(events)
    attached: list[_CapturedLaunchMaterial] = []
    capture = _ReservationLaunchCapture(
        backend,
        attempt_id="attempt-verify-replay",
        max_inherited_slots=8,
        on_capture=attached.append,
        on_orphan=attached.append,
    )
    binding = await capture.capture(
        _LaunchCaptureSpec(
            request=request,
            profile_id="fake-profile-v1",
            execution_closure=("launcher:fake-v1", "payload:fake-v1"),
        )
    )
    material = backend.materials[0]
    material.block_verify = True
    material.verify_release.clear()
    managed = capture.bind_result(
        _ManagedLaunchPreparationResult(_Preparation(request, events), binding)
    )
    first = asyncio.create_task(managed.verify_current())
    await material.verify_entered.wait()

    with pytest.raises(HostingError) as replay:
        await managed.verify_current()
    material.verify_release.set()
    await first

    assert replay.value.category is HostingFailureCategory.PREPARATION_FAILED
    assert events.count("native-verify") == 1
    await managed.close()


@_async_test
async def test_managed_launch_dual_cleanup_failure_retries_in_dependency_order() -> None:
    events: list[str] = []
    request = _process_request()
    backend = _CaptureBackend(events)
    attached: list[_CapturedLaunchMaterial] = []
    capture = _ReservationLaunchCapture(
        backend,
        attempt_id="attempt-dual-cleanup",
        max_inherited_slots=8,
        on_capture=attached.append,
        on_orphan=attached.append,
    )
    binding = await capture.capture(
        _LaunchCaptureSpec(
            request=request,
            profile_id="fake-profile-v1",
            execution_closure=("launcher:fake-v1", "payload:fake-v1"),
        )
    )
    caller = _Preparation(request, events)
    caller.close_error_once = OSError("caller cleanup")
    material = backend.materials[0]
    material.close_error_once = OSError("native cleanup")
    managed = capture.bind_result(_ManagedLaunchPreparationResult(caller, binding))

    with pytest.raises(BaseExceptionGroup) as first:
        await managed.close()

    assert len(first.value.exceptions) == 2
    assert events.index("native-close") < events.index("preparation-close")
    await managed.close()
    assert material.close_calls == 2
    assert caller.close_calls == 2
    assert capture.state == "closed"


@_async_test
async def test_managed_launch_unknown_spawn_outcome_fences_host_and_attempt() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    process_backend.ambiguous_spawn_error = OSError("spawn outcome unavailable")
    request = _process_request()

    with pytest.raises(HostingError) as failure:
        await host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )

    material = capture_backend.materials[0]
    assert failure.value.category is HostingFailureCategory.SPAWN_FAILED
    assert material.claim_calls == 1
    assert material.close_calls == 0
    assert process_backend.processes == []
    assert endpoint_backend.transports[0].close_calls == 1
    assert host._state == "faulted"
    with pytest.raises(HostingError) as fenced:
        await host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )
    assert fenced.value.category is HostingFailureCategory.HOST_CLOSED
    with pytest.raises(BaseExceptionGroup):
        await host.close()
    assert material.close_calls == 0
    assert host._reservations


@_async_test
async def test_managed_launch_cancelled_missing_spawn_callback_is_salvaged() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    process_backend.skip_managed_attachment = True
    process_backend.block_spawn = True
    process_backend.spawn_release.clear()
    request = _process_request()
    start = asyncio.create_task(
        host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )
    )
    await process_backend.managed_process_created.wait()

    start.cancel()
    process_backend.spawn_release.set()
    with pytest.raises(asyncio.CancelledError):
        await start

    assert len(process_backend.processes) == 1
    assert process_backend.close_handle_calls == 1
    assert capture_backend.materials[0].close_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1
    assert not host._reservations
    await host.close()


@_async_test
async def test_managed_launch_cancelled_different_spawn_retains_both_processes() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    process_backend.return_different_managed_process = True
    process_backend.block_spawn = True
    process_backend.spawn_release.clear()
    request = _process_request()
    start = asyncio.create_task(
        host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )
    )
    await process_backend.spawn_attached.wait()

    start.cancel()
    process_backend.spawn_release.set()
    with pytest.raises(asyncio.CancelledError):
        await start

    assert len(process_backend.processes) == 2
    assert process_backend.close_handle_calls == 2
    assert capture_backend.materials[0].close_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1
    assert not host._reservations
    await host.close()


@_async_test
async def test_managed_launch_not_created_receipt_after_effect_fences_attempt() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    process_backend.not_created_after_effect_error = OSError(
        "adapter misreported a post-effect failure"
    )
    request = _process_request()

    with pytest.raises(HostingError) as failure:
        await host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )

    assert failure.value.category is HostingFailureCategory.SPAWN_FAILED
    assert len(process_backend.processes) == 1
    assert process_backend.close_handle_calls == 0
    assert capture_backend.materials[0].close_calls == 0
    assert endpoint_backend.transports[0].close_calls == 1
    assert host._state == "faulted"
    with pytest.raises(BaseExceptionGroup):
        await host.close()


@_async_test
async def test_managed_launch_missing_effect_gate_is_attached_then_fenced() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    process_backend.skip_managed_effect_gate = True
    request = _process_request()

    with pytest.raises(HostingError) as failure:
        await host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )

    assert failure.value.category is HostingFailureCategory.SPAWN_FAILED
    assert len(process_backend.processes) == 1
    assert process_backend.close_handle_calls == 1
    assert capture_backend.materials[0].close_calls == 0
    assert endpoint_backend.transports[0].close_calls == 1
    assert host._state == "faulted"
    with pytest.raises(BaseExceptionGroup):
        await host.close()


@_async_test
async def test_managed_launch_attachment_invalidates_forged_not_created_receipt() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    process_backend.skip_managed_effect_gate = True
    process_backend.callback_error_as_not_created = True
    request = _process_request()

    with pytest.raises(HostingError) as failure:
        await host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )

    assert failure.value.category is HostingFailureCategory.SPAWN_FAILED
    assert len(process_backend.processes) == 1
    assert process_backend.close_handle_calls == 1
    assert capture_backend.materials[0].close_calls == 0
    assert endpoint_backend.transports[0].close_calls == 1
    assert host._state == "faulted"
    with pytest.raises(BaseExceptionGroup):
        await host.close()


@_async_test
async def test_managed_launch_transfer_fault_reclaims_process_but_keeps_fence() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    capture_backend.block_after_attachment = True
    capture_backend.release.clear()
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    request = _process_request()
    start = asyncio.create_task(
        host.start(
            ChildSessionRequest(request),
            _ManagedPreparationPort(request, events),
        )
    )
    await capture_backend.attached.wait()
    material = capture_backend.materials[0]
    material.transfer_error = OSError("native transfer acknowledgement failed")
    capture_backend.release.set()

    with pytest.raises(HostingError) as failure:
        await start

    assert failure.value.category is HostingFailureCategory.SPAWN_FAILED
    assert len(process_backend.processes) == 1
    assert process_backend.close_handle_calls == 1
    assert endpoint_backend.transports[0].close_calls == 1
    assert material.transfer_calls == 1
    assert material.close_calls == 0
    assert host._state == "faulted"
    with pytest.raises(BaseExceptionGroup):
        await host.close()
    assert material.close_calls == 0


@_async_test
async def test_managed_launch_recursive_start_cannot_bypass_reserved_capacity() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, endpoint_backend = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()

    class _RecursivePreparation(_ManagedLaunchPreparationPort):
        async def prepare(self, candidate: ProcessLaunchRequest) -> _Preparation:
            raise AssertionError("managed path expected")

        async def prepare_managed(
            self,
            candidate: ProcessLaunchRequest,
            capture: _LaunchCapturePort,
        ) -> _ManagedLaunchPreparationResult:
            await host.start(
                ChildSessionRequest(candidate),
                _PreparationPort(_Preparation(candidate, events), events),
            )
            raise AssertionError("recursive start must not acquire capacity")

    with pytest.raises(HostingError) as failure:
        await host.start(ChildSessionRequest(request), _RecursivePreparation())

    assert failure.value.category is HostingFailureCategory.CAPACITY_EXHAUSTED
    assert capture_backend.materials == []
    assert process_backend.processes == []
    assert endpoint_backend.transports == []
    await host.close()


@pytest.mark.parametrize(
    ("profile_id", "execution_closure"),
    (
        (
            "posix-descriptor-profile-v1",
            ("launcher:posix-fake", "loader:posix-fake", "payload:fake"),
        ),
        (
            "windows-token-handle-profile-v1",
            ("image:windows-fake", "loader:windows-fake", "payload:fake"),
        ),
    ),
)
@_async_test
async def test_managed_launch_profile_identities_use_the_same_opaque_protocol(
    profile_id: str,
    execution_closure: tuple[str, ...],
) -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, _ = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    process_backend.expected_inheritance = (51, 51, 61, 62)
    request = _process_request()

    lease = await host.start(
        ChildSessionRequest(request),
        _ManagedPreparationPort(
            request,
            events,
            profile_id=profile_id,
            execution_closure=execution_closure,
        ),
    )

    material = capture_backend.materials[0]
    assert material.profile_id == profile_id
    assert material.execution_closure == execution_closure
    await lease.close()
    await host.close()


@_async_test
async def test_managed_launch_private_process_seam_is_nominal_not_duck_typed() -> None:
    events: list[str] = []
    host, process_backend, _ = _fake_host(events)
    request = _process_request()

    class _LookalikePreparation(_Preparation):
        async def spawn_prepared(self, *args: object, **kwargs: object) -> _Process:
            raise AssertionError("ordinary caller must not enter the private H6 seam")

    preparation = _LookalikePreparation(request, events)
    lease = await host.start(
        ChildSessionRequest(request),
        _PreparationPort(preparation, events),
    )

    assert len(process_backend.processes) == 1
    await lease.close()
    await host.close()


@_async_test
async def test_managed_launch_private_caller_seam_is_nominal_and_default_dark() -> None:
    events: list[str] = []
    capture_backend = _CaptureBackend(events)
    host, process_backend, _ = _fake_host(
        events,
        launch_capture_backend=capture_backend,
    )
    request = _process_request()

    class _LookalikePort(_PreparationPort):
        async def prepare_managed(
            self,
            candidate: ProcessLaunchRequest,
            capture: _LaunchCapturePort,
        ) -> _ManagedLaunchPreparationResult:
            raise AssertionError("ordinary caller must not enter the private H6 seam")

    lease = await host.start(
        ChildSessionRequest(request),
        _LookalikePort(_Preparation(request, events), events),
    )

    assert len(process_backend.processes) == 1
    assert capture_backend.materials == []
    await lease.close()
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
