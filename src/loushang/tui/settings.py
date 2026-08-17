from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from loushang.tui.cell_width import truncate_to_width
from loushang.tui.core import (
    CursorDeclaration,
    RenderConstraints,
    RenderLine,
    RenderResult,
)
from loushang.tui.input import InputIntent
from loushang.tui.theme import ThemeResolver
from loushang.tui.ui_parts import (
    SearchableList,
    SearchableListItem,
    SearchableListSelect,
)

__all__ = [
    "SETTINGS_PAGE_THEME",
    "SETTINGS_VALUE_COLUMN",
    "ConfigRow",
    "SettingsListPage",
    "SettingsRowSelect",
    "as_bool",
    "boolean_setting_intent",
    "bool_text",
    "config_items",
    "is_space_event",
    "is_tab_fallback_key",
    "next_bool_value",
    "row_for_key",
    "settings_header",
]


@dataclass(frozen=True, slots=True)
class ConfigRow:
    id: str
    label: str
    value: str
    description: str = ""
    disabled: bool = False


SETTINGS_VALUE_COLUMN = 42

SETTINGS_PAGE_THEME = ThemeResolver(
    defaults={
        "widget.tabs.tab": {"color": "white"},
        "widget.tabs.selected": {"bold": True, "color": "green"},
        "widget.tabs.level0.selected_header_focus": {"bold": True, "color": "cyan"},
        "widget.tabs.level0.selected_content_focus": {"bold": True, "color": "green"},
        "widget.tabs.level1.selected_header_focus": {"bold": True, "color": "magenta"},
        "widget.tabs.level1.selected_content_focus": {"bold": True, "color": "yellow"},
        "widget.searchableList.search": {"color": "white"},
        "widget.searchableList.placeholder": {"color": "bright_black"},
        "widget.searchableList.item": {"color": "white"},
        "widget.searchableList.focus": {"bold": True, "color": "cyan"},
        "widget.searchableList.disabled": {"dim": True},
        "widget.searchableList.description": {"color": "bright_black"},
        "widget.searchableList.empty": {"color": "bright_black"},
        "widget.searchableList.overflow": {"color": "bright_black"},
    }
)


def config_items(rows: tuple[ConfigRow, ...]) -> tuple[SearchableListItem, ...]:
    return tuple(
        SearchableListItem(row.id, row.label, row.value, row.description, disabled=row.disabled)
        for row in rows
    )


def row_for_key(rows: tuple[ConfigRow, ...], key: str) -> ConfigRow | None:
    for row in rows:
        if row.id == key:
            return row
    return None


def settings_header(width: int) -> str:
    value_column = max(8, min(SETTINGS_VALUE_COLUMN, max(8, width - 8)))
    return truncate_to_width(f"{'Setting':<{value_column}}Value", max_width=width, ellipsis="")


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def as_bool(value: str) -> bool | None:
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def next_bool_value(value: str) -> str:
    current = as_bool(value)
    if current is None:
        return value
    return bool_text(not current)


def is_space_event(event: object) -> bool:
    return (
        getattr(event, "kind", "") == "key"
        and getattr(event, "key", "") == "space"
    ) or (
        getattr(event, "kind", "") == "text"
        and getattr(event, "text", "") == " "
    )


def is_tab_fallback_key(event: object) -> bool:
    return getattr(event, "kind", "") == "key" and getattr(event, "key", "") in {"left", "right", "home", "end"}


SettingsRowSelect = Callable[[ConfigRow], object | None]


def boolean_setting_intent(row: ConfigRow) -> InputIntent | None:
    if row.disabled:
        return None
    return InputIntent(kind="setting", text=row.id, note=next_bool_value(row.value))


@dataclass(slots=True)
class SettingsListPage:
    """Searchable settings rows with the shared table layout and input contract."""

    rows: tuple[ConfigRow, ...]
    focused: bool = False
    placeholder: str = "Search settings..."
    empty_text: str = "No matching settings"
    on_select: SettingsRowSelect | None = boolean_setting_intent
    settings: SearchableList = field(init=False)

    def __post_init__(self) -> None:
        # Pages are focused by their containing surface after assembly.  Keeping
        # construction unfocused preserves the existing settings-page contract.
        self.settings = self._make_list(focused=False)

    def focus(self) -> None:
        self.focused = True
        self.settings.focus()

    def blur(self) -> None:
        self.focused = False
        self.settings.blur()

    def editor_input_target(self) -> object | None:
        return self.settings.editor_input_target()

    def set_rows(self, rows: tuple[ConfigRow, ...], *, preserve_active_key: str = "") -> None:
        self.rows = rows
        self.settings.set_items(config_items(rows), preserve_active_key=preserve_active_key)

    def handle_input(self, event: object) -> object:
        result = self.settings.handle_input(event)
        if isinstance(result, SearchableListSelect):
            return self._select(result.key)
        if result is not None:
            return result
        if self.settings.focus_region == "list" and is_space_event(event):
            item = self.settings.active_item
            if item is not None:
                return self._select(item.key)
        if is_tab_fallback_key(event):
            return True
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if constraints.max_height <= 0:
            return RenderResult.from_lines([], constraints=constraints)
        if constraints.max_height <= 4:
            return self.settings.render(constraints)
        result = self.settings.render(
            RenderConstraints(width=constraints.width, max_height=max(1, constraints.max_height - 2))
        )
        header = RenderLine(settings_header(constraints.width))
        rows = [*result.lines[:3], RenderLine(""), header, *result.lines[3:]]
        cursor = result.cursor
        if cursor is not None and cursor.row >= 3:
            cursor = CursorDeclaration(row=cursor.row + 2, column=cursor.column)
        return RenderResult.from_lines(rows[: constraints.max_height], constraints=constraints, cursor=cursor)

    def _make_list(self, *, focused: bool) -> SearchableList:
        return SearchableList(
            config_items(self.rows),
            placeholder=self.placeholder,
            empty_text=self.empty_text,
            focused=focused,
            search_box=True,
            detail_column=SETTINGS_VALUE_COLUMN,
            theme=SETTINGS_PAGE_THEME,
        )

    def _select(self, key: str) -> object | None:
        row = row_for_key(self.rows, key)
        if row is None or row.disabled or self.on_select is None:
            return None
        return self.on_select(row)
