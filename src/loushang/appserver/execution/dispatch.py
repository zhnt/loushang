"""Closed execution dispatch; authority remains with the injected capability."""

import inspect
from typing import cast

from ..protocol import AppErrorCodeV1, AppServiceError
from .client import (
    ExecutionGoalControlPortV1,
    ExecutionObservationPortV1,
    ExecutionPortV1,
    InteractiveGoalClientPortV1,
    InteractiveGoalCommandClientPortV1,
    InteractiveGoalReviewClientPortV1,
)
from .model import (
    ExecutionCallV1,
    ExecutionEventsV1,
    ExecutionOperationV1,
    ExecutionResultV1,
    InteractiveGoalCommandV1,
    InteractiveGoalReviewSubmissionV1,
)


async def dispatch_execution(client: ExecutionObservationPortV1, call: ExecutionCallV1) -> ExecutionResultV1:
    args = call.control, call.expected_instance_id
    if call.operation is ExecutionOperationV1.GOAL_PROGRESS:
        progress = getattr(client, "goal_progress", None)
        if not inspect.iscoroutinefunction(progress):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return await progress(*args, call.execution_id)
    if call.operation is ExecutionOperationV1.SNAPSHOT:
        return await client.snapshot_execution_session(*args)
    if call.operation is ExecutionOperationV1.EVENTS:
        return ExecutionEventsV1(await client.read_execution_events(*args))
    if isinstance(client, ExecutionGoalControlPortV1):
        match call.operation:
            case ExecutionOperationV1.GOAL_START:
                return await client.goal_start(*args, cast(str, call.submission_id))
            case ExecutionOperationV1.FIND:
                return await client.goal_find(*args, cast(str, call.submission_id))
            case ExecutionOperationV1.INTERRUPT:
                return await client.goal_interrupt(*args, cast(str, call.execution_id))
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
    if not isinstance(client, ExecutionPortV1):
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    match call.operation:
        case ExecutionOperationV1.RESUME_INPUT_LOOKUP:
            lookup = getattr(client, "lookup_resume_input", None)
            if not inspect.iscoroutinefunction(lookup):
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            return await lookup(*args, call.resume_query)
        case ExecutionOperationV1.SUBMIT:
            return await client.submit_execution(*args, cast(str, call.submission_id), cast(str, call.text))
        case ExecutionOperationV1.GET:
            return await client.get_execution(*args, cast(str, call.execution_id))
        case ExecutionOperationV1.FIND:
            return await client.find_execution_by_submission(*args, cast(str, call.submission_id))
        case ExecutionOperationV1.INTERRUPT:
            return await client.interrupt_execution(*args, cast(str, call.execution_id))
        case _:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
