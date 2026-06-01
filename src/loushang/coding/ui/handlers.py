from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from loushang.coding.commands.catalog import CodingCommandCatalog
from loushang.coding.ui.intent import (
    CodingUiIntent,
    CommandSelectIntent,
    CommandsIntent,
    FollowUpIntent,
    ModelSelectIntent,
    ModelsIntent,
    QuitIntent,
    StatuslineIntent,
    parse_prompt_intent,
)
from loushang.coding.ui.lifecycle import RunLifecycle
from loushang.coding.ui.pending_queue import pending_queue_view, restore_queued_messages
from loushang.coding.ui.prompt_dispatch import PromptDispatchOutcome
from loushang.coding.ui.prompt_routing import PromptRoute, route_prompt_intent
from loushang.runtime.commands import CommandEffect, CommandEffectKind
from loushang.tui import InfoPanel, PendingQueueView, SettingsList


class TraceFn(Protocol):
    def __call__(self, name: str, **data: Any) -> None: ...


class StableEmit(Protocol):
    def __call__(self, write_callable: Callable[[], None], *, label: str) -> Awaitable[None]: ...


class FollowUpFn(Protocol):
    def __call__(self, text: str, *, source: str) -> Awaitable[int | None]: ...


class PromptDispatchFn(Protocol):
    def __call__(self, intent: CodingUiIntent) -> Awaitable[PromptDispatchOutcome]: ...


class PromptResultFn(Protocol):
    def __call__(self, outcome: Any, *, prompt_started: float) -> Awaitable[int | None]: ...


class CommandCatalog(Protocol):
    def effect_for_route(self, route: PromptRoute, intent: CodingUiIntent) -> CommandEffect | None: ...


class ModelsFn(Protocol):
    def __call__(self, query: str) -> Awaitable[str]: ...


class ModelSelectFn(Protocol):
    def __call__(self, query: str) -> Awaitable[str]: ...


class CommandsFn(Protocol):
    def __call__(self, query: str) -> Awaitable[str]: ...


class CommandSelectFn(Protocol):
    def __call__(self, query: str) -> Awaitable[str]: ...


class SettingsFn(Protocol):
    def __call__(self) -> str: ...


class SettingsListFn(Protocol):
    def __call__(self) -> SettingsList: ...


class ApplySettingsFn(Protocol):
    def __call__(self, settings: SettingsList) -> str: ...


class InfoPanelPresenter(Protocol):
    def __call__(self, panel: InfoPanel) -> bool | Awaitable[bool]: ...


class SettingsListPresenter(Protocol):
    def __call__(self, settings: SettingsList) -> SettingsList | None | Awaitable[SettingsList | None]: ...


