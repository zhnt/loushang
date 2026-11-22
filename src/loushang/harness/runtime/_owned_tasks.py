"""Cancellation-safe joins and cleanup of unpublished runtime owners."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Generic, Protocol, TypeVar

from loushang.foundation._owned_tasks import (
    _join_failure_first,
    _observe_task_result,
)

T = TypeVar("T")


_await_cancellation_atomic = _join_failure_first


def _get_close_task(
    task: asyncio.Task[None] | None,
    close: Callable[[], Coroutine[Any, Any, None]],
    *,
    retry_cancelled: bool = True,
) -> asyncio.Task[None]:
    """Reuse an in-flight close and observe failures even without a waiter."""
    if task is not None and (
        not task.done()
        or (not retry_cancelled if task.cancelled() else task.exception() is None)
    ):
        return task
    task = asyncio.create_task(close())
    task.add_done_callback(_observe_task_result)
    return task


class _UnpublishedCloseOwner(Protocol):
    async def close(self) -> None: ...


_ProductOwnerT = TypeVar("_ProductOwnerT", bound=_UnpublishedCloseOwner)


class _UnpublishedProductOwners(Generic[_ProductOwnerT]):
    """Track unpublished construction separately from failed compensation."""

    __slots__ = ("_active", "_debt")

    def __init__(self) -> None:
        self._active: set[_ProductOwnerT] = set()
        self._debt: set[_ProductOwnerT] = set()

    @property
    def active(self) -> bool:
        return bool(self._active)

    @property
    def pending_count(self) -> int:
        return len(self._debt)

    def adopt(self, owner: _ProductOwnerT) -> None:
        self._active.add(owner)

    def publish(self, owner: _ProductOwnerT) -> None:
        self._active.discard(owner)

    async def abort(
        self,
        owner: _ProductOwnerT,
        *,
        failure: RuntimeError,
        join_close: bool = False,
    ) -> None:
        task = asyncio.create_task(owner.close()) if join_close else None
        try:
            if task is None:
                await owner.close()
            else:
                await _join_failure_first(task)
        except asyncio.CancelledError:
            self._debt.discard(owner)
            raise
        except BaseException:
            self._debt.add(owner)
            raise failure from None
        else:
            self._debt.discard(owner)
        finally:
            self._active.discard(owner)

    async def retry_cleanup(self) -> bool:
        debt = tuple(self._debt)
        if debt:
            results = await asyncio.gather(
                *(owner.close() for owner in debt), return_exceptions=True
            )
            for owner, result in zip(debt, results, strict=True):
                if result is None:
                    self._debt.discard(owner)
        return not self._debt


__all__: list[str] = []
