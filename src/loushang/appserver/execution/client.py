"""Optional semantic client, separate from the unchanged AppServicePortV1 port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..protocol import SessionSnapshotRequestV1
from .goal_client import (
    ExecutionGoalControlPortV1,
    InteractiveGoalClientPortV1,
    InteractiveGoalCommandClientPortV1,
    InteractiveGoalRecoveryClientPortV1,
    InteractiveGoalReviewClientPortV1,
)
from .model import (
    ExecutionContentEventV1,
    ExecutionInterruptResultV1,
    ExecutionRecordV1,
    ExecutionSessionSnapshotV1,
    ExecutionUpdateV1,
    ResourceRefV1,
)
from .session_commands import (
    SessionCommandCatalogV1,
    SessionCommandInvocationV1,
    SessionCommandResultV1,
)


class ExecutionObservationPortV1(Protocol):
    @property
    def service_instance_id(self) -> str: ...

    async def snapshot_execution_session(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> ExecutionSessionSnapshotV1: ...

    async def read_execution_events(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> tuple[ExecutionContentEventV1 | ExecutionUpdateV1, ...]: ...

@runtime_checkable
class ExecutionClientV1(ExecutionObservationPortV1, Protocol):
    async def submit_execution(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        submission_id: str, text: str, resource_refs: tuple[ResourceRefV1, ...] = (),
    ) -> ExecutionRecordV1: ...

    async def get_execution(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        execution_id: str,
    ) -> ExecutionRecordV1: ...

    async def find_execution_by_submission(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        submission_id: str,
    ) -> ExecutionRecordV1 | None: ...

    async def interrupt_execution(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        execution_id: str,
    ) -> ExecutionInterruptResultV1: ...


@runtime_checkable
class SessionCommandClientV1(ExecutionClientV1, Protocol):
    async def session_command_catalog(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, prefix: str = "",
    ) -> SessionCommandCatalogV1: ...

    async def read_session_command(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        command: SessionCommandInvocationV1,
    ) -> SessionCommandResultV1: ...

    async def submit_session_command(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        submission_id: str, command: SessionCommandInvocationV1,
    ) -> ExecutionRecordV1: ...

    async def session_command_result(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, execution_id: str,
    ) -> SessionCommandResultV1 | None: ...


ExecutionPortV1 = ExecutionClientV1

__all__ = [
    "ExecutionGoalControlPortV1", "InteractiveGoalClientPortV1", "InteractiveGoalCommandClientPortV1",
    "InteractiveGoalRecoveryClientPortV1", "InteractiveGoalReviewClientPortV1", "ExecutionObservationPortV1",
    "ExecutionClientV1", "ExecutionPortV1", "SessionCommandClientV1",
]
