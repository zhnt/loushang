"""CLI batch composition; exact frozen instances, original owners and no force."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import monotonic

from loushang.apphost.managed._files import ManagedStorageError, _check_deadline
from loushang.apphost.managed.child import _spawn
from loushang.apphost.managed.connection import _settled_native
from loushang.apphost.managed.defaults import ManagedDefaultsV1
from loushang.apphost.managed.discovery import (
    ManagedDiscoverySnapshotV1,
    ManagedServiceObservationV1,
)
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.paths import resolve_managed_service_paths
from loushang.apphost.managed.stopper import ManagedServiceStopOperationV1


@dataclass
class _Entry:
    observation: ManagedServiceObservationV1
    journal: ManagedServiceJournalV1 | None = None
    stopper: ManagedServiceStopOperationV1 | None = None
    closing: asyncio.Task[None] | None = None


class StopAll:
    """Borrow namespace until all original entry cleanup has completed.

    The stop budget never renews. Cleanup gets a separate bounded wait, never
    another stop attempt. Cancelling a waiter does not cancel owned cleanup.
    """

    def __init__(self, namespace: ManagedNamespaceAdmissionV1, defaults: ManagedDefaultsV1,
                 snapshot: ManagedDiscoverySnapshotV1, *, deadline: float,
                 emit: Callable[[dict[str, object]], None]) -> None:
        self.namespace, self.defaults, self.deadline, self.emit = namespace, defaults, deadline, emit
        self.entries = tuple(_Entry(item) for item in snapshot.services)
        self.started = self.closed = False

    @property
    def cleanup_pending(self) -> bool:
        return any(entry.journal is not None or entry.stopper is not None for entry in self.entries)

    async def _close_entry(self, entry: _Entry) -> None:
        if entry.stopper is not None:
            await entry.stopper.close()
            entry.stopper = None
        if entry.journal is not None:
            await _settled_native(entry.journal.close)
            entry.journal = None

    def _begin_close(self, entry: _Entry) -> None:
        previous = entry.closing
        retry = previous is None or (previous.done() and (
            previous.cancelled() or previous.exception() is not None))
        if retry and (entry.stopper is not None or entry.journal is not None):
            entry.closing = _spawn(self._close_entry(entry))

    async def _wait_close(self, entries: tuple[_Entry, ...]) -> None:
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
            result: dict[str, object] = {"action": "stop_result", "serviceId": observed.service.service_id,
                "instanceId": None if observed.instance is None else observed.instance.instance_id}
            if observed.instance is None:
                self.emit({**result, "status": "skipped", "reason": "no_instance_at_snapshot"})
                continue
            if monotonic() >= self.deadline:
                failed = True
                self.emit({**result, "status": "not_attempted", "reason": "deadline"})
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
                self.emit({**result, "status": "failed", "code": code})
            else:
                self.emit({**result, "status": "stopped"})
        if failed:
            raise ManagedStorageError("unavailable")
