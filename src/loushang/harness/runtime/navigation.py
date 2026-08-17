from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

P = TypeVar("P")
R = TypeVar("R")
A = TypeVar("A")


@dataclass
class CancellationSignal:
    """Small neutral cancellation signal for Harness-owned operations."""

    aborted: bool = False


class CancellationController:
    """Mutable owner for one neutral cancellation signal."""

    def __init__(self) -> None:
        self._signal = CancellationSignal()

    @property
    def signal(self) -> CancellationSignal:
        return self._signal

    def abort(self) -> None:
        self._signal.aborted = True

NavigationCallback = Callable[[P], Awaitable[None] | None]
NavigationCommit = Callable[[P, A], Awaitable[R] | R]
NavigationSuccessCallback = Callable[[P, R], Awaitable[None] | None]


@dataclass(frozen=True)
class NavigationFailure(Generic[P]):
    plan: P
    error: Exception


NavigationFailureCallback = Callable[[NavigationFailure[P]], Awaitable[None] | None]


class NavigationTransactionCoordinator(Generic[A]):
    """Own the lifecycle and abort scope of one product navigation commit."""

    def __init__(
        self,
        *,
        create_abort_scope: Callable[[], A],
        abort: Callable[[A], None],
    ) -> None:
        self._create_abort_scope = create_abort_scope
        self._abort = abort
        self._active_scope: A | None = None
        self._active_task: asyncio.Task[object] | None = None

    @property
    def is_active(self) -> bool:
        return self._active_scope is not None

    def owns_current_task(self) -> bool:
        task = asyncio.current_task()
        return task is not None and self._active_task is task

    def abort(self) -> bool:
        scope = self._active_scope
        if scope is None:
            return False
        self._abort(scope)
        return True

    async def wait(self) -> None:
        """Join the active navigation without consuming its result."""

        task = self._active_task
        if task is None or task.done():
            return
        if task is asyncio.current_task():
            raise RuntimeError("cannot wait for navigation from its active task")
        await asyncio.gather(task, return_exceptions=True)

    async def run(
        self,
        plan: P,
        *,
        commit: NavigationCommit[P, A, R],
        before_commit: NavigationCallback[P] | None = None,
        after_commit: NavigationSuccessCallback[P, R] | None = None,
        on_failure: NavigationFailureCallback[P] | None = None,
    ) -> R:
        if self._active_scope is not None:
            raise RuntimeError("A navigation transaction is already active.")
        scope = self._create_abort_scope()
        task = asyncio.current_task()
        self._active_scope = scope
        self._active_task = task
        try:
            if before_commit is not None:
                await _maybe_await(before_commit(plan))
            result = await _maybe_await(commit(plan, scope))
            if after_commit is not None:
                await _maybe_await(after_commit(plan, result))
            return result
        except Exception as exc:
            if on_failure is not None:
                await _maybe_await(on_failure(NavigationFailure(plan=plan, error=exc)))
            raise
        finally:
            if self._active_task is task:
                self._active_task = None
                self._active_scope = None


async def _maybe_await(value: Awaitable[R] | R) -> R:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "CancellationController",
    "CancellationSignal",
    "NavigationFailure",
    "NavigationTransactionCoordinator",
]