class CodingTuiHandlers:
    def __init__(
        self,
        *,
        lifecycle: RunLifecycle,
        parse_prompt: Callable[[str], CodingUiIntent | None] = parse_prompt_intent,
        route_prompt: Callable[[CodingUiIntent, RunLifecycle], PromptRoute] = route_prompt_intent,
        command_catalog: CommandCatalog | None = None,
        follow_up: FollowUpFn,
        steer: Callable[[str], Awaitable[int | None]],
        debug: Callable[[Any], Awaitable[int | None]],
        dispatch: PromptDispatchFn,
        result: PromptResultFn,
        abort: Callable[[], Awaitable[None]],
        restore_queue: Callable[[str], Awaitable[str | None]] | None = None,
        session: Any | None = None,
        emit: StableEmit,
        render_status: Callable[[str], None],
        render_info_panel: Callable[[InfoPanel], None] | None = None,
        present_info_panel: InfoPanelPresenter | None = None,
        status: Callable[[], str] = lambda: "",
        model_select: ModelSelectFn | None = None,
        models: ModelsFn | None = None,
        command_select: CommandSelectFn | None = None,
        commands: CommandsFn | None = None,
        hotkeys: Callable[[], str] = lambda: "",
        settings: SettingsFn | None = None,
        settings_list: SettingsListFn | None = None,
        apply_settings: ApplySettingsFn | None = None,
        present_settings_list: SettingsListPresenter | None = None,
        statusline: Callable[[bool | None], str] = lambda _enabled: "",
        now: Callable[[], float],
        session_running: Callable[[], bool],
        trace: TraceFn,
    ) -> None:
        self._lifecycle = lifecycle
        self._parse_prompt = parse_prompt
        self._route_prompt = route_prompt
        self._command_catalog = command_catalog or CodingCommandCatalog(session_commands=_session_commands_provider(session))
        self._follow_up = follow_up
        self._steer = steer
        self._debug = debug
        self._dispatch = dispatch
        self._result = result
        self._abort = abort
        self._restore_queue = restore_queue
        self._session = session
        self._emit = emit
        self._render_status = render_status
        self._render_info_panel = render_info_panel
        self._present_info_panel = present_info_panel
        self._status = status
        self._model_select = model_select or _empty_model_select
        self._models = models or _empty_models
        self._command_select = command_select or _empty_command_select
        self._commands = commands or _empty_commands
        self._hotkeys = hotkeys
        self._settings = settings or _empty_settings
        self._settings_list = settings_list
        self._apply_settings = apply_settings
        self._present_settings_list = present_settings_list
        self._statusline = statusline
        self._now = now
        self._session_running = session_running
        self._trace = trace

    async def handle_prompt(self, text: str) -> int | None:
        prompt_started = self._now()
        self._trace(
            "prompt.start",
            active_run=self._lifecycle.active,
            active_run_id=self._lifecycle.active_id,
            aborted_run_id=self._lifecycle.aborted_id,
            session_running=self._session_running(),
            text_len=len(text),
        )
        intent = self._parse_prompt(text)
        if intent is None:
            self._trace("prompt.ignored", reason="empty")
            return None

        route = self._route_prompt(intent, self._lifecycle)
        if route is PromptRoute.ABORT_SETTLING:
            self._trace("prompt.ignored", reason="abort_in_progress", active_run_id=self._lifecycle.active_id)
            await self._emit(
                lambda: self._render_status("Abort in progress. Wait for the current request to settle."),
                label="abort:pending_input",
            )
            return None
        if route is PromptRoute.FOLLOW_UP:
            if isinstance(intent, FollowUpIntent):
                return await self.queue_follow_up(intent.text, source="command")
            return None
        if route is PromptRoute.STEER:
            return await self._steer(text)
        if route is PromptRoute.DEBUG:
            return await self._debug(intent)
        effect = self._command_catalog.effect_for_route(route, intent)
        if effect is not None:
            self._trace(
                "prompt.command",
                route=route.value,
                command_id=effect.command.id,
                command_name=effect.command.name,
                effect=effect.kind.value,
            )
            if effect.kind is CommandEffectKind.LOCAL_UI and await self._handle_local_command_effect(effect, intent):
                return None
        if route is PromptRoute.STATUS:
            await self._show_info("Status", self._status(), label="status:show", local=True)
            return None
        if route is PromptRoute.MODEL_SELECT:
            query = intent.query if isinstance(intent, ModelSelectIntent) else ""
            text = await self._model_select(query)
            await self._emit(lambda: self._render_info("Model", text), label="model:select")
            return None
        if route is PromptRoute.MODELS:
            query = intent.query if isinstance(intent, ModelsIntent) else ""
            text = await self._models(query)
            await self._show_info("Models", text, label="models:show", local=True)
            return None
        if route is PromptRoute.COMMAND_SELECT:
            query = intent.query if isinstance(intent, CommandSelectIntent) else ""
            text = await self._command_select(query)
            await self._emit(lambda: self._render_info("Command", text), label="command:select")
            return None
        if route is PromptRoute.COMMANDS:
            query = intent.query if isinstance(intent, CommandsIntent) else ""
            text = await self._commands(query)
            await self._show_info("Commands", text, label="commands:show", local=True)
            return None
        if route is PromptRoute.HOTKEYS:
            await self._show_info("Hotkeys", self._hotkeys(), label="hotkeys:show", local=True)
            return None
        if route is PromptRoute.SETTINGS:
            if await self._show_settings_list():
                return None
            await self._emit(lambda: self._render_info("Settings", self._settings()), label="settings:show")
            return None
        if route is PromptRoute.STATUSLINE:
            enabled = intent.enabled if isinstance(intent, StatuslineIntent) else None
            message = self._statusline(enabled)
            await self._emit(lambda: self._render_status(message), label="statusline:set")
            return None

        outcome = await self._dispatch(intent)
        return await self._result(outcome, prompt_started=prompt_started)

    async def _handle_local_command_effect(self, effect: CommandEffect, intent: CodingUiIntent) -> bool:
        command_name = effect.command.name
        if command_name == "status":
            await self._show_info("Status", self._status(), label="status:show", local=True)
            return True
        if command_name == "model":
            query = intent.query if isinstance(intent, ModelSelectIntent) else ""
            text = await self._model_select(query)
            await self._emit(lambda: self._render_info("Model", text), label="model:select")
            return True
        if command_name == "models":
            query = intent.query if isinstance(intent, ModelsIntent) else ""
            text = await self._models(query)
            await self._show_info("Models", text, label="models:show", local=True)
            return True
        if command_name == "command":
            query = intent.query if isinstance(intent, CommandSelectIntent) else ""
            text = await self._command_select(query)
            await self._emit(lambda: self._render_info("Command", text), label="command:select")
            return True
        if command_name == "commands":
            query = intent.query if isinstance(intent, CommandsIntent) else ""
            text = await self._commands(query)
            await self._show_info("Commands", text, label="commands:show", local=True)
            return True
        if command_name == "hotkeys":
            await self._show_info("Hotkeys", self._hotkeys(), label="hotkeys:show", local=True)
            return True
        if command_name == "settings":
            if await self._show_settings_list():
                return True
            await self._emit(lambda: self._render_info("Settings", self._settings()), label="settings:show")
            return True
        if command_name == "statusline":
            enabled = intent.enabled if isinstance(intent, StatuslineIntent) else None
            message = self._statusline(enabled)
            await self._emit(lambda: self._render_status(message), label="statusline:set")
            return True
        return False

    async def queue_follow_up(self, text: str, *, source: str) -> int | None:
        return await self._follow_up(text, source=source)

    async def handle_follow_up(self, text: str) -> int | None:
        return await self.queue_follow_up(text, source="keybinding")

    async def handle_abort(self) -> None:
        await self._abort()

    async def restore_queue_to_composer(self, current_text: str) -> str | None:
        if self._restore_queue is not None:
            return await self._restore_queue(current_text)
        if self._session is None:
            return None
        return await restore_queued_messages(self._session, current_text, trace=self._trace)

    def pending_messages(self) -> PendingQueueView:
        return pending_queue_view(self._session)

    def should_exit(self, text: str) -> bool:
        return isinstance(self._parse_prompt(text), QuitIntent)

    def _render_info(self, title: str, text: str) -> None:
        if self._render_info_panel is None:
            self._render_status(text)
            return
        self._render_info_panel(InfoPanel.from_text(title=title, text=text, footer=""))

    async def _show_info(self, title: str, text: str, *, label: str, local: bool) -> None:
        if local and self._present_info_panel is not None:
            panel = InfoPanel.from_text(title=title, text=text, footer="Press Enter to continue.")
            handled = await _resolve(self._present_info_panel(panel))
            if handled:
                return
        panel = InfoPanel.from_text(title=title, text=text, footer="")
        await self._emit(lambda: self._render_panel_or_status(panel), label=label)

    def _render_panel_or_status(self, panel: InfoPanel) -> None:
        if self._render_info_panel is None:
            self._render_status("\n".join(panel.lines))
            return
        self._render_info_panel(panel)

    async def _show_settings_list(self) -> bool:
        if self._settings_list is None or self._apply_settings is None or self._present_settings_list is None:
            return False
        settings = await _resolve(self._present_settings_list(self._settings_list()))
        if settings is None:
            return True
        message = self._apply_settings(settings)
        await self._emit(lambda: self._render_status(message), label="settings:set")
        return True


async def _empty_models(_query: str) -> str:
    return "No models available."


async def _empty_model_select(_query: str) -> str:
    return "Model selection is not available."


async def _empty_commands(_query: str) -> str:
    return "No commands available."


async def _empty_command_select(_query: str) -> str:
    return "Command selection is not available."


def _empty_settings() -> str:
    return "No settings available."


def _session_commands_provider(session: Any | None):
    if session is None:
        return None
    getter = getattr(session, "list_commands", None)
    if not callable(getter):
        return None
    return getter


async def _resolve(value):
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = ["CodingTuiHandlers"]
