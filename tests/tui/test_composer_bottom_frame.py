from __future__ import annotations

from typing import Any

from loushang.tui import (
    BottomFrame,
    CompletionApplication,
    CompletionCancellationToken,
    CompletionContext,
    CompletionItem,
    CompletionProvider,
    CompletionSuggestions,
    Composer,
    PendingQueueView,
    PendingSection,
    RenderConstraints,
    RenderLine,
    RenderResult,
    ScreenLayout,
    ScreenRegion,
    ScreenRegionStack,
    SlashCommand,
    SlashCommandCompletionProvider,
    StatusBar,
    StatusField,
    ThemeResolver,
    WorkingLine,
    strip_control_sequences,
    visible_width,
)
from loushang.tui.ui_parts.composer import BottomFrame as ModuleBottomFrame
from loushang.tui.ui_parts.composer import Composer as ModuleComposer
from loushang.tui.ui_parts.layout import ScreenLayout as ModuleScreenLayout
from loushang.tui.ui_parts.layout import ScreenRegion as ModuleScreenRegion
from loushang.tui.ui_parts.layout import ScreenRegionStack as ModuleScreenRegionStack
from loushang.tui.ui_parts.pending import PendingQueueView as ModulePendingQueueView
from loushang.tui.ui_parts.pending import PendingSection as ModulePendingSection
from loushang.tui.ui_parts.status import StatusBar as ModuleStatusBar
from loushang.tui.ui_parts.status import StatusField as ModuleStatusField
from loushang.tui.ui_parts.status import WorkingLine as ModuleWorkingLine


class StaticRenderable:
    def __init__(self, *lines: str) -> None:
        self.lines = lines

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines(
            [RenderLine(line) for line in self.lines[: constraints.max_height]],
            constraints=constraints,
        )


class ExclusiveStaticRenderable(StaticRenderable):
    exclusive_bottom = True


class BottomExclusiveStaticRenderable(StaticRenderable):
    presentation = "bottom-exclusive"


def test_split_ui_part_imports_are_compatible() -> None:
    assert BottomFrame is ModuleBottomFrame
    assert Composer is ModuleComposer
    assert PendingQueueView is ModulePendingQueueView
    assert PendingSection is ModulePendingSection
    assert ScreenLayout is ModuleScreenLayout
    assert ScreenRegion is ModuleScreenRegion
    assert ScreenRegionStack is ModuleScreenRegionStack
    assert StatusBar is ModuleStatusBar
    assert StatusField is ModuleStatusField
    assert WorkingLine is ModuleWorkingLine


def test_bottom_frame_exclusive_surface_suppresses_composer_and_status() -> None:
    frame = BottomFrame(
        composer=Composer(prompt="› "),
        surface=ExclusiveStaticRenderable("Select Model", "", "> 1. kimi"),
        status_bar=StatusBar((StatusField("kimi"),)),
    )

    lines = rendered_text(frame, width=40, height=8)

    assert lines == ("Select Model", "", "> 1. kimi")


def test_bottom_frame_bottom_exclusive_presentation_suppresses_composer_and_status() -> None:
    frame = BottomFrame(
        composer=Composer(prompt="› "),
        surface=BottomExclusiveStaticRenderable("Select Model", "", "> 1. kimi"),
        status_bar=StatusBar((StatusField("kimi"),)),
    )

    lines = rendered_text(frame, width=40, height=8)

    assert lines == ("Select Model", "", "> 1. kimi")


def rendered_text(part: Any, *, width: int = 20, height: int = 10) -> tuple[str, ...]:
    result = part.render(RenderConstraints(width=width, max_height=height))
    return tuple(line.text for line in result.lines)


def test_composer_soft_wraps_long_input_from_the_beginning_and_maps_cursor() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abcdef")

    result = composer.render(RenderConstraints(width=6, max_height=4))

    assert tuple(line.text for line in result.lines) == ("> abc", "  def")
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (1, 5)


def test_composer_reserves_last_terminal_cell_for_autowrap_safety() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abcdef")

    result = composer.render(RenderConstraints(width=6, max_height=4))

    assert all(visible_width(line.text) <= 5 for line in result.lines)


def test_composer_wraps_at_word_boundaries_when_possible() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello world")

    result = composer.render(RenderConstraints(width=9, max_height=4))

    assert tuple(line.text for line in result.lines) == ("> hello", "  world")
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (1, 7)


def test_composer_explicit_newline_grows_upward_as_multiple_visual_lines() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello")
    composer.insert_newline()
    composer.insert_text("world")

    result = composer.render(RenderConstraints(width=20, max_height=5))

    assert tuple(line.text for line in result.lines) == ("> hello", "  world")
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (1, 7)
    assert composer.value == "hello\nworld"


def test_multiline_paste_inserts_text_without_submitting_and_undoes_as_one_step() -> None:
    composer = Composer(prompt="> ")

    composer.paste("a\nb")

    assert composer.value == "a\nb"
    assert composer.submitted is False

    composer.undo()

    assert composer.value == ""


def test_paste_records_single_undo_snapshot_for_redo_after_extra_undo() -> None:
    composer = Composer(prompt="> ")

    composer.paste("a\nb")
    composer.undo()
    composer.undo()
    composer.redo()

    assert composer.value == "a\nb"


def test_paste_normalizes_line_endings_and_tabs_atomically() -> None:
    composer = Composer(prompt="> ")

    composer.paste("a\r\nb\tc\rd")

    assert composer.value == "a\nb   c\nd"

    composer.undo()

    assert composer.value == ""


def test_path_paste_after_word_character_inserts_readability_space() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("cat")

    composer.paste("/tmp/file.py")

    assert composer.value == "cat /tmp/file.py"


def test_path_paste_after_space_does_not_insert_extra_space() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("cat ")

    composer.paste("/tmp/file.py")

    assert composer.value == "cat /tmp/file.py"


