"""Opt-in hosted Goal facade borrowing the original canonical Coding Session."""
from __future__ import annotations

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
        super().__init__(binding, owner=owner)
        self._setup = setup
        self._goal: CodingGoal | None = CodingGoal(setup.config.workspace, setup.config.data_root)
        self._invocation: GoalInvocation | None = None
        self._goal_binding = token_hex(16)

    @property
    def goal_capability(self):
        self._require_execution_open()
        c = self._setup.config
        return GoalCapabilityV1(self._goal_binding, c.max_advances, c.max_model_calls,
                                c.max_output_tokens, c.deadline_seconds, accepting=self._invocation is None)

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
            view = await owner.query("calculator")
            core = owner.controller
            batches = []
            for batch in core.history.batches:
                run = owner._work.get_run_for_operation(batch.operation_id)
                observed = observe_work_run(owner._work, run) if run is not None else None
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
