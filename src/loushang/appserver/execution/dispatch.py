"""Closed execution dispatch; authority remains with the injected capability."""

import inspect
from typing import cast

from ..protocol import AppErrorCodeV1, AppServiceError
from .client import (
    ExecutionGoalControlPortV1,
    ExecutionObservationPortV1,
    ExecutionPortV1,
)
from .goal_dispatch import dispatch_goal
from .model import (
    ExecutionCallV1,
    ExecutionEventsV1,
    ExecutionOperationV1,
    ExecutionResultV1,
)


async def dispatch_execution(client: ExecutionObservationPortV1, call: ExecutionCallV1) -> ExecutionResultV1:
    args = call.control, call.expected_instance_id
    if call.operation is ExecutionOperationV1.GOAL_PROGRESS:
        progress = getattr(client, "goal_progress", None)
        if not inspect.iscoroutinefunction(progress):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return await progress(*args, call.execution_id)
    if call.operation is ExecutionOperationV1.RESOURCE:
        exchange = getattr(client, "session_resource", None)
        if not inspect.iscoroutinefunction(exchange):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return await exchange(*args, call.resource_query)
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
    if call.operation.value.startswith("session/interactive_goal_"):
        return await dispatch_goal(client, call)
    if not isinstance(client, ExecutionPortV1):
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    match call.operation:
        case ExecutionOperationV1.RESUME_INPUT_LOOKUP:
            lookup = getattr(client, "lookup_resume_input", None)
            if not inspect.iscoroutinefunction(lookup):
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
            return await lookup(*args, call.resume_query)
        case ExecutionOperationV1.SUBMIT:
            submission = (*args, cast(str, call.submission_id), cast(str, call.text))
            if call.resource_refs:
                return await client.submit_execution(*submission, call.resource_refs)
            return await client.submit_execution(*submission)
        case ExecutionOperationV1.GET:
            return await client.get_execution(*args, cast(str, call.execution_id))
        case ExecutionOperationV1.FIND:
            return await client.find_execution_by_submission(*args, cast(str, call.submission_id))
        case ExecutionOperationV1.INTERRUPT:
            return await client.interrupt_execution(*args, cast(str, call.execution_id))
        case _:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
