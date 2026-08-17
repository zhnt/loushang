"""Coding policy bound to the shared HarnessTUI conversation components."""

from __future__ import annotations

import inspect
from typing import Any, TextIO, cast

from loushang.ai.types import ImagePart
from loushang.foundation.observability import get_log
from loushang.harness.commands import CommandEffectKind
from loushang.harness.host.types import HostActionResult
from loushang.harness.session import (
    SessionControlPort,
    SessionOperationAvailability,
    SessionOperationResolver,
    current_session_operation_resolver,
    require_active_session,
    session_operation_resolver,
)
from loushang.harnesstui.commands.catalog import ConversationCommandCatalog
from loushang.harnesstui.conversation.action_presentation import (
    ConversationActionPresentationPort,
    PresentedConversationActionHost,
    build_standard_presented_conversation_action_host,
)
from loushang.harnesstui.conversation.agent_binding import (
    agent_image_parts_from_prompt_attachments,
)
from loushang.harnesstui.conversation.controller import (
    ConversationUiController,
    build_standard_conversation_ui_controller,
)
from loushang.harnesstui.conversation.intents import ConversationIntent

_LOG = get_log(__name__).bind(component="CodingUiController")


def build_coding_ui_controller(
    *,
    session: Any,
    runtime: Any | None = None,
    verbose: bool = False,
) -> ConversationUiController:
    get_operations = build_coding_session_operation_resolver(
        session=session,
        runtime=runtime,
    )

    def current_session() -> Any:
        return _current_coding_session(session=session, runtime=runtime)

    async def dispatch_session_command(
        intent: object,
    ) -> HostActionResult | None:
        if getattr(intent, "images", None):
            return None
        current = current_session()
        command_provider = getattr(current, "list_commands", None)
        executor = getattr(current, "execute_command_async", None)
        if not callable(command_provider) or not callable(executor):
            return None
        catalog = ConversationCommandCatalog(session_commands=command_provider)
        effect = catalog.effect_for_route("dispatch", intent)
        if effect is None or effect.kind is not CommandEffectKind.SESSION:
            return None
        if effect.command.source not in {"builtin", "extension"}:
            return None
        invocation_name = effect.payload.get("invocation_name")
        args = effect.payload.get("args", "")
        if not isinstance(invocation_name, str) or not isinstance(args, str):
            return None
        execution = executor(invocation_name, args)
        if inspect.isawaitable(execution):
            execution = await execution
        return _coding_result_from_command_execution(
            execution,
            invocation_name=invocation_name,
        )

    async def execute_bash(command: str) -> None:
        execution = current_session().execute_bash(
            command,
            exclude_from_context=True,
        )
        if inspect.isawaitable(execution):
            await execution

    def abort_command() -> None:
        current = current_session()
        command_execution = getattr(current, "command_execution", None)
        abort = getattr(command_execution, "abort", None)
        if not callable(abort):
            abort = getattr(current, "abort_bash", None)
        if callable(abort):
            abort()

    return build_standard_conversation_ui_controller(
        get_operations=get_operations,
        dispatch_session_command=dispatch_session_command,
        execute_bash=execute_bash,
        abort_command=abort_command,
        verbose=verbose,
        problem_code_prefix="coding_ui",
        problem_logger=_LOG,
    )


def build_coding_session_operation_resolver(
    *,
    session: Any,
    runtime: Any | None = None,
    availability: SessionOperationAvailability | None = None,
) -> SessionOperationResolver:
    """Bind Coding to an explicit dynamic or fixed Session operation mode."""

    if runtime is not None:
        return current_session_operation_resolver(
            runtime,
            availability=availability,
        )

    control = cast(
        SessionControlPort,
        getattr(session, "session_control", session),
    )
    return session_operation_resolver(
        lambda: control,
        availability=availability,
    )


def _current_coding_session(*, session: Any, runtime: Any | None) -> Any:
    return session if runtime is None else require_active_session(runtime)


def _coding_result_from_command_execution(
    execution: object,
    *,
    invocation_name: str,
) -> HostActionResult:
    result = getattr(execution, "result", None)
    if result is None and not hasattr(execution, "result"):
        result = execution
    if isinstance(result, dict):
        display = result.get("display")
        if isinstance(display, str) and display:
            return HostActionResult(status_message=display)
        message = result.get("message")
        if isinstance(message, str) and message:
            if result.get("status") == "error":
                return HostActionResult(error_message=message)
            return HostActionResult(status_message=message)
    return HostActionResult(status_message=f"Command /{invocation_name} completed.")


def build_screen_coding_action_host(
    *,
    presenter: ConversationActionPresentationPort,
    controller: ConversationUiController,
    stderr: TextIO,
    verbose: bool,
) -> PresentedConversationActionHost[
    ConversationIntent,
    tuple[ImagePart, ...] | None,
]:
    return build_standard_presented_conversation_action_host(
        presenter=presenter,
        controller=controller,
        stderr=stderr,
        verbose=verbose,
        attachments=agent_image_parts_from_prompt_attachments,
    )


__all__ = [
    "build_coding_session_operation_resolver",
    "build_coding_ui_controller",
    "build_screen_coding_action_host",
]
