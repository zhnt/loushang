from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from loushang.tui.cell_width import (
    autowrap_safe_width,
    truncate_to_width,
    visible_width,
    wrap_cells,
)
from loushang.tui.compat import SettingItem
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.fuzzy import fuzzy_match
from loushang.tui.input import InputEvent, InputIntent, InputIntentKind
from loushang.tui.theme import ThemeResolver, ThemeStyle, apply_theme_style
from loushang.tui.ui_parts.text_input import TextInput

DEFAULT_PRIMARY_COLUMN_WIDTH = 32
PRIMARY_COLUMN_GAP = 2
MIN_DESCRIPTION_WIDTH = 10
DEFAULT_SELECTED_STYLE: ThemeStyle = {"color": 33, "bold": True}
TruncateTextHandler = Callable[[str, int, str], str]


@dataclass(frozen=True, slots=True)
class SelectItem:
    label: str
    value: str = ""
    description: str = ""

    @property
    def selected_value(self) -> str:
        return self.value or self.label


SelectionChangeHandler = Callable[[SelectItem | None], None]


@dataclass(slots=True)
class SelectionSurface:
    items: list[SelectItem] | tuple[SelectItem, ...]
    max_visible: int = 5
    select_kind: InputIntentKind = "select"
    empty_text: str = "No matching items"
    selected_index: int = 0
    focused: bool = False
    show_scroll_info: bool = True
    selected_style: ThemeStyle | None = None
    theme: ThemeResolver | None = None
    selected_theme_token: str = "selection.selected"
    enable_search: bool = False
    search_prompt: str = "Search: "
    show_search_when_empty: bool = True
    filter_mode: Literal["prefix", "contains", "fuzzy"] = "prefix"
    on_selection_change: SelectionChangeHandler | None = None
    primary_column_width: int | None = None
    min_description_width: int = MIN_DESCRIPTION_WIDTH
    truncate_text: TruncateTextHandler | None = None
    _filtered_items: list[SelectItem] = field(init=False)
    _filter_input: TextInput | None = field(default=None, init=False, repr=False)
    _last_visible_start: int = field(default=0, init=False, repr=False)
    _last_visible_count: int = field(default=0, init=False, repr=False)
    _last_search_line_count: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._filtered_items = list(self.items)
        self._filter_input = TextInput(prompt=self.search_prompt) if self.enable_search else None
        self.selected_index = _clamp_index(self.selected_index, self._filtered_items)

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def set_filter(self, query: str) -> None:
        if self._filter_input is not None:
            self._filter_input.set_text(query)
        self._apply_filter(query)

    @property
    def filter_text(self) -> str:
        if self._filter_input is None:
            return ""
        return self._filter_input.value

    def handle_input(self, event: InputEvent) -> InputIntent | None:
        if self.enable_search and event.kind == "text":
            filter_input = self._ensure_filter_input()
            filter_input.handle_input(event)
            self._apply_filter(filter_input.value)
            return None
        if event.kind == "mouse":
            self._handle_mouse(event)
            return None
        if event.kind != "key":
            return None
        if self._search_accepts_editing_keys() and _handle_text_input_key(self._filter_input, event.key):
            self._apply_filter(self._filter_input.value if self._filter_input is not None else "")
            return None
        if event.key == "up":
            self._move(-1)
            return None
        if event.key == "down":
            self._move(1)
            return None
        if event.key == "pageUp":
            self._move(-max(1, self.max_visible))
            return None
        if event.key == "pageDown":
            self._move(max(1, self.max_visible))
            return None
        if event.key == "home":
            self._move_to_edge("first")
            return None
        if event.key == "end":
            self._move_to_edge("last")
            return None
        if event.key == "enter":
            selected = self.selected_item()
            if selected is None:
                return None
            return InputIntent(kind=self.select_kind, text=selected.selected_value)
        if event.key in {"esc", "escape"}:
            return InputIntent(kind="surface_close")
        return None

    def selected_item(self) -> SelectItem | None:
        if not self._filtered_items:
            return None
        return self._filtered_items[self.selected_index]

    def render(self, constraints: RenderConstraints) -> RenderResult:
        search_lines: list[RenderLine] = []
        cursor = None
        if self._search_visible():
            filter_input = self._ensure_filter_input()
            search_result = filter_input.render(
                RenderConstraints(
                    width=constraints.width,
                    max_height=1,
                    visible_height=constraints.visible_height,
                )
            )
            search_lines.extend(search_result.lines)
            cursor = search_result.cursor
            if len(search_lines) < constraints.max_height:
                search_lines.append(RenderLine(""))
        self._last_search_line_count = len(search_lines)
        item_height = constraints.max_height - len(search_lines)
        if item_height <= 0:
            self._last_visible_start = 0
            self._last_visible_count = 0
            return RenderResult.from_lines(search_lines[: constraints.max_height], constraints=constraints, cursor=cursor)
        item_result = self._render_items(
            RenderConstraints(
                width=constraints.width,
                max_height=item_height,
                visible_height=constraints.visible_height,
            )
        )
        return RenderResult.from_lines([*search_lines, *item_result.lines], constraints=constraints, cursor=cursor)

    def _render_items(self, constraints: RenderConstraints) -> RenderResult:
        if not self._filtered_items:
            self._last_visible_start = 0
            self._last_visible_count = 0
            line = truncate_to_width(self.empty_text, max_width=autowrap_safe_width(constraints.width))
            return RenderResult.from_lines([RenderLine(line)], constraints=constraints)

        visible_budget = max(1, min(self.max_visible, constraints.max_height))
        include_scroll = self.show_scroll_info and len(self._filtered_items) > visible_budget and constraints.max_height > visible_budget
        item_budget = visible_budget if include_scroll else min(visible_budget, constraints.max_height)
        start = _scroll_start(self.selected_index, len(self._filtered_items), item_budget)
        end = min(start + item_budget, len(self._filtered_items))
        self._last_visible_start = start
        self._last_visible_count = max(0, end - start)

        lines = [
            RenderLine(
                _render_select_item(
                    self._filtered_items[index],
                    selected=index == self.selected_index,
                    width=constraints.width,
                    primary_column_width=self.primary_column_width or _select_primary_column_width(self._filtered_items),
                    min_description_width=self.min_description_width,
                    truncate_text=self.truncate_text,
                    selected_style=self._selected_style(),
                )
            )
            for index in range(start, end)
        ]
        if include_scroll and (start > 0 or end < len(self._filtered_items)):
            info = f"  ({self.selected_index + 1}/{len(self._filtered_items)})"
            lines.append(RenderLine(truncate_to_width(info, max_width=autowrap_safe_width(constraints.width))))
        return RenderResult.from_lines(lines, constraints=constraints)

    def _move(self, delta: int) -> None:
        if not self._filtered_items:
            return
        previous = self.selected_item()
        self.selected_index = (self.selected_index + delta) % len(self._filtered_items)
        if self.selected_item() != previous:
            self._notify_selection_change()

    def _move_to_edge(self, edge: Literal["first", "last"]) -> None:
        if not self._filtered_items:
            return
        previous = self.selected_item()
        self.selected_index = 0 if edge == "first" else len(self._filtered_items) - 1
        if self.selected_item() != previous:
            self._notify_selection_change()

    def _handle_mouse(self, event: InputEvent) -> None:
        if event.mouse_action != "press" or event.mouse_button not in {0, None}:
            return
        if not self._filtered_items or event.mouse_row is None:
            return
        item_row = event.mouse_row - self._last_search_line_count
        if item_row < 0 or item_row >= self._last_visible_count:
            return
        target_index = self._last_visible_start + item_row
        if 0 <= target_index < len(self._filtered_items):
            previous = self.selected_item()
            self.selected_index = target_index
            if self.selected_item() != previous:
                self._notify_selection_change()

    def _ensure_filter_input(self) -> TextInput:
        if self._filter_input is None:
            self._filter_input = TextInput(prompt=self.search_prompt)
        return self._filter_input

    def _search_visible(self) -> bool:
        if not self.enable_search:
            return False
        if self.show_search_when_empty:
            return True
        return bool(self._filter_input is not None and self._filter_input.value)

    def _search_accepts_editing_keys(self) -> bool:
        return self.enable_search and self._search_visible()

    def _apply_filter(self, query: str) -> None:
        normalized = query.lower().strip()
        if not normalized:
            previous = self.selected_item()
            self._filtered_items = list(self.items)
            self.selected_index = _clamp_index(0, self._filtered_items)
            if self.selected_item() != previous:
                self._notify_selection_change()
            return
        previous = self.selected_item()
        self._filtered_items = [
            item
            for item in self.items
            if _select_item_matches_filter(item, normalized, mode=self.filter_mode)
        ]
        self.selected_index = _clamp_index(0, self._filtered_items)
        if self.selected_item() != previous:
            self._notify_selection_change()

    def _selected_style(self) -> ThemeStyle | None:
        if self.selected_style is not None:
            return self.selected_style
        if self.theme is not None and self.selected_theme_token:
            resolved = self.theme.resolve(self.selected_theme_token)
            if resolved:
                return resolved
        return DEFAULT_SELECTED_STYLE

    def _notify_selection_change(self) -> None:
        if self.on_selection_change is not None:
            self.on_selection_change(self.selected_item())


