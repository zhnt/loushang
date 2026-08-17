from __future__ import annotations

import os
import re
from dataclasses import InitVar, dataclass, field
from typing import Literal, Protocol, cast

from loushang.tui.framework import SurfaceHost
from loushang.tui.keybindings import KeybindingManager, normalize_key_id
from loushang.tui.ui_parts import Composer

InputEventKind = Literal["key", "text", "paste", "resize", "focus", "mouse", "signal"]
InputIntentKind = Literal[
    "submit",
    "follow_up",
    "steer",
    "abort",
    "surface_close",
    "invalidate_render",
    "select",
    "complete",
    "command",
    "setting",
    "approve",
    "approve_session",
    "approval_decision",
    "permission_profile_action",
    "reject",
    "dialog_confirm",
    "dialog_cancel",
    "question_submit",
    "question_cancel",
    "command_select",
    "command_cancel",
    "consumed",
]
SubmitMode = Literal["submit", "follow_up", "steer"]
KeyEventType = Literal["press", "repeat", "release"]

ESC = "\x1b"
BRACKETED_PASTE_START = "\x1b[200~"
BRACKETED_PASTE_END = "\x1b[201~"
CSI_U_CTRL_LETTER_IN_PASTE_RE = re.compile(r"\x1b\[(\d+);5u")

_MOD_SHIFT = 1
_MOD_ALT = 2
_MOD_CTRL = 4
_MOD_SUPER = 8
_LOCK_MASK = 64 + 128
_SYMBOL_KEYS = set("`-=[]\\;',./!@#$%^&*()_+|~{}:<>?")

_ARROW_CODEPOINTS = {"A": ("up", -1), "B": ("down", -2), "C": ("right", -3), "D": ("left", -4)}
_FUNCTIONAL_CODEPOINTS = {
    2: "insert",
    3: "delete",
    5: "pageUp",
    6: "pageDown",
    7: "home",
    8: "end",
    11: "f1",
    12: "f2",
    13: "f3",
    14: "f4",
    15: "f5",
    17: "f6",
    18: "f7",
    19: "f8",
    20: "f9",
    21: "f10",
    23: "f11",
    24: "f12",
}
_FUNCTIONAL_NAME_CODEPOINTS = {
    "delete": -10,
    "insert": -11,
    "pageUp": -12,
    "pageDown": -13,
    "home": -14,
    "end": -15,
    "clear": -16,
    "f1": -17,
    "f2": -18,
    "f3": -19,
    "f4": -20,
    "f5": -21,
    "f6": -22,
    "f7": -23,
    "f8": -24,
    "f9": -25,
    "f10": -26,
    "f11": -27,
    "f12": -28,
}
_KITTY_FUNCTIONAL_EQUIVALENTS = {
    57399: 48,
    57400: 49,
    57401: 50,
    57402: 51,
    57403: 52,
    57404: 53,
    57405: 54,
    57406: 55,
    57407: 56,
    57408: 57,
    57409: 46,
    57410: 47,
    57411: 42,
    57412: 45,
    57413: 43,
    57414: 13,
    57415: 61,
    57416: 44,
    57417: -4,
    57418: -3,
    57419: -1,
    57420: -2,
    57421: -12,
    57422: -13,
    57423: -14,
    57424: -15,
    57425: -11,
    57426: -10,
}
_NEGATIVE_FUNCTIONAL_CODEPOINTS = {
    -1: "up",
    -2: "down",
    -3: "right",
    -4: "left",
    -10: "delete",
    -11: "insert",
    -12: "pageUp",
    -13: "pageDown",
    -14: "home",
    -15: "end",
    -16: "clear",
    -17: "f1",
    -18: "f2",
    -19: "f3",
    -20: "f4",
    -21: "f5",
    -22: "f6",
    -23: "f7",
    -24: "f8",
    -25: "f9",
    -26: "f10",
    -27: "f11",
    -28: "f12",
}
_LEGACY_KEY_SEQUENCES = {
    "\x1b[A": "up",
    "\x1bOA": "up",
    "\x1b[B": "down",
    "\x1bOB": "down",
    "\x1b[C": "right",
    "\x1bOC": "right",
    "\x1b[D": "left",
    "\x1bOD": "left",
    "\x1b[H": "home",
    "\x1bOH": "home",
    "\x1b[1~": "home",
    "\x1b[7~": "home",
    "\x1b[F": "end",
    "\x1bOF": "end",
    "\x1b[4~": "end",
    "\x1b[8~": "end",
    "\x1b[2~": "insert",
    "\x1b[3~": "delete",
    "\x1b[5~": "pageUp",
    "\x1b[[5~": "pageUp",
    "\x1b[6~": "pageDown",
    "\x1b[[6~": "pageDown",
    "\x1b[E": "clear",
    "\x1bOE": "clear",
    "\x1b[e": "shift+clear",
    "\x1bOe": "ctrl+clear",
    "\x1bOP": "f1",
    "\x1bOQ": "f2",
    "\x1bOR": "f3",
    "\x1bOS": "f4",
    "\x1b[11~": "f1",
    "\x1b[12~": "f2",
    "\x1b[13~": "f3",
    "\x1b[14~": "f4",
    "\x1b[15~": "f5",
    "\x1b[17~": "f6",
    "\x1b[18~": "f7",
    "\x1b[19~": "f8",
    "\x1b[20~": "f9",
    "\x1b[21~": "f10",
    "\x1b[23~": "f11",
    "\x1b[24~": "f12",
    "\x1b[[A": "f1",
    "\x1b[[B": "f2",
    "\x1b[[C": "f3",
    "\x1b[[D": "f4",
    "\x1b[[E": "f5",
    "\x1b[Z": "shift+tab",
    "\x1b[a": "shift+up",
    "\x1b[b": "shift+down",
    "\x1b[c": "shift+right",
    "\x1b[d": "shift+left",
    "\x1bOa": "ctrl+up",
    "\x1bOb": "ctrl+down",
    "\x1bOc": "ctrl+right",
    "\x1bOd": "ctrl+left",
    "\x1b[1;3A": "alt+up",
    "\x1b[1;3B": "alt+down",
    "\x1b[1;3C": "alt+right",
    "\x1b[1;3D": "alt+left",
    "\x1bp": "alt+up",
    "\x1bn": "alt+down",
    "\x1bf": "alt+right",
    "\x1bb": "alt+left",
    "\x1by": "alt+y",
    "\x1b\r": "alt+enter",
}
_ALT_WRAPPED_LEGACY_KEY_SEQUENCES = {
    "\x1b\x1b[A": "alt+up",
    "\x1b\x1bOA": "alt+up",
    "\x1b\x1b[B": "alt+down",
    "\x1b\x1bOB": "alt+down",
    "\x1b\x1b[C": "alt+right",
    "\x1b\x1bOC": "alt+right",
    "\x1b\x1b[D": "alt+left",
    "\x1b\x1bOD": "alt+left",
}
_CONTROL_KEY_MAP = {
    "\x00": "ctrl+space",
    "\x01": "ctrl+a",
    "\x02": "ctrl+b",
    "\x03": "ctrl+c",
    "\x04": "ctrl+d",
    "\x05": "ctrl+e",
    "\x06": "ctrl+f",
    "\x07": "ctrl+g",
    "\x08": "backspace",
    "\x09": "tab",
    "\x0a": "ctrl+j",
    "\x0b": "ctrl+k",
    "\x0f": "ctrl+o",
    "\x0d": "enter",
    "\x15": "ctrl+u",
    "\x16": "ctrl+v",
    "\x17": "ctrl+w",
    "\x19": "ctrl+y",
    "\x1d": "ctrl+]",
    "\x1f": "ctrl+-",
    "\x7f": "backspace",
}
_ALT_CONTROL_KEY_MAP = {
    control: f"ctrl+alt+{key.removeprefix('ctrl+')}" if key.startswith("ctrl+") else f"alt+{key}"
    for control, key in _CONTROL_KEY_MAP.items()
}
_ALT_CONTROL_KEY_MAP["\x08"] = "alt+backspace"
_ALT_CONTROL_KEY_MAP["\x7f"] = "alt+backspace"


