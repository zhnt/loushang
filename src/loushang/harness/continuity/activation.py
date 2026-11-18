"""Neutral lifecycle mechanics for unpublished activation candidates."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loushang.harness.continuity._payload_staging import _ContinuityPayloadStaging
from loushang.harness.continuity.import_provider import ContinuityActivationPayload
from loushang.harness.continuity.provider import PreparedActivationLease
from loushang.harness.continuity.types import (
    ActivationDisposition,
    ContinuityTarget,
)
from loushang.harness.runtime import await_owned_task

ActivationFactory = Callable[[], object | Awaitable[object]]
CleanupCallback = Callable[[], None | Awaitable[None]]


class ActivationLeaseStateError(RuntimeError):
    """Raised when a prepared activation lease is consumed more than once."""


class _PreparedActivationOperation(Protocol):
    async def consume(self) -> object: ...

    async def abort(self) -> None: ...


@dataclass(slots=True)
class _PreparedOperationSettlement:
    prepared: _PreparedActivationOperation
    error_label: str
    _abort_complete: bool = False

    async def consume(self) -> object:
        try:
            return await self.prepared.consume()
        except BaseException as operation_error:
            try:
                await self.abort()
            except BaseException as abort_error:
                operation_error.add_note(
                    f"{self.error_label} abort also failed: "
                    f"{type(abort_error).__name__}"
                )
            raise

    async def abort(self) -> None:
        if self._abort_complete:
            return
        abort_task = asyncio.create_task(self.prepared.abort())
        try:
            await await_owned_task(abort_task)
        except BaseException:
            if _task_completed_successfully(abort_task):
                self._abort_complete = True
            raise
        self._abort_complete = True


def _task_completed_successfully(task: asyncio.Task[object]) -> bool:
    return task.done() and not task.cancelled() and task.exception() is None


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
        self._initialize_lifecycle()

    @classmethod
    async def _from_staged_payload(
        cls,
        *,
        target: ContinuityTarget,
        payload: ContinuityActivationPayload,
        staging: _ContinuityPayloadStaging,
        root: Path,
        prepare: Callable[[Path], Awaitable[_PreparedActivationOperation]],
        settlement_error_label: str,
    ) -> CallbackPreparedActivationLease:
        staged = await staging.write_atomic(root, payload)
        try:
            prepared = await prepare(staged.path)
        except BaseException as operation_error:
            try:
                await staging.remove_atomic(staged)
            except BaseException as cleanup_error:
                operation_error.add_note(
                    f"{staging.label} temporary cleanup also failed: {cleanup_error!r}"
                )
            raise
        try:
            await staging.remove_atomic(staged)
        except BaseException as cleanup_error:
            try:
                abort_task = asyncio.create_task(prepared.abort())
                await await_owned_task(abort_task)
            except BaseException as abort_error:
                cleanup_error.add_note(
                    f"{staging.label} prepared-operation abort also failed: "
                    f"{abort_error!r}"
                )
            raise
        settlement = _PreparedOperationSettlement(prepared, settlement_error_label)
        return cls(
            target=target,
            disposition="in_place",
            consume=settlement.consume,
            abort=settlement.abort,
        )

    def _initialize_lifecycle(self) -> None:
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
        complete = self._admit_consume()
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
            self._activation_consumed()
            return result
        finally:
            self._consuming = False
            self._consume_done.set()
            if complete is not None:
                complete()

    async def abort(self) -> None:
        if self._closed:
            return
        # Record abort intent before the first await.  Cancellation or cleanup
        # failure never re-opens the lease for consume.
        self._abort_requested = True
        if self._consuming:
            await asyncio.shield(self._consume_done.wait())
        if self._closed:
            return
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
        self._activation_aborted()

    def _admit_consume(self) -> Callable[[], None] | None:
        return None

    def _activation_consumed(self) -> None:
        pass

    def _activation_aborted(self) -> None:
        pass

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
