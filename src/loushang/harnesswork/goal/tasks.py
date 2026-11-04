"""Small task contracts and policies over the existing Goal batch selector.

Domain code supplies snapshots, action bindings and evidence readers. This
module never opens a Session, reads files, calls a model or executes a tool.
"""

from __future__ import annotations

from dataclasses import dataclass

from .batch_planning import BatchPlanningPolicy
from .contracts import GoalAssessment, PolicyStop
from .records import GoalError, canonical, plain

TASK_POLICY = "interactive-task/v1"
TASK_LIMITS = {
    "work_intents": 24,
    "planning_intents": 8,
    "invalid_proposals": 3,
    "no_progress": 2,
    "planning_calls": 1,
    "repair_calls": 8,
    "provider_attempts": 1,
}


@dataclass(frozen=True)
class GoalTask:
    """Accepted content; requirements themselves remain in GoalState."""

    text: str
    checks: tuple[str, ...] = ()
    method: str | None = None
    max_model_calls: int = 8

    def __post_init__(self):
        if (
            not isinstance(self.text, str)
            or not self.text.strip()
            or len(self.text.encode()) > 16384
        ):
            raise GoalError("Goal text must contain 1–16384 UTF-8 bytes")
        object.__setattr__(self, "checks", tuple(self.checks))
        if (
            type(self.max_model_calls) is not int
            or not 1 <= self.max_model_calls <= 32
            or len(self.checks) > 8
            or any(
                not isinstance(c, str) or not c.strip() or len(c.encode()) > 4096
                for c in self.checks
            )
            or (
                self.method is not None
                and (not isinstance(self.method, str) or not self.method.strip())
            )
        ):
            raise GoalError("invalid Goal checks, method or call allowance")

    def data(self):
        return {
            "version": 1,
            "checks": list(self.checks),
            "method": self.method,
            "max_model_calls": self.max_model_calls,
            "acceptance": "human_required",
        }


class TaskPolicy(BatchPlanningPolicy):
    """Domain mixin after BatchPlanningPolicy; no second proposal-selection loop."""

    limits = TASK_LIMITS

    def _observations(self, basis, facts):
        evidence, routes, rejections = [], [], []
        invalid = stalled = planning = 0
        for batch in facts.batches:
            if batch.goal_id != basis.goal.id:
                continue
            run = self._run(batch, facts)
            planning += batch.source.get("phase") == "planning"
            if run is None or run.status == "cancelled":
                continue
            if batch.source.get("phase") == "planning":
                try:
                    proposal = self._proposal(batch, run)
                    routes.append(
                        {"proposal_id": batch.operation_id, "proposal": proposal.data()}
                    )
                except self.rejection_error as error:
                    invalid += 1
                    rejections.append(
                        {"proposal_id": batch.operation_id, "reason": str(error)}
                    )
            else:
                invalid = 0
                result = self.action_result(batch, run)
                evidence.append(
                    {
                        "id": batch.operation_id,
                        "phase": batch.source["phase"],
                        "status": run.status,
                        "revision": batch.revision,
                        "result": result,
                    }
                )
                if batch.source["phase"] == "repair":
                    stalled = (
                        stalled + 1
                        if result["inventory"] == plain(batch.source["inventory"])
                        else 0
                    )
        return evidence, routes, rejections, planning, invalid, stalled

    async def prepare(self, basis, facts):
        snapshot, _ = self.planning_context(basis)
        if self.pending_review is not None:
            return self.review_candidate(basis, snapshot)
        if (
            sum(b.goal_id == basis.goal.id for b in facts.batches)
            >= basis.goal.limit - 2
        ):
            return PolicyStop("closeout_capacity_reserved")
        return await super().prepare(basis, facts)

    def confirm_resume(self, basis, facts):
        return not facts.busy and not facts.unresolved

    async def assess(self, basis, facts):
        if facts.busy or facts.unresolved:
            return GoalAssessment(basis, "needs_user", "execution_unresolved")
        snapshot, _ = self.planning_context(basis)
        evidence, _, _, _, invalid, stalled = self._observations(basis, facts)
        for batch in reversed(facts.batches):
            if (
                batch.goal_id == basis.goal.id
                and batch.revision == basis.goal.revision
                and batch.epoch == basis.goal.epoch
                and batch.source.get("phase") == "review"
            ):
                run = self._run(batch, facts)
                if run is not None and run.status == "completed":
                    result = self.action_result(batch, run)
                    if (
                        result["inventory"] != snapshot
                        or result["approved"] is not True
                    ):
                        continue
                    try:
                        checks = self.review_dependencies(basis, snapshot)
                    except GoalError as error:
                        return GoalAssessment(basis, "needs_user", str(error))
                    if (
                        result["inventory"] == snapshot
                        and result["approved"]
                        and result.get("checks") == checks
                    ):
                        return GoalAssessment(
                            basis,
                            "satisfied",
                            "user_accepted_current_result",
                            coverage=tuple(r.id for r in basis.goal.requirements),
                            operations=(batch.operation_id,),
                            proof=result,
                        )
        if self.pending_review is not None:
            return GoalAssessment(basis, "more_evidence", "record_user_review")
        if (
            invalid >= self.limits["invalid_proposals"]
            or stalled >= self.limits["no_progress"]
        ):
            return GoalAssessment(basis, "needs_user", "planning_limit_or_no_progress")
        return GoalAssessment(basis, "more_evidence", "work_remaining")

    def confirm_current(self, assessment):
        try:
            return self.history().goal(
                assessment.basis.goal.id
            ) == assessment.basis.goal and self.planning_context(assessment.basis)[
                0
            ] == plain(assessment.proof["inventory"])
        except (ValueError, OSError, KeyError):
            return False

    def contract(self, basis):
        contract = plain(basis.goal.metadata["task_contract"])
        if (
            contract.get("version") != 1
            or contract.get("acceptance") != "human_required"
            or basis.header.policy_id != TASK_POLICY
        ):
            raise GoalError("unsupported interactive task contract")
        return contract

    def planning_material(self, snapshot):
        return {
            "task_contract": self.current_contract,
            "actions": self.action_evidence,
            "remaining_model_calls": self.allowance.total_limit
            - self.allowance.total_calls,
            "note": "Execute uses original file tools. Verify selects a check ID. Only user review completes.",
        }

    def action_identity(self, basis, snapshot):
        return canonical(
            {
                "scope": basis.header.scope_id,
                "session": basis.header.session_id,
                "goal_id": basis.goal.id,
                "revision": basis.goal.revision,
                "epoch": basis.goal.epoch,
                "contract": self.contract(basis),
                "inventory": snapshot,
            }
        )
