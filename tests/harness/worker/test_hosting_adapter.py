from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.worker import (
    HostingManagedWorkerSessionAdapter,
    ManagedWorkerLaunchRequestV1,
    WorkerBindingError,
    WorkerFrameCodec,
    WorkerHostingActivationError,
    WorkerHostingActivationV1,
    WorkerLaunchIdentityV1,
    WorkerProtocolMessage,
    WorkerRuntimeBindingV1,
    WorkerSessionOwnerRouter,
    WorkerSupervisor,
    WorkerSupervisorError,
)
from loushang.harness.worker.journal import WorkerSupervisorJournal
from loushang.harness.workspace.process import ProcessStderrTail
from loushang.hosting import (
    ChildSessionRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
)
from loushang.hosting import (
    ProcessExit as HostingProcessExit,
)
from loushang.hosting import (
    ProcessLaunchRequest as HostingProcessLaunchRequest,
)
from loushang.hosting._child_session_host import _ChildSessionHost
from loushang.hosting._endpoint_backend import (
    _PlatformEndpointPair,
    _SingleUseProcessInheritance,
)
from loushang.hosting._endpoint_host import _InheritedEndpointHost
from loushang.hosting._launch_preparation import (
    _LaunchCapturePort,
    _LaunchCaptureSpec,
    _ManagedLaunchPreparationPort,
    _ManagedLaunchPreparationResult,
    _ManagedSpawnEffect,
    _OpaqueLaunchBinding,
)
from loushang.hosting._process_backend import (
    _ProcessBackend as _ProcessBackendPort,
)
from loushang.hosting._process_backend import (
    _ProcessInheritance,
    _ProcessTransport,
)
from loushang.hosting._process_host import _ProcessHost, _ProcessHostLimits


def _runtime(tmp_path: Path) -> WorkerRuntimeBindingV1:
    executable = tmp_path / "worker"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o500)
    return WorkerRuntimeBindingV1.capture(
        package_root=tmp_path,
        configuration=PluginLocalWorkerConfiguration(
            entrypoint="worker",
            protocol="capability.query",
            protocol_version=1,
        ),
    )


def _identity(runtime: WorkerRuntimeBindingV1) -> WorkerLaunchIdentityV1:
    return WorkerLaunchIdentityV1(
        plugin_id="review-pack",
        plugin_revision_digest="a" * 64,
        contribution_id="review-provider",
        owner_id="coding.lsp",
        product_id="coding",
        scope_id="session-one",
        owner_generation=3,
        declaration_fingerprint="b" * 64,
        worker_configuration_fingerprint=runtime.worker_configuration_fingerprint,
        attempt_id="c" * 32,
        supervisor_epoch=1,
        session_nonce="d" * 64,
    )


def _request(
    tmp_path: Path,
    *,
    validate_current,
) -> ManagedWorkerLaunchRequestV1:
    runtime = _runtime(tmp_path)
    return ManagedWorkerLaunchRequestV1(
        identity=_identity(runtime),
        runtime=runtime,
        validate_current=validate_current,
    )


class _PreparationLease:
    def __init__(self, request: HostingProcessLaunchRequest, *, on_verify=None) -> None:
        self._request = request
        self._on_verify = on_verify
        self.verified = 0
        self.closed = 0

    @property
    def request(self) -> HostingProcessLaunchRequest:
        return self._request

    async def verify_current(self) -> None:
        self.verified += 1
        if self._on_verify is not None:
            self._on_verify()

    async def close(self) -> None:
        self.closed += 1


class _PreparationPort:
    def __init__(self, *, on_verify=None) -> None:
        self._on_verify = on_verify
        self.requests: list[HostingProcessLaunchRequest] = []
        self.lease: _PreparationLease | None = None

    async def prepare(
        self, request: HostingProcessLaunchRequest
    ) -> _PreparationLease:
        self.requests.append(request)
        self.lease = _PreparationLease(request, on_verify=self._on_verify)
        return self.lease


