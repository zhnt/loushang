"""Private local repository profile over the original Coding Goal owner and Work."""

from __future__ import annotations

import json
import shlex
from dataclasses import replace
from functools import partial
from types import SimpleNamespace
from uuid import uuid4

from loushang.harness.artifacts import SessionBlobRef
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
    prepare_session_work_source,
    project_prepared_session_work_turns,
)
from loushang.harnesswork.integrations.transcript import CONTRACT_KEY
from loushang.harnesswork.ports import WorkExecutionBinding
from loushang.method.runtime import (
    MethodDomainProfile,
    MethodDomainRequest,
    MethodDomainRuntime,
    MethodPolicy,
)
from loushang.method.types import MethodDescriptor

from ._goal_calculator import put, read
from ._goal_planning_history import PlanningHistory
from ._goal_planning_shared import BatchPlanningPolicy
from ._goal_planning_work import PlanningToolPolicy, ScopedSessionWork, publish_report
from ._goal_proposal import LIMITS as DEFAULT_LIMITS
from ._goal_proposal import Action, ProposalRejected, _strings, parse_proposal
from ._goal_repository_review import review_candidate, review_value, validate_review
from ._goal_repository_task import RepositoryTask, digest
from ._verification_work import inspect_verification
from ._work_evidence import project_work_evidence
from .goal import CodingGoal, CodingGoalView, _inspect_goal, _view
from .harnesswork import CODING_WORK_PROFILE, project_coding_runtime_event

LIMITS = {**DEFAULT_LIMITS, "planning_intents": 8}

REQUIREMENTS = frozenset(f"RC-0{i}" for i in range(1, 7))
EVIDENCE = {
    "inspect": frozenset({"repository_report"}),
    "implement": frozenset({"method_execution"}),
    "check": frozenset({"report", "validation"}),
    "verify_all": frozenset({"report", "validation"}),
    "stop": frozenset(),
}


def validate_check_result(result, check):
    if (
        not isinstance(result, dict)
        or type(result.get("version")) is not int
        or result["version"] != 1
    ):
        raise GoalError("unsupported repository result version")
    rows = result.get("results")
    names = ["contract", "regression" if check == "all" else check]
    if (
        not isinstance(rows, list)
        or len(rows) != 2
        or [r.get("name") for r in rows if isinstance(r, dict)] != names
    ):
        raise GoalError("incomplete repository check coverage")
    for row in rows:
        if (
            set(row)
            != {
                "name",
                "exit_code",
                "collected",
                "skipped",
                "failed",
                "errors",
                "output",
            }
            or any(
                type(row[k]) is not int for k in ("exit_code", "collected", "skipped")
            )
            or row["exit_code"] not in {0, 1}
            or not 0 <= row["skipped"] < row["collected"]
            or not isinstance(row["failed"], list)
            or any(not isinstance(n, str) for n in row["failed"])
            or (row["exit_code"] == 1) != bool(row["failed"])
            or row["errors"] != []
            or not isinstance(row["output"], str)
            or (row["name"] == "contract" and row["skipped"] != 0)
        ):
            raise GoalError("repository check environment or collection unknown")


class RepositoryAction(Action):
    @classmethod
    def parse(cls, name, targets):
        selected = tuple(sorted(_strings(targets)))
        if not isinstance(name, str) or name not in EVIDENCE:
            raise ProposalRejected("unknown repository action")
        allowed = {
            "inspect": {"reader", "operations", "tests"},
            "implement": {"reader", "tests"},
            "check": {"reader", "regression"},
        }
        if name in allowed:
            if (
                not selected
                or not set(selected) <= allowed[name]
                or (name == "check" and len(selected) != 1)
            ):
                raise ProposalRejected("invalid repository targets")
        elif selected:
            raise ProposalRejected("verify_all/stop require empty targets")
        return cls(name, selected)

    @property
    def required_requirements(self):
        return frozenset() if self.name == "stop" else REQUIREMENTS


