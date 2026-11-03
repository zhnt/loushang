"""Product-private planning and inspection bindings for the original Work runtime."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

from loushang.harness.artifacts import SessionBlobRef
from loushang.harness.effects import FilesystemEffect, ProcessEffect
from loushang.harness.policy import PolicyDecision, ToolPolicySubject
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.records import canonical, plain
from loushang.harnesswork.integrations.planning import (
    PlanningWork as _SharedPlanningWork,
)

from . import _goal_driver as driver
from ._goal_calculator import put
from ._goal_planning_response import capture_response
from ._goal_proposal import ProposalRejected, parse_proposal
from ._work_evidence import validate_evidence_fact, work_evidence_fact


def publish_report(blobs, context, value, *, role, session_id):
    blob = SessionBlobRef.from_manifest_entry(
        put(blobs, canonical(value).encode(), f"{context.run_id}/{role}.json")
    )
    fact = work_evidence_fact(blob, role=role, reported_step_id=context.step_id)
    validate_evidence_fact(fact, session_id=session_id)
    context.publish(fact)


class PlanningToolPolicy:
    """Only the current Method step may grant model file-tool access."""

    def __init__(self, workspace: Path, *, read_paths=None, write_paths=None):
        self.workspace = workspace.resolve()
        self.read_paths = None if read_paths is None else frozenset(read_paths)
        self.write_paths = (
            frozenset(write_paths)
            if write_paths is not None
            else {self.workspace / "calculator.py"}
        )
        self.step: str | None = None
        self.verification: Mapping[str, object] | None = None

    def evaluate(self, subject, /):
        deny = PolicyDecision.deny(
            "tool outside current Goal action", code="goal_action_scope"
        )
        if self.verification is not None and isinstance(subject, ToolPolicySubject):
            verifier = self.verification
            execution = verifier.get("execution", {})
            if (
                isinstance(execution, Mapping)
                and subject.tool_name == "bash"
                and subject.command is not None
                and subject.command.shell_payload == verifier.get("command")
                and subject.cwd == execution.get("cwd")
                and subject.arguments.get("stdin") == execution.get("stdin")
                and plain(subject.arguments.get("env")) == plain(execution.get("env"))
                and subject.effects == (ProcessEffect(subject.command.command),)
                and not subject.paths
            ):
                return PolicyDecision.allow()
            return deny
        if not isinstance(subject, ToolPolicySubject) or self.step not in {
            "inspect",
            "repair",
        }:
            return deny
        names = {"read"} if self.step == "inspect" else {"read", "edit", "write"}
        if (
            subject.tool_name not in names
            or subject.command is not None
            or not subject.paths
            or not subject.effects
        ):
            return deny
        paths = set()
        for item in subject.paths:
            if item.resolved_path is None or not Path(item.resolved_path).is_absolute():
                return deny
            path = Path(item.resolved_path).resolve()
            if not path.is_relative_to(self.workspace) or (
                self.read_paths is not None and path not in self.read_paths
            ):
                return deny
            paths.add(path)
        expected = "read" if subject.tool_name == "read" else "write"
        effect_paths = set()
        for effect in subject.effects:
            if not isinstance(effect, FilesystemEffect) or effect.operation != expected:
                return deny
            for value in effect.paths:
                if not Path(value).is_absolute():
                    return deny
                effect_paths.add(Path(value).resolve())
        if paths != effect_paths or (
            expected == "write" and not paths <= self.write_paths
        ):
            return deny
        return PolicyDecision.allow()


class ScopedSessionWork:
    """Bind the original Session overlay and retain it until its turn settles."""

    def __init__(self, delegate, *, session, allowance, policy, phase, execution=None):
        self.delegate, self.session, self.allowance = delegate, session, allowance
        self.policy, self.phase = policy, phase
        self.execution = execution

    async def execute(self, operation, context):
        if self.execution is None:
            raise GoalError("Goal model Work requires a Session execution binding")
        reservation = self.execution()
        if reservation is None:
            raise GoalError("Goal model Work requires a Session execution binding")
        self.allowance.enter(operation.operation_id, self.phase)
        step = context.step_id if self.phase == "repair" else None
        self.policy.step = step
        tools = (
            ["read"]
            if step == "inspect"
            else ["read", "edit", "write"]
            if step == "repair"
            else []
        )
        try:
            if self.phase == "repair" and step not in {"inspect", "repair"}:
                raise GoalError("unsupported Method step in model-planning profile")
            self.session.configure_execution(
                reservation, stream_fn=self.allowance.stream, tool_names=tuple(tools),
                additional_policy=self.policy,
            )
            result = await self.delegate.execute(operation, context)
            if self.phase == "repair" and self.allowance.failed:
                raise GoalError("repair model allowance failed")
            return result
        finally:
            # Do not end the phase while an original Session invocation is live.
            try:
                await self.session.wait_for_idle()
                self.policy.step = None
                self.session.runtime.execution_configuration.release_execution(reservation)
            except BaseException:
                self.allowance.fenced = True
                raise
            finally:
                self.policy.step = None
                self.allowance.leave(operation.operation_id)

    async def cancel_and_wait(self, operation, context):
        return await self.delegate.cancel_and_wait(operation, context)


class ScopedVerificationWork:
    """Authorize only the already admitted verifier's exact command and input."""

    def __init__(self, delegate, *, policy, session=None, execution=None):
        self.delegate, self.policy = delegate, policy
        self.session, self.execution = session, execution

    async def execute(self, operation, context):
        if self.policy.verification is not None or self.policy.step is not None:
            raise GoalError("overlapping Goal execution scope")
        self.policy.verification = operation.payload
        reservation = self.execution() if self.execution is not None else None
        try:
            if reservation is not None:
                self.session.configure_execution(reservation, additional_policy=self.policy)
            return await self.delegate.execute(operation, context)
        finally:
            self.policy.verification = None
            if reservation is not None:
                self.session.runtime.execution_configuration.release_execution(reservation)

    async def cancel_and_wait(self, operation, context):
        return await self.delegate.cancel_and_wait(operation, context)


