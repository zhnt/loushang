"""Automatic retry runtime for the optional Agent transcript profile.

The generic runtime layer owns retry timing and lifecycle state. This module
adapts that mechanism to live Agent messages and common session events while
leaving continuation scheduling with the session runtime.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loushang.agent.types import AgentMessage
from loushang.ai.types import AssistantMessage
from loushang.harness.events import (
    RetryAttempt,
    RetryCompleted,
    RetryOutcome,
    RetryStarted,
    SessionRuntimeEventPayload,
)
from loushang.harness.runtime import CancellationController, CancellationSignal
from loushang.harness.runtime.retry import RetryCoordinator, RetryPolicy


@dataclass(frozen=True)
class AutoRetryOutcome:
    """Explicit control result for one automatic-retry check."""

    should_continue: bool = False


_NON_RETRYABLE_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"requires an api key",
        r"\bapi[-_ ]?key\b",
        r"authorization",
        r"authentication",
        r"\bunauthorized\b",
        r"\bforbidden\b",
        r"\b401\b",
        r"\b403\b",
        r"access[_ -]?terminated",
        r"access.?denied",
        r"permission.?denied",
        r"currently only available",
    )
)

_RETRYABLE_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"overloaded",
        r"provider.?returned.?error",
        r"rate.?limit",
        r"too many requests",
        r"\b429\b",
        r"\b500\b",
        r"\b502\b",
        r"\b503\b",
        r"\b504\b",
        r"service.?unavailable",
        r"server.?error",
        r"internal.?error",
        r"network.?error",
        r"network.*connection.*lost",
        r"connection.?error",
        r"connection.?refused",
        r"connection.*lost",
        r"fetch failed",
        r"upstream.?connect",
        r"socket hang up",
        r"ended without",
        r"timed? out",
        r"timeout",
        r"terminated",
        r"retry delay",
    )
)

RetrySettingsProvider = Callable[[], RetryPolicy]
EventDispatcher = Callable[[SessionRuntimeEventPayload], Awaitable[None]]
ContinueRun = Callable[[], Awaitable[None]]
RuntimeExceptionRecorder = Callable[..., None]
RetrySleeper = Callable[[int, CancellationSignal], Awaitable[None]]
MessageProvider = Callable[[], list[AgentMessage]]
MessageSetter = Callable[[list[AgentMessage]], None]
ContextWindowProvider = Callable[[], int | None]
ContextOverflowPredicate = Callable[[AssistantMessage, int], bool]


class AgentTranscriptRetryRuntime:
    """Run retry policy against one Agent transcript's live message state."""

    def __init__(
        self,
        *,
        get_policy: RetrySettingsProvider,
        get_messages: MessageProvider,
        set_messages: MessageSetter,
        get_context_window: ContextWindowProvider,
        dispatch_event: EventDispatcher,
        record_runtime_exception: RuntimeExceptionRecorder,
        sleep_for_retry: RetrySleeper,
        is_context_overflow_fn: ContextOverflowPredicate,
    ) -> None:
        self._get_policy = get_policy
        self._get_messages = get_messages
        self._set_messages = set_messages
        self._get_context_window = get_context_window
        self._dispatch_event = dispatch_event
        self._record_runtime_exception = record_runtime_exception
        self._is_context_overflow = is_context_overflow_fn
        self._coordinator = RetryCoordinator(
            create_cancel_handle=CancellationController,
            cancel=lambda controller: controller.abort(),
            delay=lambda delay_ms, controller: sleep_for_retry(
                delay_ms, controller.signal
            ),
            on_started=self._on_started,
            on_finished=self._on_finished,
        )

    @property
    def attempt(self) -> int:
        return self._coordinator.attempt

    @attempt.setter
    def attempt(self, value: int) -> None:
        self._coordinator.attempt = value

    @property
    def retry_future(self) -> asyncio.Future[None] | object | None:
        return self._coordinator.future

    @retry_future.setter
    def retry_future(self, value: asyncio.Future[None] | object | None) -> None:
        self._coordinator.future = value

    @property
    def is_retrying(self) -> bool:
        return self._coordinator.is_retrying

    @property
    def cancel_handle(self) -> CancellationController | None:
        return self._coordinator.cancel_handle

    @cancel_handle.setter
    def cancel_handle(self, value: CancellationController | None) -> None:
        self._coordinator.cancel_handle = value

    def abort(self) -> None:
        self._coordinator.abort()

    async def wait(self) -> None:
        await self._coordinator.wait()

    def ensure_future(self) -> asyncio.Future[None]:
        return self._coordinator.ensure_waiter()

    async def finish(
        self,
        *,
        success: bool,
        attempt: int,
        final_error: str | None = None,
    ) -> None:
        await self._coordinator.finish(
            RetryOutcome(
                success=success,
                attempt=attempt,
                error=final_error,
                cancelled=final_error == "Retry cancelled",
            )
        )

    async def finish_success_if_needed(
        self, assistant_message: AssistantMessage
    ) -> None:
        if assistant_message.stop_reason != "error" and self.attempt > 0:
            await self.finish(success=True, attempt=self.attempt)

    def should_prepare_retry(self, assistant_message: AssistantMessage) -> bool:
        return self._get_policy().enabled and self.is_retryable_error(assistant_message)

    def is_retryable_error(self, assistant_message: AssistantMessage) -> bool:
        return is_retryable_assistant_error(
            assistant_message,
            context_window=self._get_context_window() or 0,
            is_context_overflow_fn=self._is_context_overflow,
        )

    async def handle_retryable_error(
        self,
        assistant_message: AssistantMessage,
    ) -> AutoRetryOutcome:
        should_continue = await self._coordinator.retry(
            assistant_message.error_message or "",
            policy=self._get_policy(),
            before_retry=self._remove_failed_assistant,
        )
        return AutoRetryOutcome(should_continue=should_continue)

    def continue_retry(self, continue_run: ContinueRun) -> None:
        self._coordinator.continue_retry(continue_run)

    async def _on_started(self, attempt: RetryAttempt) -> None:
        await self._dispatch_event(RetryStarted(attempt=attempt))

    async def _on_finished(self, outcome: RetryOutcome) -> None:
        final_error = (
            ("Retry cancelled" if outcome.cancelled else outcome.error)
            if not outcome.success
            else None
        )
        if final_error is not None:
            self._record_runtime_exception(
                code="retry_cancelled" if outcome.cancelled else "retry_failed",
                exc=final_error,
            )
        await self._dispatch_event(
            RetryCompleted(
                outcome=RetryOutcome(
                    success=outcome.success,
                    attempt=outcome.attempt,
                    error=final_error,
                    cancelled=outcome.cancelled,
                )
            )
        )

    def _remove_failed_assistant(self) -> None:
        messages = self._get_messages()
        if messages and getattr(messages[-1], "role", None) == "assistant":
            self._set_messages(messages[:-1])


def is_retryable_assistant_error(
    message: AssistantMessage,
    *,
    context_window: int,
    is_context_overflow_fn: ContextOverflowPredicate,
) -> bool:
    if message.stop_reason != "error" or not message.error_message:
        return False
    if is_context_overflow_fn(message, context_window):
        return False
    error_info = message.error_info
    if isinstance(error_info, dict) and isinstance(
        error_info.get("retryable"), bool
    ):
        return error_info["retryable"] is True
    if any(
        pattern.search(message.error_message)
        for pattern in _NON_RETRYABLE_ERROR_PATTERNS
    ):
        return False
    return any(
        pattern.search(message.error_message) for pattern in _RETRYABLE_ERROR_PATTERNS
    )


__all__ = [
    "AgentTranscriptRetryRuntime",
    "AutoRetryOutcome",
    "is_retryable_assistant_error",
]