class AutocompleteSurface(SelectionSurface):
    def __init__(self, items: list[SelectItem] | tuple[SelectItem, ...], *, max_visible: int = 5) -> None:
        super().__init__(items=items, max_visible=max_visible, select_kind="complete")


class CommandSurface(SelectionSurface):
    def __init__(
        self,
        items: list[SelectItem] | tuple[SelectItem, ...],
        *,
        query: str = "",
        max_visible: int = 5,
    ) -> None:
        super().__init__(
            items=items,
            max_visible=max_visible,
            select_kind="command",
            enable_search=True,
            show_search_when_empty=False,
            filter_mode="contains",
        )
        if query:
            self.set_filter(query)


class SettingsSurface(SelectionSurface):
    def __init__(
        self,
        items: list[SelectItem | SettingItem] | tuple[SelectItem | SettingItem, ...],
        *,
        max_visible: int = 8,
        enable_search: bool = False,
    ) -> None:
        self._settings_items = [item for item in items if isinstance(item, SettingItem)]
        self._search_enabled = enable_search
        self._search_input = TextInput(prompt="Search: ") if enable_search else None
        self._submenu_component: Any | None = None
        self._submenu_item_id: str | None = None
        self._submenu_item_index: int | None = None
        self._pending_submenu_intent: InputIntent | None = None
        if self._settings_items and len(self._settings_items) == len(items):
            super().__init__(items=[], max_visible=max_visible, select_kind="setting")
            self._filtered_items = []
            return
        super().__init__(items=[item for item in items if isinstance(item, SelectItem)], max_visible=max_visible, select_kind="setting")

    def set_filter(self, query: str) -> None:
        if self._settings_items:
            if self._search_input is not None:
                self._search_input.set_text(query)
            self.selected_index = 0
            return
        super().set_filter(query)

    def handle_input(self, event: InputEvent) -> InputIntent | None:
        if self._submenu_component is not None:
            return self._handle_submenu_input(event)
        if not self._settings_items:
            return super().handle_input(event)
        if event.kind == "text" and event.text == " " and not self._search_enabled:
            return self._activate_setting()
        if event.kind == "text" and self._search_enabled:
            if self._search_input is not None:
                self._search_input.insert_text(event.text)
            self.selected_index = 0
            return None
        if event.kind != "key":
            return None
        if self._search_enabled and _handle_text_input_key(self._search_input, event.key):
            self.selected_index = 0
            return None
        if event.key == "up":
            self._move_settings(-1)
            return None
        if event.key == "down":
            self._move_settings(1)
            return None
        if event.key == "pageUp":
            self._move_settings(-max(1, self.max_visible))
            return None
        if event.key == "pageDown":
            self._move_settings(max(1, self.max_visible))
            return None
        if event.key in {"enter", "space"} or event.text == " ":
            return self._activate_setting()
        if event.key in {"esc", "escape"}:
            return InputIntent(kind="surface_close")
        return None

    def selected_setting(self) -> SettingItem | None:
        items = self._display_settings()
        if not items:
            return None
        return items[self.selected_index]

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if self._submenu_component is not None:
            render = getattr(self._submenu_component, "render", None)
            if callable(render):
                return render(constraints)
        if not self._settings_items:
            return self._render_legacy_select_settings(constraints)
        target_width = autowrap_safe_width(constraints.width)
        rendered: list[str] = []
        cursor = None
        if self._search_enabled:
            search_input = self._search_input or TextInput(prompt="Search: ")
            search_result = search_input.render(
                RenderConstraints(
                    width=target_width,
                    max_height=1,
                    visible_height=constraints.visible_height,
                )
            )
            rendered.extend(line.text for line in search_result.lines)
            cursor = search_result.cursor
            rendered.append("")
        display_items = self._display_settings()
        if not display_items:
            rendered.append(truncate_to_width("  No matching settings", max_width=target_width, ellipsis=""))
            return RenderResult.from_lines(
                [RenderLine(line) for line in rendered[: constraints.max_height]],
                constraints=constraints,
                cursor=cursor,
            )
        self.selected_index = _clamp_setting_index(self.selected_index, display_items)
        item_budget = max(1, min(self.max_visible, constraints.max_height - len(rendered)))
        start = _scroll_start(self.selected_index, len(display_items), item_budget)
        end = min(start + item_budget, len(display_items))
        label_width = _settings_label_width(self._settings_items)
        for index in range(start, end):
            item = display_items[index]
            rendered.append(_render_setting_item(item, selected=index == self.selected_index, label_width=label_width, width=target_width))
        if start > 0 or end < len(display_items):
            rendered.append(truncate_to_width(f"  ({self.selected_index + 1}/{len(display_items)})", max_width=target_width, ellipsis=""))
        selected = display_items[self.selected_index]
        if selected.description and len(rendered) + 2 <= constraints.max_height:
            rendered.append("")
            description_budget = max(0, constraints.max_height - len(rendered))
            rendered.extend(_wrap_setting_description(selected.description, width=target_width)[:description_budget])
        if len(rendered) + 2 <= constraints.max_height:
            rendered.append("")
            rendered.append(truncate_to_width("  Enter/Space to change - Esc to cancel", max_width=target_width, ellipsis=""))
        return RenderResult.from_lines(
            [RenderLine(line) for line in rendered[: constraints.max_height]],
            constraints=constraints,
            cursor=cursor,
        )

    def _render_legacy_select_settings(self, constraints: RenderConstraints) -> RenderResult:
        if not self._filtered_items:
            line = truncate_to_width(self.empty_text, max_width=autowrap_safe_width(constraints.width))
            return RenderResult.from_lines([RenderLine(line)], constraints=constraints)
        visible_budget = max(1, min(self.max_visible, constraints.max_height))
        start = _scroll_start(self.selected_index, len(self._filtered_items), visible_budget)
        end = min(start + visible_budget, len(self._filtered_items))
        lines = [
            RenderLine(
                _render_legacy_settings_item(
                    self._filtered_items[index],
                    selected=index == self.selected_index,
                    width=constraints.width,
                )
            )
            for index in range(start, end)
        ]
        return RenderResult.from_lines(lines, constraints=constraints)

    def _display_settings(self) -> list[SettingItem]:
        search_query = self._search_input.value if self._search_input is not None else ""
        if not self._search_enabled or not search_query:
            return list(self._settings_items)
        query = search_query.lower()
        return [item for item in self._settings_items if _setting_item_matches_search(item, query)]

    def _move_settings(self, delta: int) -> None:
        items = self._display_settings()
        if not items:
            return
        self.selected_index = (self.selected_index + delta) % len(items)

    def _activate_setting(self) -> InputIntent | None:
        selected = self.selected_setting()
        if selected is None:
            return None
        if selected.submenu is not None:
            self._submenu_item_id = selected.id
            self._submenu_item_index = self.selected_index
            self._pending_submenu_intent = None
            self._submenu_component = selected.submenu(selected.current_value, self._complete_submenu_from_callback)
            return None
        if selected.values:
            try:
                current_index = selected.values.index(selected.current_value)
            except ValueError:
                current_index = -1
            new_value = selected.values[(current_index + 1) % len(selected.values)]
            self._settings_items = [
                replace(item, current_value=new_value) if item.id == selected.id else item
                for item in self._settings_items
            ]
            return InputIntent(kind="setting", text=selected.id, note=new_value)
        if selected.current_value:
            return InputIntent(kind="setting", text=selected.id, note=selected.current_value)
        return InputIntent(kind="setting", text=selected.id, note="true" if selected.enabled else "false")

    def _handle_submenu_input(self, event: InputEvent) -> InputIntent | None:
        component = self._submenu_component
        handle_input = getattr(component, "handle_input", None)
        result = handle_input(event) if callable(handle_input) else None
        pending = self._consume_pending_submenu_intent()
        if pending is not None:
            return pending
        intents = _normalize_submenu_result(result)
        for intent in intents:
            if intent.kind in {"select", "complete", "setting"}:
                selected_value = intent.note or intent.text
                return self._complete_submenu(selected_value)
            if intent.kind in {"surface_close", "dialog_cancel"}:
                self._close_submenu()
                return None
        return result if isinstance(result, InputIntent) else None

    def _complete_submenu_from_callback(self, selected_value: str | None = None) -> None:
        if selected_value is None:
            self._close_submenu()
            return
        self._pending_submenu_intent = self._complete_submenu(selected_value)

    def _consume_pending_submenu_intent(self) -> InputIntent | None:
        intent = self._pending_submenu_intent
        self._pending_submenu_intent = None
        return intent

    def _complete_submenu(self, selected_value: str) -> InputIntent | None:
        item_id = self._submenu_item_id
        if item_id is None:
            self._close_submenu()
            return None
        self._settings_items = [
            replace(item, current_value=selected_value) if item.id == item_id else item
            for item in self._settings_items
        ]
        self._close_submenu()
        return InputIntent(kind="setting", text=item_id, note=selected_value)

    def _close_submenu(self) -> None:
        self._submenu_component = None
        if self._submenu_item_index is not None:
            self.selected_index = self._submenu_item_index
        self._submenu_item_id = None
        self._submenu_item_index = None