class _ManagedPreparationPort(_ManagedLaunchPreparationPort):
    def __init__(self, *, on_verify=None, pause_after_capture: bool = False) -> None:
        self._on_verify = on_verify
        self.public_calls = 0
        self.managed_calls = 0
        self.specs: list[_LaunchCaptureSpec] = []
        self.lease: _PreparationLease | None = None
        self.captured = asyncio.Event()
        self.release = asyncio.Event()
        if not pause_after_capture:
            self.release.set()

    async def prepare(
        self, request: HostingProcessLaunchRequest
    ) -> _PreparationLease:
        del request
        self.public_calls += 1
        raise AssertionError("managed Worker preparation must preserve the private seam")

    async def prepare_managed(
        self,
        request: HostingProcessLaunchRequest,
        capture: _LaunchCapturePort,
    ) -> _ManagedLaunchPreparationResult:
        self.managed_calls += 1
        lease = _PreparationLease(request, on_verify=self._on_verify)
        self.lease = lease
        returned = False
        try:
            spec = _LaunchCaptureSpec(
                request=request,
                profile_id="harness-worker-parity-fake-v1",
                execution_closure=("worker:harness-parity-fake-v1",),
            )
            self.specs.append(spec)
            binding = await capture.capture(spec)
            self.captured.set()
            await self.release.wait()
            result = _ManagedLaunchPreparationResult(lease=lease, binding=binding)
            returned = True
            return result
        finally:
            if not returned:
                cleanup = asyncio.create_task(
                    lease.close(),
                    name="harness-worker-managed-preparation-rollback",
                )
                await asyncio.shield(cleanup)


class _CapturePort:
    def __init__(self) -> None:
        self.specs: list[_LaunchCaptureSpec] = []
        self._nonce = object()

    async def capture(self, spec: _LaunchCaptureSpec) -> _OpaqueLaunchBinding:
        self.specs.append(spec)
        return _OpaqueLaunchBinding(self, self._nonce)


class _ManagedEndpointTransport:
    def __init__(self) -> None:
        self.close_calls = 0

    async def read(self, max_bytes: int) -> bytes:
        del max_bytes
        return b""

    async def write(self, data: bytes) -> None:
        del data

    async def close(self) -> None:
        self.close_calls += 1


class _ManagedEndpointBackend:
    backend_id = "harness-managed-endpoint-fake-v1"

    def __init__(self) -> None:
        self.transports: list[_ManagedEndpointTransport] = []
        self.child_close_calls = 0
        self.close_calls = 0

    async def create_pair(self, *, on_create) -> _PlatformEndpointPair:
        transport = _ManagedEndpointTransport()
        self.transports.append(transport)

        def close_child() -> None:
            self.child_close_calls += 1

        pair = _PlatformEndpointPair(
            transport=transport,
            inheritance=_SingleUseProcessInheritance(
                backend_id=_ManagedProcessBackend.backend_id,
                values=(51, 52),
                close_values=close_child,
            ),
        )
        on_create(pair)
        return pair

    async def close_backend(self) -> None:
        self.close_calls += 1


class _ManagedProcessTransport:
    def __init__(self) -> None:
        self._return_code: int | None = None
        self._exited = asyncio.Event()
        self._tree_exited = asyncio.Event()

    @property
    def return_code(self) -> int | None:
        return self._return_code

    async def read_stdout(self, max_bytes: int) -> bytes:
        del max_bytes
        return b""

    async def read_stderr(self, max_bytes: int) -> bytes:
        del max_bytes
        return b""

    async def write_stdin(self, data: bytes) -> None:
        del data

    async def close_stdin(self) -> None:
        return None

    async def wait(self) -> int:
        await self._exited.wait()
        assert self._return_code is not None
        return self._return_code

    def exit(self, return_code: int) -> None:
        self._return_code = return_code
        self._exited.set()
        self._tree_exited.set()


