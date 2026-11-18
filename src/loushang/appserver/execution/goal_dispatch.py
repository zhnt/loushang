"""Dispatch optional Goal operations through the original scoped client."""

from typing import cast

from ..protocol import AppErrorCodeV1, AppServiceError
from .client import ExecutionObservationPortV1
from .goal_client import (
    InteractiveGoalClientPortV1,
    InteractiveGoalCommandClientPortV1,
    InteractiveGoalRecoveryClientPortV1,
    InteractiveGoalReviewClientPortV1,
)
from .goal_model import InteractiveGoalCommandV1, InteractiveGoalReviewSubmissionV1
from .model import ExecutionCallV1, ExecutionResultV1
from .operation import ExecutionOperationV1


async def dispatch_goal(client: ExecutionObservationPortV1, call: ExecutionCallV1) -> ExecutionResultV1:
    args = call.control, call.expected_instance_id
    if call.operation in {ExecutionOperationV1.INTERACTIVE_GOAL_CREATE, ExecutionOperationV1.INTERACTIVE_GOAL_STATUS}:
        if not isinstance(client, InteractiveGoalClientPortV1):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        if call.operation is ExecutionOperationV1.INTERACTIVE_GOAL_CREATE:
            return await client.create_interactive_goal(*args, cast(str, call.goal_target))
        return await client.interactive_goal_status(*args)
    if call.operation is ExecutionOperationV1.INTERACTIVE_GOAL_COMMAND:
        if not isinstance(client, InteractiveGoalCommandClientPortV1):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return await client.control_interactive_goal(*args, cast(InteractiveGoalCommandV1, call.goal_command))
    if call.operation in {ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW, ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW_SUBMIT}:
        if not isinstance(client, InteractiveGoalReviewClientPortV1):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        if call.operation is ExecutionOperationV1.INTERACTIVE_GOAL_REVIEW:
            return await client.interactive_goal_review(*args, cast(str, call.review_goal_id))
        return await client.submit_interactive_goal_review(*args, cast(InteractiveGoalReviewSubmissionV1, call.review_submission))
    if call.operation is ExecutionOperationV1.INTERACTIVE_GOAL_RECOVERY:
        if not isinstance(client, InteractiveGoalRecoveryClientPortV1):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return await client.interactive_goal_recovery(*args)
    raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
