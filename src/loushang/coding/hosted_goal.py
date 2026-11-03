"""Opt-in hosted Goal facade borrowing the original canonical Coding Session."""
from __future__ import annotations

from dataclasses import replace
from secrets import token_hex

from loushang.appserver.goal import (
    GoalBatchObservationV1,
    GoalCapabilityV1,
    GoalObservationV1,
)
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError
from loushang.appservice.execution_contract import InterruptModeV1
from loushang.appservice.execution_registry import ExecutionLimitsV1
from loushang.appservice.execution_service import HostedExecutionServiceBindingV1

from ._hosted_goal_config import HostedGoalSetup
from ._hosted_goal_work import GoalInvocation
from ._hosted_work_observation import observe_work_run
from .adapters.goal import CodingGoal
from .hosted_execution import CodingHostedExecutionSessionV1
from .hosted_session import CodingRealHostedSessionV1


class CodingHostedGoalSessionV1(CodingHostedExecutionSessionV1):
    def __init__(self, binding, setup: HostedGoalSetup, *, owner=None):
        if type(binding) is not CodingRealHostedSessionV1 or type(setup) is not HostedGoalSetup:
            raise TypeError("hosted Goal requires fresh Coding binding and fixed setup")
        self._setup = setup
        super().__init__(binding, owner=owner)
        if setup.repository is not None:
            from .adapters._goal_repository import _RepositoryGoal
            self._goal: CodingGoal | None = _RepositoryGoal(setup.config.workspace, setup.config.data_root)
            self._goal._profile = setup.repository
        else:
            self._goal = CodingGoal(setup.config.workspace, setup.config.data_root)
        self._invocation: GoalInvocation | None = None
        self._goal_binding = token_hex(16)

    @property
    def goal_capability(self):
        self._require_execution_open()
        c = self._setup.config
        return GoalCapabilityV1(self._goal_binding, c.max_advances, c.max_model_calls,
                                c.max_output_tokens, c.deadline_seconds, profile=self._setup.profile_id,
                                accepting=self._invocation is None, supports_progress=True)

    def start_execution(self, request):
        self._require_execution_open()
        if self._invocation is not None or not self._product_binding.execution_available:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        assert self._goal is not None
        invocation = GoalInvocation(self._goal, self._product_binding.control, self._setup,
                                    request.execution_id, lambda: self._guard.interrupt_requested)
        self._guard.start(request, invocation)
        self._invocation = invocation

    async def query_goal(self, execution_id):
        self._require_execution_open()
        invocation, owner = self._invocation, self._goal
        if invocation is None:
            return GoalObservationV1("not_started", "not_started")
        if invocation.execution_id != execution_id:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        usage = dict(advances=invocation.advances, model_calls=self._setup.allowance.total_calls)
        if not invocation.initialized:
            return GoalObservationV1("initializing" if invocation.initializing else
                                     "unavailable" if invocation.initialization_failed else "not_started",
                                     invocation.reason, **usage)
        assert owner is not None
        try:
            view = await owner.query(self._setup.goal_id)
            core = owner.controller
            batches = []
            for batch in core.history.batches:
                run = owner._work.get_run_for_operation(batch.operation_id)
                observed = observe_work_run(owner._work, run) if run is not None else None
                if observed is not None and self._setup.repository is not None:
                    observed = _repository_observation(observed)
                batches.append(GoalBatchObservationV1(
                    batch.id, batch.operation_id, observed.work if observed else None,
                    observed.recording if observed else None, observed.cancellation if observed else None,
                    observed.errors if observed else ("work_observation_unavailable",),
                ))
            state = view.goal
            recording_unavailable = any(b.recording is None for b in batches)
            result = GoalObservationV1(
                "present", invocation.reason, state.id, state.status, state.revision, state.epoch,
                core.history.sequence, "unknown" if core.fenced or recording_unavailable else view.validity,
                view.execution_unresolved or core.fenced,
                batches=tuple(batches), **usage,
            )
        except Exception:
            result = GoalObservationV1("unavailable", "goal_observation_unavailable", **usage)
        self._require_execution_open()
        return result

    async def start_turn(self, text):
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    async def progress_goal(self, execution_id):
        # No await, business assessment, workspace IO or history replay here.
        self._require_execution_open()
        invocation, owner = self._invocation, self._goal
        if invocation is None:
            return GoalObservationV1("not_started", "not_started")
        if invocation.execution_id != execution_id:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        usage = dict(advances=invocation.advances, model_calls=self._setup.allowance.total_calls)
        if not invocation.initialized:
            return GoalObservationV1("initializing" if invocation.initializing else
                                     "unavailable" if invocation.initialization_failed else "not_started",
                                     invocation.reason, **usage)
        try:
            core = owner.controller
            state = core.query(self._setup.goal_id)
            if len(core.history.batches) > self._setup.config.max_advances:
                raise ValueError("unexpected Goal batch count")
            batches, unresolved = [], core.fenced
            for batch in core.history.batches:
                observed = None
                if batch.run_receipt is not None and not batch.not_submitted:
                    run = owner._work.get_run(batch.run_receipt)
                    if run.operation_id != batch.operation_id or run.session_id != core.header.session_id:
                        raise ValueError("Goal/Work identity mismatch")
                    observed = observe_work_run(owner._work, run, progress=True)
                    if self._setup.repository is not None:
                        observed = _repository_observation(observed)
                    unresolved |= (run.status == "orphaned" or observed.cancellation is None or
                                   observed.cancellation.status not in {"not_requested", "settled"})
                elif not batch.not_submitted:
                    unresolved = True
                batches.append(GoalBatchObservationV1(
                    batch.id, batch.operation_id, observed.work if observed else None,
                    observed.recording if observed else None, observed.cancellation if observed else None,
                    observed.errors if observed else (() if batch.not_submitted else ("work_observation_unavailable",)),
                ))
            unknown = core.fenced or any(b.errors for b in batches)
            reason = "advancing" if invocation.reason in {"planning", "advancing"} else invocation.reason
            return GoalObservationV1(
                "present", reason, state.id, state.status, state.revision, state.epoch,
                core.history.sequence, "unknown" if unknown else "not_checked",
                unresolved, batches=tuple(batches), **usage,
            )
        except Exception:
            return GoalObservationV1("unavailable", "goal_observation_unavailable", **usage)

    async def snapshot(self):
        snapshot = await super().snapshot()
        if self._setup.repository is not None:
            return replace(snapshot, title="Repository Goal", records=())
        return snapshot

    async def snapshot_execution(self):
        snapshot = await super().snapshot_execution()
        if self._setup.repository is not None:
            return replace(snapshot, source=replace(snapshot.source, title="Repository Goal", records=()),
                           draft="", truncated=False)
        return snapshot

    async def _on_runtime_event(self, event):
        # Repository prompts contain trusted source/review material. Ordinary
        # Session content subscriptions must not bypass the Goal DTO boundary.
        # Guard observation remains the execution-status event authority.
        if self._setup.repository is None:
            await super()._on_runtime_event(event)

    def steer_turn(self, text):
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    def follow_up_turn(self, text):
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    def interrupt_turn(self):
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

    def interrupt_execution(self, execution_id, mode):
        if mode is not InterruptModeV1.WHOLE_EXECUTION:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return super().interrupt_execution(execution_id, mode)

    async def _close_execution(self):
        state = self._guard.state
        if state is not None and not state.status.terminal:
            self._guard.interrupt(state.execution_id, InterruptModeV1.WHOLE_EXECUTION)
            await self._guard.retry_settlement(state.execution_id)
        if self._goal is not None:
            await self._goal.close()
        await super()._close_execution()
        if self._invocation is not None:
            self._invocation.task = None
            self._invocation.owner = None
        self._goal = None


def create_coding_goal_service_binding(application_id, *, service_instance_id=None):
    def select(port):
        return port if isinstance(port, CodingHostedGoalSessionV1) else None

    return HostedExecutionServiceBindingV1(
        application_id, service_instance_id or token_hex(16), select,
        ExecutionLimitsV1(active=1, submissions=1), select_goal_port=select,
    )


def _repository_observation(observed):
    work = observed.work
    if work is None:
        return observed
    allowed = {"planning", "inspect", "repair", "report", "validation", "review"}
    unknown = (work.current_step_id is not None and work.current_step_id not in allowed) or any(
        step.step_id not in allowed for step in work.steps)
    return replace(observed, work=replace(
        work, method_id=None, plan_id=None, current_step_id=None if unknown else work.current_step_id,
        steps=() if unknown else work.steps),
        errors=observed.errors + (("work_plan_unavailable",) if unknown else ()))
