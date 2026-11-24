"""Coding run and review policy for the AppHost Goal command owner."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loushang.apphost.integrations._goal_commands import (
    HostedGoalCommands as _HostedGoalCommands,
)
from loushang.appserver.execution.goal_model import (
    InteractiveGoalCommandV1,
    InteractiveGoalReviewSubmissionV1,
)
from loushang.coding.hosted.goal_review import execute_review
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.integrations.goal_run import run_goal

if TYPE_CHECKING:
    from loushang.coding.adapters.goal import CodingGoal


async def _execute_goal_command(
    owner: CodingGoal,
    command: InteractiveGoalCommandV1 | InteractiveGoalReviewSubmissionV1,
) -> None:
    if isinstance(command, InteractiveGoalReviewSubmissionV1):
        from loushang.coding.adapters.interactive_goal import InteractiveGoal

        if not isinstance(owner, InteractiveGoal):
            raise GoalError("current Goal cannot be reviewed")
        await execute_review(owner, command)
    else:
        await run_goal(
            owner, command.goal_id, steps=1 if command.action == "step" else 24, seconds=600
        )


class HostedGoalCommands(_HostedGoalCommands["CodingGoal"]):
    def __init__(self) -> None:
        super().__init__(
            execute=_execute_goal_command, error=GoalError, task_name="coding-hosted-goal-command"
        )