@dataclass(slots=True)
class ApprovalSurface:
    action: str
    risk: str = ""
    action_id: str | None = None
    focused: bool = False

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def handle_input(self, event: InputEvent) -> InputIntent | None:
        if event.kind == "text":
            value = event.text.strip().lower()
        elif event.kind == "key":
            value = event.key.lower()
        else:
            return None
        if value == "y":
            return InputIntent(kind="approve", note=self.action_id or "")
        if value == "n" or value in {"esc", "escape"}:
            return InputIntent(kind="reject", note=self.action_id or "")
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        raw_lines = [self.action]
        if self.risk:
            raw_lines.append(self.risk)
        raw_lines.append("[y] approve  [n] reject")
        return _bounded_lines(raw_lines, constraints)


@dataclass(slots=True)
class DialogSurface:
    title: str
    message: str = ""
    focused: bool = False

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def handle_input(self, event: InputEvent) -> InputIntent | None:
        if event.kind != "key":
            return None
        if event.key == "enter":
            return InputIntent(kind="dialog_confirm")
        if event.key in {"esc", "escape"}:
            return InputIntent(kind="dialog_cancel")
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        raw_lines = [self.title]
        if self.message:
            raw_lines.append(self.message)
        raw_lines.append("[enter] confirm  [esc] cancel")
        return _bounded_lines(raw_lines, constraints)


