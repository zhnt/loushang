from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harness.events.session import RetryAttempt, RetryOutcome

C = TypeVar("C")


@dataclass(frozen=True)
class RetryPolicy:
    enabled: bool
    max_attempts: int
    base_delay_ms: int
    backoff_factor: float = 2.0


Delay = Callable[[int, C], Awaitable[None]]
Cancel = Callable[[C], None]
RetryStarted = Callable[[RetryAttempt], Awaitable[None]]
RetryFinished = Callable[[RetryOutcome], Awaitable[None]]
AsyncAction = Callable[[], Awaitable[None]]


class RetryCoordinator(Generic[C]):
    """Own retry attempt, backoff, cancellation, and waiter lifecycle."""

    def __init__(
        self,
        *,
        create_cancel_handle: Callable[[], C],
        cancel: Cancel[C],
        delay: Delay[C],
        on_started: RetryStarted,
        on_finished: RetryFinished,
    ) -> None:
        self._create_cancel_handle = create_cancel_handle
        self._cancel = cancel
        self._delay = delay
        self._on_started = on_started
        self._on_finished = on_finished
        self._attempt = 0
        self._future: asyncio.Future[None] | object | None = None
        self._cancel_handle: C | None = None
        self._delay_active = False
        self._continuation_task: asyncio.Task[None] | None = None

    @property
    def attempt(self) -> int:
        return self._attempt

    @attempt.setter
    def attempt(self, value: int) -> None:
        self._attempt = value

    @property
    def future(self) -> asyncio.Future[None] | object | None:
        return self._future

    @future.setter
    def future(self, value: asyncio.Future[None] | object | None) -> None:
        self._future = value

    @property
    def cancel_handle(self) -> C | None:
        return self._cancel_handle

    @cancel_handle.setter
    def cancel_handle(self, value: C | None) -> None:
        self._cancel_handle = value

    @property
    def is_retrying(self) -> bool:
        return self._future is not None

    def ensure_waiter(self) -> asyncio.Future[None]:
        if not isinstance(self._future, asyncio.Future):
            self._future = asyncio.get_running_loop().create_future()
        return self._future

    def abort(self) -> None:
        if self._cancel_handle is not None:
            self._cancel(self._cancel_handle)

    async def wait(self) -> None:
        future = self._future
        if future is None:
            return
        if isinstance(future, asyncio.Future):
            await future

    async def finish(self, outcome: RetryOutcome) -> None:
        try:
            await self._on_finished(outcome)
        finally:
            self._resolve_and_reset()

    async def retry(
        self,
        error: str,
        *,
        policy: RetryPolicy,
        before_retry: Callable[[], None] | None = None,
    ) -> bool:
        if not policy.enabled:
            if self._future is not None:
                await self.finish(
                    RetryOutcome(success=False, attempt=self._attempt, error=error)
                )
            return False
        if self._delay_active:
            raise RuntimeError("Retry delay already in progress")

        self._cancel_pending_continuation()

        self.ensure_waiter()
        self._attempt += 1
        if self._attempt > max(0, policy.max_attempts):
            await self.finish(
                RetryOutcome(
                    success=False,
                    attempt=self._attempt - 1,
                    error=error,
                )
            )
            return False

        delay_ms = _backoff_delay(policy, self._attempt)
        attempt = RetryAttempt(
            attempt=self._attempt,
            max_attempts=policy.max_attempts,
            delay_ms=delay_ms,
            error=error,
        )
        try:
            await self._on_started(attempt)
            if before_retry is not None:
                before_retry()

            cancel_handle = self._create_cancel_handle()
            self._cancel_handle = cancel_handle
            self._delay_active = True
            await self._delay(delay_ms, cancel_handle)
        except asyncio.CancelledError:
            await self.finish(
                RetryOutcome(
                    success=False,
                    attempt=self._attempt,
                    cancelled=True,
                )
            )
            return False
        except BaseException:
            self._resolve_and_reset()
            raise
        finally:
            self._delay_active = False

        return True

    def continue_retry(self, continue_run: AsyncAction) -> asyncio.Task[None]:
        """Start the caller-owned continuation for the active retry attempt."""

        if self._future is None:
            raise RuntimeError("Retry continuation requires an active retry")
        self._cancel_pending_continuation()
        attempt = self._attempt
        task = asyncio.create_task(self._run_continuation(attempt, continue_run))
        self._continuation_task = task
        return task

    async def _run_continuation(
        self,
        attempt: int,
        continue_run: AsyncAction,
    ) -> None:
        try:
            await continue_run()
        except asyncio.CancelledError:
            # A later user action or retry attempt may invalidate this
            # deferred continuation. Its cancellation is intentional and
            # must not become an unhandled background-task exception.
            return
        except Exception as error:
            if not self._is_current_attempt(attempt):
                return
            try:
                await self.finish(
                    RetryOutcome(
                        success=False,
                        attempt=attempt,
                        error=str(error),
                    )
                )
            except BaseException:
                # This task has no caller to receive an exception. Preserve
                # the retry state invariant even if the failure event sink
                # itself fails.
                self._resolve_and_reset()

    def _is_current_attempt(self, attempt: int) -> bool:
        return self._future is not None and self._attempt == attempt

    def _cancel_pending_continuation(self) -> None:
        task = self._continuation_task
        if task is None or task.done() or task is asyncio.current_task():
            return
        self._continuation_task = None
        task.cancel()

    def _resolve_and_reset(self) -> None:
        continuation_task = self._continuation_task
        self._continuation_task = None
        if (
            continuation_task is not None
            and continuation_task is not asyncio.current_task()
            and not continuation_task.done()
        ):
            continuation_task.cancel()

        future = self._future
        if isinstance(future, asyncio.Future) and not future.done():
            future.set_result(None)
        self._future = None
        self._cancel_handle = None
        self._attempt = 0
        self._delay_active = False


def _backoff_delay(policy: RetryPolicy, attempt: int) -> int:
    delay = max(0, policy.base_delay_ms) * policy.backoff_factor ** max(0, attempt - 1)
    return max(0, int(delay))


__all__ = [
    "RetryCoordinator",
    "RetryPolicy",
]
