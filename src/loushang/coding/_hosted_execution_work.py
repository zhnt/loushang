"""Coding's explicit invocation result and retained Session settlement."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from loushang.agent import AbortSignal
from loushang.agent.types import AgentEvent
from loushang.ai.types import AssistantMessage
from loushang.appservice.execution_contract import ExecutionOutcomeV1, ExecutionStatusV1
from loushang.appservice.execution_guard import ExecutionControlV1

from .session.agent_session import AgentSession


class CodingExecutionWorkV1:
    def __init__(
        self, session: AgentSession, text: str, cancel_requested: Callable[[], bool]
    ) -> None:
        self.session = session
        self.text = text
        self._cancel_requested = cancel_requested
        self._interrupted = False
        self._agent_outcome: ExecutionOutcomeV1 | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._unbind_turn: Callable[[], None] | None = None

    async def run(self, control: ExecutionControlV1) -> ExecutionOutcomeV1:
        def observe(event: AgentEvent, signal: AbortSignal) -> None:
            if event["type"] == "agent_end":
                messages = event["messages"]
                for message in reversed(messages):
                    if isinstance(message, AssistantMessage):
                        self._agent_outcome = _assistant_outcome(message)
                        break

        self._unsubscribe = self.session.agent.subscribe(observe)
        self._unbind_turn = control.bind_turn_interrupt(
            lambda: self.session.abort() if self.session.is_streaming else False
        )
        try:
            result = await self.session.execute_prompt(
                self.text, source="appservice", check_cancelled=self._checkpoint
            )
            if result.failure_code is not None:
                return ExecutionOutcomeV1(
                    ExecutionStatusV1.FAILED, error_code=result.failure_code
                )
            if not result.accepted:
                return ExecutionOutcomeV1(
                    ExecutionStatusV1.FAILED, error_code="input_not_accepted"
                )
            if not result.model_started:
                return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
            if self._agent_outcome is None:
                return ExecutionOutcomeV1(
                    ExecutionStatusV1.FAILED, error_code="missing_agent_outcome"
                )
            return self._agent_outcome
        except asyncio.CancelledError:
            self._interrupted = True
            self.session.abort()
            self.session.abort_retry()
            self.session.abort_command()
            self.session.abort_compaction()
            self.session.abort_branch_summary()
            raise
        finally:
            self._clear_turn()

    async def settle(self) -> None:
        await self.session.settle_execution(interrupted=self._interrupted)
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _clear_turn(self) -> None:
        if self._unbind_turn is not None:
            self._unbind_turn()
            self._unbind_turn = None

    def _checkpoint(self) -> None:
        if self._cancel_requested():
            raise asyncio.CancelledError


def _assistant_outcome(message: AssistantMessage) -> ExecutionOutcomeV1:
    if message.stop_reason == "aborted":
        return ExecutionOutcomeV1(ExecutionStatusV1.INTERRUPTED)
    if message.stop_reason == "error":
        return ExecutionOutcomeV1(
            ExecutionStatusV1.FAILED, error_code="assistant_response_error"
        )
    return ExecutionOutcomeV1(ExecutionStatusV1.SUCCEEDED)