class _ManagedCapturedMaterial:
    backend_id = "harness-managed-process-fake-v1"

    def __init__(
        self,
        *,
        spec: _LaunchCaptureSpec,
        attempt_id: str,
        attempt_token: object,
    ) -> None:
        self.request = spec.request
        self.profile_id = spec.profile_id
        self.execution_closure = spec.execution_closure
        self.attempt_id = attempt_id
        self.attempt_token = attempt_token
        self.verify_calls = 0
        self.claim_calls = 0
        self.transfer_calls = 0
        self.close_calls = 0

    @property
    def inherited_slot_count(self) -> int:
        return 1

    async def verify_current(self, request: HostingProcessLaunchRequest) -> None:
        assert request == self.request
        self.verify_calls += 1

    def claim_for_spawn(self, *, backend_id: str) -> tuple[int, ...]:
        assert backend_id == self.backend_id
        self.claim_calls += 1
        return (61,)

    def mark_transferred(self) -> None:
        self.transfer_calls += 1

    async def spawn(
        self,
        backend: _ProcessBackendPort,
        request: HostingProcessLaunchRequest,
        *,
        effect: _ManagedSpawnEffect,
        on_spawn,
        inheritance: _ProcessInheritance | None,
    ) -> _ProcessTransport:
        assert isinstance(backend, _ManagedProcessBackend)
        return await backend.spawn_managed(
            request,
            material=self,
            effect=effect,
            on_spawn=on_spawn,
            inheritance=inheritance,
        )

    async def close(self) -> None:
        self.close_calls += 1


class _ManagedCaptureBackend:
    backend_id = _ManagedCapturedMaterial.backend_id

    def __init__(self) -> None:
        self.materials: list[_ManagedCapturedMaterial] = []

    async def capture(
        self,
        spec: _LaunchCaptureSpec,
        *,
        attempt_id: str,
        attempt_token: object,
        on_capture,
    ) -> _ManagedCapturedMaterial:
        material = _ManagedCapturedMaterial(
            spec=spec,
            attempt_id=attempt_id,
            attempt_token=attempt_token,
        )
        self.materials.append(material)
        on_capture(material)
        return material


class _ManagedProcessBackend:
    backend_id = _ManagedCapturedMaterial.backend_id

    def __init__(self) -> None:
        self.processes: list[_ManagedProcessTransport] = []
        self.close_handle_calls = 0
        self.close_calls = 0

    async def spawn(self, *args, **kwargs) -> _ManagedProcessTransport:
        del args, kwargs
        raise AssertionError("managed Harness preparation must use managed spawn")

    async def spawn_managed(
        self,
        request: HostingProcessLaunchRequest,
        *,
        material: _ManagedCapturedMaterial,
        effect: _ManagedSpawnEffect,
        on_spawn,
        inheritance: _ProcessInheritance | None,
    ) -> _ManagedProcessTransport:
        assert request == material.request
        assert inheritance is not None
        endpoint_slots = inheritance.claim(backend_id=self.backend_id)
        preparation_slots = material.claim_for_spawn(backend_id=self.backend_id)
        assert endpoint_slots == (51, 52)
        assert preparation_slots == (61,)
        assert not set(endpoint_slots) & set(preparation_slots)
        effect.begin_effect()
        process = _ManagedProcessTransport()
        self.processes.append(process)
        on_spawn(process)
        inheritance.mark_transferred()
        material.mark_transferred()
        return process

    def tree_exited(self, process: _ProcessTransport) -> bool:
        assert isinstance(process, _ManagedProcessTransport)
        return process._tree_exited.is_set()

    async def wait_tree(self, process: _ProcessTransport) -> None:
        assert isinstance(process, _ManagedProcessTransport)
        await process._tree_exited.wait()

    async def terminate_tree(self, process: _ProcessTransport) -> None:
        assert isinstance(process, _ManagedProcessTransport)
        process.exit(-15)

    async def kill_tree(self, process: _ProcessTransport) -> None:
        assert isinstance(process, _ManagedProcessTransport)
        process.exit(-9)

    async def close_process_handles(self, process: _ProcessTransport) -> None:
        assert isinstance(process, _ManagedProcessTransport)
        self.close_handle_calls += 1

    async def close_backend(self) -> None:
        self.close_calls += 1


