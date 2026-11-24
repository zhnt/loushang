"""Coding policy bound to the shared HarnessTUI conversation components."""

from __future__ import annotations

import asyncio
import inspect
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TextIO, TypeVar, cast

from loushang.ai.types import ImagePart
from loushang.coding.diagnostics.debug_status import debug_status_text
from loushang.coding.package.product_repair_ui import (
    execute_coding_package_repair_ui_command,
)
from loushang.coding.plugin_manager.operation_guidance import (
    coding_desired_repair_command,
)
from loushang.coding.plugin_manager.read_sdk import (
    open_coding_plugin_management_read_client,
)
from loushang.coding.plugin_manager.ui import (
    execute_coding_plugin_management_ui_command,
)
from loushang.coding.plugin_manager.ui import (
    format_coding_plugin_support_status as _format_coding_plugin_support_status,
)
from loushang.foundation.observability import get_log
from loushang.harness.cli.plugin_explanation import (
    render_plugin_operation_explanation as _format_coding_plugin_operation_explanation,
)
from loushang.harness.cli.plugin_listing import render_plugin_management_list
from loushang.harness.cli.plugin_management import valid_plugin_terminal_identifier
from loushang.harness.cli.plugin_preview import (
    render_plugin_preview as _format_coding_plugin_preview,
)
from loushang.harness.commands import CommandEffectKind
from loushang.harness.conversation import CommandExecutionRecord
from loushang.harness.host.types import HostActionResult
from loushang.harness.session import (
    SessionControlPort,
    SessionOperationAvailability,
    SessionOperationResolver,
    current_session_operation_resolver,
    require_active_session,
    session_operation_resolver,
)
from loushang.harness.workspace.paths import WorkspaceOperationGuard
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
    bind_user_bash_executor,
    build_standard_conversation_ui_controller,
)
from loushang.harnesstui.conversation.intents import (
    ConversationIntent,
    DebugIntent,
)

_LOG = get_log(__name__).bind(component="CodingUiController")
_PluginArgs = ParamSpec("_PluginArgs")
_PluginResultT = TypeVar("_PluginResultT")
_PLUGIN_USAGE = (
    "Usage: /plugins [list | status | explain OPERATION_ID | enable ID | disable ID | "
    "remove ID | repair OPERATION_ID | repair-package ACTION OPERATION_ID]"
)


@dataclass(frozen=True, slots=True)
class ScreenCodingDebugBinding:
    """Late-bound Product effects for the Native screen ``/debug`` command."""

    current_session: Callable[[], object]
    current_cwd: Callable[[], str]
    enable: Callable[..., Path]
    disable: Callable[[], None]


