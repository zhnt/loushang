from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Protocol, TextIO, TypeVar, runtime_checkable

from loushang.tui.cell_width import _extract_control_sequence

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TerminalSize:
    columns: int
    rows: int

    def __post_init__(self) -> None:
        if self.columns <= 0:
            raise ValueError("columns must be positive")
        if self.rows <= 0:
            raise ValueError("rows must be positive")


@dataclass(frozen=True, slots=True)
class TerminalOperation:
    kind: str
    text: str = ""
    row: int | None = None
    column: int | None = None
    bottom: int | None = None
    lines: int = 0
    active: bool | None = None

    @classmethod
    def write(cls, text: str) -> TerminalOperation:
        return cls(kind="write", text=text)

    @classmethod
    def begin_synchronized_update(cls) -> TerminalOperation:
        return cls(kind="begin_synchronized_update")

    @classmethod
    def end_synchronized_update(cls) -> TerminalOperation:
        return cls(kind="end_synchronized_update")

    @classmethod
    def carriage_return(cls) -> TerminalOperation:
        return cls(kind="carriage_return")

    @classmethod
    def newline(cls) -> TerminalOperation:
        return cls(kind="newline")

    @classmethod
    def clear_line(cls) -> TerminalOperation:
        return cls(kind="clear_line")

    @classmethod
    def clear_from_cursor(cls) -> TerminalOperation:
        return cls(kind="clear_from_cursor")

    @classmethod
    def clear_screen(cls) -> TerminalOperation:
        return cls(kind="clear_screen")

    @classmethod
    def clear_scrollback(cls) -> TerminalOperation:
        return cls(kind="clear_scrollback")

    @classmethod
    def set_scroll_region(cls, *, top: int, bottom: int) -> TerminalOperation:
        return cls(kind="set_scroll_region", row=top, bottom=bottom)

    @classmethod
    def reset_scroll_region(cls) -> TerminalOperation:
        return cls(kind="reset_scroll_region")

    @classmethod
    def move_cursor(cls, *, row: int, column: int) -> TerminalOperation:
        return cls(kind="move_cursor", row=row, column=column)

    @classmethod
    def move_relative(cls, *, lines: int) -> TerminalOperation:
        return cls(kind="move_relative", lines=lines)

    @classmethod
    def move_column(cls, *, column: int) -> TerminalOperation:
        return cls(kind="move_column", column=column)

    @classmethod
    def hide_cursor(cls) -> TerminalOperation:
        return cls(kind="hide_cursor")

    @classmethod
    def show_cursor(cls) -> TerminalOperation:
        return cls(kind="show_cursor")

    @classmethod
    def set_title(cls, title: str) -> TerminalOperation:
        return cls(kind="set_title", text=title)

    @classmethod
    def set_progress(cls, active: bool) -> TerminalOperation:
        return cls(kind="set_progress", active=active)

    def serialize(self) -> str:
        if self.kind == "write":
            return self.text
        if self.kind == "begin_synchronized_update":
            return "\x1b[?2026h"
        if self.kind == "end_synchronized_update":
            return "\x1b[?2026l"
        if self.kind == "carriage_return":
            return "\r"
        if self.kind == "newline":
            return "\r\n"
        if self.kind == "clear_line":
            return "\x1b[2K"
        if self.kind == "clear_from_cursor":
            return "\x1b[J"
        if self.kind == "clear_screen":
            return "\x1b[2J\x1b[H"
        if self.kind == "clear_scrollback":
            return "\x1b[3J"
        if self.kind == "set_scroll_region":
            top = 0 if self.row is None else self.row
            bottom = top if self.bottom is None else self.bottom
            return f"\x1b[{top + 1};{bottom + 1}r"
        if self.kind == "reset_scroll_region":
            return "\x1b[r"
        if self.kind == "move_cursor":
            row = 0 if self.row is None else self.row
            column = 0 if self.column is None else self.column
            return f"\x1b[{row + 1};{column + 1}H"
        if self.kind == "move_relative":
            if self.lines > 0:
                return f"\x1b[{self.lines}B"
            if self.lines < 0:
                return f"\x1b[{-self.lines}A"
            return ""
        if self.kind == "move_column":
            column = 0 if self.column is None else self.column
            return f"\x1b[{column + 1}G"
        if self.kind == "hide_cursor":
            return "\x1b[?25l"
        if self.kind == "show_cursor":
            return "\x1b[?25h"
        if self.kind == "set_title":
            return f"\x1b]0;{self.text}\x07"
        if self.kind == "set_progress":
            return "\x1b]9;4;3\x07" if self.active else "\x1b]9;4;0;\x07"
        raise ValueError(f"unknown terminal operation: {self.kind}")


