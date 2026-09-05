"""Private retryable settlement primitives for AppHost-owned resources."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, cast

from .errors import CleanupIncompleteError

AsyncClose = Callable[[], Awaitable[None]]
AsyncCall = Callable[..., Awaitable[Any]]


class RetryableCloser:
    """Join concurrent close calls and retry only an unsettled callback."""

    __slots__ = ("_callback", "_complete", "_debt_count", "_lock", "_task")

    def __init__(self, callback: AsyncClose) -> None:
        self._callback = callback
        self._complete = False
        self._debt_count = 0
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[bool] | None = None

    @classmethod
    def bind(cls, value: object) -> RetryableCloser:
        return cls(bind_native_async(value, "close"))

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def debt_count(self) -> int:
        return self._debt_count

    async def settle(self) -> bool:
        async with self._lock:
            if self._complete:
                return True
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run_once())
            task = self._task
        return await asyncio.shield(task)

    async def _run_once(self) -> bool:
        try:
            await self._callback()
        except BaseException:
            self._debt_count += 1
            return False
        self._complete = True
        return True


class CloseGroup:
    """Retryable reverse-order settlement retaining only unresolved owners."""

    __slots__ = ("_closers", "_complete", "_lock", "_task")

    def __init__(self, closers: Iterable[RetryableCloser] = ()) -> None:
        self._closers = list(closers)
        self._complete = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[bool] | None = None

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def debt_count(self) -> int:
        return sum(closer.debt_count for closer in self._closers)

    def append(self, closer: RetryableCloser) -> None:
        if self._task is not None or self._complete:
            raise RuntimeError("cannot append after settlement begins")
        self._closers.append(closer)

    async def settle(self) -> bool:
        async with self._lock:
            if self._complete:
                return True
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run_once())
            task = self._task
        return await asyncio.shield(task)

    async def close(self) -> None:
        if not await self.settle():
            raise CleanupIncompleteError(cleanup_debt_count=self.debt_count) from None

    async def _run_once(self) -> bool:
        complete = True
        for closer in reversed(self._closers):
            if closer.complete:
                continue
            if not await closer.settle():
                complete = False
        self._complete = complete
        return complete


class AcquisitionStack:
    """Record actual acquisition order and transfer it to one close group."""

    __slots__ = ("_closers", "_transferred")

    def __init__(self) -> None:
        self._closers: list[RetryableCloser] = []
        self._transferred = False

    def push(self, value: object) -> RetryableCloser:
        if self._transferred:
            raise RuntimeError("acquisition stack was transferred")
        closer = RetryableCloser.bind(value)
        self._closers.append(closer)
        return closer

    def push_closer(self, closer: RetryableCloser) -> None:
        if self._transferred:
            raise RuntimeError("acquisition stack was transferred")
        self._closers.append(closer)

    def transfer(self) -> CloseGroup:
        if self._transferred:
            raise RuntimeError("acquisition stack was transferred")
        self._transferred = True
        return CloseGroup(self._closers)

    async def unwind(self) -> None:
        if self._transferred:
            return
        self._transferred = True
        await CloseGroup(self._closers).close()


def bind_native_async(value: object, name: str) -> AsyncCall:
    """Bind one class-defined native-async descriptor without dynamic lookup."""

    if inspect.getattr_static(
        type(value), "__getattribute__", object.__getattribute__
    ) is not object.__getattribute__:
        raise TypeError("dynamic attribute dispatch is forbidden")
    descriptor = inspect.getattr_static(type(value), name, None)
    if inspect.getattr_static(value, name, None) is not descriptor:
        raise TypeError("instance callback shadow is forbidden")
    inspected = (
        descriptor.__func__
        if isinstance(descriptor, (classmethod, staticmethod))
        else descriptor
    )
    if not inspect.iscoroutinefunction(inspected):
        raise TypeError("native async class descriptor required")
    return cast(AsyncCall, descriptor.__get__(value, type(value)))


def read_static_property(value: object, name: str) -> object:
    """Read one class-defined property once without invoking attribute hooks."""

    if inspect.getattr_static(
        type(value), "__getattribute__", object.__getattribute__
    ) is not object.__getattribute__:
        raise TypeError("dynamic attribute dispatch is forbidden")
    descriptor = inspect.getattr_static(type(value), name, None)
    if not isinstance(descriptor, property):
        raise TypeError("class-defined property required")
    if inspect.getattr_static(value, name, None) is not descriptor:
        raise TypeError("instance property shadow is forbidden")
    return descriptor.__get__(value, type(value))


__all__: list[str] = []
