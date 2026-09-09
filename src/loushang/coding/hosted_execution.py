"""Explicitly selected Coding execution port; default Hosted composition is unchanged."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast
from uuid import uuid4

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppFailureV1,
    AppServiceError,
    SessionEventKindV1,
    SessionEventV1,
    SessionSnapshotV1,
)
from loushang.appservice.execution_contract import (
    ExecutionContentEventV1,
    ExecutionOutcomeV1,
    ExecutionRequestV1,
    ExecutionSourceSnapshotV1,
    ExecutionStateV1,
    ExecutionStatusV1,
    InterruptModeV1,
)
from loushang.appservice.execution_guard import ExecutionGuardV1

from ._hosted_execution_work import CodingExecutionWorkV1
from .appservice_adapter import CodingHostedEventProjectionV1, CodingHostedSessionV1
from .hosted_session import CodingRealHostedSessionV1
from .session.agent_session import AgentSession


class CodingHostedExecutionSessionV1(CodingHostedSessionV1):
    """Own the optional capability and the legacy surface on one real binding.

    The caller transfers exclusive binding ownership. No second Hosted adapter
    or direct input driver may run against that same AgentSession concurrently.
    """

    def __init__(self, binding: CodingRealHostedSessionV1) -> None:
        if type(binding) is not CodingRealHostedSessionV1:
            raise TypeError("execution requires a real Coding Product binding")
        self._session = cast(AgentSession, binding.control)
        self._content: set[Callable[[ExecutionContentEventV1], None]] = set()
        self._draft = ""
        self._truncated = False
        self._closing = False
        self._execution_close_task: asyncio.Task[None] | None = None
        super().__init__(binding)
        self._projection = binding.project_snapshot()
        self._guard = ExecutionGuardV1(source_cursor=self._complete_source)

    @property
    def execution_state(self) -> ExecutionStateV1 | None:
        return self._guard.state

    def start_execution(self, request: ExecutionRequestV1) -> None:
        self._require_execution_open()
        if not self._session.execution_available:
            raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
        self._guard.start(
            request,
            CodingExecutionWorkV1(
                self._session, request.text, lambda: self._guard.interrupt_requested
            ),
        )

    async def wait_execution(self, execution_id: str) -> ExecutionOutcomeV1:
        return await self._guard.wait(execution_id)

    def interrupt_execution(self, execution_id: str, mode: InterruptModeV1) -> bool:
        self._require_execution_open()
        return self._guard.interrupt(execution_id, mode)

    async def retry_execution_settlement(self, execution_id: str) -> None:
        await self._guard.retry_settlement(execution_id)

    async def start_turn(self, text: str) -> None:
        execution_id = "legacy-" + uuid4().hex
        self.start_execution(ExecutionRequestV1(execution_id, text))
        outcome = await self.wait_execution(execution_id)
        if isinstance(outcome.legacy_result, AppFailureV1):
            raise AppServiceError(outcome.legacy_result.code)

    def interrupt_turn(self) -> bool:
        self._require_execution_open()
        state = self._guard.state
        return state is not None and self._guard.interrupt(
            state.execution_id, InterruptModeV1.LEGACY_TURN_ONLY
        )

    async def snapshot_execution(self) -> ExecutionSourceSnapshotV1:
        self._require_execution_open()
        projection, observation = self._projection, self._guard.observation
        return ExecutionSourceSnapshotV1(
            source=SessionSnapshotV1(
                identity=self.identity,
                title=projection.title,
                cursor=self._cursor,
                revision=projection.revision,
                running=observation.status is ExecutionStatusV1.RUNNING,
                records=projection.records,
            ),
            observation=observation,
            draft=self._draft
            if observation.status is ExecutionStatusV1.RUNNING
            else "",
            truncated=self._truncated or projection.truncated,
        )

    def subscribe_execution_content(
        self, listener: Callable[[ExecutionContentEventV1], None]
    ) -> Callable[[], None]:
        self._require_execution_open()
        if not callable(listener):
            raise TypeError("execution content listener must be callable")
        self._content.add(listener)
        return lambda: self._content.discard(listener)

    def _observe_projection(
        self, projection: CodingHostedEventProjectionV1, event: SessionEventV1
    ) -> None:
        self._projection = self._binding.project_snapshot()
        if event.kind is SessionEventKindV1.ASSISTANT_DELTA:
            text = self._draft + (event.text or "")
            self._truncated |= len(text) > 16_384 or projection.truncated
            self._draft = text[:16_384]
        elif event.kind in {
            SessionEventKindV1.ASSISTANT_MESSAGE,
            SessionEventKindV1.TURN_STARTED,
            SessionEventKindV1.TURN_COMPLETED,
            SessionEventKindV1.TURN_INTERRUPTED,
        }:
            self._draft = ""
            self._truncated = False
        observation = self._guard.observation
        envelope = ExecutionContentEventV1(
            event,
            observation.execution_id
            if observation.status is ExecutionStatusV1.RUNNING
            else None,
        )
        for listener in tuple(self._content):
            try:
                listener(envelope)
            except Exception:
                self._content.discard(listener)

    def _complete_source(self) -> int:
        self._projection = self._binding.project_snapshot()
        self._draft = ""
        self._truncated = False
        return self._cursor

    async def close(self) -> None:
        self._closing = True
        task = self._execution_close_task
        if task is None or (
            task.done() and (task.cancelled() or task.exception() is not None)
        ):
            task = asyncio.create_task(self._close_execution())
            task.add_done_callback(_observe_close)
            self._execution_close_task = task
        await asyncio.shield(task)

    async def _close_execution(self) -> None:
        state = self._guard.state
        if state is not None and not state.status.terminal:
            self._guard.interrupt(state.execution_id, InterruptModeV1.WHOLE_EXECUTION)
            await self._guard.retry_settlement(state.execution_id)
        await super().close()
        self._content.clear()

    def _require_execution_open(self) -> None:
        self._require_open()

    def _require_open(self) -> None:
        super()._require_open()
        if self._closing:
            raise RuntimeError("coding_hosted_session_closed")


def _observe_close(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


__all__ = ["CodingHostedExecutionSessionV1"]