@dataclass(frozen=True, slots=True)
class FakeCellStyle:
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    blink: bool = False
    reverse: bool = False
    hidden: bool = False
    strikethrough: bool = False
    foreground: str | None = None
    background: str | None = None


@dataclass(frozen=True, slots=True)
class FakeScreen:
    size: TerminalSize
    visible_lines: tuple[str, ...]
    cell_styles: tuple[tuple[FakeCellStyle, ...], ...]
    scrollback_lines: tuple[str, ...] = ()
    cursor_row: int = 0
    cursor_column: int = 0
    viewport_top: int = 0
    scroll_top: int = 0
    scroll_bottom: int | None = None
    scrollback_cleared: bool = False
    autowrap_pending: bool = False
    active_style: FakeCellStyle = field(default_factory=FakeCellStyle)

    @classmethod
    def empty(cls, size: TerminalSize) -> FakeScreen:
        return cls(
            size=size,
            visible_lines=tuple("" for _ in range(size.rows)),
            cell_styles=tuple(_empty_style_row(size.columns) for _ in range(size.rows)),
        )

    def resized(self, size: TerminalSize) -> FakeScreen:
        lines = tuple(line[: size.columns] for line in self.visible_lines[: size.rows])
        if len(lines) < size.rows:
            lines = (*lines, *(("" for _ in range(size.rows - len(lines)))))
        styles = tuple(_resize_style_row(row, size.columns) for row in self.cell_styles[: size.rows])
        if len(styles) < size.rows:
            styles = (*styles, *(_empty_style_row(size.columns) for _ in range(size.rows - len(styles))))
        return FakeScreen(
            size=size,
            visible_lines=lines,
            cell_styles=styles,
            scrollback_lines=self.scrollback_lines,
            cursor_row=min(self.cursor_row, size.rows - 1),
            cursor_column=min(self.cursor_column, size.columns - 1),
            viewport_top=self.viewport_top,
            scroll_top=max(0, min(self.scroll_top, size.rows - 1)),
            scroll_bottom=None
            if self.scroll_bottom is None
            else max(0, min(self.scroll_bottom, size.rows - 1)),
            scrollback_cleared=self.scrollback_cleared,
            autowrap_pending=False,
            active_style=self.active_style,
        )

    def cell_style(self, *, row: int, column: int) -> FakeCellStyle:
        row = max(0, min(row, self.size.rows - 1))
        column = max(0, min(column, self.size.columns - 1))
        return self.cell_styles[row][column]

    def apply(self, operations: Sequence[TerminalOperation]) -> FakeScreen:
        screen = self
        for operation in operations:
            screen = screen._apply_one(operation)
        return screen

    def _apply_one(self, operation: TerminalOperation) -> FakeScreen:
        if operation.kind == "write":
            return self._write(operation.text)
        if operation.kind == "newline":
            return self._newline()
        if operation.kind == "carriage_return":
            return self._replace(cursor_column=0, autowrap_pending=False)
        if operation.kind == "clear_line":
            return self._set_line(self.cursor_row, "")._replace(autowrap_pending=False)
        if operation.kind == "clear_from_cursor":
            return self._clear_from_cursor()
        if operation.kind == "clear_screen":
            cleared = FakeScreen.empty(self.size)
            return cleared._replace(
                scrollback_lines=self.scrollback_lines,
                viewport_top=self.viewport_top,
                scrollback_cleared=self.scrollback_cleared,
            )
        if operation.kind == "clear_scrollback":
            return self._replace(
                scrollback_lines=(),
                viewport_top=0,
                scrollback_cleared=True,
            )
        if operation.kind == "set_scroll_region":
            top = max(0, min(0 if operation.row is None else operation.row, self.size.rows - 1))
            bottom = max(top, min(top if operation.bottom is None else operation.bottom, self.size.rows - 1))
            return self._replace(scroll_top=top, scroll_bottom=bottom, autowrap_pending=False)
        if operation.kind == "reset_scroll_region":
            return FakeScreen(
                size=self.size,
                visible_lines=self.visible_lines,
                cell_styles=self.cell_styles,
                scrollback_lines=self.scrollback_lines,
                cursor_row=self.cursor_row,
                cursor_column=self.cursor_column,
                viewport_top=self.viewport_top,
                scroll_top=0,
                scroll_bottom=None,
                scrollback_cleared=self.scrollback_cleared,
                autowrap_pending=False,
                active_style=self.active_style,
            )
        if operation.kind == "move_cursor":
            row = 0 if operation.row is None else operation.row
            column = 0 if operation.column is None else operation.column
            return self._replace(
                cursor_row=max(0, min(row, self.size.rows - 1)),
                cursor_column=max(0, min(column, self.size.columns - 1)),
                autowrap_pending=False,
            )
        if operation.kind == "move_relative":
            return self._replace(
                cursor_row=max(0, min(self.cursor_row + operation.lines, self.size.rows - 1)),
                autowrap_pending=False,
            )
        if operation.kind == "move_column":
            column = 0 if operation.column is None else operation.column
            return self._replace(cursor_column=max(0, min(column, self.size.columns - 1)), autowrap_pending=False)
        return self

    def _write(self, text: str) -> FakeScreen:
        screen = self
        index = 0
        while index < len(text):
            control = _extract_control_sequence(text, index)
            if control is not None:
                screen = screen._apply_control_sequence(control.code)
                index += control.length
                continue

            char = text[index]
            if char == "\r":
                screen = screen._replace(cursor_column=0, autowrap_pending=False)
            elif char == "\n":
                screen = screen._newline()
            else:
                if screen.autowrap_pending:
                    screen = screen._newline()
                column = max(0, min(screen.cursor_column, screen.size.columns - 1))
                next_column = column if column == screen.size.columns - 1 else column + 1
                screen = screen._set_cell(screen.cursor_row, column, char, screen.active_style)._replace(
                    cursor_column=next_column,
                    autowrap_pending=column == screen.size.columns - 1,
                )
            index += 1
        return screen

    def _apply_control_sequence(self, control: str) -> FakeScreen:
        if not control.startswith("\x1b[") or not control.endswith("m"):
            return self
        return self._replace(active_style=_apply_sgr_to_style(self.active_style, control))

    def _newline(self) -> FakeScreen:
        scroll_top, scroll_bottom = self._scroll_region_bounds()
        if scroll_top <= self.cursor_row >= scroll_bottom:
            return self._scroll_region_up(scroll_top, scroll_bottom)
        if self.cursor_row >= self.size.rows - 1:
            return FakeScreen(
                size=self.size,
                visible_lines=(*self.visible_lines[1:], ""),
                cell_styles=(*self.cell_styles[1:], _empty_style_row(self.size.columns)),
                scrollback_lines=(*self.scrollback_lines, self.visible_lines[0]),
                cursor_row=self.size.rows - 1,
                cursor_column=0,
                viewport_top=self.viewport_top + 1,
                scroll_top=self.scroll_top,
                scroll_bottom=self.scroll_bottom,
                scrollback_cleared=self.scrollback_cleared,
                autowrap_pending=False,
                active_style=self.active_style,
            )
        return self._replace(cursor_row=self.cursor_row + 1, cursor_column=0, autowrap_pending=False)

    def _scroll_region_bounds(self) -> tuple[int, int]:
        bottom = self.size.rows - 1 if self.scroll_bottom is None else self.scroll_bottom
        top = max(0, min(self.scroll_top, self.size.rows - 1))
        return top, max(top, min(bottom, self.size.rows - 1))

    def _scroll_region_up(self, top: int, bottom: int) -> FakeScreen:
        if top == 0 and bottom == self.size.rows - 1:
            return FakeScreen(
                size=self.size,
                visible_lines=(*self.visible_lines[1:], ""),
                cell_styles=(*self.cell_styles[1:], _empty_style_row(self.size.columns)),
                scrollback_lines=(*self.scrollback_lines, self.visible_lines[0]),
                cursor_row=bottom,
                cursor_column=0,
                viewport_top=self.viewport_top + 1,
                scroll_top=self.scroll_top,
                scroll_bottom=self.scroll_bottom,
                scrollback_cleared=self.scrollback_cleared,
                autowrap_pending=False,
                active_style=self.active_style,
            )
        lines = list(self.visible_lines)
        styles = list(self.cell_styles)
        for row in range(top, bottom):
            lines[row] = lines[row + 1]
            styles[row] = styles[row + 1]
        lines[bottom] = ""
        styles[bottom] = _empty_style_row(self.size.columns)
        return self._replace(
            visible_lines=tuple(lines),
            cell_styles=tuple(styles),
            cursor_row=bottom,
            cursor_column=0,
            autowrap_pending=False,
        )

    def _set_line(self, row: int, text: str) -> FakeScreen:
        lines = list(self.visible_lines)
        lines[row] = text[: self.size.columns]
        styles = list(self.cell_styles)
        styles[row] = _empty_style_row(self.size.columns)
        return self._replace(visible_lines=tuple(lines), cell_styles=tuple(styles))

    def _clear_from_cursor(self) -> FakeScreen:
        lines = list(self.visible_lines)
        styles = list(self.cell_styles)
        lines[self.cursor_row] = lines[self.cursor_row][
            : self.cursor_column
        ].rstrip()
        current_styles = list(styles[self.cursor_row])
        for column in range(self.cursor_column, self.size.columns):
            current_styles[column] = FakeCellStyle()
        styles[self.cursor_row] = tuple(current_styles)
        for row in range(self.cursor_row + 1, self.size.rows):
            lines[row] = ""
            styles[row] = _empty_style_row(self.size.columns)
        return self._replace(
            visible_lines=tuple(lines),
            cell_styles=tuple(styles),
            autowrap_pending=False,
        )

    def _set_cell(self, row: int, column: int, char: str, style: FakeCellStyle) -> FakeScreen:
        lines = list(self.visible_lines)
        padded = lines[row].ljust(self.size.columns)
        updated = f"{padded[:column]}{char}{padded[column + 1 :]}"
        lines[row] = updated[: self.size.columns].rstrip()
        styles = list(self.cell_styles)
        style_row = list(styles[row])
        style_row[column] = style
        styles[row] = tuple(style_row)
        return self._replace(visible_lines=tuple(lines), cell_styles=tuple(styles))

    def _replace(
        self,
        *,
        visible_lines: tuple[str, ...] | None = None,
        cell_styles: tuple[tuple[FakeCellStyle, ...], ...] | None = None,
        scrollback_lines: tuple[str, ...] | None = None,
        cursor_row: int | None = None,
        cursor_column: int | None = None,
        viewport_top: int | None = None,
        scroll_top: int | None = None,
        scroll_bottom: int | None = None,
        scrollback_cleared: bool | None = None,
        autowrap_pending: bool | None = None,
        active_style: FakeCellStyle | None = None,
    ) -> FakeScreen:
        return FakeScreen(
            size=self.size,
            visible_lines=self.visible_lines if visible_lines is None else visible_lines,
            cell_styles=self.cell_styles if cell_styles is None else cell_styles,
            scrollback_lines=self.scrollback_lines if scrollback_lines is None else scrollback_lines,
            cursor_row=self.cursor_row if cursor_row is None else cursor_row,
            cursor_column=self.cursor_column if cursor_column is None else cursor_column,
            viewport_top=self.viewport_top if viewport_top is None else viewport_top,
            scroll_top=self.scroll_top if scroll_top is None else scroll_top,
            scroll_bottom=self.scroll_bottom if scroll_bottom is None else scroll_bottom,
            scrollback_cleared=self.scrollback_cleared if scrollback_cleared is None else scrollback_cleared,
            autowrap_pending=self.autowrap_pending if autowrap_pending is None else autowrap_pending,
            active_style=self.active_style if active_style is None else active_style,
        )


