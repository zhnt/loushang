from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TextIO

from loushang.coding.ui.event_policy import is_cancelled_error_message
from loushang.coding.ui.prompt_dispatch import PromptDispatchOutcome


class Lifecycle(Protocol):
    aborted_id: int | None

    def clear_aborted(self, run_id: int) -> None: ...


class Renderer(Protocol):
    def render_status(self, text: str) -> None: ...
    def render_error(self, text: str) -> None: ...
    def render_worked(self, elapsed_seconds: float) -> None: ...


class StableEmit(Protocol):
    def __call__(self, write_callable: Callable[[], None], *, label: str) -> Awaitable[None]: ...


class TraceFn(Protocol):
    def __call__(self, name: str, **data: Any) -> None: ...


class PromptResultHandler:
    def __init__(
        self,
        *,
        lifecycle: Lifecycle,
        renderer: Renderer,
        emit: StableEmit,
        stderr: TextIO,
        verbose: bool,
        last_error_message: Callable[[], str | None],
        session_error_message: Callable[[], str | None],
        now: Callable[[], float],
        trace: TraceFn,
    ) -> None:
        self._lifecycle = lifecycle
        self._renderer = renderer
        self._emit = emit
        self._stderr = stderr
        self._verbose = verbose
        self._last_error_message = last_error_message
        self._session_error_message = session_error_message
        self._now = now
        self._trace = trace

    async def handle(self, outcome: PromptDispatchOutcome, *, prompt_started: float) -> int | None:
        result = outcome.result
        run_id = outcome.run_id
        error_message = result.error_message or self._session_error_message()
        if (
            run_id is not None
            and self._lifecycle.aborted_id == run_id
            and is_cancelled_error_message(error_message)
        ):
            self._lifecycle.clear_aborted(run_id)
            self._trace("prompt.suppressed_cancelled", run_id=run_id, error_message=error_message)
            return result.exit_code

        if error_message:
            if self._last_error_message() != error_message:
                await self._emit(lambda: self._renderer.render_error(error_message or "Unknown error"), label="prompt:error")
            if self._verbose and result.traceback_text:
                self._stderr.write(result.traceback_text)
                self._stderr.flush()
        elif result.status_message:
            await self._emit(lambda: self._renderer.render_status(result.status_message or ""), label="prompt:status")
        elif outcome.work_intent and result.exit_code is None:
            await self._emit(
                lambda: self._renderer.render_worked(self._now() - outcome.started_at),
                label="prompt:worked",
            )

        self._trace(
            "prompt.end",
            run_id=run_id,
            exit_code=result.exit_code,
            error_message=error_message,
            elapsed_s=self._now() - prompt_started,
        )
        return result.exit_code


__all__ = ["PromptResultHandler"]
