from __future__ import annotations

import asyncio


class _Lifecycle:
    active = False
    active_id = 0
    aborted_id = None

    def abort_is_settling(self) -> bool:
        return False


def test_coding_tui_handlers_ignore_empty_prompt() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers

    traces: list[tuple[str, dict[str, object]]] = []
    dispatched: list[str] = []

    async def dispatch(_intent):
        dispatched.append("dispatch")

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: None,
        route_prompt=lambda _intent, _lifecycle: None,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=dispatch,
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=lambda _write, *, label: _async_none(),
        render_status=lambda _text: None,
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda name, **data: traces.append((name, data)),
    )

    result = asyncio.run(handlers.handle_prompt("   "))

    assert result is None
    assert dispatched == []
    assert traces == [
        (
            "prompt.start",
            {
                "active_run": False,
                "active_run_id": 0,
                "aborted_run_id": None,
                "session_running": False,
                "text_len": 3,
            },
        ),
        ("prompt.ignored", {"reason": "empty"}),
    ]


def test_coding_tui_handlers_block_abort_settling_input() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import PromptIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    statuses: list[str] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda text: PromptIntent(text),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.ABORT_SETTLING,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        now=lambda: 10.0,
        session_running=lambda: True,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("hello"))

    assert result is None
    assert emitted == ["abort:pending_input"]
    assert statuses == ["Abort in progress. Wait for the current request to settle."]


def test_coding_tui_handlers_renders_status_command() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import StatusIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    statuses: list[str] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: StatusIntent(),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.STATUS,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        status=lambda: "model=m cwd=/repo session=sid",
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/status"))

    assert result is None
    assert emitted == ["status:show"]
    assert statuses == ["model=m cwd=/repo session=sid"]


def test_coding_tui_handlers_routes_status_through_command_catalog() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import StatusIntent
    from loushang.coding.ui.prompt_routing import PromptRoute
    from loushang.runtime.commands import (
        CommandDef,
        CommandEffect,
        CommandEffectKind,
        CommandKind,
    )

    emitted: list[str] = []
    statuses: list[str] = []
    catalog_calls: list[tuple[PromptRoute, object]] = []

    class Catalog:
        def effect_for_route(self, route: PromptRoute, intent: object) -> CommandEffect | None:
            catalog_calls.append((route, intent))
            return CommandEffect(
                kind=CommandEffectKind.LOCAL_UI,
                command=CommandDef(
                    id="coding.ui.status",
                    name="status",
                    kind=CommandKind.LOCAL_UI,
                    description="Show current status",
                ),
            )

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    intent = StatusIntent()
    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: intent,
        route_prompt=lambda _intent, _lifecycle: PromptRoute.STATUS,
        command_catalog=Catalog(),
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        status=lambda: "model=m cwd=/repo session=sid",
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/status"))

    assert result is None
    assert emitted == ["status:show"]
    assert statuses == ["model=m cwd=/repo session=sid"]
    assert catalog_calls == [(PromptRoute.STATUS, intent)]


def test_coding_tui_handlers_can_render_status_command_with_info_panel() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import StatusIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    panels: list[tuple[str, tuple[str, ...]]] = []

    async def emit(write, *, label: str):
        assert label == "status:show"
        write()

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: StatusIntent(),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.STATUS,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda _text: None,
        render_info_panel=lambda panel: panels.append((panel.title, tuple(panel.lines))),
        status=lambda: "model=m cwd=/repo session=sid",
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/status"))

    assert result is None
    assert panels == [("Status", ("model=m cwd=/repo session=sid",))]


def test_coding_tui_handlers_prefers_local_info_panel_presenter_for_status() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import StatusIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    rendered: list[str] = []
    presented: list[tuple[str, tuple[str, ...], str]] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    async def present(panel):
        presented.append((panel.title, tuple(panel.lines), panel.footer))
        return True

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: StatusIntent(),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.STATUS,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=rendered.append,
        present_info_panel=present,
        status=lambda: "model=m cwd=/repo session=sid",
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/status"))

    assert result is None
    assert emitted == []
    assert rendered == []
    assert presented == [("Status", ("model=m cwd=/repo session=sid",), "Press Enter to continue.")]


