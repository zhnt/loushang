"""Private H1 process-lifetime owner.

H1 deliberately has no public composition entrypoint.  The owner is exercised
against a fake backend until H2 supplies separately proven platform adapters.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar, cast

from ._process_backend import (
    _ManagedProcessPreparation,
    _ProcessBackend,
    _ProcessInheritance,
    _ProcessTransport,
)
from .contracts import (
    HostingComponent,
    HostingLifecycleTransition,
    HostingObservation,
    HostingObservationSink,
    LaunchPreparationLease,
    LaunchPreparationPort,
    ProcessExit,
    ProcessLaunchRequest,
    ProcessLease,
    ProcessStderrMode,
    ProcessStderrTail,
    ProcessStdinMode,
    ProcessStdoutMode,
)
from .errors import HostingError, HostingFailureCategory

_T = TypeVar("_T")


class _Timeouts:
    """Private clock seam used by lifecycle tests and the future H2 adapters."""

    async def wait(self, operation: Awaitable[_T], seconds: float) -> _T:
        return await asyncio.wait_for(operation, seconds)


@dataclass(frozen=True, slots=True)
class _ProcessHostLimits:
    max_processes: int = 4
    max_read_bytes: int = 64 * 1024
    max_write_bytes: int = 1024 * 1024
    stderr_tail_bytes: int = 64 * 1024
    termination_grace_seconds: float = 1.0
    stderr_drain_seconds: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "max_processes",
            "max_read_bytes",
            "max_write_bytes",
            "stderr_tail_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("termination_grace_seconds", "stderr_drain_seconds"):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive finite number")


class _CleanupPhase(str, Enum):
    STDIN = "stdin"
    TERMINATE = "terminate"
    KILL = "kill"
    REAP = "reap"
    STDERR = "stderr"
    PROCESS_HANDLES = "process_handles"
    BACKEND = "backend"
    PREPARATION = "preparation"
    REGISTRATION = "registration"


@dataclass(frozen=True, slots=True)
class _CleanupFailure:
    phase: _CleanupPhase
    category: HostingFailureCategory
    cause: BaseException = field(repr=False, compare=False)


class _CleanupError(HostingError):
    """Private typed aggregate; arbitrary backend text never enters observations."""

    def __init__(self, failures: tuple[_CleanupFailure, ...]) -> None:
        if not failures:
            raise ValueError("cleanup failures must not be empty")
        self.failures = failures
        phases = ", ".join(failure.phase.value for failure in failures)
        super().__init__(
            HostingFailureCategory.CLEANUP_FAILED,
            f"hosting cleanup failed in {len(failures)} phase(s): {phases}",
        )


@dataclass(slots=True)
class _Reservation:
    reservation_id: int
    owner_id: str
    owner: asyncio.Task[object]
    settled: asyncio.Event
    session_id: str | None = None
    preparation: LaunchPreparationLease | None = None
    process: _ProcessTransport | None = None
    orphan_processes: list[_ProcessTransport] = field(default_factory=list)
    cleanup_error: _CleanupError | None = None

    def attach_preparation(self, preparation: LaunchPreparationLease) -> None:
        if self.preparation is not None and self.preparation is not preparation:
            raise RuntimeError("process reservation already owns preparation")
        self.preparation = preparation

    def attach_process(self, process: _ProcessTransport) -> None:
        if self.process is not None and self.process is not process:
            raise RuntimeError("process reservation already owns a process")
        self.process = process

    def attach_orphan_process(self, process: _ProcessTransport) -> None:
        if self.process is process or any(
            owned is process for owned in self.orphan_processes
        ):
            return
        self.orphan_processes.append(process)


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
        return ProcessStderrTail(bytes(self._content), self._truncated)


class _HostedProcess(ProcessLease):
    def __init__(
        self,
        *,
        lease_id: str,
        request: ProcessLaunchRequest,
        process: _ProcessTransport,
        preparation: LaunchPreparationLease,
        backend: _ProcessBackend,
        limits: _ProcessHostLimits,
        timeouts: _Timeouts,
        observe: Callable[
            [HostingLifecycleTransition, HostingFailureCategory | None], None
        ],
        on_finalized: Callable[["_HostedProcess"], Awaitable[None]],
    ) -> None:
        self._lease_id = lease_id
        self._request = request
        self._process = process
        self._preparation = preparation
        self._backend = backend
        self._limits = limits
        self._timeouts = timeouts
        self._observe = observe
        self._on_finalized = on_finalized
        self._stderr_tail = _BoundedByteTail(limits.stderr_tail_bytes)
        self._stdin_lock = asyncio.Lock()
        self._stdout_lock = asyncio.Lock()
        self._stderr_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._stdin_closed = False
        self._closing = False
        self._exit: asyncio.Future[ProcessExit] = (
            asyncio.get_running_loop().create_future()
        )
        self._termination_task: asyncio.Task[ProcessExit] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._tree_task: asyncio.Task[None] | None = None
        self._finalizer_task: asyncio.Task[None] | None = None
        self._finalization_error: _CleanupError | None = None
        self._finalizer_finished = False
        self._tree_settled = False
        self._process_handles_task: asyncio.Task[None] | None = None
        self._process_handles_closed = False
        self._preparation_task: asyncio.Task[None] | None = None
        self._preparation_closed = False
        self._registration_task: asyncio.Task[None] | None = None
        self._released = False

    @property
    def lease_id(self) -> str:
        return self._lease_id

    def begin(self) -> None:
        if self._finalizer_task is not None:
            raise RuntimeError("hosted process finalizer already started")
        if self._request.streams.stderr is ProcessStderrMode.CAPTURE_TAIL:
            self._stderr_task = asyncio.create_task(
                self._drain_stderr(),
                name=f"hosting-process-{self._lease_id}-stderr",
            )
        self._tree_task = asyncio.create_task(
            self._backend.wait_tree(self._process),
            name=f"hosting-process-{self._lease_id}-tree",
        )
        self._finalizer_task = asyncio.create_task(
            self._finalize(),
            name=f"hosting-process-{self._lease_id}-finalizer",
        )

    async def read_stdout(self, max_bytes: int) -> bytes:
        self._validate_read_bound(max_bytes)
        if self._request.streams.stdout is not ProcessStdoutMode.PIPE:
            return b""
        async with self._stdout_lock:
            return self._validate_read_result(
                await self._process.read_stdout(max_bytes), max_bytes
            )

    async def read_stderr(self, max_bytes: int) -> bytes:
        self._validate_read_bound(max_bytes)
        if self._request.streams.stderr is not ProcessStderrMode.PIPE:
            raise HostingError(
                HostingFailureCategory.PEER_CLOSED,
                "hosted process stderr is not available as a pipe",
            )
        async with self._stderr_lock:
            chunk = self._validate_read_result(
                await self._process.read_stderr(max_bytes), max_bytes
            )
        self._stderr_tail.append(chunk)
        return chunk

    async def write_stdin(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("hosted process stdin writes must be bytes")
        if len(data) > self._limits.max_write_bytes:
            raise HostingError(
                HostingFailureCategory.WRITE_BOUND_EXCEEDED,
                "hosted process stdin write exceeds its fixed bound",
            )
        async with self._stdin_lock:
            if (
                self._closing
                or self._exit.done()
                or self._stdin_closed
                or self._request.streams.stdin is not ProcessStdinMode.PIPE
            ):
                raise HostingError(
                    HostingFailureCategory.PEER_CLOSED,
                    "hosted process stdin is closed",
                )
            try:
                await self._process.write_stdin(data)
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise HostingError(
                    HostingFailureCategory.PEER_CLOSED,
                    "hosted process stdin is closed",
                ) from exc

    async def close_stdin(self) -> None:
        async with self._stdin_lock:
            if self._stdin_closed:
                return
            self._stdin_closed = True
            await self._process.close_stdin()

    async def wait(self) -> ProcessExit:
        return await asyncio.shield(self._exit)

    async def terminate(self) -> ProcessExit:
        async with self._lifecycle_lock:
            task = self._termination_task
            if task is None or _task_failed(task):
                self._closing = True
                task = asyncio.create_task(
                    self._terminate_owned(),
                    name=f"hosting-process-{self._lease_id}-terminate",
                )
                self._termination_task = task
        return await _await_owned(task)

    async def close(self) -> None:
        async with self._lifecycle_lock:
            task = self._close_task
            if task is not None and not task.done():
                pass
            elif self._released:
                return
            else:
                self._closing = True
                task = asyncio.create_task(
                    self._close_owned(),
                    name=f"hosting-process-{self._lease_id}-close",
                )
                self._close_task = task
        await _await_owned(task)

    def stderr_tail(self) -> ProcessStderrTail:
        return self._stderr_tail.snapshot()

    def _validate_read_bound(self, max_bytes: int) -> None:
        if (
            type(max_bytes) is not int
            or max_bytes < 1
            or max_bytes > self._limits.max_read_bytes
        ):
            raise HostingError(
                HostingFailureCategory.READ_BOUND_EXCEEDED,
                "hosted process read exceeds its fixed bound",
            )

    @staticmethod
    def _validate_read_result(chunk: object, max_bytes: int) -> bytes:
        if not isinstance(chunk, bytes) or len(chunk) > max_bytes:
            raise HostingError(
                HostingFailureCategory.READ_BOUND_EXCEEDED,
                "process backend violated the requested read bound",
            )
        return chunk

    async def _drain_stderr(self) -> None:
        while True:
            chunk = self._validate_read_result(
                await self._process.read_stderr(self._limits.max_read_bytes),
                self._limits.max_read_bytes,
            )
            if not chunk:
                return
            self._stderr_tail.append(chunk)

    async def _finalize(self) -> None:
        failures: list[_CleanupFailure] = []
        try:
            try:
                return_code = await self._process.wait()
                if type(return_code) is not int:
                    raise TypeError("process backend returned a non-integer exit code")
            except BaseException as exc:
                failures.append(
                    _failure(_CleanupPhase.REAP, HostingFailureCategory.TERMINATION_FAILED, exc)
                )
                if not self._exit.done():
                    self._exit.set_exception(
                        HostingError(
                            HostingFailureCategory.TERMINATION_FAILED,
                            "hosted process exit could not be observed",
                        )
                    )
            else:
                if not self._exit.done():
                    self._exit.set_result(ProcessExit(return_code))
                self._observe(HostingLifecycleTransition.EXITED, None)

            try:
                tree_exited = self._backend.tree_exited(self._process)
            except BaseException:
                # An unknown state is never treated as successful settlement.
                # _terminate_owned records the query failure while continuing
                # every reachable reclamation step.
                tree_exited = False
            if not tree_exited:
                try:
                    await self._ensure_termination()
                except _CleanupError as exc:
                    failures.extend(exc.failures)
                except BaseException as exc:
                    failures.append(
                        _failure(
                            _CleanupPhase.TERMINATE,
                            HostingFailureCategory.TERMINATION_FAILED,
                            exc,
                        )
                    )
            else:
                self._tree_settled = True
                await self._finish_tree_wait(failures)

            await self._finish_stderr(failures)
            await self._finish_process_handles(failures)
            if self._tree_settled:
                await self._finish_preparation(failures)
        finally:
            self._closing = True
            self._finalizer_finished = True
            if failures:
                self._finalization_error = _CleanupError(tuple(failures))
                self._observe(
                    HostingLifecycleTransition.FAILED,
                    HostingFailureCategory.CLEANUP_FAILED,
                )
            else:
                self._finalization_error = None
            registration_failures: list[_CleanupFailure] = []
            await self._finish_registration(registration_failures)
            if registration_failures:
                failures.extend(registration_failures)
                self._finalization_error = _CleanupError(tuple(failures))
                if len(failures) == len(registration_failures):
                    self._observe(
                        HostingLifecycleTransition.FAILED,
                        HostingFailureCategory.CLEANUP_FAILED,
                    )

    async def _finish_stderr(self, failures: list[_CleanupFailure]) -> None:
        task = self._stderr_task
        if task is None:
            return
        try:
            await self._timeouts.wait(
                asyncio.shield(task), self._limits.stderr_drain_seconds
            )
        except TimeoutError as exc:
            failures.append(
                _failure(
                    _CleanupPhase.STDERR,
                    HostingFailureCategory.CLEANUP_FAILED,
                    exc,
                )
            )
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except BaseException as exc:
            failures.append(
                _failure(
                    _CleanupPhase.STDERR,
                    HostingFailureCategory.CLEANUP_FAILED,
                    exc,
                )
            )

    async def _terminate_owned(self) -> ProcessExit:
        failures: list[_CleanupFailure] = []
        try:
            tree_exited = self._backend.tree_exited(self._process)
        except BaseException as exc:
            tree_exited = False
            failures.append(
                _failure(
                    _CleanupPhase.REAP,
                    HostingFailureCategory.TERMINATION_FAILED,
                    exc,
                )
            )
        if tree_exited:
            self._tree_settled = True
            settled_failures: list[_CleanupFailure] = []
            await self._finish_tree_wait(settled_failures)
            failures.extend(settled_failures)
            if failures:
                raise _CleanupError(tuple(failures)) from failures[0].cause
            return await asyncio.shield(self._exit)

        failure_count = len(failures)
        await _attempt(
            failures,
            _CleanupPhase.TERMINATE,
            HostingFailureCategory.TERMINATION_FAILED,
            self._backend.terminate_tree(self._process),
        )
        # Tree termination must not queue behind a blocked stdin writer.
        # Closing stdin is still attempted before the grace wait, but it can
        # now converge because the child-side reader is being reclaimed.
        if len(failures) == failure_count:
            await _attempt(
                failures,
                _CleanupPhase.STDIN,
                HostingFailureCategory.CLEANUP_FAILED,
                self.close_stdin(),
            )
        else:
            try:
                await asyncio.wait_for(
                    self.close_stdin(),
                    self._limits.termination_grace_seconds,
                )
            except BaseException as exc:
                failures.append(
                    _failure(
                        _CleanupPhase.STDIN,
                        HostingFailureCategory.CLEANUP_FAILED,
                        exc,
                    )
                )

        force_kill = False
        tree_task = await self._active_tree_task()
        try:
            await self._timeouts.wait(
                asyncio.shield(tree_task),
                self._limits.termination_grace_seconds,
            )
            self._tree_settled = True
        except TimeoutError:
            force_kill = True
        except BaseException as exc:
            force_kill = True
            failures.append(
                _failure(
                    _CleanupPhase.REAP,
                    HostingFailureCategory.TERMINATION_FAILED,
                    exc,
                )
            )

        if force_kill:
            await _attempt(
                failures,
                _CleanupPhase.KILL,
                HostingFailureCategory.TERMINATION_FAILED,
                self._backend.kill_tree(self._process),
            )
            await self._finish_forced_tree_wait(failures)

        if failures:
            raise _CleanupError(tuple(failures)) from failures[0].cause
        return await asyncio.shield(self._exit)

    async def _ensure_termination(self) -> ProcessExit:
        async with self._lifecycle_lock:
            task = self._termination_task
            if task is None or _task_failed(task):
                self._closing = True
                task = asyncio.create_task(
                    self._terminate_owned(),
                    name=f"hosting-process-{self._lease_id}-terminate",
                )
                self._termination_task = task
        return await asyncio.shield(task)

    async def _finish_tree_wait(
        self, failures: list[_CleanupFailure]
    ) -> None:
        try:
            await asyncio.shield(self._require_tree_task())
        except BaseException as exc:
            failures.append(
                _failure(
                    _CleanupPhase.REAP,
                    HostingFailureCategory.TERMINATION_FAILED,
                    exc,
                )
            )
        else:
            self._tree_settled = True

    async def _finish_forced_tree_wait(
        self, failures: list[_CleanupFailure]
    ) -> None:
        existing = self._require_tree_task()
        task = (
            existing
            if (
                not existing.done()
                or not existing.cancelled()
                and existing.exception() is None
            )
            else asyncio.create_task(
                self._backend.wait_tree(self._process),
                name=f"hosting-process-{self._lease_id}-forced-tree",
            )
        )
        if task is not existing:
            self._tree_task = task
        try:
            await self._timeouts.wait(
                asyncio.shield(task), self._limits.termination_grace_seconds
            )
        except BaseException as exc:
            failures.append(
                _failure(
                    _CleanupPhase.REAP,
                    HostingFailureCategory.TERMINATION_FAILED,
                    exc,
                )
            )
        else:
            self._tree_settled = True
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if task is not existing and not existing.done():
                existing.cancel()
                await asyncio.gather(existing, return_exceptions=True)

    def _require_tree_task(self) -> asyncio.Task[None]:
        if self._tree_task is None:
            raise RuntimeError("hosted process tree waiter was not started")
        return self._tree_task

    async def _active_tree_task(self) -> asyncio.Task[None]:
        async with self._lifecycle_lock:
            task = self._require_tree_task()
            if _task_failed(task):
                task = asyncio.create_task(
                    self._backend.wait_tree(self._process),
                    name=f"hosting-process-{self._lease_id}-tree-retry",
                )
                self._tree_task = task
            return task

    async def _close_owned(self) -> None:
        self._observe(HostingLifecycleTransition.CLEANING, None)
        failures: list[_CleanupFailure] = []
        finalizer_was_finished = self._finalizer_finished
        await self._reset_failed_cleanup_tasks()
        if finalizer_was_finished:
            # Root observation already ran, but a failed finalizer is not
            # proof that the complete tree settled.  Retry bounded tree
            # reclamation before releasing process/preparation owners.
            if not self._tree_settled:
                try:
                    await self.terminate()
                except _CleanupError as exc:
                    failures.extend(exc.failures)
                except BaseException as exc:
                    failures.append(
                        _failure(
                            _CleanupPhase.TERMINATE,
                            HostingFailureCategory.TERMINATION_FAILED,
                            exc,
                        )
                    )
            await self._finish_process_handles(failures)
            if self._tree_settled:
                await self._finish_preparation(failures)
            if not failures and self._tree_settled:
                self._finalization_error = None
            await self._finish_registration(failures)
            self._record_unsettled_tree(failures)
            if failures:
                raise _CleanupError(tuple(failures)) from failures[0].cause
            return

        termination_failed = False
        try:
            await self.terminate()
        except _CleanupError as exc:
            termination_failed = True
            failures.extend(exc.failures)
        except BaseException as exc:
            termination_failed = True
            failures.append(
                _failure(
                    _CleanupPhase.TERMINATE,
                    HostingFailureCategory.TERMINATION_FAILED,
                    exc,
                )
            )

        if termination_failed:
            # A platform termination failure must not leave the finalizer
            # waiting forever before it reaches the backend's kill-on-close
            # safety path. Backends make this operation idempotent, so the
            # finalizer can still run the normal phase afterwards.
            await self._finish_process_handles(failures)

            # A denied TERM/KILL may leave the root wait pending forever.  The
            # failed close attempt returns after the bounded termination and
            # last-resort handle phases, while this lease remains registered
            # as the exact owner for a later retry.
            if not self._finalizer_finished:
                raise _CleanupError(tuple(failures)) from failures[0].cause

        finalizer = self._finalizer_task
        if finalizer is None:
            failures.append(
                _failure(
                    _CleanupPhase.REGISTRATION,
                    HostingFailureCategory.CLEANUP_FAILED,
                    RuntimeError("hosted process finalizer was not started"),
                )
            )
        else:
            try:
                await asyncio.shield(finalizer)
            except BaseException as exc:
                failures.append(
                    _failure(
                        _CleanupPhase.REGISTRATION,
                        HostingFailureCategory.CLEANUP_FAILED,
                        exc,
                    )
                )
        if self._finalization_error is not None:
            failures.extend(self._finalization_error.failures)

        await self._finish_registration(failures)
        self._record_unsettled_tree(failures)
        if failures:
            raise _CleanupError(tuple(failures)) from failures[0].cause

    async def _finish_process_handles(
        self, failures: list[_CleanupFailure]
    ) -> None:
        async with self._lifecycle_lock:
            if self._process_handles_closed:
                return
            task = self._process_handles_task
            if task is None:
                task = asyncio.create_task(
                    self._backend.close_process_handles(self._process),
                    name=f"hosting-process-{self._lease_id}-handles",
                )
                self._process_handles_task = task
        try:
            await _await_owned(task)
        except BaseException as exc:
            failures.append(
                _failure(
                    _CleanupPhase.PROCESS_HANDLES,
                    HostingFailureCategory.CLEANUP_FAILED,
                    exc,
                )
            )
        else:
            async with self._lifecycle_lock:
                self._process_handles_closed = True
            if not self._tree_settled:
                try:
                    self._tree_settled = self._backend.tree_exited(self._process)
                except BaseException as exc:
                    failures.append(
                        _failure(
                            _CleanupPhase.REAP,
                            HostingFailureCategory.TERMINATION_FAILED,
                            exc,
                        )
                    )

    async def _finish_preparation(
        self, failures: list[_CleanupFailure]
    ) -> None:
        async with self._lifecycle_lock:
            if self._preparation_closed:
                return
            task = self._preparation_task
            if task is None:
                task = asyncio.create_task(
                    self._preparation.close(),
                    name=f"hosting-process-{self._lease_id}-preparation",
                )
                self._preparation_task = task
        try:
            await _await_owned(task)
        except BaseException as exc:
            failures.append(
                _failure(
                    _CleanupPhase.PREPARATION,
                    HostingFailureCategory.CLEANUP_FAILED,
                    exc,
                )
            )
        else:
            async with self._lifecycle_lock:
                self._preparation_closed = True

    async def _finish_registration(
        self, failures: list[_CleanupFailure]
    ) -> None:
        async with self._lifecycle_lock:
            if self._released:
                return
            if (
                not self._finalizer_finished
                or not self._tree_settled
                or not self._process_handles_closed
                or not self._preparation_closed
            ):
                return
            task = self._registration_task
            if task is None:
                task = asyncio.create_task(
                    self._release_registration(),
                    name=f"hosting-process-{self._lease_id}-registration",
                )
                self._registration_task = task
        try:
            await _await_owned(task)
        except BaseException as exc:
            failures.append(
                _failure(
                    _CleanupPhase.REGISTRATION,
                    HostingFailureCategory.CLEANUP_FAILED,
                    exc,
                )
            )
        else:
            async with self._lifecycle_lock:
                if not self._released:
                    self._released = True
                    self._observe(HostingLifecycleTransition.CLOSED, None)

    async def _release_registration(self) -> None:
        await self._on_finalized(self)

    def _record_unsettled_tree(
        self, failures: list[_CleanupFailure]
    ) -> None:
        if self._released or self._tree_settled or failures:
            return
        failures.append(
            _failure(
                _CleanupPhase.REAP,
                HostingFailureCategory.TERMINATION_FAILED,
                TimeoutError("hosted process tree remains unsettled"),
            )
        )

    async def _reset_failed_cleanup_tasks(self) -> None:
        async with self._lifecycle_lock:
            for attribute in (
                "_process_handles_task",
                "_preparation_task",
                "_registration_task",
            ):
                task = cast(asyncio.Task[object] | None, getattr(self, attribute))
                if task is not None and _task_failed(task):
                    setattr(self, attribute, None)


class _ProcessHost:
    """Bounded owner for pending and published local process lifetimes."""

    def __init__(
        self,
        backend: _ProcessBackend,
        *,
        limits: _ProcessHostLimits | None = None,
        observation_sink: HostingObservationSink | None = None,
        timeouts: _Timeouts | None = None,
    ) -> None:
        backend_id = backend.backend_id
        if (
            not isinstance(backend_id, str)
            or not backend_id
            or len(backend_id) > 128
            or "\0" in backend_id
        ):
            raise ValueError("backend_id must be 1-128 characters")
        self._backend = backend
        self._backend_id = backend_id
        self._limits = limits or _ProcessHostLimits()
        self._timeouts = timeouts or _Timeouts()
        self._observation_sink = observation_sink
        self._lock = asyncio.Lock()
        self._state = "open"
        self._next_id = 1
        self._reservations: dict[int, _Reservation] = {}
        self._leases: set[_HostedProcess] = set()
        self._close_task: asyncio.Task[None] | None = None

    async def start(
        self,
        request: ProcessLaunchRequest,
        preparation: LaunchPreparationPort,
    ) -> ProcessLease:
        return await self._start_with_inheritance(
            request,
            preparation,
            inheritance=None,
            session_id=None,
        )

    def _has_cleanup_debt(self, session_id: str) -> bool:
        return any(
            reservation.session_id == session_id
            and reservation.cleanup_error is not None
            for reservation in self._reservations.values()
        )

    async def _start_with_inheritance(
        self,
        request: ProcessLaunchRequest,
        preparation: LaunchPreparationPort,
        *,
        inheritance: _ProcessInheritance | None,
        session_id: str | None,
    ) -> ProcessLease:
        if not isinstance(request, ProcessLaunchRequest):
            raise TypeError("process host requires ProcessLaunchRequest")
        owner = asyncio.current_task()
        if owner is None:
            raise RuntimeError("process start requires an asyncio task")

        async with self._lock:
            if self._state != "open":
                raise HostingError(
                    HostingFailureCategory.HOST_CLOSED,
                    "process host is closing",
                )
            if len(self._reservations) + len(self._leases) >= self._limits.max_processes:
                raise HostingError(
                    HostingFailureCategory.CAPACITY_EXHAUSTED,
                    "process host capacity is exhausted",
                )
            reservation_id = self._next_id
            self._next_id += 1
            owner_id = f"process-{reservation_id}"
            reservation = _Reservation(
                reservation_id,
                owner_id,
                owner,
                asyncio.Event(),
                session_id,
            )
            self._reservations[reservation_id] = reservation

        self._emit(
            owner_id,
            HostingLifecycleTransition.CAPACITY_RESERVED,
            session_id=session_id,
        )
        phase = "preparation"
        published = False
        try:
            self._emit(
                owner_id,
                HostingLifecycleTransition.PREPARING,
                session_id=session_id,
            )
            prepared = await preparation.prepare(request)
            if not isinstance(prepared, LaunchPreparationLease):
                raise TypeError("preparation port returned an invalid lease")
            reservation.attach_preparation(prepared)
            prepared_request = prepared.request
            if not isinstance(prepared_request, ProcessLaunchRequest):
                raise TypeError("preparation lease returned an invalid request")
            await prepared.verify_current()

            phase = "spawn"
            self._emit(
                owner_id,
                HostingLifecycleTransition.SPAWNING,
                session_id=session_id,
            )
            if isinstance(prepared, _ManagedProcessPreparation):
                process = await prepared.spawn_prepared(
                    self._backend,
                    prepared_request,
                    on_spawn=reservation.attach_process,
                    on_orphan_spawn=reservation.attach_orphan_process,
                    inheritance=inheritance,
                )
            else:
                process = await self._backend.spawn(
                    prepared_request,
                    on_spawn=reservation.attach_process,
                    inheritance=inheritance,
                )
            if reservation.process is None:
                # Salvage the returned object so a broken backend cannot turn
                # its own missing callback into an unowned process leak.
                reservation.attach_process(process)
                raise RuntimeError("process backend returned before owner attachment")
            reservation.attach_process(process)
            if process.return_code is not None:
                raise HostingError(
                    HostingFailureCategory.CHILD_EXITED_EARLY,
                    "child process exited before lease publication",
                )

            def observe(
                transition: HostingLifecycleTransition,
                failure: HostingFailureCategory | None = None,
            ) -> None:
                self._emit(
                    owner_id,
                    transition,
                    failure,
                    session_id=session_id,
                )

            lease = _HostedProcess(
                lease_id=owner_id,
                request=prepared_request,
                process=process,
                preparation=prepared,
                backend=self._backend,
                limits=self._limits,
                timeouts=self._timeouts,
                observe=observe,
                on_finalized=self._release,
            )
            async with self._lock:
                if (
                    self._state != "open"
                    or self._reservations.get(reservation_id) is not reservation
                ):
                    raise HostingError(
                        HostingFailureCategory.HOST_CLOSED,
                        "process host closed during start",
                    )
                self._reservations.pop(reservation_id)
                self._leases.add(lease)
                lease.begin()
                published = True
            self._emit(
                owner_id,
                HostingLifecycleTransition.PUBLISHED,
                session_id=session_id,
            )
            return lease
        except BaseException as caught:
            primary = _start_failure(caught, phase)
            if isinstance(primary, HostingError):
                self._emit(
                    owner_id,
                    HostingLifecycleTransition.FAILED,
                    primary.category,
                    session_id=session_id,
                )
            rollback = asyncio.create_task(
                self._rollback(reservation),
                name=f"hosting-process-{owner_id}-rollback",
            )
            try:
                await _await_owned(rollback)
            except BaseException as cleanup_error:
                if isinstance(cleanup_error, asyncio.CancelledError):
                    if cleanup_error.__cause__ is not None:
                        cleanup_error.add_note(
                            "hosting start rollback also reported a cleanup failure"
                        )
                    raise cleanup_error from primary
                if isinstance(primary, asyncio.CancelledError):
                    raise primary from cleanup_error
                if isinstance(primary, BaseException):
                    primary.add_note(f"hosting start rollback also failed: {cleanup_error}")
                    raise primary from cleanup_error
                raise
            if primary is caught:
                raise
            raise primary from caught
        finally:
            if not published:
                # _rollback is the single remover. This assertion-like fallback
                # handles only an impossible task-construction failure.
                async with self._lock:
                    if reservation.cleanup_error is None:
                        self._reservations.pop(reservation_id, None)
                reservation.settled.set()

    async def close(self) -> None:
        caller = asyncio.current_task()
        async with self._lock:
            task = self._close_task
            if task is not None and not task.done():
                pass
            elif self._state == "closed":
                return
            else:
                if any(
                    reservation.owner is caller
                    and not reservation.settled.is_set()
                    for reservation in self._reservations.values()
                ):
                    raise RuntimeError(
                        "process host cannot close from its active start transaction"
                    )
                self._state = "closing"
                task = asyncio.create_task(
                    self._close_owned(), name="hosting-process-host-close"
                )
                self._close_task = task
        await _await_owned(task)

    async def _rollback(self, reservation: _Reservation) -> None:
        failures: list[_CleanupFailure] = []
        self._emit(
            reservation.owner_id,
            HostingLifecycleTransition.CLEANING,
            session_id=reservation.session_id,
        )
        try:
            remaining_orphans: list[_ProcessTransport] = []
            for orphan in reservation.orphan_processes:
                failure_count = len(failures)
                await _reclaim_unpublished(
                    self._backend,
                    orphan,
                    self._limits,
                    self._timeouts,
                    failures,
                )
                if len(failures) != failure_count:
                    remaining_orphans.append(orphan)
            reservation.orphan_processes = remaining_orphans
            if reservation.process is not None:
                failure_count = len(failures)
                await _reclaim_unpublished(
                    self._backend,
                    reservation.process,
                    self._limits,
                    self._timeouts,
                    failures,
                )
                if len(failures) == failure_count:
                    reservation.process = None
            if reservation.preparation is not None:
                failure_count = len(failures)
                await _attempt(
                    failures,
                    _CleanupPhase.PREPARATION,
                    HostingFailureCategory.CLEANUP_FAILED,
                    reservation.preparation.close(),
                )
                if len(failures) == failure_count:
                    reservation.preparation = None
        finally:
            if failures:
                reservation.cleanup_error = _CleanupError(tuple(failures))
                async with self._lock:
                    if self._state == "open":
                        self._state = "faulted"
                self._emit(
                    reservation.owner_id,
                    HostingLifecycleTransition.FAILED,
                    HostingFailureCategory.CLEANUP_FAILED,
                    session_id=reservation.session_id,
                )
            else:
                reservation.cleanup_error = None
                async with self._lock:
                    self._reservations.pop(reservation.reservation_id, None)
                self._emit(
                    reservation.owner_id,
                    HostingLifecycleTransition.CLOSED,
                    session_id=reservation.session_id,
                )
        if reservation.cleanup_error is not None:
            raise reservation.cleanup_error from reservation.cleanup_error.failures[0].cause

    async def _release(self, lease: _HostedProcess) -> None:
        async with self._lock:
            self._leases.discard(lease)

    async def _close_owned(self) -> None:
        async with self._lock:
            reservations = tuple(self._reservations.values())
        for reservation in reservations:
            if (
                not reservation.settled.is_set()
                and reservation.owner is not asyncio.current_task()
            ):
                reservation.owner.cancel()
        if reservations:
            await asyncio.gather(
                *(reservation.settled.wait() for reservation in reservations)
            )

        failures: list[_CleanupFailure] = []
        for reservation in reservations:
            if reservation.cleanup_error is not None:
                try:
                    await self._rollback(reservation)
                except _CleanupError as exc:
                    failures.extend(exc.failures)
                except BaseException as exc:
                    failures.append(
                        _failure(
                            _CleanupPhase.REGISTRATION,
                            HostingFailureCategory.CLEANUP_FAILED,
                            exc,
                        )
                    )

        async with self._lock:
            leases = tuple(self._leases)
        if leases:
            results = await asyncio.gather(
                *(lease.close() for lease in leases), return_exceptions=True
            )
            for result in results:
                if isinstance(result, _CleanupError):
                    failures.extend(result.failures)
                elif isinstance(result, BaseException):
                    failures.append(
                        _failure(
                            _CleanupPhase.REGISTRATION,
                            HostingFailureCategory.CLEANUP_FAILED,
                            result,
                        )
                    )
        async with self._lock:
            has_cleanup_debt = bool(self._reservations or self._leases)
        if has_cleanup_debt:
            if not failures:
                failures.append(
                    _failure(
                        _CleanupPhase.REGISTRATION,
                        HostingFailureCategory.CLEANUP_FAILED,
                        RuntimeError("process host still owns cleanup debt"),
                    )
                )
            async with self._lock:
                self._state = "faulted"
        else:
            failure_count = len(failures)
            await _attempt(
                failures,
                _CleanupPhase.BACKEND,
                HostingFailureCategory.CLEANUP_FAILED,
                self._backend.close_backend(),
            )
            async with self._lock:
                self._state = (
                    "closed" if len(failures) == failure_count else "faulted"
                )
        if failures:
            raise _CleanupError(tuple(failures)) from failures[0].cause

    def _emit(
        self,
        owner_id: str,
        transition: HostingLifecycleTransition,
        failure: HostingFailureCategory | None = None,
        *,
        session_id: str | None = None,
    ) -> None:
        sink = self._observation_sink
        if sink is None:
            return
        observation = HostingObservation(
            component=HostingComponent.PROCESS,
            transition=transition,
            owner_id=owner_id,
            session_id=session_id,
            backend_id=self._backend_id,
            failure=failure,
        )
        try:
            sink.observe(observation)
        except BaseException:
            # Observability is explicitly non-owning and cannot veto lifecycle.
            return


async def _reclaim_unpublished(
    backend: _ProcessBackend,
    process: _ProcessTransport,
    limits: _ProcessHostLimits,
    timeouts: _Timeouts,
    failures: list[_CleanupFailure],
) -> None:
    await _attempt(
        failures,
        _CleanupPhase.STDIN,
        HostingFailureCategory.CLEANUP_FAILED,
        process.close_stdin(),
    )
    try:
        tree_exited = backend.tree_exited(process)
    except BaseException as exc:
        tree_exited = False
        failures.append(
            _failure(
                _CleanupPhase.REAP,
                HostingFailureCategory.TERMINATION_FAILED,
                exc,
            )
        )
    if not tree_exited:
        await _attempt(
            failures,
            _CleanupPhase.TERMINATE,
            HostingFailureCategory.TERMINATION_FAILED,
            backend.terminate_tree(process),
        )
        try:
            await timeouts.wait(
                backend.wait_tree(process), limits.termination_grace_seconds
            )
            tree_exited = True
        except TimeoutError:
            pass
        except BaseException as exc:
            failures.append(
                _failure(
                    _CleanupPhase.REAP,
                    HostingFailureCategory.TERMINATION_FAILED,
                    exc,
                )
            )
    if not tree_exited:
        await _attempt(
            failures,
            _CleanupPhase.KILL,
            HostingFailureCategory.TERMINATION_FAILED,
            backend.kill_tree(process),
        )
        try:
            await timeouts.wait(
                backend.wait_tree(process), limits.termination_grace_seconds
            )
        except BaseException as exc:
            failures.append(
                _failure(
                    _CleanupPhase.REAP,
                    HostingFailureCategory.TERMINATION_FAILED,
                    exc,
                )
            )
    await _attempt(
        failures,
        _CleanupPhase.REAP,
        HostingFailureCategory.TERMINATION_FAILED,
        process.wait(),
    )
    await _attempt(
        failures,
        _CleanupPhase.PROCESS_HANDLES,
        HostingFailureCategory.CLEANUP_FAILED,
        backend.close_process_handles(process),
    )


async def _attempt(
    failures: list[_CleanupFailure],
    phase: _CleanupPhase,
    category: HostingFailureCategory,
    operation: Awaitable[object],
) -> None:
    try:
        await operation
    except BaseException as exc:
        failures.append(_failure(phase, category, exc))


def _failure(
    phase: _CleanupPhase,
    category: HostingFailureCategory,
    cause: BaseException,
) -> _CleanupFailure:
    return _CleanupFailure(phase=phase, category=category, cause=cause)


def _start_failure(caught: BaseException, phase: str) -> BaseException:
    if isinstance(caught, (asyncio.CancelledError, HostingError)):
        return caught
    if not isinstance(caught, Exception):
        return caught
    category = (
        HostingFailureCategory.PREPARATION_FAILED
        if phase == "preparation"
        else HostingFailureCategory.SPAWN_FAILED
    )
    return HostingError(category, f"hosting process {phase} failed")


async def _await_owned(task: asyncio.Task[_T]) -> _T:
    """Shield one owner task and delay repeated caller cancellation until settled."""

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


def _task_failed(task: asyncio.Task[object]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


__all__: list[str] = []
