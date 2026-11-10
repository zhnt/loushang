"""Coding policy and real compatibility types over shared delegated Work."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding.bootstrap import _create_agent_session_runtime
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.multiagent import CodingSubagentFactory
from loushang.harness.multiagent import (
    AgentRef,
    AgentTypeRegistry,
    AgentTypeSpec,
    MultiAgentControl,
)
from loushang.harness.policy import PolicyEvaluatorChain
from loushang.harness.session.multiagent import SessionMultiAgentRuntime
from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
from loushang.harnesswork.goal import GoalError
from loushang.harnesswork.goal.records import plain as plain
from loushang.harnesswork.integrations.delegation import (
    DelegatedSessionWork,
    SessionGoalDelegation,
)

from ._goal_execution_context import (
    OPERATION_KIND,
    ROLE,
    TOOLS,
    SessionChoice,
    context_material,
    detach_message,
    ref_data,
)
from ._work_evidence import validate_evidence_fact, work_evidence_fact

KEY = "coding_goal_context"
WORKER = "shared_implementation_worker"


@dataclass(frozen=True)
class ExecutionContextView:
    ref: AgentRef
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


class DelegatedSessions(SessionGoalDelegation):
    _choice_type = SessionChoice
    _view_type = ExecutionContextView
    _ref_data = staticmethod(ref_data)
    _detach_message = staticmethod(detach_message)
    _payload_key, _operation_kind = KEY, OPERATION_KIND
    _worker_type, _tools, _phase = WORKER, TOOLS, "repair"
    _report_role = ROLE
    _blob_prefix, _blob_kind = "goal", "coding-goal-input"
    _blob_media_type, _blob_source = (
        "application/octet-stream",
        "coding-goal:trusted-input",
    )

    def __init__(
        self,
        owner,
        profile,
        blobs,
        reader,
        source_identity,
        approval_resolver,
        additional_tool_policy=None,
    ):
        self.owner, self.profile, self.blobs = owner, profile, blobs
        self.additional_tool_policy = additional_tool_policy
        self.reader, self.source_identity = reader, source_identity
        super().__init__(
            session=owner._session,
            work=owner._work,
            allowance=owner._allowance,
            blobs=blobs,
            reader=reader,
            source_identity=source_identity,
            selection=profile.execution_policy.choice,
        )
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

    def _build(self, **kwargs):
        if self.active is None or self.active.cancelled:
            raise GoalError("child creation no longer admitted")
        policy = self.profile.tool_policy(self.owner.workspace)
        policy.step = "repair"
        kwargs.update(
            composition_set=resolve_coding_composition_set("coding-standard"),
            enable_multiagent=False,
            stream_fn=self.owner._allowance.stream,
            tool_policy_evaluator=(
                PolicyEvaluatorChain(
                    (policy, self.additional_tool_policy), strategy="most_restrictive"
                )
                if self.additional_tool_policy is not None
                else policy
            ),
        )
        sdk = _create_agent_session_runtime(**kwargs)
        ref = kwargs["delegated_execution_profile"].actor_ref
        child = _ChildRuntime(sdk, policy, self, ref)
        self.children[ref] = child
        return child

    def _binding(self, child):
        return {
            "ref": ref_data(child.ref),
            "session_id": child.session.session_id,
            "origin_operation_id": child.origin,
            "prior_operation_id": child.last_operation,
            "prior_round": child.last_round,
        }

    @property
    def _work_type(self):
        return DelegatedWork

    @property
    def _context_prompt(self):
        return self.profile.system_prompt

    def _context_material(self, choice, plan, watermark):
        return context_material(
            session_id=self.owner._session.session_id,
            source_identity=self.source_identity,
            choice=choice,
            plan=plan,
            watermark=watermark,
        )

    def _freeze(self, basis, operation, spec, turn, choice, history, child):
        return {
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

    def _report(self, operation, context, frozen, ref, round_id, child, completion):
        return {
            "version": 1,
            "operation_id": operation.operation_id,
            "run_id": context.run_id,
            "session_id": operation.session_id,
            "context": frozen,
            "child_ref": ref_data(ref),
            "child_session_id": child.session.session_id,
            "origin_operation_id": child.origin,
            "round_id": round_id,
            "terminal": completion.terminal.status,
        }

    def _evidence_fact(self, blob, context, session_id):
        fact = work_evidence_fact(blob, role=ROLE, reported_step_id=context.step_id)
        validate_evidence_fact(fact, session_id=session_id)
        return fact


class DelegatedWork(DelegatedSessionWork):
    """Original Coding entrypoint for the shared Work-to-round binding."""