def test_coding_tui_handlers_prefers_local_info_panel_presenter_for_hotkeys() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import HotkeysIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    rendered: list[str] = []
    presented: list[tuple[str, tuple[str, ...], str]] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    async def present(panel):
        presented.append((panel.title, tuple(panel.lines), panel.footer))
        return True

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: HotkeysIntent(),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.HOTKEYS,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=rendered.append,
        present_info_panel=present,
        hotkeys=lambda: "Hotkeys:\nEsc: abort",
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/hotkeys"))

    assert result is None
    assert emitted == []
    assert rendered == []
    assert presented == [("Hotkeys", ("Hotkeys:", "Esc: abort"), "Press Enter to continue.")]


def test_coding_tui_handlers_renders_models_command() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import ModelsIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    statuses: list[str] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    async def models(query: str) -> str:
        return f"models:{query}"

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: ModelsIntent(query="kimi"),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.MODELS,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        models=models,
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/models kimi"))

    assert result is None
    assert emitted == ["models:show"]
    assert statuses == ["models:kimi"]


def test_coding_tui_handlers_handles_model_select_command() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import ModelSelectIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    statuses: list[str] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    async def model_select(query: str) -> str:
        return f"selected:{query}"

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: ModelSelectIntent(query="kimi"),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.MODEL_SELECT,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        model_select=model_select,
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/model kimi"))

    assert result is None
    assert emitted == ["model:select"]
    assert statuses == ["selected:kimi"]


def test_coding_tui_handlers_renders_hotkeys_command() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import HotkeysIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    statuses: list[str] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: HotkeysIntent(),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.HOTKEYS,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        hotkeys=lambda: "hotkeys",
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/hotkeys"))

    assert result is None
    assert emitted == ["hotkeys:show"]
    assert statuses == ["hotkeys"]


def test_coding_tui_handlers_renders_settings_command() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import SettingsIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    statuses: list[str] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: SettingsIntent(),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.SETTINGS,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        settings=lambda: "settings",
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/settings"))

    assert result is None
    assert emitted == ["settings:show"]
    assert statuses == ["settings"]


def test_coding_tui_handlers_prefers_local_settings_list_presenter() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import SettingsIntent
    from loushang.coding.ui.prompt_routing import PromptRoute
    from loushang.tui import SettingItem, SettingsList

    emitted: list[str] = []
    statuses: list[str] = []
    presented: list[SettingsList] = []
    applied: list[SettingsList] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    async def present(settings: SettingsList) -> SettingsList:
        presented.append(settings)
        return settings.set_enabled("statusline", False)

    def apply(settings: SettingsList) -> str:
        applied.append(settings)
        return "Status line: off"

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: SettingsIntent(),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.SETTINGS,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=statuses.append,
        settings=lambda: "fallback settings",
        settings_list=lambda: SettingsList((SettingItem(id="statusline", label="Status line", enabled=True),)),
        apply_settings=apply,
        present_settings_list=present,
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/settings"))

    assert result is None
    assert emitted == ["settings:set"]
    assert statuses == ["Status line: off"]
    assert presented and presented[0].items[0].enabled is True
    assert applied and applied[0].items[0].enabled is False


def test_coding_tui_handlers_handles_statusline_command() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import StatuslineIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    statuses: list[str] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: StatuslineIntent(enabled=False),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.STATUSLINE,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        statusline=lambda enabled: f"statusline:{enabled}",
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/statusline off"))

    assert result is None
    assert emitted == ["statusline:set"]
    assert statuses == ["statusline:False"]


def test_coding_tui_handlers_renders_commands_command() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import CommandsIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    statuses: list[str] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    async def commands(query: str) -> str:
        return f"commands:{query}"

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: CommandsIntent(query="model"),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.COMMANDS,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        commands=commands,
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/commands model"))

    assert result is None
    assert emitted == ["commands:show"]
    assert statuses == ["commands:model"]


