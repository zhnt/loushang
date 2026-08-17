from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from loushang.harnesstui.conversation.attachments import PromptImageAttachment
from loushang.harnesstui.conversation.run_context import StableEmit, TraceFn


class ActionResult(Protocol):
    """Product-neutral result facts returned by a conversation action."""

    @property
    def exit_code(self) -> int | None: ...

    @property
    def error_message(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ConversationTextAction:
    """Product-neutral text and attachments submitted by a conversation UI."""

    text: str
    attachments: tuple[PromptImageAttachment, ...] = ()
    source: str = ""


class ConversationActionHost(Protocol):
    """Product boundary for actions initiated by a conversation UI."""

    async def submit(self, action: ConversationTextAction) -> int | None: ...

    async def steer(self, action: ConversationTextAction) -> int | None: ...

    async def follow_up(self, action: ConversationTextAction) -> int | None: ...

    async def abort(self) -> None: ...


class RunControl(Protocol):
    active: bool
    active_id: int
    aborted_id: int | None

    def mark_abort_requested(self) -> None: ...


class ActiveRunControl(Protocol):
    active: bool
    active_id: int


class RunIdentity(Protocol):
    active_id: int


class SteerController(Protocol):
    async def steer(self, text: str) -> ActionResult: ...


class FollowUpController(Protocol):
    async def follow_up(self, text: str) -> ActionResult: ...


class InterruptionRenderer(Protocol):
    def render_interruption(self) -> None: ...


class StatusRenderer(Protocol):
    def render_status(self, text: str) -> None: ...


@dataclass
class ConversationRunControl:
    """Track one product-neutral, in-memory conversation UI action run.

    This state coordinates transient input and presentation behavior. It is not
    a Harness Session lifecycle, durable state, or runtime owner.
    """

    active: bool = False
    active_id: int = 0
    aborted_id: int | None = None

    def begin_work(self) -> int:
        self.active = True
        self.active_id += 1
        return self.active_id

    def end_work(self) -> None:
        self.active = False

    def mark_abort_requested(self) -> None:
        if self.active:
            self.aborted_id = self.active_id

    def abort_is_settling(self) -> bool:
        return self.active and self.aborted_id == self.active_id

    def clear_aborted(self, run_id: int) -> None:
        if self.aborted_id == run_id:
            self.aborted_id = None

    def visible_running(self, *, session_running: bool) -> bool:
        return self.active or session_running


class AbortActionHandler:
    """Coordinate transient abort presentation around a supplied action."""

    def __init__(
        self,
        *,
        run_control: RunControl,
        abort_action: Callable[[], Awaitable[Any]],
        renderer: InterruptionRenderer,
        emit: StableEmit,
        session_running: Callable[[], bool],
        trace: TraceFn,
    ) -> None:
        self._run_control = run_control
        self._abort_action = abort_action
        self._renderer = renderer
        self._emit = emit
        self._session_running = session_running
        self._trace = trace

    async def abort(self) -> None:
        self._trace(
            "abort.start",
            active_run=self._run_control.active,
            active_run_id=self._run_control.active_id,
            aborted_run_id=self._run_control.aborted_id,
            session_running=self._session_running(),
        )
        self._run_control.mark_abort_requested()
        await self._emit(
            self._renderer.render_interruption,
            label="abort:interruption",
        )
        await self._abort_action()
        self._trace(
            "abort.end",
            active_run=self._run_control.active,
            active_run_id=self._run_control.active_id,
            aborted_run_id=self._run_control.aborted_id,
            session_running=self._session_running(),
        )


class SteerActionHandler:
    """Dispatch steering text and present a caller-supplied action error."""

    def __init__(
        self,
        *,
        lifecycle: RunIdentity,
        controller: SteerController,
        renderer: StatusRenderer,
        emit: StableEmit,
        trace: TraceFn,
    ) -> None:
        # ``_lifecycle`` remains available for Coding's historical private API.
        self._lifecycle = lifecycle
        self._run_control = lifecycle
        self._controller = controller
        self._renderer = renderer
        self._emit = emit
        self._trace = trace

    async def steer(self, text: str) -> int | None:
        self._trace(
            "prompt.steer.start",
            active_run_id=self._run_control.active_id,
        )
        result = await self._controller.steer(text)
        error_message = result.error_message
        self._trace(
            "prompt.steer.end",
            error_message=error_message,
            exit_code=result.exit_code,
        )
        if error_message:
            await self._emit(
                lambda: self._renderer.render_status(error_message),
                label="steer:error",
            )
        return result.exit_code


class FollowUpActionHandler:
    """Validate, dispatch, and present a queued follow-up action."""

    def __init__(
        self,
        *,
        lifecycle: ActiveRunControl,
        controller: FollowUpController,
        renderer: StatusRenderer,
        emit: StableEmit,
        trace: TraceFn,
        idle_status_message: str,
        queued_status_message: str,
    ) -> None:
        # ``_lifecycle`` remains available for Coding's historical private API.
        self._lifecycle = lifecycle
        self._run_control = lifecycle
        self._controller = controller
        self._renderer = renderer
        self._emit = emit
        self._trace = trace
        self._idle_status_message = idle_status_message
        self._queued_status_message = queued_status_message

    async def queue(self, text: str, *, source: str) -> int | None:
        follow_text = text.strip()
        self._trace(
            "prompt.follow_up.start",
            active_run_id=self._run_control.active_id,
            active_run=self._run_control.active,
            source=source,
            text_len=len(follow_text),
        )
        if not follow_text:
            self._trace(
                "prompt.follow_up.ignored",
                reason="empty",
                source=source,
            )
            return None
        if not self._run_control.active:
            await self._emit(
                lambda: self._renderer.render_status(self._idle_status_message),
                label="follow_up:idle",
            )
            return None

        result = await self._controller.follow_up(follow_text)
        error_message = result.error_message
        self._trace(
            "prompt.follow_up.end",
            error_message=error_message,
            exit_code=result.exit_code,
            source=source,
        )
        if error_message:
            await self._emit(
                lambda: self._renderer.render_status(error_message),
                label="follow_up:error",
            )
        else:
            await self._emit(
                lambda: self._renderer.render_status(self._queued_status_message),
                label="follow_up:queued",
            )
        return result.exit_code


__all__ = [
    "AbortActionHandler",
    "ActionResult",
    "ActiveRunControl",
    "ConversationActionHost",
    "ConversationRunControl",
    "ConversationTextAction",
    "FollowUpActionHandler",
    "FollowUpController",
    "InterruptionRenderer",
    "RunControl",
    "RunIdentity",
    "StableEmit",
    "StatusRenderer",
    "SteerActionHandler",
    "SteerController",
    "TraceFn",
]
