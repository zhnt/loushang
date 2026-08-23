from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loushang.tui.selection import SelectionRange

__all__ = ["SelectionController"]


@dataclass(slots=True)
class SelectionController:
    length: Callable[[], int]
    cursor: Callable[[], int]
    set_cursor: Callable[[int], object]
    _selection: SelectionRange | None = None

    @property
    def selected_range(self) -> tuple[int, int] | None:
        selection = self._selection
        if selection is None:
            return None
        start, end = selection.normalized(self.length())
        if start == end:
            return None
        return start, end

    @property
    def raw_selection(self) -> SelectionRange | None:
        return self._selection

    def has_selection(self) -> bool:
        return self.selected_range is not None

    def set(self, anchor: int, focus: int) -> None:
        anchor = self.clamp_index(anchor)
        focus = self.clamp_index(focus)
        self.set_cursor(focus)
        self._selection = None if anchor == focus else SelectionRange(anchor=anchor, focus=focus)

    def clear(self) -> None:
        self._selection = None

    def extend_to(self, target: int) -> None:
        previous_cursor = self.cursor()
        target = self.clamp_index(target)
        anchor = self._selection.anchor if self._selection is not None else previous_cursor
        self.set(anchor, target)

    def clamp_index(self, index: int) -> int:
        return max(0, min(index, self.length()))
