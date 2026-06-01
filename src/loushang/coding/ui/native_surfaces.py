from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Literal, Protocol

from loushang.coding.commands.catalog import CodingCommandCatalog
from loushang.coding.ui.command_list import (
    coding_command_palette,
    format_coding_commands,
)
from loushang.coding.ui.hotkeys import format_hotkeys
from loushang.coding.ui.intent import (
    CommandSelectIntent,
    CommandsIntent,
    HotkeysIntent,
    ModelSelectIntent,
    ModelsIntent,
    SettingsIntent,
    StatusIntent,
    StatuslineIntent,
    TerminalDiagnosticsIntent,
    parse_prompt_intent,
)
from loushang.coding.ui.model import (
    current_model_first,
    get_session_model_selection,
    iter_scoped_model_selections,
    model_label_from_selection,
)
from loushang.coding.ui.model_list import (
    ModelChoice,
    available_model_choices,
    current_model_choice_value,
    format_available_models,
    model_detail_descriptions_by_label,
    select_available_model,
)
from loushang.coding.ui.native_app import NativeCodingTuiApp
from loushang.coding.ui.status_provider import CodingTuiStatusProvider
from loushang.runtime.commands import CommandDef, CommandKind
from loushang.tui import (
    ApprovalSurface,
    CommandPalette,
    CommandSurface,
    FocusableMixin,
    InfoPanel,
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SelectionSurface,
    SelectItem,
    Surface,
    SurfaceHandle,
    apply_theme_style,
)
from loushang.tui.cell_width import truncate_to_width, wrap_cells
from loushang.tui.surfaces import SettingsSurface

NativeSurfacePurpose = Literal["info", "model", "command", "settings", "dialog", "approval"]
NativeSurfacePresentation = Literal["bottom", "bottom-exclusive"]
SurfaceEventKind = Literal["surface_submit", "surface_close"]
SurfaceEventSource = Literal["model", "command", "settings", "dialog", "approval"]
MODEL_SELECTOR_SELECTED_STYLE = {"color": 33, "bold": True}


class NativeCommandCatalog(Protocol):
    def lookup(self, text: str) -> CommandDef | None: ...

    def commands(self) -> tuple[CommandDef, ...]: ...


@dataclass(slots=True)
class NativeSurfaceView(FocusableMixin):
    title: str
    purpose: NativeSurfacePurpose
    content: Any
    footer: str = "Enter to select - Esc to close"
    subtitle: str = ""
    presentation: NativeSurfacePresentation = "bottom"
    _last_content_start_row: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        FocusableMixin.__init__(self)

    @property
    def exclusive_bottom(self) -> bool:
        return self.presentation == "bottom-exclusive"

    def handle_input(self, event: InputEvent) -> InputIntent | None:
        if event.kind == "key" and event.key in {"escape", "esc"}:
            return InputIntent(kind="surface_close")
        if self.purpose == "info":
            if event.kind == "key" and event.key in {"enter", "space"}:
                return InputIntent(kind="surface_close")
            return None
        handler = getattr(self.content, "handle_input", None)
        if callable(handler):
            return handler(self._translate_content_input_event(event))
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        width = constraints.width
        lines = [truncate_to_width(self.title, max_width=width)]
        if self.subtitle:
            lines.append(truncate_to_width(self.subtitle, max_width=width))
        lines.append("")
        reserved_footer_lines = 2 if self.footer else 0
        body_constraints = RenderConstraints(
            width=width,
            max_height=max(1, constraints.max_height - len(lines) - reserved_footer_lines),
        )
        if isinstance(self.content, InfoPanel):
            for raw_line in self.content.text.splitlines():
                lines.extend(wrap_cells(raw_line, width=width) or [""])
        else:
            self._last_content_start_row = len(lines)
            result = self.content.render(body_constraints)
            lines.extend(line.text for line in result.lines)
        if self.footer and len(lines) < constraints.max_height:
            lines.append("")
            lines.append(truncate_to_width(self.footer, max_width=width))
        return RenderResult.from_lines([RenderLine(line) for line in lines[: constraints.max_height]], constraints=constraints)

    def _translate_content_input_event(self, event: InputEvent) -> InputEvent:
        if event.kind != "mouse" or event.mouse_row is None:
            return event
        return replace(event, mouse_row=event.mouse_row - self._last_content_start_row)


