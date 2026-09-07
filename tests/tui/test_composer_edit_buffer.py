from __future__ import annotations

from loushang.tui.cell_width import visible_width
from loushang.tui.composer_edit_buffer import (
    ComposerEditBuffer,
    ComposerPasteMarker,
)


def test_composer_optional_undo_limit_is_bounded_without_changing_the_default():
    from loushang.tui.ui_parts.composer import Composer

    limited, ordinary = Composer(max_undo_depth=2), Composer()
    for value in ("one", "two", "three", "four"):
        limited.set_text(value)
        ordinary.set_text(value)
    for _ in range(4):
        limited.undo()
        ordinary.undo()
    assert limited.value == "two"
    assert ordinary.value == ""


def test_composer_edit_buffer_preserves_atom_value_and_display_text() -> None:
    buffer = ComposerEditBuffer()
    marker = ComposerPasteMarker(marker_id=1, text="a\nb\nc", label="[paste #1 +3 lines]")

    buffer.insert_text("prefix")
    buffer.insert_atoms([marker])

    assert buffer.value == "prefixa\nb\nc"
    assert buffer.display_text == "prefix[paste #1 +3 lines]"
    assert buffer.display_cursor == visible_width("prefix[paste #1 +3 lines]")


def test_composer_edit_buffer_deletes_paste_marker_atomically_and_undoes() -> None:
    buffer = ComposerEditBuffer()
    marker = ComposerPasteMarker(marker_id=1, text="a\nb\nc", label="[paste #1 +3 lines]")

    buffer.insert_atoms([marker])

    assert buffer.delete_backward()
    assert buffer.value == ""

    assert buffer.undo()
    assert buffer.value == "a\nb\nc"
    assert buffer.display_text == "[paste #1 +3 lines]"


def test_composer_edit_buffer_moves_words_across_marker_atoms() -> None:
    buffer = ComposerEditBuffer()
    marker = ComposerPasteMarker(marker_id=1, text="a\nb\nc", label="[paste #1 +3 lines]")

    buffer.insert_text("prefix")
    buffer.insert_atoms([marker])
    buffer.insert_text("suffix")

    buffer.move_to_start()
    assert buffer.move_word_right()
    assert buffer.cursor == 6
    assert buffer.move_word_right()
    assert buffer.cursor == 7
    assert buffer.move_word_right()
    assert buffer.cursor == 13

    buffer.move_to_end()
    assert buffer.move_word_left()
    assert buffer.cursor == 7
    assert buffer.move_word_left()
    assert buffer.cursor == 6


def test_composer_edit_buffer_maps_value_index_and_lines_cursor() -> None:
    buffer = ComposerEditBuffer()
    marker = ComposerPasteMarker(marker_id=1, text="a\nb\nc", label="[paste #1 +3 lines]")

    buffer.insert_text("x")
    buffer.insert_atoms([marker])
    buffer.insert_text("y")

    buffer.move_cursor_to_value_index(2)
    assert buffer.cursor == 1

    buffer.move_to_end()
    lines, cursor_line, cursor_col = buffer.lines_and_cursor()

    assert lines == ("xa", "b", "cy")
    assert (cursor_line, cursor_col) == (2, 2)


def test_composer_edit_buffer_replaces_completion_prefix() -> None:
    buffer = ComposerEditBuffer()
    buffer.insert_text("/he")

    assert buffer.completion_prefix_range() == (0, 3)
    assert buffer.completion_prefix_text() == "/he"

    buffer.replace_range(0, 3, "/help")

    assert buffer.value == "/help"
    assert buffer.cursor == 5
    assert buffer.undo()
    assert buffer.value == "/he"


def test_composer_edit_buffer_apply_edit_records_composite_change_as_one_undo_step() -> None:
    buffer = ComposerEditBuffer()
    buffer.insert_text("abcdef")

    changed = buffer.apply_edit(
        lambda: (
            buffer.delete_range(1, 4, record=False),
            buffer.insert_text("X", record=False),
        )
    )

    assert changed
    assert buffer.value == "aXef"

    assert buffer.undo()
    assert buffer.value == "abcdef"

    assert buffer.redo()
    assert buffer.value == "aXef"


def test_composer_edit_buffer_apply_edit_ignores_cursor_only_changes() -> None:
    buffer = ComposerEditBuffer()
    buffer.insert_text("abc")

    changed = buffer.apply_edit(buffer.move_to_start)

    assert not changed
    assert buffer.cursor == 0
    assert buffer.undo()
    assert buffer.value == ""
