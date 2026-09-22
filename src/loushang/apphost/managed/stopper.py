"""One graceful stop over an exact recorded service; no kill or restart policy."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from functools import partial
from typing import TypeVar

from loushang.hosting.service import LinuxServiceObserverV1
from loushang.hosting.service_group import LinuxServiceGroupObservationV1

from ._files import ManagedStorageError, _check_deadline
from .child import _spawn
from .connection import _settled_native
from .contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from .lifecycle import ManagedServiceJournalV1, ManagedServiceStateV1
from .paths import resolve_managed_service_paths

_T = TypeVar("_T")


class ManagedServiceStopOperationV1:
    """Own observations, borrow the journal; closing never revokes accepted stop.

    Retain before run, and keep the original event loop/journal through close.
    Already-dead leaders without a prior group admission remain unavailable;
    numeric PID disappearance is not clean-stop recovery evidence.
    """

    def __init__(self, journal: ManagedServiceJournalV1, namespace: ManagedNamespaceV1,
                 service: ManagedServiceKeyV1, instance: ManagedInstanceRefV1, *, runtime_root: str) -> None:
        paths = resolve_managed_service_paths(namespace, service, runtime_root=runtime_root)
        if (type(journal) is not ManagedServiceJournalV1 or type(instance) is not ManagedInstanceRefV1
                or namespace.user_id != os.geteuid() or instance.namespace_key != namespace.namespace_key
                or instance.service_id != service.service_id or journal._namespace != namespace
                or journal._service != service or str(journal._fence._root) != str(paths.lifecycle)
                or str(journal._database._directory._root) != str(paths.registry)):
            raise ManagedContractError()
        self._journal, self._instance = journal, instance
        self._observer: LinuxServiceObserverV1 | None = None
        self._group: LinuxServiceGroupObservationV1 | None = None
        self._native_uncertain = self._close_unknown = False
        self._state: ManagedServiceStateV1 | None = None
        self._task: asyncio.Task[ManagedServiceStateV1] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._deadline: float | None = None
        self._closing = self._settled = False

    @property
    def state(self) -> ManagedServiceStateV1 | None:
        return self._state

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ManagedStorageError("conflict")

    async def run(self, *, deadline: float) -> ManagedServiceStateV1:
        self._bind_loop()
        if type(deadline) not in (int, float) or not 0 < deadline <= 1e12:
            raise ManagedContractError()
        _check_deadline(deadline)
        if self._closing:
            raise ManagedStorageError("closed")
        if self._task is None:
            self._deadline = deadline
            self._task = _spawn(self._run_once(deadline))
        elif self._deadline != deadline:
            raise ManagedStorageError("conflict")
        result = await asyncio.shield(self._task)
        _check_deadline(deadline)
        return result

    async def _control(self, operation: Callable[[], _T], deadline: float) -> _T:
        def enter() -> _T:
            # Executor admission can lag behind submission. Once entered, keep
            # the original receipt even if it arrives after the deadline.
            _check_deadline(deadline)
            return operation()

        while True:
            _check_deadline(deadline)
            try:
                return await _settled_native(enter)
            except ManagedStorageError as error:
                if error.code != "busy":
                    raise
                await asyncio.sleep(0.01)

    def _read(self, deadline: float) -> ManagedServiceStateV1:
        state = self._journal.read(deadline=deadline)
        if state is None or state.handoff.instance != self._instance:
            raise ManagedStorageError("conflict")
        self._state = state
        return state

    def _admit(self, state: ManagedServiceStateV1) -> None:
        assert state.native_identity is not None
        self._native_uncertain = True
        self._observer = LinuxServiceObserverV1.reopen(state.native_identity)
        self._native_uncertain = False
        self._group = LinuxServiceGroupObservationV1(self._observer)
        self._group.admit()

    def _observe(self) -> tuple[bool, bool]:
        assert self._observer is not None and self._group is not None
        if not self._observer.exited():
            return False, False
        return True, self._group.exited()

    async def _run_once(self, deadline: float) -> ManagedServiceStateV1:
        if self._closing:
            raise ManagedStorageError("closed")
        state = await self._control(lambda: self._read(deadline), deadline)
        if state.cleanly_stopped:
            return state
        if state.native_identity is not None:
            await self._control(lambda: self._admit(state), deadline)
        self._state = await self._control(lambda: self._journal.request_stop(self._instance, deadline=deadline), deadline)
        while True:
            state = await self._control(lambda: self._read(deadline), deadline)
            if state.cleanly_stopped:
                return state
            if state.native_identity is not None:
                if self._observer is None:
                    await self._control(partial(self._admit, state), deadline)
                assert self._observer is not None
                if self._observer.identity != state.native_identity:
                    raise ManagedStorageError("conflict")
                leader, group = await self._control(self._observe, deadline)
                if leader:
                    native = self._observer.identity
                    self._state = await self._control(partial(self._journal.record_native_stop,
                        self._instance, native, process_exited=leader,
                        process_scope_settled=group, deadline=deadline,
                    ), deadline)
                    if self._state.cleanly_stopped:
                        return self._state
            await asyncio.sleep(0.01)

    async def close(self) -> None:
        self._bind_loop()
        self._closing = True
        if self._close_task is None or (self._close_task.done() and (
            self._close_task.cancelled() or self._close_task.exception() is not None
        )):
            self._close_task = _spawn(self._close_once())
        await asyncio.shield(self._close_task)

    async def _close_once(self) -> None:
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        if self._observer is not None:
            if self._close_unknown:
                raise ManagedStorageError("unavailable")
            self._close_unknown = True
            await _settled_native(self._observer.close)
            self._close_unknown = False
            self._observer = None
            self._group = None
        if self._native_uncertain:
            raise ManagedStorageError("unavailable")
        self._settled = True


__all__ = ["ManagedServiceStopOperationV1"]
