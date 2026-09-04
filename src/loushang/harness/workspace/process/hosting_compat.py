"""Dark compatibility adapter from Harness Process Host to Hosting H2."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TypeVar, cast

from loushang.hosting import (
    HostingError,
    HostingFailureCategory,
    LaunchPreparationLease,
    ProcessHostingPort,
    ProcessLease,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
    create_process_host,
)
from loushang.hosting import (
    ProcessExit as HostingProcessExit,
)
from loushang.hosting import (
    ProcessLaunchRequest as HostingProcessLaunchRequest,
)

from ._sealed_executable import _process_inherited_file_descriptors
from .host import (
    ProcessHostCapacityError,
    ProcessHostClosedError,
    ProcessHostError,
    ProcessWriteLimitError,
)
from .local import ProcessContainmentPlan, ProcessContainmentPlanner
from .types import ProcessExit, ProcessHandle, ProcessLaunchRequest, ProcessStderrTail

_T = TypeVar("_T")
_E = TypeVar("_E", bound=BaseException)


class HostingCompatibilityUnavailableError(ProcessHostError):
    """The Current Harness request cannot be represented by Hosting v1."""


class _CompatibilityPreparationError(Exception):
    def __init__(self, original: BaseException) -> None:
        self.original = original
        super().__init__("Harness preparation failed before Hosting spawn")


@dataclass(slots=True)
class _HarnessPreparationLease:
    _request: HostingProcessLaunchRequest
    _containment: ProcessContainmentPlan | None

    @property
    def request(self) -> HostingProcessLaunchRequest:
        return self._request

    async def verify_current(self) -> None:
        containment = self._containment
        if containment is None:
            return
        inherited = _process_inherited_file_descriptors(containment.request)
        if inherited:
            raise HostingCompatibilityUnavailableError(
                "Hosting v1 cannot transfer the Harness sealed-executable "
                "or bound-cwd descriptor"
            )

    async def close(self) -> None:
        if self._containment is not None:
            await self._containment.close()


class _HarnessPreparationPort:
    def __init__(
        self,
        request: ProcessLaunchRequest,
        containment_planner: ProcessContainmentPlanner | None,
    ) -> None:
        self._request = request
        self._containment_planner = containment_planner

    async def prepare(
        self, request: HostingProcessLaunchRequest
    ) -> LaunchPreparationLease:
        containment: ProcessContainmentPlan | None = None
        try:
            prepared = self._request
            if self._containment_planner is not None:
                candidate = await self._containment_planner(self._request)
                if not isinstance(candidate, ProcessContainmentPlan):
                    raise TypeError(
                        "process containment planner must return ProcessContainmentPlan"
                    )
                containment = candidate
                prepared = containment.request
            mapped = _map_request(prepared)
            if mapped.streams != request.streams:
                raise RuntimeError("Hosting compatibility stream intent changed")
            lease = _HarnessPreparationLease(mapped, containment)
            await lease.verify_current()
            return lease
        except BaseException as primary:
            if containment is not None:
                cleanup = asyncio.create_task(
                    containment.close(),
                    name="harness-hosting-compat-preparation-rollback",
                )
                try:
                    await _await_owned(cleanup)
                except BaseException as cleanup_error:
                    if isinstance(primary, asyncio.CancelledError):
                        raise primary from cleanup_error
                    primary.add_note(
                        f"Harness Hosting preparation cleanup also failed: {cleanup_error}"
                    )
                    raise primary from cleanup_error
            if isinstance(primary, asyncio.CancelledError):
                raise
            raise _CompatibilityPreparationError(primary) from primary


class _HarnessProcessHandle(ProcessHandle):
    def __init__(self, lease: ProcessLease, *, stream_stderr: bool) -> None:
        self._lease = lease
        self._stream_stderr = stream_stderr

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        try:
            return await self._lease.read_stdout(max_bytes)
        except HostingError as exc:
            raise _map_operation_error(exc) from exc

    async def read_stderr(self, max_bytes: int = 64 * 1024) -> bytes:
        if not self._stream_stderr:
            raise ProcessHostError(
                "stderr streaming was not requested for this process"
            )
        try:
            return await self._lease.read_stderr(max_bytes)
        except HostingError as exc:
            raise _map_operation_error(exc) from exc

    async def write_stdin(self, data: bytes) -> None:
        try:
            await self._lease.write_stdin(data)
        except HostingError as exc:
            raise _map_operation_error(exc) from exc

    async def close_stdin(self) -> None:
        try:
            await self._lease.close_stdin()
        except HostingError as exc:
            raise _map_operation_error(exc) from exc

    async def wait(self) -> ProcessExit:
        try:
            return _map_exit(await self._lease.wait())
        except HostingError as exc:
            raise _map_operation_error(exc) from exc

    async def terminate(self) -> ProcessExit:
        try:
            return _map_exit(await self._lease.terminate())
        except HostingError as exc:
            raise _map_operation_error(exc) from exc

    async def close(self) -> None:
        try:
            await self._lease.close()
        except HostingError as exc:
            raise _map_operation_error(exc) from exc

    def stderr_tail(self) -> ProcessStderrTail:
        tail = self._lease.stderr_tail()
        return ProcessStderrTail(content=tail.content, truncated=tail.truncated)


class HostingProcessHostAdapter:
    """Inactive-by-default Harness facade over the public Hosting H2 port."""

    def __init__(
        self,
        *,
        hosting_port: ProcessHostingPort | None = None,
        max_processes: int = 4,
        max_read_bytes: int = 64 * 1024,
        max_write_bytes: int = 1024 * 1024,
        stderr_max_bytes: int = 64 * 1024,
        termination_grace_seconds: float = 1.0,
    ) -> None:
        self._hosting = (
            hosting_port
            if hosting_port is not None
            else create_process_host(
                max_processes=max_processes,
                max_read_bytes=max_read_bytes,
                max_write_bytes=max_write_bytes,
                stderr_tail_bytes=stderr_max_bytes,
                termination_grace_seconds=termination_grace_seconds,
            )
        )

    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        containment_planner: ProcessContainmentPlanner | None = None,
    ) -> ProcessHandle:
        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("HostingProcessHostAdapter.start requires ProcessLaunchRequest")
        try:
            mapped = _map_request(request)
            lease = await self._hosting.start(
                mapped,
                _HarnessPreparationPort(request, containment_planner),
            )
        except HostingError as exc:
            preparation_error = _find_cause(exc, _CompatibilityPreparationError)
            if preparation_error is not None:
                raise preparation_error.original from exc
            unavailable = _find_cause(exc, HostingCompatibilityUnavailableError)
            if unavailable is not None:
                raise unavailable from exc
            raise _map_operation_error(exc) from exc
        return _HarnessProcessHandle(
            lease,
            stream_stderr=request.stream_stderr,
        )

    async def close(self) -> None:
        try:
            await self._hosting.close()
        except HostingError as exc:
            raise _map_operation_error(exc) from exc


def _map_request(request: ProcessLaunchRequest) -> HostingProcessLaunchRequest:
    try:
        return HostingProcessLaunchRequest(
            argv=request.command,
            cwd=request.cwd,
            effective_environment=request.effective_environment,
            streams=ProcessStreamSpec(
                stdin=ProcessStdinMode.PIPE,
                stdout=ProcessStdoutMode.PIPE,
                stderr=(
                    ProcessStderrMode.PIPE
                    if request.stream_stderr
                    else ProcessStderrMode.CAPTURE_TAIL
                ),
            ),
        )
    except HostingError as exc:
        raise HostingCompatibilityUnavailableError(
            "Harness process request is outside the Hosting v1 contract"
        ) from exc


def _map_exit(exit_result: HostingProcessExit) -> ProcessExit:
    return ProcessExit(return_code=exit_result.return_code)


def _map_operation_error(error: HostingError) -> Exception:
    if error.category is HostingFailureCategory.CAPACITY_EXHAUSTED:
        return ProcessHostCapacityError("process host capacity is exhausted")
    if error.category in {
        HostingFailureCategory.HOST_CLOSED,
        HostingFailureCategory.PEER_CLOSED,
    }:
        return ProcessHostClosedError("hosted process is closed")
    if error.category is HostingFailureCategory.WRITE_BOUND_EXCEEDED:
        return ProcessWriteLimitError("stdin write exceeds its fixed limit")
    if error.category is HostingFailureCategory.READ_BOUND_EXCEEDED:
        return ValueError("max_bytes exceeds the process host read limit")
    return ProcessHostError(f"Hosting process operation failed: {error.category.value}")


def _find_cause(
    error: BaseException,
    error_type: type[_E],
) -> _E | None:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, error_type):
            return current
        current = current.__cause__
    return None


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


__all__ = ["HostingCompatibilityUnavailableError", "HostingProcessHostAdapter"]