def _empty_style_row(columns: int) -> tuple[FakeCellStyle, ...]:
    default = FakeCellStyle()
    return tuple(default for _ in range(columns))


def _resize_style_row(row: tuple[FakeCellStyle, ...], columns: int) -> tuple[FakeCellStyle, ...]:
    resized = row[:columns]
    if len(resized) < columns:
        resized = (*resized, *_empty_style_row(columns - len(resized)))
    return resized


def _apply_sgr_to_style(style: FakeCellStyle, control: str) -> FakeCellStyle:
    params = control[2:-1]
    if params == "":
        return FakeCellStyle()
    parts = params.split(";")
    index = 0
    updated = style
    while index < len(parts):
        try:
            code = int(parts[index] or "0")
        except ValueError:
            index += 1
            continue

        if code == 38:
            color, consumed = _parse_extended_color(parts[index:])
            updated = dataclass_replace(updated, foreground=color)
            index += consumed
            continue
        if code == 48:
            color, consumed = _parse_extended_color(parts[index:])
            updated = dataclass_replace(updated, background=color)
            index += consumed
            continue

        updated = _apply_sgr_code_to_style(updated, code)
        index += 1
    return updated


def _parse_extended_color(parts: list[str]) -> tuple[str | None, int]:
    if len(parts) >= 3 and parts[1] == "5":
        return ";".join(parts[:3]), 3
    if len(parts) >= 5 and parts[1] == "2":
        return ";".join(parts[:5]), 5
    return None, 1


