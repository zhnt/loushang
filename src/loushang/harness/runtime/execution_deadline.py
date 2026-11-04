"""Monotonic execution and optional phase deadlines, without an execution driver.

The caller retains its task, timeout context, stop-result mapping and settlement.
This scope never extends a deadline or owns a Session or domain state.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable


class ExecutionDeadline:
    def __init__(self, *, clock: Callable[[], float], cancel_requested: Callable[[], bool],
                 total_reason: str, phase_reason: str, phase_active: bool = False) -> None:
        self._clock = clock
        self.cancel_requested = cancel_requested
        self._total_deadline_reason = total_reason
        self._phase_deadline_reason = phase_reason
        self.deadline: float | None = None
        self.phase_deadline: float | None = None
        self.phase_active = phase_active
        self.cancelled = False
        self.reason = "not_started"
        self._stop_reason: str | None = None
        self._timer: asyncio.Timeout | None = None

    def start_deadlines(self, total_seconds: float, reserve_seconds: float = 0) -> None:
        self.deadline = self._clock() + total_seconds
        self.phase_deadline = self.deadline - reserve_seconds

    def _deadline_reason(self) -> str | None:
        now = self._clock()
        if self.deadline is not None and now >= self.deadline:
            return self._total_deadline_reason
        if self.phase_active and self.phase_deadline is not None and now >= self.phase_deadline:
            return self._phase_deadline_reason
        return None

    def checkpoint(self) -> None:
        if self.cancelled or self.cancel_requested():
            raise asyncio.CancelledError
        reason = self._deadline_reason()
        if reason is not None:
            self._stop_reason = self._stop_reason or reason
            self.reason = self._stop_reason
            raise TimeoutError(reason)

    def begin_closeout(self) -> None:
        self.checkpoint()
        self.phase_active = False
        if self._timer is not None:
            assert self.deadline is not None
            self._timer.reschedule(asyncio.get_running_loop().time() + max(0, self.deadline - self._clock()))