parse_repository_proposal = partial(
    parse_proposal,
    action_type=RepositoryAction,
    requirement_ids=REQUIREMENTS,
    expected_evidence=EVIDENCE,
)


def prompt(operation_id, content):
    return (
        "Choose one next action and a revisable route for issue #125 from the supplied facts. "
        "Return ONE JSON object, no fences/tools. Keys exactly: next_action, targets, "
        "requirement_ids, rationale, expected_evidence, remaining_route, change_reason, evidence_refs. "
        "rationale/change_reason are strings <=2048 UTF-8 bytes; change_reason may be empty. "
        "targets/requirement_ids/expected_evidence/evidence_refs are string arrays. "
        "remaining_route is 1-6 objects with action and targets, first matching next_action. "
        "inspect targets: nonempty subset of reader,operations,tests. implement targets: reader,tests. "
        "check targets: exactly one of reader,regression. All checks include the independent contract. "
        "verify_all and stop targets: []. Every non-stop action covers RC-01 through RC-06. "
        "An implement Work may edit any of the two allowed files; targets describe focus. "
        "Use actual failures to adjust the plan. The initial defect is established; implementation need not wait "
        "for another failed test. Only verify_all and independent human review can support completion. "
        "Do not change requirements, protected verifier, Method, paths, permissions or limits. "
        "evidence_refs must use supplied evidence IDs. expected_evidence must match: "
        + canonical({key: sorted(value) for key, value in EVIDENCE.items()})
        + f"\nTrusted planning operation: {operation_id}; input sha256: {digest(content)}\n"
        + content.decode()
    )


class RepositoryProfile:
    limits = LIMITS
    policy_id = RepositoryTask.policy_id
    system_prompt = (
        "Pursue the bounded repository task. Planning turns return only requested JSON without tools. "
        "Implementation turns follow the protected Method and use read/edit/write only on allowed files. "
        "Do not run commands, alter tests to hide failures, change requirements or claim Goal completion."
    )

    def __init__(self, task, execution_policy=None):
        from ._goal_execution_context import SessionExecutionPolicy

        if execution_policy is not None and not isinstance(
            execution_policy, SessionExecutionPolicy
        ):
            raise GoalError("invalid repository Session policy")
        self.execution_policy = execution_policy
        self.task, self.requirements = task, task.requirements

    def tool_policy(self, root):
        if root != self.task.root:
            raise GoalError("repository workspace mismatch")
        return PlanningToolPolicy(
            root,
            read_paths={root / n for n in self.task.readable},
            write_paths={root / n for n in self.task.allowed},
        )

    def initial_metadata(self, root, blobs):
        return {
            "profile": self.policy_id,
            "task_sha256": self.task.digest,
            "initial_inventory": self.task.snapshot(),
            "planning_limits": LIMITS,
            "task_ref": put(blobs, self.task.path.read_bytes(), "repository-task.json"),
        }

    def policy(self, **kwargs):
        return RepositoryPolicy(task=self.task, **kwargs)

    def inspect(
        self,
        workspace,
        data_root,
        session_id,
        goal_id,
        header,
        history,
        log,
        runs,
        unresolved,
        blobs,
    ):
        if header.policy_id != self.policy_id or workspace.resolve() != self.task.root:
            raise GoalError("repository cold read identity mismatch")
        state = history.goal(goal_id)
        try:
            manager = (
                PlanningHistory(data_root.resolve() / "sessions", session_id, blobs)
                if any(b.source.get("phase") == "planning" for b in history.batches)
                else None
            )
        except (ValueError, OSError, KeyError) as error:
            return CodingGoalView(
                state,
                "unknown",
                "planning_history_unavailable",
                unresolved,
                {"status": "unknown", "reason": str(error)},
            )
        policy = self.policy(
            workspace=workspace,
            session=SimpleNamespace(
                session_id=session_id, session_manager=manager, pending_message_count=0
            ),
            blobs=blobs,
            event_log=log,
            prepared={},
            allowance=None,
            tool_policy=None,
            history=lambda: history,
        )
        basis, facts = (
            GoalBasis(header, state, history.sequence),
            GoalFacts(history.batches, runs, unresolved=unresolved),
        )
        assessment = policy.assess_now(basis, facts)
        return replace(
            _view(state, assessment, unresolved=unresolved),
            planning=policy.trace(basis, facts),
        )