def test_large_paste_marker_preserves_payload_and_deletes_atomically() -> None:
    composer = Composer(prompt="> ", large_paste_line_threshold=2)

    composer.paste("a\nb\nc")

    assert composer.value == "a\nb\nc"
    assert rendered_text(composer, width=30) == ("> [paste #1 +3 lines]",)

    composer.delete_backward()

    assert composer.value == ""

    composer.undo()

    assert composer.value == "a\nb\nc"
    assert rendered_text(composer, width=30) == ("> [paste #1 +3 lines]",)


def test_large_paste_marker_forward_delete_is_atomic() -> None:
    composer = Composer(prompt="> ", large_paste_line_threshold=2)

    composer.paste("a\nb\nc")
    composer.move_to_line_start()
    composer.delete_forward()

    assert composer.value == ""

    composer.undo()

    assert composer.value == "a\nb\nc"


def test_composer_selection_extends_and_clears_on_plain_movement() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abc")

    composer.select_char_left()
    composer.select_char_left()

    assert composer.selected_range == (1, 3)

    composer.move_left()

    assert composer.selected_range is None


def test_composer_visual_movement_attempts_clear_selection_at_boundaries() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abc")
    composer.select_char_left()

    assert not composer.move_visual_up(width=80)

    assert composer.selected_range is None

    composer.select_char_left()
    composer.move_visual_page_up(width=80, visible_lines=4)

    assert composer.selected_range is None


def test_composer_set_selection_moves_cursor_to_focus() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abc")

    composer.set_selection(0, 2)
    composer.insert_text("x")

    assert composer.value == "xc"


def test_composer_typing_replaces_selection_in_one_undo_step() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello")
    composer.select_word_left()

    composer.insert_text("bye")

    assert composer.value == "bye"
    assert composer.selected_range is None

    composer.undo()

    assert composer.value == "hello"
    assert composer.selected_range is None


def test_composer_paste_replaces_selection_in_one_undo_step() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello")
    composer.select_word_left()

    composer.paste("bye")

    assert composer.value == "bye"

    composer.undo()

    assert composer.value == "hello"


def test_composer_backspace_and_delete_remove_selection_without_adjacent_atoms() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abcd")
    composer.select_char_left()
    composer.select_char_left()

    composer.delete_backward()

    assert composer.value == "ab"

    composer.undo()
    composer.move_to_line_end()
    composer.select_char_left()
    composer.select_char_left()
    composer.delete_forward()

    assert composer.value == "ab"


def test_composer_kill_commands_kill_selection_only() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("alpha beta")
    composer.select_word_left()

    composer.kill_to_line_start()

    assert composer.value == "alpha "
    assert composer.kill_ring[0] == "beta"

    composer.undo()
    composer.move_to_line_end()
    composer.select_word_left()
    composer.kill_to_line_end()

    assert composer.value == "alpha "
    assert composer.kill_ring[0] == "beta"


def test_composer_yank_replaces_selection_and_yank_pop_still_rotates() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("one")
    composer.select_word_left()
    composer.kill_to_line_start()
    composer.insert_text("two")
    composer.select_word_left()
    composer.kill_to_line_start()
    composer.insert_text("target")
    composer.select_word_left()

    composer.yank()

    assert composer.value == "two"

    composer.yank_pop()

    assert composer.value == "one"


def test_composer_selection_uses_atom_indexes_for_paste_markers() -> None:
    composer = Composer(prompt="> ", large_paste_line_threshold=2)
    composer.insert_text("x")
    composer.paste("a\nb\nc")

    composer.select_char_left()

    assert composer.selected_range == (1, 2)

    composer.delete_backward()

    assert composer.value == "x"


def test_composer_selection_handles_grapheme_clusters() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("你🙂a")

    composer.select_char_left()
    composer.select_char_left()

    assert composer.selected_range == (1, 3)

    composer.insert_text("x")

    assert composer.value == "你x"


def test_composer_render_highlights_selected_text() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abc")
    composer.select_char_left()

    assert rendered_text(composer, width=20) == ("> ab\x1b[7mc\x1b[27m",)


def test_composer_selection_highlight_uses_editor_selection_theme_token() -> None:
    composer = Composer(
        prompt="> ",
        theme=ThemeResolver(defaults={"editor.selection": {"color": "cyan", "bold": True}}),
    )
    composer.insert_text("abc")
    composer.select_char_left()

    raw = rendered_text(composer, width=20)[0]

    assert strip_control_sequences(raw) == "> abc"
    assert "\x1b[1;36mc\x1b[22;39m" in raw


def test_composer_completion_navigation_does_not_share_text_selection_state() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("ab")
    composer.set_completion_items([CompletionItem(value="abc"), CompletionItem(value="abd")])

    composer.select_char_left()
    composer.select_next_completion()

    assert composer.selected_range == (1, 2)

    composer.apply_selected_completion()

    assert composer.selected_range is None


def test_composer_history_and_undo_redo_clear_selection() -> None:
    composer = Composer(prompt="> ")
    composer.add_history("old")
    composer.insert_text("new")
    composer.select_word_left()

    composer.history_previous()

    assert composer.value == "old"
    assert composer.selected_range is None

    composer.select_word_left()
    composer.insert_text("fresh")
    composer.select_word_left()
    composer.undo()

    assert composer.selected_range is None

    composer.select_word_left()
    composer.redo()

    assert composer.selected_range is None


def test_large_paste_marker_is_atomic_for_word_backward_operations() -> None:
    composer = Composer(prompt="> ", large_paste_line_threshold=2)

    composer.insert_text("prefix")
    composer.paste("a\nb\nc")

    composer.delete_word_backward()

    assert composer.value == "prefix"

    composer.undo()
    composer.move_word_left()
    composer.delete_forward()

    assert composer.value == "prefix"


