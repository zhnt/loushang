from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypedDict, Unpack

from loushang.tui.cell_width import autowrap_safe_width, truncate_to_width
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.theme import ThemeResolver
from loushang.tui.ui_parts.widgets._utils import (
    callback_result,
    is_activation_event,
    style_text,
)

ButtonKind = Literal["default", "primary", "danger", "ghost"]


class _ButtonOptions(TypedDict, total=False):
    kind: ButtonKind
    disabled: bool
    on_press: Callable[[], object] | None
    theme: ThemeResolver | None
    theme_token: str | None
    focused: bool


@dataclass(slots=True)
class Button:
    label: str
    icon: str = ""
    kind: ButtonKind = "default"
    disabled: bool = False
    on_press: Callable[[], object] | None = None
    theme: ThemeResolver | None = None
    theme_token: str | None = None
    focused: bool = False

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def handle_input(self, event: object) -> object:
        if self.disabled or not is_activation_event(event):
            return None
        if self.on_press is None:
            return True
        return callback_result(self.on_press())

    def render(self, constraints: RenderConstraints) -> RenderResult:
        target_width = autowrap_safe_width(constraints.width)
        label = self.label if not self.icon else f"{self.icon} {self.label}".strip()
        line = f"{'> ' if self.focused else '  '}[{label}]"
        rendered = truncate_to_width(line, max_width=target_width, ellipsis="")
        base_token = self.theme_token or _button_base_token(self.kind)
        state_token = "widget.disabled" if self.disabled else "widget.focus" if self.focused else None
        rendered = style_text(rendered, self.theme, base_token, state_token)
        return RenderResult.from_lines([RenderLine(rendered)][: constraints.max_height], constraints=constraints)


def IconButton(
    icon: str, *, label: str = "", **kwargs: Unpack[_ButtonOptions]
) -> Button:
    return Button(label=label, icon=icon, **kwargs)


def _button_base_token(kind: ButtonKind) -> str:
    return f"widget.button.{kind}"