class RepositoryDomain:
    """Only repository facts and acceptance; batch admission is inherited once."""

    def __init__(
        self,
        *,
        task,
        workspace,
        session,
        blobs,
        event_log,
        prepared,
        allowance,
        tool_policy,
        history,
        transcript_source=None,
    ):
        self.task, self.root, self.session, self.blobs = task, workspace, session, blobs
        self.log, self.prepared = event_log, prepared
        self.allowance, self.tool_policy, self.history = allowance, tool_policy, history
        self.pending_review = None
        self.transcript_source = transcript_source
        self.delegation = None

    def _bind_source(self, operation, spec, executor):
        if self.transcript_source is None:
            return operation, executor
        return prepare_session_work_source(
            operation,
            spec=spec,
            session=self.session,
            executor=executor,
            source=self.transcript_source,
        )

    def _current_inputs(self, basis):
        if (
            basis.header.policy_id != self.task.policy_id
            or basis.goal.limit != LIMITS["work_intents"]
            or basis.goal.metadata.get("task_sha256") != self.task.digest
            or plain(basis.goal.metadata.get("planning_limits")) != LIMITS
            or tuple(basis.goal.requirements) != self.task.requirements
            or (self.allowance is not None and self.allowance.fenced)
        ):
            raise GoalError("repository task or limits changed")
        if (
            read(self.blobs, basis.goal.metadata["task_ref"])
            != self.task.path.read_bytes()
        ):
            raise GoalError("repository task evidence changed")
        return self.task.snapshot(), None, None, None

    def confirm_candidate(self, candidate):
        from ._goal_delegation import KEY

        try:
            if KEY in candidate.source and (
                self.delegation is None
                or plain(candidate.source[KEY])
                != plain(candidate.operation.payload.get(KEY))
                or not self.delegation.confirm(plain(candidate.source[KEY]))
            ):
                return False
            if CONTRACT_KEY in candidate.operation.payload:
                if self.transcript_source is None:
                    return False
                self.transcript_source.check()
            return self._current_inputs(candidate.basis)[0] == plain(
                candidate.source["inventory"]
            )
        except (ValueError, OSError, KeyError):
            return False

    def confirm_resume(self, basis, work_facts):
        try:
            self._current_inputs(basis)
            _, _, _, count, invalid, stalled = self._observations(basis, work_facts)
            return count < LIMITS["planning_intents"] and invalid < 3 and stalled < 2
        except (ValueError, OSError, KeyError):
            return False

    def planning_material(self, snapshot):
        return {
            "acceptance": self.task.config["requirements"],
            "allowed_files": self.task.allowed,
            "inspect_files": self.task.config["inspect_files"],
        }

    def _verification(self, batch, run):
        evidence = inspect_verification(
            self.log.query(), run_id=run.run_id, blobs=self.blobs
        )
        if evidence.passed is None:
            raise GoalError("repository verification evidence unknown")
        report = json.loads(
            self.blobs.read_bytes(
                next(r.blob for r in evidence.records if r.role == "report")
            )
        )
        outputs = [
            self.blobs.read_bytes(SessionBlobRef.from_manifest_entry(ref)).decode()
            for ref in report["outputs"]
        ]
        result = json.loads("".join(outputs))
        validate_check_result(result, batch.source["check"])
        expected_identity = {
            "goal_id": batch.goal_id,
            "revision": batch.revision,
            "epoch": batch.epoch,
            "operation_id": batch.operation_id,
        }
        if (
            result["identity"] != expected_identity
            or result["package_sha256"] != self.task.digest
            or result["inventory"] != plain(batch.source["inventory"])
            or result["current"] is not True
            or result["check"] != batch.source["check"]
        ):
            raise GoalError("repository check identity mismatch")
        if any(
            type(row.get("exit_code")) is not int
            or row["exit_code"] not in {0, 1}
            or type(row.get("collected")) is not int
            or type(row.get("skipped")) is not int
            or row["collected"] <= row["skipped"]
            or (row["exit_code"] == 1 and not row.get("failed"))
            for row in result["results"]
        ):
            raise GoalError("repository check environment or collection unknown")
        passed = all(
            row["exit_code"] == 0
            and row["collected"] > row["skipped"]
            and not row["failed"]
            for row in result["results"]
        )
        if passed != evidence.passed or not result["results"]:
            raise GoalError("repository check outcome mismatch")
        return {**result, "passed": passed, "run_id": run.run_id}

    def _planning_call_failure(self, batch, run):
        """Read existing Work facts; a failed call is not an invalid model plan."""
        for entry in self.log.query(operation_id=batch.operation_id):
            if (
                entry.run_id != run.run_id
                or entry.session_id != self.session.session_id
                or entry.payload.get("kind") != "AgentInvocationCompleted"
            ):
                continue
            for message in entry.payload.get("payload", {}).get("messages", []):
                if message.get("stopReason") == "error":
                    info = message.get("errorInfo") or {}
                    code = info.get("code", "unknown")
                    return code if isinstance(code, str) else "unknown"
        return None

    def _observations(self, basis, facts):
        evidence, routes, rejections = [], [], []
        planning = invalid = stalled = 0
        knowledge = set()
        delegated_reports = {}
        from ._goal_delegation_report import observe_delegation

        for batch in facts.batches:
            if batch.goal_id != basis.goal.id:
                continue
            phase = batch.source.get("phase")
            planning += phase == "planning"
            run = self._run(batch, facts)
            if run is None:
                continue
            delegated = observe_delegation(self, batch, run, delegated_reports)
            if phase == "planning":
                if run.status == "cancelled":
                    continue
                failure = self._planning_call_failure(batch, run)
                if failure is not None:
                    evidence.append(
                        {
                            "id": batch.operation_id,
                            "phase": "planning_call_failure",
                            "revision": batch.revision,
                            "epoch": batch.epoch,
                            "error_code": failure,
                        }
                    )
                    continue
                try:
                    proposal = self._proposal(batch, run)
                    routes.append(
                        {"proposal_id": batch.operation_id, "proposal": proposal.data()}
                    )
                except ProposalRejected as error:
                    invalid += 1
                    rejections.append(
                        {"proposal_id": batch.operation_id, "reason": str(error)}
                    )
                continue
            invalid = 0
            item = {
                "id": batch.operation_id,
                "phase": phase,
                "status": run.status,
                "revision": batch.revision,
                "epoch": batch.epoch,
                "action": plain(batch.source.get("action")),
            }
            if phase in {"check", "verification"}:
                result = self._verification(batch, run)
                item["result"] = result
                key = canonical(
                    {
                        "inventory": result["inventory"],
                        "check": result["check"],
                        "failures": [r["failed"] for r in result["results"]],
                    }
                )
                progress = key not in knowledge
            elif phase in {"inspect", "repair"}:
                if delegated and run.status != "completed":
                    item["result"] = {
                        "status": "partial",
                        "reason": "delegated_work_not_completed",
                    }
                    evidence.append(item)
                    stalled += 1
                    continue
                result = self._report(batch, run, "repository_report")
                if result["before"] != plain(batch.source["inventory"]):
                    raise GoalError("repository execution input mismatch")
                item["result"] = result
                key = canonical({"inventory": result["after"], "phase": phase})
                progress = (
                    result["before"] != result["after"]
                    if phase == "repair"
                    else key not in knowledge
                )
            elif phase == "review":
                if run.status != "completed":
                    raise GoalError("review Work did not complete")
                result = self._report(batch, run, "repository_review")
                value = result["review"]
                validate_review(value)
                original = next(
                    (
                        row["result"]
                        for row in evidence
                        if row["phase"] == "verification"
                        and row["id"] == value["identity"]["verification_operation_id"]
                    ),
                    None,
                )
                if original is None:
                    raise GoalError("review verification missing")
                identity = self._review_identity(basis, original)
                identity.update(
                    goal_id=batch.goal_id, revision=batch.revision, epoch=batch.epoch
                )
                if (
                    value["identity"] != identity
                    or value["command_id"] != batch.command_id
                    or digest(canonical(value).encode())
                    != batch.source.get("review_sha256")
                    or value["review_id"] != batch.source.get("review_id")
                    or value["identity"]["inventory"]
                    != plain(batch.source["inventory"])
                    or (value["decision"] == "approved" and not original["passed"])
                ):
                    raise GoalError("review identity or content mismatch")
                item["result"] = value
                record = next(
                    r
                    for r in project_work_evidence(
                        self.log.query(operation_id=batch.operation_id)
                    )
                    if r.role == "repository_review" and r.run_id == run.run_id
                )
                item["report_ref"] = {
                    "run_id": record.run_id,
                    "sequence": record.sequence,
                    "event_id": record.event_id,
                    "blob": record.blob.manifest_entry(),
                }
                key = canonical(
                    {
                        "review_findings": value["findings"],
                        "inventory": value["identity"]["inventory"],
                    }
                )
                progress = value["decision"] == "rejected" and key not in knowledge
            else:
                raise GoalError("unknown repository Work phase")
            knowledge.add(key)
            stalled = 0 if progress else stalled + 1
            evidence.append(item)
        return evidence, routes, rejections, planning, invalid, stalled

    async def assess(self, basis, facts):
        return self.assess_now(basis, facts)

    def _review_identity(self, basis, result):
        return {
            "policy_id": self.task.policy_id,
            "scope_id": basis.header.scope_id,
            "session_id": basis.header.session_id,
            "goal_id": basis.goal.id,
            "revision": basis.goal.revision,
            "epoch": basis.goal.epoch,
            "task_sha256": self.task.digest,
            "inventory": result["inventory"],
            "verification_operation_id": result["identity"]["operation_id"],
            "verification_run_id": result["run_id"],
        }

    def assess_now(self, basis, facts):
        try:
            snapshot, *_ = self._current_inputs(basis)
            if facts.busy or facts.unresolved:
                return GoalAssessment(basis, "more_evidence", "work_busy_or_unresolved")
            evidence, _, _, _, invalid, stalled = self._observations(basis, facts)
            failures = [
                row
                for row in evidence
                if row["phase"] == "planning_call_failure"
                and row["revision"] == basis.goal.revision
                and row["epoch"] == basis.goal.epoch
            ]
            reason = (
                "planning_model_call_failed:" + failures[-1]["error_code"]
                if failures
                else basis.goal.reason
            )
            if failures or (
                basis.goal.status == "paused"
                and reason.startswith("planning_model_call_failed:")
            ):
                return GoalAssessment(
                    basis, "needs_user", reason, proof={"validity": "current"}
                )
            matches = [
                row["result"]
                for row in evidence
                if row["phase"] == "verification"
                and row["revision"] == basis.goal.revision
                and row["epoch"] == basis.goal.epoch
                and row["result"]["inventory"] == snapshot
            ]
            reviews = [
                row
                for row in evidence
                if row["phase"] == "review"
                and row["revision"] == basis.goal.revision
                and row["epoch"] == basis.goal.epoch
                and row["result"]["identity"]["inventory"] == snapshot
            ]
            if any(row["result"]["decision"] == "rejected" for row in reviews):
                return GoalAssessment(basis, "more_evidence", "review_rejected")
            if matches and matches[-1]["passed"]:
                result = matches[-1]
                identity = self._review_identity(basis, result)
                approved = [
                    row
                    for row in reviews
                    if row["result"]["identity"] == identity
                    and row["result"]["decision"] == "approved"
                ]
                if not approved:
                    return GoalAssessment(
                        basis, "more_evidence", "review_required", proof=identity
                    )
                if len(approved) != 1:
                    raise GoalError("ambiguous review")
                return GoalAssessment(
                    basis,
                    "satisfied",
                    "repository_contract_and_review_satisfied",
                    coverage=tuple(r.id for r in self.task.requirements),
                    operations=(result["identity"]["operation_id"], approved[0]["id"]),
                    proof={
                        **identity,
                        "review_operation_id": approved[0]["id"],
                        "review_id": approved[0]["result"]["review_id"],
                    },
                )
            if basis.goal.status == "completed":
                return GoalAssessment(
                    basis, "more_evidence", "repository_verification_required"
                )
            if invalid >= 3 or stalled >= 2:
                return GoalAssessment(basis, "needs_user", "repository_planning_limit")
            return GoalAssessment(
                basis, "more_evidence", "repository_verification_required"
            )
        except (ValueError, OSError, KeyError, StopIteration) as error:
            return GoalAssessment(
                basis,
                "needs_user",
                f"repository_evidence_unknown:{error}",
                proof={"validity": "unknown"},
            )

    def confirm_current(self, assessment):
        try:
            return self._current_inputs(assessment.basis)[0] == plain(
                assessment.proof["inventory"]
            )
        except (ValueError, OSError, KeyError):
            return False

    def _implementation(self, basis, proposal, snapshot, source, tests, code, evidence):
        action = proposal.action
        if action.name == "stop":
            return PolicyStop("model_requested_stop:" + proposal.rationale)
        op_id = "goal-op-" + uuid4().hex
        common = {"inventory": snapshot, "basis": basis.identity}
        if action.name in {"check", "verify_all"}:
            check = "all" if action.name == "verify_all" else action.targets[0]
            request = {
                "package": str(self.task.path),
                "package_sha256": self.task.digest,
                "inventory": snapshot,
                "check": check,
                "identity": {
                    "goal_id": basis.goal.id,
                    "revision": basis.goal.revision,
                    "epoch": basis.goal.epoch,
                    "operation_id": op_id,
                },
            }
            command = shlex.join(
                [
                    self.task.config["python"],
                    "-I",
                    "-S",
                    str(self.task.path.parent / "driver.py"),
                ]
            )
            operation = WorkOperation(
                op_id,
                "VerifyCodingCommand",
                basis.header.session_id,
                "coding",
                {
                    "command": command,
                    "execution": {
                        "stdin": canonical(request),
                        "cwd": str(self.root),
                        "env": [["PYTHONDONTWRITEBYTECODE", "1"]],
                    },
                },
            )
            return WorkCandidate(
                basis,
                operation,
                WorkRunSpec(
                    plan_id="verification:" + op_id,
                    steps=(WorkStepSpec("report"), WorkStepSpec("validation")),
                ),
                {
                    **common,
                    "phase": "verification" if check == "all" else "check",
                    "check": check,
                },
            )
        if action.name == "inspect":
            operation = WorkOperation(
                op_id, "InspectRepository", basis.header.session_id, "coding", {}
            )
            spec = WorkRunSpec(
                plan_id="inspect:" + op_id, steps=(WorkStepSpec("inspect"),)
            )
            executor = RepositoryReport(self, snapshot, targets=action.targets)
        else:
            descriptor = MethodDescriptor(
                **json.loads((self.task.path.parent / "method.json").read_bytes())
            )
            loader = SimpleNamespace(discover_methods=lambda cwd: [descriptor])
            turns = MethodDomainRuntime(
                profile=MethodDomainProfile(domain="coding"), method_loader=loader
            ).prepare_turns(
                MethodDomainRequest(
                    "Implement the admitted action.\n"
                    + canonical(
                        {
                            "proposal": proposal.data(),
                            "material": self.task.material(),
                            "evidence": evidence,
                        }
                    ),
                    self.root,
                    method_policy=MethodPolicy.explicit(descriptor.id),
                )
            )
            prepared = project_prepared_session_work_turns(
                turns, images=None, follow_up_messages=()
            )
            if (
                len(prepared) != 1
                or prepared[0].step_id != "repair"
                or prepared[0].planned_constraint
                or prepared[0].audit_policy
            ):
                raise GoalError("protected repository Method changed")
            original = SessionTurnExecutor(
                session=self.session,
                profile=CODING_WORK_PROFILE,
                project_event_facts=project_coding_runtime_event,
                turns=prepared,
            )
            operation = prepared[0].to_operation(
                profile=CODING_WORK_PROFILE,
                session_id=basis.header.session_id,
                operation_id=op_id,
            )
            spec = prepared[0].to_run_spec(profile=CODING_WORK_PROFILE, run_id=None)
            if self.delegation is not None:
                from ._goal_delegation import KEY

                operation, scoped, selection = self.delegation.prepare(
                    basis, operation, spec, prepared[0]
                )
                common[KEY] = selection
            else:
                operation, original = self._bind_source(operation, spec, original)
                scoped = ScopedSessionWork(
                    original,
                    session=self.session,
                    allowance=self.allowance,
                    policy=self.tool_policy,
                    phase="repair",
                )
            executor = RepositoryReport(self, snapshot, scoped)
        self.prepared[op_id] = WorkExecutionBinding(
            executor, executor if action.name == "implement" else None
        )
        return WorkCandidate(
            basis,
            operation,
            spec,
            {**common, "phase": "repair" if action.name == "implement" else "inspect"},
        )


