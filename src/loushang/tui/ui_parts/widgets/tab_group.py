from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from loushang.tui.core import (
    CursorDeclaration,
    RenderConstraints,
    RenderLine,
    RenderResult,
)
from loushang.tui.theme import ThemeResolver
from loushang.tui.ui_parts.widgets._utils import callback_result
from loushang.tui.ui_parts.widgets.tabs import TabFocusState, TabItem, Tabs

__all__ = ["TabGroup", "TabPage"]


@dataclass(frozen=True, slots=True)
class TabPage:
    value: str
    label: str
    content: object
    disabled: bool = False
    badge: str = ""


@dataclass(frozen=True, slots=True)
class TabChange:
    value: str
    previous_value: str
    level: int = 0


@dataclass(slots=True)
class _ContentSwitcher:
    content_height: int | None = None

    def render(self, content: object | None, constraints: RenderConstraints) -> RenderResult:
        height = self._target_height(constraints)
        if content is None or height <= 0:
            return RenderResult.from_lines(
                [RenderLine("") for _ in range(height)],
                constraints=constraints,
            )
        render = getattr(content, "render", None)
        cursor = None
        if not callable(render):
            lines = [RenderLine("")]
        else:
            result = render(
                RenderConstraints(
                    width=constraints.width,
                    max_height=height,
                    visible_height=constraints.visible_height,
                )
            )
            lines = list(result.lines[:height])
            if result.cursor is not None and result.cursor.row < len(lines):
                cursor = result.cursor
        while len(lines) < height:
            lines.append(RenderLine(""))
        return RenderResult.from_lines(lines[:height], constraints=constraints, cursor=cursor)

    def _target_height(self, constraints: RenderConstraints) -> int:
        if self.content_height is None:
            return max(0, constraints.max_height)
        return max(0, min(self.content_height, constraints.max_height))