@dataclass(frozen=True, slots=True)
class SurfaceEvent:
    kind: SurfaceEventKind
    source: SurfaceEventSource | None = None
    payload: Any = None


@dataclass(slots=True)
class ModelSelectorSurface:
    all_items: tuple[SelectItem, ...]
    scoped_items: tuple[SelectItem, ...] = ()
    selected_value: str | None = None
    max_visible: int = 10
    _scope: Literal["all", "scoped"] = field(default="all", init=False)
    _surface: SelectionSurface = field(init=False, repr=False)
    _filter_text: str = field(default="", init=False, repr=False)
    _pending_ordinal: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        if self.scoped_items:
            self._scope = "scoped"
        self._rebuild_surface()

    def focus(self) -> None:
        self._surface.focus()

    def blur(self) -> None:
        self._surface.blur()

    def handle_input(self, event: InputEvent) -> InputIntent | None:
        if event.kind == "text":
            consumed, quick_select = self._handle_ordinal_text(event.text)
            if consumed:
                return quick_select
        if event.kind == "key" and event.key == "enter" and self._pending_ordinal:
            return self._select_pending_ordinal()
        if event.kind == "key" and event.key == "tab" and self.scoped_items:
            self._set_scope("all" if self._scope == "scoped" else "scoped")
            return None
        if event.kind == "key" and event.key == "right" and self.scoped_items:
            self._set_scope("all")
            return None
        if event.kind == "key" and event.key == "left" and self.scoped_items:
            self._set_scope("scoped")
            return None
        if event.kind != "text":
            self._pending_ordinal = ""
        intent = self._surface.handle_input(event)
        self._filter_text = self._surface.filter_text
        return intent

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if not self.scoped_items:
            return self._surface.render(constraints)
        header = [RenderLine(self._scope_line()), RenderLine("")]
        body_height = constraints.max_height - len(header)
        if body_height <= 0:
            return RenderResult.from_lines(header[: constraints.max_height], constraints=constraints)
        body = self._surface.render(
            RenderConstraints(
                width=constraints.width,
                max_height=body_height,
                visible_height=constraints.visible_height,
            )
        )
        cursor = replace(body.cursor, row=body.cursor.row + len(header)) if body.cursor is not None else None
        return RenderResult.from_lines([*header, *body.lines], constraints=constraints, cursor=cursor)

    def _rebuild_surface(self) -> None:
        items = self.scoped_items if self._scope == "scoped" else self.all_items
        selected_index = _selected_model_item_index(items, self.selected_value)
        self._surface = SelectionSurface(
            items,
            max_visible=self.max_visible,
            select_kind="select",
            selected_index=selected_index,
            empty_text="No matching models",
            show_scroll_info=False,
            selected_style=MODEL_SELECTOR_SELECTED_STYLE,
            enable_search=True,
            show_search_when_empty=False,
            filter_mode="contains",
        )
        if self._filter_text:
            self._surface.set_filter(self._filter_text)

    def _set_scope(self, scope: Literal["all", "scoped"]) -> None:
        if not self.scoped_items:
            return
        self._pending_ordinal = ""
        self._filter_text = self._surface.filter_text
        self._scope = scope
        self._rebuild_surface()

    def _scope_line(self) -> str:
        if self._scope == "scoped":
            scoped = apply_theme_style("scoped", MODEL_SELECTOR_SELECTED_STYLE)
            return f"Scope: {scoped} | all"
        all_models = apply_theme_style("all", MODEL_SELECTOR_SELECTED_STYLE)
        return f"Scope: {all_models} | scoped"

    def _handle_ordinal_text(self, text: str) -> tuple[bool, InputIntent | None]:
        if self._surface.filter_text or not text or any(digit not in "0123456789" for digit in text):
            self._pending_ordinal = ""
            return False, None
        consumed = False
        for digit in text:
            digit_consumed, intent = self._handle_ordinal_digit(digit)
            if not digit_consumed:
                return consumed, None
            consumed = True
            if intent is not None:
                return True, intent
        return consumed, None

    def _handle_ordinal_digit(self, digit: str) -> tuple[bool, InputIntent | None]:
        items = self._current_items()
        if not items:
            self._pending_ordinal = ""
            return False, None
        if not self._pending_ordinal and digit == "0":
            intent = self._select_ordinal(10)
            return intent is not None, intent

        candidate = f"{self._pending_ordinal}{digit}"
        if not self._ordinal_is_possible(candidate, len(items)):
            consumed = bool(self._pending_ordinal)
            self._pending_ordinal = ""
            return consumed, None

        ordinal = int(candidate)
        if (
            1 <= ordinal <= len(items)
            and not self._has_longer_ordinal_match(candidate, len(items))
        ):
            self._pending_ordinal = ""
            return True, self._select_ordinal(ordinal)

        self._pending_ordinal = candidate
        return True, None

    def _select_pending_ordinal(self) -> InputIntent | None:
        if not self._pending_ordinal:
            return None
        pending = self._pending_ordinal
        self._pending_ordinal = ""
        if not self._ordinal_is_possible(pending, len(self._current_items())):
            return None
        return self._select_ordinal(int(pending))

    def _select_ordinal(self, ordinal: int) -> InputIntent | None:
        index = ordinal - 1
        items = self._current_items()
        if index < 0 or index >= len(items):
            return None
        return InputIntent(kind="select", text=items[index].selected_value)

    def _current_items(self) -> tuple[SelectItem, ...]:
        return self.scoped_items if self._scope == "scoped" else self.all_items

    @staticmethod
    def _ordinal_is_possible(prefix: str, item_count: int) -> bool:
        if not prefix:
            return False
        ordinal = int(prefix)
        return 1 <= ordinal <= item_count or ModelSelectorSurface._has_longer_ordinal_match(prefix, item_count)

    @staticmethod
    def _has_longer_ordinal_match(prefix: str, item_count: int) -> bool:
        if not prefix or prefix.startswith("0"):
            return False
        prefix_length = len(prefix)
        max_length = len(str(item_count))
        for length in range(prefix_length + 1, max_length + 1):
            lower = int(f"{prefix}{'0' * (length - prefix_length)}")
            if lower <= item_count:
                return True
        return False