class RepositoryPolicy(BatchPlanningPolicy, RepositoryDomain):
    limits = LIMITS
    parse_proposal = staticmethod(parse_repository_proposal)
    make_prompt = staticmethod(prompt)
    planning_material = RepositoryDomain.planning_material

    async def prepare(self, basis, work_facts):
        if self.pending_review is not None:
            return review_candidate(self, basis, self.pending_review)
        reason = self.assess_now(basis, work_facts).reason
        if reason == "review_required":
            raise GoalError("review_required")
        if reason.startswith("planning_model_call_failed:"):
            return PolicyStop(reason)
        return await super().prepare(basis, work_facts)


class RepositoryReport:
    def __init__(self, policy, before, delegate=None, targets=()):
        self.policy, self.before, self.delegate = policy, before, delegate
        self.targets = targets

    async def execute(self, operation, context):
        if self.policy.task.snapshot() != self.before:
            raise GoalError("repository changed after admission")
        if self.delegate is not None:
            await self.delegate.execute(operation, context)
        report = {
            "version": 1,
            "operation_id": operation.operation_id,
            "run_id": context.run_id,
            "before": self.before,
            "after": self.policy.task.snapshot(),
        }
        if self.targets:
            names = {
                name
                for target in self.targets
                for name in self.policy.task.config["inspect_files"][target]
            }
            report["files"] = {
                name: (self.policy.root / name).read_text() for name in sorted(names)
            }
        publish_report(
            self.policy.blobs,
            context,
            report,
            role="repository_report",
            session_id=operation.session_id,
        )

    async def cancel_and_wait(self, operation, context):
        return await self.delegate.cancel_and_wait(operation, context)


