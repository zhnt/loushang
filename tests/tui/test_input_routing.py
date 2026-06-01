from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loushang.tui import (
    CompletionItem,
    CompletionProvider,
    Composer,
    FocusableMixin,
    InputEvent,
    InputIntent,
    InputReader,
    InputRouter,
    KeybindingConflict,
    KeybindingManager,
    RenderConstraints,
    RenderLine,
    RenderResult,
    Surface,
    SurfaceHost,
)


@dataclass(slots=True)
class DummyRenderable:
    text: str = "surface"

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines([RenderLine(self.text)], constraints=constraints)


class EscConsumer(FocusableMixin):
    def handle_input(self, event: Any) -> Any:
        if isinstance(event, InputEvent) and event.kind == "key" and event.key == "esc":
            return InputIntent(kind="surface_close")
        return None


def test_input_reader_groups_bracketed_paste_as_single_paste_event() -> None:
    reader = InputReader()

    events = reader.feed("a\x1b[200~b\nc\x1b[201~d")

    assert events == (
        InputEvent(kind="text", text="a"),
        InputEvent(kind="paste", text="b\nc"),
        InputEvent(kind="text", text="d"),
    )


def test_input_reader_buffers_bracketed_paste_across_feeds() -> None:
    reader = InputReader()

    assert reader.feed("\x1b[200~hello") == ()
    assert reader.feed(" world\x1b[201~") == (InputEvent(kind="paste", text="hello world"),)


def test_input_reader_sanitizes_terminal_controls_inside_paste() -> None:
    reader = InputReader()

    events = reader.feed("\x1b[200~hello\x1b[2Jworld\x1b[201~")

    assert events == (InputEvent(kind="paste", text="hello^[[2Jworld"),)


def test_input_reader_decodes_csi_u_control_letters_inside_paste() -> None:
    reader = InputReader()

    events = reader.feed("\x1b[200~a\x1b[106;5ub\x1b[73;5uc\x1b[201~")

    assert events == (InputEvent(kind="paste", text="a\nb\tc"),)


def test_input_reader_creates_resize_and_signal_events() -> None:
    reader = InputReader()

    assert reader.resize(columns=100, rows=40) == InputEvent(kind="resize", columns=100, rows=40)
    assert reader.signal("sigwinch") == InputEvent(kind="signal", signal="sigwinch")


def test_input_reader_normalizes_arrow_escape_sequences() -> None:
    reader = InputReader()

    events = reader.feed("\x1b[A\x1b[B\x1b[C\x1b[D")

    assert events == (
        InputEvent(kind="key", key="up"),
        InputEvent(kind="key", key="down"),
        InputEvent(kind="key", key="right"),
        InputEvent(kind="key", key="left"),
    )


def test_input_reader_normalizes_common_editor_control_keys() -> None:
    reader = InputReader()

    events = reader.feed("\x7f\x1b[3~\x01\x05\x0a\x0b\x15\x16\x17\x19\x1by\x1b\r\x1b[13;2~\x1b[1;3A")

    assert events == (
        InputEvent(kind="key", key="backspace"),
        InputEvent(kind="key", key="delete"),
        InputEvent(kind="key", key="ctrl+a"),
        InputEvent(kind="key", key="ctrl+e"),
        InputEvent(kind="key", key="ctrl+j"),
        InputEvent(kind="key", key="ctrl+k"),
        InputEvent(kind="key", key="ctrl+u"),
        InputEvent(kind="key", key="ctrl+v"),
        InputEvent(kind="key", key="ctrl+w"),
        InputEvent(kind="key", key="ctrl+y"),
        InputEvent(kind="key", key="alt+y"),
        InputEvent(kind="key", key="alt+enter"),
        InputEvent(kind="key", key="shift+enter"),
        InputEvent(kind="key", key="alt+up"),
    )


def test_input_reader_buffers_incomplete_escape_until_flush() -> None:
    reader = InputReader()

    assert reader.feed("\x1b") == ()
    assert reader.feed("[A") == (InputEvent(kind="key", key="up", raw="\x1b[A"),)

    assert reader.feed("\x1b") == ()
    assert reader.flush() == (InputEvent(kind="key", key="escape", raw="\x1b"),)


