"""Optional child-side application owner; no CLI, Product selection or spawn.

The trusted child composition publishes this owner before run and retains it
through cleanup. Run waiters are not service-lifetime owners. A single retained
worker executes synchronous control IO without blocking the application loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from typing import Any, Literal, Protocol, TypeVar

from .contracts import ManagedHandoffPhaseV1
from .handoff import ManagedChildControlV1
from .lifecycle import ManagedServiceStateV1

_T = TypeVar("_T")


class ManagedChildError(RuntimeError):
    def __init__(self, code: str) -> None:
        if code not in {"closed", "startup_failed", "activation_failed", "cleanup_incomplete"}:
            raise ValueError("invalid child error")
        super().__init__("managed_child_" + code)


class ManagedChildApplicationPortV1(Protocol):
    """One already adopted application's complete, retryable lifecycle."""

    @property
    def cleanup_pending(self) -> bool: ...

    async def prepare(self, *, deadline: float | None = None) -> None: ...

    async def activate(self) -> None: ...

    def fence(self) -> None: ...

    async def close(self, *, retry_timeout: float | None = None) -> None: ...

    async def wait_closed(self) -> None: ...


class ManagedChildApplicationV1:
    """Keep application ownership after durable handoff and starter exit.

    close is explicit child-local stop authority, never implicit run cancellation
    or a client EOF. Cleanup failures retain phase tasks, the worker and the
    borrowed journal dependency. No success here proves process/scope exit.
    """

    def __init__(
        self, application: ManagedChildApplicationPortV1, control: ManagedChildControlV1,
        *, startup_timeout: float = 30.0, settlement_timeout: float = 30.0,
    ) -> None:
        for value in (startup_timeout, settlement_timeout):
            _budget(value)
        if type(control) is not ManagedChildControlV1 or any(
            not callable(getattr(application, name, None))
            for name in ("prepare", "activate", "fence", "close", "wait_closed")
        ):
            raise TypeError("invalid managed child owner")
        self._application, self._control = application, control
        self._startup_timeout, self._timeout = startup_timeout, settlement_timeout
        self._worker: ThreadPoolExecutor | None = None
        self._io_lock = asyncio.Lock()
        self._pending_io: Future[Any] | None = None
        self._observation_task: asyncio.Task[ManagedServiceStateV1 | None] | None = None
        self._stop_task: asyncio.Task[ManagedServiceStateV1 | None] | None = None
        self._stop_deadline: float | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._prepare_task: asyncio.Task[None] | None = None
        self._activate_task: asyncio.Task[None] | None = None
        self._wait_task: asyncio.Task[None] | None = None
        self._application_close: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._startup_deadline: float | None = None
        self._close_deadline: float | None = None
        self._application_settled = False
        self._committed = False
        self._closing = False
        self._settled = False
        self._failure: BaseException | None = None
        self._wakeup = asyncio.Event()

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    @property
    def accepting(self) -> bool:
        return (self._committed and not self._closing and self._activate_task is not None
                and self._activate_task.done() and not _failed(self._activate_task))

    async def run(self) -> None:
        """Join the retained service runner; cancelling this waiter is nonterminal."""
        if self._run_task is None:
            if self._closing:
                raise ManagedChildError("closed")
            self._startup_deadline = asyncio.get_running_loop().time() + self._startup_timeout
            self._run_task = _spawn(self._run_once())
        await asyncio.shield(self._run_task)

    async def _run_once(self) -> None:
        try:
            await self._drive()
        except BaseException as error:
            self._failure = error
            try:
                await self.close()
            except BaseException:
                error.add_note("managed_child_cleanup_incomplete")
            if isinstance(error, Exception) and not isinstance(error, ManagedChildError):
                raise ManagedChildError("activation_failed" if self._committed else "startup_failed") from None
            raise
        else:
            await self.close()

    async def _drive(self) -> None:
        assert self._startup_deadline is not None
        failure: str | None = None
        while not self._closing:
            if (not self.accepting and asyncio.get_running_loop().time() >= self._startup_deadline):
                failure = "startup_failed"
                break  # Application's own startup budget, not a starter timeout.
            state = await self._observe_running(
                "read" if self._committed else "poll",
                deadline=None if self.accepting else self._startup_deadline,
            )
            if self._closing:
                break
            if state is not None:
                if state.handoff.stop_requested or state.handoff.phase is ManagedHandoffPhaseV1.ABORTING:
                    break
                if self._prepare_task is None:
                    if state.handoff.phase is not ManagedHandoffPhaseV1.PROVISIONAL:
                        failure = "startup_failed"
                        break
                    self._prepare_task = _spawn(self._application.prepare(deadline=self._startup_deadline))
                if state.handoff.phase is ManagedHandoffPhaseV1.COMMITTED:
                    self._committed = True
            if self._prepare_task is not None and self._prepare_task.done():
                if _failed(self._prepare_task):
                    failure = "startup_failed"
                    break
                if not self._committed:
                    # No fresh commit effect may begin after the app deadline.
                    if asyncio.get_running_loop().time() >= self._startup_deadline:
                        failure = "startup_failed"
                        break
                    state = await self._observe_running("commit", deadline=self._startup_deadline)
                    if self._closing:
                        break
                    if state is not None:
                        if state.handoff.stop_requested or state.handoff.phase is ManagedHandoffPhaseV1.ABORTING:
                            break
                        self._committed = state.handoff.phase is ManagedHandoffPhaseV1.COMMITTED
                if self._committed and self._activate_task is None:
                    if asyncio.get_running_loop().time() >= self._startup_deadline:
                        failure = "startup_failed"
                        break
                    self._activate_task = _spawn(self._application.activate())
            if self._activate_task is not None and self._activate_task.done():
                if _failed(self._activate_task):
                    failure = "activation_failed"
                    break
                if self._wait_task is None:
                    self._wait_task = _spawn(self._application.wait_closed())
                if self._wait_task.done():
                    if _failed(self._wait_task):
                        failure = "activation_failed"
                    break
            self._wakeup.clear()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), 0.25 if self.accepting else 0.05)
        if failure is not None:
            raise ManagedChildError(failure)

    async def _observe_running(
        self, action: Literal["read", "poll", "commit"], *, deadline: float | None = None,
    ) -> ManagedServiceStateV1 | None:
        # Retain the observation independently. A blocked fsync cannot prevent
        # noticing application failure/deadline or explicit local stop.
        task = self._observation_task = _spawn(self._observe(action, deadline=deadline))
        while True:
            if self._closing:
                return None
            if (self._activate_task is not None and self._activate_task.done()
                    and not _failed(self._activate_task) and self._wait_task is None):
                self._wait_task = _spawn(self._application.wait_closed())
            if self._wait_task is not None and self._wait_task.done():
                return None  # Application stop must not wait for hung control IO.
            if any(phase is not None and _failed(phase) for phase in (self._prepare_task, self._activate_task)):
                raise ManagedChildError("activation_failed" if self._committed else "startup_failed")
            if (not self.accepting and self._startup_deadline is not None
                    and asyncio.get_running_loop().time() >= self._startup_deadline):
                raise ManagedChildError("startup_failed")
            if task.done():
                return await asyncio.shield(task)
            pending: set[asyncio.Task[Any]] = {task}
            pending.update(phase for phase in (self._prepare_task, self._activate_task, self._wait_task)
                           if phase is not None and not phase.done())
            await asyncio.wait(pending, timeout=0.01, return_when=asyncio.FIRST_COMPLETED)

    async def _observe(
        self, action: Literal["read", "poll", "commit", "stop", "cleanup"],
        *, deadline: float | None = None,
    ) -> ManagedServiceStateV1 | None:
        limit = asyncio.get_running_loop().time() + 2.0
        if deadline is not None:
            limit = min(limit, deadline)
        return await self._io(lambda: self._control.observe(action, limit))

    async def _io(self, operation: Callable[[], _T]) -> _T:
        async with self._io_lock:
            # Even event-loop shutdown cancellation cannot make the previous
            # native job disappear or admit a second queued job over it.
            prior = self._pending_io
            if prior is not None:
                with suppress(Exception):
                    await asyncio.shield(asyncio.wrap_future(prior))
                self._pending_io = None
            if self._worker is None:
                self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lmux-control")
            future = self._worker.submit(operation)
            self._pending_io = future
            try:
                return await asyncio.shield(asyncio.wrap_future(future))
            finally:
                # Public waiters never cancel this retained coroutine. Native IO
                # cannot be preempted; if shutdown cancels it, retain the future.
                if future.done():
                    self._pending_io = None

    async def close(self, *, retry_timeout: float | None = None) -> None:
        if retry_timeout is not None:
            _budget(retry_timeout)
        if self._settled:
            return
        self._closing = True
        self._application.fence()
        self._wakeup.set()
        if self._close_deadline is None:
            self._close_deadline = asyncio.get_running_loop().time() + self._timeout
        task = self._close_task
        if task is None or _failed(task):
            if retry_timeout is not None:
                self._close_deadline = asyncio.get_running_loop().time() + retry_timeout
            task = self._close_task = _spawn(self._close_once(retry_timeout))
        await _wait(task, self._close_deadline)

    async def _close_once(self, retry_timeout: float | None) -> None:
        assert self._close_deadline is not None
        deadline = self._close_deadline
        # This phase runs before waiting for the IO worker, even if its current
        # journal call is blocked. Local cleanup needs no successful DB write.
        if not self._application_settled:
            task = self._application_close
            if task is None or _failed(task) or (task.done() and self._application.cleanup_pending):
                if asyncio.get_running_loop().time() >= deadline:
                    raise ManagedChildError("cleanup_incomplete")
                task = self._application_close = _spawn(self._application.close(retry_timeout=retry_timeout))
            self._start_stop(deadline)
            await _wait(task, deadline)
            if self._application.cleanup_pending:
                raise ManagedChildError("cleanup_incomplete")
            for owned in (self._prepare_task, self._activate_task, self._wait_task):
                if owned is not None:
                    await _wait(owned, deadline, ignore_failure=True)
            self._application_settled = True
        self._start_stop(deadline)
        if self._observation_task is not None:
            await _wait(self._observation_task, deadline, ignore_failure=True)
        assert self._stop_task is not None
        await _wait(self._stop_task, deadline)
        state = self._stop_task.result()
        if (state is None and self._stop_deadline is not None and self._stop_deadline < deadline):
            # A retained request from an older, expired attempt just settled.
            # Use the explicitly granted retry budget only after that exact job
            # completes; never replace it or enqueue a second native operation.
            self._start_stop(deadline)
            await _wait(self._stop_task, deadline)
            state = self._stop_task.result()
        if state is None or not state.handoff.stop_requested:
            raise ManagedChildError("cleanup_incomplete")
        state = await self._observe("cleanup", deadline=deadline)
        if state is None or not state.evidence.application_cleanup_completed:
            raise ManagedChildError("cleanup_incomplete")
        if asyncio.get_running_loop().time() >= deadline:
            raise ManagedChildError("cleanup_incomplete")
        await self._io(self._control.close)
        assert self._worker is not None and self._pending_io is None
        # All jobs have finished; never join a native thread on the app loop.
        self._worker.shutdown(wait=False)
        self._settled = True

    def _start_stop(self, deadline: float) -> None:
        task = self._stop_task
        if task is not None and not _failed(task):
            if not task.done():
                return
            state = task.result()
            if state is not None and state.handoff.stop_requested:
                return
        if asyncio.get_running_loop().time() >= deadline:
            raise ManagedChildError("cleanup_incomplete")
        # Independent of successful application cleanup, but serialized behind
        # any exact in-flight native job by the same single-worker IO owner.
        self._stop_task = _spawn(self._observe("stop", deadline=deadline))
        self._stop_deadline = deadline


def _budget(value: float) -> None:
    if type(value) not in (int, float) or not 0 < value <= 30:
        raise ValueError("invalid managed child budget")


def _failed(task: asyncio.Task[Any]) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


async def _wait(task: asyncio.Task[Any], deadline: float, *, ignore_failure: bool = False) -> None:
    if not task.done():
        await asyncio.wait({task}, timeout=max(0, deadline - asyncio.get_running_loop().time()))
    if not task.done() or not ignore_failure and _failed(task):
        raise ManagedChildError("cleanup_incomplete")


def _spawn(work: Coroutine[object, object, _T]) -> asyncio.Task[_T]:
    published = asyncio.get_running_loop().create_future()

    async def invoke() -> _T:
        await published
        return await work

    def finished(task: asyncio.Task[_T]) -> None:
        work.close()
        if not task.cancelled():
            task.exception()

    invocation = invoke()
    try:
        task = asyncio.create_task(invocation)
    except BaseException:
        invocation.close()
        work.close()
        raise
    task.add_done_callback(finished)
    published.set_result(None)
    return task
