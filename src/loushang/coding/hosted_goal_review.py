"""Bounded user-facing projection of the original Coding task review basis."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from hashlib import sha256
from hmac import compare_digest
from typing import TYPE_CHECKING

from loushang.appserver.execution.model import (
    InteractiveGoalReviewSubmissionV1,
    InteractiveGoalReviewV1,
    is_review_path,
)
from loushang.harnesswork.goal import GoalError

if TYPE_CHECKING:
    from .adapters.interactive_goal import InteractiveGoal


def _digest(identity: str) -> str:
    return sha256(identity.encode()).hexdigest()


async def summarize_review(owner: InteractiveGoal, goal_id: str) -> InteractiveGoalReviewV1:
    identity = await owner.review_basis(goal_id)
    snapshot = json.loads(identity)["inventory"]
    state = owner.controller.query(goal_id)
    initial = state.metadata["initial_inventory"]
    if not isinstance(initial, Mapping):
        raise GoalError("Goal creation inventory unavailable")
    changed = [path for path in sorted(snapshot.keys() | initial.keys()) if snapshot.get(path) != initial.get(path)]
    names = tuple(path for path in changed if is_review_path(path))[:100]
    count, satisfied = owner.review_check_status(goal_id, snapshot)
    return InteractiveGoalReviewV1(
        goal_id, state.revision, state.epoch, _digest(identity), names,
        len(changed) != len(names), count, satisfied,
    )


async def execute_review(owner: InteractiveGoal, command: InteractiveGoalReviewSubmissionV1) -> None:
    goal_id = command.goal_id
    try:
        identity = await owner.review_basis(goal_id)
        if not compare_digest(_digest(identity), command.review_token):
            raise GoalError("review candidate changed; review again")
        if command.decision == "accept":
            receipt = await owner.accept(goal_id, identity)
        else:
            receipt = await owner.review(goal_id, identity, approved=False, reason=command.reason)
    except asyncio.CancelledError:
        await owner.controller.request_cancel(goal_id)
        raise
    facts = owner.controller.facts()
    operations = {batch.operation_id for batch in facts.batches if batch.command_id == receipt.id}
    if not any(run.operation_id in operations and run.status == "completed" for run in facts.runs):
        raise GoalError("review Work did not finish")
