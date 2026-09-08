from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from loushang.tui.cell_width import grapheme_clusters, visible_width
from loushang.tui.undo_stack import UndoStack
from loushang.tui.word_navigation import word_left_index, word_right_index

__all__ = [
    "ComposerAtom",
    "ComposerEditBuffer",
    "ComposerPasteMarker",
    "ComposerSnapshot",
    "atom_display",
    "atom_kind",
    "atom_value",
    "cursor_advance",
    "text_atoms",
]


@dataclass(frozen=True, slots=True)
class ComposerPasteMarker:
    marker_id: int
    text: str
    label: str


ComposerAtom = str | ComposerPasteMarker
ComposerSnapshot = tuple[tuple[ComposerAtom, ...], int]


@dataclass(slots=True)
class ComposerEditBuffer:
    max_undo_depth: int | None = field(default=None, kw_only=True)
    _atoms: list[ComposerAtom] = field(default_factory=list, repr=False)
    _cursor: int = 0
    _undo_stack: UndoStack[ComposerSnapshot] = field(default_factory=UndoStack, repr=False)
    _redo_stack: UndoStack[ComposerSnapshot] = field(default_factory=UndoStack, repr=False)

    def __post_init__(self) -> None:
        if self.max_undo_depth is not None:
            self._undo_stack = UndoStack(max_depth=self.max_undo_depth)
            self._redo_stack = UndoStack(max_depth=self.max_undo_depth)

    def __len__(self) -> int:
        return len(self._atoms)

    @property
    def atoms(self) -> tuple[ComposerAtom, ...]:
        return tuple(self._atoms)

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def value(self) -> str:
        return "".join(atom_value(atom) for atom in self._atoms)

    @property
    def display_text(self) -> str:
        return "".join(atom_display(atom) for atom in self._atoms)

    @property
    def display_cursor(self) -> int:
        return sum(cursor_advance(atom) for atom in self._atoms[: self._cursor])

    def set_text(self, text: str, *, record: bool = False) -> None:
        self.set_atoms(text_atoms(text), record=record)

    def set_atoms(self, atoms: Sequence[ComposerAtom], *, cursor: int | None = None, record: bool = False) -> None:
        next_atoms = list(atoms)
        next_cursor = len(next_atoms) if cursor is None else max(0, min(cursor, len(next_atoms)))
        if self._atoms == next_atoms and self._cursor == next_cursor:
            return
        if record:
            self.push_undo()
        self._atoms = next_atoms
        self._cursor = next_cursor
        if record:
            self._redo_stack.clear()

    def clear(self) -> None:
        self._atoms.clear()
        self._cursor = 0
        self._undo_stack.clear()
        self._redo_stack.clear()

    def insert_text(self, text: str, *, record: bool = True) -> None:
        self.insert_atoms(text_atoms(text), record=record)

    def insert_atoms(self, atoms: Sequence[ComposerAtom], *, record: bool = True) -> None:
        inserted = list(atoms)
        if not inserted:
            return
        if record:
            self.push_undo()
        self._atoms[self._cursor : self._cursor] = inserted
        self._cursor += len(inserted)
        self._redo_stack.clear()

    def delete_backward(self, *, record: bool = True) -> bool:
        if self._cursor <= 0:
            return False
        if record:
            self.push_undo()
        del self._atoms[self._cursor - 1]
        self._cursor -= 1
        self._redo_stack.clear()
        return True

    def delete_forward(self, *, record: bool = True) -> bool:
        if self._cursor >= len(self._atoms):
            return False
        if record:
            self.push_undo()
        del self._atoms[self._cursor]
        self._redo_stack.clear()
        return True

    def delete_range(self, start: int, end: int, *, record: bool = True) -> tuple[ComposerAtom, ...]:
        start, end = self._clamp_range(start, end)
        if start == end:
            return ()
        removed = tuple(self._atoms[start:end])
        if record:
            self.push_undo()
        del self._atoms[start:end]
        self._cursor = start
        self._redo_stack.clear()
        return removed

    def replace_range(self, start: int, end: int, text: str, *, record: bool = True) -> tuple[ComposerAtom, ...]:
        return self.replace_atoms(start, end, text_atoms(text), record=record)

    def replace_atoms(
        self,
        start: int,
        end: int,
        atoms: Sequence[ComposerAtom],
        *,
        record: bool = True,
    ) -> tuple[ComposerAtom, ...]:
        start, end = self._clamp_range(start, end)
        inserted = list(atoms)
        removed = tuple(self._atoms[start:end])
        if list(removed) == inserted:
            self._cursor = start + len(inserted)
            return removed
        if record:
            self.push_undo()
        self._atoms[start:end] = inserted
        self._cursor = start + len(inserted)
        self._redo_stack.clear()
        return removed

    def move_left(self) -> bool:
        if self._cursor <= 0:
            return False
        self._cursor -= 1
        return True

    def move_right(self) -> bool:
        if self._cursor >= len(self._atoms):
            return False
        self._cursor += 1
        return True

    def move_to_start(self) -> bool:
        if self._cursor == 0:
            return False
        self._cursor = 0
        return True

    def move_to_end(self) -> bool:
        end = len(self._atoms)
        if self._cursor == end:
            return False
        self._cursor = end
        return True

    def move_to_line_start(self) -> bool:
        target = self.line_start_index()
        if target == self._cursor:
            return False
        self._cursor = target
        return True

    def move_to_line_end(self) -> bool:
        target = self.line_end_index()
        if target == self._cursor:
            return False
        self._cursor = target
        return True

    def move_word_left(self) -> bool:
        target = self.word_left_index()
        if target == self._cursor:
            return False
        self._cursor = target
        return True

    def move_word_right(self) -> bool:
        target = self.word_right_index()
        if target == self._cursor:
            return False
        self._cursor = target
        return True

    def move_cursor_to_value_index(self, value_index: int) -> bool:
        value_index = max(0, value_index)
        previous = self._cursor
        remaining = value_index
        for index, atom in enumerate(self._atoms):
            width = len(atom_value(atom))
            if remaining <= 0:
                self._cursor = index
                return self._cursor != previous
            if remaining < width:
                self._cursor = index
                return self._cursor != previous
            remaining -= width
        self._cursor = len(self._atoms)
        return self._cursor != previous

    def move_cursor_to_display_width(self, target_width: int) -> bool:
        target_width = max(0, target_width)
        current_width = 0
        for index, atom in enumerate(self._atoms):
            atom_width = cursor_advance(atom)
            if target_width <= current_width:
                self._cursor = index
                return False
            next_width = current_width + atom_width
            if target_width == next_width:
                self._cursor = index + 1
                return False
            if target_width < next_width:
                self._cursor = index if target_width - current_width < atom_width / 2 else index + 1
                return True
            current_width = next_width
        self._cursor = len(self._atoms)
        return False

    def line_start_index(self) -> int:
        index = self._cursor
        while index > 0 and atom_value(self._atoms[index - 1]) != "\n":
            index -= 1
        return index

    def line_end_index(self) -> int:
        index = self._cursor
        while index < len(self._atoms) and atom_value(self._atoms[index]) != "\n":
            index += 1
        return index

    def word_left_index(self) -> int:
        return word_left_index(self._atoms, self._cursor, atom_kind, atomic_kinds={"newline", "paste_marker"})

    def word_right_index(self) -> int:
        return word_right_index(self._atoms, self._cursor, atom_kind, atomic_kinds={"newline", "paste_marker"})

    def lines_and_cursor(self) -> tuple[tuple[str, ...], int, int]:
        text = self.value
        lines = tuple(text.split("\n")) or ("",)
        before_cursor = "".join(atom_value(atom) for atom in self._atoms[: self._cursor])
        cursor_line = before_cursor.count("\n")
        cursor_col = len(before_cursor.rsplit("\n", 1)[-1])
        return lines, cursor_line, cursor_col

    def set_lines_and_cursor(self, lines: tuple[str, ...], *, cursor_line: int, cursor_col: int) -> None:
        if not lines:
            lines = ("",)
        text = "\n".join(lines)
        cursor_line = max(0, min(cursor_line, len(lines) - 1))
        cursor_col = max(0, min(cursor_col, len(lines[cursor_line])))
        prefix_lines = [*lines[:cursor_line], lines[cursor_line][:cursor_col]]
        before_cursor = "\n".join(prefix_lines)
        atoms = text_atoms(text)
        cursor = min(len(atoms), len(text_atoms(before_cursor)))
        self.set_atoms(atoms, cursor=cursor, record=False)

    def completion_prefix_range(self) -> tuple[int, int]:
        start = self._cursor
        while start > 0:
            value = atom_value(self._atoms[start - 1])
            if value.isspace() or value == "\n":
                break
            start -= 1
        return start, self._cursor

    def completion_prefix_text(self) -> str:
        start, end = self.completion_prefix_range()
        return "".join(atom_value(atom) for atom in self._atoms[start:end])

    def push_undo(self) -> None:
        self._undo_stack.push(self._snapshot())
        self._redo_stack.clear()

    def undo(self) -> bool:
        snapshot = self._undo_stack.pop()
        if snapshot is None:
            return False
        self._redo_stack.push(self._snapshot())
        self._restore(snapshot)
        return True

    def redo(self) -> bool:
        snapshot = self._redo_stack.pop()
        if snapshot is None:
            return False
        self._undo_stack.push(self._snapshot())
        self._restore(snapshot)
        return True

    def clear_redo(self) -> None:
        self._redo_stack.clear()

    def apply_edit(self, edit: Callable[[], object]) -> bool:
        snapshot = self._snapshot()
        previous_atoms = snapshot[0]
        edit()
        if tuple(self._atoms) == previous_atoms:
            return False
        self._undo_stack.push(snapshot)
        self._redo_stack.clear()
        return True

    def _clamp_range(self, start: int, end: int) -> tuple[int, int]:
        length = len(self._atoms)
        start = max(0, min(start, length))
        end = max(0, min(end, length))
        if end < start:
            end = start
        return start, end

    def _snapshot(self) -> ComposerSnapshot:
        return tuple(self._atoms), self._cursor

    def _restore(self, snapshot: ComposerSnapshot) -> None:
        atoms, cursor = snapshot
        self._atoms = list(atoms)
        self._cursor = max(0, min(cursor, len(self._atoms)))


def atom_value(atom: ComposerAtom) -> str:
    if isinstance(atom, ComposerPasteMarker):
        return atom.text
    return atom


def atom_display(atom: ComposerAtom) -> str:
    if isinstance(atom, ComposerPasteMarker):
        return atom.label
    return atom


def atom_kind(atom: ComposerAtom) -> str:
    if isinstance(atom, ComposerPasteMarker):
        return "paste_marker"
    if atom == "\n":
        return "newline"
    if atom.isspace():
        return "space"
    if atom.isalnum() or atom == "_":
        return "word"
    return "punctuation"


def cursor_advance(atom: ComposerAtom) -> int:
    if isinstance(atom, ComposerPasteMarker):
        return visible_width(atom.label)
    if atom == "\n":
        return 1
    return visible_width(atom)


def text_atoms(text: str) -> list[ComposerAtom]:
    return list(grapheme_clusters(text))
