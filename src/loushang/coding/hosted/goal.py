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
from loushang.appservice.execution_registry import ExecutionLimitsV1
from loushang.appservice.execution_service import HostedExecutionServiceBindingV1
from loushang.coding.adapters.goal import CodingGoal
from loushang.coding.hosted._goal_config import HostedGoalSetup
from loushang.coding.hosted._goal_work import GoalInvocation
from loushang.coding.hosted._work_observation import observe_work_run
from loushang.coding.hosted.execution import CodingHostedExecutionSessionV1
from loushang.coding.hosted.session import CodingRealHostedSessionV1


class CodingHostedGoalSessionV1(CodingHostedExecutionSessionV1):
    _legacy_turns = False

    def __init__(self, binding, setup: HostedGoalSetup, *, owner=None):
        if type(binding) is not CodingRealHostedSessionV1 or type(setup) is not HostedGoalSetup:
            raise TypeError("hosted Goal requires fresh Coding binding and fixed setup")
        self._setup = setup
        super().__init__(binding, owner=owner)
        if setup.repository is not None:
            from loushang.coding.adapters._goal_repository import _RepositoryGoal
            self._goal: CodingGoal | None = _RepositoryGoal(setup.config.workspace, setup.config.data_root)
            self._goal._profile = setup.repository
        else:
            self._goal = CodingGoal(setup.config.workspace, setup.config.data_root)
        self._invocation: GoalInvocation | None = None
        self._goal_binding = token_hex(16)

    @property
    def goal_capability(self):
        self._require_open()
        c = self._setup.config
        return GoalCapabilityV1(self._goal_binding, c.max_advances, c.max_model_calls,
                                c.max_output_tokens, c.deadline_seconds, profile=self._setup.profile_id,
                                accepting=self._invocation is None, supports_progress=True)

    def start_execution(self, request):
        self._require_open()
        if self._invocation is not None or not self._product_binding.execution_available:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        assert self._goal is not None
        invocation = GoalInvocation(self._goal, self._product_binding.control, self._setup,
                                    request.execution_id, lambda: self._guard.interrupt_requested)
        self._guard.start(request, invocation)
        self._invocation = invocation

    async def query_goal(self, execution_id: str) -> GoalObservationV1:
        return await self._observe_goal(execution_id, progress=False)

    async def progress_goal(self, execution_id: str) -> GoalObservationV1:
        return await self._observe_goal(execution_id, progress=True)

    async def _observe_goal(self, execution_id: str, *, progress: bool) -> GoalObservationV1:
        self._require_open()
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
        if not progress:
            assert owner is not None
        try:
            assert owner is not None
            view = None if progress else await owner.query(self._setup.goal_id)
            core = owner.controller
            if progress:
                state = core.query(self._setup.goal_id)
                if len(core.history.batches) > self._setup.config.max_advances:
                    raise ValueError("unexpected Goal batch count")
            batches, unresolved = [], core.fenced if progress else False
            for batch in core.history.batches:
                run = None
                if not progress:
                    run = owner._work.get_run_for_operation(batch.operation_id)
                elif batch.run_receipt is not None and not batch.not_submitted:
                    run = owner._work.get_run(batch.run_receipt)
                    if run.operation_id != batch.operation_id or run.session_id != core.header.session_id:
                        raise ValueError("Goal/Work identity mismatch")
                observed = observe_work_run(owner._work, run, progress=progress) if run is not None else None
                if observed is not None and self._setup.repository is not None:
                    observed = _repository_observation(observed)
                if progress and not batch.not_submitted:
                    assert run is None or observed is not None
                    cancellation = observed.cancellation if observed is not None else None
                    unresolved |= (
                        run is None or run.status == "orphaned" or cancellation is None
                        or cancellation.status not in {"not_requested", "settled"}
                    )
                batches.append(GoalBatchObservationV1(
                    batch.id, batch.operation_id, observed.work if observed else None,
                    observed.recording if observed else None, observed.cancellation if observed else None,
                    observed.errors if observed else
                    (() if progress and batch.not_submitted else ("work_observation_unavailable",)),
                ))
            reason = invocation.reason
            if progress:
                validity = "unknown" if core.fenced or any(batch.errors for batch in batches) else "not_checked"
                if reason in {"planning", "advancing"}:
                    reason = "advancing"
            else:
                assert view is not None
                state = view.goal
                validity = (
                    "unknown" if core.fenced or any(batch.recording is None for batch in batches)
                    else view.validity
                )
                unresolved = view.execution_unresolved or core.fenced
            result = GoalObservationV1(
                "present", reason, state.id, state.status, state.revision, state.epoch,
                core.history.sequence, validity, unresolved, batches=tuple(batches), **usage,
            )
        except Exception:
            result = GoalObservationV1("unavailable", "goal_observation_unavailable", **usage)
        if not progress:
            self._require_open()
        return result

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

    async def _dispose_execution_resources(self) -> None:
        if self._goal is not None:
            await self._goal.close()

    def _release_execution_resources(self) -> None:
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
