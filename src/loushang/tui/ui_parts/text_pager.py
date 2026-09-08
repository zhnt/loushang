"""Bounded read-only plain text paging, without command or decision semantics."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from loushang.tui.cell_width import (
    max_display_cluster_width,
    strip_control_sequences,
    truncate_to_width,
    wrap_cells,
)
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.input import InputEvent


@dataclass(slots=True)
class TextPager:
    title: str
    text: str
    _lines: list[str] = field(default_factory=list, init=False, repr=False)
    _width: int = field(default=0, init=False)
    _height: int = field(default=1, init=False)
    _row: int = field(default=0, init=False)
    _presented: int = field(default=0, init=False)
    _layout_valid: bool = field(default=False, init=False)
    _cluster_width: int = field(default=2, init=False)

    def __post_init__(self) -> None:
        for value in (self.title, self.text):
            if len(value.encode("utf-8")) > 1024 * 1024:
                raise ValueError("pager_text_limit")
        self.text = "".join(
            char
            for char in strip_control_sequences(self.text).expandtabs(4)
            if char == "\n" or unicodedata.category(char) != "Cc"
        )
        if len(self.text.encode("utf-8")) > 1024 * 1024:
            raise ValueError("pager_text_limit")
        title = "".join(
            char
            for char in strip_control_sequences(self.title)
            if char in "\n\t" or unicodedata.category(char) != "Cc"
        )
        self.title = " ".join(title.split())
        self._cluster_width = max_display_cluster_width(self.text)

    @property
    def fully_presented(self) -> bool:
        """Every wrapped line has been included in a contiguous rendered view."""
        return (
            self._layout_valid
            and bool(self._lines)
            and self._presented >= len(self._lines)
        )

    def handle_input(self, event: InputEvent) -> None:
        if event.kind != "key":
            return
        if event.key == "home":
            self._row = 0
        elif event.key == "end":
            self._row = len(self._lines)
        elif event.key in {"up", "down", "pageUp", "pageDown"}:
            step = self._height if event.key.startswith("page") else 1
            self._row += step if event.key in {"down", "pageDown"} else -step
        self._row = max(0, min(self._row, max(0, len(self._lines) - self._height)))

    def render(self, constraints: RenderConstraints) -> RenderResult:
        width = max(1, constraints.width - 1)
        self._layout_valid = (
            width >= max(2, self._cluster_width) and constraints.max_height >= 3
        )
        if not self._layout_valid:
            return RenderResult.from_lines(
                (
                    RenderLine(
                        truncate_to_width(
                            "Resize terminal to read details", max_width=width
                        )
                    ),
                ),
                constraints=constraints,
            )
        if self._width != width:
            self._width, self._row, self._presented = width, 0, 0
            self._lines = wrap_cells(self.text, width=width)
        self._height = constraints.max_height - 2
        self._row = min(self._row, max(0, len(self._lines) - self._height))
        end = min(len(self._lines), self._row + self._height)
        if self._row <= self._presented:
            self._presented = max(self._presented, end)
        footer = f"{self._row + 1}-{end}/{len(self._lines)} | PgUp/PgDn | Esc back"
        rows = [self.title, *self._lines[self._row : end], footer]
        return RenderResult.from_lines(
            tuple(RenderLine(truncate_to_width(row, max_width=width)) for row in rows),
            constraints=constraints,
        )


__all__ = ["TextPager"]
