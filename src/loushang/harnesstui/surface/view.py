from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from loushang.tui import (
    CursorDeclaration,
    FocusableMixin,
    InfoPanel,
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
)
from loushang.tui.cell_width import truncate_to_width, wrap_ansi, wrap_cells
from loushang.tui.theme import ThemeResolver, apply_theme_style

ScreenSurfacePurpose = Literal[
    "info",
    "model",
    "command",
    "settings",
    "session",
    "delete",
    "fork",
    "rename",
    "agent_tree",
    "permissions",
    "dialog",
    "approval",
]
ScreenSurfacePresentation = Literal["bottom", "bottom-exclusive", "page"]


@dataclass(slots=True)
class ScreenSurfaceView(FocusableMixin):
    title: str
    purpose: ScreenSurfacePurpose
    content: Any
    footer: str = "Enter to select - Esc to close"
    subtitle: str = ""
    feedback: str = ""
    feedback_hint: str = ""
    presentation: ScreenSurfacePresentation = "bottom"
    preferred_height: int | None = None
    theme: ThemeResolver | None = None
    title_theme_token: str = "surface.title"
    subtitle_theme_token: str = "surface.subtitle"
    feedback_theme_token: str = "widget.error"
    feedback_hint_theme_token: str = "surface.hint"
    footer_theme_token: str = "surface.footer"
    _last_content_start_row: int = field(default=0, init=False, repr=False)
    _info_scroll_offset: int = field(default=0, init=False, repr=False)
    _last_info_body_height: int = field(default=0, init=False, repr=False)
    _last_info_body_line_count: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        FocusableMixin.__init__(self)

    @property
    def exclusive_bottom(self) -> bool:
        return self.presentation == "bottom-exclusive"

    @property
    def full_screen_page(self) -> bool:
        return self.presentation == "page"

    def editor_input_target(self) -> object | None:
        target = getattr(self.content, "editor_input_target", None)
        return target() if callable(target) else None

    def handle_input(self, event: InputEvent) -> InputIntent[str] | None:
        if self.purpose == "info":
            if event.kind == "key" and event.key in {"enter", "space", "escape", "esc"}:
                return InputIntent(kind="surface_close")
            if event.kind == "key":
                return self._handle_info_scroll_input(event.key)
            return None
        handler = getattr(self.content, "handle_input", None)
        if callable(handler):
            intent = _screen_input_intent_or_none(
                handler(self._translate_content_input_event(event))
            )
            if intent is not None:
                return intent
        if event.kind == "key" and event.key in {"escape", "esc"}:
            return InputIntent(kind="surface_close")
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        width = constraints.width
        lines = [
            self._styled(
                truncate_to_width(self.title, max_width=width),
                self.title_theme_token,
            )
        ]
        cursor: CursorDeclaration | None = None
        if self.subtitle:
            lines.append(
                self._styled(
                    truncate_to_width(self.subtitle, max_width=width),
                    self.subtitle_theme_token,
                )
            )
        lines.append("")
        footer = self._footer_text()
        feedback_lines = self._feedback_lines(width)
        reserved_feedback_lines = len(feedback_lines) + (1 if feedback_lines else 0)
        reserved_footer_lines = 2 if footer else 0
        body_constraints = RenderConstraints(
            width=width,
            max_height=max(
                1,
                constraints.max_height
                - len(lines)
                - reserved_feedback_lines
                - reserved_footer_lines,
            ),
        )
        if isinstance(self.content, InfoPanel):
            body_lines: list[str] = []
            for raw_line in self.content.text.splitlines():
                body_lines.extend(wrap_cells(raw_line, width=width) or [""])
            self._last_info_body_height = body_constraints.max_height
            self._last_info_body_line_count = len(body_lines)
            max_offset = self._max_info_scroll_offset()
            self._info_scroll_offset = max(0, min(self._info_scroll_offset, max_offset))
            visible_body_lines = body_lines[
                self._info_scroll_offset : self._info_scroll_offset
                + body_constraints.max_height
            ]
            body_start_row = len(lines)
            lines.extend(visible_body_lines)
            if visible_body_lines:
                cursor = CursorDeclaration(
                    row=body_start_row + len(visible_body_lines) - 1, column=0
                )
        else:
            self._last_content_start_row = len(lines)
            result = self.content.render(body_constraints)
            lines.extend(line.text for line in result.lines)
            if result.cursor is not None:
                cursor_row = self._last_content_start_row + result.cursor.row
                if cursor_row < constraints.max_height:
                    cursor = CursorDeclaration(
                        row=cursor_row, column=result.cursor.column
                    )
        footer = self._footer_text()
        if feedback_lines and len(lines) < constraints.max_height:
            lines.append("")
            lines.extend(
                feedback_lines[: max(0, constraints.max_height - len(lines))]
            )
        if footer and len(lines) < constraints.max_height:
            if len(lines) + 1 < constraints.max_height:
                lines.append("")
            lines.append(
                self._styled(
                    truncate_to_width(footer, max_width=width),
                    self.footer_theme_token,
                )
            )
        return RenderResult.from_lines(
            [RenderLine(line) for line in lines[: constraints.max_height]],
            constraints=constraints,
            cursor=cursor,
        )

    def _translate_content_input_event(self, event: InputEvent) -> InputEvent:
        if event.kind != "mouse" or event.mouse_row is None:
            return event
        return replace(event, mouse_row=event.mouse_row - self._last_content_start_row)

    def _handle_info_scroll_input(self, key: str) -> InputIntent[str] | None:
        page = max(1, self._last_info_body_height)
        if key == "down":
            return self._scroll_info(1)
        if key == "up":
            return self._scroll_info(-1)
        if key == "pageDown":
            return self._scroll_info(page)
        if key == "pageUp":
            return self._scroll_info(-page)
        if key == "home":
            return self._set_info_scroll(0)
        if key == "end":
            return self._set_info_scroll(self._max_info_scroll_offset())
        return None

    def _scroll_info(self, delta: int) -> InputIntent[str] | None:
        return self._set_info_scroll(self._info_scroll_offset + delta)

    def _set_info_scroll(self, offset: int) -> InputIntent[str] | None:
        max_offset = self._max_info_scroll_offset()
        next_offset = max(0, min(offset, max_offset))
        if next_offset == self._info_scroll_offset:
            return None
        self._info_scroll_offset = next_offset
        return InputIntent(kind="consumed", note="info_scroll")

    def _max_info_scroll_offset(self) -> int:
        return max(0, self._last_info_body_line_count - self._last_info_body_height)

    def _footer_text(self) -> str:
        dynamic_footer = getattr(self.content, "footer_help", None)
        footer = dynamic_footer if isinstance(dynamic_footer, str) else self.footer
        if not footer:
            return ""
        if self.purpose == "info" and self._max_info_scroll_offset() > 0:
            return f"Up/Down/Page to scroll - {footer}"
        return footer

    def _feedback_lines(self, width: int) -> list[str]:
        lines: list[str] = []
        if self.feedback:
            lines.extend(
                wrap_ansi(
                    self._styled(self.feedback, self.feedback_theme_token),
                    width=width,
                )
            )
        if self.feedback_hint:
            lines.extend(
                wrap_ansi(
                    self._styled(self.feedback_hint, self.feedback_hint_theme_token),
                    width=width,
                )
            )
        return lines

    def _styled(self, text: str, token: str) -> str:
        if self.theme is None:
            return text
        return apply_theme_style(text, self.theme.resolve(token))


def _screen_input_intent_or_none(result: object) -> InputIntent[str] | None:
    if isinstance(result, InputIntent):
        return result
    kind = getattr(result, "kind", None)
    if not isinstance(kind, str):
        return None
    return InputIntent(
        kind=kind,
        text=str(getattr(result, "text", "")),
        note=str(getattr(result, "note", "")),
    )


__all__ = [
    "ScreenSurfacePresentation",
    "ScreenSurfacePurpose",
    "ScreenSurfaceView",
]
