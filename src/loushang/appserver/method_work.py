"""Application-local Method/Work observations; not a wire protocol extension."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .execution.model import ExecutionRecordV1, _identifier


def method_identifier(value: str) -> None:
    # Method IDs have their own vocabulary (including colons).
    if type(value) is not str or not value.strip() or len(value) > 1024:
        raise ValueError("invalid Method identifier")


@dataclass(frozen=True, slots=True)
class MethodWorkCapabilityV1:
    work_binding: str
    method_id: str
    method_digest: str
    max_steps: int
    retention: Literal["live_owner"] = "live_owner"
    accepting: bool = True

    def __post_init__(self) -> None:
        _identifier(self.work_binding)
        method_identifier(self.method_id)
        if (len(self.method_digest) != 64 or any(c not in "0123456789abcdef" for c in self.method_digest)
                or type(self.max_steps) is not int or not 1 <= self.max_steps <= 64
                or self.retention != "live_owner" or type(self.accepting) is not bool):
            raise ValueError("invalid Method capability")


@dataclass(frozen=True, slots=True)
class MethodWorkHandleV1:
    service_instance_id: str
    work_binding: str
    execution_id: str

    def __post_init__(self) -> None:
        for value in (self.service_instance_id, self.work_binding, self.execution_id):
            _identifier(value)


@dataclass(frozen=True, slots=True)
class MethodWorkSubmissionV1:
    handle: MethodWorkHandleV1
    execution: ExecutionRecordV1


@dataclass(frozen=True, slots=True)
class WorkStepObservationV1:
    step_id: str
    status: str


@dataclass(frozen=True, slots=True)
class WorkRunObservationV1:
    operation_id: str
    run_id: str
    session_id: str
    method_id: str | None
    plan_id: str | None
    status: str
    current_step_id: str | None
    steps: tuple[WorkStepObservationV1, ...]


@dataclass(frozen=True, slots=True)
class WorkRecordingObservationV1:
    version: int
    capture: str
    retention: str
    require_persistence: bool
    run_status: str
    basis: str
    observed_sequence: int
    source_event_id: str | None


@dataclass(frozen=True, slots=True)
class WorkCancellationObservationV1:
    status: str
    reason_code: str
    reported_status: str | None
    basis: str
    observed_sequence: int
    source_event_id: str | None


@dataclass(frozen=True, slots=True)
class MethodWorkObservationV1:
    presence: Literal["present", "not_yet_observed", "not_submitted", "unknown"]
    work: WorkRunObservationV1 | None = None
    recording: WorkRecordingObservationV1 | None = None
    cancellation: WorkCancellationObservationV1 | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MethodWorkQueryV1:
    handle: MethodWorkHandleV1
    execution: ExecutionRecordV1
    observation: MethodWorkObservationV1


class MethodWorkError(ValueError):
    """Stable local capability errors; never carries Product exception text."""

    def __init__(self, code: Literal["unsupported", "binding_changed", "invalid_handle", "unavailable"]) -> None:
        self.code = code
        super().__init__(code)
