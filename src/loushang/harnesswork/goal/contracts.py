"""The three injected Goal collaboration contracts, not execution engines."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from loushang.harnesswork.types import WorkOperation, WorkRun, WorkRunSpec, WorkStepSpec

from .records import GoalBatch, GoalHeader, GoalRecord, GoalState, basis_data, document

# Shared physical exclusion protocol; implementations still own roots and I/O.
GOAL_LOCK_DIRECTORY = ".goal-writers"
GOAL_WRITER_HASH_DOMAIN = "harnesswork-goal-writer/v1"


@dataclass(frozen=True)
class GoalBasis:
    header: GoalHeader
    goal: GoalState
    sequence: int

    @property
    def identity(self) -> Mapping[str, object]:
        return basis_data(self.header, self.goal, self.sequence)


@dataclass(frozen=True)
class GoalFacts:
    batches: tuple[GoalBatch, ...]
    runs: tuple[WorkRun, ...]
    busy: bool = False
    unresolved: bool = False


@dataclass(frozen=True)
class PolicyStop:
    reason: str


@dataclass(frozen=True)
class WorkCandidate:
    basis: GoalBasis
    operation: WorkOperation
    spec: WorkRunSpec
    source: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", document(self.source))
        # Do not retain a mutable Product or model payload across an await.
        op = self.operation
        object.__setattr__(
            self,
            "operation",
            WorkOperation(
                op.operation_id,
                op.kind,
                op.session_id,
                op.domain,
                document(op.payload),
                document(op.source),
            ),
        )
        spec = self.spec
        object.__setattr__(
            self,
            "spec",
            WorkRunSpec(
                run_id=spec.run_id,
                method_id=spec.method_id,
                plan_id=spec.plan_id,
                step_id=spec.step_id,
                run_event_payload=document(spec.run_event_payload),
                scope_event_payload=document(spec.scope_event_payload),
                steps=tuple(
                    WorkStepSpec(step.step_id, document(step.payload))
                    for step in spec.steps
                ),
            ),
        )


@dataclass(frozen=True)
class GoalAssessment:
    basis: GoalBasis
    status: str
    reason: str
    coverage: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    proof: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "proof", document(self.proof))


class NextWorkPolicy(Protocol):
    def confirm_resume(
        self, basis: GoalBasis, work_facts: GoalFacts
    ) -> bool | PolicyStop:
        """Read-only local readiness check; does not prepare or execute Work."""
        ...

    async def prepare(
        self, basis: GoalBasis, work_facts: GoalFacts
    ) -> WorkCandidate | PolicyStop: ...
    def confirm_candidate(self, candidate: WorkCandidate) -> bool: ...


class GoalAcceptancePolicy(Protocol):
    async def assess(
        self, basis: GoalBasis, work_facts: GoalFacts
    ) -> GoalAssessment: ...
    def confirm_current(self, assessment: GoalAssessment) -> bool: ...


class GoalRecordStore(Protocol):
    def load(self) -> tuple[GoalHeader, tuple[GoalRecord, ...]]: ...
    def append(self, expected_sequence: int, record: GoalRecord) -> int: ...