def test_input_reader_normalizes_csi_u_and_modify_other_keys() -> None:
    reader = InputReader()

    events = reader.feed("\x1b[97;5u\x1b[1;5D\x1b[27;3;127~\x1b[13;2u")

    assert events == (
        InputEvent(kind="key", key="ctrl+a", raw="\x1b[97;5u"),
        InputEvent(kind="key", key="ctrl+left", raw="\x1b[1;5D"),
        InputEvent(kind="key", key="alt+backspace", raw="\x1b[27;3;127~"),
        InputEvent(kind="key", key="shift+enter", raw="\x1b[13;2u"),
    )


def test_input_reader_reports_kitty_protocol_response_as_signal() -> None:
    reader = InputReader()

    assert reader.feed("\x1b[?7u") == (InputEvent(kind="signal", signal="kitty_protocol", text="7", raw="\x1b[?7u"),)


def test_input_reader_normalizes_focus_and_sgr_mouse_events() -> None:
    reader = InputReader()

    events = reader.feed("\x1b[I\x1b[O\x1b[<0;10;5M\x1b[<0;10;5m")

    assert events == (
        InputEvent(kind="focus", focused=True, raw="\x1b[I"),
        InputEvent(kind="focus", focused=False, raw="\x1b[O"),
        InputEvent(kind="mouse", mouse_button=0, mouse_column=9, mouse_row=4, mouse_action="press", raw="\x1b[<0;10;5M"),
        InputEvent(kind="mouse", mouse_button=0, mouse_column=9, mouse_row=4, mouse_action="release", raw="\x1b[<0;10;5m"),
    )


def test_input_reader_buffers_old_x10_mouse_sequence_across_feeds() -> None:
    reader = InputReader()

    assert reader.feed("\x1b[M ") == ()
    events = reader.feed("*%")

    assert events == (InputEvent(kind="mouse", mouse_button=0, mouse_column=9, mouse_row=4, mouse_action="press"),)


def test_input_reader_reports_terminal_control_responses_as_signals() -> None:
    reader = InputReader()

    assert reader.feed("\x1b]0;title") == ()
    assert reader.feed("\x07") == (InputEvent(kind="signal", signal="osc", text="0;title", raw="\x1b]0;title\x07"),)
    assert reader.feed("\x1bP>|version\x1b\\") == (
        InputEvent(kind="signal", signal="dcs", text=">|version", raw="\x1bP>|version\x1b\\"),
    )
    assert reader.feed("\x1b_Gi=1;OK\x1b\\") == (
        InputEvent(kind="signal", signal="apc", text="Gi=1;OK", raw="\x1b_Gi=1;OK\x1b\\"),
    )


def test_input_reader_reports_terminal_cell_size_response_as_signal() -> None:
    reader = InputReader()

    assert reader.feed("\x1b[6;18;9t") == (
        InputEvent(kind="signal", signal="cell_size", text="18;9", raw="\x1b[6;18;9t"),
    )


def test_input_reader_marks_key_release_without_triggering_router_actions() -> None:
    reader = InputReader()
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    events = reader.feed("\x1b[97;5:3u")

    assert events == (InputEvent(kind="key", key="ctrl+a", raw="\x1b[97;5:3u", event_type="release"),)
    assert router.route(events[0]) == ()


def test_input_reader_decodes_unmodified_kitty_printable_without_duplicate_echo() -> None:
    reader = InputReader()

    events = reader.feed("\x1b[20320u你")

    assert events == (InputEvent(kind="text", text="你", raw="\x1b[20320u"),)


def test_keybinding_manager_allows_input_action_overrides() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("line")
    keybindings = KeybindingManager(
        {
            "tui.input.newLine": ("alt+enter",),
            "tui.input.submit": ("shift+enter",),
        }
    )
    router = InputRouter(composer=composer, keybindings=keybindings)

    assert router.route(InputEvent(kind="key", key="shift+enter")) == (InputIntent(kind="submit", text="line"),)
    composer.insert_text("line")
    assert router.route(InputEvent(kind="key", key="alt+enter")) == ()
    assert composer.value == "line\n"