@dataclass(slots=True)
class NativeSurfaceManager:
    app: NativeCodingTuiApp
    session: Any
    status_provider: CodingTuiStatusProvider
    on_approval: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    set_statusline_visible: Callable[[bool | None], str] | None = None
    command_catalog: NativeCommandCatalog | None = None
    _handlers: dict[SurfaceEventSource, Callable[[Any], Awaitable[None]]] = field(init=False, repr=False)
    _active_overlay_view: NativeSurfaceView | None = None
    _active_overlay_handle: SurfaceHandle | None = None

    def __post_init__(self) -> None:
        self._handlers = {
            "model": self._handle_model_submit,
            "command": self._handle_command_submit,
            "settings": self._handle_settings_submit,
            "dialog": self._handle_dialog_submit,
            "approval": self._handle_approval_submit,
        }
        if self.command_catalog is None:
            self.command_catalog = CodingCommandCatalog(session_commands=_session_commands_provider(self.session))

    def is_local_command(self, text: str) -> bool:
        return self._lookup_local_command(text) is not None

    async def handle_text(self, text: str) -> int | None:
        command = self._lookup_local_command(text)
        if command is None:
            return None
        intent = parse_prompt_intent(text)
        if command.name == "model" and isinstance(intent, ModelSelectIntent):
            await self._handle_model_intent(intent)
        elif command.name == "models" and isinstance(intent, ModelsIntent):
            self._open_info("Models", await format_available_models(self.session, query=intent.query))
        elif command.name == "command" and isinstance(intent, CommandSelectIntent):
            await self._handle_command_intent(intent)
        elif command.name == "commands" and isinstance(intent, CommandsIntent):
            self._open_info(
                "Commands",
                await format_coding_commands(
                    self.session,
                    query=intent.query,
                    command_catalog=self._list_command_catalog(),
                ),
            )
        elif command.name == "status" and isinstance(intent, StatusIntent):
            self._open_info("Status", self.status_provider.render())
        elif command.name == "terminal" and isinstance(intent, TerminalDiagnosticsIntent):
            self._open_terminal_diagnostics()
        elif command.name == "hotkeys" and isinstance(intent, HotkeysIntent):
            self._open_info("Hotkeys", format_hotkeys())
        elif command.name == "settings" and isinstance(intent, SettingsIntent):
            self._open_settings()
        elif command.name == "statusline" and isinstance(intent, StatuslineIntent):
            setter = self.set_statusline_visible or self.status_provider.set_visible
            message = setter(intent.enabled)
            if intent.enabled is not None:
                self.app.set_statusline_visible(intent.enabled)
            else:
                self.app.set_statusline_visible(self.status_provider.is_visible())
            self.app.set_status(message)
        return None

    def _lookup_local_command(self, text: str) -> CommandDef | None:
        if self.command_catalog is None:
            return None
        command = self.command_catalog.lookup(text)
        if command is None or command.kind is not CommandKind.LOCAL_UI:
            return None
        return command

    def _list_command_catalog(self) -> CodingCommandCatalog | None:
        return self.command_catalog if isinstance(self.command_catalog, CodingCommandCatalog) else None

    async def handle_surface_intent(self, intent: InputIntent) -> int | None:
        surface = self._current_surface()
        if not isinstance(surface, NativeSurfaceView):
            return None

        event = self._normalize_surface_intent(intent, surface)
        if event is None:
            return None
        if event.kind == "surface_close":
            self.close_surface()
            return None
        handler = self._handlers.get(event.source)
        if handler is None:
            return None
        await handler(event.payload)
        return None

    def _normalize_surface_intent(self, intent: InputIntent, surface: NativeSurfaceView) -> SurfaceEvent | None:
        if intent.kind in {"surface_close", "dialog_cancel"}:
            return SurfaceEvent(kind="surface_close", source=None)
        if surface.purpose == "model" and intent.kind in {"command", "select"}:
            return SurfaceEvent(kind="surface_submit", source="model", payload=intent.text)
        if surface.purpose == "command" and intent.kind in {"command", "select"}:
            return SurfaceEvent(kind="surface_submit", source="command", payload=intent.text)
        if surface.purpose == "settings" and intent.kind == "setting":
            return SurfaceEvent(
                kind="surface_submit",
                source="settings",
                payload={"id": intent.text, "value": intent.note},
            )
        if surface.purpose == "dialog" and intent.kind == "dialog_confirm":
            return SurfaceEvent(kind="surface_submit", source="dialog")
        if surface.purpose == "approval" and intent.kind in {"approve", "reject"}:
            action_id = getattr(surface.content, "action_id", None)
            action = getattr(surface.content, "action", None)
            return SurfaceEvent(
                kind="surface_submit",
                source="approval",
                payload={
                    "action_id": action_id,
                    "action": action,
                    "approved": intent.kind == "approve",
                    "raw_note": intent.note or action_id,
                },
            )
        return None

    async def _handle_model_submit(self, payload: str) -> None:
        try:
            message = await select_available_model(self.session, query=payload)
        except Exception as error:
            self.app.set_status(_recoverable_surface_error(error))
            return
        self.close_surface()
        await self._refresh_model_label()
        self.app.set_status(message)

    async def _handle_command_submit(self, payload: str) -> None:
        command = payload.strip()
        if command:
            self.app.composer.set_text(command + (" " if " " not in command else ""))
            self.app.set_status(f"Command selected: {command}")
        self.close_surface()

    async def _handle_settings_submit(self, payload: dict[str, str]) -> None:
        updated = self.status_provider.settings_list().toggle(payload["id"])
        self.close_surface()
        message = self.status_provider.apply_settings(updated)
        self.app.set_statusline_visible(self.status_provider.is_visible())
        self.app.set_status(message)

    async def _handle_dialog_submit(self, _payload: Any | None = None) -> None:
        self.close_surface()

    async def _handle_approval_submit(self, payload: dict[str, Any] | None = None) -> None:
        self.close_surface()
        if payload is not None and payload.get("approved"):
            self.app.set_status(f"Action confirmed: {payload.get('action')}")
        elif payload is not None:
            self.app.set_status("Action rejected")
        if self.on_approval is not None:
            await self.on_approval(payload or {})

    def close_surface(self) -> None:
        if self._active_overlay_handle is not None:
            self._active_overlay_handle.close("closed")
        self._active_overlay_handle = None
        self._active_overlay_view = None
        self.app.active_surface = None

    async def _handle_model_intent(self, intent: ModelSelectIntent) -> None:
        if intent.query.strip():
            try:
                message = await select_available_model(self.session, query=intent.query)
            except Exception as error:
                self.app.set_status(_recoverable_surface_error(error))
            else:
                await self._refresh_model_label()
                self.app.set_status(message)
            return
        await self._open_model_selector()

    async def _handle_command_intent(self, intent: CommandSelectIntent) -> None:
        if intent.query.strip():
            command = intent.query if intent.query.startswith("/") else f"/{intent.query}"
            self.app.composer.set_text(command + " ")
            self.app.set_status(f"Command selected: {command}")
            return
        self._open_palette(
            "Commands",
            await coding_command_palette(self.session, title="Commands", command_catalog=self._list_command_catalog()),
            purpose="command",
        )

    def _open_palette(self, title: str, palette: CommandPalette, *, purpose: Literal["model", "command"]) -> None:
        surface = CommandSurface(_palette_items(palette), max_visible=8)
        self._open_surface(NativeSurfaceView(title=title, purpose=purpose, content=surface))

    async def _open_model_selector(self) -> None:
        current_label = model_label_from_selection(await get_session_model_selection(self.session))
        choices = await available_model_choices(self.session)
        current_value = await current_model_choice_value(self.session, choices=choices)
        scoped_selections = await iter_scoped_model_selections(self.session)
        descriptions = await model_detail_descriptions_by_label(self.session)
        surface = ModelSelectorSurface(
            all_items=tuple(_model_choice_selector_items(choices, current_value=current_value)),
            scoped_items=tuple(_model_selector_items(scoped_selections, current_label=current_label, descriptions=descriptions)),
            selected_value=current_value or current_label,
            max_visible=10,
        )
        self._open_surface(
            NativeSurfaceView(
                title="Select Model",
                subtitle="Access legacy models by running loushang --model <provider/model>.",
                purpose="model",
                content=surface,
                footer="  Press number or enter to confirm or esc to go back",
                presentation="bottom-exclusive",
            )
        )

    def _open_info(self, title: str, text: str) -> None:
        self._open_surface(
            NativeSurfaceView(
                title=title,
                purpose="info",
                content=InfoPanel.from_text(title=title, text=text, footer=""),
                footer="Enter/Esc to close",
            )
        )

    def _open_terminal_diagnostics(self) -> None:
        provider = self.app.terminal_diagnostics_provider
        text = provider() if provider is not None else "Terminal diagnostics are not available outside an active TUI session."
        self._open_info("Terminal", text)

    def _open_settings(self) -> None:
        surface = SettingsSurface(list(self.status_provider.settings_list().items), max_visible=8, enable_search=True)
        self._open_surface(
            NativeSurfaceView(
                title="Settings",
                purpose="settings",
                content=surface,
                footer="",
                presentation="bottom-exclusive",
            )
        )

    def open_approval(self, *, action: str, risk: str = "", action_id: str | None = None) -> None:
        self._open_surface(
            NativeSurfaceView(
                title="Approval",
                purpose="approval",
                content=ApprovalSurface(action=action, risk=risk, action_id=action_id),
                footer="",
                presentation="bottom-exclusive",
            )
        )

    def _open_surface(self, view: NativeSurfaceView) -> None:
        self.close_surface()
        surface_host = self.app.surface_host
        if surface_host is None or view.exclusive_bottom:
            self.app.active_surface = view
            return
        self.app.active_surface = None
        self._active_overlay_view = view
        self._active_overlay_handle = surface_host.open_surface(
            Surface(
                renderable=view,
                focus_target=view,
                presentation="overlay",
                anchor="bottom-left",
                width="100%",
                max_height="80%",
            )
        )

    def _current_surface(self) -> NativeSurfaceView | Any | None:
        return self._active_overlay_view if self._active_overlay_view is not None else self.app.active_surface

    async def _refresh_model_label(self) -> None:
        label = model_label_from_selection(await get_session_model_selection(self.session))
        if label is not None:
            self.app.state.model_label = label


