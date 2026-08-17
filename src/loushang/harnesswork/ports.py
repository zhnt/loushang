from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from loushang.harnesswork.event_log import EventLogEntry, EventPosition
from loushang.harnesswork.types import (
    WorkCancellationOutcome,
    WorkEvent,
    WorkEventFact,
    WorkOperation,
    WorkRun,
    WorkRunSpec,
)


class WorkExecutionContext(Protocol):
    """The only Work capability exposed to a domain executor."""

    @property
    def run_id(self) -> str: ...

    @property
    def step_id(self) -> str | None: ...

    @property
    def step_index(self) -> int | None: ...

    @property
    def step_payload(self) -> Mapping[str, object]: ...

    def publish(self, fact: WorkEventFact) -> WorkEvent: ...


class WorkDomainExecutor(Protocol):
    """Execute one accepted operation without owning its Work lifecycle."""

    def execute(
        self,
        operation: WorkOperation,
        context: WorkExecutionContext,
    ) -> Awaitable[object]: ...


class WorkDomainCancellation(Protocol):
    """Ask a domain to abort its invocation and wait until it has settled."""

    def cancel_and_wait(
        self,
        operation: WorkOperation,
        context: WorkExecutionContext,
    ) -> Awaitable[WorkCancellationOutcome]: ...


@dataclass(frozen=True)
class WorkExecutionBinding:
    """The domain capabilities resolved once for one accepted operation."""

    executor: WorkDomainExecutor
    cancellation: WorkDomainCancellation | None = None


class WorkDomainExecutionResolver(Protocol):
    """Resolve focused domain capabilities without teaching Work product details."""

    def resolve(
        self,
        operation: WorkOperation,
        spec: WorkRunSpec,
    ) -> WorkExecutionBinding: ...


class WorkAcceptPort(Protocol):
    async def accept(
        self,
        operation: WorkOperation,
        *,
        spec: WorkRunSpec | None = None,
    ) -> WorkRun: ...


class WorkWaitPort(Protocol):
    async def wait(self, run_id: str) -> WorkRun: ...


class WorkCancelPort(Protocol):
    async def cancel(self, run_id: str) -> WorkRun: ...


class WorkSubscribePort(Protocol):
    def subscribe(
        self,
        *,
        operation_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        after: EventPosition | None = None,
    ) -> AsyncIterator[EventLogEntry]: ...


class WorkQueryPort(Protocol):
    def query(
        self,
        *,
        operation_id: str | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        after: EventPosition | None = None,
        limit: int | None = None,
    ) -> list[EventLogEntry]: ...


WorkEventPublisher = Callable[[WorkEventFact], WorkEvent]


__all__ = [
    "WorkAcceptPort",
    "WorkCancelPort",
    "WorkDomainExecutor",
    "WorkDomainCancellation",
    "WorkDomainExecutionResolver",
    "WorkExecutionBinding",
    "WorkEventPublisher",
    "WorkExecutionContext",
    "WorkQueryPort",
    "WorkSubscribePort",
    "WorkWaitPort",
]
