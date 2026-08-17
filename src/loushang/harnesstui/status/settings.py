from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from loushang.harnesstui.status.line import (
    StatusLinePreviewSnapshot,
    StatusLineSettings,
    status_line_fields,
    status_line_separator,
    status_line_style_mode,
)
from loushang.tui import (
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SearchableList,
    StatusBar,
)
from loushang.tui.settings import (
    ConfigRow,
    SettingsListPage,
    bool_text,
    next_bool_value,
    row_for_key,
)

__all__ = [
    "StatusLineSettingsPage",
    "next_statusline_value",
    "statusline_rows",
]


@dataclass(slots=True)
class StatusLineSettingsPage:
    statusline_settings: StatusLineSettings
    statusline_preview: Callable[[], StatusLinePreviewSnapshot]
    focused: bool = False
    settings: SearchableList = field(init=False)
    _list_page: SettingsListPage = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._list_page = SettingsListPage(
            statusline_rows(self.statusline_settings),
            placeholder="Search status line...",
            empty_text="No matching status line settings",
            on_select=self._setting_intent,
        )
        self.settings = self._list_page.settings

    def focus(self) -> None:
        self.focused = True
        self._list_page.focus()

    def blur(self) -> None:
        self.focused = False
        self._list_page.blur()

    def editor_input_target(self) -> object | None:
        return self._list_page.editor_input_target()

    def set_statusline_settings(self, settings: StatusLineSettings, *, preserve_active_key: str = "") -> None:
        self.statusline_settings = settings
        self._list_page.set_rows(statusline_rows(settings), preserve_active_key=preserve_active_key)

    def handle_input(self, event: object) -> object:
        return self._list_page.handle_input(event)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if constraints.max_height <= 0:
            return RenderResult.from_lines([], constraints=constraints)
        if constraints.max_height <= 6:
            return self.settings.render(constraints)
        result = self._list_page.render(
            RenderConstraints(width=constraints.width, max_height=max(1, constraints.max_height - 2))
        )
        preview = _statusline_preview_lines(
            self.statusline_preview(),
            self.statusline_settings,
            width=constraints.width,
        )
        rows = [*result.lines, RenderLine(""), *preview]
        return RenderResult.from_lines(
            rows[: constraints.max_height],
            constraints=constraints,
            cursor=result.cursor,
        )

    def _setting_intent(self, row: ConfigRow) -> InputIntent | None:
        current = row_for_key(statusline_rows(self.statusline_settings), row.id)
        if current is None or current.disabled:
            return None
        return InputIntent(
            kind="setting",
            text=current.id,
            note=next_statusline_value(current.id, current.value),
        )


def statusline_rows(settings: StatusLineSettings) -> tuple[ConfigRow, ...]:
    return (
        ConfigRow("statusline.enabled", "Enabled", bool_text(settings.enabled)),
        ConfigRow("statusline.field.model", "Model", bool_text(settings.model)),
        ConfigRow("statusline.field.workspace", "Workspace", bool_text(settings.workspace)),
        ConfigRow("statusline.field.branch", "Branch", bool_text(settings.branch)),
        ConfigRow("statusline.field.session", "Session", bool_text(settings.session)),
        ConfigRow(
            "statusline.field.permissions",
            "Permissions",
            bool_text(settings.permissions),
        ),
        ConfigRow("statusline.field.runtime", "Runtime", bool_text(settings.runtime)),
        ConfigRow("statusline.field.queue", "Queue", settings.queue),
        ConfigRow("statusline.field.message", "Message", settings.message),
        ConfigRow("statusline.separator", "Separator", settings.separator),
        ConfigRow("statusline.style", "Style", settings.style),
    )


def next_statusline_value(item_id: str, value: str) -> str:
    if item_id in {
        "statusline.enabled",
        "statusline.field.model",
        "statusline.field.workspace",
        "statusline.field.branch",
        "statusline.field.session",
        "statusline.field.permissions",
        "statusline.field.runtime",
    }:
        return next_bool_value(value)
    if item_id in {"statusline.field.queue", "statusline.field.message"}:
        return {"auto": "true", "true": "false", "false": "auto"}.get(value, value)
    if item_id == "statusline.separator":
        return "dot" if value == "pipe" else "pipe"
    if item_id == "statusline.style":
        return {"codex-like": "muted", "muted": "plain", "plain": "codex-like"}.get(value, value)
    return value


def _statusline_preview_lines(
    snapshot: StatusLinePreviewSnapshot,
    settings: StatusLineSettings,
    *,
    width: int,
) -> tuple[RenderLine, ...]:
    result = StatusBar(
        status_line_fields(snapshot, settings),
        separator=status_line_separator(settings),
        style_mode=status_line_style_mode(settings),
    ).render(RenderConstraints(width=width, max_height=1))
    line = result.lines[0].text if result.lines else ""
    return (RenderLine("Preview"), RenderLine(line))
