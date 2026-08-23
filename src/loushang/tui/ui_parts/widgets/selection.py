from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loushang.tui.core import RenderConstraints, RenderResult
from loushang.tui.theme import ThemeResolver

if TYPE_CHECKING:
    from loushang.tui.surfaces import SelectItem


@dataclass(slots=True)
class SelectList:
    items: list[SelectItem] | tuple[SelectItem, ...]
    max_visible: int = 5
    close_on_escape: bool = False
    theme: ThemeResolver | None = None
    focused: bool = False
    _surface: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        from loushang.tui.surfaces import SelectionSurface

        self._surface = SelectionSurface(
            self.items,
            max_visible=self.max_visible,
            show_selection_when_unfocused=False,
            theme=self.theme,
        )
        if self.focused:
            self._surface.focus()

    def focus(self) -> None:
        self.focused = True
        self._surface.focus()

    def blur(self) -> None:
        self.focused = False
        self._surface.blur()

    @property
    def selected_item(self) -> object | None:
        return self._surface.selected_item()

    @property
    def selected_value(self) -> str:
        selected = self._surface.selected_item()
        return "" if selected is None else selected.selected_value

    def handle_input(self, event: object) -> object:
        if (
            not self.close_on_escape
            and getattr(event, "kind", "") == "key"
            and getattr(event, "key", "") in {"esc", "escape"}
        ):
            return None
        return self._surface.handle_input(event)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return self._surface.render(constraints)
