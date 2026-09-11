"""Borrowed remote execution API; requests never regenerate submission IDs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from ..protocol import InvalidAppMessageError, SessionSnapshotRequestV1
from .model import (
    ExecutionCallV1,
    ExecutionContentEventV1,
    ExecutionEventsV1,
    ExecutionInterruptResultV1,
    ExecutionOperationV1,
    ExecutionRecordV1,
    ExecutionSessionSnapshotV1,
    ExecutionUpdateV1,
)

_Send = Callable[[Callable[[str], ExecutionCallV1], type[object], bool, bool], Awaitable[object]]


class RemoteExecutionClientV1:
    def __init__(self, service_instance_id: str, send: _Send) -> None:
        self.service_instance_id, self._send = service_instance_id, send

    async def _call(
        self, operation: ExecutionOperationV1, control: SessionSnapshotRequestV1,
        expected_instance_id: str, *, submission_id: str | None = None,
        execution_id: str | None = None, text: str | None = None,
    ) -> object:
        result_type = {
            ExecutionOperationV1.SNAPSHOT: ExecutionSessionSnapshotV1,
            ExecutionOperationV1.EVENTS: ExecutionEventsV1,
            ExecutionOperationV1.INTERRUPT: ExecutionInterruptResultV1,
        }.get(operation, ExecutionRecordV1)
        # Validate before allocating a communication slot or request ID.
        ExecutionCallV1("validation", operation, control, expected_instance_id,
                        submission_id, execution_id, text)
        result = await self._send(
            lambda request_id: ExecutionCallV1(request_id, operation, control,
                                               expected_instance_id, submission_id, execution_id, text),
            result_type,
            operation in {ExecutionOperationV1.GET, ExecutionOperationV1.FIND, ExecutionOperationV1.INTERRUPT},
            operation is ExecutionOperationV1.FIND,
        )
        checked = result.record if isinstance(result, ExecutionInterruptResultV1) else result
        if isinstance(checked, (ExecutionRecordV1, ExecutionSessionSnapshotV1)) and (
            checked.service_instance_id != expected_instance_id
        ):
            raise InvalidAppMessageError()
        if isinstance(checked, ExecutionRecordV1) and (
            (execution_id is not None and checked.state.execution_id != execution_id)
            or (submission_id is not None and checked.submission_id != submission_id)
        ):
            raise InvalidAppMessageError()
        return result

    async def submit_execution(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        submission_id: str, text: str,
    ) -> ExecutionRecordV1:
        return cast(ExecutionRecordV1, await self._call(
            ExecutionOperationV1.SUBMIT, control, expected_instance_id, submission_id=submission_id, text=text
        ))

    async def get_execution(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, execution_id: str,
    ) -> ExecutionRecordV1:
        return cast(ExecutionRecordV1, await self._call(
            ExecutionOperationV1.GET, control, expected_instance_id, execution_id=execution_id
        ))

    async def find_execution_by_submission(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, submission_id: str,
    ) -> ExecutionRecordV1 | None:
        return cast(ExecutionRecordV1 | None, await self._call(
            ExecutionOperationV1.FIND, control, expected_instance_id, submission_id=submission_id
        ))

    async def interrupt_execution(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, execution_id: str,
    ) -> ExecutionInterruptResultV1:
        return cast(ExecutionInterruptResultV1, await self._call(
            ExecutionOperationV1.INTERRUPT, control, expected_instance_id, execution_id=execution_id
        ))

    async def snapshot_execution_session(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> ExecutionSessionSnapshotV1:
        return cast(ExecutionSessionSnapshotV1, await self._call(
            ExecutionOperationV1.SNAPSHOT, control, expected_instance_id
        ))

    async def read_execution_events(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> tuple[ExecutionContentEventV1 | ExecutionUpdateV1, ...]:
        value = cast(ExecutionEventsV1, await self._call(
            ExecutionOperationV1.EVENTS, control, expected_instance_id
        ))
        return value.events
