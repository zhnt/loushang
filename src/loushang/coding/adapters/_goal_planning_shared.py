"""Coding profile and original Work preparation over the shared Goal selector."""
from __future__ import annotations

from uuid import uuid4

from loushang.harness.artifacts import SessionBlobRef
from loushang.harnesswork import WorkRunSpec, WorkStepSpec
from loushang.harnesswork.goal import WorkCandidate
from loushang.harnesswork.goal.batch_planning import (
    BatchPlanningPolicy as _SharedBatchPlanningPolicy,
)
from loushang.harnesswork.goal.records import canonical
from loushang.harnesswork.integrations.session import (
    SessionTurnExecutor,
    SessionWorkTurn,
)
from loushang.harnesswork.ports import WorkExecutionBinding

from . import _goal_driver as driver
from ._goal_calculator import put, read
from ._goal_planning_response import verify_response
from ._goal_planning_work import PlanningWork, ScopedSessionWork
from ._goal_proposal import (
    LIMITS,
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


class BatchPlanningPolicy(_SharedBatchPlanningPolicy):
    """Original Coding profile and bindings; no second selection algorithm."""

    limits = LIMITS
    rejection_error = ProposalRejected
    parse_proposal = staticmethod(parse_proposal)
    make_prompt = staticmethod(planning_prompt)
    decode_planning_document = staticmethod(driver.strict_json)

    def planning_material(self, snapshot):
        return {}

    def planning_session_id(self):
        return self.session.session_id

    def planning_input_pending(self):
        return self.session.pending_message_count

    def planning_context(self, basis):
        snapshot, source, tests, code = self._current_inputs(basis)
        return snapshot, (source, tests, code)

    def bind_planned_action(self, basis, proposal, snapshot, context, evidence):
        return self._implementation(basis, proposal, snapshot, *context, evidence)

    def planning_report_records(self, operation_id, role):
        return [
            record for record in project_work_evidence(self.log.query(operation_id=operation_id))
            if record.operation_id == operation_id and record.role == role
        ]

    def read_planning_blob(self, reference):
        if isinstance(reference, SessionBlobRef):
            return self.blobs.read_bytes(reference)
        return read(self.blobs, reference)

    def verify_planning_reply(self, batch, report, content, raw):
        verify_response(
            self.session.session_manager, report["response_proof"],
            session_id=self.session.session_id,
            prompt=self.make_prompt(batch.operation_id, content), raw=raw,
        )

    def _planning(self, basis, snapshot, evidence, routes, rejections):
        operation_id = f"goal-op-{uuid4().hex}"
        batches = [b for b in self.history().batches if b.goal_id == basis.goal.id]
        budget = self.allowance.model_budget() if self.allowance is not None else {}
        remaining = self._planning_remaining(basis, batches)
        if budget:
            hosted = budget["hosted_budget"]
            remaining["model_calls_remaining_including_next_call"] = hosted["model_calls_remaining_including_next_call"]
            # The original Invocation already charged this command before
            # preparation; this planning Work is included in both quantities.
            remaining["work_intents_including_this_planning"] = min(
                remaining["work_intents_including_this_planning"],
                max(0, hosted["max_advances"] - hosted["advances_including_current_command"] + 1),
            )
        content = canonical(
            {
                "version": 1,
                "basis": basis.identity,
                "requirements": [
                    {"id": r.id, "text": r.text} for r in basis.goal.requirements
                ],
                "inventory": snapshot,
                "material": self.planning_material(snapshot),
                "evidence": evidence,
                "routes": routes,
                "rejections": rejections,
                "limits": self.allowance.model_limits(self.limits) if self.allowance is not None else self.limits,
                "remaining": remaining,
                **budget,
            }
        ).encode()
        input_ref = put(self.blobs, content, f"{operation_id}/planning-input.json")
        prompt = self.make_prompt(operation_id, content)
        turn = SessionWorkTurn(
            prompt, plan_id=f"planning:{operation_id}", step_id="planning"
        )
        original = SessionTurnExecutor(
            session=self.execution_session,
            profile=CODING_WORK_PROFILE,
            project_event_facts=project_coding_runtime_event,
            turns=(turn,),
        )
        operation = turn.to_operation(
            profile=CODING_WORK_PROFILE,
            session_id=basis.header.session_id,
            operation_id=operation_id,
        )
        spec = WorkRunSpec(plan_id=turn.plan_id, steps=(WorkStepSpec("planning"),))
        operation, original = self._bind_source(operation, spec, original)
        scoped = ScopedSessionWork(
            original,
            session=self.session,
            allowance=self.allowance,
            policy=self.tool_policy,
            phase="planning", execution=self.execution,
        )
        executor = PlanningWork(
            scoped,
            session=self.session,
            blobs=self.blobs,
            allowance=self.allowance,
            prompt=prompt,
            input_ref=input_ref,
            known_evidence=[item["id"] for item in evidence],
            parser=self.parse_proposal,
        )
        self.prepared[operation_id] = WorkExecutionBinding(executor, executor)
        return WorkCandidate(
            basis,
            operation,
            spec,
            {
                "phase": "planning",
                "inventory": snapshot,
                "basis": basis.identity,
                "input_ref": input_ref,
                "input_sha256": driver.digest(content),
            },
        )
