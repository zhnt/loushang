from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from loushang.tui.cell_width import (
    autowrap_safe_width,
    truncate_to_width,
    visible_width,
)
from loushang.tui.core import (
    CursorDeclaration,
    RenderConstraints,
    RenderLine,
    RenderResult,
)
from loushang.tui.theme import ThemeResolver
from loushang.tui.ui_parts.widgets._utils import (
    callback_result,
    is_activation_event,
    style_text,
)

TabFocusState = Literal["auto", "header", "content", "none"]
TabRenderState = Literal[
    "normal",
    "selected_unfocused",
    "selected_content_focus",
    "selected_header_focus",
    "disabled",
]


@dataclass(frozen=True, slots=True)
class TabItem:
    value: str
    label: str
    disabled: bool = False
    badge: str = ""

    @property
    def display_label(self) -> str:
        return self.label if not self.badge else f"{self.label} {self.badge}".strip()


@dataclass(slots=True)
class Tabs:
    tabs: Sequence[TabItem]
    value: str = ""
    wrap: bool = True
    on_change: Callable[[str], object] | None = None
    theme: ThemeResolver | None = None
    focused: bool = False
    level: int = 0
    selected_focus: TabFocusState = "auto"

    def __post_init__(self) -> None:
        self.tabs = tuple(self.tabs)
        self.value = self._normalize_value(self.value)

    @property
    def selected_value(self) -> str:
        return self.value

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def handle_input(self, event: object) -> object:
        if getattr(event, "kind", "") == "key":
            key = getattr(event, "key", "")
            if key == "left":
                return self._move_selection(-1)
            if key == "right":
                return self._move_selection(1)
            if key == "home":
                return self._jump_selection(first=True)
            if key == "end":
                return self._jump_selection(first=False)
        if is_activation_event(event):
            return self.value or None
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if not self.tabs:
            return RenderResult.from_lines([], constraints=constraints)
        target_width = autowrap_safe_width(constraints.width)
        parts: list[str] = []
        cursor_column: int | None = None
        current_column = 0
        for tab in self.tabs:
            segment = _tab_segment(self, tab)
            if self.focused and tab.value == self.value and not tab.disabled:
                cursor_column = min(current_column, max(0, target_width - 1))
            parts.append(segment)
            current_column += visible_width(segment) + 2
        line = truncate_to_width("  ".join(parts), max_width=target_width, ellipsis="")
        cursor = None if cursor_column is None else CursorDeclaration(row=0, column=cursor_column)
        return RenderResult.from_lines([RenderLine(line)][: constraints.max_height], constraints=constraints, cursor=cursor)

    def _enabled_indices(self) -> tuple[int, ...]:
        return tuple(index for index, tab in enumerate(self.tabs) if not tab.disabled)

    def _index_for_value(self, value: str) -> int | None:
        for index, tab in enumerate(self.tabs):
            if tab.value == value:
                return index
        return None

    def _normalize_value(self, requested: str) -> str:
        enabled = self._enabled_indices()
        if not enabled:
            return ""
        requested_index = self._index_for_value(requested)
        if requested_index is not None:
            if requested_index in enabled:
                return self.tabs[requested_index].value
            for index in enabled:
                if index > requested_index:
                    return self.tabs[index].value
        return self.tabs[enabled[0]].value

    def _selected_index(self) -> int | None:
        index = self._index_for_value(self.value)
        if index is None or self.tabs[index].disabled:
            return None
        return index

    def _move_selection(self, delta: int) -> object:
        enabled = self._enabled_indices()
        if not enabled:
            return None
        selected = self._selected_index()
        if selected is None:
            return self._set_value(self.tabs[enabled[0]].value)
        position = enabled.index(selected)
        next_position = position + delta
        if self.wrap:
            next_position %= len(enabled)
        elif next_position < 0 or next_position >= len(enabled):
            return False
        next_index = enabled[next_position]
        if next_index == selected:
            return False
        return self._set_value(self.tabs[next_index].value)

    def _jump_selection(self, *, first: bool) -> object:
        enabled = self._enabled_indices()
        if not enabled:
            return None
        selected = self._selected_index()
        target = enabled[0] if first else enabled[-1]
        if target == selected:
            return False
        return self._set_value(self.tabs[target].value)

    def _set_value(self, value: str) -> object:
        self.value = value
        if self.on_change is not None:
            return callback_result(self.on_change(value))
        return True


def _tab_segment(tabs: Tabs, tab: TabItem) -> str:
    state = _tab_render_state(tabs, tab)
    text = f"{_tab_marker(state)}[{tab.display_label}]"
    return style_text(text, tabs.theme, *_tab_tokens(tabs, state=state))


def _tab_render_state(tabs: Tabs, tab: TabItem) -> TabRenderState:
    selected = tab.value == tabs.value and not tab.disabled
    if tab.disabled:
        return "disabled"
    if not selected:
        return "normal"
    focus_state = _selected_focus_state(tabs)
    if focus_state == "header":
        return "selected_header_focus"
    if focus_state == "content":
        return "selected_content_focus"
    return "selected_unfocused"


def _tab_marker(state: TabRenderState) -> str:
    if state == "selected_header_focus":
        return ">"
    if state in {"selected_unfocused", "selected_content_focus"}:
        return "*"
    return " "


def _selected_focus_state(tabs: Tabs) -> str:
    if tabs.selected_focus != "auto":
        return tabs.selected_focus
    return "header" if tabs.focused else "none"


def _tab_tokens(tabs: Tabs, *, state: TabRenderState) -> tuple[str, ...]:
    level = max(0, tabs.level)
    nested_prefix = "widget.tabs.nested" if level > 0 else ""
    level_prefix = f"widget.tabs.level{level}"
    if state == "disabled":
        return tuple(
            token
            for token in (
                "widget.tabs.disabled",
                f"{nested_prefix}.disabled" if nested_prefix else "",
                f"{level_prefix}.disabled",
            )
            if token
        )
    if state == "selected_header_focus":
        return tuple(
            token
            for token in (
                "widget.tabs.selected",
                "widget.tabs.focus",
                f"{nested_prefix}.selected_header_focus" if nested_prefix else "",
                f"{level_prefix}.selected_header_focus",
            )
            if token
        )
    if state == "selected_content_focus":
        return tuple(
            token
            for token in (
                "widget.tabs.selected",
                f"{nested_prefix}.selected_content_focus" if nested_prefix else "",
                f"{level_prefix}.selected_content_focus",
            )
            if token
        )
    if state == "selected_unfocused":
        return ("widget.tabs.selected",)
    return tuple(
        token
        for token in (
            "widget.tabs.tab",
            "widget.tabs.normal",
            f"{nested_prefix}.normal" if nested_prefix else "",
            f"{level_prefix}.normal",
        )
        if token
    )
