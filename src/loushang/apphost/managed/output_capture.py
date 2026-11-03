"""Loop-owned capture lease; native work outlives cancelled public waiters."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, TypeVar

from loushang.harness.workspace.exec.capture_lease import (
    CapturePreparation,
    SealedExecCapture,
)
from loushang.harness.workspace.exec.types import ExecOutputChunk

from ._capture_native import NativeOutputCapture
from ._files import MAX_RECORD_BYTES, ManagedStorageError, PrivateManagedDirectory
from .connection import _settled_native
from .contracts import ManagedContractError
from .storage_budget import ManagedStorageAllocationV1, ManagedStorageBudgetV1

_T = TypeVar("_T")


class ManagedOutputCaptureFactory:
    """Borrow one instance's opened root; keep slots until leases truly close.

    The composition owns the directory and keeps it alive through factory close.
    Constructing a lease performs no filesystem or database IO.
    """

    def __init__(self, owner: PrivateManagedDirectory, budget: ManagedStorageBudgetV1, *,
                 service_id: str, instance_id: str, capacity: int = 64 * 1024**2) -> None:
        if type(owner) is not PrivateManagedDirectory or type(budget) is not ManagedStorageBudgetV1:
            raise ManagedContractError()
        self._owner, self._budget = owner, budget
        self._template = ManagedStorageAllocationV1(service_id, "temporary", instance_id, 0, capacity,
            sha256(os.fsencode(owner._root)).hexdigest(), owner._identity)
        self._leases: dict[int, ManagedOutputCapture] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing = False
        self._settled = False

    @property
    def settled(self) -> bool:
        """Terminal receipt readable by the outer native dependency owner."""
        return self._settled

    def close_unstarted(self) -> None:
        """No-loop failure cleanup; never settle a factory that entered a loop."""
        if self._settled:
            return
        if self._loop is not None or self._leases:
            raise ManagedStorageError("busy")
        self._closing = self._settled = True

    def _bind(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise ManagedStorageError("conflict")
        self._loop = loop

    def new_capture(self) -> ManagedOutputCapture:
        self._bind()
        if self._closing:
            raise ManagedStorageError("closed")
        for existing_slot, lease in tuple(self._leases.items()):
            if lease._closed and not lease.cleanup_pending:
                del self._leases[existing_slot]
        slot = next((value for value in range(8) if value not in self._leases), None)
        if slot is None:
            raise ManagedStorageError("capacity")
        template = self._template
        allocations = tuple(ManagedStorageAllocationV1(template.service_id, "temporary", template.instance_id,
            slot * 2 + index, template.capacity, template.root_key, template.root_identity) for index in (0, 1))
        lease = ManagedOutputCapture(NativeOutputCapture(self._owner, self._budget, (allocations[0], allocations[1])))
        self._leases[slot] = lease
        return lease

    @property
    def cleanup_pending(self) -> bool:
        self._bind()
        return any(not lease._closed or lease.cleanup_pending for lease in self._leases.values())

    async def close(self) -> None:
        self._bind()
        self._closing = True
        for lease in self._leases.values():
            lease._fence()
        failures = []
        for lease in tuple(self._leases.values()):
            try:
                await lease.close()
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]
        self._settled = True


@dataclass(frozen=True, slots=True)
class _SealedSource:
    lease: ManagedOutputCapture
    index: int
    size_bytes: int

    async def read_bytes(self, *, max_bytes: int) -> bytes:
        return await self.lease._read(self.index, max_bytes=max_bytes)


class ManagedOutputCapture:
    """One original storage owner, bounded admissions, one serialized worker."""

    def __init__(self, native: NativeOutputCapture) -> None:
        self._native = native
        self._loop: asyncio.AbstractEventLoop | None = None
        self._serial = asyncio.Lock()
        self._pending: set[asyncio.Task[Any]] = set()
        self._prepare_task: asyncio.Task[bool] | None = None
        self._seal_task: asyncio.Task[Any] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._reads: list[asyncio.Task[bytes] | None] = [None, None]
        self._sealed: SealedExecCapture | None = None
        self._accepting = True
        self._refused = False
        self._closing = self._closed = self._unknown = False

    def _bind(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise ManagedStorageError("conflict")
        self._loop = loop
        return loop

    def _submit(self, function: Callable[[], _T]) -> asyncio.Task[_T]:
        loop = self._bind()
        if self._unknown:
            raise ManagedStorageError("unavailable")
        if len(self._pending) >= 8:
            raise ManagedStorageError("capacity")

        async def run() -> _T:
            async with self._serial:
                if self._unknown:
                    raise ManagedStorageError("unavailable")
                try:
                    return await _settled_native(function)
                except asyncio.CancelledError:
                    self._unknown = True  # Not a native completion receipt.
                    raise

        coroutine = run()
        try:
            # Trusted internal owner: public loop task factories cannot detach
            # the native callable from the task retained by this lease.
            task = asyncio.Task(coroutine, loop=loop)
        except BaseException:
            coroutine.close()
            raise
        self._pending.add(task)

        def completed(done: asyncio.Task[_T]) -> None:
            if done.cancelled():
                self._unknown = True
                return
            done.exception()  # Observe failure even if every waiter departed.
            self._pending.discard(done)

        task.add_done_callback(completed)
        return task

    async def prepare(self) -> CapturePreparation:
        self._bind()
        if self._closing:
            raise ManagedStorageError("closed")
        if self._prepare_task is None:
            self._prepare_task = self._submit(self._native.prepare)
        ready = await asyncio.shield(self._prepare_task)
        if self._closing:
            raise ManagedStorageError("closed")
        if not ready:
            self._refused = True
            self._accepting = False
        return CapturePreparation.READY if ready else CapturePreparation.RETENTION_UNAVAILABLE

    def stop_accepting(self) -> None:
        self._bind()
        self._accepting = False

    async def append(self, chunk: ExecOutputChunk) -> None:
        self._bind()
        if not self._accepting or self._closing:
            return
        if (type(chunk) is not ExecOutputChunk or chunk.stream not in ("stdout", "stderr")
                or type(chunk.text) is not str or len(chunk.text) > MAX_RECORD_BYTES):
            raise ManagedStorageError("invalid_record")
        content = chunk.text.encode("utf-8", errors="surrogateescape")
        index = 0 if chunk.stream == "stdout" else 1

        def append() -> None:
            for start in range(0, len(content), MAX_RECORD_BYTES):
                self._native.append(index, content[start:start + MAX_RECORD_BYTES])

        await asyncio.shield(self._submit(append))

    async def seal(self) -> SealedExecCapture | None:
        self._bind()
        if self._closing:
            raise ManagedStorageError("closed")
        self._accepting = False
        if self._refused:
            return None
        if self._seal_task is None:
            self._seal_task = self._submit(self._native.seal)
        snapshots = await asyncio.shield(self._seal_task)
        if self._closing:
            raise ManagedStorageError("closed")
        if snapshots is None:
            return None
        if self._sealed is None:
            self._sealed = SealedExecCapture(_SealedSource(self, 0, snapshots[0].size),
                                             _SealedSource(self, 1, snapshots[1].size))
        return self._sealed

    async def _read(self, index: int, *, max_bytes: int) -> bytes:
        self._bind()
        if self._closing or self._sealed is None:
            raise ManagedStorageError("closed")
        prior = self._reads[index]
        if prior is not None and not prior.done():
            raise ManagedStorageError("busy")
        task = self._submit(lambda: self._native.read(index, max_bytes=max_bytes))
        self._reads[index] = task
        return await asyncio.shield(task)

    @property
    def cleanup_pending(self) -> bool:
        self._bind()
        return not self._closed and (bool(self._pending) or self._unknown or self._close_task is not None
                                     or self._native.cleanup_pending)

    async def close(self) -> None:
        loop = self._bind()
        self._fence()
        if self._closed:
            return
        task = self._close_task
        if task is None or (task.done() and not task.cancelled() and task.exception() is not None):
            task = asyncio.Task(self._close(), loop=loop)
            self._close_task = task
        await asyncio.shield(task)

    def _fence(self) -> None:
        self._bind()
        self._closing = True
        self._accepting = False

    async def _close(self) -> None:
        pending = tuple(self._pending)
        if pending:
            await asyncio.gather(*(asyncio.shield(task) for task in pending), return_exceptions=True)
        if self._unknown:
            raise ManagedStorageError("unavailable")
        await asyncio.shield(self._submit(self._native.close))
        if self._native.cleanup_pending:
            raise ManagedStorageError("unavailable")
        self._reads = [None, None]
        self._sealed = None
        self._closed = True
