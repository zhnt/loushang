"""Default-dark Worker adapter over the Product-neutral Hosting session owner."""

from __future__ import annotations

import asyncio
from typing import TypeVar, cast

from loushang.harness.workspace.process import ProcessExit, ProcessStderrTail
from loushang.hosting import (
    ChildSessionHostingPort,
    ChildSessionLease,
    ChildSessionRequest,
    HostByteEndpoint,
    HostingError,
    HostingFailureCategory,
    LaunchPreparationLease,
    LaunchPreparationPort,
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting._launch_preparation import (
    _LaunchCapturePort,
    _ManagedLaunchPreparationPort,
    _ManagedLaunchPreparationResult,
)

from .contracts import (
    ManagedWorkerLaunchRequestV1,
    WorkerBindingError,
    WorkerLaunchEvidenceV1,
)
from .launch import WORKER_DIAGNOSTIC_READ_MAX_BYTES
from .protocol import WorkerFramedTransport, WorkerProtocolError
from .session import (
    ManagedWorkerProcessControl,
    ManagedWorkerSession,
    ManagedWorkerSessionLaunchPort,
    _close_unpublished_worker_session,
    _launch_evidence,
)

WORKER_HOSTING_ENDPOINT_READ_CHUNK_BYTES = 64 * 1024

_T = TypeVar("_T")


class HostingManagedWorkerSessionAdapter(ManagedWorkerSessionLaunchPort):
    """Harness meaning adapter over an injected atomic Hosting capability.

    The preparation port remains caller-owned authority. This adapter neither
    manufactures containment evidence nor resolves a mutable executable path.
    No production composition root binds this adapter in H5.
    """

    def __init__(
        self,
        *,
        hosting: ChildSessionHostingPort,
        preparation: LaunchPreparationPort,
        endpoint_read_chunk_bytes: int = WORKER_HOSTING_ENDPOINT_READ_CHUNK_BYTES,
    ) -> None:
        if not isinstance(hosting, ChildSessionHostingPort):
            raise TypeError("Worker Hosting adapter requires a child-session port")
        if not isinstance(preparation, LaunchPreparationPort):
            raise TypeError("Worker Hosting adapter requires a preparation port")
        if (
            type(endpoint_read_chunk_bytes) is not int
            or endpoint_read_chunk_bytes < 1
            or endpoint_read_chunk_bytes > WORKER_HOSTING_ENDPOINT_READ_CHUNK_BYTES
        ):
            raise ValueError("Worker Hosting endpoint read chunk is outside its bound")
        self._hosting = hosting
        self._preparation = preparation
        self._endpoint_read_chunk_bytes = endpoint_read_chunk_bytes

    async def start(
        self,
        request: ManagedWorkerLaunchRequestV1,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ManagedWorkerSession:
        if not isinstance(request, ManagedWorkerLaunchRequestV1):
            raise TypeError("Worker Hosting adapter requires a typed launch request")
        _raise_if_aborted(signal)
        evidence = _launch_evidence(request, correlation_id=correlation_id)
        request.validate_current()
        request.runtime.verify()
        _raise_if_aborted(signal)
        process_request = _map_worker_request(request)
        preparation = _worker_launch_preparation_port(
            expected=process_request,
            worker_request=request,
            delegate=self._preparation,
            signal=signal,
        )
        try:
            lease = await self._hosting.start(
                ChildSessionRequest(process=process_request),
                preparation,
            )
        except HostingError as exc:
            worker_error = _find_cause(exc, WorkerBindingError)
            if worker_error is not None:
                raise worker_error from exc
            raise _map_start_error(exc) from exc
        if not isinstance(lease, ChildSessionLease):
            await _close_unpublished_worker_session(
                lease,
                task_name="harness-invalid-hosting-session-rollback",
            )
            raise TypeError("Worker Hosting owner returned an invalid session lease")
        try:
            return _HostingManagedWorkerSession(
                lease=lease,
                evidence=evidence,
                endpoint_read_chunk_bytes=self._endpoint_read_chunk_bytes,
            )
        except BaseException as primary:
            try:
                await _close_unpublished_worker_session(
                    lease,
                    task_name="harness-hosting-session-wrap-rollback",
                )
            except BaseException as cleanup_error:
                if not isinstance(primary, asyncio.CancelledError):
                    primary.add_note(
                        f"Worker Hosting session rollback also failed: {cleanup_error}"
                    )
                raise primary from cleanup_error
            raise


class _WorkerLaunchPreparationPort:
    def __init__(
        self,
        *,
        expected: ProcessLaunchRequest,
        worker_request: ManagedWorkerLaunchRequestV1,
        delegate: LaunchPreparationPort,
        signal: object | None,
    ) -> None:
        self._expected = expected
        self._worker_request = worker_request
        self._delegate = delegate
        self._signal = signal

    async def prepare(
        self, request: ProcessLaunchRequest
    ) -> LaunchPreparationLease:
        self._require_expected(request)
        prepared = await self._delegate.prepare(request)
        return self._wrap(prepared)

    def _require_expected(self, request: ProcessLaunchRequest) -> None:
        if request != self._expected:
            raise WorkerBindingError(
                "Worker Hosting material changed before preparation",
                code="worker_hosting_request_changed",
            )

    def _wrap(self, prepared: object) -> LaunchPreparationLease:
        if not isinstance(prepared, LaunchPreparationLease):
            raise TypeError("Worker Hosting preparation returned an invalid lease")
        return _WorkerLaunchPreparationLease(
            delegate=prepared,
            worker_request=self._worker_request,
            signal=self._signal,
        )


class _ManagedWorkerLaunchPreparationPort(
    _WorkerLaunchPreparationPort,
    _ManagedLaunchPreparationPort,
):
    """Preserve Hosting's nominal managed seam while adding Worker meaning."""

    def __init__(
        self,
        *,
        expected: ProcessLaunchRequest,
        worker_request: ManagedWorkerLaunchRequestV1,
        delegate: LaunchPreparationPort,
        signal: object | None,
    ) -> None:
        super().__init__(
            expected=expected,
            worker_request=worker_request,
            delegate=delegate,
            signal=signal,
        )
        self._managed_delegate = cast(_ManagedLaunchPreparationPort, delegate)

    async def prepare_managed(
        self,
        request: ProcessLaunchRequest,
        capture: _LaunchCapturePort,
    ) -> _ManagedLaunchPreparationResult:
        self._require_expected(request)
        result = await self._managed_delegate.prepare_managed(request, capture)
        if not isinstance(result, _ManagedLaunchPreparationResult):
            raise TypeError(
                "Worker Hosting managed preparation returned an invalid result"
            )
        return _ManagedLaunchPreparationResult(
            lease=self._wrap(result.lease),
            binding=result.binding,
        )


def _worker_launch_preparation_port(
    *,
    expected: ProcessLaunchRequest,
    worker_request: ManagedWorkerLaunchRequestV1,
    delegate: LaunchPreparationPort,
    signal: object | None,
) -> _WorkerLaunchPreparationPort:
    preparation_type = (
        _ManagedWorkerLaunchPreparationPort
        if isinstance(delegate, _ManagedLaunchPreparationPort)
        else _WorkerLaunchPreparationPort
    )
    return preparation_type(
        expected=expected,
        worker_request=worker_request,
        delegate=delegate,
        signal=signal,
    )


class _WorkerLaunchPreparationLease:
    def __init__(
        self,
        *,
        delegate: LaunchPreparationLease,
        worker_request: ManagedWorkerLaunchRequestV1,
        signal: object | None,
    ) -> None:
        self._delegate = delegate
        self._worker_request = worker_request
        self._signal = signal

    @property
    def request(self) -> ProcessLaunchRequest:
        return self._delegate.request

    async def verify_current(self) -> None:
        _raise_if_aborted(self._signal)
        await self._delegate.verify_current()
        _raise_if_aborted(self._signal)
        self._worker_request.runtime.verify()
        self._worker_request.validate_current()
        _raise_if_aborted(self._signal)

    async def close(self) -> None:
        await self._delegate.close()


class _HostingManagedWorkerSession:
    def __init__(
        self,
        *,
        lease: ChildSessionLease,
        evidence: WorkerLaunchEvidenceV1,
        endpoint_read_chunk_bytes: int,
    ) -> None:
        self._lease = lease
        self._evidence = evidence
        self._process = _HostingManagedWorkerProcess(lease)
        self._transport = WorkerFramedTransport(
            _HostingWorkerByteTransport(
                lease,
                lease.endpoint,
                read_chunk_bytes=endpoint_read_chunk_bytes,
            )
        )

    @property
    def evidence(self) -> WorkerLaunchEvidenceV1:
        return self._evidence

    @property
    def process(self) -> ManagedWorkerProcessControl:
        return self._process

    @property
    def transport(self) -> WorkerFramedTransport:
        return self._transport

    async def terminate(self) -> None:
        await self._lease.close()

    async def close(self) -> None:
        await self._lease.close()


class _HostingManagedWorkerProcess:
    def __init__(self, session: ChildSessionLease) -> None:
        self._session = session
        self._process = session.process

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        _require_diagnostic_read_bound(max_bytes)
        return await self._process.read_stdout(max_bytes)

    async def read_stderr(self, max_bytes: int = 64 * 1024) -> bytes:
        _require_diagnostic_read_bound(max_bytes)
        return await self._process.read_stderr(max_bytes)

    async def wait(self) -> ProcessExit:
        result = await self._process.wait()
        return ProcessExit(return_code=result.return_code)

    async def terminate(self) -> ProcessExit:
        await self._session.close()
        result = await self._process.wait()
        return ProcessExit(return_code=result.return_code)

    async def close(self) -> None:
        await self._session.close()

    def stderr_tail(self) -> ProcessStderrTail:
        tail = self._process.stderr_tail()
        return ProcessStderrTail(content=tail.content, truncated=tail.truncated)


class _HostingWorkerByteTransport:
    def __init__(
        self,
        session: ChildSessionLease,
        endpoint: HostByteEndpoint,
        *,
        read_chunk_bytes: int,
    ) -> None:
        self._session = session
        self._endpoint = endpoint
        self._read_chunk_bytes = read_chunk_bytes

    async def read_exactly(self, size: int) -> bytes:
        if type(size) is not int or size < 1:
            raise ValueError("Worker Hosting read size must be positive")
        result = bytearray()
        while len(result) < size:
            try:
                chunk = await self._endpoint.read(
                    min(size - len(result), self._read_chunk_bytes)
                )
            except HostingError as exc:
                if exc.category is HostingFailureCategory.PEER_CLOSED:
                    raise EOFError from exc
                raise WorkerProtocolError(
                    "Worker Hosting endpoint read failed",
                    code="worker_hosting_endpoint_read_failed",
                ) from exc
            if not chunk:
                raise EOFError
            result.extend(chunk)
        return bytes(result)

    async def write(self, body: bytes) -> None:
        await self._endpoint.write(body)

    async def close(self) -> None:
        # The aggregate owner, not this view, preserves process-before-endpoint
        # cleanup order.
        await self._session.close()


def _map_worker_request(
    request: ManagedWorkerLaunchRequestV1,
) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(str(request.runtime.executable),),
        cwd=str(request.runtime.package_root),
        effective_environment=(),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.PIPE,
        ),
    )


