from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from loushang.tui.cell_width import (
    TAB_WIDTH,
    autowrap_safe_width,
    grapheme_clusters,
    slice_by_column,
    truncate_to_width,
    visible_width,
)
from loushang.tui.completion import (
    CompletionCancellationToken,
    CompletionContext,
    get_completion_suggestions,
)
from loushang.tui.completion_models import (
    CompletionApplication,
    CompletionItem,
    CompletionSuggestions,
)
from loushang.tui.composer_edit_buffer import (
    ComposerAtom as _Atom,
)
from loushang.tui.composer_edit_buffer import (
    ComposerEditBuffer,
)
from loushang.tui.composer_edit_buffer import (
    ComposerPasteMarker as _PasteMarker,
)
from loushang.tui.composer_edit_buffer import (
    atom_value as _atom_value,
)
from loushang.tui.composer_edit_buffer import (
    cursor_advance as _cursor_advance,
)
from loushang.tui.composer_edit_buffer import (
    text_atoms as _text_atoms,
)
from loushang.tui.core import (
    CursorDeclaration,
    RenderConstraints,
    RenderLine,
    RenderResult,
)
from loushang.tui.framework import surface_is_bottom_exclusive
from loushang.tui.kill_ring import KillRing
from loushang.tui.selection_controller import SelectionController
from loushang.tui.selection_rendering import (
    DEFAULT_SELECTION_STYLE,
    highlight_selection_by_columns,
)
from loushang.tui.theme import ThemeResolver, ThemeStyle, apply_theme_style

from .layout import RegionRenderable, ScreenRegion, ScreenRegionStack, _part_has_content
from .pending import PendingQueueView as PendingQueueView
from .status import StatusBar as StatusBar
from .status import WorkingLine as WorkingLine

_EditAction = str | None
DEFAULT_COMPOSER_SELECTION_STYLE: ThemeStyle = DEFAULT_SELECTION_STYLE


@dataclass(frozen=True, slots=True)
class _WrappedChunk:
    text: str
    start_width: int
    end_width: int


@dataclass(frozen=True, slots=True)
class _VisualSegment:
    row: int
    start_width: int
    end_width: int


@dataclass(frozen=True, slots=True)
class _CompletionRefreshRequest:
    token: int
    provider: Any
    lines: tuple[str, ...]
    cursor_line: int
    cursor_col: int
    force: bool
    explicit: bool
    due_at: float
    cancellation_token: CompletionCancellationToken


