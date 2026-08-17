"""Neutral lifecycle mechanics for unpublished activation candidates."""

from __future__ import annotations

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
        self._closed = False

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
        if self._closed:
            raise ActivationLeaseStateError("activation lease is closed")
        if self._consumed:
            raise ActivationLeaseStateError(
                "activation lease has already been consumed"
            )
        self._consumed = True
        result = self._consume()
        if inspect.isawaitable(result):
            return await result
        return result

    async def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._consumed or self._abort is None:
            return
        result = self._abort()
        if inspect.isawaitable(result):
            await result

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
