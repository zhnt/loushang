"""Optional composite snapshot proof and bounded two-stream attachment buffer.

The caller subscribes the buffer to both sources before capture and validates
membership/authority in read_view. Product owns its coherent content projection.
This module does not allocate Product cursors or mutate any legacy attachment.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Protocol

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionIdentityV1,
)

from .execution_contract import (
    CompositeExecutionSnapshotV1,
    ExecutionBindingViewV1,
    ExecutionContentEventV1,
    ExecutionSourceSnapshotV1,
    ExecutionStatusV1,
    ExecutionUpdateV1,
)

ExecutionDeliveryV1 = ExecutionContentEventV1 | ExecutionUpdateV1


class ExecutionSnapshotPortV1(Protocol):
    """The read facet of the optional Product execution port."""

    async def snapshot_execution(self) -> ExecutionSourceSnapshotV1: ...


class ExecutionSnapshotBufferV1:
    def __init__(
        self,
        binding: object,
        identity: SessionIdentityV1,
        *,
        capacity: int = 256,
    ) -> None:
        if type(identity) is not SessionIdentityV1:
            raise TypeError("invalid source identity")
        if type(capacity) is not int or not 1 <= capacity <= 1024:
            raise ValueError("invalid execution buffer capacity")
        self.binding = binding
        self.identity = identity
        self._capacity = capacity
        self._events: deque[ExecutionDeliveryV1] = deque()
        self._watermarks: tuple[int, int] | None = None
        self._invalid = False

    def push(self, event: ExecutionDeliveryV1) -> None:
        """Nonblocking delivery; overflow or malformed stream requires a new cut."""
        if self._invalid:
            return
        if type(event) not in (ExecutionContentEventV1, ExecutionUpdateV1):
            self.invalidate()
            return
        if isinstance(event, ExecutionContentEventV1) and (
            event.source.session_id != self.identity.session_id
        ):
            self.invalidate()
            return
        if self._watermarks is not None:
            content, metadata = self._watermarks
            if isinstance(event, ExecutionContentEventV1):
                if event.source.cursor <= content:
                    return
                if event.source.cursor != content + 1:
                    self.invalidate()
                    return
                content = event.source.cursor
            else:
                if event.revision <= metadata:
                    return
                if event.revision != metadata + 1:
                    self.invalidate()
                    return
                metadata = event.revision
            self._watermarks = content, metadata
        if len(self._events) >= self._capacity:
            self.invalidate()
            return
        self._events.append(event)

    def invalidate(self) -> None:
        self._invalid = True
        self._events.clear()

    def require_current(self, view: ExecutionBindingViewV1) -> None:
        if view.binding is not self.binding or view.identity != self.identity:
            raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)
        if self._invalid:
            raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)

    def activate(self, snapshot: CompositeExecutionSnapshotV1) -> None:
        self.require_current(snapshot.executions)
        if self._watermarks is not None:
            raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
        events = tuple(self._events)
        self._events.clear()
        self._watermarks = snapshot.source.source.cursor, snapshot.executions.revision
        for event in events:
            self.push(event)
        self.require_current(snapshot.executions)

    def read(self) -> tuple[ExecutionDeliveryV1, ...]:
        if self._invalid or self._watermarks is None:
            raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
        events = tuple(self._events)
        self._events.clear()
        return events


def _matches(view: ExecutionBindingViewV1, source: ExecutionSourceSnapshotV1) -> bool:
    active = view.active
    if active is not None and active.status is ExecutionStatusV1.RUNNING:
        return (
            source.observation.execution_id == active.execution_id
            and source.observation.status is ExecutionStatusV1.RUNNING
        )
    # Initial idle, accepted B after completed A, and service-only B outcomes
    # all match retained Q, not every historical/displayed terminal summary.
    return source.observation == view.quiescent


async def capture_execution_snapshot(
    port: ExecutionSnapshotPortV1,
    read_view: Callable[[], ExecutionBindingViewV1],
    buffer: ExecutionSnapshotBufferV1,
    *,
    attempts: int = 3,
) -> CompositeExecutionSnapshotV1:
    """Install a cut only while binding, authority and registry view stay stable.

    read_view must be synchronous, check authority, and return immutable state.
    Its revision includes every active/Q/latest change; no lock spans Product IO.
    On failure the caller discards/unsubscribes the reserved buffer, never reuses
    an old attachment. Content lifecycle callbacks are not suppressed by this
    delivery buffer; application settlement is a separate subscriber/owner.
    """
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise ValueError("invalid execution snapshot retry bound")
    try:
        for _ in range(attempts):
            before = read_view()
            buffer.require_current(before)
            try:
                source = await port.snapshot_execution()
            except AppServiceError:
                raise
            except Exception:
                raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE) from None
            if type(source) is not ExecutionSourceSnapshotV1:
                raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
            after = read_view()
            buffer.require_current(after)
            if source.source.identity != after.identity:
                raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
            if before.revision != after.revision or not _matches(after, source):
                continue
            # Catch a misbehaving provider that mutates state without revision.
            if before != after:
                raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
            result = CompositeExecutionSnapshotV1(source, after)
            buffer.activate(result)
            return result
        raise AppServiceError(AppErrorCodeV1.SNAPSHOT_REQUIRED)
    except BaseException:
        buffer.invalidate()
        raise
