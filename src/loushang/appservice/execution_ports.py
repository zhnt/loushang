"""Optional Product capability. Existing hosted Session ports stay unchanged."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from loushang.appserver.execution.model import (
    InteractiveGoalCommandV1,
    InteractiveGoalRecoveryV1,
    InteractiveGoalReviewSubmissionV1,
    InteractiveGoalReviewV1,
    InteractiveGoalViewV1,
)
from loushang.appserver.protocol import SessionIdentityV1

from .execution_contract import (
    ExecutionContentEventV1,
    ExecutionObservationV1,
    ExecutionOutcomeV1,
    ExecutionRequestV1,
    ExecutionSourceSnapshotV1,
    InterruptModeV1,
)


class HostedExecutionPortV1(Protocol):
    """Explicitly injected capability on one owned Product Session binding.

    start_execution retains an invocation before any asynchronous effect. The
    Product installs its execution identity before command/preflight/model work.
    wait_execution is delivery-cancellation safe and returns only after Product
    quiescence and coherent source completion publication. Cleanup failure keeps
    ownership fenced and can be retried without replaying the input.

    Snapshot captures content/observation at the same source cut. Reopening the
    canonical Session creates a new source lifetime. No existing V1 Product is
    inferred to implement this capability from a normal start_turn return.
    """

    @property
    def identity(self) -> SessionIdentityV1: ...

    def start_execution(self, request: ExecutionRequestV1) -> None: ...

    async def wait_execution(self, execution_id: str) -> ExecutionOutcomeV1: ...

    def interrupt_execution(self, execution_id: str, mode: InterruptModeV1) -> bool:
        """Atomically check target and apply only the requested interrupt scope."""
        ...

    async def retry_execution_settlement(self, execution_id: str) -> None: ...

    async def snapshot_execution(self) -> ExecutionSourceSnapshotV1: ...

    def subscribe_execution_observation(
        self, listener: Callable[[ExecutionObservationV1], None]
    ) -> Callable[[], None]:
        """Nonblocking causal lifecycle notification, reserved before admission.

        Emit running after installing source identity and before any Product
        work, including commands that emit no content. Emit terminal with its
        final cursor only after cleanup. A pre-entry interruption emits neither;
        wait_execution still returns its explicit outcome. This stream never
        passes through a content mailbox or relies on model events.
        """
        ...

    def subscribe_execution_content(
        self, listener: Callable[[ExecutionContentEventV1], None]
    ) -> Callable[[], None]:
        """Nonblocking ordered content subscription, reserved before capture.

        Execution metadata is separately owned by AppService; suppressing a
        covered content event must never suppress outcome settlement.
        """
        ...


@runtime_checkable
class HostedInteractiveGoalPortV1(Protocol):
    @property
    def supports_interactive_goal(self) -> bool: ...

    async def create_interactive_goal(
        self, target: str, *, check_current: Callable[[], None],
    ) -> InteractiveGoalViewV1: ...

    async def interactive_goal_status(self) -> InteractiveGoalViewV1: ...


@runtime_checkable
class HostedInteractiveGoalCommandPortV1(Protocol):
    def control_interactive_goal(
        self, command: InteractiveGoalCommandV1 | InteractiveGoalReviewSubmissionV1, *, check_current: Callable[[], None],
    ) -> InteractiveGoalViewV1: ...


@runtime_checkable
class HostedInteractiveGoalReviewPortV1(HostedInteractiveGoalCommandPortV1, Protocol):
    async def interactive_goal_review(
        self, goal_id: str, *, check_current: Callable[[], None],
    ) -> InteractiveGoalReviewV1: ...


@runtime_checkable
class HostedInteractiveGoalRecoveryPortV1(Protocol):
    @property
    def supports_interactive_goal_recovery(self) -> bool: ...

    async def interactive_goal_recovery(self) -> InteractiveGoalRecoveryV1: ...
