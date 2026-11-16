"""Optional semantic client, separate from the unchanged AppServicePortV1 port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..protocol import SessionSnapshotRequestV1
from .model import (
    ExecutionContentEventV1,
    ExecutionInterruptResultV1,
    ExecutionRecordV1,
    ExecutionSessionSnapshotV1,
    ExecutionUpdateV1,
    InteractiveGoalViewV1,
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
        submission_id: str, text: str,
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
class ExecutionGoalControlPortV1(Protocol):
    """Control the Goal already bound by the host to the addressed Session."""

    async def goal_start(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        submission_id: str,
    ) -> ExecutionRecordV1: ...

    async def goal_find(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        submission_id: str,
    ) -> ExecutionRecordV1 | None: ...

    async def goal_interrupt(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        execution_id: str,
    ) -> ExecutionInterruptResultV1: ...


@runtime_checkable
class InteractiveGoalClientPortV1(Protocol):
    async def create_interactive_goal(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, target: str,
    ) -> InteractiveGoalViewV1: ...

    async def interactive_goal_status(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> InteractiveGoalViewV1: ...


ExecutionPortV1 = ExecutionClientV1
