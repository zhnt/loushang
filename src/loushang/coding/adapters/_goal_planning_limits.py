"""Coding-owned model-call allowance at the original stream injection seam.

This is not a transport, scheduler or usage ledger. It delegates unchanged to
the standard AI stream and counts logical invocations within an admitted Work.
"""

from __future__ import annotations

from loushang.agent.model_transport import prepared_request_conformant
from loushang.ai import CallOptions, RetryOptions, stream
from loushang.harnesswork.goal import GoalError

from ._goal_proposal import LIMITS


class PlanningCallLimit(GoalError):
    pass


class PlanningCallAllowance:
    def __init__(self) -> None:
        self.operation_id: str | None = None
        self.phase: str | None = None
        self.calls = 0
        self.failed = False
        self.fenced = False
        # Decorating the bound callable itself is unsupported; decorate the
        # closure given to the SDK, preserving its existing conformance seam.
        self.stream = prepared_request_conformant(self._delegate())

    def enter(self, operation_id: str, phase: str) -> None:
        if (
            not operation_id
            or self.fenced
            or self.phase is not None
            or phase not in {"planning", "repair"}
        ):
            raise PlanningCallLimit("model phase unavailable")
        if operation_id != self.operation_id:
            self.operation_id, self.calls, self.failed = operation_id, 0, False
        elif self.failed:
            raise PlanningCallLimit("model Work allowance already failed")
        self.phase = phase

    def leave(self, operation_id: str) -> None:
        if self.operation_id != operation_id:
            self.fenced = True
            raise PlanningCallLimit("model phase ownership mismatch")
        self.phase = None
        # Preserve calls/failed across Method steps and cancellation settlement.

    def _delegate(self):
        async def bounded_stream(model, context, options=None):
            if self.fenced or self.phase is None or self.failed:
                self.failed = True
                raise PlanningCallLimit("model call outside an admitted phase")
            maximum = LIMITS[f"{self.phase}_calls"]
            if self.calls >= maximum:
                self.failed = True
                raise PlanningCallLimit("model logical-call allowance exhausted")
            if options is not None and not isinstance(options, CallOptions):
                self.failed = True
                raise PlanningCallLimit("unrecognized model call options")
            retry = options.retry if options is not None else None
            if retry is not None and (
                not isinstance(retry, RetryOptions)
                or retry.max_attempts > LIMITS["provider_attempts"]
            ):
                self.failed = True
                raise PlanningCallLimit("provider retry allowance unsupported")
            # No suspension occurs before consuming the allowance. Pass through
            # the exact prepared committer, cancellation authority and response.
            self.calls += 1
            try:
                return await stream(model, context, options)
            except BaseException:
                self.failed = True
                raise

        return bounded_stream
