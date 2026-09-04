"""Aggregate process-plus-transport ownership for one supervised Worker."""

from __future__ import annotations

import asyncio
import inspect
from typing import Protocol, TypeVar, cast, runtime_checkable

from loushang.harness.workspace.process import ProcessExit, ProcessStderrTail

from .contracts import ManagedWorkerLaunchRequestV1, WorkerLaunchEvidenceV1
from .launch import ManagedWorkerLaunchPort
from .protocol import WorkerFramedTransport

_T = TypeVar("_T")


@runtime_checkable
class ManagedWorkerProcessControl(Protocol):
    """Process operations used by the protocol supervisor, without spawn authority."""

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes: ...

    async def read_stderr(self, max_bytes: int = 64 * 1024) -> bytes: ...

    async def wait(self) -> ProcessExit: ...

    async def terminate(self) -> ProcessExit: ...

    async def close(self) -> None: ...

    def stderr_tail(self) -> ProcessStderrTail: ...


@runtime_checkable
class ManagedWorkerSession(Protocol):
    """One aggregate Worker attempt published with process and transport together."""

    @property
    def evidence(self) -> WorkerLaunchEvidenceV1: ...

    @property
    def process(self) -> ManagedWorkerProcessControl: ...

    @property
    def transport(self) -> WorkerFramedTransport: ...

    async def terminate(self) -> None: ...

    async def close(self) -> None: ...


class ManagedWorkerSessionLaunchPort(Protocol):
    """Owner port that publishes one complete Worker runtime session or neither."""

    async def start(
        self,
        request: ManagedWorkerLaunchRequestV1,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ManagedWorkerSession: ...


class _CurrentManagedWorkerSession:
    """Compatibility aggregate over the Current separate process/transport owners."""

    def __init__(
        self,
        *,
        process: ManagedWorkerProcessControl,
        transport: WorkerFramedTransport,
        evidence: WorkerLaunchEvidenceV1,
    ) -> None:
        self._process = process
        self._transport = transport
        self._evidence = evidence
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None

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
        failures: list[BaseException] = []
        try:
            await self._transport.close()
        except BaseException as exc:
            failures.append(exc)
        try:
            await self._process.terminate()
        except BaseException as exc:
            failures.append(exc)
            try:
                await self._process.close()
            except BaseException as close_error:
                failures.append(close_error)
        if failures:
            raise BaseExceptionGroup(
                "Current Worker session termination failed", failures
            )

    async def close(self) -> None:
        async with self._close_lock:
            task = self._close_task
            if task is None:
                task = asyncio.create_task(
                    self._close_owned(),
                    name="harness-current-worker-session-close",
                )
                self._close_task = task
        await _await_owned(task)

    async def _close_owned(self) -> None:
        failures: list[BaseException] = []
        try:
            await self._transport.close()
        except BaseException as exc:
            failures.append(exc)
        try:
            await self._process.close()
        except BaseException as exc:
            failures.append(exc)
        if failures:
            raise BaseExceptionGroup("Current Worker session cleanup failed", failures)


class _CurrentManagedWorkerSessionPort:
    def __init__(
        self,
        launch_port: ManagedWorkerLaunchPort,
        transport: WorkerFramedTransport,
    ) -> None:
        if not callable(getattr(launch_port, "start", None)):
            raise TypeError("Current Worker session requires a launch port")
        if not isinstance(transport, WorkerFramedTransport):
            raise TypeError("Current Worker session requires a framed transport")
        self._launch_port = launch_port
        self._transport = transport
        self._started = False

    async def start(
        self,
        request: ManagedWorkerLaunchRequestV1,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ManagedWorkerSession:
        if self._started:
            raise RuntimeError("Current Worker session port is single-use")
        self._started = True
        try:
            process = await self._launch_port.start(
                request,
                correlation_id=correlation_id,
                signal=signal,
            )
        except BaseException as primary:
            cleanup = asyncio.create_task(
                self._transport.close(),
                name="harness-current-worker-transport-rollback",
            )
            try:
                await _await_owned(cleanup)
            except BaseException as cleanup_error:
                if not isinstance(primary, asyncio.CancelledError):
                    primary.add_note(
                        f"Current Worker transport rollback also failed: {cleanup_error}"
                    )
                raise primary from cleanup_error
            raise
        if not _is_managed_worker_process_control(process):
            invalid_error = TypeError(
                "Current Worker launch returned an invalid process"
            )
            cleanup = asyncio.create_task(
                self._rollback_invalid_process(process),
                name="harness-invalid-worker-process-rollback",
            )
            try:
                await _await_owned(cleanup)
            except BaseException as cleanup_error:
                invalid_error.add_note(
                    f"Invalid Current Worker process rollback also failed: {cleanup_error}"
                )
                raise invalid_error from cleanup_error
            raise invalid_error
        return _CurrentManagedWorkerSession(
            process=cast(ManagedWorkerProcessControl, process),
            transport=self._transport,
            evidence=_launch_evidence(request, correlation_id=correlation_id),
        )

    async def _rollback_invalid_process(self, process: object) -> None:
        failures: list[BaseException] = []
        try:
            await self._transport.close()
        except BaseException as exc:
            failures.append(exc)
        close = getattr(process, "close", None)
        if callable(close):
            try:
                operation = close()
                if not inspect.isawaitable(operation):
                    raise TypeError("Current Worker process close must be awaitable")
                await operation
            except BaseException as exc:
                failures.append(exc)
        if failures:
            raise BaseExceptionGroup(
                "Invalid Current Worker process cleanup failed", failures
            )


def bind_current_worker_session_port(
    launch_port: ManagedWorkerLaunchPort,
    transport: WorkerFramedTransport,
) -> ManagedWorkerSessionLaunchPort:
    """Aggregate already-owned Current capabilities for one selection attempt."""

    return _CurrentManagedWorkerSessionPort(launch_port, transport)


def _launch_evidence(
    request: ManagedWorkerLaunchRequestV1,
    *,
    correlation_id: str,
) -> WorkerLaunchEvidenceV1:
    return WorkerLaunchEvidenceV1(
        identity_fingerprint=request.identity.fingerprint,
        runtime_binding_fingerprint=request.runtime.fingerprint,
        request_fingerprint=request.fingerprint,
        launch_correlation_id=correlation_id,
    )


def _is_managed_worker_process_control(value: object) -> bool:
    """Validate only lifecycle operations consumed by WorkerSupervisor."""

    return all(
        callable(getattr(value, name, None))
        for name in ("wait", "terminate", "close")
    )


async def _close_unpublished_worker_session(
    value: object,
    *,
    task_name: str,
) -> None:
    close = getattr(value, "close", None)
    if not callable(close):
        return
    operation = close()
    if not inspect.isawaitable(operation):
        raise TypeError("Worker session close must be awaitable")

    async def settle() -> None:
        await operation

    await _await_owned(asyncio.create_task(settle(), name=task_name))


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
    "ManagedWorkerProcessControl",
    "ManagedWorkerSession",
    "ManagedWorkerSessionLaunchPort",
    "bind_current_worker_session_port",
]
