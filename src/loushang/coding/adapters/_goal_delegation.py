"""Repository-owned Work adapter over the original Harness child owner.

The control registry owns identities/rounds; the factory owns partial creation
and cleanup. This adapter only freezes admission and joins one Work to one round.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace

from loushang.coding.bootstrap import _create_agent_session_runtime
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.multiagent import CodingSubagentFactory
from loushang.harness.multiagent import (
    AgentTypeRegistry,
    AgentTypeSpec,
    HostCaller,
    MultiAgentControl,
)
from loushang.harness.session.model_selection import model_identity_data
from loushang.harness.session.multiagent import SessionMultiAgentRuntime
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harnesswork import WorkCancellationOutcome
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.records import plain

from ._goal_execution_context import (
    OPERATION_KIND,
    ROLE,
    TOOLS,
    SessionChoice,
    build_context,
    ref_data,
)
from ._goal_planning_work import publish_report

KEY = "coding_goal_context"
WORKER = "shared_implementation_worker"


@dataclass(frozen=True)
class ExecutionContextView:
    ref: object
    session_id: str
    status: str
    round_id: int
    origin_operation_id: str | None


class _ChildRuntime:
    """Thin construction hook; the shared factory retains this owner on failure."""

    def __init__(self, sdk, policy, family, ref):
        self.sdk, self.policy, self.family, self.ref = sdk, policy, family, ref
        self.session = None
        self.origin = self.last_operation = None
        self.last_round = 0

    async def create_session(self, *, cwd):
        from .goal import _validate_goal_session

        self.session = await self.sdk.create_session(cwd=cwd)
        _validate_goal_session(self.session, self.family.owner.workspace, True)
        if self.family.model_data(self.session) != self.family.model:
            raise GoalError("child model differs from admitted parent model")
        return self.session

    async def dispose_session_runtime(self):
        await self.sdk.dispose_session_runtime()
        self.policy.step = None


class DelegatedSessions:
    def __init__(
        self, owner, profile, blobs, reader, source_identity, approval_resolver
    ):
        self.owner, self.profile, self.blobs = owner, profile, blobs
        self.reader, self.source_identity = reader, source_identity
        self.selection = profile.execution_policy.choice
        self.revision = 0
        self.gate = asyncio.Lock()
        self.children = {}
        self.last_ref = None
        self.active = None
        self.closing = False
        self.fenced = False
        self.cleanup_pending = set()
        self.model = self.model_data(owner._session)
        self.control = MultiAgentControl(
            limits=profile.execution_policy.limits,
            agent_types=AgentTypeRegistry(
                (
                    AgentTypeSpec(
                        WORKER,
                        allowed_tools=TOOLS,
                        can_spawn=False,
                        maximum_children=profile.execution_policy.limits.max_open_agents,
                    ),
                )
            ),
        )
        factory = CodingSubagentFactory(
            session_dir=owner.data_root / "sessions",
            cwd=owner.workspace,
            tool_registry=WorkspaceToolRegistry(),
            runtime_builder=self._build,
            default_model_provider=lambda: owner._session.agent.model,
            selected_exact_tool_names=TOOLS,
            approval_resolver=approval_resolver,
        )
        self.runtime = SessionMultiAgentRuntime(
            control=self.control,
            child_factory=factory,
            root_input=None,
            notice_wake_policy="discard",
        )

    @staticmethod
    def model_data(session):
        return asdict(model_identity_data(session.agent.model))

    def _build(self, **kwargs):
        if self.active is None or self.active.cancelled:
            raise GoalError("child creation no longer admitted")
        policy = self.profile.tool_policy(self.owner.workspace)
        policy.step = "repair"
        kwargs.update(
            composition_set=resolve_coding_composition_set("coding-standard"),
            enable_multiagent=False,
            stream_fn=self.owner._allowance.stream,
            tool_policy_evaluator=policy,
        )
        sdk = _create_agent_session_runtime(**kwargs)
        ref = kwargs["delegated_execution_profile"].actor_ref
        child = _ChildRuntime(sdk, policy, self, ref)
        self.children[ref] = child
        return child

    def _available(self):
        if (
            self.closing
            or self.fenced
            or self.cleanup_pending
            or self.owner._allowance.fenced
        ):
            raise GoalError("delegated Session family unavailable")
        if self.model_data(self.owner._session) != self.model:
            raise GoalError("parent model changed")

    def _reusable(self, ref, expected=None):
        child = self.children.get(ref)
        record = self.control.registry.get(ref)
        if child is None or child.session is None or record is None:
            raise GoalError("reuse target unavailable")
        run = (
            self.owner._work.get_run_for_operation(child.last_operation)
            if child.last_operation
            else None
        )
        if (
            record.status != "completed"
            or record.round_id != child.last_round
            or child.session.pending_message_count
            or child.session.is_streaming
            or run is None
            or run.status != "completed"
            or self.model_data(child.session) != self.model
            or (expected is not None and expected != self._binding(child))
        ):
            raise GoalError("reuse target not idle with a confirmed handoff")
        return child

    def _binding(self, child):
        return {
            "ref": ref_data(child.ref),
            "session_id": child.session.session_id,
            "origin_operation_id": child.origin,
            "prior_operation_id": child.last_operation,
            "prior_round": child.last_round,
        }

    def views(self):
        return tuple(
            ExecutionContextView(
                ref,
                child.session.session_id if child.session else "",
                record.status,
                record.round_id,
                child.origin,
            )
            for ref, child in self.children.items()
            if (record := self.control.registry.get(ref)) is not None
        )

    def select(self, choice):
        self._available()
        if self.active is not None or self.gate.locked():
            raise GoalError("delegated execution busy")
        if choice is not None and not isinstance(choice, SessionChoice):
            raise GoalError("invalid Session choice")
        self.selection = choice
        self.revision += 1

    def prepare(self, basis, operation, spec, turn):
        self._available()
        if self.active is not None:
            raise GoalError("delegated execution busy")
        choice = self.selection
        if choice is None:
            choice = (
                SessionChoice("reuse", target=self.last_ref)
                if self.last_ref
                else SessionChoice("fresh")
            )
        child = self._reusable(choice.target) if choice.mode == "reuse" else None
        plan, history = build_context(
            session=self.owner._session,
            blobs=self.blobs,
            choice=choice,
            system_prompt=self.profile.system_prompt,
            source_identity=self.source_identity,
        )
        frozen = {
            "version": 1,
            "mode": choice.mode,
            "reason": choice.reason,
            "selection_revision": self.revision,
            "basis": basis.identity,
            "operation_id": operation.operation_id,
            "method_id": spec.method_id,
            "plan_id": spec.plan_id,
            "step_id": turn.step_id,
            "model": self.model,
            "tools": list(TOOLS),
            "history": history,
            "reuse": self._binding(child) if child else None,
        }
        # Operation and Goal intent retain independent immutable snapshots.
        operation = replace(
            operation,
            kind=OPERATION_KIND,
            payload={**operation.payload, KEY: plain(frozen)},
        )
        return (
            operation,
            DelegatedWork(self, choice, plan, plain(frozen), turn.text),
            frozen,
        )

    def confirm(self, value):
        try:
            self._available()
            if self.active is not None or value["selection_revision"] != self.revision:
                return False
            if value["mode"] == "reuse":
                child = next(
                    c
                    for c in self.children.values()
                    if ref_data(c.ref) == value["reuse"]["ref"]
                )
                self._reusable(child.ref, value["reuse"])
            return True
        except (ValueError, KeyError, StopIteration):
            return False

    async def release(self, ref):
        async with self.gate:
            if self.active is not None or self.closing:
                raise GoalError("delegated execution busy")
            record = self.control.registry.get(ref)
            if record is None or ref not in self.children:
                raise GoalError("unknown exact child identity")
            if record.status == "running":
                raise GoalError("cannot release an active child")
            result = await self.runtime.close_agent(
                caller=HostCaller(), target=ref.path
            )
            if result.dispose_errors:
                self.cleanup_pending.add(ref)
                raise GoalError("child cleanup pending")
            self.cleanup_pending.discard(ref)
            if self.last_ref == ref:
                self.last_ref = None
            # The original owner retains resources until this retry succeeds.

    async def close(self):
        self.closing = True
        await self.runtime.dispose()


class DelegatedWork:
    def __init__(self, family, choice, plan, frozen, prompt):
        self.family, self.choice, self.plan = family, choice, plan
        self.frozen, self.prompt = frozen, prompt
        self.cancelled = False
        self.task = self.creation = None
        self.ref = None
        self.round = None

    async def execute(self, operation, context):
        async with self.family.gate:
            if self.cancelled:
                raise GoalError("delegated Work cancelled before dispatch")
            if self.task is not None:
                raise GoalError("duplicate delegated dispatch")
            self.task = asyncio.create_task(self._execute(operation, context))
        await asyncio.shield(self.task)

    async def _execute(self, operation, context):
        family = self.family
        allowance = family.owner._allowance
        child = None
        entered = False
        try:
            async with family.gate:
                if self.cancelled or not family.confirm(self.frozen):
                    raise GoalError("delegated admission changed")
                if (
                    plain(operation.payload.get(KEY)) != self.frozen
                    or context.step_id != "repair"
                ):
                    raise GoalError("delegated operation mismatch")
                family.active = self
                allowance.enter(operation.operation_id, "repair")
                entered = True
            if self.choice.mode == "inherit":
                manager = family.owner._session.session_manager
                watermark = self.frozen["history"]["watermark"]
                records = tuple(manager.get_branch(watermark))
                source = await family.reader.read([r.record_id for r in records])
                if (
                    source.store_identity != family.source_identity
                    or tuple(r.record for r in source.records) != records
                ):
                    raise GoalError("inherited source changed or unavailable")
                plan, material = build_context(
                    session=family.owner._session,
                    blobs=family.blobs,
                    choice=self.choice,
                    system_prompt=family.profile.system_prompt,
                    source_identity=source.store_identity,
                    watermark=watermark,
                )
                if material != self.frozen["history"]:
                    raise GoalError("inherited context changed")
                self.plan = plan
            async with family.gate:
                if self.cancelled:
                    raise GoalError("delegated Work cancelled before delivery")
                if self.choice.mode == "reuse":
                    child = family._reusable(self.choice.target, self.frozen["reuse"])
                    child.policy.step = "repair"
                    self.ref = child.ref
                    receipt = await family.runtime.send_message(
                        caller=HostCaller(),
                        target=self.ref.path,
                        text=self.prompt,
                    )
                    self.round = receipt.round_id
                    if (
                        not receipt.triggered_new_round
                        or receipt.recipient_ref != self.ref
                        or self.round != child.last_round + 1
                    ):
                        raise GoalError(
                            "child delivery did not start the admitted round"
                        )
                else:
                    self.creation = asyncio.create_task(
                        family.runtime.spawn_child(
                            caller=HostCaller(),
                            parent_path=family.control.root_ref.path,
                            name=operation.operation_id,
                            agent_type=WORKER,
                            initial_prompt=self.prompt,
                            context_plan=self.plan,
                        )
                    )
            if self.creation is not None:
                record = await asyncio.shield(self.creation)
                self.ref, self.round = record.ref, record.round_id
                child = family.children[self.ref]
                child.origin = operation.operation_id
            completion = await family.runtime.await_completion(
                caller=HostCaller(), target=self.ref.path
            )
            if (
                self.cancelled
                or completion.sender_ref != self.ref
                or completion.round_id != self.round
                or completion.terminal.status != "completed"
                or allowance.failed
            ):
                raise GoalError("child round did not complete successfully")
            report = {
                "version": 1,
                "operation_id": operation.operation_id,
                "run_id": context.run_id,
                "session_id": operation.session_id,
                "context": self.frozen,
                "child_ref": ref_data(self.ref),
                "child_session_id": child.session.session_id,
                "origin_operation_id": child.origin,
                "round_id": self.round,
                "terminal": completion.terminal.status,
            }
            publish_report(
                family.blobs,
                context,
                report,
                role=ROLE,
                session_id=operation.session_id,
            )
            child.last_operation, child.last_round = operation.operation_id, self.round
            family.last_ref = self.ref
        except BaseException:
            # Settle the real round before releasing permissions/allowance. The
            # shared creation owner retains partially created resources on error.
            if self.ref is not None:
                try:
                    await family.runtime.interrupt_agent(
                        caller=HostCaller(), target=self.ref.path
                    )
                except BaseException:
                    family.fenced = allowance.fenced = True
            elif self.creation is not None and not self.creation.cancelled():
                error = self.creation.exception() if self.creation.done() else None
                if getattr(error, "owner", None) is not None:
                    family.cleanup_pending.add(error.ref)
            raise
        finally:
            if child is not None:
                try:
                    await child.session.wait_for_idle()
                except BaseException:
                    family.fenced = allowance.fenced = True
                    raise
                child.policy.step = None
            if entered:
                allowance.leave(operation.operation_id)
            if family.active is self:
                family.active = None

    async def cancel_and_wait(self, operation, context):
        family = self.family
        try:
            async with family.gate:
                self.cancelled = True
                creation = self.creation
                if creation is not None and not creation.done():
                    creation.cancel()
            if creation is not None:
                try:
                    record = await asyncio.shield(creation)
                    self.ref, self.round = record.ref, record.round_id
                except asyncio.CancelledError:
                    if not creation.done():
                        raise
                except BaseException as error:
                    if getattr(error, "owner", None) is not None:
                        raise
            if self.ref is not None:
                await family.runtime.interrupt_agent(
                    caller=HostCaller(), target=self.ref.path
                )
            if self.task is not None:
                try:
                    await asyncio.shield(self.task)
                except (GoalError, asyncio.CancelledError):
                    if not self.task.done():
                        raise
            if family.fenced or family.owner._allowance.fenced:
                raise GoalError("delegated cancellation cleanup unresolved")
            return WorkCancellationOutcome.settled()
        except BaseException as error:
            family.fenced = True
            return WorkCancellationOutcome.failed(str(error))
