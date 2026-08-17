from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from loushang.tui import (
    CursorDeclaration,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SearchableList,
    TabGroup,
    truncate_to_width,
)
from loushang.tui.settings import bool_text


class StatusSnapshotView(Protocol):
    @property
    def model_label(self) -> str | None: ...

    @property
    def cwd(self) -> str: ...

    @property
    def branch(self) -> str | None: ...

    @property
    def session_label(self) -> str | None: ...

    @property
    def thinking_level(self) -> str | None: ...

    @property
    def running(self) -> bool: ...

    @property
    def statusline_visible(self) -> bool: ...


UsageProvider = Callable[[], object | None]


@dataclass(slots=True)
class StaticLinesPage:
    lines: tuple[str, ...]
    focused: bool = False

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def handle_input(self, event: object) -> object:
        if getattr(event, "kind", "") == "key" and getattr(event, "key", "") in {
            "left",
            "right",
            "home",
            "end",
        }:
            return True
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        rows = [
            RenderLine(truncate_to_width(line, max_width=constraints.width, ellipsis=""))
            for line in self.lines[: constraints.max_height]
        ]
        return RenderResult.from_lines(rows, constraints=constraints)


@dataclass(slots=True)
class SettingsDashboard:
    """Product-neutral tabbed settings shell.

    Products provide the populated ``TabGroup`` and handle setting intents.
    This class owns only focus routing, close interaction, chrome, and footer
    presentation shared by Harness-backed terminal products.
    """

    tabs: TabGroup = field(init=False)
    focused: bool = field(default=False, init=False)
    feedback_message: str | None = field(default=None, init=False)

    def focus(self) -> None:
        self.focused = True
        self.tabs.focus_content()

    def blur(self) -> None:
        self.focused = False
        self.tabs.blur()

    def editor_input_target(self) -> object | None:
        return self.tabs.editor_input_target()

    def handle_input(self, event: object) -> object:
        result = self.tabs.handle_input(event)
        if result is not None:
            return result
        if _is_escape_event(event):
            return InputIntent(kind="surface_close")
        if _is_q_event(event) and self.focus_context() in {
            "tabs",
            "page",
            "settings-list",
            "model-list",
        }:
            return InputIntent(kind="surface_close")
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if constraints.max_height <= 0:
            return RenderResult.from_lines([], constraints=constraints)
        body_height = max(1, constraints.max_height - 2)
        result = self.tabs.render(
            RenderConstraints(width=constraints.width, max_height=body_height)
        )
        rows = _with_separator(result.lines, width=constraints.width)
        cursor = _offset_cursor_after_separator(result.cursor)
        footer = settings_footer_text(
            self.focus_context(),
            self.feedback_message,
            width=constraints.width,
        )
        while len(rows) < constraints.max_height - 1:
            rows.append(RenderLine(""))
        if len(rows) < constraints.max_height:
            rows.append(RenderLine(footer))
        return RenderResult.from_lines(
            rows[: constraints.max_height],
            constraints=constraints,
            cursor=cursor,
        )

    def focus_context(self) -> str:
        if self.tabs.header_focused:
            return "tabs"
        page = self.tabs.selected_page
        content = page.content if page is not None else None
        settings = getattr(content, "settings", None)
        if isinstance(settings, SearchableList):
            return "search" if settings.focus_region == "search" else "settings-list"
        models = getattr(content, "models", None)
        if isinstance(models, SearchableList):
            return "search" if models.focus_region == "search" else "model-list"
        if isinstance(content, TabGroup):
            return "tabs" if content.header_focused else "page"
        return "page"


def status_lines(snapshot: StatusSnapshotView) -> tuple[str, ...]:
    return (
        "Status",
        "",
        f"Model              {snapshot.model_label or 'Unavailable'}",
        f"Workspace          {snapshot.cwd}",
        f"Branch             {snapshot.branch or 'Unavailable'}",
        f"Session            {snapshot.session_label or 'Unavailable'}",
        f"Thinking           {snapshot.thinking_level or 'Unavailable'}",
        f"Runtime            {'running' if snapshot.running else 'idle'}",
        f"Status line        {bool_text(snapshot.statusline_visible)}",
    )


def usage_lines(provider: UsageProvider | None) -> tuple[str, ...]:
    if provider is None:
        return ("Usage", "", "Usage data unavailable")
    try:
        snapshot = provider()
    except Exception:
        snapshot = None
    if snapshot is None:
        return ("Usage", "", "Usage data unavailable")
    return (
        "Usage",
        "",
        f"Current context    {getattr(snapshot, 'tokens', 'Unavailable')}",
        f"Context window     {getattr(snapshot, 'context_window', 'Unavailable')}",
        f"Percent used       {getattr(snapshot, 'percent', 'Unavailable')}",
        f"Source             {getattr(snapshot, 'source', 'Unavailable')}",
    )


def stats_overview_lines(snapshot: StatusSnapshotView) -> tuple[str, ...]:
    return (
        "Session Overview",
        "",
        f"Session            {snapshot.session_label or 'Unavailable'}",
        f"Runtime            {'running' if snapshot.running else 'idle'}",
        "Historical stats   Unavailable",
    )


def model_usage_lines(current_value: str | None) -> tuple[str, ...]:
    return (
        "Model Usage",
        "",
        f"Current model      {current_value or 'Unavailable'}",
        "Historical usage   Unavailable",
    )


def settings_footer_text(
    focus_context: str,
    feedback_message: str | None = None,
    *,
    width: int,
) -> str:
    if focus_context == "search":
        text = "Type to filter · Enter/↓ to select · ↑ to tabs · Esc to clear"
    elif focus_context in {"settings-list", "model-list"}:
        text = "↑/↓ to move · Enter/Space to select · ↑ on first row to search · q to close"
    elif focus_context == "tabs":
        text = "←/→ to switch tabs · ↓ to enter · q to close"
    else:
        text = "↑ to tabs · q to close"
    if feedback_message:
        text = f"{feedback_message} · {text}"
    return truncate_to_width(text, max_width=width, ellipsis="")


def _separator(width: int) -> str:
    return "-" * max(1, width)


def _with_separator(lines: Sequence[RenderLine], *, width: int) -> list[RenderLine]:
    if not lines:
        return []
    return [lines[0], RenderLine(_separator(width)), *lines[1:]]


def _offset_cursor_after_separator(
    cursor: CursorDeclaration | None,
) -> CursorDeclaration | None:
    if cursor is None or cursor.row == 0:
        return cursor
    return CursorDeclaration(row=cursor.row + 1, column=cursor.column)


def _is_escape_event(event: object) -> bool:
    return getattr(event, "kind", "") == "key" and getattr(event, "key", "") in {
        "escape",
        "esc",
    }


def _is_q_event(event: object) -> bool:
    return (
        getattr(event, "kind", "") == "key"
        and getattr(event, "key", "").casefold() == "q"
    ) or (
        getattr(event, "kind", "") == "text"
        and getattr(event, "text", "").casefold() == "q"
    )


__all__ = [
    "SettingsDashboard",
    "StaticLinesPage",
    "StatusSnapshotView",
    "UsageProvider",
    "model_usage_lines",
    "settings_footer_text",
    "stats_overview_lines",
    "status_lines",
    "usage_lines",
]
