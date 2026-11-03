"""Coding-owned model-call allowance at the original stream injection seam.

This is not a transport, scheduler or usage ledger. It delegates unchanged to
the standard AI stream and counts logical invocations within an admitted Work.
"""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType

from loushang.agent.model_transport import prepared_request_conformant
from loushang.ai import stream
from loushang.harness.session.call_allowance import ModelCallAllowance
from loushang.harnesswork.goal import GoalError

from ._goal_proposal import LIMITS


class PlanningCallLimit(GoalError):
    pass


class PlanningCallAllowance(ModelCallAllowance):
    """Compatibility profile over the shared operation call limiter."""

    def __init__(self, *, total_limit: int | None = None, max_output_tokens: int | None = None) -> None:
        @prepared_request_conformant
        async def delegate(model, context, options=None):
            # Resolve the original module binding at call time, as before.
            return await stream(model, context, options)

        self._initialize(delegate, total_limit=total_limit, max_output_tokens=max_output_tokens)

    @classmethod
    def from_stream(cls, delegate, *, total_limit=None, max_output_tokens=None, checkpoint=None):
        """Bind the existing Session transport without replacing its authority."""
        from loushang.ai.api import stream as standard_stream

        if delegate is standard_stream:
            @prepared_request_conformant
            async def standard_delegate(model, context, options=None):
                return await delegate(model, context, options)

            transport = standard_delegate
        else:
            transport = delegate
        owner = cls.__new__(cls)
        owner._initialize(transport, total_limit=total_limit, max_output_tokens=max_output_tokens)
        owner._checkpoint = checkpoint
        return owner

    def _initialize(self, delegate, *, total_limit, max_output_tokens):
        super().__init__(phase_limits={name: LIMITS[f"{name}_calls"] for name in ("planning", "repair")},
                         provider_attempts=LIMITS["provider_attempts"], delegate=delegate,
                         total_limit=total_limit, max_output_tokens=max_output_tokens,
                         retry_attempts=1 if max_output_tokens is not None else None,
                         error_type=PlanningCallLimit)
        self.hosted_limits = None
        self._budget_snapshot: Callable[[], dict] | None = None

    def _error(self, message: str) -> Exception:
        return PlanningCallLimit(message.replace("model operation allowance already failed",
                                                 "model Work allowance already failed"))

    def bind_hosted_budget(self, limits, snapshot, checkpoint):
        if self.hosted_limits is not None or self.total_calls:
            raise PlanningCallLimit("hosted budget already bound")
        self.hosted_limits = MappingProxyType(dict(limits))
        self._budget_snapshot = snapshot
        prior_checkpoint = self._checkpoint
        if prior_checkpoint is None:
            self._checkpoint = checkpoint
        else:
            def combined_checkpoint():
                prior_checkpoint()
                checkpoint()
            self._checkpoint = combined_checkpoint

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