def test_large_paste_marker_is_atomic_for_word_forward_operations() -> None:
    composer = Composer(prompt="> ", large_paste_line_threshold=2)

    composer.paste("a\nb\nc")
    composer.insert_text("suffix")
    composer.move_to_line_start()

    composer.delete_word_forward()

    assert composer.value == "suffix"


def test_long_single_line_paste_marker_preserves_payload_and_deletes_atomically() -> None:
    composer = Composer(prompt="> ", large_paste_char_threshold=5)

    composer.paste("abcdef")

    assert composer.value == "abcdef"
    assert rendered_text(composer, width=30) == ("> [paste #1 6 chars]",)

    composer.delete_backward()

    assert composer.value == ""

    composer.undo()

    assert composer.value == "abcdef"
    assert rendered_text(composer, width=30) == ("> [paste #1 6 chars]",)


def test_composer_edits_user_visible_grapheme_clusters_atomically() -> None:
    for text in ("👍🏽", "e\u0301", "👨\u200d👩\u200d👧\u200d👦"):
        composer = Composer(prompt="> ")
        composer.insert_text(text)

        composer.delete_backward()

        assert composer.value == ""

    composer = Composer(prompt="> ")
    composer.insert_text("a👍🏽b")

    composer.move_left()
    result = composer.render(RenderConstraints(width=20, max_height=3))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 5)

    composer.move_left()
    result = composer.render(RenderConstraints(width=20, max_height=3))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 3)


def test_composer_undo_redo_and_kill_ring_preserve_cursor_mapping() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello world")
    composer.move_cursor_to(5)

    composer.kill_to_line_end()

    assert composer.value == "hello"
    assert composer.kill_ring == (" world",)

    composer.yank()

    assert composer.value == "hello world"

    composer.undo()
    assert composer.value == "hello"

    composer.redo()
    assert composer.value == "hello world"


def test_composer_consecutive_kills_accumulate_in_emacs_order() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("alpha beta gamma")

    composer.delete_word_backward()
    composer.delete_word_backward()

    assert composer.value == "alpha "
    assert composer.kill_ring == ("beta gamma",)

    composer.insert_text("delta epsilon")
    composer.move_word_left()
    composer.kill_to_line_end()
    composer.kill_to_line_start()

    assert composer.value == ""
    assert composer.kill_ring[-1] == "alpha delta epsilon"


def test_composer_yank_pop_rotates_kill_ring_after_yank() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("alpha beta")
    composer.delete_word_backward()
    composer.insert_text(" gamma")
    composer.delete_word_backward()

    assert composer.kill_ring == ("beta", "gamma")

    composer.yank()
    assert composer.value == "alpha  gamma"

    composer.yank_pop()
    assert composer.value == "alpha  beta"

    composer.yank_pop()
    assert composer.value == "alpha  gamma"


def test_composer_undo_coalesces_consecutive_word_typing() -> None:
    composer = Composer(prompt="> ")

    composer.insert_text("h")
    composer.insert_text("e")
    composer.insert_text("l")
    composer.insert_text("l")
    composer.insert_text("o")
    composer.insert_text(" ")
    composer.insert_text("w")
    composer.insert_text("o")
    composer.insert_text("r")
    composer.insert_text("l")
    composer.insert_text("d")

    assert composer.value == "hello world"

    composer.undo()
    assert composer.value == "hello"

    composer.undo()
    assert composer.value == ""


def test_composer_horizontal_cursor_movement_and_line_boundaries() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello")

    composer.move_left()
    result = composer.render(RenderConstraints(width=20, max_height=3))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 6)

    composer.move_to_line_start()
    result = composer.render(RenderConstraints(width=20, max_height=3))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 2)

    composer.move_to_line_end()
    result = composer.render(RenderConstraints(width=20, max_height=3))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 7)

    composer.move_right()
    result = composer.render(RenderConstraints(width=20, max_height=3))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 7)


def test_composer_visual_up_down_tracks_wrapped_lines_by_cell_width() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abcd efgh ij")

    assert tuple(line.text for line in composer.render(RenderConstraints(width=7, max_height=5)).lines) == (
        "> abcd",
        "  efgh",
        "  ij",
    )

    composer.move_visual_up(width=7)
    result = composer.render(RenderConstraints(width=7, max_height=5))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (1, 4)

    composer.move_visual_up(width=7)
    result = composer.render(RenderConstraints(width=7, max_height=5))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 4)

    composer.move_visual_down(width=7)
    result = composer.render(RenderConstraints(width=7, max_height=5))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (1, 4)


def test_composer_visual_movement_preserves_column_when_snapping_across_wide_character() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("A中B\n123")
    composer.move_left()

    lower = composer.render(RenderConstraints(width=20, max_height=5))
    assert lower.cursor is not None
    assert (lower.cursor.row, lower.cursor.column) == (1, 4)

    composer.move_visual_up(width=20)
    upper = composer.render(RenderConstraints(width=20, max_height=5))
    assert upper.cursor is not None
    assert (upper.cursor.row, upper.cursor.column) == (0, 5)

    composer.move_visual_down(width=20)
    lower_again = composer.render(RenderConstraints(width=20, max_height=5))
    assert lower_again.cursor is not None
    assert (lower_again.cursor.row, lower_again.cursor.column) == (1, 4)


def test_composer_visual_page_movement_moves_by_visible_page() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("one\ntwo\nthree\nfour\nfive")

    composer.move_visual_page_up(width=20, visible_lines=3)
    result = composer.render(RenderConstraints(width=20, max_height=5))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (2, 6)

    composer.move_visual_page_down(width=20, visible_lines=3)
    result = composer.render(RenderConstraints(width=20, max_height=5))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (4, 6)


