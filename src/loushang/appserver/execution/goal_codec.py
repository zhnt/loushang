"""Closed field maps for Goal execution values."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypedDict, cast

from ..protocol.codec import _string
from .goal_model import (
    ExecutionGoalBatchV1,
    ExecutionGoalProgressV1,
    InteractiveGoalCommandV1,
    InteractiveGoalCommandViewV1,
    InteractiveGoalRecoveryV1,
    InteractiveGoalReviewSubmissionV1,
    InteractiveGoalReviewV1,
    InteractiveGoalViewV1,
)
from .operation import ExecutionOperationV1

GOAL_FIELDS: dict[type, tuple[str, ...]] = {
    ExecutionGoalBatchV1: (
        "batch_id", "work_status", "recording_available", "cancellation_status", "observation_unavailable",
    ),
    ExecutionGoalProgressV1: (
        "execution_id", "presence", "goal_id", "status", "reason_code", "validity",
        "execution_unresolved", "advances", "model_calls", "batch_count", "batches",
    ),
    InteractiveGoalCommandV1: ("goal_id", "command_id", "action"),
    InteractiveGoalCommandViewV1: ("command_id", "action", "status"),
    InteractiveGoalRecoveryV1: (
        "presence", "reason_code", "goal_id", "goal_status", "revision", "epoch",
        "batch_count", "completed_count", "failed_count", "cancelled_count", "orphaned_count",
        "execution_unresolved", "read_only",
    ),
    InteractiveGoalReviewSubmissionV1: ("goal_id", "review_token", "command_id", "decision", "reason"),
    InteractiveGoalReviewV1: ("goal_id", "revision", "epoch", "review_token", "changed_files",
                              "files_truncated", "check_count", "checks_satisfied"),
    InteractiveGoalViewV1: ("availability", "goal_id", "status", "revision", "epoch", "execution_unresolved"),
}
GOAL_KINDS: dict[str, type] = {
    "goal_progress": ExecutionGoalProgressV1,
    "interactive_goal": InteractiveGoalViewV1,
    "interactive_goal_review": InteractiveGoalReviewV1,
    "interactive_goal_recovery": InteractiveGoalRecoveryV1,
}


if TYPE_CHECKING:
    from .model import ExecutionCallV1


_REVIEW_SUBMISSION_KEYS = {"goalId", "reviewToken", "commandId", "decision", "reason"}
_GOAL_COMMAND_KEYS = {"goalId", "commandId", "action"}


def encode_goal_fields(
    call: ExecutionCallV1, body: dict[str, object], encode: Callable[[object], object],
) -> None:
    if call.goal_target is not None:
        body["goalTarget"] = call.goal_target
    if call.goal_command is not None:
        body.update(goalId=call.goal_command.goal_id, commandId=call.goal_command.command_id,
                    action=call.goal_command.action)
    if call.review_goal_id is not None:
        body["goalId"] = call.review_goal_id
    if call.review_submission is not None:
        review = encode(call.review_submission)
        assert isinstance(review, dict)
        body.update(review)
    if call.include_goal_batches:
        body["includeBatches"] = True


def add_goal_fields(operation: ExecutionOperationV1, raw: object, fields: set[str]) -> bool:
    match operation:
        case ExecutionOperationV1.INTERACTIVE_GOAL_CREATE:
            fields.add("goalTarget")
        case ExecutionOperationV1.INTERACTIVE_GOAL_COMMAND:
            fields.update(_GOAL_COMMAND_KEYS)
        case ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW:
            fields.add("goalId")
        case ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW_SUBMIT:
            fields.update(_REVIEW_SUBMISSION_KEYS)
    include_batches = (
        operation is ExecutionOperationV1.GOAL_PROGRESS and type(raw) is dict and "includeBatches" in raw
    )
    if include_batches:
        fields.add("includeBatches")
    return include_batches


class _GoalCallFields(TypedDict):
    goal_target: str | None
    goal_command: InteractiveGoalCommandV1 | None
    review_goal_id: str | None
    review_submission: InteractiveGoalReviewSubmissionV1 | None


def decode_goal_fields(
    operation: ExecutionOperationV1, body: dict[str, object], decode: Callable[[object, object], object],
) -> _GoalCallFields:
    return {
        "goal_target": _string(body["goalTarget"]) if "goalTarget" in body else None,
        "goal_command": cast(InteractiveGoalCommandV1, decode(
            InteractiveGoalCommandV1, {key: body[key] for key in _GOAL_COMMAND_KEYS},
        )) if operation is ExecutionOperationV1.INTERACTIVE_GOAL_COMMAND else None,
        "review_goal_id": _string(body["goalId"]) if operation is ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW else None,
        "review_submission": cast(InteractiveGoalReviewSubmissionV1, decode(
            InteractiveGoalReviewSubmissionV1, {key: body[key] for key in _REVIEW_SUBMISSION_KEYS},
        )) if operation is ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW_SUBMIT else None,
    }


GOAL_CAPABILITIES = (
    "supports_goal_progress", "supports_goal_start", "supports_interactive_goal",
    "supports_interactive_goal_commands", "supports_interactive_goal_recovery",
)
