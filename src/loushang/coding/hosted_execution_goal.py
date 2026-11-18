"""Adapt one existing Coding execution binding to optional Goal operations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from loushang.appserver.execution.goal_model import (
    InteractiveGoalCommandV1,
    InteractiveGoalRecoveryV1,
    InteractiveGoalReviewSubmissionV1,
    InteractiveGoalReviewV1,
    InteractiveGoalViewV1,
)
from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

from .hosted_resume import CodingDeferredHostedSessionV1
from .hosted_session import CodingRealHostedSessionV1

if TYPE_CHECKING:
    from loushang.appservice.execution_guard import ExecutionGuardV1


class _HostedExecutionGoal:
    if TYPE_CHECKING:
        _product_binding: CodingRealHostedSessionV1 | CodingDeferredHostedSessionV1
        _closing: bool
        _model_lock: asyncio.Lock
        _guard: ExecutionGuardV1

        def _require_execution_open(self) -> None: ...

        def _allows_interactive_goal(self) -> bool: ...

    @property
    def supports_interactive_goal(self) -> bool:
        return self._allows_interactive_goal() and type(self._product_binding) is CodingRealHostedSessionV1

    @property
    def supports_interactive_goal_recovery(self) -> bool:
        binding = self._product_binding
        return (self._allows_interactive_goal()
                and isinstance(binding, CodingDeferredHostedSessionV1)
                and binding.supports_interactive_goal_recovery)

    async def interactive_goal_recovery(self) -> InteractiveGoalRecoveryV1:
        self._require_execution_open()
        binding = self._product_binding
        if not self.supports_interactive_goal_recovery or not isinstance(binding, CodingDeferredHostedSessionV1):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return await binding.interactive_goal_recovery()

    def _interactive_goal_binding(self) -> CodingRealHostedSessionV1:
        self._require_execution_open()
        binding = self._product_binding
        if not self.supports_interactive_goal or not isinstance(binding, CodingRealHostedSessionV1):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return binding

    async def interactive_goal_status(self) -> InteractiveGoalViewV1:
        return await self._interactive_goal_binding().interactive_goal_view()

    async def create_interactive_goal(
        self, target: str, *, check_current: Callable[[], None],
    ) -> InteractiveGoalViewV1:
        from loushang.harness.session.execution_admission import (
            SessionExecutionUnavailable,
        )
        from loushang.harnesswork.goal import GoalError

        from .adapters.goal import GoalConstructionError

        binding = self._interactive_goal_binding()
        view = await binding.interactive_goal_view()
        check_current()
        if view.availability != "ready":
            return view
        try:
            await binding.create_interactive_goal(target, check_current=check_current)
        except (GoalError, GoalConstructionError, SessionExecutionUnavailable):
            check_current()
            view = await binding.interactive_goal_view()
            if view.availability == "ready":
                raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None
            return view
        return await binding.interactive_goal_view()

    def control_interactive_goal(
        self, command: InteractiveGoalCommandV1 | InteractiveGoalReviewSubmissionV1, *, check_current: Callable[[], None],
    ) -> InteractiveGoalViewV1:
        from loushang.harness.session.execution_admission import (
            SessionExecutionUnavailable,
        )
        from loushang.harnesswork.goal import GoalError

        try:
            return self._interactive_goal_binding().control_interactive_goal(command, check_current=check_current)
        except (GoalError, SessionExecutionUnavailable):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None

    async def interactive_goal_review(
        self, goal_id: str, *, check_current: Callable[[], None],
    ) -> InteractiveGoalReviewV1:
        from loushang.harness.session.execution_admission import (
            SessionExecutionUnavailable,
        )
        from loushang.harnesswork.goal import GoalError

        try:
            return await self._interactive_goal_binding().interactive_goal_review(goal_id, check_current=check_current)
        except (GoalError, SessionExecutionUnavailable):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE) from None

    def _idle_for_interactive_goal(self) -> bool:
        if not self._allows_interactive_goal() or self._closing or self._model_lock.locked():
            return False
        state = self._guard.state
        return state is None or state.status.terminal