@dataclass(frozen=True, slots=True, eq=False)
class InputEvent:
    kind: InputEventKind
    text: str = ""
    key: str = ""
    columns: int = 0
    rows: int = 0
    signal: str = ""
    raw: str = ""
    event_type: KeyEventType = "press"
    focused: bool | None = None
    mouse_button: int | None = None
    mouse_column: int | None = None
    mouse_row: int | None = None
    mouse_action: str = ""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, InputEvent):
            return False
        return (
            self.kind == other.kind
            and self.text == other.text
            and self.key == other.key
            and self.columns == other.columns
            and self.rows == other.rows
            and self.signal == other.signal
            and self.event_type == other.event_type
            and self.focused == other.focused
            and self.mouse_button == other.mouse_button
            and self.mouse_column == other.mouse_column
            and self.mouse_row == other.mouse_row
            and self.mouse_action == other.mouse_action
            and (self.raw == other.raw or not other.raw)
        )


@dataclass(frozen=True, slots=True)
class InputIntent:
    kind: InputIntentKind
    text: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class InputBatch:
    app_events: tuple[InputEvent, ...] = ()
    control_events: tuple[InputEvent, ...] = ()
    has_pending: bool = False


class EditorInputTarget(Protocol):
    def insert_text(self, text: str) -> None: ...

    def paste(self, text: str) -> None: ...

    def move_left(self) -> None: ...

    def move_right(self) -> None: ...

    def move_word_left(self) -> None: ...

    def move_word_right(self) -> None: ...

    def move_to_line_start(self) -> None: ...

    def move_to_line_end(self) -> None: ...

    def select_char_left(self) -> None: ...

    def select_char_right(self) -> None: ...

    def select_word_left(self) -> None: ...

    def select_word_right(self) -> None: ...

    def select_line_start(self) -> None: ...

    def select_line_end(self) -> None: ...

    def delete_backward(self) -> None: ...

    def delete_forward(self) -> None: ...

    def delete_word_backward(self) -> None: ...

    def delete_word_forward(self) -> None: ...

    def kill_to_line_start(self) -> None: ...

    def kill_to_line_end(self) -> None: ...

    def yank(self) -> None: ...

    def yank_pop(self) -> None: ...

    def undo(self) -> None: ...

    def redo(self) -> None: ...