@dataclass(slots=True)
class Composer:
    prompt: str = "> "
    continuation_prompt: str = "  "
    large_paste_line_threshold: int = 8
    large_paste_char_threshold: int = 1000
    theme: ThemeResolver | None = None
    selection_theme_token: str = "editor.selection"
    completion_debounce_seconds: float = 0.05
    completion_min_interval_seconds: float = 0.05
    now: Callable[[], float] = field(default_factory=lambda: time.monotonic, repr=False)
    submitted: bool = False
    _buffer: ComposerEditBuffer = field(default_factory=ComposerEditBuffer, repr=False)
    _selection_controller: SelectionController = field(init=False, repr=False)
    _kill_ring: KillRing = field(default_factory=KillRing)
    _last_action: _EditAction = None
    _history: list[str] = field(default_factory=list)
    _history_index: int = -1
    _history_draft: str = ""
    _next_paste_marker_id: int = 1
    _preferred_visual_column: int | None = None
    _scroll_offset: int = 0
    autocomplete_max_visible: int = 8
    _completion_provider: Any | None = None
    _completion_items: tuple[CompletionItem, ...] = ()
    _completion_selected_index: int = 0
    _completion_prefix: str = ""
    _completion_group: str = ""
    _completion_pending: _CompletionRefreshRequest | None = None
    _completion_request_token: int = 0
    _completion_last_started_at: float | None = None

    def __post_init__(self) -> None:
        self._selection_controller = SelectionController(
            length=lambda: len(self._buffer),
            cursor=lambda: self._buffer.cursor,
            set_cursor=self._set_cursor_index,
        )

    @property
    def value(self) -> str:
        return self._buffer.value

    @property
    def kill_ring(self) -> tuple[str, ...]:
        return tuple(self._kill_ring)

    @property
    def browsing_history(self) -> bool:
        return self._history_index >= 0

    @property
    def has_completions(self) -> bool:
        return bool(self._completion_items)

    @property
    def selected_range(self) -> tuple[int, int] | None:
        return self._selection_controller.selected_range

    def has_selection(self) -> bool:
        return self._selection_controller.has_selection()

    def set_selection(self, anchor: int, focus: int) -> None:
        self._selection_controller.set(anchor, focus)

    def clear_selection(self) -> None:
        self._selection_controller.clear()

    def next_frame_due_ms(self, *, after_ms: int) -> int | None:
        del after_ms
        if self._completion_pending is None:
            return None
        return max(0, math.ceil(self._completion_pending.due_at * 1000))

    def insert_text(self, text: str) -> None:
        if not text:
            return
        atoms = _text_atoms(text)
        if self._replace_selection_with_atoms(atoms, last_action="type-word" if len(atoms) == 1 else None):
            return
        if self._insert_pushes_undo(atoms):
            self._buffer.push_undo()
        self._insert_atoms(atoms)
        self._last_action = "type-word" if len(atoms) == 1 else None

    def set_text(self, text: str) -> None:
        if self.value == text:
            return
        self._buffer.set_text(text, record=True)
        self.clear_selection()
        self.submitted = False
        self._history_index = -1
        self._last_action = None
        self._refresh_completion_items()

    def insert_newline(self) -> None:
        self.insert_text("\n")

    def paste(self, text: str) -> None:
        if not text:
            return
        text = _normalize_paste(text)
        selection = self.selected_range
        insert_at = self._buffer.cursor if selection is None else selection[0]
        text = _prefix_space_before_path_paste(self._buffer.atoms, insert_at, text)
        line_count = text.count("\n") + 1
        char_count = len(text)
        if line_count > self.large_paste_line_threshold or char_count > self.large_paste_char_threshold:
            marker_id = self._next_paste_marker_id
            marker = _PasteMarker(
                marker_id=marker_id,
                text=text,
                label=_paste_marker_label(
                    marker_id=marker_id,
                    line_count=line_count,
                    char_count=char_count,
                    line_threshold=self.large_paste_line_threshold,
                ),
            )
            self._next_paste_marker_id += 1
            self._apply_buffer_content_edit(
                lambda: self._replace_or_insert_atoms(selection, [marker]),
                last_action=None,
            )
            return
        if selection is not None:
            self._apply_buffer_content_edit(
                lambda: self._buffer.replace_range(selection[0], selection[1], text, record=False),
                last_action=None,
            )
            return
        self._apply_buffer_content_edit(lambda: self._buffer.insert_atoms(_text_atoms(text), record=False), last_action=None)

    def delete_backward(self) -> None:
        if self._delete_selection_or_none():
            return
        if self._buffer.cursor == 0:
            return
        self._apply_buffer_content_edit(lambda: self._buffer.delete_backward(record=False), last_action=None)

    def delete_forward(self) -> None:
        if self._delete_selection_or_none():
            return
        if self._buffer.cursor >= len(self._buffer):
            return
        self._apply_buffer_content_edit(lambda: self._buffer.delete_forward(record=False), last_action=None)

    def move_left(self) -> None:
        self._buffer.move_left()
        self._after_cursor_move()

    def move_right(self) -> None:
        self._buffer.move_right()
        self._after_cursor_move()

    def move_to_line_start(self) -> None:
        self._buffer.move_to_line_start()
        self._after_cursor_move()

    def move_to_line_end(self) -> None:
        self._buffer.move_to_line_end()
        self._after_cursor_move()

    def move_word_left(self) -> None:
        self._buffer.move_word_left()
        self._after_cursor_move()

    def move_word_right(self) -> None:
        self._buffer.move_word_right()
        self._after_cursor_move()

    def select_char_left(self) -> None:
        self._extend_selection_to(self._buffer.cursor - 1)

    def select_char_right(self) -> None:
        self._extend_selection_to(self._buffer.cursor + 1)

    def select_word_left(self) -> None:
        self._extend_selection_to(self._word_left_index())

    def select_word_right(self) -> None:
        self._extend_selection_to(self._word_right_index())

    def select_line_start(self) -> None:
        self._extend_selection_to(self._line_start_index())

    def select_line_end(self) -> None:
        self._extend_selection_to(self._line_end_index())

    def jump_to_char(self, char: str, *, direction: Literal["forward", "backward"]) -> None:
        if not char:
            return
        target = char[0]
        if direction == "forward":
            indexes = range(self._buffer.cursor + 1, len(self._buffer))
        else:
            indexes = range(self._buffer.cursor - 1, -1, -1)
        atoms = self._buffer.atoms
        for index in indexes:
            if _atom_value(atoms[index]) == target:
                self._buffer.set_atoms(atoms, cursor=index)
                self._after_cursor_move()
                return

    def move_visual_up(self, *, width: int) -> bool:
        moved = self._move_visual(delta=-1, width=width)
        self.clear_selection()
        self._last_action = None
        return moved

    def move_visual_down(self, *, width: int) -> bool:
        moved = self._move_visual(delta=1, width=width)
        self.clear_selection()
        self._last_action = None
        return moved

    def move_visual_page_up(self, *, width: int, visible_lines: int) -> None:
        for _ in range(_page_visual_delta(visible_lines)):
            self._move_visual(delta=-1, width=width)
        self.clear_selection()
        self._last_action = None

    def move_visual_page_down(self, *, width: int, visible_lines: int) -> None:
        for _ in range(_page_visual_delta(visible_lines)):
            self._move_visual(delta=1, width=width)
        self.clear_selection()
        self._last_action = None

    def delete_word_backward(self) -> None:
        if self._kill_selection_or_none(prepend=True):
            return
        start = self._word_left_index()
        cursor = self._buffer.cursor
        if start == cursor:
            return
        killed = "".join(_atom_value(atom) for atom in self._buffer.atoms[start:cursor])
        was_kill = self._last_action == "kill"
        self._apply_buffer_content_edit(
            lambda: self._delete_range_to_kill_ring(start, cursor, killed, prepend=True, accumulate=was_kill),
            last_action="kill",
        )

    def delete_word_forward(self) -> None:
        if self._kill_selection_or_none(prepend=False):
            return
        end = self._word_right_index()
        cursor = self._buffer.cursor
        if end == cursor:
            return
        killed = "".join(_atom_value(atom) for atom in self._buffer.atoms[cursor:end])
        was_kill = self._last_action == "kill"
        self._apply_buffer_content_edit(
            lambda: self._delete_range_to_kill_ring(cursor, end, killed, prepend=False, accumulate=was_kill),
            last_action="kill",
        )

    def move_cursor_to(self, value_index: int) -> None:
        self._buffer.move_cursor_to_value_index(value_index)
        self._after_cursor_move()

    def set_completion_items(self, items: tuple[CompletionItem, ...] | list[CompletionItem], *, group: str = "") -> None:
        self._cancel_pending_completion()
        selected = self._selected_completion_item()
        previous_prefix = self._completion_prefix
        self._completion_items = tuple(items)
        self._completion_prefix = self._completion_prefix_text()
        self._completion_group = group
        self._completion_selected_index = _completion_index_after_refresh(
            selected if self._completion_prefix == previous_prefix else None,
            self._completion_selected_index,
            self._completion_items,
        )

    def set_completion_provider(self, provider: Any | None) -> None:
        if provider is not self._completion_provider:
            self._cancel_pending_completion()
            self._clear_completion_items_state()
        self._completion_provider = provider
        self.refresh_completions()

    def clear_completion_provider(self) -> None:
        self._completion_provider = None
        self._cancel_pending_completion()
        self.clear_completion_items()

    def refresh_completions(self, *, force: bool = False, explicit: bool = False) -> None:
        self._request_completion_refresh(force=force, explicit=explicit)

    def clear_completion_items(self) -> None:
        self._cancel_pending_completion()
        self._clear_completion_items_state()

    def _clear_completion_items_state(self) -> None:
        self._completion_items = ()
        self._completion_selected_index = 0
        self._completion_prefix = ""
        self._completion_group = ""

    def select_next_completion(self) -> None:
        if not self._completion_items:
            return
        self._completion_selected_index = (self._completion_selected_index + 1) % len(self._completion_items)

    def select_previous_completion(self) -> None:
        if not self._completion_items:
            return
        self._completion_selected_index = (self._completion_selected_index - 1) % len(self._completion_items)

    def apply_selected_completion(self) -> None:
        if not self._completion_items:
            return
        self._cancel_pending_completion()
        selected = self._completion_items[self._completion_selected_index]
        if self._completion_provider is not None and self._completion_prefix:
            application = self._apply_provider_completion(selected)
            if application is not None:
                self._buffer.push_undo()
                self._buffer.set_lines_and_cursor(
                    application.lines,
                    cursor_line=application.cursor_line,
                    cursor_col=application.cursor_col,
                )
                self._completion_items = ()
                self._completion_selected_index = 0
                self._completion_prefix = ""
                self._completion_group = ""
                self._preferred_visual_column = None
                self._buffer.clear_redo()
                self.clear_selection()
                self._last_action = None
                return
        start, end = self._completion_prefix_range()
        self._buffer.replace_range(start, end, selected.value)
        self._completion_items = ()
        self._completion_selected_index = 0
        self._completion_prefix = ""
        self._completion_group = ""
        self._preferred_visual_column = None
        self.clear_selection()
        self._last_action = None

    def add_history(self, text: str) -> None:
        trimmed = text.strip()
        if not trimmed:
            return
        if self._history and self._history[0] == trimmed:
            return
        self._history.insert(0, trimmed)
        del self._history[100:]

    def history_previous(self) -> str:
        if not self._history:
            return self.value
        if self._history_index == -1:
            self._history_draft = self.value
            self._history_index = 0
        elif self._history_index < len(self._history) - 1:
            self._history_index += 1
        self._buffer.set_text(self._history[self._history_index], record=False)
        self.clear_selection()
        self._last_action = None
        return self.value

    def history_next(self) -> str:
        if self._history_index == -1:
            return self.value
        if self._history_index > 0:
            self._history_index -= 1
            self._buffer.set_text(self._history[self._history_index], record=False)
            self.clear_selection()
            self._last_action = None
            return self.value
        self._history_index = -1
        self._buffer.set_text(self._history_draft, record=False)
        self._history_draft = ""
        self.clear_selection()
        self._last_action = None
        return self.value

    def kill_to_line_end(self) -> None:
        if self._kill_selection_or_none(prepend=False):
            return
        end = self._line_end_index()
        cursor = self._buffer.cursor
        killed = "".join(_atom_value(atom) for atom in self._buffer.atoms[cursor:end])
        if not killed:
            return
        was_kill = self._last_action == "kill"
        self._apply_buffer_content_edit(
            lambda: self._delete_range_to_kill_ring(cursor, end, killed, prepend=False, accumulate=was_kill),
            last_action="kill",
        )

    def kill_to_line_start(self) -> None:
        if self._kill_selection_or_none(prepend=True):
            return
        start = self._line_start_index()
        cursor = self._buffer.cursor
        killed = "".join(_atom_value(atom) for atom in self._buffer.atoms[start:cursor])
        if not killed:
            return
        was_kill = self._last_action == "kill"
        self._apply_buffer_content_edit(
            lambda: self._delete_range_to_kill_ring(start, cursor, killed, prepend=True, accumulate=was_kill),
            last_action="kill",
        )

    def yank(self) -> None:
        text = self._kill_ring.peek()
        if text is None:
            return
        if self._replace_selection_with_atoms(_text_atoms(text), last_action="yank"):
            return
        self._apply_buffer_content_edit(lambda: self._buffer.insert_atoms(_text_atoms(text), record=False), last_action="yank")

    def yank_pop(self) -> None:
        if self._last_action != "yank" or len(self._kill_ring) <= 1:
            return
        previous_text = self._kill_ring.peek()
        if previous_text is None:
            return
        previous_atoms = _text_atoms(previous_text)
        start = self._buffer.cursor - len(previous_atoms)
        if start < 0:
            return
        cursor = self._buffer.cursor
        if "".join(_atom_value(atom) for atom in self._buffer.atoms[start:cursor]) != previous_text:
            return

        def edit() -> None:
            self._buffer.delete_range(start, cursor, record=False)
            self._rotate_kill_ring()
            replacement = self._kill_ring.peek()
            if replacement is not None:
                self._buffer.insert_atoms(_text_atoms(replacement), record=False)

        self._apply_buffer_content_edit(edit, last_action="yank")

    def undo(self) -> None:
        if not self._buffer.undo():
            return
        self.clear_selection()
        self._last_action = None
        self._refresh_completion_items()

    def redo(self) -> None:
        if not self._buffer.redo():
            return
        self.clear_selection()
        self._last_action = None
        self._refresh_completion_items()

    def clear(self) -> None:
        self._buffer.clear()
        self.clear_selection()
        self._history_index = -1
        self.submitted = False
        self._scroll_offset = 0
        self.clear_completion_items()
        self._last_action = None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        self._poll_pending_completion_refresh()
        lines, cursor = _render_composer_text(
            self._buffer.display_text,
            display_cursor=self._buffer.display_cursor,
            selection_display_range=self._selection_display_range(),
            selection_style=self._selection_style(),
            prompt=self.prompt,
            continuation_prompt=self.continuation_prompt,
            width=constraints.width,
        )
        completion_lines = self._render_completion_lines(
            width=constraints.width,
            max_height=max(0, constraints.max_height - 1),
        )
        composer_budget = max(1, constraints.max_height - len(completion_lines))
        lines, cursor = self._visible_composer_lines(lines, cursor, max_height=composer_budget)
        return RenderResult.from_lines(
            [RenderLine(line) for line in [*lines, *completion_lines]],
            constraints=constraints,
            cursor=cursor,
        )

    def _insert_atoms(self, atoms: list[_Atom]) -> None:
        self._buffer.insert_atoms(atoms, record=False)
        self.submitted = False
        self._history_index = -1
        self._refresh_completion_items()

    def _insert_pushes_undo(self, atoms: list[_Atom]) -> bool:
        if len(atoms) != 1:
            return True
        value = _atom_value(atoms[0])
        return value.isspace() or self._last_action != "type-word"

    def _push_kill(self, text: str, *, prepend: bool, accumulate: bool) -> None:
        if not text:
            return
        self._kill_ring.push(text, prepend=prepend, accumulate=accumulate)
        self._last_action = "kill"

    def _rotate_kill_ring(self) -> None:
        self._kill_ring.rotate()

    def _clamp_selection_index(self, index: int) -> int:
        return max(0, min(index, len(self._buffer)))

    def _set_cursor_index(self, index: int) -> None:
        self._buffer.set_atoms(self._buffer.atoms, cursor=self._clamp_selection_index(index), record=False)

    def _extend_selection_to(self, target: int) -> None:
        self._selection_controller.extend_to(target)
        self._last_action = None
        self._preferred_visual_column = None
        self._refresh_completion_items()

    def _after_cursor_move(self) -> None:
        self.clear_selection()
        self._last_action = None
        self._preferred_visual_column = None
        self._refresh_completion_items()

    def _after_buffer_content_edit(self, *, last_action: _EditAction) -> None:
        self.clear_selection()
        self.submitted = False
        self._history_index = -1
        self._preferred_visual_column = None
        self._last_action = last_action
        self._refresh_completion_items()

    def _apply_buffer_content_edit(self, edit: Callable[[], object], *, last_action: _EditAction) -> bool:
        changed = self._buffer.apply_edit(edit)
        if not changed:
            return False
        self._after_buffer_content_edit(last_action=last_action)
        return True

    def _replace_or_insert_atoms(self, selection: tuple[int, int] | None, atoms: list[_Atom]) -> None:
        if selection is None:
            self._buffer.insert_atoms(atoms, record=False)
            return
        self._buffer.replace_atoms(selection[0], selection[1], atoms, record=False)

    def _delete_range_to_kill_ring(
        self,
        start: int,
        end: int,
        killed: str,
        *,
        prepend: bool,
        accumulate: bool,
    ) -> None:
        self._push_kill(killed, prepend=prepend, accumulate=accumulate)
        self._buffer.delete_range(start, end, record=False)

    def _replace_selection_with_atoms(self, atoms: list[_Atom], *, last_action: _EditAction) -> bool:
        selection = self.selected_range
        if selection is None:
            return False
        return self._apply_buffer_content_edit(
            lambda: self._buffer.replace_atoms(selection[0], selection[1], atoms, record=False),
            last_action=last_action,
        )

    def _delete_selection_or_none(self) -> bool:
        selection = self.selected_range
        if selection is None:
            return False
        return self._apply_buffer_content_edit(
            lambda: self._buffer.delete_range(selection[0], selection[1], record=False),
            last_action=None,
        )

    def _kill_selection_or_none(self, *, prepend: bool) -> bool:
        selection = self.selected_range
        if selection is None:
            return False
        killed = "".join(_atom_value(atom) for atom in self._buffer.atoms[selection[0] : selection[1]])
        if not killed:
            self.clear_selection()
            return True
        was_kill = self._last_action == "kill"
        return self._apply_buffer_content_edit(
            lambda: self._delete_range_to_kill_ring(
                selection[0],
                selection[1],
                killed,
                prepend=prepend,
                accumulate=was_kill,
            ),
            last_action="kill",
        )

    def _display_cursor(self) -> int:
        return self._buffer.display_cursor

    def _selection_display_range(self) -> tuple[int, int] | None:
        selection = self.selected_range
        if selection is None:
            return None
        start, end = selection
        atoms = self._buffer.atoms
        display_start = sum(_cursor_advance(atom) for atom in atoms[:start])
        display_end = display_start + sum(_cursor_advance(atom) for atom in atoms[start:end])
        if display_start == display_end:
            return None
        return display_start, display_end

    def _selection_style(self) -> ThemeStyle:
        if self.theme is not None and self.selection_theme_token:
            resolved = self.theme.resolve(self.selection_theme_token)
            if resolved:
                return resolved
        return DEFAULT_COMPOSER_SELECTION_STYLE

    def _line_start_index(self) -> int:
        return self._buffer.line_start_index()

    def _line_end_index(self) -> int:
        return self._buffer.line_end_index()

    def _word_left_index(self) -> int:
        return self._buffer.word_left_index()

    def _word_right_index(self) -> int:
        return self._buffer.word_right_index()

    def _move_visual(self, *, delta: int, width: int) -> bool:
        segments = _visual_segments(
            self._buffer.display_text,
            prompt=self.prompt,
            continuation_prompt=self.continuation_prompt,
            width=width,
        )
        if not segments:
            return False
        previous_cursor = self._buffer.cursor
        display_cursor = self._display_cursor()
        current_index = _find_visual_segment_index(segments, display_cursor)
        target_index = max(0, min(len(segments) - 1, current_index + delta))
        current_segment = segments[current_index]
        current_column = display_cursor - current_segment.start_width
        if self._preferred_visual_column is not None:
            current_column = self._preferred_visual_column
        target_segment = segments[target_index]
        target_width = target_segment.end_width - target_segment.start_width
        if current_column > target_width:
            self._preferred_visual_column = current_column
        else:
            self._preferred_visual_column = None
        snapped = self._move_cursor_to_display_width(target_segment.start_width + min(current_column, target_width))
        if snapped:
            self._preferred_visual_column = current_column
        return self._buffer.cursor != previous_cursor

    def _move_cursor_to_display_width(self, target_width: int) -> bool:
        snapped = self._buffer.move_cursor_to_display_width(target_width)
        self._refresh_completion_items()
        return snapped

    def _refresh_completion_items(self, *, force: bool = False, explicit: bool = False) -> None:
        self._request_completion_refresh(force=force, explicit=explicit)

    def _request_completion_refresh(self, *, force: bool = False, explicit: bool = False) -> None:
        if self._completion_provider is None:
            self._cancel_pending_completion()
            return
        request = self._completion_refresh_request(force=force, explicit=explicit)
        if request is None:
            self.clear_completion_items()
            return
        if force or not _should_debounce_completion_request(request):
            if self._completion_pending is not None:
                self._completion_pending.cancellation_token.cancel("superseded")
                self._completion_pending = None
            self._run_completion_refresh(request)
            return
        if self._completion_pending is not None:
            self._completion_pending.cancellation_token.cancel("superseded")
        self._completion_pending = request
        if self._completion_items and self._completion_prefix != _completion_prefix_from_request(request):
            self._clear_completion_items_state()

    def _completion_refresh_request(self, *, force: bool, explicit: bool) -> _CompletionRefreshRequest | None:
        provider = self._completion_provider
        if provider is None:
            return None
        lines, cursor_line, cursor_col = self._lines_and_cursor()
        if not force and not _completion_prefix_from_position(lines, cursor_line, cursor_col):
            return None
        now = self.now()
        due_at = now
        if not force:
            due_at = max(due_at, now + max(0.0, self.completion_debounce_seconds))
            if self._completion_last_started_at is not None:
                due_at = max(due_at, self._completion_last_started_at + max(0.0, self.completion_min_interval_seconds))
        token = self._next_completion_token()
        return _CompletionRefreshRequest(
            token=token,
            provider=provider,
            lines=tuple(lines),
            cursor_line=cursor_line,
            cursor_col=cursor_col,
            force=force,
            explicit=explicit,
            due_at=due_at,
            cancellation_token=CompletionCancellationToken(),
        )

    def _run_completion_refresh(self, request: _CompletionRefreshRequest) -> None:
        if request.token != self._completion_request_token or request.cancellation_token.cancelled:
            return
        selected = self._selected_completion_item()
        self._completion_last_started_at = self.now()
        suggestions = self._provider_suggestions_for_request(request)
        if (
            request.token != self._completion_request_token
            or request.cancellation_token.cancelled
            or not self._completion_request_is_current(request)
        ):
            return
        if suggestions is None or not suggestions.items:
            self._clear_completion_items_state()
            return
        previous_prefix = self._completion_prefix
        self._completion_items = tuple(suggestions.items)
        self._completion_prefix = suggestions.prefix
        self._completion_group = suggestions.group
        self._completion_selected_index = _completion_index_after_refresh(
            selected if self._completion_prefix == previous_prefix else None,
            self._completion_selected_index,
            self._completion_items,
        )

    def _poll_pending_completion_refresh(self) -> None:
        request = self._completion_pending
        if request is None or request.due_at - self.now() > 1e-9:
            return
        self._completion_pending = None
        self._run_completion_refresh(request)

    def _cancel_pending_completion(self) -> None:
        if self._completion_pending is not None:
            self._completion_pending.cancellation_token.cancel("superseded")
            self._completion_pending = None
        self._next_completion_token()

    def _next_completion_token(self) -> int:
        self._completion_request_token += 1
        return self._completion_request_token

    def _completion_request_is_current(self, request: _CompletionRefreshRequest) -> bool:
        if request.provider is not self._completion_provider:
            return False
        lines, cursor_line, cursor_col = self._lines_and_cursor()
        return request.lines == tuple(lines) and request.cursor_line == cursor_line and request.cursor_col == cursor_col

    def _provider_suggestions_for_request(self, request: _CompletionRefreshRequest) -> CompletionSuggestions | None:
        return get_completion_suggestions(
            request.provider,
            CompletionContext(
                lines=request.lines,
                cursor_line=request.cursor_line,
                cursor_col=request.cursor_col,
                force=request.force,
                explicit=request.explicit,
                cancellation_token=request.cancellation_token,
            ),
        )

    def _apply_provider_completion(self, selected: CompletionItem) -> CompletionApplication | None:
        provider = self._completion_provider
        if provider is None:
            return None
        apply_completion = getattr(provider, "apply_completion", None)
        if not callable(apply_completion):
            return None
        lines, cursor_line, cursor_col = self._lines_and_cursor()
        return apply_completion(tuple(lines), cursor_line, cursor_col, selected, self._completion_prefix)

    def _lines_and_cursor(self) -> tuple[tuple[str, ...], int, int]:
        return self._buffer.lines_and_cursor()

    def _selected_completion_item(self) -> CompletionItem | None:
        if not self._completion_items:
            return None
        index = _clamp_completion_index(self._completion_selected_index, self._completion_items)
        return self._completion_items[index]

    def _completion_prefix_text(self) -> str:
        return self._buffer.completion_prefix_text()

    def _completion_prefix_range(self) -> tuple[int, int]:
        return self._buffer.completion_prefix_range()

    def _render_completion_lines(self, *, width: int, max_height: int) -> list[str]:
        if not self._completion_items or max_height <= 1:
            return []
        item_budget = max(1, min(self.autocomplete_max_visible, max_height - 1))
        lines: list[str] = []
        start = _completion_scroll_start(self._completion_selected_index, len(self._completion_items), item_budget)
        visible_items = self._completion_items[start : min(start + item_budget, len(self._completion_items))]
        label_width = _completion_label_width(visible_items)
        lines.append("")
        for index in range(start, start + len(visible_items)):
            lines.append(
                _render_completion_item(
                    self._completion_items[index],
                    selected=index == self._completion_selected_index,
                    label_width=label_width,
                    width=width,
                )
            )
        return lines

    def _visible_composer_lines(
        self,
        lines: list[str],
        cursor: CursorDeclaration,
        *,
        max_height: int,
    ) -> tuple[list[str], CursorDeclaration]:
        if len(lines) <= max_height:
            self._scroll_offset = 0
            return lines, cursor
        max_offset = max(0, len(lines) - max_height)
        offset = max(0, min(self._scroll_offset, max_offset))
        if cursor.row < offset:
            offset = cursor.row
        elif cursor.row >= offset + max_height:
            offset = cursor.row - max_height + 1
        offset = max(0, min(offset, max_offset))
        self._scroll_offset = offset
        return lines[offset : offset + max_height], CursorDeclaration(
            row=cursor.row - offset,
            column=cursor.column,
        )


