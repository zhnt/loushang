"""Cold projection of an authorized Coding Session's Goal and Work journals."""

from __future__ import annotations

from pathlib import Path
from typing import cast, get_args

from loushang.appserver.execution.model import (
    ExecutionGoalStatusV1,
    GoalRecoveryHistoryReasonV1,
    GoalRecoveryUnavailableReasonV1,
    InteractiveGoalRecoveryV1,
)
from loushang.coding.adapters._goal_store import _GOAL_STORE_OWNER_ID, goal_journal_path
from loushang.harnesswork.integrations.goal_store import (
    DetachedGoalWorkFacts,
    observe_detached_goal_work,
)

_MAX_JOURNAL_BYTES = 64 * 1024 * 1024


def unavailable_recovery(reason: GoalRecoveryUnavailableReasonV1) -> InteractiveGoalRecoveryV1:
    return InteractiveGoalRecoveryV1("unavailable", reason, execution_unresolved=True)


def _project_recovery(facts: DetachedGoalWorkFacts) -> InteractiveGoalRecoveryV1:
    goal = facts.goal
    reason = (
        cast(GoalRecoveryHistoryReasonV1, goal.reason)
        if goal.reason in get_args(GoalRecoveryHistoryReasonV1)
        else "other"
    )
    counts = facts.run_counts
    return InteractiveGoalRecoveryV1(
        "present", reason, goal.id, cast(ExecutionGoalStatusV1, goal.status), goal.revision,
        goal.epoch, facts.batch_count, counts["completed"], counts["failed"], counts["cancelled"],
        counts["orphaned"], facts.execution_unresolved,
    )


def read_interactive_goal_recovery(directory: Path, session_id: str) -> InteractiveGoalRecoveryV1:
    """Read only the original journal paths supplied by the authorized catalog."""
    result = observe_detached_goal_work(
        directory, session_id, path_for=goal_journal_path,
        owner_id=_GOAL_STORE_OWNER_ID, max_bytes=_MAX_JOURNAL_BYTES, project=_project_recovery,
    )
    if isinstance(result, str):
        if result == "no_goal":
            return InteractiveGoalRecoveryV1("absent", result)
        return unavailable_recovery(result)
    return result
