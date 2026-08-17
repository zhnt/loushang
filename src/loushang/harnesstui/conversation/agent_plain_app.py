"""Standard Agent binding for the reusable plain conversation application."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from loushang.harness.commands import CommandDef, CommandEffect
from loushang.harness.session import SessionOperationResolver
from loushang.harnesstui.commands.catalog import (
    ConversationCommandCatalog,
    SessionCommandsProvider,
    snapshot_conversation_command_catalog,
)
from loushang.harnesstui.commands.interaction import (
    CommandInteractionPresentationCopy,
    CommandInteractionSnapshot,
    CommandPaletteChooser,
    present_command_interaction,
    run_command_interaction,
)
from loushang.harnesstui.commands.presentation import (
    command_completion_item,
    format_commands,
)
from loushang.harnesstui.conversation.debug_action import (
    DebugActionCopy,
    DebugActionHandler,
    DebugActionPorts,
)
from loushang.harnesstui.conversation.host import (
    build_standard_conversation_host_profile,
)
from loushang.harnesstui.conversation.info import (
    ConversationLocalActionBinding,
    ConversationLocalActionRegistry,
    ConversationLocalActionResult,
    InfoPanelPresenter,
)
from loushang.harnesstui.conversation.intents import (
    AbortIntent,
    BashIntent,
    CommandSelectIntent,
    CommandsIntent,
    ConversationIntent,
    DebugIntent,
    HotkeysIntent,
    ModelSelectIntent,
    ModelsIntent,
    PromptIntent,
    SettingsIntent,
)
from loushang.harnesstui.conversation.plain_app import (
    PlainConversationApp,
    PlainConversationAssembly,
    PlainConversationController,
    PlainConversationPorts,
    PlainConversationProductBinding,
    PlainConversationProfile,
    PlainConversationRenderer,
    build_plain_conversation_app,
)
from loushang.harnesstui.conversation.queue import (
    pending_queue_view,
    restore_queued_messages,
)
from loushang.harnesstui.conversation.run_context import StableEmit, TraceFn
from loushang.harnesstui.conversation.session_view import (
    is_running,
    session_error_message,
)
from loushang.harnesstui.selection.binding import (
    format_available_session_models,
)
from loushang.harnesstui.selection.interaction import ModelInteractionChooser
from loushang.tui import CompletionProvider


class AgentPlainEventRenderer(Protocol):
    @property
    def last_error_message(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class AgentPlainConversationCopy:
    debug_disabled: str = "Debug logging disabled."
    debug_enabled_label: str = "debug:enabled"
    debug_disabled_label: str = "debug:disabled"
    command_cancelled: str = "Command selection cancelled."
    command_empty: str = "No commands available."
    command_ambiguous_title: str = "Multiple commands match:"
    command_ambiguous_hint: str = "Use /command <full command> to select one."
    command_selected_prefix: str = "Command selected: "
    abort_settling: str = "Abort in progress. Wait for the current request to settle."
    idle_follow_up: str = "Follow-up is only available while a run is active."
    queued_follow_up: str = "Follow-up queued."

    def command_no_match(self, query: str) -> str:
        return f"No commands match: {query}"


@dataclass(frozen=True)
class AgentPlainConversationPorts:
    session: object
    renderer: PlainConversationRenderer
    event_renderer: AgentPlainEventRenderer
    stderr: TextIO
    verbose: bool
    emit: StableEmit
    trace: TraceFn
    now: Callable[[], float]
    controller: PlainConversationController[ConversationIntent]
    get_operations: SessionOperationResolver
    command_effect: Callable[
        [str, ConversationIntent],
        CommandEffect | None,
    ]
    snapshot_commands: Callable[[], Awaitable[Sequence[CommandDef]]]
    select_model: Callable[[str, ModelInteractionChooser | None], Awaitable[str]]
    format_models: Callable[[str], Awaitable[str]]
    hotkeys: Callable[[], str]
    debug_status: Callable[[Path, tuple[str, ...]], str]
    enable_debug: Callable[..., Path]
    disable_debug: Callable[[], None]
    suppress_cancelled_error: Callable[[str | None], bool]
    settings_manager: object | None = None
    completion_provider: CompletionProvider | None = None
    model_palette_chooser: ModelInteractionChooser | None = None
    command_palette_chooser: CommandPaletteChooser | None = None
    info_panel_presenter: InfoPanelPresenter | None = None


def build_agent_plain_conversation_ports(
    *,
    session: object,
    renderer: PlainConversationRenderer,
    event_renderer: AgentPlainEventRenderer,
    stderr: TextIO,
    verbose: bool,
    emit: StableEmit,
    trace: TraceFn,
    now: Callable[[], float],
    controller: PlainConversationController[ConversationIntent],
    get_operations: SessionOperationResolver,
    select_model: Callable[[str, ModelInteractionChooser | None], Awaitable[str]],
    hotkeys: Callable[[], str],
    debug_status: Callable[[Path, tuple[str, ...]], str],
    enable_debug: Callable[..., Path],
    disable_debug: Callable[[], None],
    suppress_cancelled_error: Callable[[str | None], bool],
    settings_manager: object | None = None,
    completion_provider: CompletionProvider | None = None,
    model_palette_chooser: ModelInteractionChooser | None = None,
    command_palette_chooser: CommandPaletteChooser | None = None,
    info_panel_presenter: InfoPanelPresenter | None = None,
    command_catalog: ConversationCommandCatalog | None = None,
) -> AgentPlainConversationPorts:
    """Bind standard command, model, and settings ports for an Agent session."""

    session_commands = _agent_session_commands_provider(session)
    catalog = command_catalog or ConversationCommandCatalog(
        session_commands=session_commands
    )

    async def snapshot_commands() -> Sequence[CommandDef]:
        return (
            await snapshot_conversation_command_catalog(session_commands)
        ).commands()

    return AgentPlainConversationPorts(
        session=session,
        renderer=renderer,
        event_renderer=event_renderer,
        stderr=stderr,
        verbose=verbose,
        emit=emit,
        trace=trace,
        now=now,
        controller=controller,
        get_operations=get_operations,
        command_effect=catalog.effect_for_route,
        snapshot_commands=snapshot_commands,
        select_model=select_model,
        format_models=lambda query: format_available_session_models(
            session,
            query=query,
        ),
        hotkeys=hotkeys,
        debug_status=debug_status,
        enable_debug=enable_debug,
        disable_debug=disable_debug,
        suppress_cancelled_error=suppress_cancelled_error,
        settings_manager=(
            settings_manager
            if settings_manager is not None
            else getattr(session, "settings_manager", None)
        ),
        completion_provider=completion_provider,
        model_palette_chooser=model_palette_chooser,
        command_palette_chooser=command_palette_chooser,
        info_panel_presenter=info_panel_presenter,
    )


def build_agent_plain_conversation_app(
    *,
    ports: AgentPlainConversationPorts,
    copy: AgentPlainConversationCopy = AgentPlainConversationCopy(),
) -> PlainConversationApp:
    """Compose standard Agent local actions over the shared plain app."""

    session = ports.session

    def bind_product(
        assembly: PlainConversationAssembly,
    ) -> PlainConversationProductBinding[ConversationIntent, str]:
        debug_action = DebugActionHandler[Path](
            copy=DebugActionCopy(
                enabled_status=lambda debug_path, scopes: ports.debug_status(
                    debug_path, tuple(scopes)
                ),
                disabled_status=copy.debug_disabled,
                enabled_emit_label=copy.debug_enabled_label,
                disabled_emit_label=copy.debug_disabled_label,
            ),
            ports=DebugActionPorts(
                enable=lambda scopes: ports.enable_debug(
                    session=session,
                    scopes=scopes,
                ),
                disable=ports.disable_debug,
                on_enabled=lambda debug_path, scopes: ports.trace(
                    "debug.enabled",
                    path=str(debug_path),
                    scopes=list(scopes),
                ),
                on_disabled=lambda: ports.trace("debug.disabled"),
                emit=ports.emit,
                render_status=ports.renderer.render_status,
            ),
        )

        async def select_command(query: str) -> str:
            commands = tuple(await ports.snapshot_commands())
            result = await run_command_interaction(
                CommandInteractionSnapshot(commands),
                query=query,
                choose=ports.command_palette_chooser,
            )
            return present_command_interaction(
                result,
                copy=CommandInteractionPresentationCopy[CommandDef](
                    list_items=format_commands,
                    item_text=_command_value,
                    cancelled=copy.command_cancelled,
                    empty=copy.command_empty,
                    no_match=copy.command_no_match,
                    ambiguous_title=copy.command_ambiguous_title,
                    ambiguous_hint=copy.command_ambiguous_hint,
                    selected_prefix=copy.command_selected_prefix,
                ),
            )

        async def local_result(
            text: str | None = None,
        ) -> ConversationLocalActionResult:
            return ConversationLocalActionResult(text=text)

        async def debug(intent: ConversationIntent) -> ConversationLocalActionResult:
            if isinstance(intent, DebugIntent):
                await debug_action.handle(enabled=intent.enabled, scopes=intent.scopes)
            return await local_result()

        async def model_select(
            intent: ConversationIntent,
        ) -> ConversationLocalActionResult:
            query = intent.query if isinstance(intent, ModelSelectIntent) else ""
            return await local_result(
                await ports.select_model(query, ports.model_palette_chooser)
            )

        async def models(intent: ConversationIntent) -> ConversationLocalActionResult:
            query = intent.query if isinstance(intent, ModelsIntent) else ""
            return await local_result(await ports.format_models(query))

        async def command_select(
            intent: ConversationIntent,
        ) -> ConversationLocalActionResult:
            query = intent.query if isinstance(intent, CommandSelectIntent) else ""
            return await local_result(await select_command(query))

        async def commands(intent: ConversationIntent) -> ConversationLocalActionResult:
            query = intent.query if isinstance(intent, CommandsIntent) else ""
            return await local_result(
                format_commands(tuple(await ports.snapshot_commands()), query=query)
            )

        async def hotkeys(
            _intent: ConversationIntent,
        ) -> ConversationLocalActionResult:
            return await local_result(ports.hotkeys())

        async def settings(
            _intent: ConversationIntent,
        ) -> ConversationLocalActionResult:
            return await local_result(assembly.settings_text())

        local_actions = ConversationLocalActionRegistry(
            presenter=assembly.info,
            bindings=(
                ConversationLocalActionBinding(
                    "debug", DebugIntent, debug, deferred=True
                ),
                ConversationLocalActionBinding(
                    "model_select",
                    ModelSelectIntent,
                    model_select,
                    title="Model",
                    label="model:select",
                ),
                ConversationLocalActionBinding(
                    "models",
                    ModelsIntent,
                    models,
                    title="Models",
                    label="models:show",
                    modal=True,
                ),
                ConversationLocalActionBinding(
                    "command_select",
                    CommandSelectIntent,
                    command_select,
                    title="Command",
                    label="command:select",
                ),
                ConversationLocalActionBinding(
                    "commands",
                    CommandsIntent,
                    commands,
                    title="Commands",
                    label="commands:show",
                    modal=True,
                ),
                ConversationLocalActionBinding(
                    "hotkeys",
                    HotkeysIntent,
                    hotkeys,
                    title="Hotkeys",
                    label="hotkeys:show",
                    modal=True,
                ),
                ConversationLocalActionBinding(
                    "settings",
                    SettingsIntent,
                    settings,
                    title="Settings",
                    label="settings:show",
                ),
            ),
        )
        return PlainConversationProductBinding(
            host_profile=build_standard_conversation_host_profile(
                lifecycle=assembly.lifecycle,
                local_actions=local_actions,
                command_effect=ports.command_effect,
                session_running=lambda: is_running(session),
                trace=ports.trace,
                now=ports.now,
            ),
            controller=ports.controller,
            abort_action=lambda: ports.controller.dispatch(AbortIntent()),
            is_work_intent=lambda intent: isinstance(intent, PromptIntent | BashIntent),
            local=local_actions.handle,
            fallback_error_message=lambda: session_error_message(session),
            suppress_aborted_error=ports.suppress_cancelled_error,
        )

    return build_plain_conversation_app(
        profile=PlainConversationProfile(
            statusline_settings_store=ports.settings_manager,
            abort_settling_message=copy.abort_settling,
            idle_follow_up_message=copy.idle_follow_up,
            queued_follow_up_message=copy.queued_follow_up,
            traceback_enabled=ports.verbose,
            now=ports.now,
        ),
        ports=PlainConversationPorts(
            bind_product=bind_product,
            renderer=ports.renderer,
            emit=ports.emit,
            trace=ports.trace,
            stderr=ports.stderr,
            session_running=lambda: is_running(session),
            last_error_message=lambda: ports.event_renderer.last_error_message,
            restore_queue=lambda text: restore_queued_messages(
                ports.get_operations(),
                text,
                trace=ports.trace,
            ),
            pending_messages=lambda: pending_queue_view(ports.get_operations()),
            render_info_panel=getattr(ports.renderer, "render_info_panel", None),
            present_info_panel=ports.info_panel_presenter,
            completion_provider=ports.completion_provider,
        ),
    )


def _command_value(item: CommandDef) -> str:
    completion = command_completion_item(item)
    return completion.value if completion is not None else ""


def _agent_session_commands_provider(
    session: object,
) -> SessionCommandsProvider | None:
    getter = getattr(session, "list_commands", None)
    return getter if callable(getter) else None


__all__ = [
    "AgentPlainConversationCopy",
    "AgentPlainConversationPorts",
    "build_agent_plain_conversation_ports",
    "build_agent_plain_conversation_app",
]
