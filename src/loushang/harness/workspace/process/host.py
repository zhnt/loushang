"""Session-owned process host with fixed limits and exactly-once cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass

from loushang.harness.workspace._local_process import (
    kill_local_process_tree,
    terminate_local_process_tree,
)

from .local import (
    LocalProcessSpawner,
    ProcessContainmentPlan,
    ProcessContainmentPlanner,
    ProcessSpawner,
    ProcessTransport,
)
from .types import ProcessExit, ProcessHandle, ProcessLaunchRequest, ProcessStderrTail


class ProcessHostError(RuntimeError):
    pass


class ProcessHostClosedError(ProcessHostError):
    pass


class ProcessHostCapacityError(ProcessHostError):
    pass


class ProcessWriteLimitError(ProcessHostError):
    pass


@dataclass(slots=True)
class _Reservation:
    reservation_id: int
    owner: asyncio.Task[object]
    transport: ProcessTransport | None = None
    containment: ProcessContainmentPlan | None = None
    cleanup_error: BaseException | None = None

    def attach(self, transport: ProcessTransport) -> None:
        if self.transport is not None and self.transport is not transport:
            raise RuntimeError("process reservation already owns a transport")
        self.transport = transport

    def attach_containment(self, containment: ProcessContainmentPlan) -> None:
        if self.containment is not None and self.containment is not containment:
            raise RuntimeError("process reservation already owns containment")
        self.containment = containment


class _BoundedByteTail:
    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._content = bytearray()
        self._truncated = False

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._content.extend(chunk)
        overflow = len(self._content) - self._max_bytes
        if overflow > 0:
            del self._content[:overflow]
            self._truncated = True

    def snapshot(self) -> ProcessStderrTail:
        return ProcessStderrTail(
            content=bytes(self._content),
            truncated=self._truncated,
        )


class _HostedProcess(ProcessHandle):
    def __init__(
        self,
        transport: ProcessTransport,
        *,
        max_read_bytes: int,
        max_write_bytes: int,
        stderr_max_bytes: int,
        termination_grace_seconds: float,
        containment: ProcessContainmentPlan | None,
        on_exit: Callable[[_HostedProcess], Awaitable[None]],
    ) -> None:
        self._transport = transport
        self._max_read_bytes = max_read_bytes
        self._max_write_bytes = max_write_bytes
        self._termination_grace_seconds = termination_grace_seconds
        self._containment = containment
        self._on_exit = on_exit
        self._stderr_tail = _BoundedByteTail(stderr_max_bytes)
        self._stdin_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._stdin_closed = False
        self._closing = False
        self._exit: asyncio.Future[ProcessExit] = (
            asyncio.get_running_loop().create_future()
        )
        self._termination_task: asyncio.Task[ProcessExit] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(),
            name="harness-hosted-process-stderr",
        )
        self._finalizer_task = asyncio.create_task(
            self._finalize(),
            name="harness-hosted-process-finalizer",
        )

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes < 1
            or max_bytes > self._max_read_bytes
        ):
            raise ValueError(f"max_bytes must be between 1 and {self._max_read_bytes}")
        stream = self._transport.stdout
        if stream is None:
            return b""
        return await stream.read(max_bytes)

    async def write_stdin(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("hosted process stdin writes must be bytes")
        if len(data) > self._max_write_bytes:
            raise ProcessWriteLimitError(
                f"stdin write exceeds fixed {self._max_write_bytes}-byte limit"
            )
        async with self._stdin_lock:
            if self._closing or self._exit.done() or self._stdin_closed:
                raise ProcessHostClosedError("hosted process stdin is closed")
            stream = self._transport.stdin
            if stream is None:
                raise ProcessHostClosedError("hosted process has no stdin pipe")
            try:
                stream.write(data)
                await stream.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise ProcessHostClosedError("hosted process stdin is closed") from exc

    async def close_stdin(self) -> None:
        async with self._stdin_lock:
            if self._stdin_closed:
                return
            self._stdin_closed = True
            stream = self._transport.stdin
            if stream is None:
                return
            stream.close()
            with suppress(BrokenPipeError, ConnectionResetError):
                await stream.wait_closed()

    async def wait(self) -> ProcessExit:
        return await asyncio.shield(self._exit)

    async def terminate(self) -> ProcessExit:
        async with self._lifecycle_lock:
            task = self._termination_task
            if task is None:
                self._closing = True
                task = asyncio.create_task(
                    self._terminate_owned(),
                    name="harness-hosted-process-terminate",
                )
                self._termination_task = task
        return await asyncio.shield(task)

    async def close(self) -> None:
        async with self._lifecycle_lock:
            task = self._close_task
            if task is None:
                self._closing = True
                task = asyncio.create_task(
                    self._close_owned(),
                    name="harness-hosted-process-close",
                )
                self._close_task = task
        await asyncio.shield(task)

    def stderr_tail(self) -> ProcessStderrTail:
        return self._stderr_tail.snapshot()

    def _is_settled(self) -> bool:
        return self._exit.done()

    async def _drain_stderr(self) -> None:
        stream = self._transport.stderr
        if stream is None:
            return
        while True:
            chunk = await stream.read(64 * 1024)
            if not chunk:
                return
            self._stderr_tail.append(chunk)

    async def _finalize(self) -> None:
        primary_error: BaseException | None = None
        return_code: int | None = None
        try:
            try:
                return_code = await self._transport.wait()
            except BaseException as exc:
                primary_error = exc
            try:
                await self._stderr_task
            except BaseException as exc:
                if primary_error is None:
                    primary_error = exc
                else:
                    primary_error.add_note(f"stderr cleanup also failed: {exc}")
            if self._containment is not None:
                try:
                    await self._containment.close()
                except BaseException as exc:
                    if primary_error is None:
                        primary_error = exc
                    else:
                        primary_error.add_note(
                            f"containment cleanup also failed: {exc}"
                        )
            if not self._exit.done():
                if primary_error is not None:
                    self._exit.set_exception(primary_error)
                else:
                    assert return_code is not None
                    self._exit.set_result(ProcessExit(return_code=return_code))
        finally:
            self._closing = True
            await self._on_exit(self)

    async def _terminate_owned(self) -> ProcessExit:
        if self._exit.done():
            return await asyncio.shield(self._exit)
        stdin_error: BaseException | None = None
        try:
            await self.close_stdin()
        except BaseException as exc:
            stdin_error = exc
        await terminate_local_process_tree(self._transport)
        try:
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(self._exit),
                    self._termination_grace_seconds,
                )
            except TimeoutError:
                await kill_local_process_tree(self._transport)
                result = await asyncio.shield(self._exit)
        except BaseException as settlement_error:
            if stdin_error is not None:
                stdin_error.add_note(
                    f"process settlement also failed: {settlement_error}"
                )
                raise stdin_error from settlement_error
            raise
        if stdin_error is not None:
            raise stdin_error
        return result

    async def _close_owned(self) -> None:
        primary_error: BaseException | None = None
        try:
            await self.close_stdin()
        except BaseException as exc:
            primary_error = exc
        try:
            await self.terminate()
        except BaseException as exc:
            primary_error = _record_cleanup_error(
                primary_error,
                exc,
                context="process termination also failed",
            )
        try:
            await self._finalizer_task
        except BaseException as exc:
            primary_error = _record_cleanup_error(
                primary_error,
                exc,
                context="process finalization also failed",
            )
        if primary_error is not None:
            raise primary_error


class ProcessHost:
    """Internal owner for a bounded set of long-lived child processes."""

    def __init__(
        self,
        *,
        spawner: ProcessSpawner | None = None,
        max_processes: int = 4,
        max_read_bytes: int = 64 * 1024,
        max_write_bytes: int = 1024 * 1024,
        stderr_max_bytes: int = 64 * 1024,
        termination_grace_seconds: float = 1.0,
    ) -> None:
        for name, value in (
            ("max_processes", max_processes),
            ("max_read_bytes", max_read_bytes),
            ("max_write_bytes", max_write_bytes),
            ("stderr_max_bytes", stderr_max_bytes),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if termination_grace_seconds <= 0:
            raise ValueError("termination_grace_seconds must be positive")
        self._spawner = spawner or LocalProcessSpawner()
        self._max_processes = max_processes
        self._max_read_bytes = max_read_bytes
        self._max_write_bytes = max_write_bytes
        self._stderr_max_bytes = stderr_max_bytes
        self._termination_grace_seconds = termination_grace_seconds
        self._state = "open"
        self._lock = asyncio.Lock()
        self._next_reservation_id = 1
        self._reservations: dict[int, _Reservation] = {}
        self._registrations: set[_HostedProcess] = set()
        self._close_task: asyncio.Task[None] | None = None

    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        containment_planner: ProcessContainmentPlanner | None = None,
    ) -> ProcessHandle:
        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("ProcessHost.start requires ProcessLaunchRequest")
        owner = asyncio.current_task()
        if owner is None:
            raise RuntimeError("ProcessHost.start requires an asyncio task")
        async with self._lock:
            if self._state != "open":
                raise ProcessHostClosedError("process host is closing")
            if (
                len(self._reservations) + len(self._registrations)
                >= self._max_processes
            ):
                raise ProcessHostCapacityError("process host capacity is exhausted")
            reservation = _Reservation(self._next_reservation_id, owner)
            self._next_reservation_id += 1
            self._reservations[reservation.reservation_id] = reservation

        handle: _HostedProcess | None = None
        published = False
        primary_error: BaseException | None = None
        try:
            launch_request = request
            if containment_planner is not None:
                containment = await containment_planner(request)
                if not isinstance(containment, ProcessContainmentPlan):
                    raise TypeError(
                        "process containment planner must return ProcessContainmentPlan"
                    )
                reservation.attach_containment(containment)
                launch_request = containment.request
            transport = await self._spawner(
                launch_request,
                on_spawn=reservation.attach,
            )
            reservation.attach(transport)
            handle = _HostedProcess(
                transport,
                max_read_bytes=self._max_read_bytes,
                max_write_bytes=self._max_write_bytes,
                stderr_max_bytes=self._stderr_max_bytes,
                termination_grace_seconds=self._termination_grace_seconds,
                containment=reservation.containment,
                on_exit=self._release,
            )
            async with self._lock:
                if (
                    self._state != "open"
                    or self._reservations.get(reservation.reservation_id)
                    is not reservation
                ):
                    raise ProcessHostClosedError("process host closed during start")
                self._reservations.pop(reservation.reservation_id, None)
                self._registrations.add(handle)
                # The child can exit before publication. Its finalizer may have
                # attempted release before registration, so make publication
                # itself close that race without retaining a phantom quota.
                if handle._is_settled():
                    self._registrations.discard(handle)
                published = True
            return handle
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            if not published:
                rollback_task = asyncio.create_task(
                    self._rollback_start(reservation, handle),
                    name="harness-process-host-start-rollback",
                )
                try:
                    await _await_cleanup_before_propagating_cancellation(rollback_task)
                except BaseException as cleanup_error:
                    if primary_error is not None:
                        primary_error.add_note(
                            f"process start rollback also failed: {cleanup_error}"
                        )
                        raise primary_error from cleanup_error
                    raise

    async def close(self) -> None:
        async with self._lock:
            task = self._close_task
            if task is None:
                self._state = "closing"
                task = asyncio.create_task(
                    self._close_owned(),
                    name="harness-process-host-close",
                )
                self._close_task = task
        await _await_cleanup_before_propagating_cancellation(task)

    async def _close_owned(self) -> None:
        async with self._lock:
            reservations = tuple(self._reservations.values())
            reservation_tasks = tuple(reservation.owner for reservation in reservations)
        for task in reservation_tasks:
            if task is not asyncio.current_task():
                task.cancel()
        if reservation_tasks:
            await asyncio.gather(*reservation_tasks, return_exceptions=True)

        async with self._lock:
            registrations = tuple(self._registrations)
        close_errors = tuple(
            reservation.cleanup_error
            for reservation in reservations
            if reservation.cleanup_error is not None
        )
        if registrations:
            results = await asyncio.gather(
                *(registration.close() for registration in registrations),
                return_exceptions=True,
            )
            close_errors = (
                *close_errors,
                *(result for result in results if isinstance(result, BaseException)),
            )
        async with self._lock:
            self._state = "closed"
        if close_errors:
            raise ProcessHostError(
                "one or more hosted processes failed to close"
            ) from (close_errors[0])

    async def _release(self, handle: _HostedProcess) -> None:
        async with self._lock:
            self._registrations.discard(handle)

    async def _rollback_start(
        self,
        reservation: _Reservation,
        handle: _HostedProcess | None,
    ) -> None:
        try:
            async with self._lock:
                self._reservations.pop(reservation.reservation_id, None)
            if handle is not None:
                await handle.close()
            else:
                try:
                    if reservation.transport is not None:
                        await _close_unpublished_transport(
                            reservation.transport,
                            grace_seconds=self._termination_grace_seconds,
                        )
                finally:
                    if reservation.containment is not None:
                        await reservation.containment.close()
        except BaseException as exc:
            reservation.cleanup_error = exc
            raise


async def _close_unpublished_transport(
    transport: ProcessTransport,
    *,
    grace_seconds: float,
) -> None:
    primary_error: BaseException | None = None
    stream = transport.stdin
    if stream is not None:
        try:
            stream.close()
            with suppress(BrokenPipeError, ConnectionResetError):
                await stream.wait_closed()
        except BaseException as exc:
            primary_error = exc
    await terminate_local_process_tree(transport)
    try:
        try:
            await asyncio.wait_for(transport.wait(), grace_seconds)
        except TimeoutError:
            await kill_local_process_tree(transport)
            await transport.wait()
    except BaseException as exc:
        primary_error = _record_cleanup_error(
            primary_error,
            exc,
            context="unpublished process settlement also failed",
        )
    if primary_error is not None:
        raise primary_error


def _record_cleanup_error(
    primary: BaseException | None,
    error: BaseException,
    *,
    context: str,
) -> BaseException:
    if primary is None:
        return error
    if error is not primary:
        primary.add_note(f"{context}: {error}")
    return primary


async def _await_cleanup_before_propagating_cancellation(
    task: asyncio.Task[None],
) -> None:
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            await asyncio.shield(task)
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


__all__ = [
    "ProcessHost",
    "ProcessHostCapacityError",
    "ProcessHostClosedError",
    "ProcessHostError",
    "ProcessWriteLimitError",
]