def _apply_sgr_code_to_style(style: FakeCellStyle, code: int) -> FakeCellStyle:
    if code == 0:
        return FakeCellStyle()
    if code == 1:
        return dataclass_replace(style, bold=True)
    if code == 2:
        return dataclass_replace(style, dim=True)
    if code == 3:
        return dataclass_replace(style, italic=True)
    if code == 4:
        return dataclass_replace(style, underline=True)
    if code == 5:
        return dataclass_replace(style, blink=True)
    if code == 7:
        return dataclass_replace(style, reverse=True)
    if code == 8:
        return dataclass_replace(style, hidden=True)
    if code == 9:
        return dataclass_replace(style, strikethrough=True)
    if code == 21:
        return dataclass_replace(style, bold=False)
    if code == 22:
        return dataclass_replace(style, bold=False, dim=False)
    if code == 23:
        return dataclass_replace(style, italic=False)
    if code == 24:
        return dataclass_replace(style, underline=False)
    if code == 25:
        return dataclass_replace(style, blink=False)
    if code == 27:
        return dataclass_replace(style, reverse=False)
    if code == 28:
        return dataclass_replace(style, hidden=False)
    if code == 29:
        return dataclass_replace(style, strikethrough=False)
    if code == 39:
        return dataclass_replace(style, foreground=None)
    if code == 49:
        return dataclass_replace(style, background=None)
    if 30 <= code <= 37 or 90 <= code <= 97:
        return dataclass_replace(style, foreground=str(code))
    if 40 <= code <= 47 or 100 <= code <= 107:
        return dataclass_replace(style, background=str(code))
    return style