@dataclass(slots=True)
class BottomFrame:
    composer: Composer
    status_bar: StatusBar | None = None
    working_line: WorkingLine | None = None
    pending_queue: PendingQueueView | None = None
    surface: Any | None = None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if constraints.max_height == 1:
            composer_result = self.composer.render(RenderConstraints(width=constraints.width, max_height=1))
            return _frame_result([line.text for line in composer_result.lines][-1:], constraints, composer_result.cursor, cursor_offset=0)
        return ScreenRegionStack(self.regions()).render(constraints)

    def regions(self) -> tuple[ScreenRegion, ...]:
        regions: list[ScreenRegion] = []
        surface = self.surface
        has_surface = False
        if surface is not None and _part_has_content(surface):
            has_surface = True
            regions.append(ScreenRegion("surface", surface))
            if surface_is_bottom_exclusive(surface):
                return tuple(regions)
        if self.working_line is not None:
            regions.append(ScreenRegion("working", self.working_line, max_height=1, gap_before=1, gap_after=1))
        if self.pending_queue is not None and self.pending_queue.has_content:
            regions.append(ScreenRegion("pending", self.pending_queue, gap_after=1))
        composer_gap_before = 1 if not regions else 0
        composer: RegionRenderable = _CursorlessRenderable(self.composer) if has_surface else self.composer
        regions.append(
            ScreenRegion(
                "composer",
                composer,
                required=True,
                min_height=1,
                gap_before=composer_gap_before,
                gap_after=1,
            )
        )
        if self.status_bar is not None and not self.composer.has_completions:
            regions.append(ScreenRegion("status", self.status_bar, required=True, min_height=1, max_height=1))
        return tuple(regions)