class _RepositoryGoal(CodingGoal):
    _repository_busy = False

    def execution_contexts(self):
        self._open_for_commands()
        return self._delegation.views() if self._delegation is not None else ()

    def set_execution_context(self, choice):
        self._open_for_commands()
        if self._repository_busy or self._delegation is None:
            raise GoalError("delegated context selection unavailable")
        self._delegation.select(choice)

    async def release_execution_context(self, ref):
        self._open_for_commands()
        if self._repository_busy or self._delegation is None:
            raise GoalError("delegated context release unavailable")
        self._repository_busy = True
        try:
            await self._delegation.release(ref)
        finally:
            self._repository_busy = False

    def review_basis(self, goal_id):
        self._open_for_commands()
        core = self.controller
        basis = GoalBasis(core.header, core.query(goal_id), core.history.sequence)
        facts = core.facts()
        if facts.busy or facts.unresolved:
            raise GoalError("review execution unresolved")
        snapshot = self._policy._current_inputs(basis)[0]
        evidence, *_ = self._policy._observations(basis, facts)
        results = [
            row["result"]
            for row in evidence
            if row["phase"] == "verification"
            and row["revision"] == basis.goal.revision
            and row["epoch"] == basis.goal.epoch
            and row["result"]["inventory"] == snapshot
        ]
        if not results:
            raise GoalError("no current full verification")
        return self._policy._review_identity(basis, results[-1]), results[-1]["passed"]

    async def advance(self, goal_id, **kwargs):
        self._open_for_commands()
        if self._repository_busy:
            raise GoalError("repository Goal busy")
        self._repository_busy = True
        try:
            command_id = kwargs.get("command_id")
            if any(
                b.command_id == command_id and b.source.get("phase") == "review"
                for b in self.controller.history.batches
            ):
                raise GoalError("command belongs to review")
            if command_id not in self.controller.history.commands:
                view = await self.query(goal_id)
                if view.reason == "review_required":
                    raise GoalError("review_required: supply a trusted review")
            return await super().advance(goal_id, **kwargs)
        finally:
            self._repository_busy = False

    async def submit_review(
        self,
        goal_id,
        *,
        command_id,
        review_id,
        expected_identity,
        decision,
        reviewer,
        reason,
        coverage,
        findings,
    ):
        """Trusted host only; one original Work, no background queue or model call."""
        self._open_for_commands()
        if self._repository_busy:
            raise GoalError("repository Goal busy")
        self._repository_busy = True
        try:
            value = review_value(
                command_id=command_id,
                review_id=review_id,
                identity=expected_identity,
                decision=decision,
                reviewer=reviewer,
                reason=reason,
                coverage=coverage,
                findings=findings,
            )
            fingerprint = digest(canonical(value).encode())
            core = self.controller
            old = [
                b
                for b in core.history.batches
                if b.command_id == command_id or b.source.get("review_id") == review_id
            ]
            if old:
                if (
                    len(old) != 1
                    or old[0].goal_id != goal_id
                    or old[0].command_id != command_id
                    or old[0].source.get("review_sha256") != fingerprint
                ):
                    raise GoalError(
                        "review id or command reused with different content"
                    )
                return await super().advance(
                    goal_id,
                    command_id=command_id,
                    revision=value["identity"]["revision"],
                    epoch=value["identity"]["epoch"],
                )
            if command_id in core.history.commands:
                raise GoalError("command has no matching review intent")
            identity, passed = self.review_basis(goal_id)
            if value["identity"] != identity or (decision == "approved" and not passed):
                raise GoalError("review basis changed or verification not passed")
            for batch in core.history.batches:
                if (
                    batch.goal_id == goal_id
                    and batch.source.get("phase") == "review"
                    and batch.revision == identity["revision"]
                    and batch.epoch == identity["epoch"]
                    and plain(batch.source["inventory"]) == identity["inventory"]
                ):
                    raise GoalError(
                        "same candidate already reviewed; conflicting review"
                    )
            self._policy.pending_review = value
            return await super().advance(
                goal_id,
                command_id=command_id,
                revision=identity["revision"],
                epoch=identity["epoch"],
            )
        finally:
            self._policy.pending_review = None
            self._repository_busy = False


async def open_repository_goal(
    *,
    task,
    data_root,
    model=None,
    transcript_retained_until=None,
    execution_policy=None,
):
    return await _RepositoryGoal._open(
        workspace=task.root,
        data_root=data_root,
        model=model,
        model_planning=True,
        profile=RepositoryProfile(task, execution_policy),
        transcript_retained_until=transcript_retained_until,
    )


def inspect_repository_goal(*, task, data_root, session_id, goal_id):
    return _inspect_goal(
        workspace=task.root,
        data_root=data_root,
        session_id=session_id,
        goal_id=goal_id,
        profile=RepositoryProfile(task),
    )