def _render_select_item(
    item: SelectItem,
    *,
    selected: bool,
    width: int,
    primary_column_width: int | None = None,
    min_description_width: int = MIN_DESCRIPTION_WIDTH,
    truncate_text: TruncateTextHandler | None = None,
    selected_style: ThemeStyle | None = None,
) -> str:
    target_width = autowrap_safe_width(width)
    prefix = "> " if selected else "  "
    prefix_width = len(prefix)
    if item.description and target_width > prefix_width + 4:
        description = _normalize_single_line(item.description)
        effective_primary_width = max(1, min(primary_column_width or DEFAULT_PRIMARY_COLUMN_WIDTH, target_width - prefix_width - 4))
        max_primary_width = max(1, effective_primary_width - PRIMARY_COLUMN_GAP)
        label = _truncate_select_text(item.label or item.selected_value, max_primary_width, "", truncate_text)
        spacing = " " * max(1, effective_primary_width - visible_width(label))
        description_start = prefix_width + visible_width(label) + len(spacing)
        remaining_width = target_width - description_start - 2
        if remaining_width > min_description_width:
            line = truncate_to_width(
                prefix + label + spacing + _truncate_select_text(description, remaining_width, "", truncate_text),
                max_width=target_width,
                ellipsis="",
            )
            return _style_selected_line(line, selected=selected, selected_style=selected_style)
    line = truncate_to_width(prefix + item.label, max_width=target_width)
    return _style_selected_line(line, selected=selected, selected_style=selected_style)


