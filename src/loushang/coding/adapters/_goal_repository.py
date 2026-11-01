"""Private local repository profile over the original Coding Goal owner and Work."""

from __future__ import annotations

import json
import shlex
from dataclasses import replace
from functools import partial
from types import SimpleNamespace
from uuid import uuid4

from loushang.foundation.platform_paths import resolve_platform_home
from loushang.harness.artifacts import SessionBlobRef
from loushang.harness.transcript.source_reader import TranscriptSourceReader
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


def _repository_limits(task):
    """Optional bounded host-closeout policy, frozen with the private task."""
    content = task.path.read_bytes()
    if digest(content) != task.digest:
        raise GoalError("task manifest changed")
    config = json.loads(content)
    if "closeout_budget" not in config:
        return dict(LIMITS)
    value = config["closeout_budget"]
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "work_intents", "planning_intents"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or any(type(value[k]) is not int for k in ("work_intents", "planning_intents"))
        or not 1 <= value["work_intents"] <= 6
        or not 1 <= value["planning_intents"] <= 2
    ):
        raise GoalError("invalid repository closeout budget")
    return {
        **LIMITS,
        "work_intents": value["work_intents"],
        "planning_intents": value["planning_intents"],
        "inspect_intents": 1,
        "repair_intents": 1,
        "verification_intents": 1,
        "review_intents": 1,
        "check_intents": 0,
    }


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


def _host_request(goal_id, command_id, revision, epoch, expected_inventory):
    if (
        any(not isinstance(v, str) or not v.strip() for v in (goal_id, command_id))
        or any(type(v) is not int or v < 1 for v in (revision, epoch))
        or not isinstance(expected_inventory, dict)
        or not expected_inventory
        or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v
            for k, v in expected_inventory.items()
        )
    ):
        raise GoalError("invalid host verification request")
    return {
        "version": 1,
        "goal_id": goal_id,
        "command_id": command_id,
        "revision": revision,
        "epoch": epoch,
        "expected_inventory": dict(expected_inventory),
    }


def _host_intent(batch, history):
    if "host_verification" not in batch.source:
        return None
    value = plain(batch.source["host_verification"])
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "version",
            "goal_id",
            "command_id",
            "revision",
            "epoch",
            "expected_inventory",
        }
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise GoalError("unsupported host verification request")
    _host_request(
        value["goal_id"],
        value["command_id"],
        value["revision"],
        value["epoch"],
        value["expected_inventory"],
    )
    expected = _host_request(
        batch.goal_id,
        batch.command_id,
        batch.revision,
        batch.epoch,
        plain(batch.source.get("inventory")),
    )
    basis = plain(batch.source.get("basis", {}))
    if not 0 < batch.intent_sequence <= len(history.records):
        raise GoalError("host verification intent missing")
    intent = history.records[batch.intent_sequence - 1]
    if (
        value != expected
        or intent.kind != "batch_intent"
        or canonical(basis) != canonical(intent.data.get("basis"))
        or not isinstance(basis, dict)
        or batch.source.get("phase") != "verification"
        or batch.source.get("check") != "all"
        or "proposal_id" in batch.source
        or basis.get("goal_id") != batch.goal_id
        or basis.get("revision") != batch.revision
        or basis.get("epoch") != batch.epoch
        or any(type(basis.get(k)) is not int for k in ("revision", "epoch", "sequence"))
        or basis["sequence"] != batch.intent_sequence - 1
    ):
        raise GoalError("host verification intent mismatch")
    return value