@dataclass(slots=True)
class _CursorlessRenderable:
    renderable: RegionRenderable

    def render(self, constraints: RenderConstraints) -> RenderResult:
        result = self.renderable.render(constraints)
        return RenderResult.from_lines(result.lines, constraints=constraints)


def _page_visual_delta(visible_lines: int) -> int:
    return max(1, int(visible_lines) - 1)


def _normalize_paste(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " " * TAB_WIDTH)


def _prefix_space_before_path_paste(atoms: Sequence[_Atom], cursor: int, text: str) -> str:
    if not text.startswith(("/", "~", ".")) or cursor <= 0:
        return text
    previous = _atom_value(atoms[cursor - 1])
    if not previous:
        return text
    previous_char = previous[-1]
    if previous_char.isalnum() or previous_char == "_":
        return f" {text}"
    return text


def _paste_marker_label(*, marker_id: int, line_count: int, char_count: int, line_threshold: int) -> str:
    if line_count > line_threshold:
        return f"[paste #{marker_id} +{line_count} lines]"
    return f"[paste #{marker_id} {char_count} chars]"


def _single_line_text(text: str) -> str:
    return text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def _clamp_completion_index(index: int, items: tuple[CompletionItem, ...]) -> int:
    if not items:
        return 0
    return max(0, min(index, len(items) - 1))


