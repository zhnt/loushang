"""Coding task content over the original current-Session Goal/Work binding."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from loushang.harness.journal._owned_io import settled_io
from loushang.harness.policy import ToolPolicySubject
from loushang.harness.session.call_allowance import ModelCallAllowance
from loushang.harness.workspace.git import observe_workspace_inventory
from loushang.harnesswork import WorkOperation, WorkRunSpec, WorkStepSpec
from loushang.harnesswork.goal import (
    GoalBasis,
    GoalError,
    PolicyStop,
    Requirement,
    WorkCandidate,
)
from loushang.harnesswork.goal.records import canonical, plain
from loushang.harnesswork.goal.tasks import (
    TASK_LIMITS,
    TASK_POLICY,
    GoalTask,
    TaskPolicy,
)
from loushang.harnesswork.integrations.session import (
    SessionTurnExecutor,
    project_prepared_session_work_turns,
)
from loushang.harnesswork.ports import WorkExecutionBinding
from loushang.method.runtime import (
    MethodDomainProfile,
    MethodDomainRequest,
    MethodDomainRuntime,
    MethodPolicy,
    resolve_method_policy,
)

from ._goal_planning_limits import PlanningCallAllowance, PlanningCallLimit
from ._goal_planning_shared import BatchPlanningPolicy
from ._goal_planning_work import PlanningToolPolicy, ScopedSessionWork, publish_report
from ._goal_proposal import Action, ProposalRejected, parse_proposal
from ._verification_work import (
    inspect_verification,
    prepare_coding_verification_command,
)
from .goal import CodingGoal, _ordinary_goal_transport, _validate_goal_session
from .harnesswork import CODING_WORK_PROFILE, project_coding_runtime_event

ACTION_EVIDENCE = {
    "inspect": frozenset({"task_report"}),
    "execute": frozenset({"task_report"}),
    "verify": frozenset({"report", "validation"}),
    "request_review": frozenset(),
    "stop": frozenset(),
}


def workspace_snapshot(root: Path):
    """Bounded identity, including dirty and new files; never used by progress."""
    return observe_workspace_inventory(
        root,
        max_files=10000,
        max_bytes=128 * 1024 * 1024,
        ignored_directories=frozenset({".git", ".venv", "node_modules", "__pycache__"}),
        error_type=GoalError,
        submodule_error="interactive Goal snapshot does not support Git submodules",
        file_limit_error="workspace snapshot exceeds 10000 files",
        external_link_error="workspace snapshot contains an external link",
        byte_limit_error="workspace snapshot exceeds 128 MiB",
    )


class _TaskAllowance(PlanningCallAllowance):
    def _initialize(self, delegate, *, total_limit, max_output_tokens):
        ModelCallAllowance.__init__(
            self,
            phase_limits={"planning": 1, "repair": TASK_LIMITS["repair_calls"]},
            provider_attempts=1,
            delegate=delegate,
            total_limit=total_limit,
            max_output_tokens=max_output_tokens,
            retry_attempts=1,
            error_type=PlanningCallLimit,
        )
        self.hosted_limits = None
        self._budget_snapshot = None


class _TaskTools(PlanningToolPolicy):
    def evaluate(self, subject, /):
        if self.verification is not None:
            return super().evaluate(subject)
        policy = PlanningToolPolicy(
            self.workspace,
            write_paths=[
                Path(p.resolved_path).resolve()
                for p in subject.paths
                if p.resolved_path is not None
            ]
            if isinstance(subject, ToolPolicySubject)
            else [],
        )
        policy.step = self.step
        return policy.evaluate(subject)


def _prompt(operation_id, content):
    return (
        "Choose the next bounded development action from actual evidence. Return only JSON: "
        "next_action, targets, requirement_ids, rationale, expected_evidence, remaining_route, "
        "change_reason, evidence_refs. requirement_ids must be [R1]. rationale is the specific "
        "instruction for this action (<=2048 UTF-8 bytes). remaining_route is 1-6 objects with "
        "action and targets, beginning with next_action/targets. Use [] targets except verify, "
        "which requires one configured check ID. expected_evidence must match actions in material. "
        "Do not change the requirement, checks, Method or budget. Request review when ready; "
        "a model cannot approve completion. Explain material route changes using evidence IDs. "
        f"\nTrusted planning operation: {operation_id}; input sha256: {hashlib.sha256(content).hexdigest()}\n"
        + content.decode()
    )


class _ReportWork:
    def __init__(self, policy, *, delegate=None, value=None, final_step=None):
        self.policy, self.delegate, self.value = policy, delegate, value
        self.final_step = final_step

    async def execute(self, operation, context):
        failure = None
        if self.delegate is not None:
            try:
                await self.delegate.execute(operation, context)
            except Exception as error:
                failure = error
        if (
            failure is None
            and self.final_step is not None
            and context.step_id != self.final_step
        ):
            return
        value = dict(self.value or {})
        if failure is not None:
            value["execution_error"] = str(failure)[:2048]
        inventory = await settled_io(workspace_snapshot, self.policy.root)
        if "inventory" in value and value["inventory"] != inventory:
            raise GoalError("review candidate changed after admission")
        value.update(
            version=1,
            operation_id=operation.operation_id,
            run_id=context.run_id,
            inventory=inventory,
        )
        publish_report(
            self.policy.blobs,
            context,
            value,
            role="task_report",
            session_id=operation.session_id,
        )
        if failure is not None:
            raise failure

    async def cancel_and_wait(self, operation, context):
        if self.delegate is not None:
            return await self.delegate.cancel_and_wait(operation, context)
        from loushang.harnesswork.types import WorkCancellationOutcome

        return WorkCancellationOutcome.settled()


class _Domain:
    def __init__(
        self,
        *,
        workspace,
        session,
        blobs,
        event_log,
        prepared,
        allowance,
        tool_policy,
        history,
        execution_session,
        execution,
        **unused,
    ):
        self.root, self.session, self.blobs, self.log = (
            workspace,
            session,
            blobs,
            event_log,
        )
        self.prepared, self.allowance, self.tool_policy, self.history = (
            prepared,
            allowance,
            tool_policy,
            history,
        )
        self.execution_session, self.execution = execution_session, execution
        self.pending_review = None
        self.current_contract = {}
        self._snapshot = None

    async def refresh(self):
        self._snapshot = await settled_io(workspace_snapshot, self.root)

    def planning_context(self, basis):
        self.current_contract = self.contract(basis)
        self.parse_proposal = cast(
            Any, partial(self.task_proposal, contract=self.current_contract)
        )
        expected = self.current_contract.get("method_identity")
        if expected != self.method_identity(self.current_contract.get("method")):
            raise GoalError("selected Method changed")
        if basis.goal.limit != TASK_LIMITS["work_intents"]:
            raise GoalError("task Work limit changed")
        if self._snapshot is None:
            raise GoalError("task snapshot not prepared")
        return dict(self._snapshot), None

    def method_identity(self, name):
        if name is None:
            return None
        runtime = MethodDomainRuntime(profile=MethodDomainProfile("coding"))
        turns = runtime.prepare_turns(
            MethodDomainRequest(
                "task contract", self.root, method_policy=MethodPolicy.explicit(name)
            )
        )
        return hashlib.sha256(canonical([vars(t) for t in turns]).encode()).hexdigest()

    def task_proposal(self, raw, *, known_evidence, contract):
        checks = contract.get("checks", [])

        class TaskAction(Action):
            @classmethod
            def parse(cls, name, targets):
                if name not in ACTION_EVIDENCE or not isinstance(targets, list):
                    raise ProposalRejected("unknown task action")
                if name == "verify":
                    if len(targets) != 1 or targets[0] not in [
                        f"check-{i + 1}" for i in range(len(checks))
                    ]:
                        raise ProposalRejected(
                            "verify requires one configured check ID"
                        )
                elif targets:
                    raise ProposalRejected("task action requires empty targets")
                return cls(name, tuple(targets))

            @property
            def required_requirements(self):
                return frozenset({"R1"})

        return parse_proposal(
            raw,
            known_evidence=known_evidence,
            action_type=TaskAction,
            requirement_ids={"R1"},
            expected_evidence=ACTION_EVIDENCE,
        )

    def _bind_source(self, operation, spec, executor):
        return operation, executor

    def confirm_candidate(self, candidate):
        try:
            return self.planning_context(candidate.basis)[0] == plain(
                candidate.source["inventory"]
            )
        except (ValueError, OSError):
            return False

    def action_result(self, batch, run):
        if batch.source["phase"] == "verification":
            proof = inspect_verification(
                self.log.query(run_id=run.run_id), run_id=run.run_id, blobs=self.blobs
            )
            return {
                "passed": proof.passed,
                "check": batch.source["check"],
                "inventory": plain(batch.source["inventory"]),
                "issues": list(proof.issues),
            }
        return self._report(batch, run, "task_report")

    def bind_planned_action(self, basis, proposal, snapshot, context, evidence):
        name, opid = proposal.action.name, f"goal-op-{uuid4().hex}"
        if name in {"request_review", "stop"}:
            return PolicyStop(
                "review_required" if name == "request_review" else proposal.rationale
            )
        if name == "verify":
            check = proposal.action.targets[0]
            command = self.contract(basis)["checks"][int(check.split("-")[1]) - 1]
            operation, spec = prepare_coding_verification_command(
                operation_id=opid,
                session_id=basis.header.session_id,
                command=command,
                execution={"cwd": str(self.root)},
                plan_id=f"task:{opid}",
            )
            return WorkCandidate(
                basis,
                operation,
                spec,
                {"phase": "verification", "check": check, "inventory": snapshot},
            )
        if name == "inspect":
            executor = _ReportWork(self, value={"files": list(snapshot)})
            operation = WorkOperation(
                opid, "InspectGoalTask", basis.header.session_id, "coding", {}
            )
            spec = WorkRunSpec(plan_id=f"task:{opid}", steps=(WorkStepSpec("inspect"),))
            phase = "inspect"
        else:
            request = (
                "Implement this development goal using the existing file tools. "
                "Do not alter the accepted goal/checks/Method, do not claim completion.\n"
                + basis.goal.requirements[0].text
                + "\nNext action: "
                + proposal.rationale
            )
            method = self.contract(basis)["method"]
            turns = MethodDomainRuntime(
                profile=MethodDomainProfile("coding")
            ).prepare_turns(
                MethodDomainRequest(
                    request,
                    self.root,
                    method_policy=MethodPolicy.explicit(method)
                    if method
                    else MethodPolicy.off(),
                )
            )
            prepared = tuple(
                replace(
                    t,
                    plan_id=t.plan_id or f"task:{opid}",
                    step_id=t.step_id or "repair",
                )
                for t in project_prepared_session_work_turns(
                    turns, images=None, follow_up_messages=()
                )
            )
            original = SessionTurnExecutor(
                self.execution_session,
                CODING_WORK_PROFILE,
                project_coding_runtime_event,
                turns=prepared,
            )
            scoped = ScopedSessionWork(
                original,
                session=self.session,
                allowance=self.allowance,
                policy=self.tool_policy,
                phase="repair",
                execution=self.execution,
                step_aliases={
                    t.step_id: "inspect" if t.step_id == "inspect" else "repair"
                    for t in prepared
                },
            )
            executor = _ReportWork(
                self, delegate=scoped, final_step=prepared[-1].step_id
            )
            operation = prepared[0].to_operation(
                profile=CODING_WORK_PROFILE,
                session_id=basis.header.session_id,
                operation_id=opid,
            )
            spec = WorkRunSpec(
                method_id=prepared[0].method_id,
                plan_id=prepared[0].plan_id,
                steps=tuple(
                    t.to_step_spec(profile=CODING_WORK_PROFILE) for t in prepared
                ),
            )
            phase = "repair"
        self.prepared[opid] = WorkExecutionBinding(executor, executor)
        return WorkCandidate(
            basis, operation, spec, {"phase": phase, "inventory": snapshot}
        )

    def review_dependencies(self, basis, snapshot):
        evidence = [
            e
            for e in self._observations(basis, self._facts())[0]
            if e["revision"] == basis.goal.revision
        ]
        checks = []
        for i in range(len(self.contract(basis)["checks"])):
            found = [
                e
                for e in evidence
                if e["phase"] == "verification"
                and e["result"]["check"] == f"check-{i + 1}"
                and e["result"]["inventory"] == snapshot
            ]
            if (
                not found
                or found[-1]["result"]["passed"] is not True
                or found[-1]["status"] != "completed"
            ):
                raise GoalError(
                    "required check missing or not passed for current files"
                )
            checks.append(found[-1]["id"])
        return checks

    def review_candidate(self, basis, snapshot):
        expected, approved, reason = self.pending_review
        if self.action_identity(basis, snapshot) != expected:
            raise GoalError("review candidate changed")
        checks = self.review_dependencies(basis, snapshot) if approved else []
        opid = f"goal-op-{uuid4().hex}"
        executor = _ReportWork(
            self,
            value={
                "approved": approved,
                "reason": reason,
                "inventory": snapshot,
                "checks": checks,
            },
        )
        self.prepared[opid] = WorkExecutionBinding(executor, executor)
        return WorkCandidate(
            basis,
            WorkOperation(
                opid, "ReviewGoalTask", basis.header.session_id, "coding", {}
            ),
            WorkRunSpec(plan_id=f"task:{opid}", steps=(WorkStepSpec("review"),)),
            {"phase": "review", "inventory": snapshot},
        )


class _Policy(TaskPolicy, BatchPlanningPolicy, _Domain):
    async def prepare(self, basis, facts):
        await self.refresh()
        return await super().prepare(basis, facts)

    async def assess(self, basis, facts):
        if not facts.busy and not facts.unresolved:
            await self.refresh()
        return await super().assess(basis, facts)

    action_evidence = {name: sorted(values) for name, values in ACTION_EVIDENCE.items()}
    make_prompt = staticmethod(_prompt)
    planning_context = _Domain.planning_context
    bind_planned_action = _Domain.bind_planned_action


_PROFILE = SimpleNamespace(
    policy_id=TASK_POLICY, policy=_Policy, tool_policy=_TaskTools
)


class InteractiveGoal(CodingGoal):
    """One retained current-Session binding, with explicit task creation."""

    _allowances: dict[str, _TaskAllowance]

    @staticmethod
    def require_session_tools(session, workspace: Path) -> None:
        _ordinary_goal_transport(session)
        _validate_goal_session(session, workspace, True, ordinary=True)

    @classmethod
    async def attach(cls, *, session, **limits):
        owner = await cls._attach(session=session, profile=_PROFILE, **limits)
        owner._allowances = {}
        owner._policy._facts = owner.controller.facts
        return owner

    async def create_task(
        self, task: GoalTask, *, check_current: Callable[[], None] | None = None,
    ) -> str:
        async def create():
            admission = self._session.runtime.execution_admission
            reservation = admission.reserve_candidate()
            try:
                await self._policy.refresh()
                admission.validate_reservation(reservation, require_operation=False)
                if check_current is not None:
                    check_current()
                return self._create_task(task)
            finally:
                reservation.release()

        assert self._scope is not None
        return await self._scope.invoke(create)

    def _create_task(self, task: GoalTask):
        if self._closing or self._closed or self.controller.fenced:
            raise GoalError("Goal binding closing or fenced")
        if any(
            g.status in {"active", "paused"}
            for g in self.controller.history.goals.values()
        ):
            raise GoalError(
                "finish or abandon the current Goal before creating another"
            )
        contract = task.data()
        policy = resolve_method_policy(
            explicit_method=task.method,
            disabled=False,
            settings_manager=self._session.settings_manager,
        )
        contract["method"] = policy.selected_method if policy.mode != "off" else None
        contract["method_identity"] = self._policy.method_identity(contract["method"])
        snapshot = dict(self._policy._snapshot)
        allowance = _TaskAllowance.from_stream(
            self._ordinary_transport,
            total_limit=task.max_model_calls,
            max_output_tokens=4096,
            checkpoint=self._check_current_transport,
        )
        goal_id = f"goal-{uuid4().hex[:12]}"
        self.controller.create(
            goal_id,
            (Requirement("R1", task.text),),
            command_id=f"{goal_id}:create",
            limit=TASK_LIMITS["work_intents"],
            metadata={"task_contract": contract, "initial_inventory": snapshot},
        )
        self._allowances[goal_id] = allowance
        self._allowance = self._policy.allowance = allowance
        return goal_id

    def _open_for_commands(self):
        if self._policy is not None and self._policy.pending_review is not None:
            if self._closing or self._closed or self.controller.fenced:
                raise GoalError("Goal binding closing or fenced")
            return
        super()._open_for_commands()

    async def advance(self, goal_id, **command):
        self._allowance = self._policy.allowance = self._allowances[goal_id]
        return await super().advance(goal_id, **command)

    async def review_basis(self, goal_id):
        async def inspect():
            self._session.runtime.execution_admission.require_current()
            core = self.controller
            basis = GoalBasis(core.header, core.query(goal_id), core.history.sequence)
            facts = core.facts()
            if facts.busy or facts.unresolved:
                raise GoalError("cannot review while execution is busy or unresolved")
            await self._policy.refresh()
            self._session.runtime.execution_admission.require_current()
            if (
                core.query(goal_id) != basis.goal
                or core.history.sequence != basis.sequence
            ):
                raise GoalError("review basis changed")
            snapshot, _ = self._policy.planning_context(basis)
            return self._policy.action_identity(basis, snapshot)

        return await self._observations.invoke(inspect)

    def review_check_status(self, goal_id, snapshot) -> tuple[int, bool]:
        """Observe exactly the required check evidence used by review admission."""
        core = self.controller
        basis = GoalBasis(core.header, core.query(goal_id), core.history.sequence)
        count = len(self._policy.contract(basis)["checks"])
        try:
            self._policy.review_dependencies(basis, snapshot)
        except GoalError:
            return count, False
        return count, True

    async def accept(self, goal_id, identity):
        return await self.review(
            goal_id, identity, approved=True, reason="user accepted current result"
        )

    async def review(self, goal_id, identity, *, approved, reason):
        if (
            type(approved) is not bool
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise GoalError("review requires a boolean decision and concrete reason")
        if await self.review_basis(goal_id) != identity:
            raise GoalError("review candidate changed; review again")
        state = self.controller.query(goal_id)
        if state.status == "paused":
            self.controller.control(
                goal_id,
                "resume",
                command_id=f"review-resume-{uuid4().hex}",
                revision=state.revision,
                epoch=state.epoch,
                reason="user_review",
            )
        # Resume changes epoch; compare the old identity before crossing it.
        state = self.controller.query(goal_id)
        current = await self.review_basis(goal_id)
        original, latest = json.loads(identity), json.loads(current)
        original["epoch"] = latest["epoch"]
        if original != latest:
            raise GoalError("review candidate changed; review again")
        self._policy.pending_review = (current, approved, reason)
        try:
            return await self.advance(
                goal_id,
                command_id=f"review-{uuid4().hex}",
                revision=state.revision,
                epoch=state.epoch,
            )
        finally:
            self._policy.pending_review = None


def read_task_history(session, *, missing_ok: bool = False):
    """Read the original store without obtaining a new execution owner."""
    from loushang.harnesswork.goal import GoalHeader
    from loushang.harnesswork.goal.records import replay

    from ._goal_store import GoalJournal

    header = GoalHeader(session.session_id, session.session_id, TASK_POLICY)
    store = GoalJournal(
        Path(session.session_manager.get_session_dir()), header, read_only=True
    )
    try:
        try:
            store.open()
        except GoalError as error:
            if missing_ok and str(error) == "unknown Goal: Session has no Goal journal":
                return None
            raise
        actual, records = store.load()
        return replay(actual, records)
    finally:
        store.close()