def prompt(operation_id, content):
    return (
        "Choose one next action and a revisable route for the supplied repository task from its frozen requirements and current facts. "
        "Return ONE JSON object, no fences/tools. Keys exactly: next_action, targets, "
        "requirement_ids, rationale, expected_evidence, remaining_route, change_reason, evidence_refs. "
        "rationale/change_reason are strings <=2048 UTF-8 bytes; change_reason may be empty. "
        "targets/requirement_ids/expected_evidence/evidence_refs are string arrays. "
        "remaining_route is 1-6 objects with action and targets, first matching next_action. "
        "inspect targets: nonempty subset of reader,operations,tests. implement targets: reader,tests. "
        "check targets: exactly one of reader,regression. All checks include the independent contract. "
        "verify_all and stop targets: []. Every non-stop action covers RC-01 through RC-06. "
        "An implement Work may edit only the files declared in allowed_files; targets describe focus. "
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
        self.limits = _repository_limits(task)

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
            "planning_limits": self.limits,
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
        reader = None
        if manager is not None:
            reader = TranscriptSourceReader(
                session_file=manager.session_file,
                conversation_id=session_id,
                store_state_root=resolve_platform_home() / "state/session-stores",
            )
            policy.source_reader = reader
        try:
            assessment = policy.assess_now(basis, facts)
            return replace(
                _view(state, assessment, unresolved=unresolved),
                planning=policy.trace(basis, facts),
            )
        finally:
            if reader is not None:
                try:
                    reader.close()
                except BaseException as error:
                    raise RepositorySourceCleanupError(reader, error) from error


class RepositorySourceCleanupError(RuntimeError):
    """Retain the independent cold reader; retry owner.close() on this object."""

    def __init__(self, owner, error):
        super().__init__("repository source reader cleanup pending")
        self.owner, self.error = owner, error


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
        self.limits = _repository_limits(task)
        self.log, self.prepared = event_log, prepared
        self.allowance, self.tool_policy, self.history = allowance, tool_policy, history
        self.pending_review = None
        self.pending_verification = None
        self.transcript_source = transcript_source
        self.delegation = None
        self.source_reader = None

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
        if self.delegation is not None:
            self.delegation._available()
        if (
            basis.header.policy_id != self.task.policy_id
            or basis.goal.limit != self.limits["work_intents"]
            or basis.goal.metadata.get("task_sha256") != self.task.digest
            or plain(basis.goal.metadata.get("planning_limits")) != self.limits
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
            if not self._closeout_admits(
                candidate.basis,
                candidate.source.get("phase"),
                own_operation=candidate.operation.operation_id,
            ):
                return False
            if "host_verification" in candidate.source:
                value = candidate.source["host_verification"]
                if (
                    self.session.pending_message_count
                    or self.pending_verification is None
                    or plain(value) != self.pending_verification
                    or value["expected_inventory"] != candidate.source["inventory"]
                    or not self._host_capacity(
                        candidate.basis, candidate.operation.operation_id
                    )
                ):
                    return False
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

    def _host_capacity(self, basis, own_operation=None):
        history = self.history()
        batches = [b for b in history.batches if b.goal_id == basis.goal.id]
        own = [b for b in batches if b.operation_id == own_operation]
        if own and (
            len(own) != 1
            or _host_intent(own[0], history) != self.pending_verification
            or own[0].source.get("basis") != basis.identity
            or own[0].intent_sequence != basis.sequence + 1
        ):
            return False
        return basis.goal.limit - len(batches) + len(own) >= 2

    def confirm_resume(self, basis, work_facts):
        try:
            self._current_inputs(basis)
            _, _, _, count, invalid, stalled = self._observations(basis, work_facts)
            if invalid >= 3 or stalled >= 2:
                return False
            if "inspect_intents" in self.limits:
                # Resume changes epoch: host closeout needs a fresh verification,
                # but need not spend another planning intent after implementation.
                return self._closeout_admits(
                    basis, "planning"
                ) or self._closeout_admits(basis, "verification")
            return count < self.limits["planning_intents"]
        except (ValueError, OSError, KeyError):
            return False

    def planning_material(self, snapshot):
        material = {
            "acceptance": self.task.config["requirements"],
            "allowed_files": self.task.allowed,
            "inspect_files": self.task.config["inspect_files"],
        }
        if "inspect_intents" in self.limits:
            material["host_closeout"] = {
                "model_actions": ["inspect", "implement", "stop"],
                "work_routes": [
                    ["planning", "repair", "verification", "review"],
                    [
                        "planning",
                        "inspect",
                        "planning",
                        "repair",
                        "verification",
                        "review",
                    ],
                ],
                "instruction": "Work routes describe phases, not proposal action names. Use only model_actions in next_action and remaining_route. Inspect only if needed and affordable; implementation receives the full allowed source. After one implement Work, the host selects full verification and independent review.",
            }
        return material

    def _closeout_admits(self, basis, phase, own_operation=None):
        if "inspect_intents" not in self.limits:
            return True
        batches = [b for b in self.history().batches if b.goal_id == basis.goal.id]
        own = [b for b in batches if b.operation_id == own_operation]
        if own:
            if (
                len(own) != 1
                or own[0].source.get("phase") != phase
                or canonical(own[0].source.get("basis")) != canonical(basis.identity)
                or own[0].intent_sequence != basis.sequence + 1
            ):
                return False
            batches.remove(own[0])
        counts = {
            p: sum(b.source.get("phase") == p for b in batches)
            for p in (
                "planning",
                "inspect",
                "repair",
                "verification",
                "review",
                "check",
            )
        }
        if phase in {"planning", "inspect"} and counts["repair"]:
            return False
        required = {
            "planning": ("planning", "repair", "verification", "review"),
            "inspect": ("inspect", "planning", "repair", "verification", "review"),
            "repair": ("repair", "verification", "review"),
            "verification": ("verification", "review"),
            "review": ("review",),
        }.get(phase, ())
        return (
            bool(required)
            and basis.goal.limit - len(batches) >= len(required)
            and all(counts[p] < self.limits[f"{p}_intents"] for p in required)
        )

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
        history = self.history()
        if "inspect_intents" in self.limits:
            batches = [b for b in history.batches if b.goal_id == basis.goal.id]
            for phase in (
                "planning",
                "inspect",
                "repair",
                "verification",
                "review",
                "check",
            ):
                if (
                    sum(b.source.get("phase") == phase for b in batches)
                    > self.limits[f"{phase}_intents"]
                ):
                    raise GoalError("repository closeout history exceeds budget")
        evidence, routes, rejections = [], [], []
        planning = invalid = stalled = 0
        knowledge = set()
        delegated_reports = {}
        from ._goal_delegation_report import observe_delegation

        for batch in facts.batches:
            if batch.goal_id != basis.goal.id:
                continue
            _host_intent(batch, history)
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

    def _verification_candidate(self, basis, snapshot, check, op_id):
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
                "inventory": snapshot,
                "basis": basis.identity,
                "phase": "verification" if check == "all" else "check",
                "check": check,
            },
        )

    def _implementation(self, basis, proposal, snapshot, source, tests, code, evidence):
        action = proposal.action
        if action.name == "stop":
            return PolicyStop("model_requested_stop:" + proposal.rationale)
        if "inspect_intents" in self.limits and (
            action.name not in {"inspect", "implement"}
            or not self._closeout_admits(
                basis, "repair" if action.name == "implement" else "inspect"
            )
        ):
            return PolicyStop("repository_closeout_budget")
        op_id = "goal-op-" + uuid4().hex
        common = {"inventory": snapshot, "basis": basis.identity}
        if action.name in {"check", "verify_all"}:
            check = "all" if action.name == "verify_all" else action.targets[0]
            return self._verification_candidate(basis, snapshot, check, op_id)
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
                from loushang.harness.multiagent import MultiAgentError

                from ._goal_delegation import KEY

                try:
                    operation, scoped, selection = self.delegation.prepare(
                        basis, operation, spec, prepared[0]
                    )
                except MultiAgentError as error:
                    return PolicyStop("child_session_admission:" + error.code)
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

    def _planning_remaining(self, basis, batches):
        remaining = super()._planning_remaining(basis, batches)
        if "inspect_intents" in self.limits:
            remaining.update(
                {
                    f"{phase}_intents": self.limits[f"{phase}_intents"]
                    - sum(b.source.get("phase") == phase for b in batches)
                    for phase in (
                        "inspect",
                        "repair",
                        "verification",
                        "review",
                        "check",
                    )
                }
            )
        return remaining

    def _planning(self, basis, snapshot, evidence, routes, rejections):
        if not self._closeout_admits(basis, "planning"):
            return PolicyStop("repository_closeout_budget")
        return super()._planning(basis, snapshot, evidence, routes, rejections)

    async def prepare(self, basis, work_facts):
        if self.pending_review is not None:
            if not self._closeout_admits(basis, "review"):
                raise GoalError("repository closeout review budget exhausted")
            return review_candidate(self, basis, self.pending_review)
        if self.pending_verification is not None:
            if not self._closeout_admits(basis, "verification"):
                raise GoalError("repository closeout verification budget exhausted")
            snapshot = self._current_inputs(basis)[0]
            if snapshot != self.pending_verification[
                "expected_inventory"
            ] or not self._host_capacity(basis):
                raise GoalError("host verification basis or capacity changed")
            candidate = self._verification_candidate(
                basis, snapshot, "all", "goal-op-" + uuid4().hex
            )
            return replace(
                candidate,
                source={
                    **candidate.source,
                    "host_verification": self.pending_verification,
                },
            )
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
                b.command_id == command_id and "host_verification" in b.source
                for b in self.controller.history.batches
            ):
                raise GoalError("command belongs to host verification")
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

    async def verify_current(
        self,
        goal_id,
        *,
        command_id,
        revision,
        epoch,
        expected_inventory,
    ):
        """Trusted host selection of original full verification; never plans."""
        self._open_for_commands()
        if self._repository_busy:
            raise GoalError("repository Goal busy")
        self._repository_busy = True
        try:
            value = _host_request(
                goal_id, command_id, revision, epoch, expected_inventory
            )
            core = self.controller
            old = [b for b in core.history.batches if b.command_id == command_id]
            if old:
                if len(old) != 1 or _host_intent(old[0], core.history) != value:
                    raise GoalError("command has no matching host verification intent")
                return await super().advance(
                    goal_id, command_id=command_id, revision=revision, epoch=epoch
                )
            if command_id in core.history.commands:
                raise GoalError("command has no matching host verification intent")
            state = core.query(goal_id)
            if state.status != "active" or (state.revision, state.epoch) != (
                revision,
                epoch,
            ):
                raise GoalError("host verification requires current active Goal")
            facts = core.facts()
            if facts.busy or facts.unresolved or self._session.pending_message_count:
                raise GoalError("host verification execution unresolved")
            basis = GoalBasis(core.header, state, core.history.sequence)
            if self._policy._current_inputs(basis)[0] != value["expected_inventory"]:
                raise GoalError("host verification inventory changed")
            if not self._policy._host_capacity(basis):
                raise GoalError("host verification requires two Work slots")
            if not self._policy._closeout_admits(basis, "verification"):
                raise GoalError("repository closeout verification budget exhausted")
            if self._policy.assess_now(basis, facts).reason == "review_required":
                raise GoalError("review_required: supply a trusted review")
            self._policy.pending_verification = value
            return await super().advance(
                goal_id, command_id=command_id, revision=revision, epoch=epoch
            )
        finally:
            self._policy.pending_verification = None
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
            basis = GoalBasis(core.header, core.query(goal_id), core.history.sequence)
            if not self._policy._closeout_admits(basis, "review"):
                raise GoalError("repository closeout review budget exhausted")
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
