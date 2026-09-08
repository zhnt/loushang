"""Bounded client-local discovery views; Product owns all actual directory IO."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from secrets import token_hex
from threading import Event

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionListResultV1,
    SessionListV1,
)

from .discovery_ports import (
    HostedSessionDiscoveryBindingV1,
    HostedSessionDiscoveryScopeV1,
    HostedSessionDiscoverySnapshotV1,
)


@dataclass(slots=True)
class _Snapshot:
    value: HostedSessionDiscoverySnapshotV1
    snapshot_id: str
    expires: float
    offsets: dict[int, str] = field(default_factory=dict)
    tokens: dict[str, int] = field(default_factory=dict)


class SessionDiscoveryOwnerV1:
    """One application's scan slots and owned semantic discovery clients."""

    def __init__(
        self, binding: HostedSessionDiscoveryBindingV1, *, close_timeout: float = 10,
        scan_timeout: float = 5, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(binding) is not HostedSessionDiscoveryBindingV1:
            raise TypeError("invalid discovery binding")
        for value, maximum in ((close_timeout, 60), (scan_timeout, 5)):
            if type(value) not in (float, int) or not 0 < value <= maximum:
                raise ValueError("invalid discovery budget")
        self.binding = binding
        self._clock, self._timeout, self._scan_timeout = clock, close_timeout, scan_timeout
        self._views: set[SessionDiscoveryViewV1] = set()
        self._scans: dict[asyncio.Task[HostedSessionDiscoverySnapshotV1], Event] = {}
        self._pending = 0
        self._closed = self._scoped = False
        self._legacy: SessionDiscoveryViewV1 | None = None

    @property
    def pending_count(self) -> int:
        return self._pending

    @property
    def legacy_client(self) -> SessionDiscoveryViewV1 | None:
        if self._scoped or self._closed:
            return None
        if self._legacy is None:
            self._legacy = self.open_view()
        return self._legacy

    def select_scoped(self) -> None:
        self._scoped = True
        if self._legacy is not None:
            self._legacy.fence()
            self._legacy = None

    def open_view(self) -> SessionDiscoveryViewV1:
        if self._closed:
            raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)
        if len(self._views) >= 8:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        view = SessionDiscoveryViewV1(self)
        self._views.add(view)
        return view

    def fence(self) -> None:
        self._closed = True
        for view in tuple(self._views):
            view.fence()
        for stop in self._scans.values():
            stop.set()

    async def close(self) -> None:
        self.fence()
        if self._scans:
            _, pending = await asyncio.wait(set(self._scans), timeout=self._timeout)
            if pending:
                # Do not cancel wrappers or pretend actual Product IO has ended.
                raise AppServiceError(AppErrorCodeV1.CLEANUP_INCOMPLETE)

    def _start(
        self, view: SessionDiscoveryViewV1, scope: HostedSessionDiscoveryScopeV1,
    ) -> tuple[asyncio.Task[HostedSessionDiscoverySnapshotV1], Event]:
        if self._pending >= 2 or view._busy:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        self._pending += 1
        view._busy = True
        stop = Event()
        view._stop = stop
        operation = self._read(scope, stop)
        try:
            task = asyncio.create_task(operation)
        except BaseException:
            operation.close()
            self._pending -= 1
            view._busy = False
            view._stop = None
            raise
        self._scans[task] = stop

        def completed(done: asyncio.Task[HostedSessionDiscoverySnapshotV1]) -> None:
            if not done.cancelled():
                done.exception()
            self._scans.pop(done, None)
            self._pending -= 1
            view._busy = False
            view._stop = None

        task.add_done_callback(completed)
        return task, stop

    async def _read(
        self, scope: HostedSessionDiscoveryScopeV1, stop: Event,
    ) -> HostedSessionDiscoverySnapshotV1:
        try:
            value = await self.binding.port.discover_sessions(scope, stop=stop.is_set)
            if type(value) is not HostedSessionDiscoverySnapshotV1 or value.scope != scope:
                raise ValueError("invalid Product discovery snapshot")
            return value
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE) from None


class SessionDiscoveryViewV1:
    """Borrowed optional client, fenced with its semantic client scope."""

    def __init__(self, owner: SessionDiscoveryOwnerV1) -> None:
        self._owner = owner
        self._snapshots: dict[HostedSessionDiscoveryScopeV1, _Snapshot] = {}
        self._epochs: dict[HostedSessionDiscoveryScopeV1, int] = {}
        self._closed = self._busy = False
        self._stop: Event | None = None

    def fence(self) -> None:
        self._closed = True
        self._snapshots.clear()
        self._owner._views.discard(self)
        if self._stop is not None:
            self._stop.set()

    def _require_open(self) -> None:
        if self._closed or self._owner._closed:
            raise AppServiceError(AppErrorCodeV1.SERVICE_CLOSED)

    async def list_sessions(self, request: SessionListV1) -> SessionListResultV1:
        self._require_open()
        if type(request) is not SessionListV1:
            raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
        scope = HostedSessionDiscoveryScopeV1(
            request.product_id, request.scope, request.scope_fingerprint
        )
        if scope not in self._owner.binding.scopes:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        if request.continuation is not None:
            snapshot = self._snapshots.get(scope)
            if snapshot is None or snapshot.expires <= self._owner._clock():
                self._snapshots.pop(scope, None)
                raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
            offset = snapshot.tokens.get(request.continuation)
            if offset is None:
                raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
        else:
            task, stop = self._owner._start(self, scope)
            epoch = self._epochs.get(scope, 0) + 1
            self._epochs[scope] = epoch
            self._snapshots.pop(scope, None)  # Explicit refresh invalidates that scope.
            try:
                done, _ = await asyncio.wait({task}, timeout=self._owner._scan_timeout)
                if not done:
                    stop.set()
                    raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
                value = task.result()
            except asyncio.CancelledError:
                stop.set()
                raise
            self._require_open()
            if self._epochs.get(scope) != epoch:
                raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
            if stop.is_set():
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            snapshot = _Snapshot(value, token_hex(16), self._owner._clock() + 60)
            self._snapshots[scope] = snapshot
            offset = 0
        end = min(len(snapshot.value.candidates), offset + request.limit)
        continuation = None
        if end < len(snapshot.value.candidates):
            continuation = snapshot.offsets.get(end)
            if continuation is None:
                continuation = token_hex(16)
                snapshot.offsets[end] = continuation
                snapshot.tokens[continuation] = end
        value = snapshot.value
        return SessionListResultV1(
            scope.product_id, scope.scope, scope.scope_fingerprint,
            snapshot.snapshot_id, value.candidates[offset:end], value.complete,
            continuation, value.omitted_count, value.omitted_count_exact,
        )