def _map_start_error(error: HostingError) -> WorkerBindingError:
    if error.category is HostingFailureCategory.CAPACITY_EXHAUSTED:
        code = "worker_hosting_capacity_exhausted"
    elif error.category is HostingFailureCategory.PLATFORM_UNSUPPORTED:
        code = "worker_hosting_platform_unsupported"
    elif error.category in {
        HostingFailureCategory.PREPARATION_REJECTED,
        HostingFailureCategory.PREPARATION_STALE,
        HostingFailureCategory.PREPARATION_FAILED,
    }:
        code = "worker_hosting_preparation_failed"
    else:
        code = "worker_hosting_start_failed"
    return WorkerBindingError("Managed Worker Hosting start failed", code=code)


def _find_cause(error: BaseException, error_type: type[_T]) -> _T | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, error_type):
            return cast(_T, current)
        current = current.__cause__
    return None


def _require_diagnostic_read_bound(max_bytes: int) -> None:
    if (
        type(max_bytes) is not int
        or max_bytes < 1
        or max_bytes > WORKER_DIAGNOSTIC_READ_MAX_BYTES
    ):
        raise ValueError("Worker diagnostic read size is outside its bound")


def _raise_if_aborted(signal: object | None) -> None:
    if signal is not None and getattr(signal, "aborted", False):
        raise WorkerBindingError(
            "Managed Worker Hosting start was aborted",
            code="worker_hosting_start_aborted",
        )


async def _await_owned(task: asyncio.Task[_T]) -> _T:
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            if cancellation is None:
                cancellation = exc
        except BaseException as exc:
            if cancellation is not None:
                raise cancellation from exc
            raise
    if cancellation is not None:
        raise cancellation
    return cast(_T, result)


__all__ = [
    "WORKER_HOSTING_ENDPOINT_READ_CHUNK_BYTES",
    "HostingManagedWorkerSessionAdapter",
]
