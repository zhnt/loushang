"""Optional semantic client, separate from the unchanged AppClientV1 port."""

from __future__ import annotations

from typing import Protocol

from ..protocol import SessionSnapshotRequestV1
from .model import (
    ExecutionContentEventV1,
    ExecutionInterruptResultV1,
    ExecutionRecordV1,
    ExecutionSessionSnapshotV1,
    ExecutionUpdateV1,
)


class ExecutionClientV1(Protocol):
    @property
    def service_instance_id(self) -> str: ...

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

    async def snapshot_execution_session(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> ExecutionSessionSnapshotV1: ...

    async def read_execution_events(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> tuple[ExecutionContentEventV1 | ExecutionUpdateV1, ...]: ...