def test_composer_internal_scroll_keeps_moved_cursor_visible() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("one")
    composer.insert_newline()
    composer.insert_text("two")
    composer.insert_newline()
    composer.insert_text("three")
    composer.insert_newline()
    composer.insert_text("four")

    bottom = composer.render(RenderConstraints(width=20, max_height=2))
    assert tuple(line.text for line in bottom.lines) == ("  three", "  four")
    assert bottom.cursor is not None
    assert (bottom.cursor.row, bottom.cursor.column) == (1, 6)

    composer.move_cursor_to(0)
    top = composer.render(RenderConstraints(width=20, max_height=2))

    assert tuple(line.text for line in top.lines) == ("> one", "  two")
    assert top.cursor is not None
    assert (top.cursor.row, top.cursor.column) == (0, 2)


def test_composer_attaches_autocomplete_items_under_input_and_applies_selection() -> None:
    composer = Composer(prompt="> ")
    assert callable(getattr(composer, "set_completion_items", None))
    composer.insert_text("/he")
    composer.set_completion_items(
        (
            CompletionItem(value="/help", label="/help", description="Show help"),
            CompletionItem(value="/hello", label="/hello", description="Say hello"),
        )
    )

    result = composer.render(RenderConstraints(width=36, max_height=5))

    assert tuple(strip_control_sequences(line.text) for line in result.lines) == (
        "> /he",
        "",
        "  /help   Show help",
        "  /hello  Say hello",
    )
    assert result.lines[2].text.startswith("\x1b[1;38;5;33m  /help")
    assert "Show help\x1b[22;39m" in result.lines[2].text
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 5)

    composer.select_next_completion()
    composer.apply_selected_completion()

    assert composer.value == "/hello"
    assert rendered_text(composer, width=36, height=5) == ("> /hello",)


def test_composer_omits_completion_group_header_and_arrows() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("/")
    composer.set_completion_items(
        (
            CompletionItem(value="/help", label="/help", description="Show help"),
            CompletionItem(value="/quit", label="/quit", description="Quit"),
        ),
        group="Commands",
    )

    result = composer.render(RenderConstraints(width=36, max_height=5))

    assert tuple(strip_control_sequences(line.text) for line in result.lines) == (
        "> /",
        "",
        "  /help  Show help",
        "  /quit  Quit",
    )
    assert "Commands" not in "\n".join(strip_control_sequences(line.text) for line in result.lines)
    assert "->" not in "\n".join(strip_control_sequences(line.text) for line in result.lines)


def test_composer_completion_defaults_to_eight_visible_items() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("/")
    composer.set_completion_items(tuple(CompletionItem(value=f"/cmd{index}", label=f"/cmd{index}") for index in range(12)))

    result = composer.render(RenderConstraints(width=36, max_height=12))
    lines = tuple(strip_control_sequences(line.text) for line in result.lines)

    assert len(lines) == 10
    assert lines[:2] == ("> /", "")
    assert lines[-1] == "  /cmd7"


def test_composer_completion_provider_tracks_current_prefix_after_edits() -> None:
    composer = Composer(prompt="> ")
    assert callable(getattr(composer, "set_completion_provider", None))
    composer.set_completion_provider(
        CompletionProvider(
            (
                CompletionItem(value="/help", label="/help", description="Show help"),
                CompletionItem(value="/quit", label="/quit", description="Quit"),
            )
        )
    )

    composer.insert_text("/")
    assert tuple(strip_control_sequences(line.text) for line in composer.render(RenderConstraints(width=36, max_height=5)).lines) == (
        "> /",
        "",
        "  /help  Show help",
        "  /quit  Quit",
    )

    composer.insert_text("h")
    assert tuple(strip_control_sequences(line.text) for line in composer.render(RenderConstraints(width=36, max_height=5)).lines) == (
        "> /h",
        "",
        "  /help  Show help",
    )

    composer.delete_backward()
    assert tuple(strip_control_sequences(line.text) for line in composer.render(RenderConstraints(width=36, max_height=5)).lines) == (
        "> /",
        "",
        "  /help  Show help",
        "  /quit  Quit",
    )


class RecordingCompletionProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], int, int, bool]] = []

    def get_suggestions(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        *,
        force: bool = False,
    ) -> CompletionSuggestions | None:
        self.calls.append((lines, cursor_line, cursor_col, force))
        prefix = lines[cursor_line][:cursor_col]
        if not prefix.startswith("/"):
            return None
        return CompletionSuggestions(
            prefix=prefix,
            items=(CompletionItem(value="help", label="/help", description="Show help"),),
        )

    def apply_completion(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        item: CompletionItem,
        prefix: str,
    ) -> CompletionApplication:
        line = lines[cursor_line]
        before = line[: cursor_col - len(prefix)]
        after = line[cursor_col:]
        new_lines = list(lines)
        new_lines[cursor_line] = f"{before}/{item.value} {after}"
        return CompletionApplication(
            lines=tuple(new_lines),
            cursor_line=cursor_line,
            cursor_col=len(before) + len(item.value) + 2,
        )


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class RecordingAtCompletionProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], int, int, bool]] = []

    def get_suggestions(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        *,
        force: bool = False,
    ) -> CompletionSuggestions | None:
        self.calls.append((lines, cursor_line, cursor_col, force))
        prefix = lines[cursor_line][:cursor_col]
        if not prefix.startswith("@"):
            return None
        return CompletionSuggestions(
            prefix=prefix,
            items=(CompletionItem(value=f"{prefix}README.md", label="README.md"),),
            group="Files",
        )

    def apply_completion(
        self,
        lines: tuple[str, ...],
        cursor_line: int,
        cursor_col: int,
        item: CompletionItem,
        prefix: str,
    ) -> CompletionApplication:
        del prefix
        new_lines = list(lines)
        new_lines[cursor_line] = item.value
        return CompletionApplication(lines=tuple(new_lines), cursor_line=cursor_line, cursor_col=len(item.value))


