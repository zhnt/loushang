"""Next-work policy for the accepted, finite model-planning calculator profile."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from loushang.harnesswork import WorkOperation, WorkRunSpec, WorkStepSpec
from loushang.harnesswork.goal import (
    GoalAssessment,
    GoalBasis,
    GoalError,
    PolicyStop,
    WorkCandidate,
)
from loushang.harnesswork.goal.records import plain
from loushang.harnesswork.ports import WorkExecutionBinding

from . import _goal_driver as driver
from ._goal_calculator import CalculatorPolicy
from ._goal_planning_shared import BatchPlanningPolicy
from ._goal_planning_shared import planning_prompt as planning_prompt
from ._goal_planning_work import InspectionWork, ScopedSessionWork
from ._goal_proposal import (
    LIMITS,
    POLICY_ID,
    ProposalRejected,
)
from ._goal_proposal import planning_instructions as planning_instructions


class ModelPlanningPolicy(BatchPlanningPolicy, CalculatorPolicy):
    policy_id = POLICY_ID
    _observations = BatchPlanningPolicy._project_observations

    def __init__(self, *, allowance, tool_policy, history, **kwargs):
        super().__init__(**kwargs)
        self.allowance, self.tool_policy, self.history = allowance, tool_policy, history

    def _current_inputs(self, basis):
        if (
            self.allowance.fenced
            or basis.goal.limit != LIMITS["work_intents"]
            or plain(basis.goal.metadata.get("planning_limits")) != LIMITS
        ):
            raise GoalError("planning owner fenced or profile limits unsupported")
        return super()._current_inputs(basis)

    def confirm_resume(self, basis, work_facts):
        ready = super().confirm_resume(basis, work_facts)
        if ready is not True:
            return ready
        try:
            _, _, _, count, invalid, stalled = self._observations(basis, work_facts)
            if (
                count >= LIMITS["planning_intents"]
                or invalid >= LIMITS["invalid_proposals"]
                or stalled >= LIMITS["no_progress"]
            ):
                return PolicyStop("planning_limits_exhausted")
            return True
        except (ValueError, OSError, KeyError) as error:
            return PolicyStop(f"planning_resume_contract:{error}")

    def prepare_repair(self, basis, snapshot, previous):
        candidate = super().prepare_repair(basis, snapshot, previous)
        if isinstance(candidate, PolicyStop):
            return candidate
        if tuple(step.step_id for step in candidate.spec.steps) != (
            "inspect",
            "repair",
        ):
            self.prepared.pop(candidate.operation.operation_id, None)
            raise GoalError(
                "model planning requires the supported inspect/repair Method"
            )
        return candidate

    def assess_now(self, basis, work_facts):
        assessment = super().assess_now(basis, work_facts)
        if (
            assessment.status in {"satisfied", "needs_user"}
            or work_facts.busy
            or work_facts.unresolved
        ):
            return assessment
        try:
            _, _, _, _, invalid, stalled = self._observations(basis, work_facts)
            reason = (
                "planning_invalid_limit"
                if invalid >= LIMITS["invalid_proposals"]
                else "planning_no_progress_limit"
                if stalled >= LIMITS["no_progress"]
                else None
            )
            return GoalAssessment(basis, "needs_user", reason) if reason else assessment
        except (ValueError, OSError, KeyError) as error:
            return GoalAssessment(
                basis, "needs_user", f"planning_evidence_unknown:{error}"
            )

    def _validate_observed_proposal(self, batch, proposal, evidence):
        if proposal.action.name == "repair":
            self._repair_proof(
                batch.revision,
                batch.epoch,
                batch.source["inventory"]["calculator.py"]["sha256"],
                evidence,
            )

    def _observed_work(self, basis, batch, run, evidence, knowledge, context):
        phase = batch.source.get("phase")
        item = self._implementation_observation(batch, run)
        progress = False
        if phase in {"verification", "check"}:
            historical = GoalBasis(
                basis.header,
                replace(basis.goal, revision=batch.revision, epoch=batch.epoch),
                basis.sequence,
            )
            proof = self._verification(
                replace(batch, run_receipt=run.run_id),
                historical,
                plain(batch.source["inventory"]),
                phase=phase,
            )
            if proof is None:
                raise GoalError("historical verification evidence missing")
            item["result"] = proof
            current_failures = frozenset(
                row["id"] for row in proof["result"]["results"] if not row["passed"]
            )
            previous = knowledge.get("check_all")
            progress = previous is None or current_failures < previous
            knowledge["check_all"] = current_failures
        elif phase == "inspect":
            report = self._report(batch, run, "goal_inspection_report")
            if (
                report["source_sha256"]
                != batch.source["inventory"]["calculator.py"]["sha256"]
            ):
                raise GoalError("inspection source mismatch")
            item["result"] = report
            inspected = {f"inspect:{target}" for target in report["targets"]}
            progress = bool(inspected - knowledge.keys())
            knowledge.update(dict.fromkeys(inspected))
        elif phase != "repair":
            raise GoalError("unknown model-planning implementation phase")
        return item, progress

    @staticmethod
    def _repair_proof(revision, epoch, source_sha256, evidence):
        matches = [
            item
            for item in evidence
            if item["phase"] in {"check", "verification"}
            and item["revision"] == revision
            and item["epoch"] == epoch
            and item["result"]["result"]["source_sha256"] == source_sha256
            and any(not row["passed"] for row in item["result"]["result"]["results"])
        ]
        if not matches:
            raise ProposalRejected(
                "repair requires current actual failing verification"
            )
        return matches[-1]["result"]

    def _implementation(self, basis, proposal, snapshot, source, tests, code, evidence):
        action = proposal.action
        if action.name == "stop":
            return PolicyStop(f"model_requested_stop:{proposal.rationale}")
        if action.name == "repair":
            proof = self._repair_proof(
                basis.goal.revision, basis.goal.epoch, driver.digest(source), evidence
            )
            candidate = self.prepare_repair(basis, snapshot, proof)
            if isinstance(candidate, WorkCandidate):
                original = self.prepared[candidate.operation.operation_id]
                scoped = ScopedSessionWork(
                    original.executor,
                    session=self.session,
                    allowance=self.allowance,
                    policy=self.tool_policy,
                    phase="repair", execution=self.execution,
                )
                self.prepared[candidate.operation.operation_id] = WorkExecutionBinding(
                    scoped, scoped
                )
            return candidate
        if action.name in {"check", "verify_all"}:
            candidate = self.prepare_verification(basis, snapshot, source, tests, code)
            if isinstance(candidate, WorkCandidate) and action.name == "check":
                candidate = replace(
                    candidate, source={**candidate.source, "phase": "check"}
                )
            return candidate
        operation_id = f"goal-op-{uuid4().hex}"
        candidate = WorkCandidate(
            basis,
            WorkOperation(
                operation_id,
                "InspectGoalCalculator",
                basis.header.session_id,
                "coding",
                {},
            ),
            WorkRunSpec(
                plan_id=f"inspection:{operation_id}", steps=(WorkStepSpec("inspect"),)
            ),
            {"phase": "inspect", "inventory": snapshot},
        )
        executor = InspectionWork(
            source=source,
            tests=tests,
            targets=action.targets,
            blobs=self.blobs,
            confirm=lambda: CalculatorPolicy.confirm_candidate(self, candidate),
        )
        self.prepared[operation_id] = WorkExecutionBinding(executor)
        return candidate