class PlanningWork(_SharedPlanningWork):
    """Legacy Coding evidence format over the shared reply handoff."""

    def __init__(
        self, delegate, *, session, blobs, allowance, prompt, input_ref,
        known_evidence, parser=parse_proposal,
    ):
        self.blobs, self.allowance = blobs, allowance
        super().__init__(
            delegate, session=session, read_transcript=lambda: session.session_manager,
            model_failed=lambda: allowance.failed, prompt=prompt, input_ref=input_ref,
            known_evidence=known_evidence, parser=parser, capture_response=capture_response,
            write_response=lambda operation, raw: put(blobs, raw, f"{operation.operation_id}/response.txt"),
            publish_report=lambda context, report, session_id: publish_report(
                blobs, context, report, role="goal_planning_report", session_id=session_id,
            ),
            rejection_error=ProposalRejected,
        )


class InspectionWork:
    def __init__(self, *, source: bytes, tests: bytes, targets, blobs, confirm):
        self.source, self.tests, self.targets = source, tests, tuple(targets)
        self.blobs, self.confirm = blobs, confirm

    async def execute(self, operation, context):
        if not self.confirm():
            raise GoalError("inspection inputs changed after admission")
        tree = driver.validate_source(self.source)
        cases = driver.validate_tests(self.tests)
        names = {"subtract" if t == "subtraction" else "clamp" for t in self.targets}
        report: dict[str, object] = {
            "version": 1,
            "operation_id": operation.operation_id,
            "run_id": context.run_id,
            "source_sha256": driver.digest(self.source),
            "tests_sha256": driver.digest(self.tests),
            "targets": self.targets,
            "functions": {
                node.name: ast.get_source_segment(self.source.decode(), node)
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names
            },
            "tests": [case for case in cases if case["function"] in names],
        }
        publish_report(
            self.blobs,
            context,
            report,
            role="goal_inspection_report",
            session_id=operation.session_id,
        )