def test_composer_provider_receives_lines_cursor_and_applies_provider_result() -> None:
    provider = RecordingCompletionProvider()
    composer = Composer(prompt="> ")
    composer.set_completion_provider(provider)

    composer.insert_text("/he")
    result = composer.render(RenderConstraints(width=36, max_height=5))

    assert provider.calls[-1] == (("/he",), 0, 3, False)
    assert tuple(strip_control_sequences(line.text) for line in result.lines) == (
        "> /he",
        "",
        "  /help  Show help",
    )

    composer.apply_selected_completion()

    assert composer.value == "/help "


def test_composer_debounces_symbol_completion_until_due_time() -> None:
    clock = FakeClock()
    provider = RecordingAtCompletionProvider()
    composer = Composer(
        prompt="> ",
        now=clock.now,
        completion_debounce_seconds=0.05,
        completion_min_interval_seconds=0.0,
    )
    composer.set_completion_provider(provider)
    provider.calls.clear()

    composer.insert_text("@R")

    assert provider.calls == []
    assert rendered_text(composer, width=36, height=4) == ("> @R",)

    clock.advance(0.049)
    assert rendered_text(composer, width=36, height=4) == ("> @R",)
    assert provider.calls == []

    clock.advance(0.001)
    result = composer.render(RenderConstraints(width=36, max_height=4))
    assert tuple(strip_control_sequences(line.text) for line in result.lines) == (
        "> @R",
        "",
        "  README.md",
    )
    assert result.lines[2].text.startswith("\x1b[1;38;5;33m  README.md")
    assert provider.calls == [(("@R",), 0, 2, False)]


def test_composer_cancels_pending_symbol_completion_when_input_changes() -> None:
    clock = FakeClock()
    provider = RecordingAtCompletionProvider()
    composer = Composer(
        prompt="> ",
        now=clock.now,
        completion_debounce_seconds=0.05,
        completion_min_interval_seconds=0.0,
    )
    composer.set_completion_provider(provider)
    provider.calls.clear()

    composer.insert_text("@R")
    clock.advance(0.025)
    composer.insert_text("E")
    clock.advance(0.05)
    rendered_text(composer, width=36, height=4)

    assert provider.calls == [(("@RE",), 0, 3, False)]


def test_composer_hides_stale_completion_items_while_next_request_is_debounced() -> None:
    clock = FakeClock()
    provider = RecordingAtCompletionProvider()
    composer = Composer(
        prompt="> ",
        now=clock.now,
        completion_debounce_seconds=0.05,
        completion_min_interval_seconds=0.0,
    )
    composer.set_completion_provider(provider)
    provider.calls.clear()

    composer.insert_text("@R")
    clock.advance(0.05)
    assert tuple(strip_control_sequences(line.text) for line in composer.render(RenderConstraints(width=36, max_height=4)).lines) == (
        "> @R",
        "",
        "  README.md",
    )

    composer.insert_text("E")

    assert tuple(strip_control_sequences(line.text) for line in composer.render(RenderConstraints(width=36, max_height=4)).lines) == (
        "> @RE",
    )

    clock.advance(0.05)
    assert tuple(strip_control_sequences(line.text) for line in composer.render(RenderConstraints(width=36, max_height=4)).lines) == (
        "> @RE",
        "",
        "  README.md",
    )


def test_composer_hides_stale_completion_items_when_provider_changes() -> None:
    class LabelProvider:
        def __init__(self, label: str) -> None:
            self.label = label

        def get_suggestions(self, context: CompletionContext) -> CompletionSuggestions | None:
            prefix = context.lines[context.cursor_line][: context.cursor_col]
            if not prefix.startswith("@"):
                return None
            return CompletionSuggestions(
                prefix=prefix,
                items=(CompletionItem(value=f"{prefix}{self.label}", label=self.label),),
            )

    clock = FakeClock()
    composer = Composer(
        prompt="> ",
        now=clock.now,
        completion_debounce_seconds=0.05,
        completion_min_interval_seconds=0.0,
    )
    composer.set_completion_provider(LabelProvider("old.md"))
    composer.insert_text("@R")
    clock.advance(0.05)
    assert tuple(strip_control_sequences(line.text) for line in composer.render(RenderConstraints(width=36, max_height=4)).lines) == (
        "> @R",
        "",
        "  old.md",
    )

    composer.set_completion_provider(LabelProvider("new.md"))

    assert tuple(strip_control_sequences(line.text) for line in composer.render(RenderConstraints(width=36, max_height=4)).lines) == (
        "> @R",
    )

    clock.advance(0.05)
    assert tuple(strip_control_sequences(line.text) for line in composer.render(RenderConstraints(width=36, max_height=4)).lines) == (
        "> @R",
        "",
        "  new.md",
    )


def test_composer_throttles_debounced_completion_after_recent_provider_call() -> None:
    clock = FakeClock()
    provider = RecordingAtCompletionProvider()
    composer = Composer(
        prompt="> ",
        now=clock.now,
        completion_debounce_seconds=0.01,
        completion_min_interval_seconds=0.05,
    )
    composer.set_completion_provider(provider)
    provider.calls.clear()

    composer.insert_text("@R")
    clock.advance(0.01)
    rendered_text(composer, width=36, height=4)
    assert provider.calls == [(("@R",), 0, 2, False)]

    composer.insert_text("E")
    clock.advance(0.01)
    rendered_text(composer, width=36, height=4)
    assert provider.calls == [(("@R",), 0, 2, False)]

    clock.advance(0.04)
    rendered_text(composer, width=36, height=4)
    assert provider.calls == [(("@R",), 0, 2, False), (("@RE",), 0, 3, False)]


def test_composer_force_refresh_requests_provider_completion() -> None:
    provider = RecordingCompletionProvider()
    composer = Composer(prompt="> ")
    composer.set_completion_provider(provider)
    composer.insert_text("plain")

    composer.refresh_completions(force=True)

    assert provider.calls[-1] == (("plain",), 0, 5, True)


