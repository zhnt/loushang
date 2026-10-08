"""Bounded, content-free trace ingress; no IO, scheduling or resource ownership.

The original child diagnostics owner polls this buffer. Producers never enqueue
loop callbacks, so contention cannot build an unbounded notification backlog.
Dequeuing is not a persistence receipt; the writer must recheck the deadline.
"""

from __future__ import annotations

import json
import math
from collections import deque
from collections.abc import Callable
from threading import Lock
from time import monotonic

from loushang.foundation.observability.records import DebugEventRecord, ProblemRecord

from .contracts import _HEX32, ManagedContractError, _match

_CODES = frozenset({"startup_failed", "application_failed", "cleanup_incomplete"})
_MAX_COUNT = 2**31 - 1


class ManagedTraceBuffer:
    """Borrowed Foundation sink with bounded, nonblocking producer admission.

    Only aggregate turn timing and closed managed error codes are projected.
    Arbitrary record fields are neither copied nor recursively sanitized.
    Dropped counts exclude lock contention and are therefore lower bounds.
    """

    def __init__(self, instance_id: str, deadline: float, *,
                 clock: Callable[[], float] = monotonic,
                 max_records: int = 128, max_bytes: int = 65536) -> None:
        _match(instance_id, _HEX32)
        if (type(deadline) not in (int, float) or not 0 <= deadline <= 2**53
                or not math.isfinite(deadline)
                or type(max_records) is not int or not 1 <= max_records <= 128
                or type(max_bytes) is not int or not 512 <= max_bytes <= 65536):
            raise ManagedContractError()
        self._instance_id, self._deadline = instance_id, deadline
        self._clock = clock
        self._max_records, self._max_bytes = max_records, max_bytes
        self._lock = Lock()
        self._queue: deque[bytes] = deque()
        self._bytes = self._dropped = 0
        self._closed = False

    @property
    def deadline(self) -> float:
        return self._deadline

    def write_problem(self, record: ProblemRecord) -> None:
        if type(record) is not ProblemRecord:
            return
        code = record.code
        if type(code) is str and len(code) <= 32 and code in _CODES:
            self._offer({"event": "problem", "code": code})

    def write_debug_event(self, record: DebugEventRecord) -> None:
        if (type(record) is not DebugEventRecord
                or type(record.scope) is not str or record.scope != "turn.start.performance"
                or type(record.name) is not str or record.name != "turn"
                or type(record.data) is not dict):
            return
        # Fixed lookups only: no iteration/copy of provider metadata, arbitrary
        # nested milestones, Session IDs, prompt content or mutable objects.
        value: dict[str, str | int | float] = {"event": "turn"}
        for key in ("total_ms", "startup_ms", "local_ready_ms"):
            duration = record.data.get(key)
            if ((type(duration) is int or type(duration) is float) and 0 <= duration <= 86400000
                    and math.isfinite(duration)):
                value[key] = duration
        if len(value) > 1:
            self._offer(value)

    def _offer(self, value: dict[str, str | int | float]) -> None:
        # Projection above is a fixed amount of pure work. Never block a caller
        # on a native worker, file lock, queue capacity or another producer.
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._closed or self._clock() >= self.deadline:
                self._drop()
                return
            frame = (json.dumps({"v": 1, "instanceId": self._instance_id, **value},
                                separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
            if (len(frame) > 512 or len(self._queue) >= self._max_records
                    or self._bytes + len(frame) > self._max_bytes):
                self._drop()
                return
            self._queue.append(frame)
            self._bytes += len(frame)
        finally:
            self._lock.release()

    def _drop(self, count: int = 1) -> None:
        self._dropped = min(_MAX_COUNT, self._dropped + count)

    def take(self) -> bytes | None:
        """Take at most one frame; the original writer checks expiry again."""
        if not self._lock.acquire(blocking=False):
            return None
        try:
            if self._clock() >= self.deadline:
                self._closed = True
                self._drop(len(self._queue))
                self._queue.clear()
                self._bytes = 0
            if not self._queue:
                return None
            frame = self._queue.popleft()
            self._bytes -= len(frame)
            return frame
        finally:
            self._lock.release()

    def fence(self) -> None:
        """Stop producers; admitted frames remain available until expiry."""
        with self._lock:
            self._closed = True

    def snapshot(self) -> tuple[int, int, int]:
        """Bounded diagnostic counts: queued records, bytes, dropped lower bound."""
        with self._lock:
            return len(self._queue), self._bytes, self._dropped

    def discard(self) -> None:
        """Fence ingress and discard only frames still owned by this queue."""
        with self._lock:
            self._closed = True
            self._drop(len(self._queue))
            self._queue.clear()
            self._bytes = 0