def test_keybinding_manager_reports_user_binding_conflicts() -> None:
    manager = KeybindingManager(
        {
            "tui.input.submit": ("ctrl+j",),
            "tui.input.newLine": ("ctrl+j",),
        }
    )

    assert manager.conflicts() == (
        KeybindingConflict(key="ctrl+j", action_ids=("tui.input.newLine", "tui.input.submit")),
    )


def test_keybinding_manager_normalizes_legacy_alt_arrow_aliases() -> None:
    manager = KeybindingManager()

    assert manager.matches("alt_left", "tui.editor.cursorWordLeft")
    assert manager.matches("alt_right", "tui.editor.cursorWordRight")
    assert manager.matches("alt_up", "tui.queue.editLast")
    assert manager.matches("alt_down", "tui.select.down")


def test_input_router_alt_angle_moves_to_line_boundaries() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("alpha beta")
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="alt+<")) == ()
    composer.delete_forward()
    assert composer.value == "lpha beta"

    assert router.route(InputEvent(kind="key", key="alt+>")) == ()
    composer.insert_text("!")
    assert composer.value == "lpha beta!"


def test_input_router_jump_mode_moves_to_next_or_previous_character() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abc def abc")
    composer.move_to_line_start()
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="ctrl+]")) == ()
    assert router.route(InputEvent(kind="text", text="d")) == ()
    composer.delete_forward()
    assert composer.value == "abc ef abc"

    assert router.route(InputEvent(kind="key", key="ctrl+alt+]")) == ()
    assert router.route(InputEvent(kind="text", text="a")) == ()
    composer.delete_forward()
    assert composer.value == "bc ef abc"


def test_input_router_escape_cancels_jump_mode_without_editing() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abc def")
    composer.move_to_line_start()
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="ctrl+]")) == ()
    assert router.route(InputEvent(kind="key", key="escape")) == ()
    assert router.route(InputEvent(kind="text", text="d")) == ()

    assert composer.value == "dabc def"


def test_input_router_routes_paste_to_composer_without_submit() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    intents = router.route(InputEvent(kind="paste", text="a\nb"))

    assert intents == ()
    assert composer.value == "a\nb"


def test_input_router_routes_common_editor_actions_to_composer() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("hello")
    router = InputRouter(composer=composer)

    router.route(InputEvent(kind="key", key="left"))
    router.route(InputEvent(kind="key", key="backspace"))

    assert composer.value == "helo"

    router.route(InputEvent(kind="key", key="ctrl_a"))
    router.route(InputEvent(kind="key", key="ctrl_k"))

    assert composer.value == ""
    assert composer.kill_ring == ("helo",)

    router.route(InputEvent(kind="key", key="ctrl_y"))

    assert composer.value == "helo"


def test_input_router_alt_y_routes_yank_pop() -> None:
    reader = InputReader()
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer, width=20)

    composer.insert_text("alpha beta")
    composer.delete_word_backward()
    composer.insert_text(" gamma")
    composer.delete_word_backward()
    composer.yank()

    for event in reader.feed("\x1by"):
        router.route(event)

    assert composer.value == "alpha  beta"


def test_input_router_up_down_use_visual_movement_before_history() -> None:
    composer = Composer(prompt="> ")
    composer.add_history("history")
    composer.insert_text("abcd efgh ij")
    router = InputRouter(composer=composer, width=7)

    assert router.route(InputEvent(kind="key", key="up")) == ()

    result = composer.render(RenderConstraints(width=7, max_height=5))
    assert composer.value == "abcd efgh ij"
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (1, 4)

    composer.clear()
    assert router.route(InputEvent(kind="key", key="up")) == ()
    assert composer.value == "history"


def test_input_router_page_up_down_move_composer_by_visible_page() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("one\ntwo\nthree\nfour\nfive")
    router = InputRouter(composer=composer, width=20, height=3)

    assert router.route(InputEvent(kind="key", key="pageUp")) == ()
    result = composer.render(RenderConstraints(width=20, max_height=5))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (2, 6)

    assert router.route(InputEvent(kind="key", key="pageDown")) == ()
    result = composer.render(RenderConstraints(width=20, max_height=5))
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (4, 6)


