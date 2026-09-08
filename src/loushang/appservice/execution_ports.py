"""Optional Product capability. Existing hosted Session ports stay unchanged."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from loushang.appserver.protocol import SessionIdentityV1

from .execution_contract import (
    ExecutionContentEventV1,
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

    def subscribe_execution_content(
        self, listener: Callable[[ExecutionContentEventV1], None]
    ) -> Callable[[], None]:
        """Nonblocking ordered content subscription, reserved before capture.

        Execution metadata is separately owned by AppService; suppressing a
        covered content event must never suppress outcome settlement.
        """
        ...
