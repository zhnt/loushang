"""Closed execution dispatch; authority remains with the injected capability."""

from typing import cast

from .client import ExecutionClientV1
from .model import (
    ExecutionCallV1,
    ExecutionEventsV1,
    ExecutionOperationV1,
    ExecutionResultV1,
)


async def dispatch_execution(client: ExecutionClientV1, call: ExecutionCallV1) -> ExecutionResultV1:
    args = call.control, call.expected_instance_id
    match call.operation:
        case ExecutionOperationV1.SUBMIT:
            return await client.submit_execution(*args, cast(str, call.submission_id), cast(str, call.text))
        case ExecutionOperationV1.GET:
            return await client.get_execution(*args, cast(str, call.execution_id))
        case ExecutionOperationV1.FIND:
            return await client.find_execution_by_submission(*args, cast(str, call.submission_id))
        case ExecutionOperationV1.INTERRUPT:
            return await client.interrupt_execution(*args, cast(str, call.execution_id))
        case ExecutionOperationV1.SNAPSHOT:
            return await client.snapshot_execution_session(*args)
        case ExecutionOperationV1.EVENTS:
            return ExecutionEventsV1(await client.read_execution_events(*args))