def _managed_child_session_host():
    process_backend = _ManagedProcessBackend()
    endpoint_backend = _ManagedEndpointBackend()
    capture_backend = _ManagedCaptureBackend()
    host = _ChildSessionHost(
        _ProcessHost(
            process_backend,
            limits=_ProcessHostLimits(max_processes=1),
        ),
        _InheritedEndpointHost(endpoint_backend, max_endpoints=1),
        max_sessions=1,
        launch_capture_backend=capture_backend,
        max_capture_slots=2,
    )
    return host, process_backend, endpoint_backend, capture_backend


class _Endpoint:
    def __init__(self, incoming: bytes, events: list[str]) -> None:
        self.incoming = bytearray(incoming)
        self.writes: list[bytes] = []
        self.events = events
        self.closed = False
        self.changed = asyncio.Event()

    async def read(self, max_bytes: int) -> bytes:
        while not self.incoming:
            if self.closed:
                return b""
            self.changed.clear()
            await self.changed.wait()
        body = bytes(self.incoming[: min(max_bytes, 3)])
        del self.incoming[: len(body)]
        return body

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def close(self) -> None:
        self.closed = True
        self.changed.set()
        self.events.append("endpoint.close")


class _HostingProcess:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.exit: asyncio.Future[HostingProcessExit] = (
            asyncio.get_running_loop().create_future()
        )

    @property
    def lease_id(self) -> str:
        return "process-one"

    async def read_stdout(self, max_bytes: int) -> bytes:
        del max_bytes
        return b""

    async def read_stderr(self, max_bytes: int) -> bytes:
        del max_bytes
        return b"diagnostic"

    async def write_stdin(self, data: bytes) -> None:
        del data

    async def close_stdin(self) -> None:
        return None

    async def wait(self) -> HostingProcessExit:
        return await asyncio.shield(self.exit)

    async def terminate(self) -> HostingProcessExit:
        self._finish(-15)
        return await self.wait()

    async def close(self) -> None:
        self.events.append("process.close")
        self._finish(-15)

    def stderr_tail(self):
        from loushang.hosting import ProcessStderrTail as HostingProcessStderrTail

        return HostingProcessStderrTail(content=b"tail")

    def _finish(self, code: int) -> None:
        if not self.exit.done():
            self.exit.set_result(HostingProcessExit(code))


class _ChildLease:
    def __init__(
        self,
        *,
        endpoint: _Endpoint,
        process: _HostingProcess,
        preparation: _PreparationLease,
        events: list[str],
    ) -> None:
        self._endpoint = endpoint
        self._process = process
        self._preparation = preparation
        self._events = events
        self._closed = False

    @property
    def session_id(self) -> str:
        return "child-session-one"

    @property
    def endpoint(self) -> _Endpoint:
        return self._endpoint

    @property
    def process(self) -> _HostingProcess:
        return self._process

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._process.close()
        await self._endpoint.close()
        await self._preparation.close()
        self._events.append("session.closed")


class _ChildPort:
    def __init__(self, incoming: bytes = b"") -> None:
        self.incoming = incoming
        self.requests: list[ChildSessionRequest] = []
        self.events: list[str] = []
        self.lease: _ChildLease | None = None

    async def start(self, request: ChildSessionRequest, preparation) -> _ChildLease:
        self.requests.append(request)
        prepared = await preparation.prepare(request.process)
        try:
            await prepared.verify_current()
        except BaseException:
            await prepared.close()
            raise
        self.lease = _ChildLease(
            endpoint=_Endpoint(self.incoming, self.events),
            process=_HostingProcess(self.events),
            preparation=prepared,
            events=self.events,
        )
        return self.lease

    async def close(self) -> None:
        if self.lease is not None:
            await self.lease.close()


