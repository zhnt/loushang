"""One graceful stop over an exact recorded service; no kill or restart policy."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import monotonic
from typing import TypeVar

from loushang.hosting.service import ServiceObserverV1, reopen_service_observer
from loushang.hosting.service_group import LinuxServiceGroupObservationV1
from loushang.hosting.service_windows import (
    WindowsServiceJobV1,
    WindowsServiceObserverV1,
)

from ._files import ManagedStorageError, _check_deadline
from .child import _spawn
from .connection import _settled_native
from .contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from .defaults import ManagedDefaultsV1, current_managed_user
from .discovery import ManagedDiscoverySnapshotV1, ManagedServiceObservationV1
from .lifecycle import ManagedServiceJournalV1, ManagedServiceStateV1
from .namespace_admission import ManagedNamespaceAdmissionV1
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
                or namespace.user_id != current_managed_user() or instance.namespace_key != namespace.namespace_key
                or instance.service_id != service.service_id or journal._namespace != namespace
                or journal._service != service or str(journal._fence._root) != str(paths.lifecycle)
                or str(journal._database._directory._root) != str(paths.registry)):
            raise ManagedContractError()
        self._journal, self._instance = journal, instance
        self._observer: ServiceObserverV1 | None = None
        self._group: LinuxServiceGroupObservationV1 | WindowsServiceJobV1 | None = None
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
        self._observer = reopen_service_observer(state.native_identity)
        self._native_uncertain = False
        if isinstance(self._observer, WindowsServiceObserverV1):
            self._group = self._observer.open_scope(state.handoff.attempt_id)
        else:
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
        if isinstance(self._group, WindowsServiceJobV1):
            await _settled_native(self._group.close)
            self._group = None
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


@dataclass
class _ServiceStopEntry:
    observation: ManagedServiceObservationV1
    journal: ManagedServiceJournalV1 | None = None
    stopper: ManagedServiceStopOperationV1 | None = None
    closing: asyncio.Task[None] | None = None


class _ManagedServiceStopBatch:
    """Borrow namespace until all original entry cleanup has completed.

    The stop budget never renews. Cleanup gets a separate bounded wait, never
    another stop attempt. Cancelling a waiter does not cancel owned cleanup.
    """

    def __init__(self, namespace: ManagedNamespaceAdmissionV1, defaults: ManagedDefaultsV1,
                 snapshot: ManagedDiscoverySnapshotV1, *, deadline: float) -> None:
        self.namespace, self.defaults, self.deadline = namespace, defaults, deadline
        self.entries = tuple(_ServiceStopEntry(item) for item in snapshot.services)
        self.started = self.closed = False

    @property
    def cleanup_pending(self) -> bool:
        return any(entry.journal is not None or entry.stopper is not None for entry in self.entries)

    async def _close_entry(self, entry: _ServiceStopEntry) -> None:
        if entry.stopper is not None:
            await entry.stopper.close()
            entry.stopper = None
        if entry.journal is not None:
            await _settled_native(entry.journal.close)
            entry.journal = None

    def _begin_close(self, entry: _ServiceStopEntry) -> None:
        previous = entry.closing
        retry = previous is None or (previous.done() and (
            previous.cancelled() or previous.exception() is not None))
        if retry and (entry.stopper is not None or entry.journal is not None):
            entry.closing = _spawn(self._close_entry(entry))

    async def _wait_close(self, entries: tuple[_ServiceStopEntry, ...]) -> None:
        # Start every original cleanup before waiting for any one of them.
        admission_failed = False
        for entry in entries:
            try:
                self._begin_close(entry)
            except Exception:
                admission_failed = True
        tasks = [entry.closing for entry in entries if entry.closing is not None]
        if not tasks:
            if admission_failed:
                raise ManagedStorageError("unavailable")
            return
        done, pending = await asyncio.wait(tasks, timeout=2.0)
        failed = any([task.cancelled() or task.exception() is not None for task in done])
        if pending or failed or admission_failed:
            raise ManagedStorageError("busy" if pending else "unavailable")

    async def close(self) -> None:
        self.closed = True
        await self._wait_close(self.entries)

    async def run(self) -> None:
        if self.started or self.closed:
            raise ManagedStorageError("closed")
        self.started = True
        failed = False
        for entry in self.entries:
            observed = entry.observation
            if observed.instance is None:
                self._report(observed, "skipped", reason="no_instance_at_snapshot")
                continue
            if monotonic() >= self.deadline:
                failed = True
                self._report(observed, "not_attempted", reason="deadline")
                continue
            try:
                _check_deadline(self.deadline)
                paths = resolve_managed_service_paths(self.defaults.namespace, observed.service,
                    runtime_root=str(self.defaults.platform.runtime))
                entry.journal = ManagedServiceJournalV1(self.namespace.registry, self.defaults.namespace,
                    observed.service, Path(paths.lifecycle), defer_open=True)
                journal = entry.journal
                await _settled_native(partial(journal.open, deadline=self.deadline, wait_for_lock=True))
                entry.stopper = ManagedServiceStopOperationV1(entry.journal, self.defaults.namespace,
                    observed.service, observed.instance, runtime_root=str(self.defaults.platform.runtime))
                await entry.stopper.run(deadline=self.deadline)
                await self._wait_close((entry,))
            except Exception as error:
                # Cancellation and KeyboardInterrupt must escape this loop.
                failed = True
                code = error.code if isinstance(error, ManagedStorageError) else "unavailable"
                self._report(observed, "failed", code=code)
            else:
                self._report(observed, "stopped")
        if failed:
            raise ManagedStorageError("unavailable")

    def _report(
        self, observation: ManagedServiceObservationV1, status: str, *,
        reason: str | None = None, code: str | None = None,
    ) -> None:
        raise NotImplementedError
