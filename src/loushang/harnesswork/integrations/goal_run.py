"""A finite invocation of the original advance port, without another scheduler."""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from loushang.harness.runtime.execution_deadline import ExecutionDeadline


async def run_goal(owner, goal_id: str, *, steps: int = 24, seconds: float = 600):
    """Keep per-Goal allowances; each explicit call has its own time window."""
    deadline = ExecutionDeadline(
        clock=time.monotonic,
        cancel_requested=lambda: False,
        total_reason="goal_run_deadline",
        phase_reason="goal_run_deadline",
    )
    deadline.start_deadlines(seconds)
    try:
        async with asyncio.timeout(seconds):
            for _ in range(steps):
                deadline.checkpoint()
                state = owner.controller.query(goal_id)
                if state.status != "active":
                    break
                result = await owner.advance(
                    goal_id,
                    command_id=f"run-{uuid4().hex}",
                    revision=state.revision,
                    epoch=state.epoch,
                )
                if result.outcome != "work_finished":
                    break
    except (TimeoutError, asyncio.CancelledError):
        state = owner.controller.query(goal_id)
        if state.status == "active" and not owner.controller.fenced:
            owner.controller.control(
                goal_id,
                "pause",
                command_id=f"stop-{uuid4().hex}",
                revision=state.revision,
                epoch=state.epoch,
                reason="run_interrupted",
            )
        await owner.controller.request_cancel(goal_id)
        raise
    return owner.controller.query(goal_id)
