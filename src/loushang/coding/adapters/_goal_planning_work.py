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

from . import _goal_driver as driver
from ._goal_calculator import put
from ._goal_planning_response import ResponseBoundary, capture_response
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

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
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
            if not path.is_relative_to(self.workspace):
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
            expected == "write" and paths != {self.workspace / "calculator.py"}
        ):
            return deny
        return PolicyDecision.allow()


class ScopedSessionWork:
    """Restore tool selection even when the original turn fails or is cancelled."""

    def __init__(self, delegate, *, session, allowance, policy, phase):
        self.delegate, self.session, self.allowance = delegate, session, allowance
        self.policy, self.phase = policy, phase

    async def execute(self, operation, context):
        prior = self.session.get_active_tool_names()
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
            await self.session.set_active_tools(tools)
            if set(self.session.get_active_tool_names()) != set(tools):
                raise GoalError("Goal tool configuration did not take effect")
            result = await self.delegate.execute(operation, context)
            if self.phase == "repair" and self.allowance.failed:
                raise GoalError("repair model allowance failed")
            return result
        finally:
            # Do not end the phase while an original Session invocation is live.
            try:
                await self.session.wait_for_idle()
                self.policy.step = None
                await self.session.set_active_tools(prior)
                if self.session.get_active_tool_names() != prior:
                    raise GoalError("Goal tool configuration was not restored")
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

    def __init__(self, delegate, *, policy):
        self.delegate, self.policy = delegate, policy

    async def execute(self, operation, context):
        if self.policy.verification is not None or self.policy.step is not None:
            raise GoalError("overlapping Goal execution scope")
        self.policy.verification = operation.payload
        try:
            return await self.delegate.execute(operation, context)
        finally:
            self.policy.verification = None


class PlanningWork:
    def __init__(
        self, delegate, *, session, blobs, allowance, prompt, input_ref, known_evidence
    ):
        self.delegate, self.session, self.blobs = delegate, session, blobs
        self.allowance, self.prompt = allowance, prompt
        self.input_ref, self.known_evidence = input_ref, tuple(known_evidence)

    async def execute(self, operation, context):
        manager = self.session.session_manager
        boundary = ResponseBoundary.capture(manager)
        events = []

        async def listen(event):
            if event.kind == "agent.message_end":
                events.append(event)

        unsubscribe = self.session.subscribe_runtime_events(listen)
        try:
            await self.delegate.execute(operation, context)
            await self.session.wait_for_idle()
        finally:
            unsubscribe()
        report: dict[str, object] = {
            "version": 1,
            "operation_id": operation.operation_id,
            "run_id": context.run_id,
            "session_id": operation.session_id,
            "input_ref": self.input_ref,
        }
        try:
            if self.allowance.failed:
                raise ProposalRejected("planning model allowance failed")
            raw, proof = capture_response(
                manager,
                boundary,
                session_id=operation.session_id,
                prompt=self.prompt,
                events=events,
            )
            report["response_ref"] = put(
                self.blobs, raw, f"{operation.operation_id}/response.txt"
            )
            report["response_proof"] = proof
            proposal = parse_proposal(raw, known_evidence=self.known_evidence)
            report["proposal"] = proposal.data()
            report["rejection"] = None
        except ProposalRejected as error:
            report["proposal"] = None
            report["rejection"] = str(error)
        publish_report(
            self.blobs,
            context,
            report,
            role="goal_planning_report",
            session_id=operation.session_id,
        )

    async def cancel_and_wait(self, operation, context):
        return await self.delegate.cancel_and_wait(operation, context)


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