class _ManagedChildPort(_ChildPort):
    def __init__(self, incoming: bytes = b"") -> None:
        super().__init__(incoming)
        self.capture = _CapturePort()

    async def start(self, request: ChildSessionRequest, preparation) -> _ChildLease:
        self.requests.append(request)
        assert isinstance(preparation, _ManagedLaunchPreparationPort)
        result = await preparation.prepare_managed(request.process, self.capture)
        prepared = result.lease
        try:
            await prepared.verify_current()
        except BaseException:
            await prepared.close()
            raise
        self.lease = _ChildLease(
            endpoint=_Endpoint(self.incoming, self.events),
            process=_HostingProcess(self.events),
            preparation=prepared,  # type: ignore[arg-type]
            events=self.events,
        )
        return self.lease


def _ready(identity: WorkerLaunchIdentityV1) -> WorkerProtocolMessage:
    return WorkerProtocolMessage.create(
        "ready",
        attemptId=identity.attempt_id,
        identityFingerprint=identity.fingerprint,
        protocol="capability.query",
        protocolVersion=1,
        sessionNonce=identity.session_nonce,
        supervisorEpoch=identity.supervisor_epoch,
    )


def test_hosting_adapter_maps_worker_and_publishes_atomic_session(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        validations = 0

        def validate_current() -> None:
            nonlocal validations
            validations += 1

        request = _request(tmp_path, validate_current=validate_current)
        preparation = _PreparationPort()
        child = _ChildPort(WorkerFrameCodec.encode(_ready(request.identity)))
        adapter = HostingManagedWorkerSessionAdapter(
            hosting=child,  # type: ignore[arg-type]
            preparation=preparation,  # type: ignore[arg-type]
            endpoint_read_chunk_bytes=7,
        )

        session = await adapter.start(request, correlation_id="hosting-launch")

        assert validations == 2
        assert len(child.requests) == 1
        mapped = child.requests[0].process
        assert mapped.argv == (str(request.runtime.executable),)
        assert mapped.cwd == str(request.runtime.package_root)
        assert mapped.effective_environment == ()
        assert mapped.streams.stdin is ProcessStdinMode.CLOSED
        assert mapped.streams.stdout is ProcessStdoutMode.DISCARD
        assert mapped.streams.stderr is ProcessStderrMode.PIPE
        assert session.evidence.request_fingerprint == request.fingerprint
        assert session.evidence.launch_correlation_id == "hosting-launch"
        assert await session.process.read_stdout() == b""
        assert await session.process.read_stderr() == b"diagnostic"
        assert session.process.stderr_tail() == ProcessStderrTail(content=b"tail")
        assert (
            await session.transport.receive(direction="worker_to_host")
        ).kind == "ready"

        await session.transport.send(
            WorkerProtocolMessage.create(
                "query",
                correlationId="1" * 32,
                payload={"operation": "describe"},
            ),
            direction="host_to_worker",
        )
        assert child.lease is not None
        assert child.lease.endpoint.writes
        await session.close()
        assert child.events == [
            "process.close",
            "endpoint.close",
            "session.closed",
        ]
        assert preparation.lease is not None
        assert preparation.lease.verified == 1
        assert preparation.lease.closed == 1

    asyncio.run(scenario())


def test_hosting_adapter_preserves_managed_capture_and_worker_semantic_fence(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        validations = 0

        def validate_current() -> None:
            nonlocal validations
            validations += 1

        request = _request(tmp_path, validate_current=validate_current)
        preparation = _ManagedPreparationPort()
        child = _ManagedChildPort()
        adapter = HostingManagedWorkerSessionAdapter(
            hosting=child,  # type: ignore[arg-type]
            preparation=preparation,
        )

        session = await adapter.start(request, correlation_id="managed-parity")

        assert validations == 2
        assert preparation.public_calls == 0
        assert preparation.managed_calls == 1
        assert child.capture.specs == preparation.specs
        assert child.capture.specs[0].request == child.requests[0].process
        assert child.capture.specs[0].profile_id == (
            "harness-worker-parity-fake-v1"
        )
        assert session.evidence.request_fingerprint == request.fingerprint
        await session.close()
        assert preparation.lease is not None
        assert preparation.lease.verified == 1
        assert preparation.lease.closed == 1

    asyncio.run(scenario())


def test_hosting_adapter_managed_capture_cancellation_retains_delegate_cleanup(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        request = _request(tmp_path, validate_current=lambda: None)
        preparation = _ManagedPreparationPort(pause_after_capture=True)
        adapter = HostingManagedWorkerSessionAdapter(
            hosting=_ManagedChildPort(),  # type: ignore[arg-type]
            preparation=preparation,
        )

        start = asyncio.create_task(
            adapter.start(request, correlation_id="managed-cancel")
        )
        await preparation.captured.wait()
        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start

        assert preparation.public_calls == 0
        assert preparation.managed_calls == 1
        assert preparation.lease is not None
        assert preparation.lease.closed == 1

    asyncio.run(scenario())


def test_hosting_adapter_managed_preparation_runs_through_real_child_session(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        validations = 0

        def validate_current() -> None:
            nonlocal validations
            validations += 1

        request = _request(tmp_path, validate_current=validate_current)
        preparation = _ManagedPreparationPort()
        host, process_backend, endpoint_backend, capture_backend = (
            _managed_child_session_host()
        )
        adapter = HostingManagedWorkerSessionAdapter(
            hosting=host,
            preparation=preparation,
        )

        session = await adapter.start(request, correlation_id="managed-real-host")

        assert validations == 2
        assert preparation.public_calls == 0
        assert preparation.managed_calls == 1
        assert len(capture_backend.materials) == 1
        material = capture_backend.materials[0]
        assert material.request == preparation.specs[0].request
        assert material.verify_calls == 1
        assert material.claim_calls == 1
        assert material.transfer_calls == 1
        assert len(process_backend.processes) == 1
        assert len(endpoint_backend.transports) == 1

        await session.close()
        assert preparation.lease is not None
        assert preparation.lease.closed == 1
        assert material.close_calls == 1
        assert process_backend.close_handle_calls == 1
        assert endpoint_backend.child_close_calls == 1
        assert endpoint_backend.transports[0].close_calls == 1
        await host.close()
        assert process_backend.close_calls == 1
        assert endpoint_backend.close_calls == 1

    asyncio.run(scenario())


def test_hosting_adapter_managed_final_fence_failure_reclaims_real_child_session(
    tmp_path: Path,
) -> None:
    class _Signal:
        aborted = False

    async def scenario() -> None:
        signal = _Signal()
        request = _request(tmp_path, validate_current=lambda: None)
        preparation = _ManagedPreparationPort(
            on_verify=lambda: setattr(signal, "aborted", True)
        )
        host, process_backend, endpoint_backend, capture_backend = (
            _managed_child_session_host()
        )
        adapter = HostingManagedWorkerSessionAdapter(
            hosting=host,
            preparation=preparation,
        )

        with pytest.raises(WorkerBindingError) as caught:
            await adapter.start(
                request,
                correlation_id="managed-real-host-abort",
                signal=signal,
            )

        assert caught.value.code == "worker_hosting_start_aborted"
        assert preparation.public_calls == 0
        assert preparation.managed_calls == 1
        assert preparation.lease is not None
        assert preparation.lease.verified == 1
        assert preparation.lease.closed == 1
        assert len(capture_backend.materials) == 1
        material = capture_backend.materials[0]
        assert material.verify_calls == 0
        assert material.claim_calls == 0
        assert material.transfer_calls == 0
        assert material.close_calls == 1
        assert process_backend.processes == []
        assert process_backend.close_handle_calls == 0
        assert endpoint_backend.child_close_calls == 1
        assert len(endpoint_backend.transports) == 1
        assert endpoint_backend.transports[0].close_calls == 1
        await host.close()
        assert process_backend.close_calls == 1
        assert endpoint_backend.close_calls == 1

    asyncio.run(scenario())


def test_hosting_adapter_managed_capture_cancellation_reclaims_real_reservation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        request = _request(tmp_path, validate_current=lambda: None)
        preparation = _ManagedPreparationPort(pause_after_capture=True)
        host, process_backend, endpoint_backend, capture_backend = (
            _managed_child_session_host()
        )
        adapter = HostingManagedWorkerSessionAdapter(
            hosting=host,
            preparation=preparation,
        )

        start = asyncio.create_task(
            adapter.start(request, correlation_id="managed-real-host-cancel")
        )
        await preparation.captured.wait()
        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start

        assert preparation.public_calls == 0
        assert preparation.managed_calls == 1
        assert preparation.lease is not None
        assert preparation.lease.closed == 1
        assert len(capture_backend.materials) == 1
        material = capture_backend.materials[0]
        assert material.verify_calls == 0
        assert material.claim_calls == 0
        assert material.transfer_calls == 0
        assert material.close_calls == 1
        assert process_backend.processes == []
        assert endpoint_backend.transports == []
        await host.close()
        assert process_backend.close_calls == 1
        assert endpoint_backend.close_calls == 1

    asyncio.run(scenario())


def test_hosting_adapter_rechecks_abort_at_final_pre_spawn_fence(
    tmp_path: Path,
) -> None:
    class _Signal:
        aborted = False

    async def scenario() -> None:
        signal = _Signal()
        request = _request(tmp_path, validate_current=lambda: None)
        preparation = _PreparationPort(
            on_verify=lambda: setattr(signal, "aborted", True)
        )
        adapter = HostingManagedWorkerSessionAdapter(
            hosting=_ChildPort(),  # type: ignore[arg-type]
            preparation=preparation,  # type: ignore[arg-type]
        )

        with pytest.raises(WorkerBindingError) as caught:
            await adapter.start(
                request,
                correlation_id="hosting-aborted",
                signal=signal,
            )
        assert caught.value.code == "worker_hosting_start_aborted"
        assert preparation.lease is not None
        assert preparation.lease.closed == 1

    asyncio.run(scenario())


class _RouteSession:
    def __init__(self, request: ManagedWorkerLaunchRequestV1, correlation_id: str):
        self.evidence = type("Evidence", (), {})()
        self.request = request
        self.correlation_id = correlation_id


class _RoutePort:
    def __init__(self, *, wait: asyncio.Event | None = None, fail: bool = False):
        self.wait = wait
        self.fail = fail
        self.calls: list[str] = []
        self.entered = asyncio.Event()

    async def start(
        self,
        request: ManagedWorkerLaunchRequestV1,
        *,
        correlation_id: str,
        signal: object | None = None,
    ):
        del signal
        self.calls.append(correlation_id)
        self.entered.set()
        if self.wait is not None:
            await self.wait.wait()
        if self.fail:
            raise RuntimeError("selected owner failed")
        return _RouteSession(request, correlation_id)


def test_owner_router_defaults_current_and_never_falls_back(tmp_path: Path) -> None:
    async def scenario() -> None:
        request = _request(tmp_path, validate_current=lambda: None)
        current = _RoutePort()
        hosting = _RoutePort(fail=True)
        default = WorkerSessionOwnerRouter(
            current=current,  # type: ignore[arg-type]
            hosting=hosting,  # type: ignore[arg-type]
        )
        assert default.selection.to_dict() == {
            "code": "worker_hosting_current_default",
            "effectiveOwner": "current",
            "generation": 1,
            "hostingAvailable": True,
            "requestedOwner": "current",
            "rollbackLatched": False,
            "selectionVersion": 1,
        }
        await default.start(request, correlation_id="current-attempt")
        assert current.calls == ["current-attempt"]
        assert hosting.calls == []

        selected = WorkerSessionOwnerRouter(
            current=current,  # type: ignore[arg-type]
            hosting=hosting,  # type: ignore[arg-type]
            activation=WorkerHostingActivationV1(owner="hosting"),
        )
        with pytest.raises(RuntimeError, match="selected owner failed"):
            await selected.start(request, correlation_id="hosting-attempt")
        assert current.calls == ["current-attempt"]
        assert hosting.calls == ["hosting-attempt"]

    asyncio.run(scenario())


def test_owner_router_rollback_is_sticky_and_affects_only_future_attempts(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        request = _request(tmp_path, validate_current=lambda: None)
        release = asyncio.Event()
        current = _RoutePort()
        hosting = _RoutePort(wait=release)
        router = WorkerSessionOwnerRouter(
            current=current,  # type: ignore[arg-type]
            hosting=hosting,  # type: ignore[arg-type]
            activation=WorkerHostingActivationV1(owner="hosting"),
        )
        in_flight = asyncio.create_task(
            router.start(request, correlation_id="hosting-in-flight")
        )
        await hosting.entered.wait()
        diagnostic = router.rollback_to_current()
        assert diagnostic.effective_owner == "current"
        assert diagnostic.requested_owner == "hosting"
        assert diagnostic.rollback_latched is True
        assert diagnostic.generation == 2
        assert diagnostic.code == "worker_hosting_rollback_latched"
        assert router.rollback_to_current() == diagnostic
        release.set()
        assert (await in_flight).correlation_id == "hosting-in-flight"

        await router.start(request, correlation_id="current-after-rollback")
        assert hosting.calls == ["hosting-in-flight"]
        assert current.calls == ["current-after-rollback"]

    asyncio.run(scenario())


def test_hosting_opt_in_without_owner_fails_closed() -> None:
    with pytest.raises(WorkerHostingActivationError) as caught:
        WorkerSessionOwnerRouter(
            current=_RoutePort(),  # type: ignore[arg-type]
            activation=WorkerHostingActivationV1(owner="hosting"),
        )
    assert caught.value.code == "worker_hosting_owner_unavailable"


def test_supervisor_can_handshake_through_hosting_aggregate(tmp_path: Path) -> None:
    async def scenario() -> None:
        request = _request(tmp_path, validate_current=lambda: None)
        child = _ChildPort(WorkerFrameCodec.encode(_ready(request.identity)))
        adapter = HostingManagedWorkerSessionAdapter(
            hosting=child,  # type: ignore[arg-type]
            preparation=_PreparationPort(),  # type: ignore[arg-type]
        )
        supervisor = WorkerSupervisor(
            identity=request.identity,
            journal=WorkerSupervisorJournal(tmp_path / "hosting-workers.jsonl"),
            protocol="capability.query",
            protocol_version=1,
        )

        await supervisor.start_session(
            session_port=adapter,
            launch_request=request,
            correlation_id="hosting-supervisor",
        )
        assert supervisor.status.state == "healthy"
        assert child.lease is not None
        frame = child.lease.endpoint.writes[0]
        size = WorkerFrameCodec.decode_header(frame[:4])
        assert WorkerFrameCodec.decode_body(frame[4:], expected_size=size).kind == "start"

        await supervisor.fence(code="worker_test_fence")
        assert supervisor.status.state == "fenced"
        assert child.events == [
            "process.close",
            "endpoint.close",
            "session.closed",
        ]

    asyncio.run(scenario())


def test_supervisor_reclaims_invalid_unpublished_session(tmp_path: Path) -> None:
    class _InvalidSession:
        closed = False

        async def close(self) -> None:
            self.closed = True

    class _InvalidPort:
        def __init__(self, session: _InvalidSession) -> None:
            self.session = session

        async def start(self, *args, **kwargs):
            del args, kwargs
            return self.session

    async def scenario() -> None:
        request = _request(tmp_path, validate_current=lambda: None)
        invalid = _InvalidSession()
        supervisor = WorkerSupervisor(
            identity=request.identity,
            journal=WorkerSupervisorJournal(tmp_path / "invalid-session.jsonl"),
            protocol="capability.query",
            protocol_version=1,
        )

        with pytest.raises(WorkerSupervisorError) as caught:
            await supervisor.start_session(
                session_port=_InvalidPort(invalid),  # type: ignore[arg-type]
                launch_request=request,
                correlation_id="invalid-session",
            )
        assert caught.value.code == "worker_launch_failed"
        assert invalid.closed is True
        assert supervisor.status.state == "failed"

    asyncio.run(scenario())
