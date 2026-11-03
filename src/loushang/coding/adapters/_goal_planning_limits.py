"""Coding-owned model-call allowance at the original stream injection seam.

This is not a transport, scheduler or usage ledger. It delegates unchanged to
the standard AI stream and counts logical invocations within an admitted Work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from types import MappingProxyType

from loushang.agent.model_transport import prepared_request_conformant
from loushang.ai import CallOptions, RetryOptions, stream
from loushang.harnesswork.goal import GoalError

from ._goal_proposal import LIMITS


class PlanningCallLimit(GoalError):
    pass


class PlanningCallAllowance:
    def __init__(self, *, total_limit: int | None = None, max_output_tokens: int | None = None) -> None:
        for value in (total_limit, max_output_tokens):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("positive model allowance required")
        self.total_limit, self.max_output_tokens = total_limit, max_output_tokens
        self.total_calls = 0
        self.operation_id: str | None = None
        self.phase: str | None = None
        self.calls = 0
        self.failed = False
        self.fenced = False
        self.hosted_limits = None
        self._budget_snapshot: Callable[[], dict] | None = None
        self._checkpoint: Callable[[], None] | None = None
        # Decorating the bound callable itself is unsupported; decorate the
        # closure given to the SDK, preserving its existing conformance seam.
        self.stream = prepared_request_conformant(self._delegate())

    def bind_hosted_budget(self, limits, snapshot, checkpoint):
        if self.hosted_limits is not None or self.total_calls:
            raise PlanningCallLimit("hosted budget already bound")
        self.hosted_limits = MappingProxyType(dict(limits))
        self._budget_snapshot, self._checkpoint = snapshot, checkpoint

    def model_budget(self):
        if self.hosted_limits is None:
            return {}
        assert self._budget_snapshot is not None
        return {"hosted_budget": {
            **self.hosted_limits, **self._budget_snapshot(),
            "total_calls": self.total_calls,
            "model_calls_remaining_including_next_call": max(0, self.total_limit - self.total_calls),
            "sample": "batch_preparation_including_next_call",
        }}

    def model_limits(self, profile):
        if self.hosted_limits is None:
            return profile
        result = dict(profile)
        for key in ("repair_calls", "planning_calls"):
            result[key] = min(result[key], self.total_limit)
        result["provider_attempts"] = 1
        result["work_intents"] = min(result["work_intents"], self.hosted_limits["max_advances"])
        return result

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
            if self._checkpoint is not None:
                self._checkpoint()
            if self.fenced or self.phase is None or self.failed:
                self.failed = True
                raise PlanningCallLimit("model call outside an admitted phase")
            if self.total_limit is not None and self.total_calls >= self.total_limit:
                self.failed = self.fenced = True
                raise PlanningCallLimit("owner model-call allowance exhausted")
            maximum = LIMITS[f"{self.phase}_calls"]
            if self.calls >= maximum:
                self.failed = True
                raise PlanningCallLimit("model logical-call allowance exhausted")
            if options is not None and not isinstance(options, CallOptions):
                self.failed = True
                raise PlanningCallLimit("unrecognized model call options")
            if self.max_output_tokens is not None:
                options = options or CallOptions()
                output = options.max_output_tokens
                options = replace(options, max_output_tokens=min(output, self.max_output_tokens)
                                  if output is not None else self.max_output_tokens,
                                  retry=RetryOptions(max_attempts=1))
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
            self.total_calls += 1
            try:
                return await stream(model, context, options)
            except BaseException:
                self.failed = True
                raise

        return bounded_stream
