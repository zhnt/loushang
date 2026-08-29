"""Neutral lifecycle mechanics for unpublished activation candidates."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable

from loushang.harness.continuity.provider import PreparedActivationLease
from loushang.harness.continuity.types import (
    ActivationDisposition,
    ContinuityTarget,
)

ActivationFactory = Callable[[], object | Awaitable[object]]
CleanupCallback = Callable[[], None | Awaitable[None]]


class ActivationLeaseStateError(RuntimeError):
    """Raised when a prepared activation lease is consumed more than once."""


class CallbackPreparedActivationLease:
    """A small lease implementation used by Product-specific coordinators.

    The candidate stays private until ``consume``. Aborting or closing an
    unconsumed lease invokes cleanup once; closing a consumed lease is a no-op.
    """

    def __init__(
        self,
        *,
        target: ContinuityTarget,
        disposition: ActivationDisposition,
        consume: ActivationFactory,
        abort: CleanupCallback | None = None,
    ) -> None:
        self._target = target
        self._disposition = disposition
        self._consume = consume
        self._abort = abort
        self._consumed = False
        self._consume_attempted = False
        self._closed = False
        self._consuming = False
        self._consume_done = asyncio.Event()
        self._consume_done.set()
        self._abort_requested = False
        self._abort_task: asyncio.Task[None] | None = None

    @property
    def target(self) -> ContinuityTarget:
        return self._target

    @property
    def disposition(self) -> ActivationDisposition:
        return self._disposition

    @property
    def consumed(self) -> bool:
        return self._consumed

    async def consume(self) -> object:
        if self._closed or self._abort_requested:
            raise ActivationLeaseStateError("activation lease is closed")
        if self._consume_attempted or self._consuming:
            raise ActivationLeaseStateError(
                "activation lease has already been consumed"
            )
        # This synchronous state change is the lease linearization point.  An
        # abort that starts after it joins this attempt; an abort that starts
        # first sets ``_abort_requested`` and prevents publication.
        self._consuming = True
        self._consume_attempted = True
        self._consume_done.clear()
        try:
            result = self._consume()
            if inspect.isawaitable(result):
                result = await result
            self._consumed = True
            return result
        finally:
            self._consuming = False
            self._consume_done.set()

    async def abort(self) -> None:
        if self._closed:
            return
        # Record abort intent before the first await.  Cancellation or cleanup
        # failure never re-opens the lease for consume.
        self._abort_requested = True
        if self._consuming:
            await asyncio.shield(self._consume_done.wait())
        if self._consumed:
            self._closed = True
            return
        if self._abort is None:
            self._closed = True
            return
        task = self._abort_task
        if task is None:
            task = asyncio.create_task(self._run_abort())
            self._abort_task = task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # The owned cleanup continues and a later abort joins the same task.
            raise
        except BaseException:
            if self._abort_task is task:
                self._abort_task = None
            raise

    async def _run_abort(self) -> None:
        assert self._abort is not None
        result = self._abort()
        if inspect.isawaitable(result):
            await result
        self._closed = True

    async def close(self) -> None:
        await self.abort()

    async def __aenter__(self) -> CallbackPreparedActivationLease:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()


async def consume_prepared_activation(
    lease: PreparedActivationLease,
) -> object:
    """Consume one prepared activation and always settle its lease."""

    try:
        result = await lease.consume()
    except BaseException:
        await lease.abort()
        raise
    await lease.close()
    return result


__all__ = [
    "ActivationLeaseStateError",
    "CallbackPreparedActivationLease",
    "consume_prepared_activation",
]
