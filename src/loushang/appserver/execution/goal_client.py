"""Optional Goal capabilities of an execution client."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..protocol import SessionSnapshotRequestV1
from .goal_model import (
    InteractiveGoalCommandV1,
    InteractiveGoalRecoveryV1,
    InteractiveGoalReviewSubmissionV1,
    InteractiveGoalReviewV1,
    InteractiveGoalViewV1,
)
from .model import ExecutionInterruptResultV1, ExecutionRecordV1


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


@runtime_checkable
class InteractiveGoalCommandClientPortV1(Protocol):
    async def control_interactive_goal(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        command: InteractiveGoalCommandV1,
    ) -> InteractiveGoalViewV1: ...


@runtime_checkable
class InteractiveGoalReviewClientPortV1(Protocol):
    async def interactive_goal_review(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, goal_id: str,
    ) -> InteractiveGoalReviewV1: ...

    async def submit_interactive_goal_review(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, command: InteractiveGoalReviewSubmissionV1,
    ) -> InteractiveGoalViewV1: ...


@runtime_checkable
class InteractiveGoalRecoveryClientPortV1(Protocol):
    async def interactive_goal_recovery(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> InteractiveGoalRecoveryV1: ...