def test_composer_passes_completion_context_to_context_provider() -> None:
    class ContextProvider:
        def __init__(self) -> None:
            self.contexts: list[CompletionContext] = []

        def get_suggestions(self, context: CompletionContext) -> CompletionSuggestions | None:
            self.contexts.append(context)
            return CompletionSuggestions(
                prefix=context.lines[context.cursor_line][: context.cursor_col],
                items=(CompletionItem(value="/help", label="/help"),),
            )

    provider = ContextProvider()
    composer = Composer(prompt="> ")
    composer.set_completion_provider(provider)

    composer.insert_text("/")

    context = provider.contexts[-1]
    assert context.lines == ("/",)
    assert (context.cursor_line, context.cursor_col) == (0, 1)
    assert context.force is False
    assert context.explicit is False
    assert not context.cancelled

    composer.refresh_completions(force=True, explicit=True)

    context = provider.contexts[-1]
    assert context.force is True
    assert context.explicit is True


def test_composer_cancels_pending_completion_context_when_input_changes() -> None:
    clock = FakeClock()
    provider = RecordingAtCompletionProvider()
    composer = Composer(
        prompt="> ",
        now=clock.now,
        completion_debounce_seconds=0.05,
        completion_min_interval_seconds=0.0,
    )
    composer.set_completion_provider(provider)

    composer.insert_text("@R")
    pending = composer._completion_pending
    assert pending is not None

    clock.advance(0.025)
    composer.insert_text("E")

    assert pending.cancellation_token.cancelled
    assert composer._completion_pending is not None
    assert composer._completion_pending.cancellation_token is not pending.cancellation_token


def test_cancelled_completion_token_exposes_reason() -> None:
    token = CompletionCancellationToken()

    token.cancel("superseded")

    assert token.cancelled
    assert token.reason == "superseded"


def test_composer_autocomplete_window_tracks_selected_item() -> None:
    composer = Composer(prompt="> ")
    composer.autocomplete_max_visible = 2
    composer.insert_text("/")
    composer.set_completion_items(
        (
            CompletionItem(value="/one", label="/one"),
            CompletionItem(value="/two", label="/two"),
            CompletionItem(value="/three", label="/three"),
            CompletionItem(value="/four", label="/four"),
        )
    )

    composer.select_next_completion()
    composer.select_next_completion()
    result = composer.render(RenderConstraints(width=24, max_height=4))
    lines = tuple(strip_control_sequences(line.text) for line in result.lines)

    assert lines == (
        "> /",
        "",
        "  /two",
        "  /three",
    )
    assert result.lines[3].text.startswith("\x1b[1;38;5;33m  /three")


def test_composer_preserves_selected_completion_when_items_refresh() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("/")
    composer.set_completion_items(
        (
            CompletionItem(value="/alpha", label="/alpha"),
            CompletionItem(value="/beta", label="/beta"),
            CompletionItem(value="/gamma", label="/gamma"),
        )
    )
    composer.select_next_completion()

    composer.set_completion_items(
        (
            CompletionItem(value="/beta", label="/beta"),
            CompletionItem(value="/alpha", label="/alpha"),
            CompletionItem(value="/gamma", label="/gamma"),
        )
    )

    result = composer.render(RenderConstraints(width=24, max_height=5))
    assert tuple(strip_control_sequences(line.text) for line in result.lines) == (
        "> /",
        "",
        "  /beta",
        "  /alpha",
        "  /gamma",
    )
    assert result.lines[2].text.startswith("\x1b[1;38;5;33m  /beta")


def test_composer_resets_selected_completion_when_prefix_changes() -> None:
    composer = Composer(prompt="> ")
    composer.set_completion_provider(
        SlashCommandCompletionProvider(
            (
                SlashCommand(name="session", description="Show session info and stats"),
                SlashCommand(name="settings", description="Open settings menu"),
                SlashCommand(name="resume", description="Resume a different session"),
                SlashCommand(name="share", description="Share session as a secret GitHub gist"),
                SlashCommand(name="scoped-models", description="Enable/disable models for Ctrl+P cycling"),
            )
        )
    )

    composer.insert_text("/s")
    lines = tuple(line.text for line in composer.render(RenderConstraints(width=72, max_height=8)).lines)
    share_line = next(line for line in lines if "/share" in strip_control_sequences(line))
    assert share_line.startswith("\x1b[1;38;5;33m")

    composer.insert_text("e")
    lines = tuple(line.text for line in composer.render(RenderConstraints(width=72, max_height=8)).lines)
    session_line = next(line for line in lines if "/session" in strip_control_sequences(line))
    share_line = next(line for line in lines if "/share" in strip_control_sequences(line))

    assert session_line.startswith("\x1b[1;38;5;33m")
    assert not share_line.startswith("\x1b[1;38;5;33m")


def test_composer_delete_word_backward_and_line_start_update_kill_ring_atomically() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("alpha beta gamma")

    composer.delete_word_backward()

    assert composer.value == "alpha beta "
    assert composer.kill_ring == ("gamma",)

    composer.undo()
    assert composer.value == "alpha beta gamma"

    composer.move_word_left()
    composer.kill_to_line_start()

    assert composer.value == "gamma"
    assert composer.kill_ring[-1] == "alpha beta "


def test_composer_history_navigation_restores_draft_after_browsing() -> None:
    composer = Composer(prompt="> ")
    composer.add_history("first")
    composer.add_history("second")
    composer.insert_text("draft")

    assert composer.history_previous() == "second"
    assert composer.value == "second"

    assert composer.history_previous() == "first"
    assert composer.value == "first"

    assert composer.history_next() == "second"
    assert composer.value == "second"

    assert composer.history_next() == "draft"
    assert composer.value == "draft"


def test_status_bar_omits_low_priority_fields_before_wrapping() -> None:
    status = StatusBar(
        [
            StatusField("model", priority=100),
            StatusField("very-long-branch-name", priority=10),
            StatusField("running", priority=80),
        ]
    )

    lines = rendered_text(status, width=16, height=1)

    assert lines == ("model | running",)