def _completion_index_after_refresh(
    selected: CompletionItem | None,
    fallback_index: int,
    items: tuple[CompletionItem, ...],
) -> int:
    if selected is not None:
        for index, item in enumerate(items):
            if item.value == selected.value:
                return index
    return _clamp_completion_index(fallback_index, items)


def _completion_prefix_from_request(request: _CompletionRefreshRequest) -> str:
    return _completion_prefix_from_position(request.lines, request.cursor_line, request.cursor_col)


def _completion_prefix_from_position(lines: tuple[str, ...], cursor_line: int, cursor_col: int) -> str:
    if cursor_line < 0 or cursor_line >= len(lines):
        return ""
    start = cursor_col
    line = lines[cursor_line]
    while start > 0:
        value = line[start - 1]
        if value.isspace() or value == "\n":
            break
        start -= 1
    return line[start:cursor_col]


def _should_debounce_completion_request(request: _CompletionRefreshRequest) -> bool:
    if request.cursor_line < 0 or request.cursor_line >= len(request.lines):
        return False
    text_before_cursor = request.lines[request.cursor_line][: request.cursor_col]
    token_start = _last_completion_delimiter_index(text_before_cursor) + 1
    token = text_before_cursor[token_start:]
    if token.startswith("/") and token_start == 0:
        return False
    return (
        token.startswith("@")
        or token.startswith("#")
        or token.startswith("./")
        or token.startswith("../")
        or token.startswith("~/")
        or "/" in token
    )