def _truncate_select_text(
    text: str,
    max_width: int,
    ellipsis: str,
    truncate_text: TruncateTextHandler | None,
) -> str:
    if truncate_text is not None:
        return truncate_text(text, max_width, ellipsis)
    return truncate_to_width(text, max_width=max_width, ellipsis=ellipsis)


def _select_primary_column_width(items: list[SelectItem]) -> int:
    if not items:
        return DEFAULT_PRIMARY_COLUMN_WIDTH
    widest = max(visible_width(item.label or item.selected_value) + PRIMARY_COLUMN_GAP for item in items)
    return max(1, min(DEFAULT_PRIMARY_COLUMN_WIDTH, max(DEFAULT_PRIMARY_COLUMN_WIDTH, widest)))


def _normalize_single_line(text: str) -> str:
    return " ".join(text.split())


def _select_item_matches_filter(item: SelectItem, query: str, *, mode: Literal["prefix", "contains", "fuzzy"]) -> bool:
    haystacks = (
        item.label.lower(),
        item.selected_value.lower(),
        item.description.lower(),
    )
    if mode == "fuzzy":
        return _fuzzy_matches_any(query, haystacks)
    if mode == "contains":
        return any(query in haystack for haystack in haystacks)
    return any(haystack.startswith(query) for haystack in haystacks[:2])