def _palette_items(palette: CommandPalette) -> list[SelectItem]:
    return [
        SelectItem(label=item.display_label(), value=item.value, description=item.description)
        for item in palette.items
    ]


def _model_selector_description(label: str, *, current_label: str | None, descriptions: dict[str, str]) -> str:
    if label == current_label:
        return "current"
    return descriptions.get(label, "")


def _model_selector_items(
    selections: list[Any],
    *,
    current_label: str | None,
    descriptions: dict[str, str],
) -> list[SelectItem]:
    labels = current_model_first(
        [
            label
            for selection in selections
            if (label := model_label_from_selection(selection)) is not None
        ],
        current_label=current_label,
        label_of=lambda label: label,
    )
    ordinal_width = max(2, len(f"{len(labels)}."))
    items: list[SelectItem] = []
    for index, label in enumerate(labels, start=1):
        ordinal = f"{index}.".ljust(ordinal_width)
        items.append(
            SelectItem(
                label=f"{ordinal} {label}",
                value=label,
                description=_model_selector_description(label, current_label=current_label, descriptions=descriptions),
            )
        )
    return items


def _model_choice_selector_items(
    choices: list[ModelChoice],
    *,
    current_value: str | None,
) -> list[SelectItem]:
    ordinal_width = max(2, len(f"{len(choices)}."))
    items: list[SelectItem] = []
    for index, choice in enumerate(choices, start=1):
        ordinal = f"{index}.".ljust(ordinal_width)
        items.append(
            SelectItem(
                label=f"{ordinal} {choice.label}",
                value=choice.value,
                description=_model_choice_selector_description(choice, current_value=current_value),
            )
        )
    return items


def _model_choice_selector_description(choice: ModelChoice, *, current_value: str | None) -> str:
    parts: list[str] = []
    if choice.value == current_value:
        parts.append("current")
    if choice.endpoint_id:
        parts.append(f"endpoint: {choice.endpoint_id}")
    if choice.description:
        parts.append(choice.description)
    return " - ".join(parts)


def _selected_model_item_index(items: tuple[SelectItem, ...], selected_value: str | None) -> int:
    if selected_value is None:
        return 0
    for index, item in enumerate(items):
        if item.selected_value == selected_value:
            return index
    return 0


def _recoverable_surface_error(error: Exception) -> str:
    message = str(error).strip() or error.__class__.__name__
    return f"Error: {message}"


def _session_commands_provider(session: Any) -> Callable[[], Any] | None:
    getter = getattr(session, "list_commands", None)
    if not callable(getter):
        return None
    return getter


__all__ = ["NativeSurfaceManager", "NativeSurfaceView"]