@dataclass(slots=True)
class TabGroup:
    pages: Sequence[TabPage]
    value: str = ""
    level: int = 0
    wrap: bool = True
    content_height: int | None = None
    focused: bool = False
    header_focused: bool = True
    on_change: Callable[[str], object] | None = None
    theme: ThemeResolver | None = None
    _pages: tuple[TabPage, ...] = field(default=(), init=False, repr=False)
    _tabs: Tabs = field(init=False, repr=False)
    _switcher: _ContentSwitcher = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._pages = tuple(self.pages)
        self.value = self._normalize_value(self.value)
        self._switcher = _ContentSwitcher(self.content_height)
        self._tabs = self._make_tabs()

    @property
    def selected_value(self) -> str:
        return self.value

    @property
    def selected_page(self) -> TabPage | None:
        for page in self._pages:
            if page.value == self.value and not page.disabled:
                return page
        return None

    def focus(self) -> None:
        self.focused = True
        self.focus_header()

    def blur(self) -> None:
        if self.focused and not self.header_focused:
            self._blur_content()
        self.focused = False
        self.header_focused = True
        self._sync_tabs()

    def focus_header(self) -> None:
        if not self.header_focused:
            self._blur_content()
        self.focused = True
        self.header_focused = True
        self._sync_tabs()

    def focus_content(self) -> bool:
        page = self.selected_page
        if page is None:
            return False
        focus = getattr(page.content, "focus", None)
        if not callable(focus):
            return False
        self.focused = True
        self.header_focused = False
        focus()
        self._sync_tabs()
        return True

    def editor_input_target(self) -> object | None:
        if not self.focused or self.header_focused:
            return None
        page = self.selected_page
        target = getattr(page.content, "editor_input_target", None) if page is not None else None
        return target() if callable(target) else None

    def handle_input(self, event: object) -> object:
        if not self.focused:
            return None
        if self.header_focused:
            return self._handle_header_input(event)
        return self._handle_content_input(event)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if constraints.max_height <= 0:
            return RenderResult.from_lines([], constraints=constraints)
        self._sync_tabs()
        header = self._tabs.render(
            RenderConstraints(
                width=constraints.width,
                max_height=1,
                visible_height=constraints.visible_height,
            )
        )
        remaining_height = max(0, constraints.max_height - len(header.lines))
        if remaining_height <= 0:
            return RenderResult.from_lines(header.lines[: constraints.max_height], constraints=constraints)
        content = self._switcher.render(
            None if self.selected_page is None else self.selected_page.content,
            RenderConstraints(
                width=constraints.width,
                max_height=remaining_height,
                visible_height=constraints.visible_height,
            ),
        )
        cursor = header.cursor
        if content.cursor is not None and len(header.lines) + content.cursor.row < constraints.max_height:
            cursor = CursorDeclaration(
                row=len(header.lines) + content.cursor.row,
                column=content.cursor.column,
            )
        return RenderResult.from_lines(
            [*header.lines, *content.lines][: constraints.max_height],
            constraints=constraints,
            cursor=cursor,
        )

    def _handle_header_input(self, event: object) -> object:
        if getattr(event, "kind", "") == "key" and getattr(event, "key", "") in {"down", "enter"}:
            return True if self.focus_content() else False
        return self._handle_tab_navigation(event)

    def _handle_content_input(self, event: object) -> object:
        page = self.selected_page
        handler = getattr(page.content, "handle_input", None) if page is not None else None
        if callable(handler):
            result = handler(event)
            if result is not None:
                return result
        if getattr(event, "kind", "") == "key" and getattr(event, "key", "") in {"left", "right", "home", "end"}:
            return self._handle_tab_navigation(event)
        if getattr(event, "kind", "") == "key" and getattr(event, "key", "") in {"up", "shift+tab"}:
            self.focus_header()
            return True
        return None

    def _handle_tab_navigation(self, event: object) -> object:
        previous = self.value
        result = self._tabs.handle_input(event)
        if self._tabs.value != previous:
            return self._set_value(self._tabs.value, previous_value=previous)
        return result

    def _set_value(self, value: str, *, previous_value: str) -> object:
        if value == previous_value:
            return False
        content_was_focused = self.focused and not self.header_focused
        if content_was_focused:
            self._blur_content()
        self.value = value
        self._sync_tabs()
        if content_was_focused:
            self.focus_content()
        if self.on_change is not None:
            return callback_result(self.on_change(value))
        return TabChange(value=value, previous_value=previous_value, level=self.level)

    def _blur_content(self) -> None:
        page = self.selected_page
        if page is None:
            return
        blur = getattr(page.content, "blur", None)
        if callable(blur):
            blur()

    def _enabled_indices(self) -> tuple[int, ...]:
        return tuple(index for index, page in enumerate(self._pages) if not page.disabled)

    def _index_for_value(self, value: str) -> int | None:
        for index, page in enumerate(self._pages):
            if page.value == value:
                return index
        return None

    def _normalize_value(self, requested: str) -> str:
        enabled = self._enabled_indices()
        if not enabled:
            return ""
        requested_index = self._index_for_value(requested)
        if requested_index is not None:
            if requested_index in enabled:
                return self._pages[requested_index].value
            for index in enabled:
                if index > requested_index:
                    return self._pages[index].value
        return self._pages[enabled[0]].value

    def _make_tabs(self) -> Tabs:
        return Tabs(
            tuple(TabItem(page.value, page.label, page.disabled, page.badge) for page in self._pages),
            value=self.value,
            wrap=self.wrap,
            theme=self.theme,
            focused=self.focused and self.header_focused,
            level=self.level,
            selected_focus=self._selected_focus_state(),
        )

    def _sync_tabs(self) -> None:
        self._tabs.tabs = tuple(TabItem(page.value, page.label, page.disabled, page.badge) for page in self._pages)
        self._tabs.value = self.value
        self._tabs.wrap = self.wrap
        self._tabs.theme = self.theme
        self._tabs.focused = self.focused and self.header_focused
        self._tabs.level = self.level
        self._tabs.selected_focus = self._selected_focus_state()

    def _selected_focus_state(self) -> TabFocusState:
        if not self.focused:
            return "none"
        return "header" if self.header_focused else "content"