def build_coding_ui_controller(
    *,
    session: Any,
    runtime: Any | None = None,
    verbose: bool = False,
    plugin_workspace: str | Path | None = None,
    plugin_preview: Callable[[], dict[str, object]] | None = None,
    plugin_management_snapshot: Callable[[], dict[str, object]] | None = None,
    plugin_support_status: Callable[[], dict[str, object]] | None = None,
    plugin_operation_explanation: Callable[[str], dict[str, object]] | None = None,
    plugin_command: Callable[[str], HostActionResult] | None = None,
    plugin_package_repair_command: Callable[[str], HostActionResult] | None = None,
    on_bash_record: Callable[[CommandExecutionRecord], None] | None = None,
) -> ConversationUiController:
    get_operations = build_coding_session_operation_resolver(
        session=session,
        runtime=runtime,
    )

    def current_session() -> Any:
        return _current_coding_session(session=session, runtime=runtime)

    def plugin_scope() -> tuple[Any, Path]:
        current = current_session()
        manager = getattr(current, "session_manager", None)
        get_cwd = getattr(manager, "get_cwd", None)
        value = get_cwd() if callable(get_cwd) else plugin_workspace
        if value is None:
            raise RuntimeError("Plugin workspace is unavailable")
        return current, Path(value).resolve(strict=True)

    def assert_plugin_scope(bound_session: Any, workspace: Path) -> None:
        current, current_workspace = plugin_scope()
        if current is not bound_session or current_workspace != workspace:
            raise RuntimeError("Plugin Session workspace changed")

    def bind_plugin_workspace(
        provided: Callable[_PluginArgs, _PluginResultT] | None,
        operation: Callable[Concatenate[Path, _PluginArgs], _PluginResultT],
    ) -> Callable[_PluginArgs, _PluginResultT] | None:
        if provided is not None or plugin_workspace is None:
            return provided

        def guarded(
            *args: _PluginArgs.args, **kwargs: _PluginArgs.kwargs
        ) -> _PluginResultT:
            bound_session, workspace = plugin_scope()
            with WorkspaceOperationGuard(
                lambda: assert_plugin_scope(bound_session, workspace)
            ):
                return operation(workspace, *args, **kwargs)

        return guarded

    async def dispatch_session_command(
        intent: object,
    ) -> HostActionResult | None:
        text = getattr(intent, "text", None)
        from loushang.coding.interaction.goal import (
            execute_goal_command,
            is_goal_command,
        )

        if isinstance(text, str) and is_goal_command(text):
            if getattr(intent, "images", None):
                return HostActionResult(error_message="/goal does not accept image attachments.")
            bound = current_session()
            result = await execute_goal_command(bound, text)
            if current_session() is not bound:
                return HostActionResult(error_message="Goal result belongs to the previous Session.")
            return result
        if isinstance(text, str) and (
            text == "/plugins" or text.startswith("/plugins ")
        ):
            if getattr(intent, "images", None):
                return HostActionResult(error_message="/plugins does not accept attachments.")
            provider = getattr(current_session(), "list_commands", None)
            if callable(provider) and any(
                getattr(command, "name", None) == "plugins"
                for command in provider()
            ):
                return HostActionResult(
                    error_message="/plugins conflicts with a selected Session command."
                )
            if text not in {"/plugins", "/plugins list", "/plugins status"}:
                words = text.split()
                if len(words) == 4 and words[1] == "repair-package":
                    package_command = bind_plugin_workspace(
                        plugin_package_repair_command,
                        lambda workspace, text: execute_coding_package_repair_ui_command(
                            workspace, text
                        ),
                    )
                    if package_command is None:
                        return HostActionResult(
                            error_message="Package repair is unavailable."
                        )
                    try:
                        return await asyncio.to_thread(package_command, text)
                    except Exception:
                        return HostActionResult(
                            error_message="Package repair refused: package_repair_unavailable"
                        )
                if len(words) == 3 and words[1] == "explain":
                    operation_id = words[2]
                    if not valid_plugin_terminal_identifier(operation_id):
                        return HostActionResult(error_message=_PLUGIN_USAGE)
                    def explain_workspace(
                        workspace: Path, operation_id: str, /
                    ) -> dict[str, object]:
                        return open_coding_plugin_management_read_client(
                            workspace
                        ).explain_operation(
                            operation_id,
                            correlation_id="coding:tui:plugins:explain",
                        )

                    explain = bind_plugin_workspace(
                        plugin_operation_explanation, explain_workspace
                    )
                    if explain is None:
                        return HostActionResult(
                            error_message="Plugin explanation is unavailable."
                        )
                    try:
                        document = await asyncio.to_thread(explain, operation_id)
                        return HostActionResult(status_message=(
                            _format_coding_plugin_operation_explanation(
                                document, operation_id=operation_id
                            )
                        ))
                    except Exception:
                        return HostActionResult(
                            error_message="Plugin explanation is unavailable."
                        )
                if len(words) != 3 or words[1] not in {
                    "enable", "disable", "remove", "repair"
                }:
                    return HostActionResult(error_message=_PLUGIN_USAGE)
                command = bind_plugin_workspace(
                    plugin_command,
                    lambda workspace, text: execute_coding_plugin_management_ui_command(
                        workspace, text
                    ),
                )
                if command is None:
                    return HostActionResult(
                        error_message="Plugin commands are unavailable."
                    )
                try:
                    return await asyncio.to_thread(command, text)
                except Exception:
                    return HostActionResult(
                        error_message="Plugin command failed: plugin_management_unavailable"
                    )
            read = (
                plugin_preview
                if text == "/plugins"
                else plugin_management_snapshot
                if text == "/plugins list"
                else plugin_support_status
            )

            def read_workspace(workspace: Path) -> dict[str, object]:
                if text == "/plugins list":
                    current = current_session()
                    return open_coding_plugin_management_read_client(
                        workspace
                    ).management_snapshot(
                        correlation_id="coding:tui:plugins:list",
                        settings_manager=getattr(current, "settings_manager", None),
                    )
                client = open_coding_plugin_management_read_client(workspace)
                if text == "/plugins":
                    return client.preview_current(correlation_id="coding:tui:plugins")
                return client.support_status(correlation_id="coding:tui:plugins:status")

            read = bind_plugin_workspace(read, read_workspace)
            if read is None:
                return HostActionResult(error_message="Plugin preview is unavailable.")
            try:
                document = await asyncio.to_thread(read)
                return HostActionResult(
                    status_message=(
                        _format_coding_plugin_preview(document)
                        if text == "/plugins"
                        else _format_coding_plugin_management_list(document)
                        if text == "/plugins list"
                        else _format_coding_plugin_support_status(document)
                    )
                )
            except Exception:
                return HostActionResult(error_message="Plugin preview is unavailable.")
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

    async def abort_command() -> None:
        current = current_session()
        goal = getattr(current, "_embedded_goal_commands", None)
        try:
            if goal is not None and goal.running:
                await goal.execute("cancel")
        finally:
            command_execution = getattr(current, "command_execution", None)
            abort = getattr(command_execution, "abort", None)
            if not callable(abort):
                abort = getattr(current, "abort_bash", None)
            if callable(abort):
                abort()

    return build_standard_conversation_ui_controller(
        get_operations=get_operations,
        dispatch_session_command=dispatch_session_command,
        execute_bash=bind_user_bash_executor(
            current_session, on_record=on_bash_record
        ),
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


def _format_coding_plugin_management_list(document: dict[str, object]) -> str:
    return render_plugin_management_list(document, repair_command=coding_desired_repair_command)


def build_screen_coding_action_host(
    *,
    presenter: ConversationActionPresentationPort,
    controller: ConversationUiController,
    stderr: TextIO,
    verbose: bool,
    debug: ScreenCodingDebugBinding | None = None,
) -> PresentedConversationActionHost[
    ConversationIntent,
    tuple[ImagePart, ...] | None,
]:
    async def dispatch_intent(intent: ConversationIntent) -> HostActionResult:
        if not isinstance(intent, DebugIntent) or debug is None:
            return await controller.dispatch(intent)
        try:
            if not intent.enabled:
                debug.disable()
                return HostActionResult(status_message="Debug logging disabled.")
            debug_path = debug.enable(
                session=debug.current_session(),
                scopes=intent.scopes,
            )
            return HostActionResult(
                status_message=debug_status_text(
                    debug_path,
                    scopes=intent.scopes,
                    cwd=debug.current_cwd(),
                )
            )
        except Exception as error:
            message = str(error) or error.__class__.__name__
            _LOG.problem(
                "coding_ui_debug_failed",
                source="tui",
                message=message,
                recoverable=True,
                exc=error,
            )
            return HostActionResult(
                error_message=message,
                traceback_text=traceback.format_exc() if verbose else None,
            )

    return build_standard_presented_conversation_action_host(
        presenter=presenter,
        controller=controller,
        stderr=stderr,
        verbose=verbose,
        attachments=agent_image_parts_from_prompt_attachments,
        dispatch_intent=dispatch_intent,
    )


__all__ = [
    "build_coding_session_operation_resolver",
    "build_coding_ui_controller",
    "build_screen_coding_action_host",
    "ScreenCodingDebugBinding",
]