def test_input_router_history_down_restores_draft_after_browsing() -> None:
    composer = Composer(prompt="> ")
    composer.add_history("first")
    composer.add_history("second")
    router = InputRouter(composer=composer, width=20)

    assert router.route(InputEvent(kind="key", key="up")) == ()
    assert composer.value == "second"
    assert router.route(InputEvent(kind="key", key="up")) == ()
    assert composer.value == "first"
    assert router.route(InputEvent(kind="key", key="down")) == ()
    assert composer.value == "second"
    assert router.route(InputEvent(kind="key", key="down")) == ()
    assert composer.value == ""


def test_input_router_browses_history_from_non_empty_single_line_draft() -> None:
    composer = Composer(prompt="> ")
    composer.add_history("first")
    composer.add_history("second")
    composer.insert_text("draft")
    router = InputRouter(composer=composer, width=20)

    assert router.route(InputEvent(kind="key", key="up")) == ()
    assert composer.value == "second"
    assert router.route(InputEvent(kind="key", key="up")) == ()
    assert composer.value == "first"
    assert router.route(InputEvent(kind="key", key="down")) == ()
    assert composer.value == "second"
    assert router.route(InputEvent(kind="key", key="down")) == ()
    assert composer.value == "draft"


def test_input_router_uses_visual_up_before_history_for_multiline_draft() -> None:
    composer = Composer(prompt="> ")
    composer.add_history("history")
    composer.insert_text("alpha\nbeta")
    router = InputRouter(composer=composer, width=20)

    assert router.route(InputEvent(kind="key", key="up")) == ()
    assert composer.value == "alpha\nbeta"
    assert router.route(InputEvent(kind="key", key="up")) == ()
    assert composer.value == "history"


def test_input_router_routes_completion_navigation_before_composer_arrows() -> None:
    composer = Composer(prompt="> ")
    assert callable(getattr(composer, "set_completion_items", None))
    composer.insert_text("/he")
    composer.set_completion_items(
        (
            CompletionItem(value="/help", label="/help"),
            CompletionItem(value="/hello", label="/hello"),
        )
    )
    router = InputRouter(composer=composer, width=20)

    assert router.route(InputEvent(kind="key", key="down")) == ()
    assert router.route(InputEvent(kind="key", key="tab")) == ()

    assert composer.value == "/hello"


def test_input_router_shift_tab_selects_previous_completion_without_applying() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("/he")
    composer.set_completion_items(
        (
            CompletionItem(value="/help", label="/help"),
            CompletionItem(value="/hello", label="/hello"),
        )
    )
    router = InputRouter(composer=composer, width=20)

    assert router.route(InputEvent(kind="key", key="shift+tab")) == ()
    assert composer.value == "/he"

    assert router.route(InputEvent(kind="key", key="tab")) == ()
    assert composer.value == "/hello"


def test_input_router_escape_closes_completion_before_running_abort() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("/he")
    composer.set_completion_items((CompletionItem(value="/help", label="/help"),))
    router = InputRouter(composer=composer, running=True, width=20)

    assert router.route(InputEvent(kind="key", key="escape")) == ()

    assert composer.value == "/he"
    assert not composer.has_completions


def test_input_router_enter_submits_text_without_applying_completion() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("/he")
    composer.set_completion_items((CompletionItem(value="/help", label="/help"),))
    router = InputRouter(composer=composer, width=20)

    assert router.route(InputEvent(kind="key", key="enter")) == (InputIntent(kind="submit", text="/he"),)

    assert composer.value == ""


def test_input_reader_tab_event_applies_provider_completion_through_router() -> None:
    reader = InputReader()
    composer = Composer(prompt="> ")
    composer.set_completion_provider(
        CompletionProvider(
            (
                CompletionItem(value="/help", label="/help"),
                CompletionItem(value="/quit", label="/quit"),
            )
        )
    )
    router = InputRouter(composer=composer, width=20)

    for event in reader.feed("/h\t"):
        router.route(event)

    assert composer.value == "/help "


