"""Private review encoding and Work binding, owned by the repository adapter."""

from __future__ import annotations

from uuid import uuid4

from loushang.harnesswork import WorkOperation, WorkRunSpec, WorkStepSpec
from loushang.harnesswork.goal import GoalError, WorkCandidate
from loushang.harnesswork.goal.records import canonical, plain
from loushang.harnesswork.ports import WorkExecutionBinding

from ._goal_planning_work import publish_report
from ._goal_repository_task import digest

_REQUIREMENTS = {f"RC-0{i}" for i in range(1, 7)}
_IDENTITY = {
    "policy_id",
    "scope_id",
    "session_id",
    "goal_id",
    "revision",
    "epoch",
    "task_sha256",
    "inventory",
    "verification_operation_id",
    "verification_run_id",
}


def validate_review(value):
    if not isinstance(value, dict) or set(value) != {
        "version",
        "command_id",
        "review_id",
        "identity",
        "decision",
        "reviewer",
        "reason",
        "coverage",
        "findings",
    }:
        raise GoalError("invalid review fields")
    if type(value["version"]) is not int or value["version"] != 1:
        raise GoalError("unsupported review version")
    for key in ("command_id", "review_id", "reviewer", "reason"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise GoalError("invalid review text")
    if value["decision"] not in ("approved", "rejected"):
        raise GoalError("invalid review decision")
    identity = value["identity"]
    if not isinstance(identity, dict) or set(identity) != _IDENTITY:
        raise GoalError("invalid review identity")
    for key in _IDENTITY - {"inventory", "revision", "epoch"}:
        if not isinstance(identity[key], str) or not identity[key].strip():
            raise GoalError("invalid review identity text")
    if any(
        type(identity[k]) is not int or identity[k] < 1 for k in ("revision", "epoch")
    ):
        raise GoalError("invalid review revision")
    if not isinstance(identity["inventory"], dict) or not identity["inventory"]:
        raise GoalError("invalid review inventory")
    coverage = value["coverage"]
    if (
        not isinstance(coverage, list)
        or any(not isinstance(v, str) for v in coverage)
        or len(coverage) != len(set(coverage))
        or not set(coverage) <= _REQUIREMENTS
    ):
        raise GoalError("invalid review coverage")
    findings = value["findings"]
    if not isinstance(findings, list):
        raise GoalError("invalid review findings")
    for finding in findings:
        if (
            not isinstance(finding, dict)
            or set(finding) != {"requirement_id", "evidence", "expected", "actual"}
            or any(not isinstance(v, str) or not v.strip() for v in finding.values())
            or finding["requirement_id"] not in coverage
        ):
            raise GoalError(
                "review requires a covered requirement and concrete finding"
            )
    if value["decision"] == "approved":
        if findings or not {"RC-05", "RC-06"} <= set(coverage):
            raise GoalError(
                "approval requires scope coverage and no unresolved findings"
            )
    elif not findings:
        raise GoalError("rejection requires concrete findings")
    if len(canonical(value).encode()) > 32 * 1024:
        raise GoalError("review exceeds bounded content size")


def review_value(**fields):
    # Freeze the caller's mutable collections before any suspension.
    import json

    value = json.loads(canonical({"version": 1, **fields}))
    validate_review(value)
    return value


def review_candidate(policy, basis, value):
    snapshot = policy._current_inputs(basis)[0]
    identity = value["identity"]
    if (
        snapshot != identity["inventory"]
        or identity["goal_id"] != basis.goal.id
        or identity["revision"] != basis.goal.revision
        or identity["epoch"] != basis.goal.epoch
    ):
        raise GoalError("review basis changed")
    op_id = "goal-review-" + uuid4().hex
    policy.prepared[op_id] = WorkExecutionBinding(ReviewWork(policy, value))
    return WorkCandidate(
        basis,
        WorkOperation(
            op_id, "ReportRepositoryReview", basis.header.session_id, "coding", {}
        ),
        WorkRunSpec(plan_id="review:" + op_id, steps=(WorkStepSpec("review"),)),
        {
            "phase": "review",
            "basis": basis.identity,
            "inventory": snapshot,
            "review_id": value["review_id"],
            "review_sha256": digest(canonical(value).encode()),
        },
    )


class ReviewWork:
    def __init__(self, policy, value):
        self.policy, self.value = (
            policy,
            review_value(**{k: v for k, v in value.items() if k != "version"}),
        )

    async def execute(self, operation, context):
        if self.policy.task.snapshot() != plain(self.value["identity"]["inventory"]):
            raise GoalError("repository changed before review publication")
        publish_report(
            self.policy.blobs,
            context,
            {
                "version": 1,
                "operation_id": operation.operation_id,
                "run_id": context.run_id,
                "review": self.value,
            },
            role="repository_review",
            session_id=operation.session_id,
        )
        if self.policy.task.snapshot() != self.value["identity"]["inventory"]:
            raise GoalError("repository changed during review publication")