class PromptInputTarget(EditorInputTarget, Protocol):
    @property
    def value(self) -> str: ...

    @property
    def browsing_history(self) -> bool: ...

    @property
    def has_completions(self) -> bool: ...

    def clear(self) -> None: ...

    def add_history(self, text: str) -> None: ...

    def insert_newline(self) -> None: ...

    def history_previous(self) -> None: ...

    def history_next(self) -> None: ...

    def move_visual_up(self, *, width: int) -> bool: ...

    def move_visual_down(self, *, width: int) -> bool: ...

    def move_visual_page_up(self, *, width: int, visible_lines: int) -> None: ...

    def move_visual_page_down(self, *, width: int, visible_lines: int) -> None: ...

    def jump_to_char(self, text: str, *, direction: Literal["forward", "backward"]) -> None: ...

    def refresh_completions(self, *, force: bool = False, explicit: bool = False) -> None: ...

    def apply_selected_completion(self) -> None: ...

    def select_previous_completion(self) -> None: ...

    def select_next_completion(self) -> None: ...

    def clear_completion_items(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ComposerInputTarget:
    composer: Composer

    @property
    def value(self) -> str:
        return self.composer.value

    @property
    def browsing_history(self) -> bool:
        return self.composer.browsing_history

    @property
    def has_completions(self) -> bool:
        return self.composer.has_completions

    def insert_text(self, text: str) -> None:
        self.composer.insert_text(text)

    def paste(self, text: str) -> None:
        self.composer.paste(text)

    def move_left(self) -> None:
        self.composer.move_left()

    def move_right(self) -> None:
        self.composer.move_right()

    def move_word_left(self) -> None:
        self.composer.move_word_left()

    def move_word_right(self) -> None:
        self.composer.move_word_right()

    def move_to_line_start(self) -> None:
        self.composer.move_to_line_start()

    def move_to_line_end(self) -> None:
        self.composer.move_to_line_end()

    def select_char_left(self) -> None:
        self.composer.select_char_left()

    def select_char_right(self) -> None:
        self.composer.select_char_right()

    def select_word_left(self) -> None:
        self.composer.select_word_left()

    def select_word_right(self) -> None:
        self.composer.select_word_right()

    def select_line_start(self) -> None:
        self.composer.select_line_start()

    def select_line_end(self) -> None:
        self.composer.select_line_end()

    def delete_backward(self) -> None:
        self.composer.delete_backward()

    def delete_forward(self) -> None:
        self.composer.delete_forward()

    def delete_word_backward(self) -> None:
        self.composer.delete_word_backward()

    def delete_word_forward(self) -> None:
        self.composer.delete_word_forward()

    def kill_to_line_start(self) -> None:
        self.composer.kill_to_line_start()

    def kill_to_line_end(self) -> None:
        self.composer.kill_to_line_end()

    def yank(self) -> None:
        self.composer.yank()

    def yank_pop(self) -> None:
        self.composer.yank_pop()

    def undo(self) -> None:
        self.composer.undo()

    def redo(self) -> None:
        self.composer.redo()

    def clear(self) -> None:
        self.composer.clear()

    def add_history(self, text: str) -> None:
        self.composer.add_history(text)

    def insert_newline(self) -> None:
        self.composer.insert_newline()

    def history_previous(self) -> None:
        self.composer.history_previous()

    def history_next(self) -> None:
        self.composer.history_next()

    def move_visual_up(self, *, width: int) -> bool:
        return self.composer.move_visual_up(width=width)

    def move_visual_down(self, *, width: int) -> bool:
        return self.composer.move_visual_down(width=width)

    def move_visual_page_up(self, *, width: int, visible_lines: int) -> None:
        self.composer.move_visual_page_up(width=width, visible_lines=visible_lines)

    def move_visual_page_down(self, *, width: int, visible_lines: int) -> None:
        self.composer.move_visual_page_down(width=width, visible_lines=visible_lines)

    def jump_to_char(self, text: str, *, direction: Literal["forward", "backward"]) -> None:
        self.composer.jump_to_char(text, direction=direction)

    def refresh_completions(self, *, force: bool = False, explicit: bool = False) -> None:
        self.composer.refresh_completions(force=force, explicit=explicit)

    def apply_selected_completion(self) -> None:
        self.composer.apply_selected_completion()

    def select_previous_completion(self) -> None:
        self.composer.select_previous_completion()

    def select_next_completion(self) -> None:
        self.composer.select_next_completion()

    def clear_completion_items(self) -> None:
        self.composer.clear_completion_items()


@dataclass(slots=True)
class InputReader:
    _buffer: str = ""
    _paste_buffer: str = ""
    _in_paste: bool = False
    _pending_kitty_printable_codepoint: int | None = None

    def feed(self, data: str) -> tuple[InputEvent, ...]:
        return self._feed_events(data)

    def feed_batch(self, data: str) -> InputBatch:
        return _input_batch(self._feed_events(data), has_pending=self.has_pending)

    @property
    def has_pending(self) -> bool:
        return bool(self._buffer or self._in_paste or self._paste_buffer)

    def flush_pending_batch(self) -> InputBatch:
        return _input_batch(self._flush_events(), has_pending=self.has_pending)

    def _feed_events(self, data: str) -> tuple[InputEvent, ...]:
        self._buffer += data
        events: list[InputEvent] = []
        while self._buffer:
            if self._in_paste:
                end_index = self._buffer.find(BRACKETED_PASTE_END)
                if end_index == -1:
                    payload, pending_end_marker = _split_paste_payload_and_pending_end_marker(self._buffer)
                    self._paste_buffer += payload
                    self._buffer = pending_end_marker
                    break
                self._paste_buffer += self._buffer[:end_index]
                events.append(InputEvent(kind="paste", text=sanitize_paste_text(self._paste_buffer)))
                self._buffer = self._buffer[end_index + len(BRACKETED_PASTE_END) :]
                self._paste_buffer = ""
                self._in_paste = False
                self._pending_kitty_printable_codepoint = None
                continue

            paste_start = self._buffer.find(BRACKETED_PASTE_START)
            if paste_start == 0:
                self._buffer = self._buffer[len(BRACKETED_PASTE_START) :]
                self._in_paste = True
                self._paste_buffer = ""
                self._pending_kitty_printable_codepoint = None
                continue

            parse_source = self._buffer if paste_start == -1 else self._buffer[:paste_start]
            sequences, remainder = _extract_complete_sequences(parse_source)
            events.extend(self._events_from_sequences(sequences))
            if paste_start == -1:
                self._buffer = remainder
                break
            self._buffer = remainder + self._buffer[paste_start:]
            if remainder:
                break
        return _coalesce_text_events(events)

    def flush(self) -> tuple[InputEvent, ...]:
        return self._flush_events()

    def _flush_events(self) -> tuple[InputEvent, ...]:
        if self._in_paste:
            return ()
        if not self._buffer:
            return ()
        buffer = self._buffer
        self._buffer = ""
        return _coalesce_text_events(self._events_from_sequences((buffer,)))

    def resize(self, *, columns: int, rows: int) -> InputEvent:
        return InputEvent(kind="resize", columns=columns, rows=rows)

    def signal(self, signal: str) -> InputEvent:
        return InputEvent(kind="signal", signal=signal)

    def _events_from_sequences(self, sequences: tuple[str, ...]) -> list[InputEvent]:
        events: list[InputEvent] = []
        for sequence in sequences:
            event = self._event_from_sequence(sequence)
            if event is not None:
                events.append(event)
        return events

    def _event_from_sequence(self, sequence: str) -> InputEvent | None:
        if not sequence:
            return None
        if sequence == ESC:
            self._pending_kitty_printable_codepoint = None
            return InputEvent(kind="key", key="escape", raw=sequence)
        if len(sequence) == 1:
            codepoint = ord(sequence)
            if self._pending_kitty_printable_codepoint == codepoint:
                self._pending_kitty_printable_codepoint = None
                return None
            self._pending_kitty_printable_codepoint = None
            if sequence in _CONTROL_KEY_MAP:
                if sequence == "\x08" and _is_windows_terminal_session():
                    return InputEvent(kind="key", key="ctrl+backspace", raw=sequence)
                return InputEvent(kind="key", key=_CONTROL_KEY_MAP[sequence], raw=sequence)
            return InputEvent(kind="text", text=sequence)

        focus = _parse_focus_sequence(sequence)
        if focus is not None:
            self._pending_kitty_printable_codepoint = None
            return InputEvent(kind="focus", focused=focus, raw=sequence)

        alt_wrapped = _ALT_WRAPPED_LEGACY_KEY_SEQUENCES.get(sequence)
        if alt_wrapped is not None:
            self._pending_kitty_printable_codepoint = None
            return InputEvent(kind="key", key=alt_wrapped, raw=sequence)

        mouse = _parse_mouse_sequence(sequence)
        if mouse is not None:
            button, column, row, action = mouse
            self._pending_kitty_printable_codepoint = None
            return InputEvent(
                kind="mouse",
                mouse_button=button,
                mouse_column=column,
                mouse_row=row,
                mouse_action=action,
                raw=sequence,
            )

        kitty_response = _parse_kitty_protocol_response(sequence)
        if kitty_response is not None:
            self._pending_kitty_printable_codepoint = None
            return InputEvent(kind="signal", signal="kitty_protocol", text=kitty_response, raw=sequence)

        cell_size = _parse_cell_size_response(sequence)
        if cell_size is not None:
            self._pending_kitty_printable_codepoint = None
            return InputEvent(kind="signal", signal="cell_size", text=cell_size, raw=sequence)

        terminal_response = _parse_terminal_control_response(sequence)
        if terminal_response is not None:
            signal, text = terminal_response
            self._pending_kitty_printable_codepoint = None
            return InputEvent(kind="signal", signal=signal, text=text, raw=sequence)

        parsed = _parse_key_sequence(sequence)
        if parsed is not None:
            key, event_type = parsed
            printable_text = _kitty_printable_text(sequence)
            if printable_text is not None:
                self._pending_kitty_printable_codepoint = ord(printable_text)
                return InputEvent(kind="text", text=printable_text, raw=sequence)
            self._pending_kitty_printable_codepoint = None
            return InputEvent(kind="key", key=key, raw=sequence, event_type=event_type)

        alt_control = _parse_alt_control_sequence(sequence)
        if alt_control is not None:
            self._pending_kitty_printable_codepoint = None
            return InputEvent(kind="key", key=alt_control, raw=sequence)

        if sequence.startswith(ESC) and len(sequence) == 2:
            return InputEvent(kind="key", key=f"alt+{sequence[1]}", raw=sequence)
        return InputEvent(kind="text", text=sequence)


@dataclass(frozen=True, slots=True)
class _SurfaceRoute:
    intents: tuple[InputIntent, ...] = ()
    consumed: bool = False


@dataclass(slots=True)
class InputRouter:
    composer: Composer | None = None
    surface_host: SurfaceHost | None = None
    running: bool = False
    steering_supported: bool = False
    width: int = 80
    height: int = 24
    keybindings: KeybindingManager | None = None
    _jump_mode: Literal["forward", "backward"] | None = None
    target: InitVar[PromptInputTarget | None] = None
    _target: PromptInputTarget = field(init=False, repr=False)

    def __post_init__(self, target: PromptInputTarget | None) -> None:
        if self.composer is not None and target is not None:
            raise TypeError("InputRouter accepts composer or target, not both")
        if target is not None:
            self._target = target
            return
        if self.composer is not None:
            self._target = ComposerInputTarget(self.composer)
            return
        raise TypeError("InputRouter requires composer or target")

    def route(self, event: InputEvent) -> tuple[InputIntent, ...]:
        target = self._target
        if event.kind == "key" and event.event_type == "release":
            return ()
        if event.kind == "key":
            if self._jump_mode is not None:
                keybindings = self._keybindings()
                if keybindings.matches(event.key, "tui.editor.jumpForward") or keybindings.matches(
                    event.key,
                    "tui.editor.jumpBackward",
                ):
                    self._jump_mode = None
                    return ()
                self._jump_mode = None
            keybindings = self._keybindings()
            surface_route = self._route_surface_first(event)
            if surface_route.intents:
                return surface_route.intents
            if surface_route.consumed:
                return ()
            focused_target = self._focused_editor_target()
            if focused_target is not None:
                if route_editor_selection_key(focused_target, event.key, keybindings=keybindings):
                    return ()
                if route_editor_editing_key(focused_target, event.key, keybindings=keybindings):
                    return ()
                return ()
            if route_editor_selection_key(target, event.key, keybindings=keybindings):
                return ()
            if target.has_completions and route_prompt_completion_key(target, event.key, keybindings=keybindings):
                return ()
            if keybindings.matches(event.key, "tui.select.cancel") and self.running:
                return (InputIntent(kind="abort"),)
            if keybindings.matches(event.key, "tui.editor.jumpForward"):
                self._jump_mode = "forward"
                return ()
            if keybindings.matches(event.key, "tui.editor.jumpBackward"):
                self._jump_mode = "backward"
                return ()
            if keybindings.matches(event.key, "tui.queue.editLast"):
                return (InputIntent(kind="command", note="edit_last_queued_prompt"),)
            if keybindings.matches(event.key, "tui.input.tab"):
                target.refresh_completions(force=True, explicit=True)
                if target.has_completions:
                    target.apply_selected_completion()
                return ()
            if keybindings.matches(event.key, "tui.input.submit"):
                return self.submit()
            if keybindings.matches(event.key, "tui.input.newLine"):
                target.insert_newline()
                return ()
            if keybindings.matches(event.key, "tui.editor.cursorUp"):
                self._move_up_or_history()
                return ()
            if keybindings.matches(event.key, "tui.editor.cursorDown"):
                self._move_down_or_history()
                return ()
            if keybindings.matches(event.key, "tui.editor.pageUp"):
                target.move_visual_page_up(width=self.width, visible_lines=self._composer_page_lines())
                return ()
            if keybindings.matches(event.key, "tui.editor.pageDown"):
                target.move_visual_page_down(width=self.width, visible_lines=self._composer_page_lines())
                return ()
            if route_editor_editing_key(target, event.key, keybindings=keybindings):
                return ()
        if event.kind == "paste":
            self._jump_mode = None
            surface_route = self._route_surface_first(event)
            if surface_route.intents:
                return surface_route.intents
            if surface_route.consumed:
                return ()
            focused_target = self._focused_editor_target()
            if focused_target is not None:
                focused_target.paste(event.text)
                return ()
            target.paste(event.text)
            return ()
        if event.kind == "text":
            if self._jump_mode is not None:
                target.jump_to_char(event.text, direction=self._jump_mode)
                self._jump_mode = None
                return ()
            surface_route = self._route_surface_first(event)
            if surface_route.intents:
                return surface_route.intents
            if surface_route.consumed:
                return ()
            focused_target = self._focused_editor_target()
            if focused_target is not None:
                focused_target.insert_text(event.text)
                return ()
            target.insert_text(event.text)
            return ()
        if event.kind == "resize" or (event.kind == "signal" and event.signal == "sigwinch"):
            return (InputIntent(kind="invalidate_render"),)
        return ()

    def submit(self, *, mode: SubmitMode = "submit") -> tuple[InputIntent, ...]:
        target = self._target
        text = target.value
        if not text:
            return ()
        target.add_history(text)
        target.clear()
        if not self.running:
            return (InputIntent(kind="submit", text=text),)
        if mode == "steer":
            if self.steering_supported:
                return (InputIntent(kind="steer", text=text),)
            return (InputIntent(kind="follow_up", text=text, note="steer_unavailable"),)
        return (InputIntent(kind="follow_up", text=text),)

    def _route_surface_first(self, event: InputEvent) -> _SurfaceRoute:
        if self.surface_host is None:
            return _SurfaceRoute()
        route_input_result = getattr(self.surface_host, "route_input_result", None)
        if callable(route_input_result):
            result = route_input_result(_legacy_event(event))
            return _SurfaceRoute(
                intents=_input_intents(getattr(result, "intents", None)),
                consumed=bool(getattr(result, "consumed", False)),
            )
        route_input = getattr(self.surface_host, "route_input", None)
        if callable(route_input):
            result = route_input(_legacy_event(event))
        else:
            result = self.surface_host.handle_input(_legacy_event(event))
        return _SurfaceRoute(intents=_input_intents(result), consumed=_input_result_consumed(result))

    def _focused_editor_target(self) -> EditorInputTarget | None:
        if self.surface_host is None:
            return None
        current = getattr(self.surface_host, "current_editor_target", None)
        if not callable(current):
            return None
        target = current()
        return cast(EditorInputTarget, target) if target is not None else None

    def _move_up_or_history(self) -> None:
        target = self._target
        if target.browsing_history:
            target.history_previous()
        elif not target.value or not target.move_visual_up(width=self.width):
            target.history_previous()

    def _move_down_or_history(self) -> None:
        target = self._target
        if target.browsing_history:
            target.history_next()
        elif not target.value or not target.move_visual_down(width=self.width):
            target.history_next()

    def _keybindings(self) -> KeybindingManager:
        if self.keybindings is None:
            self.keybindings = KeybindingManager()
        return self.keybindings

    def _composer_page_lines(self) -> int:
        return max(2, min(10, self.height))


def _input_intents(result: object) -> tuple[InputIntent, ...]:
    if result is None:
        return ()
    if isinstance(result, InputIntent):
        return (result,)
    if isinstance(result, tuple):
        return tuple(item for item in result if isinstance(item, InputIntent))
    return ()


def _input_result_consumed(result: object) -> bool:
    if isinstance(result, bool):
        return result
    if result is None:
        return False
    if isinstance(result, tuple):
        return bool(result)
    return True


def sanitize_paste_text(text: str) -> str:
    text = _decode_csi_u_control_letters_in_paste(text)
    output: list[str] = []
    for char in text:
        if char == "\x1b":
            output.append("^[")
        elif char == "\t" or char == "\n" or char == "\r":
            output.append(char)
        elif ord(char) < 32:
            continue
        else:
            output.append(char)
    return "".join(output)


def _decode_csi_u_control_letters_in_paste(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        codepoint = int(match.group(1))
        if 97 <= codepoint <= 122:
            return chr(codepoint - 96)
        if 65 <= codepoint <= 90:
            return chr(codepoint - 64)
        return match.group(0)

    return CSI_U_CTRL_LETTER_IN_PASTE_RE.sub(replace, text)


def _split_paste_payload_and_pending_end_marker(text: str) -> tuple[str, str]:
    max_prefix_length = min(len(text), len(BRACKETED_PASTE_END) - 1)
    for length in range(max_prefix_length, 0, -1):
        suffix = text[-length:]
        if BRACKETED_PASTE_END.startswith(suffix):
            return text[:-length], suffix
    return text, ""


def route_editor_editing_key(
    target: EditorInputTarget,
    key: str,
    *,
    keybindings: KeybindingManager | None = None,
) -> bool:
    keybindings = keybindings or KeybindingManager()
    if keybindings.matches(key, "tui.editor.cursorLeft"):
        target.move_left()
        return True
    if keybindings.matches(key, "tui.editor.cursorRight"):
        target.move_right()
        return True
    if keybindings.matches(key, "tui.editor.cursorWordLeft"):
        target.move_word_left()
        return True
    if keybindings.matches(key, "tui.editor.cursorWordRight"):
        target.move_word_right()
        return True
    if keybindings.matches(key, "tui.editor.deleteCharBackward"):
        target.delete_backward()
        return True
    if keybindings.matches(key, "tui.editor.deleteCharForward"):
        target.delete_forward()
        return True
    if keybindings.matches(key, "tui.editor.cursorLineStart"):
        target.move_to_line_start()
        return True
    if keybindings.matches(key, "tui.editor.cursorLineEnd"):
        target.move_to_line_end()
        return True
    if keybindings.matches(key, "tui.editor.deleteToLineEnd"):
        target.kill_to_line_end()
        return True
    if keybindings.matches(key, "tui.editor.deleteToLineStart"):
        target.kill_to_line_start()
        return True
    if keybindings.matches(key, "tui.editor.deleteWordBackward"):
        target.delete_word_backward()
        return True
    if keybindings.matches(key, "tui.editor.deleteWordForward"):
        target.delete_word_forward()
        return True
    if keybindings.matches(key, "tui.editor.yank"):
        target.yank()
        return True
    if keybindings.matches(key, "tui.editor.yankPop"):
        target.yank_pop()
        return True
    if keybindings.matches(key, "tui.editor.undo"):
        target.undo()
        return True
    if keybindings.matches(key, "tui.editor.redo"):
        target.redo()
        return True
    return False


def route_editor_selection_key(
    target: EditorInputTarget,
    key: str,
    *,
    keybindings: KeybindingManager | None = None,
) -> bool:
    keybindings = keybindings or KeybindingManager()
    if keybindings.matches(key, "tui.editor.selectCharLeft"):
        target.select_char_left()
        return True
    if keybindings.matches(key, "tui.editor.selectCharRight"):
        target.select_char_right()
        return True
    if keybindings.matches(key, "tui.editor.selectWordLeft"):
        target.select_word_left()
        return True
    if keybindings.matches(key, "tui.editor.selectWordRight"):
        target.select_word_right()
        return True
    if keybindings.matches(key, "tui.editor.selectLineStart"):
        target.select_line_start()
        return True
    if keybindings.matches(key, "tui.editor.selectLineEnd"):
        target.select_line_end()
        return True
    return False


def route_prompt_completion_key(
    target: PromptInputTarget,
    key: str,
    *,
    keybindings: KeybindingManager | None = None,
) -> bool:
    keybindings = keybindings or KeybindingManager()
    if keybindings.matches(key, "tui.select.up"):
        target.select_previous_completion()
        return True
    if keybindings.matches(key, "tui.select.down"):
        target.select_next_completion()
        return True
    if keybindings.matches(key, "tui.input.tab"):
        target.apply_selected_completion()
        return True
    if keybindings.matches(key, "tui.select.cancel"):
        target.clear_completion_items()
        return True
    return False


def route_composer_editing_key(
    composer: Composer,
    key: str,
    *,
    keybindings: KeybindingManager | None = None,
) -> bool:
    return route_editor_editing_key(ComposerInputTarget(composer), key, keybindings=keybindings)


def route_composer_selection_key(
    composer: Composer,
    key: str,
    *,
    keybindings: KeybindingManager | None = None,
) -> bool:
    return route_editor_selection_key(ComposerInputTarget(composer), key, keybindings=keybindings)


def _extract_complete_sequences(buffer: str) -> tuple[tuple[str, ...], str]:
    sequences: list[str] = []
    index = 0
    while index < len(buffer):
        remaining = buffer[index:]
        if not remaining.startswith(ESC):
            sequences.append(remaining[0])
            index += 1
            continue
        alt_wrapped_status = _complete_alt_wrapped_legacy_status(remaining)
        if alt_wrapped_status == "complete":
            sequence = _matching_alt_wrapped_legacy_sequence(remaining)
            if sequence is None:
                return tuple(sequences), remaining
            sequences.append(sequence)
            index += len(sequence)
            continue
        if alt_wrapped_status == "incomplete":
            return tuple(sequences), remaining
        sequence_end = 1
        while sequence_end <= len(remaining):
            candidate = remaining[:sequence_end]
            status = _complete_escape_status(candidate)
            if status == "complete":
                if candidate == "\x1b\x1b" and _starts_escape_tail(remaining[sequence_end : sequence_end + 1]):
                    sequences.append(ESC)
                    index += 1
                    break
                sequences.append(candidate)
                index += sequence_end
                break
            if status == "not-escape":
                sequences.append(candidate)
                index += sequence_end
                break
            sequence_end += 1
        if sequence_end > len(remaining):
            return tuple(sequences), remaining
    return tuple(sequences), ""


def _complete_alt_wrapped_legacy_status(data: str) -> Literal["complete", "incomplete", "not-escape"]:
    if not data.startswith(ESC + ESC):
        return "not-escape"
    if _matching_alt_wrapped_legacy_sequence(data) is not None:
        return "complete"
    if any(sequence.startswith(data) for sequence in _ALT_WRAPPED_LEGACY_KEY_SEQUENCES):
        return "incomplete"
    return "not-escape"


def _matching_alt_wrapped_legacy_sequence(data: str) -> str | None:
    for sequence in sorted(_ALT_WRAPPED_LEGACY_KEY_SEQUENCES, key=len, reverse=True):
        if data.startswith(sequence):
            return sequence
    return None


def _complete_escape_status(data: str) -> Literal["complete", "incomplete", "not-escape"]:
    if not data.startswith(ESC):
        return "not-escape"
    if len(data) == 1:
        return "incomplete"
    after_esc = data[1:]
    if after_esc.startswith("["):
        return _complete_csi_status(data)
    if after_esc.startswith("]"):
        return "complete" if data.endswith("\x07") or data.endswith("\x1b\\") else "incomplete"
    if after_esc.startswith("P") or after_esc.startswith("_"):
        return "complete" if data.endswith("\x1b\\") else "incomplete"
    if after_esc.startswith("O"):
        return "complete" if len(after_esc) >= 2 else "incomplete"
    return "complete" if len(after_esc) >= 1 else "incomplete"


def _complete_csi_status(data: str) -> Literal["complete", "incomplete"]:
    if len(data) < 3:
        return "incomplete"
    payload = data[2:]
    if payload.startswith("M"):
        return "complete" if len(data) >= 6 else "incomplete"
    last_code = ord(payload[-1])
    if 0x40 <= last_code <= 0x7E:
        if payload.startswith("<") and not re.match(r"^<\d+;\d+;\d+[Mm]$", payload):
            return "incomplete"
        return "complete"
    return "incomplete"


def _starts_escape_tail(char: str) -> bool:
    return char in {"[", "]", "O", "P", "_"}


def _parse_key_sequence(sequence: str) -> tuple[str, KeyEventType] | None:
    if sequence in _LEGACY_KEY_SEQUENCES:
        return _LEGACY_KEY_SEQUENCES[sequence], "press"
    kitty = _parse_kitty_sequence(sequence)
    if kitty is not None:
        codepoint, modifier, event_type, base_layout_key = kitty
        return _format_key_from_codepoint(codepoint, modifier, base_layout_key=base_layout_key), event_type
    modify_other = _parse_modify_other_keys(sequence)
    if modify_other is not None:
        codepoint, modifier = modify_other
        return _format_key_from_codepoint(codepoint, modifier), "press"
    return None


def _parse_focus_sequence(sequence: str) -> bool | None:
    if sequence == "\x1b[I":
        return True
    if sequence == "\x1b[O":
        return False
    return None


def _parse_kitty_protocol_response(sequence: str) -> str | None:
    match = re.match(r"^\x1b\[\?(\d+)u$", sequence)
    if match is None:
        return None
    return match.group(1)


def _parse_cell_size_response(sequence: str) -> str | None:
    match = re.match(r"^\x1b\[6;(\d+);(\d+)t$", sequence)
    if match is None:
        return None
    return f"{match.group(1)};{match.group(2)}"


def _parse_terminal_control_response(sequence: str) -> tuple[str, str] | None:
    if sequence.startswith("\x1b]") and (sequence.endswith("\x07") or sequence.endswith("\x1b\\")):
        terminator_length = 1 if sequence.endswith("\x07") else 2
        return "osc", sequence[2:-terminator_length]
    if sequence.startswith("\x1bP") and sequence.endswith("\x1b\\"):
        return "dcs", sequence[2:-2]
    if sequence.startswith("\x1b_") and sequence.endswith("\x1b\\"):
        return "apc", sequence[2:-2]
    return None


def _parse_mouse_sequence(sequence: str) -> tuple[int, int, int, str] | None:
    sgr = _parse_sgr_mouse_sequence(sequence)
    if sgr is not None:
        return sgr
    return _parse_x10_mouse_sequence(sequence)


def _parse_sgr_mouse_sequence(sequence: str) -> tuple[int, int, int, str] | None:
    match = re.match(r"^\x1b\[<(\d+);(\d+);(\d+)([Mm])$", sequence)
    if match is None:
        return None
    button = int(match.group(1))
    column = max(0, int(match.group(2)) - 1)
    row = max(0, int(match.group(3)) - 1)
    action = "press" if match.group(4) == "M" else "release"
    return button, column, row, action


def _parse_x10_mouse_sequence(sequence: str) -> tuple[int, int, int, str] | None:
    if not sequence.startswith("\x1b[M") or len(sequence) < 6:
        return None
    button_code = max(0, ord(sequence[3]) - 32)
    button = button_code & 0b11
    column = max(0, ord(sequence[4]) - 33)
    row = max(0, ord(sequence[5]) - 33)
    action = "release" if button == 3 else "press"
    return button, column, row, action


def _parse_kitty_sequence(sequence: str) -> tuple[int, int, KeyEventType, int | None] | None:
    csi_u = re.match(r"^\x1b\[(\d+)(?::(\d*))?(?::(\d+))?(?:;(\d+))?(?::(\d+))?u$", sequence)
    if csi_u:
        codepoint = int(csi_u.group(1))
        base_layout_key = int(csi_u.group(3)) if csi_u.group(3) else None
        modifier = int(csi_u.group(4) or "1") - 1
        return codepoint, modifier, _event_type(csi_u.group(5)), base_layout_key
    arrow = re.match(r"^\x1b\[1;(\d+)(?::(\d+))?([ABCD])$", sequence)
    if arrow:
        _name, codepoint = _ARROW_CODEPOINTS[arrow.group(3)]
        return codepoint, int(arrow.group(1)) - 1, _event_type(arrow.group(2)), None
    func = re.match(r"^\x1b\[(\d+)(?:;(\d+))?(?::(\d+))?~$", sequence)
    if func:
        key_number = int(func.group(1))
        modifier = int(func.group(2) or "1") - 1
        if key_number == 13 and modifier != 0:
            return 13, modifier, _event_type(func.group(3)), None
        name = _FUNCTIONAL_CODEPOINTS.get(key_number)
        if name is None:
            return None
        codepoint = _FUNCTIONAL_NAME_CODEPOINTS[name]
        return codepoint, modifier, _event_type(func.group(3)), None
    ss3_function = re.match(r"^\x1bO([PQRSE])$", sequence)
    if ss3_function:
        name = {"P": "f1", "Q": "f2", "R": "f3", "S": "f4", "E": "clear"}[ss3_function.group(1)]
        return _FUNCTIONAL_NAME_CODEPOINTS[name], 0, "press", None
    home_end = re.match(r"^\x1b\[1;(\d+)(?::(\d+))?([HF])$", sequence)
    if home_end:
        codepoint = -14 if home_end.group(3) == "H" else -15
        return codepoint, int(home_end.group(1)) - 1, _event_type(home_end.group(2)), None
    return None


def _parse_modify_other_keys(sequence: str) -> tuple[int, int] | None:
    match = re.match(r"^\x1b\[27;(\d+);(\d+)~$", sequence)
    if match is None:
        return None
    return int(match.group(2)), int(match.group(1)) - 1


def _event_type(value: str | None) -> KeyEventType:
    if value == "2":
        return "repeat"
    if value == "3":
        return "release"
    return "press"


def _format_key_from_codepoint(codepoint: int, modifier: int, *, base_layout_key: int | None = None) -> str:
    normalized_codepoint = _KITTY_FUNCTIONAL_EQUIVALENTS.get(codepoint, codepoint)
    if normalized_codepoint in _NEGATIVE_FUNCTIONAL_CODEPOINTS:
        base = _NEGATIVE_FUNCTIONAL_CODEPOINTS[normalized_codepoint]
    elif normalized_codepoint == 9:
        base = "tab"
    elif normalized_codepoint in {13, 57414}:
        base = "enter"
    elif normalized_codepoint == 27:
        base = "escape"
    elif normalized_codepoint == 32:
        base = "space"
    elif normalized_codepoint == 127:
        base = "backspace"
    else:
        identity_codepoint = _normalize_shifted_letter(normalized_codepoint, modifier)
        effective_codepoint = (
            identity_codepoint
            if _is_authoritative_keyboard_codepoint(identity_codepoint)
            else (base_layout_key or identity_codepoint)
        )
        base = chr(_normalize_shifted_letter(effective_codepoint, modifier)).lower()
    return _apply_modifiers(base, modifier)


def _normalize_shifted_letter(codepoint: int, modifier: int) -> int:
    effective_modifier = modifier & ~_LOCK_MASK
    if effective_modifier & _MOD_SHIFT and 65 <= codepoint <= 90:
        return codepoint + 32
    return codepoint


def _is_authoritative_keyboard_codepoint(codepoint: int) -> bool:
    return 97 <= codepoint <= 122 or 48 <= codepoint <= 57 or chr(codepoint) in _SYMBOL_KEYS


def _is_windows_terminal_session() -> bool:
    return bool(
        os.environ.get("WT_SESSION")
        and not os.environ.get("SSH_CONNECTION")
        and not os.environ.get("SSH_CLIENT")
        and not os.environ.get("SSH_TTY")
    )


def _apply_modifiers(base: str, modifier: int) -> str:
    effective = modifier & ~_LOCK_MASK
    modifiers: list[str] = []
    if effective & _MOD_CTRL:
        modifiers.append("ctrl")
    if effective & _MOD_SHIFT:
        modifiers.append("shift")
    if effective & _MOD_ALT:
        modifiers.append("alt")
    if effective & _MOD_SUPER:
        modifiers.append("super")
    return normalize_key_id("+".join([*modifiers, base]) if modifiers else base)


def _kitty_printable_text(sequence: str) -> str | None:
    parsed = _parse_kitty_sequence(sequence)
    if parsed is None:
        return None
    codepoint, modifier, event_type, _base_layout_key = parsed
    if event_type != "press" or modifier & ~_LOCK_MASK:
        return None
    normalized_codepoint = _KITTY_FUNCTIONAL_EQUIVALENTS.get(codepoint, codepoint)
    if normalized_codepoint in _NEGATIVE_FUNCTIONAL_CODEPOINTS:
        return None
    if normalized_codepoint in {9, 13, 27, 127}:
        return None
    if normalized_codepoint < 32:
        return None
    return chr(normalized_codepoint)


def _parse_alt_control_sequence(sequence: str) -> str | None:
    if not sequence.startswith(ESC) or len(sequence) != 2:
        return None
    return _ALT_CONTROL_KEY_MAP.get(sequence[1])


def _coalesce_text_events(events: list[InputEvent]) -> tuple[InputEvent, ...]:
    if not events:
        return ()
    coalesced: list[InputEvent] = []
    pending_text = ""
    pending_raw = ""
    for event in events:
        if event.kind == "text":
            pending_text += event.text
            pending_raw += event.raw
            continue
        if pending_text:
            coalesced.append(InputEvent(kind="text", text=pending_text, raw=pending_raw))
            pending_text = ""
            pending_raw = ""
        coalesced.append(event)
    if pending_text:
        coalesced.append(InputEvent(kind="text", text=pending_text, raw=pending_raw))
    return tuple(coalesced)


def _input_batch(events: tuple[InputEvent, ...], *, has_pending: bool) -> InputBatch:
    app_events: list[InputEvent] = []
    control_events: list[InputEvent] = []
    for event in events:
        if event.kind == "signal":
            control_events.append(event)
        else:
            app_events.append(event)
    return InputBatch(
        app_events=tuple(app_events),
        control_events=tuple(control_events),
        has_pending=has_pending,
    )


def _legacy_event(event: InputEvent) -> InputEvent:
    legacy_key = {
        "escape": "esc",
        "ctrl+c": "ctrl_c",
        "ctrl+j": "ctrl_j",
        "alt+enter": "alt_enter",
        "alt+up": "alt_up",
    }.get(event.key)
    if legacy_key is None:
        return event
    return InputEvent(
        kind=event.kind,
        text=event.text,
        key=legacy_key,
        columns=event.columns,
        rows=event.rows,
        signal=event.signal,
        raw=event.raw,
        event_type=event.event_type,
    )