def test_input_router_tab_forces_provider_before_applying_completion() -> None:
    class ForceProvider:
        def __init__(self) -> None:
            self.force_values: list[bool] = []

        def get_suggestions(
            self,
            lines: tuple[str, ...],
            cursor_line: int,
            cursor_col: int,
            *,
            force: bool = False,
        ):
            self.force_values.append(force)
            if not force:
                return None
            from loushang.tui import CompletionItem, CompletionSuggestions

            return CompletionSuggestions(prefix=lines[cursor_line][:cursor_col], items=(CompletionItem(value="src/"),))

    provider = ForceProvider()
    composer = Composer(prompt="> ")
    composer.set_completion_provider(provider)
    composer.insert_text("s")
    router = InputRouter(composer=composer, width=20)

    assert router.route(InputEvent(kind="key", key="tab")) == ()

    assert provider.force_values[-1] is True
    assert composer.value == "src/"


def test_input_router_tab_applies_first_forced_completion_when_multiple_results() -> None:
    class MultiForceProvider:
        def get_suggestions(
            self,
            lines: tuple[str, ...],
            cursor_line: int,
            cursor_col: int,
            *,
            force: bool = False,
        ):
            if not force:
                return None
            from loushang.tui import CompletionItem, CompletionSuggestions

            return CompletionSuggestions(
                prefix=lines[cursor_line][:cursor_col],
                items=(
                    CompletionItem(value="src/"),
                    CompletionItem(value="script.py"),
                ),
            )

    composer = Composer(prompt="> ")
    composer.set_completion_provider(MultiForceProvider())
    composer.insert_text("s")
    router = InputRouter(composer=composer, width=20)

    assert router.route(InputEvent(kind="key", key="tab")) == ()

    assert composer.value == "src/"
    assert not composer.has_completions


def test_input_router_ctrl_j_and_alt_enter_insert_explicit_newline() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("first")
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="ctrl_j")) == ()
    composer.insert_text("second")
    assert router.route(InputEvent(kind="key", key="alt_enter")) == ()

    assert composer.value == "first\nsecond\n"


def test_input_router_alt_up_requests_edit_last_queued_prompt() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="alt_up")) == (InputIntent(kind="command", note="edit_last_queued_prompt"),)
    assert composer.value == ""


def test_surface_receives_escape_before_active_run_abort() -> None:
    composer = Composer(prompt="> ")
    focus = EscConsumer()
    host = SurfaceHost()
    host.open_surface(Surface(renderable=DummyRenderable(), focus_target=focus))
    router = InputRouter(composer=composer, surface_host=host, running=True)

    intents = router.route(InputEvent(kind="key", key="esc"))

    assert intents == (InputIntent(kind="surface_close"),)
    assert host.entries == []
    assert focus.focused is False


def test_ctrl_c_during_running_turn_routes_abort_intent() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer, running=True)

    intents = router.route(InputEvent(kind="key", key="ctrl_c"))

    assert intents == (InputIntent(kind="abort"),)


def test_escape_when_idle_does_not_create_abort_intent() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer, running=False)

    assert router.route(InputEvent(kind="key", key="esc")) == ()


def test_alt_enter_inserts_explicit_newline_without_submit() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("first")
    router = InputRouter(composer=composer)

    intents = router.route(InputEvent(kind="key", key="alt_enter"))

    assert intents == ()
    assert composer.value == "first\n"


def test_resize_and_sigwinch_events_request_render_invalidation() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="resize", columns=120, rows=50)) == (InputIntent(kind="invalidate_render"),)
    assert router.route(InputEvent(kind="signal", signal="sigwinch")) == (InputIntent(kind="invalidate_render"),)


def test_enter_while_running_queues_follow_up_and_clears_composer() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("later")
    router = InputRouter(composer=composer, running=True)

    intents = router.route(InputEvent(kind="key", key="enter"))

    assert intents == (InputIntent(kind="follow_up", text="later"),)
    assert composer.value == ""


def test_configured_steer_submit_routes_steer_when_supported() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("look at logs")
    router = InputRouter(composer=composer, running=True, steering_supported=True)

    intents = router.submit(mode="steer")

    assert intents == (InputIntent(kind="steer", text="look at logs"),)
    assert composer.value == ""


def test_unavailable_steer_downgrades_to_visible_follow_up() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("look at logs")
    router = InputRouter(composer=composer, running=True, steering_supported=False)

    intents = router.submit(mode="steer")

    assert intents == (InputIntent(kind="follow_up", text="look at logs", note="steer_unavailable"),)
    assert composer.value == ""