@dataclass(frozen=True, slots=True)
class TerminalFrame:
    size: TerminalSize
    operations: tuple[TerminalOperation, ...]
    serialized_output: str
    screen_before: FakeScreen
    screen_after: FakeScreen
    synchronized: bool
    clear_scrollback_emitted: bool


@runtime_checkable
class TerminalPort(Protocol):
    def size(self) -> TerminalSize: ...

    def flush(self, operations: Sequence[TerminalOperation]) -> TerminalFrame: ...


@dataclass(slots=True)
class TerminalProgressReporter:
    terminal: TerminalPort
    now_ms: Callable[[], int] = field(default_factory=lambda: _monotonic_ms)
    keepalive_interval_ms: int = 1_000
    active: bool = False
    last_sent_ms: int | None = None

    def set_active(self, active: bool) -> bool:
        if self.active == active and self.last_sent_ms is not None:
            return False
        self.active = active
        self._send(active)
        return True

    def keepalive(self) -> bool:
        if not self.active:
            return False
        now = self.now_ms()
        if self.last_sent_ms is not None and now - self.last_sent_ms < self.keepalive_interval_ms:
            return False
        self._send(True, now_ms=now)
        return True

    def stop(self) -> bool:
        return self.set_active(False)

    def _send(self, active: bool, *, now_ms: int | None = None) -> None:
        sent_at = self.now_ms() if now_ms is None else now_ms
        self.terminal.flush((TerminalOperation.set_progress(active),))
        self.last_sent_ms = sent_at