def _last_completion_delimiter_index(text: str) -> int:
    for index in range(len(text) - 1, -1, -1):
        if text[index].isspace() or text[index] in {'"', "'", "="}:
            return index
    return -1


def _completion_scroll_start(selected_index: int, total: int, visible_budget: int) -> int:
    if total <= visible_budget:
        return 0
    centered = selected_index - visible_budget // 2
    return max(0, min(centered, total - visible_budget))


def _completion_label_width(items: tuple[CompletionItem, ...]) -> int:
    if not items:
        return 1
    return max(1, min(24, max(visible_width(item.display_label()) for item in items)))


def _render_completion_item(item: CompletionItem, *, selected: bool, label_width: int, width: int) -> str:
    target_width = autowrap_safe_width(width)
    prefix = "  "
    label = item.display_label()
    if item.description and target_width > 24:
        content_width = max(1, target_width - visible_width(prefix))
        label_width = max(1, min(label_width, content_width // 2))
        description_width = max(0, content_width - label_width - 2)
        rendered_label = truncate_to_width(label, max_width=label_width, ellipsis="", pad=True)
        rendered_description = truncate_to_width(item.description, max_width=description_width, ellipsis="")
        rendered_content = f"{rendered_label}  {rendered_description}"
        line = truncate_to_width(f"{prefix}{rendered_content}", max_width=target_width, ellipsis="")
        return _selected_completion_line(line) if selected else line
    rendered_label = truncate_to_width(label, max_width=max(1, min(label_width, target_width - visible_width(prefix))), ellipsis="")
    line = truncate_to_width(f"{prefix}{rendered_label}", max_width=target_width, ellipsis="")
    return _selected_completion_line(line) if selected else line


def _selected_completion_line(line: str) -> str:
    return apply_theme_style(line, {"color": 33, "bold": True})


def _render_composer_text(
    text: str,
    *,
    display_cursor: int,
    prompt: str,
    continuation_prompt: str,
    width: int,
    selection_display_range: tuple[int, int] | None = None,
    selection_style: ThemeStyle | None = None,
) -> tuple[list[str], CursorDeclaration]:
    lines: list[str] = []
    cursor: CursorDeclaration | None = None
    consumed = 0
    line_width = autowrap_safe_width(width)
    logical_lines = text.split("\n")
    for logical_index, logical_line in enumerate(logical_lines):
        prefix = prompt if logical_index == 0 else continuation_prompt
        available = max(1, line_width - visible_width(prefix))
        wrapped = _word_wrap_line(logical_line, width=available)
        line_start = consumed
        for wrap_index, chunk in enumerate(wrapped):
            row_prefix = prefix if (logical_index == 0 and wrap_index == 0) else continuation_prompt
            chunk_start = line_start + chunk.start_width
            chunk_end = line_start + chunk.end_width
            chunk_text = _highlight_selection_in_chunk(
                chunk.text,
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                selection_display_range=selection_display_range,
                selection_style=selection_style,
            )
            lines.append(truncate_to_width(row_prefix + chunk_text, max_width=line_width))
            if cursor is None and chunk_start <= display_cursor <= chunk_end:
                column = visible_width(row_prefix) + max(0, display_cursor - chunk_start)
                cursor = CursorDeclaration(row=len(lines) - 1, column=column)
        consumed += visible_width(logical_line)
        if logical_index < len(logical_lines) - 1:
            if cursor is None and consumed >= display_cursor:
                cursor = CursorDeclaration(row=len(lines) - 1, column=visible_width(lines[-1]))
            consumed += 1
    if not lines:
        lines.append(prompt)
    if cursor is None:
        cursor = CursorDeclaration(row=len(lines) - 1, column=visible_width(lines[-1]))
    return lines, cursor


def _highlight_selection_in_chunk(
    text: str,
    *,
    chunk_start: int,
    chunk_end: int,
    selection_display_range: tuple[int, int] | None,
    selection_style: ThemeStyle | None,
) -> str:
    if selection_display_range is None:
        return text
    selection_start, selection_end = selection_display_range
    overlap_start = max(selection_start, chunk_start)
    overlap_end = min(selection_end, chunk_end)
    if overlap_start >= overlap_end:
        return text
    return highlight_selection_by_columns(
        text,
        selection_range=(overlap_start - chunk_start, overlap_end - chunk_start),
        selection_style=selection_style or DEFAULT_COMPOSER_SELECTION_STYLE,
    )


def _visual_segments(
    text: str,
    *,
    prompt: str,
    continuation_prompt: str,
    width: int,
) -> list[_VisualSegment]:
    segments: list[_VisualSegment] = []
    consumed = 0
    line_width = autowrap_safe_width(width)
    logical_lines = text.split("\n")
    row = 0
    for logical_index, logical_line in enumerate(logical_lines):
        prefix = prompt if logical_index == 0 else continuation_prompt
        available = max(1, line_width - visible_width(prefix))
        wrapped = _word_wrap_line(logical_line, width=available)
        line_start = consumed
        for chunk in wrapped:
            segments.append(
                _VisualSegment(
                    row=row,
                    start_width=line_start + chunk.start_width,
                    end_width=line_start + chunk.end_width,
                )
            )
            row += 1
        consumed += visible_width(logical_line)
        if logical_index < len(logical_lines) - 1:
            consumed += 1
    return segments or [_VisualSegment(row=0, start_width=0, end_width=0)]


def _find_visual_segment_index(segments: list[_VisualSegment], display_cursor: int) -> int:
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        if segment.start_width <= display_cursor < segment.end_width:
            return index
        if is_last and segment.start_width <= display_cursor <= segment.end_width:
            return index
    for index, segment in enumerate(segments):
        if display_cursor < segment.start_width:
            return max(0, index - 1)
    return len(segments) - 1


def _word_wrap_line(text: str, *, width: int) -> list[_WrappedChunk]:
    if text == "":
        return [_WrappedChunk("", 0, 0)]

    chunks: list[_WrappedChunk] = []
    clusters = grapheme_clusters(text)
    start = 0
    start_width = 0
    while start < len(clusters):
        remaining = clusters[start:]
        remaining_text = "".join(remaining)
        remaining_width = visible_width(remaining_text)
        if remaining_width <= width:
            chunks.append(_WrappedChunk(remaining_text, start_width, start_width + remaining_width))
            break

        break_index = _find_word_break(remaining, width=width)
        if break_index == 0:
            sliced = slice_by_column(remaining_text, start=0, length=width).text
            break_index = max(1, len(grapheme_clusters(sliced)))

        raw_chunk = "".join(remaining[:break_index]).rstrip()
        chunk_width = visible_width(raw_chunk)
        chunks.append(_WrappedChunk(raw_chunk, start_width, start_width + chunk_width))

        consumed = break_index
        while consumed < len(remaining) and remaining[consumed].isspace() and remaining[consumed] != "\n":
            consumed += 1
        start += consumed
        start_width += visible_width("".join(remaining[:consumed]))

    return chunks or [_WrappedChunk("", start_width, start_width)]


def _find_word_break(clusters: tuple[str, ...], *, width: int) -> int:
    current_width = 0
    last_space = -1
    for index, cluster in enumerate(clusters):
        cluster_width = visible_width(cluster)
        if current_width + cluster_width > width:
            if last_space > 0:
                return last_space
            return index
        current_width += cluster_width
        if cluster.isspace():
            last_space = index
    return len(clusters)


def _frame_result(
    lines: list[str],
    constraints: RenderConstraints,
    cursor: CursorDeclaration | None,
    *,
    cursor_offset: int,
) -> RenderResult:
    frame_cursor = None
    if cursor is not None:
        frame_cursor = CursorDeclaration(row=cursor.row + cursor_offset, column=cursor.column)
        if frame_cursor.row >= len(lines):
            frame_cursor = None
    return RenderResult.from_lines([RenderLine(line) for line in lines], constraints=constraints, cursor=frame_cursor)