def test_coding_tui_handlers_handles_command_select_command() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import CommandSelectIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    emitted: list[str] = []
    statuses: list[str] = []

    async def emit(write, *, label: str):
        emitted.append(label)
        write()

    async def command_select(query: str) -> str:
        return f"selected:{query}"

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=lambda _text: CommandSelectIntent(query="demo"),
        route_prompt=lambda _intent, _lifecycle: PromptRoute.COMMAND_SELECT,
        follow_up=lambda _text, *, source: _async_none(),
        steer=lambda _text: _async_none(),
        debug=lambda _intent: _async_none(),
        dispatch=lambda _intent: _async_none(),
        result=lambda _outcome, *, prompt_started: _async_none(),
        abort=lambda: _async_none(),
        restore_queue=lambda _text: _async_none(),
        emit=emit,
        render_status=lambda text: statuses.append(text),
        command_select=command_select,
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    result = asyncio.run(handlers.handle_prompt("/command demo"))

    assert result is None
    assert emitted == ["command:select"]
    assert statuses == ["selected:demo"]


def test_coding_tui_handlers_routes_follow_up_steer_debug_dispatch_abort_and_restore() -> None:
    from loushang.coding.ui.handlers import CodingTuiHandlers
    from loushang.coding.ui.intent import DebugIntent, FollowUpIntent, PromptIntent
    from loushang.coding.ui.prompt_routing import PromptRoute

    calls: list[tuple[str, object]] = []
    routes = {
        "follow": PromptRoute.FOLLOW_UP,
        "steer": PromptRoute.STEER,
        "debug": PromptRoute.DEBUG,
        "dispatch": PromptRoute.DISPATCH,
    }

    async def follow_up(text, *, source: str):
        calls.append((f"follow:{source}", text))
        return 1

    async def steer(text):
        calls.append(("steer", text))
        return 2

    async def debug(intent):
        calls.append(("debug", intent))
        return 3

    async def dispatch(intent):
        calls.append(("dispatch", intent))
        return "outcome"

    async def result(outcome, *, prompt_started: float):
        calls.append(("result", (outcome, prompt_started)))
        return 4

    async def abort():
        calls.append(("abort", ""))

    async def restore(text):
        calls.append(("restore", text))
        return "restored"

    def parse(text: str):
        if text == "follow":
            return FollowUpIntent("later")
        if text == "debug":
            return DebugIntent()
        return PromptIntent(text)

    def route(intent, _lifecycle):
        if isinstance(intent, FollowUpIntent):
            return PromptRoute.FOLLOW_UP
        if isinstance(intent, DebugIntent):
            return PromptRoute.DEBUG
        return routes[intent.text]

    handlers = CodingTuiHandlers(
        lifecycle=_Lifecycle(),
        parse_prompt=parse,
        route_prompt=route,
        follow_up=follow_up,
        steer=steer,
        debug=debug,
        dispatch=dispatch,
        result=result,
        abort=abort,
        restore_queue=restore,
        emit=lambda _write, *, label: _async_none(),
        render_status=lambda _text: None,
        now=lambda: 10.0,
        session_running=lambda: False,
        trace=lambda _name, **_data: None,
    )

    assert asyncio.run(handlers.handle_prompt("follow")) == 1
    assert asyncio.run(handlers.handle_follow_up("inline")) == 1
    assert asyncio.run(handlers.handle_prompt("steer")) == 2
    assert asyncio.run(handlers.handle_prompt("debug")) == 3
    assert asyncio.run(handlers.handle_prompt("dispatch")) == 4
    assert asyncio.run(handlers.handle_abort()) is None
    assert asyncio.run(handlers.restore_queue_to_composer("draft")) == "restored"
    assert calls == [
        ("follow:command", "later"),
        ("follow:keybinding", "inline"),
        ("steer", "steer"),
        ("debug", parse("debug")),
        ("dispatch", parse("dispatch")),
        ("result", ("outcome", 10.0)),
        ("abort", ""),
        ("restore", "draft"),
    ]


async def _async_none() -> None:
    return None