def test_status_bar_reserves_last_column_to_avoid_terminal_autowrap() -> None:
    status = StatusBar([StatusField("1234567890", priority=100)])

    lines = rendered_text(status, width=10, height=1)

    assert lines == ("123456\x1b[0m...\x1b[0m",)
    assert visible_width(lines[0]) == 9


def test_working_line_formats_elapsed_time_with_two_decimal_places() -> None:
    working = WorkingLine(label="Working", elapsed_seconds=3.012)

    assert rendered_text(working, width=24, height=1) == ("- Working 3.01s -------",)


def test_pending_queue_keeps_header_and_newest_items_under_height_pressure() -> None:
    pending = PendingQueueView(["old", "middle", "new"])

    assert rendered_text(pending, width=24, height=3) == (
        "Queued follow-up inputs",
        "-> middle",
        "-> new",
    )


def test_pending_queue_omits_empty_legacy_items() -> None:
    pending = PendingQueueView(())

    assert rendered_text(pending, width=24, height=3) == ()


def test_pending_queue_omits_empty_sections() -> None:
    pending = PendingQueueView(
        sections=(
            PendingSection(label="Messages to be submitted after next tool call", items=()),
            PendingSection(label="Messages to be submitted at end of turn", items=()),
        )
    )

    assert rendered_text(pending, width=40, height=4) == ()


def test_pending_queue_can_render_interruption_section_without_items() -> None:
    pending = PendingQueueView(
        sections=(
            PendingSection(
                label="Conversation interrupted - tell the model what to do differently.",
                marker="■",
                show_when_empty=True,
            ),
            PendingSection(
                label="Queued follow-up inputs",
                items=("继续",),
                hint="alt + ↑ edit last queued message",
            ),
        )
    )

    assert rendered_text(pending, width=72, height=6) == (
        "■ Conversation interrupted - tell the model what to do differently.",
        "",
        "• Queued follow-up inputs",
        "  ↳ 继续",
        "    alt + ↑ edit last queued message",
    )


def test_pending_queue_renders_only_sections_with_items() -> None:
    pending = PendingQueueView(
        sections=(
            PendingSection(label="Steer", items=(), hint="esc"),
            PendingSection(label="Follow-up", items=("next",)),
        )
    )

    assert rendered_text(pending, width=40, height=4) == ("• Follow-up", "  ↳ next")


def test_pending_queue_separates_steer_and_followup_sections_with_blank_row() -> None:
    pending = PendingQueueView(
        sections=(
            PendingSection(
                label="Messages to be submitted after next tool call",
                items=("继续",),
                hint="press esc to interrupt and send immediately",
                hint_placement="header",
            ),
            PendingSection(label="Queued follow-up inputs", items=("继续",), hint="alt + ↑ edit last queued message"),
        )
    )

    assert rendered_text(pending, width=120, height=6) == (
        "• Messages to be submitted after next tool call (press esc to interrupt and send immediately)",
        "  ↳ 继续",
        "",
        "• Queued follow-up inputs",
        "  ↳ 继续",
        "    alt + ↑ edit last queued message",
    )


def test_screen_region_stack_orders_regions_with_gaps_and_maps_cursor() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("cmd")
    stack = ScreenRegionStack(
        (
            ScreenRegion("working", StaticRenderable("working"), max_height=1, gap_after=1),
            ScreenRegion("pending", StaticRenderable("pending"), max_height=1),
            ScreenRegion("composer", composer, required=True, min_height=1, gap_after=1),
            ScreenRegion("status", StaticRenderable("status"), required=True, min_height=1, max_height=1),
        )
    )

    result = stack.render(RenderConstraints(width=20, max_height=6))

    assert tuple(line.text for line in result.lines) == (
        "working",
        "",
        "pending",
        "> cmd",
        "",
        "status",
    )
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (3, 5)


def test_screen_region_stack_drops_optional_regions_before_required_regions_under_height_pressure() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("cmd")
    stack = ScreenRegionStack(
        (
            ScreenRegion("working", StaticRenderable("working"), max_height=1, gap_after=1),
            ScreenRegion("pending", StaticRenderable("pending"), max_height=1),
            ScreenRegion("composer", composer, required=True, min_height=1, gap_after=1),
            ScreenRegion("status", StaticRenderable("status"), required=True, min_height=1, max_height=1),
        )
    )

    result = stack.render(RenderConstraints(width=20, max_height=2))

    assert tuple(line.text for line in result.lines) == ("> cmd", "status")
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 5)


def test_screen_layout_projects_pi_like_top_level_region_order() -> None:
    layout = ScreenLayout(
        header=StaticRenderable("header"),
        transcript=StaticRenderable("chat 1", "chat 2"),
        pending=StaticRenderable("pending"),
        status=StaticRenderable("status"),
        widgets_above_editor=(StaticRenderable("widget above"),),
        editor=StaticRenderable("editor"),
        widgets_below_editor=(StaticRenderable("widget below"),),
        footer=StaticRenderable("footer 1", "footer 2"),
    )

    assert tuple(region.name for region in layout.regions()) == (
        "header",
        "transcript",
        "pending",
        "status",
        "widget_above_editor:0",
        "editor",
        "widget_below_editor:0",
        "footer",
    )
    assert rendered_text(layout, width=24, height=10) == (
        "header",
        "chat 1",
        "chat 2",
        "pending",
        "status",
        "widget above",
        "editor",
        "widget below",
        "footer 1",
        "footer 2",
    )


def test_screen_layout_preserves_editor_status_and_footer_under_height_pressure() -> None:
    layout = ScreenLayout(
        header=StaticRenderable("header"),
        transcript=StaticRenderable("chat 1", "chat 2", "chat 3"),
        pending=StaticRenderable("pending"),
        status=StaticRenderable("status"),
        widgets_above_editor=(StaticRenderable("widget above"),),
        editor=StaticRenderable("editor"),
        widgets_below_editor=(StaticRenderable("widget below"),),
        footer=StaticRenderable("footer"),
    )

    assert rendered_text(layout, width=24, height=3) == (
        "status",
        "editor",
        "footer",
    )


