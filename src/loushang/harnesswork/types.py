from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, TypeAlias

WorkRunStatus: TypeAlias = Literal[
    "accepted",
    "running",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
    "orphaned",
]

WorkCancellationStatus: TypeAlias = Literal["settled", "unsupported", "failed"]

WorkStepStatus: TypeAlias = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    "cancelled",
]

DeliveryHint: TypeAlias = Literal["immediate", "coalesce", "final_only"]
ArtifactStatus: TypeAlias = Literal["planned", "created", "updated", "deleted", "failed"]


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: str
    kind: str
    uri: str | None = None
    title: str | None = None
    domain: str | None = None
    produced_by_run_id: str | None = None
    produced_by_step_id: str | None = None
    expected_artifact: str | None = None
    media_type: str | None = None
    status: ArtifactStatus = "created"
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkOperation:
    operation_id: str
    kind: str
    session_id: str | None
    domain: str
    payload: Mapping[str, object]
    source: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkEventFact:
    """A domain fact that Work will correlate, sequence, and persist."""

    kind: str
    payload: Mapping[str, object]
    delivery_hint: DeliveryHint = "coalesce"
    source_event_ref: str | None = None


@dataclass(frozen=True)
class WorkCancellationOutcome:
    """Explicit result of asking a domain invocation to settle after cancellation."""

    status: WorkCancellationStatus
    error: BaseException | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.status not in {"settled", "unsupported", "failed"}:
            raise ValueError(f"unsupported Work cancellation status: {self.status}")
        if self.status == "failed" and self.error is None:
            raise ValueError("failed Work cancellation requires an error")
        if self.status != "failed" and self.error is not None:
            raise ValueError(f"{self.status} Work cancellation cannot carry an error")

    @classmethod
    def settled(cls) -> WorkCancellationOutcome:
        return cls(status="settled")

    @classmethod
    def unsupported(cls) -> WorkCancellationOutcome:
        return cls(status="unsupported")

    @classmethod
    def failed(cls, error: BaseException) -> WorkCancellationOutcome:
        return cls(status="failed", error=error)


@dataclass(frozen=True)
class WorkStepSpec:
    """One Work-owned sequential step in an accepted run."""

    step_id: str
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkRunSpec:
    """Work-owned lifecycle metadata supplied when an operation is accepted."""

    run_id: str | None = None
    method_id: str | None = None
    plan_id: str | None = None
    step_id: str | None = None
    run_event_payload: Mapping[str, object] = field(default_factory=dict)
    scope_event_payload: Mapping[str, object] = field(default_factory=dict)
    steps: tuple[WorkStepSpec, ...] = ()


@dataclass(frozen=True)
class WorkRun:
    run_id: str
    operation_id: str
    session_id: str
    domain: str
    status: WorkRunStatus
    method_id: str | None = None
    plan_id: str | None = None
    current_step_id: str | None = None


@dataclass(frozen=True)
class WorkStepDeviation:
    step_id: str
    deviation_type: str
    reason: str
    policy_level: str | None = None
    evidence_refs: tuple[str, ...] = ()
    approval_ref: str | None = None
    risk: str | None = None
    outcome: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkStepRun:
    run_id: str
    plan_id: str
    step_id: str
    sequence: int
    status: WorkStepStatus
    method_id: str | None = None
    title: str | None = None
    phase: str | None = None
    activity: str | None = None
    task: str | None = None
    role: str | None = None
    expected_artifacts: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    deviation: WorkStepDeviation | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkPlanRun:
    plan_id: str
    status: WorkRunStatus
    steps: tuple[WorkStepRun, ...] = ()
    method_id: str | None = None
    current_step_id: str | None = None
    step_count: int = 0
    completed_step_count: int = 0
    failed_step_count: int = 0
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkEvent:
    event_id: str
    kind: str
    run_id: str
    session_id: str
    domain: str
    operation_id: str
    sequence: int
    created_at: datetime
    delivery_hint: DeliveryHint
    payload: Mapping[str, object]
    source_event_ref: str | None = None


__all__ = [
    "ArtifactRef",
    "ArtifactStatus",
    "DeliveryHint",
    "WorkEvent",
    "WorkEventFact",
    "WorkCancellationOutcome",
    "WorkCancellationStatus",
    "WorkOperation",
    "WorkPlanRun",
    "WorkRun",
    "WorkRunStatus",
    "WorkRunSpec",
    "WorkStepSpec",
    "WorkStepDeviation",
    "WorkStepRun",
    "WorkStepStatus",
]
