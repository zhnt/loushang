"""Application-local Goal observations; no remote wire activation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .execution.model import ExecutionRecordV1, _identifier
from .method_work import (
    WorkCancellationObservationV1,
    WorkRecordingObservationV1,
    WorkRunObservationV1,
)


@dataclass(frozen=True, slots=True)
class GoalCapabilityV1:
    goal_binding: str
    max_advances: int
    max_model_calls: int
    max_output_tokens: int
    deadline_seconds: float
    profile: str = "calculator"
    accepting: bool = True


@dataclass(frozen=True, slots=True)
class GoalHandleV1:
    service_instance_id: str
    goal_binding: str
    execution_id: str

    def __post_init__(self) -> None:
        for value in (self.service_instance_id, self.goal_binding, self.execution_id):
            _identifier(value)


@dataclass(frozen=True, slots=True)
class GoalSubmissionV1:
    handle: GoalHandleV1
    execution: ExecutionRecordV1


@dataclass(frozen=True, slots=True)
class GoalBatchObservationV1:
    batch_id: str
    operation_id: str
    work: WorkRunObservationV1 | None
    recording: WorkRecordingObservationV1 | None
    cancellation: WorkCancellationObservationV1 | None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GoalObservationV1:
    presence: Literal["not_started", "initializing", "present", "unavailable"]
    reason_code: str
    goal_id: str | None = None
    status: str | None = None
    revision: int | None = None
    epoch: int | None = None
    sequence: int | None = None
    validity: str = "unknown"
    execution_unresolved: bool = True
    advances: int = 0
    model_calls: int = 0
    batches: tuple[GoalBatchObservationV1, ...] = ()


@dataclass(frozen=True, slots=True)
class GoalQueryV1:
    handle: GoalHandleV1
    execution: ExecutionRecordV1
    observation: GoalObservationV1


class GoalServiceError(ValueError):
    def __init__(self, code: Literal["unsupported", "binding_changed", "invalid_handle", "unavailable"]) -> None:
        self.code = code
        super().__init__(code)
