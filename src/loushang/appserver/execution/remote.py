"""Borrowed remote execution API; requests never regenerate submission IDs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from ..protocol import (
    AppErrorCodeV1,
    AppServiceError,
    InvalidAppMessageError,
    SessionSnapshotRequestV1,
)
from ..resume_model import ResumeInputLookupQueryV1, ResumeInputLookupResultV1
from .model import (
    ExecutionCallV1,
    ExecutionContentEventV1,
    ExecutionEventsV1,
    ExecutionInterruptResultV1,
    ExecutionOperationV1,
    ExecutionRecordV1,
    ExecutionSessionSnapshotV1,
    ExecutionUpdateV1,
    ResourceRefV1,
)
from .resources import SessionResourceQueryV1, SessionResourceResultV1
from .session_commands import (
    SessionCommandCatalogV1,
    SessionCommandInvocationV1,
    SessionCommandResultV1,
)

_Send = Callable[[Callable[[str], ExecutionCallV1], type[object], bool, bool], Awaitable[object]]


class RemoteExecutionClientV1:
    def __init__(
        self, service_instance_id: str, send: _Send, *, resume_input_lookup: bool = False,
    ) -> None:
        self.service_instance_id, self._send = service_instance_id, send
        if type(resume_input_lookup) is not bool:
            raise TypeError("invalid Resume lookup capability")
        self.resume_input_lookup_available = resume_input_lookup

    async def lookup_resume_input(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        query: ResumeInputLookupQueryV1,
    ) -> ResumeInputLookupResultV1:
        if not self.resume_input_lookup_available:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        ExecutionCallV1(
            "validation", ExecutionOperationV1.RESUME_INPUT_LOOKUP, control,
            expected_instance_id, resume_query=query,
        )
        result = await self._send(
            lambda request_id: ExecutionCallV1(
                request_id, ExecutionOperationV1.RESUME_INPUT_LOOKUP, control,
                expected_instance_id, resume_query=query,
            ),
            ResumeInputLookupResultV1, True, False,
        )
        if type(result) is not ResumeInputLookupResultV1 or result.input_id != query.input_id:
            raise InvalidAppMessageError()
        return result

    async def session_resource(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        query: SessionResourceQueryV1,
    ) -> SessionResourceResultV1:
        result = await self._send(
            lambda request_id: ExecutionCallV1(
                request_id, ExecutionOperationV1.RESOURCE, control, expected_instance_id,
                resource_query=query,
            ), SessionResourceResultV1, query.action != "upload", False,
        )
        return cast(SessionResourceResultV1, result)

    async def session_command_catalog(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, prefix: str = "",
    ) -> SessionCommandCatalogV1:
        return cast(SessionCommandCatalogV1, await self._send(
            lambda request_id: ExecutionCallV1(
                request_id, ExecutionOperationV1.COMMAND_CATALOG, control, expected_instance_id,
                command_prefix=prefix,
            ), SessionCommandCatalogV1, True, False,
        ))

    async def read_session_command(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        command: SessionCommandInvocationV1,
    ) -> SessionCommandResultV1:
        return cast(SessionCommandResultV1, await self._send(
            lambda request_id: ExecutionCallV1(
                request_id, ExecutionOperationV1.COMMAND_READ, control, expected_instance_id,
                command=command,
            ), SessionCommandResultV1, True, False,
        ))

    async def submit_session_command(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        submission_id: str, command: SessionCommandInvocationV1,
    ) -> ExecutionRecordV1:
        record = cast(ExecutionRecordV1, await self._send(
            lambda request_id: ExecutionCallV1(
                request_id, ExecutionOperationV1.COMMAND_SUBMIT, control, expected_instance_id,
                submission_id=submission_id, command=command,
            ), ExecutionRecordV1, False, False,
        ))
        if record.service_instance_id != expected_instance_id or record.submission_id != submission_id:
            raise InvalidAppMessageError()
        return record

    async def session_command_result(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, execution_id: str,
    ) -> SessionCommandResultV1 | None:
        return cast(SessionCommandResultV1 | None, await self._send(
            lambda request_id: ExecutionCallV1(
                request_id, ExecutionOperationV1.COMMAND_RESULT, control, expected_instance_id,
                execution_id=execution_id,
            ), SessionCommandResultV1, True, True,
        ))

    async def _call(
        self, operation: ExecutionOperationV1, control: SessionSnapshotRequestV1,
        expected_instance_id: str, *, submission_id: str | None = None,
        execution_id: str | None = None, text: str | None = None,
        resource_refs: tuple[ResourceRefV1, ...] = (),
    ) -> object:
        result_type = {
            ExecutionOperationV1.SNAPSHOT: ExecutionSessionSnapshotV1,
            ExecutionOperationV1.EVENTS: ExecutionEventsV1,
            ExecutionOperationV1.INTERRUPT: ExecutionInterruptResultV1,
        }.get(operation, ExecutionRecordV1)
        # Validate before allocating a communication slot or request ID.
        ExecutionCallV1("validation", operation, control, expected_instance_id,
                        submission_id, execution_id, text, resource_refs=resource_refs)
        result = await self._send(
            lambda request_id: ExecutionCallV1(request_id, operation, control,
                                               expected_instance_id, submission_id, execution_id, text,
                                               resource_refs=resource_refs),
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
        submission_id: str, text: str, resource_refs: tuple[ResourceRefV1, ...] = (),
    ) -> ExecutionRecordV1:
        return cast(ExecutionRecordV1, await self._call(
            ExecutionOperationV1.SUBMIT, control, expected_instance_id, submission_id=submission_id, text=text,
            resource_refs=resource_refs
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
