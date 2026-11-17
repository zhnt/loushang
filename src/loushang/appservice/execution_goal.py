"""Optional Goal operations on the existing Execution client scope."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypedDict

from loushang.appserver.execution.goal_model import (
    InteractiveGoalCommandV1,
    InteractiveGoalRecoveryV1,
    InteractiveGoalReviewSubmissionV1,
    InteractiveGoalReviewV1,
    InteractiveGoalViewV1,
)
from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionSnapshotRequestV1,
)

from .execution_ports import (
    HostedExecutionPortV1,
    HostedInteractiveGoalCommandPortV1,
    HostedInteractiveGoalPortV1,
    HostedInteractiveGoalRecoveryPortV1,
    HostedInteractiveGoalReviewPortV1,
)

if TYPE_CHECKING:
    from .execution_registry import ExecutionBindingV1, ExecutionRegistryV1
    from .runtime import _SessionOwner


def _interactive_goal_port(port: HostedExecutionPortV1) -> HostedInteractiveGoalPortV1 | None:
    if isinstance(port, HostedInteractiveGoalPortV1) and port.supports_interactive_goal is True:
        return port
    return None


class _GoalCapabilities(TypedDict):
    supports_interactive_goal: bool
    supports_interactive_goal_commands: bool
    supports_interactive_goal_recovery: bool


def goal_capabilities(port: HostedExecutionPortV1) -> _GoalCapabilities:
    goal = _interactive_goal_port(port)
    return {
        "supports_interactive_goal": goal is not None,
        "supports_interactive_goal_commands": isinstance(goal, HostedInteractiveGoalCommandPortV1),
        "supports_interactive_goal_recovery": (
            isinstance(port, HostedInteractiveGoalRecoveryPortV1)
            and port.supports_interactive_goal_recovery
        ),
    }


class _ScopedInteractiveGoal:
    """Uses the resolver and controller checks of the owning scoped client."""

    if TYPE_CHECKING:
        _registry: ExecutionRegistryV1

        async def _resolve(
            self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        ) -> tuple[_SessionOwner, ExecutionBindingV1]: ...

        def _check(self, control: SessionSnapshotRequestV1, session: _SessionOwner) -> None: ...

    async def _resolve_interactive_goal(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        *, starts_work: bool = False,
    ) -> tuple[HostedInteractiveGoalPortV1, Callable[[], None]]:
        session, binding = await self._resolve(control, expected_instance_id)
        port = _interactive_goal_port(binding.port)
        if port is None:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)

        def check_current() -> None:
            self._check(control, session)
            self._registry.require_instance(expected_instance_id)
            if session._execution is not binding or binding.closing or (starts_work and binding.active is not None):
                raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)

        check_current()
        return port, check_current

    async def create_interactive_goal(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, target: str,
    ) -> InteractiveGoalViewV1:
        port, check_current = await self._resolve_interactive_goal(control, expected_instance_id)
        result = await port.create_interactive_goal(target, check_current=check_current)
        check_current()
        return result

    async def interactive_goal_status(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> InteractiveGoalViewV1:
        port, check_current = await self._resolve_interactive_goal(control, expected_instance_id)
        result = await port.interactive_goal_status()
        check_current()
        return result

    async def control_interactive_goal(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        command: InteractiveGoalCommandV1,
    ) -> InteractiveGoalViewV1:
        if type(command) is not InteractiveGoalCommandV1:
            raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
        port, check_current = await self._resolve_interactive_goal(
            control, expected_instance_id, starts_work=command.action in {"run", "step", "resume"},
        )
        if not isinstance(port, HostedInteractiveGoalCommandPortV1):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return port.control_interactive_goal(command, check_current=check_current)

    async def interactive_goal_review(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, goal_id: str,
    ) -> InteractiveGoalReviewV1:
        port, check_current = await self._resolve_interactive_goal(control, expected_instance_id, starts_work=True)
        if not isinstance(port, HostedInteractiveGoalReviewPortV1):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        result = await port.interactive_goal_review(goal_id, check_current=check_current)
        check_current()
        return result

    async def submit_interactive_goal_review(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str, command: InteractiveGoalReviewSubmissionV1,
    ) -> InteractiveGoalViewV1:
        if type(command) is not InteractiveGoalReviewSubmissionV1:
            raise AppServiceError(AppErrorCodeV1.INVALID_REQUEST)
        port, check_current = await self._resolve_interactive_goal(control, expected_instance_id, starts_work=True)
        if not isinstance(port, HostedInteractiveGoalReviewPortV1):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        return port.control_interactive_goal(command, check_current=check_current)

    async def interactive_goal_recovery(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
    ) -> InteractiveGoalRecoveryV1:
        session, binding = await self._resolve(control, expected_instance_id)
        port = binding.port
        if (not isinstance(port, HostedInteractiveGoalRecoveryPortV1)
                or not port.supports_interactive_goal_recovery):
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        result = await port.interactive_goal_recovery()
        self._check(control, session)
        self._registry.require_instance(expected_instance_id)
        if (session._execution is not binding or binding.closing
                or not port.supports_interactive_goal_recovery):
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        return result
