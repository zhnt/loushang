"""Next-work policy for the accepted, finite model-planning calculator profile."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

from loushang.harnesswork import WorkOperation, WorkRunSpec, WorkStepSpec
from loushang.harnesswork.goal import (
    GoalAssessment,
    GoalBasis,
    GoalError,
    GoalFacts,
    PolicyStop,
    WorkCandidate,
)
from loushang.harnesswork.goal.records import canonical, plain
from loushang.harnesswork.integrations.session import (
    SessionTurnExecutor,
    SessionWorkTurn,
)
from loushang.harnesswork.ports import WorkExecutionBinding
from loushang.harnesswork.run_projection import project_work_runs

from . import _goal_driver as driver
from ._goal_calculator import CalculatorPolicy, put, read
from ._goal_planning_response import verify_response
from ._goal_planning_work import InspectionWork, PlanningWork, ScopedSessionWork
from ._goal_proposal import (
    LIMITS,
    POLICY_ID,
    ProposalRejected,
    parse_proposal,
    planning_instructions,
)
from ._work_evidence import project_work_evidence
from .harnesswork import CODING_WORK_PROFILE, project_coding_runtime_event


def planning_prompt(operation_id, content):
    return (
        planning_instructions()
        + f"\nTrusted planning operation: {operation_id}; input sha256: {driver.digest(content)}\n"
        + content.decode("utf-8")
    )


class ModelPlanningPolicy(CalculatorPolicy):
    policy_id = POLICY_ID

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

    def trace(self, basis, facts):
        """One read-only projection for live and detached original records."""
        if facts.busy or facts.unresolved:
            return {"status": "unknown", "reason": "work_busy_or_unresolved"}
        try:
            evidence, routes, rejections, count, invalid, stalled = self._observations(
                basis, facts
            )
            batches = []
            for batch in facts.batches:
                if batch.goal_id != basis.goal.id:
                    continue
                run = self._run(batch, facts)
                batches.append(
                    {
                        "operation_id": batch.operation_id,
                        "run_id": run.run_id if run else None,
                        "phase": batch.source.get("phase"),
                        "proposal_id": batch.source.get("proposal_id"),
                        "intent_sequence": batch.intent_sequence,
                        "admission": "not_submitted"
                        if batch.not_submitted
                        else "admitted",
                        "work_status": run.status if run else None,
                    }
                )
            for route in routes:
                batch = next(
                    b for b in facts.batches if b.operation_id == route["proposal_id"]
                )
                report = self._report(
                    batch, self._run(batch, facts), "goal_planning_report"
                )
                route["input_ref"] = plain(batch.source["input_ref"])
                route["response_ref"] = report["response_ref"]
                route["response_proof"] = report["response_proof"]
                route["consumed_by"] = [
                    item["operation_id"]
                    for item in batches
                    if item["proposal_id"] == route["proposal_id"]
                ]
            return {
                "status": "known",
                "evidence": evidence,
                "routes": routes,
                "batches": batches,
                "rejections": rejections,
                "planning_intents": count,
                "consecutive_invalid": invalid,
                "consecutive_no_progress": stalled,
            }
        except (ValueError, OSError, KeyError) as error:
            return {"status": "unknown", "reason": str(error)}

    def _run(self, batch, facts):
        found = [run for run in facts.runs if run.operation_id == batch.operation_id]
        if batch.not_submitted:
            if found:
                raise GoalError("not_submitted contradicts Work")
            return None
        if len(found) != 1:
            raise GoalError("planning Work association unknown")
        run = found[0]
        if (
            run.session_id != self.session.session_id
            or batch.run_receipt not in {None, run.run_id}
            or run.status not in {"completed", "failed", "cancelled"}
        ):
            raise GoalError("planning Work identity or outcome unresolved")
        return run

    def _report(self, batch, run, role):
        reports = [
            record
            for record in project_work_evidence(
                self.log.query(operation_id=batch.operation_id)
            )
            if record.operation_id == batch.operation_id and record.role == role
        ]
        if len(reports) != 1 or reports[0].run_id != run.run_id:
            raise GoalError(f"{role}: required original evidence missing or ambiguous")
        value = driver.strict_json(self.blobs.read_bytes(reports[0].blob))
        if (
            not isinstance(value, dict)
            or type(value.get("version")) is not int
            or value["version"] != 1
            or value.get("operation_id") != batch.operation_id
            or value.get("run_id") != run.run_id
        ):
            raise GoalError("planning report identity/version mismatch")
        return value

    def _proposal(self, batch, run):
        report = self._report(batch, run, "goal_planning_report")
        if report.get("session_id") != self.session.session_id or report.get(
            "input_ref"
        ) != plain(batch.source.get("input_ref")):
            raise GoalError("planning input identity mismatch")
        if report.get("rejection") is not None:
            raise ProposalRejected(str(report["rejection"]))
        if run.status != "completed":
            raise GoalError("noncompleted planning Work cannot supply a proposal")
        content = read(self.blobs, batch.source["input_ref"])
        if driver.digest(content) != batch.source["input_sha256"]:
            raise GoalError("planning input digest mismatch")
        inputs = driver.strict_json(content)
        raw = read(self.blobs, report["response_ref"])
        try:
            verify_response(
                self.session.session_manager,
                report["response_proof"],
                session_id=self.session.session_id,
                prompt=planning_prompt(batch.operation_id, content),
                raw=raw,
            )
            proposal = parse_proposal(
                raw, known_evidence=[item["id"] for item in inputs["evidence"]]
            )
        except (ValueError, OSError, KeyError) as error:
            raise GoalError(
                "original planning response evidence unavailable or inconsistent"
            ) from error
        if proposal.data() != report["proposal"]:
            raise GoalError("planning parsed candidate mismatch")
        return proposal

    def _observations(self, basis, facts):
        """Derive limits and input facts, without a second index or counter ledger."""
        evidence: list[dict[str, Any]] = []
        routes: list[dict[str, Any]] = []
        rejections: list[dict[str, Any]] = []
        invalid = no_progress = planning = 0
        knowledge = set()
        failures = None
        for batch in facts.batches:
            if batch.goal_id != basis.goal.id:
                continue
            phase = batch.source.get("phase")
            planning += phase == "planning"
            run = self._run(batch, facts)
            if run is None:
                continue
            if phase == "planning":
                if run.status == "cancelled":
                    continue
                try:
                    proposal = self._proposal(batch, run)
                    if proposal.action.name == "repair":
                        self._repair_proof(
                            batch.revision,
                            batch.epoch,
                            batch.source["inventory"]["calculator.py"]["sha256"],
                            evidence,
                        )
                    routes.append(
                        {"proposal_id": batch.operation_id, "proposal": proposal.data()}
                    )
                except ProposalRejected as error:
                    invalid += 1
                    rejections.append(
                        {"proposal_id": batch.operation_id, "reason": str(error)}
                    )
                continue
            # Only an actual original implementation run resets proposal failures.
            invalid = 0
            item = {
                "id": batch.operation_id,
                "phase": phase,
                "status": run.status,
                "revision": batch.revision,
                "epoch": batch.epoch,
                "action": plain(batch.source.get("action")),
            }
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
                progress = "check_all" not in knowledge or (
                    failures is not None and current_failures < failures
                )
                knowledge.add("check_all")
                failures = current_failures
            elif phase == "inspect":
                report = self._report(batch, run, "goal_inspection_report")
                if (
                    report["source_sha256"]
                    != batch.source["inventory"]["calculator.py"]["sha256"]
                ):
                    raise GoalError("inspection source mismatch")
                item["result"] = report
                inspected = {f"inspect:{target}" for target in report["targets"]}
                progress = bool(inspected - knowledge)
                knowledge.update(inspected)
            elif phase != "repair":
                raise GoalError("unknown model-planning implementation phase")
            no_progress = 0 if progress else no_progress + 1
            evidence.append(item)
        return evidence, routes, rejections, planning, invalid, no_progress

    async def prepare(self, basis, work_facts):
        self.prepared.clear()
        if self.session.pending_message_count:
            return PolicyStop("pending_input")
        try:
            snapshot, source, tests, code = self._current_inputs(basis)
            evidence, routes, rejections, count, invalid, stalled = self._observations(
                basis, work_facts
            )
            if invalid >= LIMITS["invalid_proposals"]:
                return PolicyStop("planning_invalid_limit")
            if stalled >= LIMITS["no_progress"]:
                return PolicyStop("planning_no_progress_limit")
            batches = [
                batch for batch in work_facts.batches if batch.goal_id == basis.goal.id
            ]
            latest = batches[-1] if batches else None
            if (
                latest is not None
                and latest.source.get("phase") == "planning"
                and not latest.not_submitted
                and latest.revision == basis.goal.revision
                and latest.epoch == basis.goal.epoch
                and plain(latest.source["inventory"]) == snapshot
            ):
                run = self._run(latest, work_facts)
                if run.status == "completed":
                    try:
                        proposal = self._proposal(latest, run)
                        candidate = self._implementation(
                            basis, proposal, snapshot, source, tests, code, evidence
                        )
                        if isinstance(candidate, PolicyStop):
                            return candidate
                        return replace(
                            candidate,
                            source={
                                **candidate.source,
                                "proposal_id": latest.operation_id,
                                "planning_basis": latest.source["basis"],
                                "action": proposal.action.data(),
                                "parent_proposal_id": next(
                                    (
                                        b.source["proposal_id"]
                                        for b in reversed(batches)
                                        if "proposal_id" in b.source
                                        and not b.not_submitted
                                    ),
                                    None,
                                ),
                            },
                        )
                    except ProposalRejected as error:
                        # Final semantic rejection is retained in the next input.
                        if not any(
                            item["proposal_id"] == latest.operation_id
                            for item in rejections
                        ):
                            invalid += 1
                            rejections.append(
                                {
                                    "proposal_id": latest.operation_id,
                                    "reason": str(error),
                                }
                            )
                        if invalid >= LIMITS["invalid_proposals"]:
                            return PolicyStop("planning_invalid_limit")
            if count >= LIMITS["planning_intents"]:
                return PolicyStop("planning_intent_limit")
            return self._planning(basis, snapshot, evidence, routes, rejections)
        except (ValueError, OSError, KeyError) as error:
            return PolicyStop(f"planning_evidence_or_contract:{error}")

    def _planning(self, basis, snapshot, evidence, routes, rejections):
        operation_id = f"goal-op-{uuid4().hex}"
        batches = [b for b in self.history().batches if b.goal_id == basis.goal.id]
        content = canonical(
            {
                "version": 1,
                "basis": basis.identity,
                "requirements": [
                    {"id": r.id, "text": r.text} for r in basis.goal.requirements
                ],
                "inventory": snapshot,
                "evidence": evidence,
                "routes": routes,
                "rejections": rejections,
                "limits": LIMITS,
                "remaining": {
                    "work_intents_including_this_planning": basis.goal.limit
                    - len(batches),
                    "planning_intents_including_this_planning": LIMITS[
                        "planning_intents"
                    ]
                    - sum(b.source.get("phase") == "planning" for b in batches),
                },
            }
        ).encode()
        input_ref = put(self.blobs, content, f"{operation_id}/planning-input.json")
        prompt = planning_prompt(operation_id, content)
        turn = SessionWorkTurn(
            prompt, plan_id=f"planning:{operation_id}", step_id="planning"
        )
        original = SessionTurnExecutor(
            session=self.session,
            profile=CODING_WORK_PROFILE,
            project_event_facts=project_coding_runtime_event,
            turn=turn,
        )
        scoped = ScopedSessionWork(
            original,
            session=self.session,
            allowance=self.allowance,
            policy=self.tool_policy,
            phase="planning",
        )
        executor = PlanningWork(
            scoped,
            session=self.session,
            blobs=self.blobs,
            allowance=self.allowance,
            prompt=prompt,
            input_ref=input_ref,
            known_evidence=[item["id"] for item in evidence],
        )
        self.prepared[operation_id] = WorkExecutionBinding(executor, executor)
        return WorkCandidate(
            basis,
            turn.to_operation(
                profile=CODING_WORK_PROFILE,
                session_id=basis.header.session_id,
                operation_id=operation_id,
            ),
            WorkRunSpec(plan_id=turn.plan_id, steps=(WorkStepSpec("planning"),)),
            {
                "phase": "planning",
                "inventory": snapshot,
                "basis": basis.identity,
                "input_ref": input_ref,
                "input_sha256": driver.digest(content),
            },
        )

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
                    phase="repair",
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
            confirm=lambda: super(ModelPlanningPolicy, self).confirm_candidate(
                candidate
            ),
        )
        self.prepared[operation_id] = WorkExecutionBinding(executor)
        return candidate

    def confirm_candidate(self, candidate):
        if not super().confirm_candidate(candidate):
            return False
        history = self.history()
        if candidate.basis.goal != history.goal(candidate.basis.goal.id):
            return False
        proposal_id = candidate.source.get("proposal_id")
        if proposal_id is not None:
            original = [b for b in history.batches if b.operation_id == proposal_id]
            if len(original) != 1:
                return False
            batch = original[0]
            if (
                batch.not_submitted
                or batch.revision != candidate.basis.goal.revision
                or batch.epoch != candidate.basis.goal.epoch
            ):
                return False
            try:
                facts = GoalFacts(
                    history.batches, tuple(project_work_runs(self.log.query()))
                )
                proposal = self._proposal(batch, self._run(batch, facts))
                if proposal.action.data() != plain(candidate.source.get("action")):
                    return False
            except (ValueError, OSError, KeyError):
                return False
            if any(
                b.source.get("proposal_id") == proposal_id
                and b.operation_id != candidate.operation.operation_id
                for b in history.batches
            ):
                return False
        if history.sequence == candidate.basis.sequence:
            return not any(
                b.source.get("proposal_id") == candidate.source.get("proposal_id")
                for b in history.batches
                if candidate.source.get("proposal_id") is not None
            )
        if history.sequence != candidate.basis.sequence + 1 or not history.batches:
            return False
        own = history.batches[-1]
        return (
            own.operation_id == candidate.operation.operation_id
            and own.intent_sequence == history.sequence
            and own.source == candidate.source
            and history.records[-1].data.get("basis") == candidate.basis.identity
        )
