from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Generic, TypeVar

S = TypeVar("S")
SessionCallback = Callable[[S], Awaitable[None] | None]
LifecycleCallback = Callable[[], Awaitable[None] | None]


class SessionTransitionHost(Generic[S]):
    """Serialize replacement and own the active product session slot."""

    def __init__(
        self,
        current: S | None = None,
        *,
        dispose: SessionCallback[S],
        rebind: SessionCallback[S] | None = None,
        before_invalidate: LifecycleCallback | None = None,
    ) -> None:
        self._current = current
        self._dispose = dispose
        self._rebind = rebind
        self._before_invalidate = before_invalidate
        self._before_invalidate_observers: list[LifecycleCallback] = []
        self._after_invalidate_observers: list[LifecycleCallback] = []
        self._pending_retirements: list[S] = []
        self._notifying_after_invalidate = False
        self._lock = asyncio.Lock()
        self._lock_owner: asyncio.Task[object] | None = None
        self._lock_depth = 0

    @property
    def current(self) -> S | None:
        return self._current

    @property
    def pending_retirements(self) -> tuple[S, ...]:
        return tuple(self._pending_retirements)

    def set_rebind(self, callback: SessionCallback[S] | None) -> None:
        self._rebind = callback

    def set_before_invalidate(self, callback: LifecycleCallback | None) -> None:
        self._before_invalidate = callback

    def subscribe_before_invalidate(
        self,
        callback: LifecycleCallback,
    ) -> Callable[[], None]:
        def observer() -> Awaitable[None] | None:
            return callback()

        self._before_invalidate_observers.append(observer)
        active = True

        def unsubscribe() -> None:
            nonlocal active
            if not active:
                return
            active = False
            self._before_invalidate_observers.remove(observer)

        return unsubscribe

    def subscribe_after_invalidate(
        self,
        callback: LifecycleCallback,
    ) -> Callable[[], None]:
        def observer() -> Awaitable[None] | None:
            return callback()

        self._after_invalidate_observers.append(observer)
        active = True

        def unsubscribe() -> None:
            nonlocal active
            if not active:
                return
            active = False
            self._after_invalidate_observers.remove(observer)

        return unsubscribe

    @asynccontextmanager
    async def transition(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is not None and self._lock_owner is task:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return

        await self._lock.acquire()
        self._lock_owner = task
        self._lock_depth = 1
        try:
            yield
        finally:
            self._lock_depth -= 1
            if self._lock_depth == 0:
                self._lock_owner = None
                self._lock.release()

    async def replace(
        self,
        next_session: S,
        *,
        prepare: SessionCallback[S] | None = None,
        before_release: SessionCallback[S] | None = None,
        activate: SessionCallback[S] | None = None,
    ) -> S:
        self._reject_reentrant_after_invalidate_transition()
        async with self.transition():
            await self._retry_pending_retirements()
            if prepare is not None:
                await _invoke_session_callback(prepare, next_session)

            previous = self._current
            if previous is not None and previous is not next_session:
                await self._prepare_release(
                    previous,
                    before_release=before_release,
                )
                self._current = None
                try:
                    await self._dispose_or_retain(previous)
                finally:
                    await self._notify_after_invalidate()

            self._current = next_session
            if activate is not None:
                await _invoke_session_callback(activate, next_session)
            if self._rebind is not None:
                await _invoke_session_callback(self._rebind, next_session)
            return next_session

    async def dispose_current(
        self,
        *,
        before_release: SessionCallback[S] | None = None,
    ) -> None:
        self._reject_reentrant_after_invalidate_transition()
        async with self.transition():
            await self._retry_pending_retirements()
            current = self._current
            if current is None:
                return
            await self._prepare_release(current, before_release=before_release)
            self._current = None
            try:
                await self._dispose_or_retain(current)
            finally:
                await self._notify_after_invalidate()

    async def _dispose_or_retain(self, session: S) -> None:
        try:
            await _invoke_session_callback(self._dispose, session)
        except BaseException:
            if not any(item is session for item in self._pending_retirements):
                self._pending_retirements.append(session)
            raise

    async def _retry_pending_retirements(self) -> None:
        if not self._pending_retirements:
            return
        pending = tuple(self._pending_retirements)
        remaining: list[S] = []
        errors: list[BaseException] = []
        for session in pending:
            try:
                await _invoke_session_callback(self._dispose, session)
            except BaseException as exc:
                remaining.append(session)
                errors.append(exc)
        self._pending_retirements = remaining
        if errors:
            primary = errors[0]
            for additional in errors[1:]:
                primary.add_note(
                    f"Additional Session retirement failure: {additional!r}"
                )
            raise primary

    async def _prepare_release(
        self,
        session: S,
        *,
        before_release: SessionCallback[S] | None,
    ) -> None:
        if before_release is not None:
            await _invoke_session_callback(before_release, session)
        if self._before_invalidate is not None:
            await _invoke_lifecycle_callback(self._before_invalidate)
        for observer in tuple(self._before_invalidate_observers):
            await _invoke_lifecycle_callback(observer)

    async def _notify_after_invalidate(self) -> None:
        self._notifying_after_invalidate = True
        try:
            for observer in tuple(self._after_invalidate_observers):
                try:
                    await _invoke_lifecycle_callback(observer)
                except Exception:
                    continue
        finally:
            self._notifying_after_invalidate = False

    def _reject_reentrant_after_invalidate_transition(self) -> None:
        if (
            self._notifying_after_invalidate
            and self._lock_owner is asyncio.current_task()
        ):
            raise RuntimeError(
                "Session transition cannot be re-entered from an "
                "after-invalidate observer"
            )


async def _invoke_session_callback(callback: SessionCallback[S], session: S) -> None:
    result = callback(session)
    if inspect.isawaitable(result):
        await result


async def _invoke_lifecycle_callback(callback: LifecycleCallback) -> None:
    result = callback()
    if inspect.isawaitable(result):
        await result


__all__ = ["LifecycleCallback", "SessionCallback", "SessionTransitionHost"]