def test_screen_layout_can_reserve_editor_height_before_transcript_budget() -> None:
    layout = ScreenLayout(
        transcript=StaticRenderable("chat 1", "chat 2", "chat 3", "chat 4"),
        editor=StaticRenderable("editor 1", "editor 2", "editor 3"),
        editor_min_height=3,
    )

    assert rendered_text(layout, width=24, height=5) == (
        "chat 1",
        "chat 2",
        "editor 1",
        "editor 2",
        "editor 3",
    )


def test_screen_layout_offsets_editor_cursor_after_top_regions() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("cmd")
    layout = ScreenLayout(
        header=StaticRenderable("header"),
        transcript=StaticRenderable("chat"),
        status=StaticRenderable("status"),
        editor=composer,
        footer=StaticRenderable("footer"),
    )

    result = layout.render(RenderConstraints(width=24, max_height=6))

    assert tuple(line.text for line in result.lines) == (
        "header",
        "chat",
        "status",
        "> cmd",
        "footer",
    )
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (3, 5)


def test_bottom_frame_projects_legacy_parts_to_named_regions() -> None:
    composer = Composer(prompt="> ")
    frame = BottomFrame(
        composer=composer,
        pending_queue=PendingQueueView(["queued"]),
        working_line=WorkingLine(label="Working", elapsed_seconds=1.0),
        status_bar=StatusBar([StatusField("model", priority=100)]),
    )

    assert tuple(region.name for region in frame.regions()) == ("working", "pending", "composer", "status")


def test_bottom_frame_preserves_status_last_row_and_composer_above_separator() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello")
    frame = BottomFrame(
        composer=composer,
        status_bar=StatusBar([StatusField("model", priority=100)]),
    )

    assert rendered_text(frame, width=20, height=4) == (
        "",
        "> hello",
        "",
        "model",
    )


def test_bottom_frame_hides_status_while_completion_list_is_visible() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("/")
    composer.set_completion_items(
        (
            CompletionItem(value="/help", label="/help", description="Show help"),
            CompletionItem(value="/quit", label="/quit", description="Quit"),
        ),
        group="Commands",
    )
    frame = BottomFrame(
        composer=composer,
        status_bar=StatusBar([StatusField("model", priority=100)]),
    )

    rendered = tuple(strip_control_sequences(line) for line in rendered_text(frame, width=36, height=5))

    assert rendered == (
        "",
        "> /",
        "",
        "  /help  Show help",
        "  /quit  Quit",
    )
    assert "model" not in rendered


def test_bottom_frame_releases_completion_height_after_completion_closes() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("/")
    frame = BottomFrame(
        composer=composer,
        status_bar=StatusBar([StatusField("model", priority=100)]),
    )
    composer.set_completion_items(
        (
            CompletionItem(value="/help", label="/help", description="Show help"),
            CompletionItem(value="/quit", label="/quit", description="Quit"),
        ),
    )

    expanded = tuple(strip_control_sequences(line) for line in rendered_text(frame, width=36, height=5))
    composer.delete_backward()
    composer.clear_completion_items()
    collapsed = tuple(strip_control_sequences(line) for line in rendered_text(frame, width=36, height=5))

    assert expanded == (
        "",
        "> /",
        "",
        "  /help  Show help",
        "  /quit  Quit",
    )
    assert collapsed == (
        "",
        "> ",
        "",
        "model",
    )


def test_bottom_frame_constrained_height_preserves_composer_over_status_when_needed() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello")
    frame = BottomFrame(
        composer=composer,
        pending_queue=PendingQueueView(["queued"]),
        working_line=WorkingLine(label="Working", elapsed_seconds=1.0),
        status_bar=StatusBar([StatusField("model", priority=100)]),
    )

    assert rendered_text(frame, width=20, height=1) == ("> hello",)
    assert rendered_text(frame, width=20, height=2) == ("> hello", "model")


def test_bottom_frame_maps_cursor_to_visible_composer_line_under_height_pressure() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("first")
    composer.insert_newline()
    composer.insert_text("second")
    frame = BottomFrame(
        composer=composer,
        status_bar=StatusBar([StatusField("model", priority=100)]),
    )

    result = frame.render(RenderConstraints(width=20, max_height=2))

    assert tuple(line.text for line in result.lines) == ("  second", "model")
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, 8)


def test_bottom_frame_orders_working_pending_composer_gap_and_status() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello")
    frame = BottomFrame(
        composer=composer,
        pending_queue=PendingQueueView(["queued"]),
        working_line=WorkingLine(label="Working", elapsed_seconds=1.25),
        status_bar=StatusBar([StatusField("model", priority=100)]),
    )

    assert rendered_text(frame, width=24, height=8) == (
        "",
        "- Working 1.25s -------",
        "",
        "Queued follow-up inputs",
        "-> queued",
        "",
        "> hello",
        "model",
    )


def test_bottom_frame_places_blank_rows_around_working_line_when_space_allows() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello")
    frame = BottomFrame(
        composer=composer,
        working_line=WorkingLine(label="Working", elapsed_seconds=2.5),
        status_bar=StatusBar([StatusField("model", priority=100)]),
    )

    assert rendered_text(frame, width=24, height=6) == (
        "",
        "- Working 2.50s -------",
        "",
        "> hello",
        "",
        "model",
    )


def test_bottom_frame_places_blank_row_above_composer_when_idle_space_allows() -> None:
    composer = Composer(prompt="> ")
    frame = BottomFrame(
        composer=composer,
        status_bar=StatusBar([StatusField("model", priority=100)]),
    )

    result = frame.render(RenderConstraints(width=24, max_height=4))

    assert tuple(line.text for line in result.lines) == (
        "",
        "> ",
        "",
        "model",
    )
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (1, 2)