def _setting_item_matches_search(item: SettingItem, query: str) -> bool:
    haystacks = (
        item.label.lower(),
        item.id.lower(),
        item.description.lower(),
        item.current_value.lower(),
    )
    return _fuzzy_matches_any(query, haystacks)


def _fuzzy_matches_any(query: str, haystacks: tuple[str, ...]) -> bool:
    tokens = tuple(token for token in query.split() if token)
    if not tokens:
        return True
    return all(
        any(fuzzy_match(token, haystack).matches for haystack in haystacks if haystack)
        for token in tokens
    )


def _wrap_setting_description(description: str, *, width: int) -> list[str]:
    body_width = max(1, width - 2)
    wrapped: list[str] = []
    for logical_line in description.splitlines():
        words = logical_line.split()
        if not words:
            wrapped.append("  ")
            continue
        current = ""
        for word in words:
            if visible_width(word) > body_width:
                if current:
                    wrapped.append(f"  {current}")
                    current = ""
                wrapped.extend(f"  {chunk}" for chunk in wrap_cells(word, width=body_width))
                continue
            candidate = word if not current else f"{current} {word}"
            if visible_width(candidate) <= body_width:
                current = candidate
                continue
            wrapped.append(f"  {current}")
            current = word
        if current:
            wrapped.append(f"  {current}")
    return wrapped or ["  "]


def _render_setting_item(item: SettingItem, *, selected: bool, label_width: int, width: int) -> str:
    prefix = "> " if selected else "  "
    label = item.label + (" " * max(0, label_width - visible_width(item.label)))
    value = item.current_value or ("on" if item.enabled else "off")
    line = truncate_to_width(f"{prefix}{label}  {value}", max_width=width, ellipsis="")
    return _style_selected_line(line, selected=selected, selected_style=DEFAULT_SELECTED_STYLE)


def _render_legacy_settings_item(item: SelectItem, *, selected: bool, width: int) -> str:
    prefix = "> " if selected else "  "
    suffix = f"  {_normalize_single_line(item.description)}" if item.description else ""
    line = truncate_to_width(f"{prefix}{item.label}{suffix}", max_width=autowrap_safe_width(width))
    return _style_selected_line(line, selected=selected, selected_style=DEFAULT_SELECTED_STYLE)


def _style_selected_line(line: str, *, selected: bool, selected_style: ThemeStyle | None) -> str:
    if not selected or selected_style is None:
        return line
    return apply_theme_style(line, selected_style)


def _settings_label_width(items: list[SettingItem]) -> int:
    if not items:
        return 1
    return min(30, max(visible_width(item.label) for item in items))


def _handle_text_input_key(text_input: TextInput | None, key: str) -> bool:
    if text_input is None:
        return False
    return text_input.handle_editing_key(key)


def _normalize_submenu_result(result: Any) -> tuple[InputIntent, ...]:
    if result is None:
        return ()
    if isinstance(result, InputIntent):
        return (result,)
    if isinstance(result, tuple) and all(isinstance(item, InputIntent) for item in result):
        return result
    return ()


def _scroll_start(selected_index: int, total: int, item_budget: int) -> int:
    if total <= item_budget:
        return 0
    centered = selected_index - item_budget // 2
    return max(0, min(centered, total - item_budget))


def _clamp_index(index: int, items: list[SelectItem]) -> int:
    if not items:
        return 0
    return max(0, min(index, len(items) - 1))


def _clamp_setting_index(index: int, items: list[SettingItem]) -> int:
    if not items:
        return 0
    return max(0, min(index, len(items) - 1))


def _bounded_lines(raw_lines: list[str], constraints: RenderConstraints) -> RenderResult:
    target_width = autowrap_safe_width(constraints.width)
    lines = [
        RenderLine(truncate_to_width(line, max_width=target_width))
        for line in raw_lines[: constraints.max_height]
    ]
    return RenderResult.from_lines(lines, constraints=constraints)
