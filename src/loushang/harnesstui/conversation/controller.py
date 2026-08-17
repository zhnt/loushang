"""Product-neutral session action coordination for conversation hosts."""

from __future__ import annotations

import asyncio
import inspect
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from loushang.harness.host.types import HostActionResult
from loushang.harness.session import (
    SessionOperationResolver,
    SessionOperationUnavailableError,
    SessionPromptRequest,
)
from loushang.harnesstui.conversation.intents import (
    AbortIntent,
    BashIntent,
    FollowUpIntent,
    PromptIntent,
    QuitIntent,
)

ImageParts = tuple[object, ...] | list[object] | None
SessionCommandDispatcher = Callable[
    [object], Awaitable[HostActionResult | None]
]
BashExecutor = Callable[[str], Awaitable[None]]
CommandAbort = Callable[[], None | Awaitable[None]]


class _TextIntent(Protocol):
    @property
    def text(self) -> str: ...


class _BashIntent(Protocol):
    @property
    def command(self) -> str: ...


@dataclass
class ConversationUiController:
    """Coordinate conversation actions against explicit, current-session ports.

    The controller owns action sequencing and failure conversion only. Product
    composition resolves the current Session and supplies command/Bash ports;
    Harnesstui never discovers concrete Session methods.
    """

    get_operations: SessionOperationResolver
    dispatch_session_command: SessionCommandDispatcher | None = None
    execute_bash: BashExecutor | None = None
    abort_command: CommandAbort | None = None
    verbose: bool = False
    prompt_intent_type: type[object] | None = None
    bash_intent_type: type[object] | None = None
    follow_up_intent_type: type[object] | None = None
    abort_intent_type: type[object] | None = None
    quit_intent_type: type[object] | None = None
    problem_code_prefix: str = "conversation_ui"
    problem_logger: Any | None = None

    async def dispatch(self, intent: object | None) -> HostActionResult:
        if intent is None:
            return HostActionResult(handled=False)
        try:
            if self.prompt_intent_type is not None and isinstance(
                intent, self.prompt_intent_type
            ):
                prompt_intent = cast(_TextIntent, intent)
                command_result = (
                    await self.dispatch_session_command(intent)
                    if self.dispatch_session_command is not None
                    else None
                )
                if command_result is not None:
                    return command_result
                await self.get_operations().prompt(
                    SessionPromptRequest(
                        text=prompt_intent.text,
                        images=cast(
                            tuple,
                            tuple(getattr(prompt_intent, "images", None) or ()),
                        ),
                        source="interactive",
                    )
                )
                return HostActionResult()
            if self.bash_intent_type is not None and isinstance(
                intent, self.bash_intent_type
            ):
                if self.execute_bash is None:
                    raise RuntimeError("Session does not support bash execution")
                await self.execute_bash(cast(_BashIntent, intent).command)
                return HostActionResult()
            if self.follow_up_intent_type is not None and isinstance(
                intent, self.follow_up_intent_type
            ):
                return await self.follow_up(cast(_TextIntent, intent).text)
            if self.abort_intent_type is not None and isinstance(
                intent, self.abort_intent_type
            ):
                await self.stop_active_interaction()
                return HostActionResult()
            if self.quit_intent_type is not None and isinstance(
                intent, self.quit_intent_type
            ):
                return HostActionResult(exit_code=0)
        except asyncio.CancelledError as error:
            self._record_problem(
                f"{self.problem_code_prefix}_request_cancelled",
                message="Request cancelled.",
                exc=error,
                intent=type(intent).__name__,
            )
            return HostActionResult(
                error_message="Request cancelled.",
                traceback_text=traceback.format_exc() if self.verbose else None,
            )
        except Exception as error:
            self._record_problem(
                f"{self.problem_code_prefix}_dispatch_failed",
                intent=type(intent).__name__,
                message=str(error) or error.__class__.__name__,
                exc=error,
            )
            return HostActionResult(
                error_message=str(error) or error.__class__.__name__,
                traceback_text=traceback.format_exc() if self.verbose else None,
            )
        return HostActionResult(handled=False)

    async def steer(
        self,
        text: str,
        images: ImageParts = None,
    ) -> HostActionResult:
        return await self._dispatch_text_action(
            "steer",
            text,
            images=images,
            unavailable="Steering is unavailable for this session.",
            failure_code="conversation_ui_steer_failed",
        )

    async def follow_up(
        self,
        text: str,
        images: ImageParts = None,
    ) -> HostActionResult:
        return await self._dispatch_text_action(
            "follow_up",
            text,
            images=images,
            unavailable="Follow-up is unavailable for this session.",
            failure_code="conversation_ui_follow_up_failed",
        )

    async def wait_for_idle(self) -> None:
        await self.get_operations().wait_for_idle()

    async def _dispatch_text_action(
        self,
        action: str,
        text: str,
        *,
        images: ImageParts,
        unavailable: str,
        failure_code: str,
    ) -> HostActionResult:
        try:
            operations = self.get_operations()
            normalized_images = cast(tuple, tuple(images or ()))
            if action == "steer":
                operations.steer(text, images=normalized_images)
            else:
                operations.follow_up(text, images=normalized_images)
            return HostActionResult()
        except SessionOperationUnavailableError as error:
            self._record_problem(
                f"{self.problem_code_prefix}_{failure_code.removeprefix('conversation_ui_')}",
                message=str(error),
                exc=error,
            )
            return HostActionResult(error_message=unavailable)
        except Exception as error:
            self._record_problem(
                f"{self.problem_code_prefix}_{failure_code.removeprefix('conversation_ui_')}",
                message=str(error) or error.__class__.__name__,
                exc=error,
            )
            return HostActionResult(
                error_message=str(error) or error.__class__.__name__,
                traceback_text=traceback.format_exc() if self.verbose else None,
            )

    async def stop_active_interaction(self) -> None:
        """Preserve TUI Esc: abort turn, clear queues, then abort command."""

        operations = self.get_operations()
        try:
            operations.abort_turn()
        finally:
            try:
                operations.clear_queue()
            finally:
                if self.abort_command is not None:
                    await _maybe_await(self.abort_command())

    def _record_problem(self, code: str, **details: object) -> None:
        if self.problem_logger is None:
            return
        self.problem_logger.problem(
            code,
            source="agent",
            message=str(details.pop("message", "Request failed.")),
            recoverable=True,
            exc=details.pop("exc", None),
            **details,
        )


def build_standard_conversation_ui_controller(
    *,
    get_operations: SessionOperationResolver,
    dispatch_session_command: SessionCommandDispatcher | None = None,
    execute_bash: BashExecutor | None = None,
    abort_command: CommandAbort | None = None,
    verbose: bool = False,
    problem_code_prefix: str = "conversation_ui",
    problem_logger: Any | None = None,
) -> ConversationUiController:
    """Bind the standard conversation intents to the shared controller."""

    return ConversationUiController(
        get_operations=get_operations,
        dispatch_session_command=dispatch_session_command,
        execute_bash=execute_bash,
        abort_command=abort_command,
        verbose=verbose,
        prompt_intent_type=PromptIntent,
        bash_intent_type=BashIntent,
        follow_up_intent_type=FollowUpIntent,
        abort_intent_type=AbortIntent,
        quit_intent_type=QuitIntent,
        problem_code_prefix=problem_code_prefix,
        problem_logger=problem_logger,
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [
    "BashExecutor",
    "CommandAbort",
    "ConversationUiController",
    "ImageParts",
    "SessionCommandDispatcher",
    "build_standard_conversation_ui_controller",
]
