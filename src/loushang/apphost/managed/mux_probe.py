"""Bounded read-only Mux discovery with owned, same-loop authentication.

No attach, spawn, stop or Session recovery. Only immutable observations leave
the operation; connections and journals settle before a result is returned.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Literal

from loushang.appserver.local_record import require_endpoint
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    MuxReadV1,
    MuxSelectorV1,
    MuxSpaceV1,
)
from loushang.appservice.continuity import require_application_id

from ._files import ManagedStorageError, _check_deadline
from .child import _spawn
from .connection import ManagedConnectionLeaseV1, _settled_native
from .contracts import (
    _ID,
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedNamespaceV1,
    _match,
    _path,
)
from .discovery import ManagedDiscoveryV1, ManagedMuxObservationV1
from .lifecycle import ManagedServiceJournalV1
from .mux_management import ManagedMuxManagerV1
from .paths import resolve_managed_service_paths
from .registry import MAX_MUXES, ManagedRegistryV1

ProbeStatus = Literal["authenticated_present", "recorded_ineligible", "not_present", "unknown"]


@dataclass(frozen=True, slots=True)
class ManagedMuxProbeResultV1:
    observation: ManagedMuxObservationV1
    status: ProbeStatus
    mux_space_id: str | None = None

    def __post_init__(self) -> None:
        if (type(self.observation) is not ManagedMuxObservationV1 or type(self.status) is not str
                or self.status not in {"authenticated_present", "recorded_ineligible", "not_present", "unknown"}
                or (self.status in {"authenticated_present", "not_present"}) != (self.mux_space_id is not None)):
            raise ManagedContractError()
        if self.mux_space_id is not None:
            MuxSelectorV1(mux_space_id=self.mux_space_id)


@dataclass(frozen=True, slots=True)
class ManagedMuxProbeSnapshotV1:
    results: tuple[ManagedMuxProbeResultV1, ...]
    candidates_unchanged: bool

    def __post_init__(self) -> None:
        if (type(self.results) is not tuple or len(self.results) > MAX_MUXES
                or any(type(row) is not ManagedMuxProbeResultV1 for row in self.results)
                or type(self.candidates_unchanged) is not bool
                or len({row.observation.name for row in self.results}) != len(self.results)):
            raise ManagedContractError()

    @property
    def unique_present(self) -> ManagedMuxProbeResultV1 | None:
        if not self.candidates_unchanged or any(row.status == "unknown" for row in self.results):
            return None
        present = [row for row in self.results if row.status == "authenticated_present"]
        return present[0] if len(present) == 1 else None


def _candidate_key(item: ManagedMuxObservationV1) -> tuple[object, ...]:
    return (item.reservation, item.instance, item.recorded_phase, item.stop_requested, item.cleanly_stopped)


class ManagedMuxProbeOperationV1:
    """Borrow registry until close settles; public cancellation never drops IO.

    Construction performs no IO. The caller retains this owner before run and
    must keep its loop alive through close, including a timed-out close waiter.
    The operation never terminates its host process.
    """

    def __init__(self, registry: ManagedRegistryV1, namespace: ManagedNamespaceV1, *,
                 product_id: str, runtime_root: str, endpoint: str,
                 expected_application_id: str, deadline: float) -> None:
        self._discovery = ManagedDiscoveryV1(registry, namespace)
        _match(product_id, _ID)
        _path(runtime_root)
        require_endpoint(endpoint)
        require_application_id(expected_application_id)
        if deadline is None:
            raise ManagedContractError()
        _check_deadline(deadline)
        self._registry, self._namespace = registry, namespace
        self._product, self._runtime = product_id, runtime_root
        self._endpoint, self._application = endpoint, expected_application_id
        self._deadline = deadline
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[ManagedMuxProbeSnapshotV1] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._close_deadline: float | None = None
        self._journal: ManagedServiceJournalV1 | None = None
        self._connection: ManagedConnectionLeaseV1 | None = None
        self._closing = self._settled = False

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    def _bind_loop(self) -> None:
        current = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = current
        elif current is not self._loop:
            raise ManagedStorageError("conflict")

    async def run(self) -> ManagedMuxProbeSnapshotV1:
        self._bind_loop()
        if self._closing:
            raise ManagedStorageError("closed")
        if self._task is None:
            self._task = _spawn(self._run_once())
        result = await asyncio.shield(self._task)
        if self._closing:
            raise ManagedStorageError("closed")
        # Native completion and loop delivery are different observations. A
        # late/rejoined result may be displayed, but cannot auto-select.
        if monotonic() >= self._deadline:
            return replace(result, candidates_unchanged=False)
        return result

    def _snapshot(self) -> tuple[ManagedMuxObservationV1, ...]:
        snapshot = self._discovery.snapshot_namespace(deadline=self._deadline, wait_for_lock=True)
        return tuple(item for item in snapshot.muxes if item.service.product_id == self._product)

    async def _run_once(self) -> ManagedMuxProbeSnapshotV1:
        original = await _settled_native(self._snapshot)
        results = {item.name: ManagedMuxProbeResultV1(item, "unknown") for item in original}
        groups: dict[str, list[ManagedMuxObservationV1]] = {}
        for item in original:
            if item.cleanly_stopped:
                results[item.name] = ManagedMuxProbeResultV1(item, "recorded_ineligible")
            elif (item.instance is not None and item.recorded_phase is ManagedHandoffPhaseV1.COMMITTED
                  and not item.stop_requested):
                groups.setdefault(item.service.service_id, []).append(item)
        for group in groups.values():
            if self._closing or monotonic() >= self._deadline:
                break
            try:
                await self._probe_group(group, results)
            except Exception:
                # A failed service admission proves neither absence nor offline.
                for item in group:
                    results[item.name] = ManagedMuxProbeResultV1(item, "unknown")
            finally:
                # Cleanup errors escape; no values can authorize selection while
                # a native owner remains unsettled. Original fields retain debt.
                await self._settle_group()
        unchanged = False
        if not self._closing and monotonic() < self._deadline:
            try:
                current = await _settled_native(self._snapshot)
                unchanged = tuple(map(_candidate_key, current)) == tuple(map(_candidate_key, original))
            except Exception:
                pass
        return ManagedMuxProbeSnapshotV1(tuple(results[item.name] for item in original), unchanged)

    async def _probe_group(self, group: list[ManagedMuxObservationV1],
                           results: dict[str, ManagedMuxProbeResultV1]) -> None:
        first = group[0]
        assert first.instance is not None
        paths = resolve_managed_service_paths(self._namespace, first.service, runtime_root=self._runtime)
        self._journal = ManagedServiceJournalV1(self._registry, self._namespace, first.service,
                                                Path(paths.lifecycle), defer_open=True)
        await _settled_native(partial(self._journal.open, deadline=self._deadline, wait_for_lock=True))
        if self._closing:
            return
        _check_deadline(self._deadline)
        self._connection = ManagedConnectionLeaseV1(self._journal, self._namespace, first.service,
            first.instance, runtime_root=self._runtime, endpoint=self._endpoint)
        await self._connection.prepare(deadline=self._deadline)
        if self._connection.application_id != self._application:
            raise ManagedStorageError("conflict")
        manager = ManagedMuxManagerV1(self._registry, self._journal, self._namespace,
            first.service, first.instance, application_id=self._application)
        for item in group:
            if self._closing or monotonic() >= self._deadline:
                break
            try:
                inspection = await _settled_native(partial(manager.inspect_mux, item.reservation,
                    deadline=self._deadline, wait_for_lock=True))
                if self._closing:
                    break
                mux_id = inspection.creation.mux_space_id
                _check_deadline(self._deadline)
                async with asyncio.timeout(max(0, self._deadline - monotonic())):
                    try:
                        mux = await self._connection.client.read_mux(MuxReadV1(MuxSelectorV1(mux_space_id=mux_id)))
                    except AppServiceError as error:
                        if error.code is not AppErrorCodeV1.NOT_FOUND:
                            raise
                        results[item.name] = ManagedMuxProbeResultV1(item, "not_present", mux_id)
                    else:
                        if type(mux) is not MuxSpaceV1 or mux.mux_space_id != mux_id or mux.name != item.name:
                            raise ManagedStorageError("conflict")
                        results[item.name] = ManagedMuxProbeResultV1(item, "authenticated_present", mux_id)
            except Exception:
                results[item.name] = ManagedMuxProbeResultV1(item, "unknown")

    async def _settle_group(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        if self._journal is not None:
            await _settled_native(self._journal.close)
            self._journal = None

    async def close(self) -> None:
        self._bind_loop()
        self._closing = True
        if self._settled:
            return
        if self._close_deadline is None:
            self._close_deadline = monotonic() + 5
        if self._close_task is None or (self._close_task.done() and (
            self._close_task.cancelled() or self._close_task.exception() is not None
        )):
            _check_deadline(self._close_deadline)
            self._close_task = _spawn(self._close_once())
        if self._close_task.done():
            await asyncio.shield(self._close_task)
            return
        async with asyncio.timeout(max(0, self._close_deadline - monotonic())):
            await asyncio.shield(self._close_task)

    async def _close_once(self) -> None:
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
        await self._settle_group()
        self._settled = True

    def close_unstarted(self) -> None:
        """Settle a never-entered operation when Runner admission itself failed."""
        if self._loop is not None or self._task is not None or self._journal is not None or self._connection is not None:
            raise ManagedStorageError("busy")
        self._closing = self._settled = True