class FakeTerminalPort:
    def __init__(
        self,
        *,
        size: TerminalSize | None = None,
        flush_history_limit: int | None = None,
        frame_history_limit: int | None = None,
    ) -> None:
        self._size = size or TerminalSize(columns=80, rows=24)
        self.screen = FakeScreen.empty(self._size)
        self.flushes: tuple[tuple[TerminalOperation, ...], ...] = ()
        self.failed_flushes: tuple[tuple[TerminalOperation, ...], ...] = ()
        self.frames: tuple[TerminalFrame, ...] = ()
        self.flush_history_limit = flush_history_limit
        self.frame_history_limit = frame_history_limit
        self._next_flush_error: BaseException | None = None

    def size(self) -> TerminalSize:
        return self._size

    def resize(self, size: TerminalSize) -> None:
        self._size = size
        self.screen = self.screen.resized(size)

    def fail_next_flush(self, error: BaseException) -> None:
        self._next_flush_error = error

    def flush(self, operations: Sequence[TerminalOperation]) -> TerminalFrame:
        operation_tuple = tuple(operations)
        if self._next_flush_error is not None:
            error = self._next_flush_error
            self._next_flush_error = None
            self.failed_flushes = _append_history(self.failed_flushes, operation_tuple, self.flush_history_limit)
            raise error
        screen_before = self.screen
        screen_after = screen_before.apply(operation_tuple)
        frame = TerminalFrame(
            size=self._size,
            operations=operation_tuple,
            serialized_output="".join(operation.serialize() for operation in operation_tuple),
            screen_before=screen_before,
            screen_after=screen_after,
            synchronized=_is_synchronized_frame(operation_tuple),
            clear_scrollback_emitted=any(operation.kind == "clear_scrollback" for operation in operation_tuple),
        )
        self.screen = screen_after
        self.flushes = _append_history(self.flushes, operation_tuple, self.flush_history_limit)
        self.frames = _append_history(self.frames, frame, self.frame_history_limit)
        return frame


def _is_synchronized_frame(operations: tuple[TerminalOperation, ...]) -> bool:
    begin_index: int | None = None
    for index, operation in enumerate(operations):
        if operation.kind == "begin_synchronized_update":
            begin_index = index
            break
    if begin_index is None:
        return False
    return any(operation.kind == "end_synchronized_update" for operation in operations[begin_index + 1 :])


class ProcessTerminalPort:
    def __init__(
        self,
        *,
        output: TextIO,
        size_provider: Callable[[], TerminalSize],
        fallback_size: TerminalSize | None = None,
        frame_history_limit: int | None = 1,
        track_screen: bool = True,
        write_log_path: str | Path | None = None,
    ) -> None:
        self._output = output
        self._size_provider = size_provider
        self._fallback_size = fallback_size or TerminalSize(columns=80, rows=24)
        self.track_screen = track_screen
        self.screen = FakeScreen.empty(self.size())
        self.frames: tuple[TerminalFrame, ...] = ()
        self.frame_history_limit = frame_history_limit
        self._write_log_path = _write_log_path(write_log_path)

    def size(self) -> TerminalSize:
        try:
            return self._size_provider()
        except Exception:
            return terminal_size_from_environment(default=self._fallback_size)

    def flush(self, operations: Sequence[TerminalOperation]) -> TerminalFrame:
        operation_tuple = tuple(operations)
        size = self.size()
        if self.track_screen and self.screen.size != size:
            self.screen = self.screen.resized(size)
        screen_before = self.screen
        serialized_output = "".join(operation.serialize() for operation in operation_tuple)
        self._output.write(serialized_output)
        self._output.flush()
        self._append_write_log(serialized_output)
        screen_after = screen_before.apply(operation_tuple) if self.track_screen else screen_before
        frame = TerminalFrame(
            size=size,
            operations=operation_tuple,
            serialized_output=serialized_output,
            screen_before=screen_before,
            screen_after=screen_after,
            synchronized=_is_synchronized_frame(operation_tuple),
            clear_scrollback_emitted=any(operation.kind == "clear_scrollback" for operation in operation_tuple),
        )
        if self.track_screen:
            self.screen = screen_after
        self.frames = _append_history(self.frames, frame, self.frame_history_limit)
        return frame

    def _append_write_log(self, text: str) -> None:
        if not text or self._write_log_path is None:
            return
        with self._write_log_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(text)


def _write_log_path(write_log_path: str | Path | None) -> Path | None:
    if write_log_path is not None:
        return Path(write_log_path)
    raw = os.environ.get("PI_TUI_WRITE_LOG") or os.environ.get("LOUSHANG_TUI_WRITE_LOG")
    return Path(raw) if raw else None


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def _append_history(history: tuple[T, ...], item: T, limit: int | None) -> tuple[T, ...]:
    if limit is None:
        return (*history, item)
    limit = max(0, limit)
    if limit == 0:
        return ()
    return (*history, item)[-limit:]


def terminal_size_from_environment(*, default: TerminalSize | None = None) -> TerminalSize:
    default = default or TerminalSize(columns=80, rows=24)
    return TerminalSize(
        columns=_positive_env_int("COLUMNS", default.columns),
        rows=_positive_env_int("LINES", default.rows),
    )


def _positive_env_int(name: str, fallback: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return fallback
    return value if value > 0 else fallback
