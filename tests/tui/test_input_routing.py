from __future__ import annotations

import inspect
import pickle
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal

import pytest

from loushang.tui import (
    TUI_CORE_KEYBINDING_CATALOG,
    CommandSurface,
    CompletionItem,
    CompletionProvider,
    Composer,
    FocusableMixin,
    InputEvent,
    InputIntent,
    InputReader,
    InputRouter,
    KeybindingCatalog,
    KeybindingConflict,
    KeybindingManager,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SelectItem,
    Surface,
    SurfaceHost,
    TextInput,
)
from loushang.tui.input import (
    apply_prompt_paste,
    apply_prompt_text,
    prompt_jump_direction_for_key,
    route_editor_editing_key,
    route_editor_selection_key,
    route_prompt_explicit_completion_key,
    route_prompt_vertical_navigation_key,
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


def test_input_intent_preserves_runtime_dataclass_value_protocol() -> None:
    intent = InputIntent(
        kind="example_plugin.openArtifact",
        text="artifact-42",
        note="preview",
    )

    assert asdict(intent) == {
        "kind": "example_plugin.openArtifact",
        "text": "artifact-42",
        "note": "preview",
    }
    assert repr(intent) == (
        "InputIntent(kind='example_plugin.openArtifact', "
        "text='artifact-42', note='preview')"
    )
    assert intent == InputIntent(
        kind="example_plugin.openArtifact",
        text="artifact-42",
        note="preview",
    )
    assert pickle.loads(pickle.dumps(intent)) == intent


class DecliningEditorFocus(FocusableMixin):
    def __init__(self, target: object) -> None:
        super().__init__()
        self.target = target

    def editor_input_target(self) -> object:
        return self.target

    def handle_input(self, event: Any) -> bool:
        return False


@dataclass(slots=True)
class FakePromptTarget:
    value: str = ""
    browsing_history: bool = False
    has_completions: bool = False
    calls: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)

    def insert_text(self, text: str) -> None:
        self.calls.append(f"insert_text:{text}")
        self.value += text

    def paste(self, text: str) -> None:
        self.calls.append(f"paste:{text}")
        self.value += text

    def clear(self) -> None:
        self.calls.append("clear")
        self.value = ""

    def add_history(self, text: str) -> None:
        self.calls.append(f"add_history:{text}")
        self.history.append(text)

    def insert_newline(self) -> None:
        self.calls.append("insert_newline")
        self.value += "\n"

    def _record(self, name: str) -> None:
        self.calls.append(name)

    def move_left(self) -> None:
        self._record("move_left")

    def move_right(self) -> None:
        self._record("move_right")

    def move_word_left(self) -> None:
        self._record("move_word_left")

    def move_word_right(self) -> None:
        self._record("move_word_right")

    def move_to_line_start(self) -> None:
        self._record("move_to_line_start")

    def move_to_line_end(self) -> None:
        self._record("move_to_line_end")

    def select_char_left(self) -> None:
        self._record("select_char_left")

    def select_char_right(self) -> None:
        self._record("select_char_right")

    def select_word_left(self) -> None:
        self._record("select_word_left")

    def select_word_right(self) -> None:
        self._record("select_word_right")

    def select_line_start(self) -> None:
        self._record("select_line_start")

    def select_line_end(self) -> None:
        self._record("select_line_end")

    def delete_backward(self) -> None:
        self._record("delete_backward")

    def delete_forward(self) -> None:
        self._record("delete_forward")

    def delete_word_backward(self) -> None:
        self._record("delete_word_backward")

    def delete_word_forward(self) -> None:
        self._record("delete_word_forward")

    def kill_to_line_start(self) -> None:
        self._record("kill_to_line_start")

    def kill_to_line_end(self) -> None:
        self._record("kill_to_line_end")

    def yank(self) -> None:
        self._record("yank")

    def yank_pop(self) -> None:
        self._record("yank_pop")

    def undo(self) -> None:
        self._record("undo")

    def redo(self) -> None:
        self._record("redo")

    def history_previous(self) -> None:
        self._record("history_previous")

    def history_next(self) -> None:
        self._record("history_next")

    def move_visual_up(self, *, width: int) -> bool:
        self.calls.append(f"move_visual_up:{width}")
        return False

    def move_visual_down(self, *, width: int) -> bool:
        self.calls.append(f"move_visual_down:{width}")
        return False

    def move_visual_page_up(self, *, width: int, visible_lines: int) -> None:
        self.calls.append(f"move_visual_page_up:{width}:{visible_lines}")

    def move_visual_page_down(self, *, width: int, visible_lines: int) -> None:
        self.calls.append(f"move_visual_page_down:{width}:{visible_lines}")

    def jump_to_char(self, text: str, *, direction: Literal["forward", "backward"]) -> None:
        self.calls.append(f"jump_to_char:{direction}:{text}")

    def refresh_completions(self, *, force: bool = False, explicit: bool = False) -> None:
        self.calls.append(f"refresh_completions:{force}:{explicit}")
        self.has_completions = True

    def apply_selected_completion(self) -> None:
        self.calls.append("apply_selected_completion")

    def select_previous_completion(self) -> None:
        self.calls.append("select_previous_completion")

    def select_next_completion(self) -> None:
        self.calls.append("select_next_completion")

    def clear_completion_items(self) -> None:
        self.calls.append("clear_completion_items")
        self.has_completions = False


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

    events = reader.feed("\x7f\x1b[3~\x01\x05\x07\x0a\x0b\x0f\x15\x16\x17\x19\x1bu\x1br\x1by\x1b\r\x1b[13;2~\x1b[1;3A")

    assert events == (
        InputEvent(kind="key", key="backspace"),
        InputEvent(kind="key", key="delete"),
        InputEvent(kind="key", key="ctrl+a"),
        InputEvent(kind="key", key="ctrl+e"),
        InputEvent(kind="key", key="ctrl+g"),
        InputEvent(kind="key", key="ctrl+j"),
        InputEvent(kind="key", key="ctrl+k"),
        InputEvent(kind="key", key="ctrl+o"),
        InputEvent(kind="key", key="ctrl+u"),
        InputEvent(kind="key", key="ctrl+v"),
        InputEvent(kind="key", key="ctrl+w"),
        InputEvent(kind="key", key="ctrl+y"),
        InputEvent(kind="key", key="alt+u"),
        InputEvent(kind="key", key="alt+r"),
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

    events = reader.feed("\x1b[97;5u\x1b[95;5u\x1b[90;6u\x1b[1;5D\x1b[27;3;127~\x1b[13;2u")

    assert events == (
        InputEvent(kind="key", key="ctrl+a", raw="\x1b[97;5u"),
        InputEvent(kind="key", key="ctrl+_", raw="\x1b[95;5u"),
        InputEvent(kind="key", key="ctrl+shift+z", raw="\x1b[90;6u"),
        InputEvent(kind="key", key="ctrl+left", raw="\x1b[1;5D"),
        InputEvent(kind="key", key="alt+backspace", raw="\x1b[27;3;127~"),
        InputEvent(kind="key", key="shift+enter", raw="\x1b[13;2u"),
    )


def test_input_reader_normalizes_selection_navigation_keys() -> None:
    reader = InputReader()

    events = reader.feed("\x1b[1;2D\x1b[1;2C\x1b[1;6D\x1b[1;6C")

    assert events == (
        InputEvent(kind="key", key="shift+left", raw="\x1b[1;2D"),
        InputEvent(kind="key", key="shift+right", raw="\x1b[1;2C"),
        InputEvent(kind="key", key="ctrl+shift+left", raw="\x1b[1;6D"),
        InputEvent(kind="key", key="ctrl+shift+right", raw="\x1b[1;6C"),
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
    assert manager.matches("alt_down", "tui.select.down")


def test_keybinding_manager_matches_transcript_reader_alias() -> None:
    manager = KeybindingManager()

    assert manager.matches("ctrl_o", "tui.transcript.open")
    assert manager.matches("ctrl+o", "tui.transcript.open")


def test_keybinding_manager_matches_default_redo_key() -> None:
    manager = KeybindingManager()

    assert manager.keys_for("tui.editor.redo") == ("alt+r",)
    assert manager.matches("alt+r", "tui.editor.redo")
    assert not manager.matches("ctrl+shift+z", "tui.editor.redo")


def test_keybinding_manager_extends_definitions_without_losing_user_overrides() -> None:
    manager = KeybindingManager({"conversation.input.followUp": ("ctrl+enter",)})

    extended = manager.with_definitions({"conversation.input.followUp": ("alt+enter",)})

    assert manager.keys_for("conversation.input.followUp") == ()
    assert extended.keys_for("conversation.input.followUp") == ("ctrl+enter",)
    assert extended.keys_for("tui.input.submit") == ("enter",)


def test_keybinding_catalog_composes_plugin_actions_with_user_overrides() -> None:
    plugin_catalog = KeybindingCatalog.from_definitions(
        {"plugin.action": "ctrl+p"}
    )
    catalog = TUI_CORE_KEYBINDING_CATALOG.compose(plugin_catalog)
    manager = KeybindingManager(
        {"plugin.action": ("alt+p",)},
        catalog=catalog,
    )

    assert manager.keys_for("tui.input.submit") == ("enter",)
    assert manager.keys_for("plugin.action") == ("alt+p",)


def test_composed_catalog_reports_cross_owner_user_binding_conflicts() -> None:
    catalog = TUI_CORE_KEYBINDING_CATALOG.compose(
        KeybindingCatalog.from_definitions({"plugin.action": ("ctrl+p",)})
    )
    manager = KeybindingManager(
        {
            "tui.input.submit": ("ctrl+p",),
            "plugin.action": ("ctrl+p",),
        },
        catalog=catalog,
    )

    assert manager.conflicts() == (
        KeybindingConflict(
            key="ctrl+p",
            action_ids=("plugin.action", "tui.input.submit"),
        ),
    )


def test_keybinding_catalog_rejects_duplicate_action_ownership() -> None:
    first = KeybindingCatalog.from_definitions({"plugin.action": ("ctrl+p",)})
    second = KeybindingCatalog.from_definitions({"plugin.action": ("alt+p",)})

    with pytest.raises(ValueError, match="plugin.action"):
        first.compose(second)


def test_tui_core_keybinding_catalog_excludes_upper_layer_actions() -> None:
    manager = KeybindingManager()

    assert manager.keys_for("conversation.input.pasteImage") == ()
    assert manager.keys_for("tui.queue.editLast") == ()
    assert manager.keys_for("tui.continuity.preview") == ()


def test_keybinding_manager_matches_terminal_underscore_undo_alias() -> None:
    manager = KeybindingManager()

    assert manager.matches("ctrl+_", "tui.editor.undo")
    assert manager.matches("alt+u", "tui.editor.undo")


def test_input_router_rejects_missing_prompt_target() -> None:
    with pytest.raises(TypeError, match="requires composer or target"):
        InputRouter()


def test_input_router_rejects_composer_and_target_together() -> None:
    with pytest.raises(TypeError, match="composer or target"):
        InputRouter(composer=Composer(prompt="> "), target=FakePromptTarget())


def test_input_router_constructor_exposes_only_generic_configuration() -> None:
    parameters = inspect.signature(InputRouter).parameters

    assert tuple(parameters) == (
        "composer",
        "surface_host",
        "width",
        "height",
        "keybindings",
        "target",
    )
    assert parameters["composer"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["surface_host"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        for name in ("width", "height", "keybindings", "target")
    )
    router_fields = {router_field.name: router_field for router_field in fields(InputRouter)}
    assert "running" not in router_fields
    assert "steering_supported" not in router_fields
    assert router_fields["_jump_mode"].init is False

    with pytest.raises(TypeError):
        InputRouter(Composer(prompt="> "), None, True)


def test_input_router_submit_accepts_no_conversation_mode() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("later")
    router = InputRouter(composer=composer)

    assert tuple(inspect.signature(InputRouter.submit).parameters) == ("self",)
    assert router.submit() == (InputIntent(kind="submit", text="later"),)

    with pytest.raises(TypeError):
        router.submit(mode="steer")  # type: ignore[call-arg]


def test_input_router_submit_is_conversation_neutral() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("later")
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="enter")) == (
        InputIntent(kind="submit", text="later"),
    )


@pytest.mark.parametrize("cancel_key", ["escape", "ctrl_c"])
def test_input_router_unconsumed_cancel_emits_prompt_cancel(cancel_key: str) -> None:
    router = InputRouter(composer=Composer(prompt="> "))

    assert router.route(InputEvent(kind="key", key=cancel_key)) == (
        InputIntent(kind="prompt_cancel"),
    )


def test_input_router_does_not_own_conversation_queue_editing() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="alt+up")) == ()
    assert composer.value == ""


def test_input_router_routes_text_paste_and_submit_through_target() -> None:
    target = FakePromptTarget()
    router = InputRouter(target=target)

    assert router.route(InputEvent(kind="text", text="he")) == ()
    assert router.route(InputEvent(kind="paste", text="llo")) == ()
    assert router.route(InputEvent(kind="key", key="enter")) == (
        InputIntent(kind="submit", text="hello"),
    )

    assert target.calls == [
        "insert_text:he",
        "paste:llo",
        "add_history:hello",
        "clear",
    ]
    assert target.history == ["hello"]
    assert target.value == ""


def test_editor_key_helpers_route_to_target_operations() -> None:
    target = FakePromptTarget()

    assert route_editor_editing_key(target, "left")
    assert route_editor_selection_key(target, "shift+left")

    assert target.calls == ["move_left", "select_char_left"]


def test_prompt_text_and_paste_primitives_apply_only_editor_mechanics() -> None:
    target = FakePromptTarget()

    apply_prompt_text(target, "alpha")
    apply_prompt_text(target, "x", jump_direction="forward")
    apply_prompt_paste(target, "beta\ngamma")

    assert target.calls == [
        "insert_text:alpha",
        "jump_to_char:forward:x",
        "paste:beta\ngamma",
    ]


def test_prompt_jump_direction_uses_configured_core_actions() -> None:
    keybindings = KeybindingManager(
        {
            "tui.editor.jumpForward": ("alt+f",),
            "tui.editor.jumpBackward": ("alt+b",),
        }
    )

    assert prompt_jump_direction_for_key("alt+f", keybindings=keybindings) == "forward"
    assert prompt_jump_direction_for_key("alt+b", keybindings=keybindings) == "backward"
    assert prompt_jump_direction_for_key("enter", keybindings=keybindings) is None


def test_prompt_explicit_completion_primitive_refreshes_before_applying() -> None:
    target = FakePromptTarget()

    assert not route_prompt_explicit_completion_key(target, "enter")
    assert route_prompt_explicit_completion_key(target, "tab")
    assert target.calls == [
        "refresh_completions:True:True",
        "apply_selected_completion",
    ]


def test_prompt_vertical_navigation_primitive_handles_history_and_pages() -> None:
    target = FakePromptTarget(value="draft")

    assert route_prompt_vertical_navigation_key(
        target,
        "up",
        width=7,
        height=3,
    )
    target.browsing_history = True
    assert route_prompt_vertical_navigation_key(
        target,
        "down",
        width=7,
        height=3,
    )
    assert route_prompt_vertical_navigation_key(
        target,
        "pageUp",
        width=7,
        height=3,
    )
    assert route_prompt_vertical_navigation_key(
        target,
        "pageDown",
        width=7,
        height=1,
    )
    assert not route_prompt_vertical_navigation_key(
        target,
        "enter",
        width=7,
        height=3,
    )
    assert target.calls == [
        "move_visual_up:7",
        "history_previous",
        "history_next",
        "move_visual_page_up:7:3",
        "move_visual_page_down:7:2",
    ]


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


def test_input_router_routes_shift_selection_before_completion_navigation() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("ab")
    composer.set_completion_items([CompletionItem(value="abc"), CompletionItem(value="abd")])
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="shift+left")) == ()

    assert composer.selected_range == (1, 2)

    assert router.route(InputEvent(kind="text", text="x")) == ()

    assert composer.value == "ax"


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


@pytest.mark.parametrize("cancel_key", ["escape", "ctrl_c"])
def test_input_router_cancel_terminates_pending_jump_without_prompt_cancel(cancel_key: str) -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abc def")
    composer.move_to_line_start()
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="ctrl+]")) == ()
    assert router.route(InputEvent(kind="key", key=cancel_key)) == ()
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


def test_input_router_routes_default_redo_to_composer() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    router.route(InputEvent(kind="text", text="abc"))
    router.route(InputEvent(kind="key", key="ctrl+-"))

    assert composer.value == ""

    router.route(InputEvent(kind="key", key="alt+r"))

    assert composer.value == "abc"


def test_input_router_routes_alt_u_undo_to_composer() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    router.route(InputEvent(kind="text", text="abc"))
    router.route(InputEvent(kind="key", key="alt+u"))

    assert composer.value == ""


def test_input_router_routes_terminal_underscore_undo_alias_to_composer() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    router.route(InputEvent(kind="text", text="abc"))
    router.route(InputEvent(kind="key", key="ctrl+_"))

    assert composer.value == ""


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


def test_input_router_escape_closes_completion_before_prompt_cancel() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("/he")
    composer.set_completion_items((CompletionItem(value="/help", label="/help"),))
    router = InputRouter(composer=composer, width=20)

    assert router.route(InputEvent(kind="key", key="escape")) == ()

    assert composer.value == "/he"
    assert not composer.has_completions


@pytest.mark.parametrize("custom_overlap", [False, True])
def test_input_router_completion_wins_after_pending_jump_cancel(custom_overlap: bool) -> None:
    keybindings = (
        KeybindingManager({"tui.editor.jumpForward": ("escape",)})
        if custom_overlap
        else KeybindingManager()
    )
    composer = Composer(prompt="> ")
    composer.insert_text("abc def")
    composer.move_to_line_start()
    router = InputRouter(composer=composer, keybindings=keybindings)
    pending_jump_key = "ctrl+alt+]" if custom_overlap else "ctrl+]"

    assert router.route(InputEvent(kind="key", key=pending_jump_key)) == ()
    composer.set_completion_items((CompletionItem(value="abc", label="abc"),))
    assert router.route(InputEvent(kind="key", key="escape")) == ()
    assert not composer.has_completions
    assert router.route(InputEvent(kind="text", text="d")) == ()
    assert composer.value == "dabc def"


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


@pytest.mark.parametrize("custom_overlap", [False, True])
def test_surface_receives_cancel_after_pending_jump(custom_overlap: bool) -> None:
    keybindings = (
        KeybindingManager({"tui.editor.jumpForward": ("escape",)})
        if custom_overlap
        else KeybindingManager()
    )
    composer = Composer(prompt="> ")
    focus = EscConsumer()
    host = SurfaceHost()
    host.open_surface(Surface(renderable=DummyRenderable(), focus_target=focus))
    router = InputRouter(composer=composer, surface_host=host, keybindings=keybindings)
    pending_jump_key = "ctrl+alt+]" if custom_overlap else "ctrl+]"

    assert router.route(InputEvent(kind="key", key=pending_jump_key)) == ()
    intents = router.route(InputEvent(kind="key", key="esc"))

    assert intents == (InputIntent(kind="surface_close"),)
    assert host.entries == []
    assert focus.focused is False


def test_input_router_routes_text_and_paste_to_declined_focused_editor_target() -> None:
    prompt = Composer(prompt="> ")
    field = TextInput()
    host = SurfaceHost()
    host.open_surface(
        Surface(
            renderable=DummyRenderable(),
            focus_target=DecliningEditorFocus(field.editor_input_target()),
        )
    )
    router = InputRouter(composer=prompt, surface_host=host)

    assert router.route(InputEvent(kind="text", text="ab")) == ()
    assert router.route(InputEvent(kind="paste", text="c\nd")) == ()

    assert field.value == "abc d"
    assert prompt.value == ""


def test_input_router_does_not_double_insert_direct_focused_text_input_surface() -> None:
    changes: list[str] = []
    prompt = Composer(prompt="> ")
    field = TextInput(on_change=changes.append)
    host = SurfaceHost()
    host.open_surface(Surface(renderable=DummyRenderable(), focus_target=field))
    router = InputRouter(composer=prompt, surface_host=host)

    assert router.route(InputEvent(kind="text", text="a")) == ()

    assert field.value == "a"
    assert changes == ["a"]
    assert prompt.value == ""


def test_input_router_routes_focused_editor_selection_and_editing_keys() -> None:
    prompt = Composer(prompt="> ")
    field = TextInput()
    target = field.editor_input_target()
    target.insert_text("abc")
    host = SurfaceHost()
    host.open_surface(Surface(renderable=DummyRenderable(), focus_target=DecliningEditorFocus(target)))
    router = InputRouter(composer=prompt, surface_host=host)

    assert router.route(InputEvent(kind="key", key="shift+left")) == ()
    assert field.selected_range == (2, 3)
    assert router.route(InputEvent(kind="key", key="backspace")) == ()

    assert field.value == "ab"
    assert prompt.value == ""


def test_input_router_surface_intent_wins_before_focused_editor_fallback() -> None:
    class ClosingEditorFocus(DecliningEditorFocus):
        def handle_input(self, event: Any) -> InputIntent | None:
            if isinstance(event, InputEvent) and event.kind == "key":
                return InputIntent(kind="surface_close")
            return None

    prompt = Composer(prompt="> ")
    field = TextInput()
    host = SurfaceHost()
    host.open_surface(Surface(renderable=DummyRenderable(), focus_target=ClosingEditorFocus(field.editor_input_target())))
    router = InputRouter(composer=prompt, surface_host=host)

    assert router.route(InputEvent(kind="key", key="left")) == (InputIntent(kind="surface_close"),)
    assert field.value == ""
    assert host.entries == []


def test_input_router_forwards_owner_qualified_surface_intent_unchanged() -> None:
    class PluginSurfaceFocus(FocusableMixin):
        def handle_input(self, event: Any) -> InputIntent[str] | None:
            if isinstance(event, InputEvent) and event.kind == "key":
                return InputIntent(
                    kind="example_plugin.openArtifact",
                    text="artifact-42",
                    note="preview",
                )
            return None

    host = SurfaceHost()
    focus = PluginSurfaceFocus()
    host.open_surface(Surface(renderable=DummyRenderable(), focus_target=focus))
    router = InputRouter(composer=Composer(prompt="> "), surface_host=host)

    assert router.route(InputEvent(kind="key", key="enter")) == (
        InputIntent(
            kind="example_plugin.openArtifact",
            text="artifact-42",
            note="preview",
        ),
    )


def test_input_router_does_not_submit_prompt_while_focused_editor_target_is_active() -> None:
    prompt = Composer(prompt="> ")
    prompt.insert_text("prompt")
    field = TextInput()
    host = SurfaceHost()
    host.open_surface(Surface(renderable=DummyRenderable(), focus_target=DecliningEditorFocus(field.editor_input_target())))
    router = InputRouter(composer=prompt, surface_host=host)

    assert router.route(InputEvent(kind="key", key="enter")) == ()
    assert prompt.value == "prompt"


@pytest.mark.parametrize("custom_overlap", [False, True])
def test_focused_editor_receives_cancel_after_pending_jump(custom_overlap: bool) -> None:
    class RecordingEditorFocus(DecliningEditorFocus):
        def __init__(self, target: object) -> None:
            super().__init__(target)
            self.keys: list[str] = []

        def handle_input(self, event: Any) -> bool:
            if isinstance(event, InputEvent) and event.kind == "key":
                self.keys.append(event.key)
            return False

    keybindings = (
        KeybindingManager({"tui.editor.jumpForward": ("escape",)})
        if custom_overlap
        else KeybindingManager()
    )
    prompt = Composer(prompt="> ")
    prompt.insert_text("abc def")
    prompt.move_to_line_start()
    router = InputRouter(composer=prompt, keybindings=keybindings)
    pending_jump_key = "ctrl+alt+]" if custom_overlap else "ctrl+]"
    assert router.route(InputEvent(kind="key", key=pending_jump_key)) == ()

    field = TextInput()
    focus = RecordingEditorFocus(field.editor_input_target())
    host = SurfaceHost()
    handle = host.open_surface(Surface(renderable=DummyRenderable(), focus_target=focus))
    router.surface_host = host

    assert router.route(InputEvent(kind="key", key="escape")) == ()
    assert focus.keys == ["esc"]

    handle.close(reason="test")
    assert router.route(InputEvent(kind="text", text="d")) == ()
    assert prompt.value == "dabc def"


def test_custom_jump_cancel_overlap_without_pending_jump_emits_prompt_cancel() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("abc def")
    composer.move_to_line_start()
    router = InputRouter(
        composer=composer,
        keybindings=KeybindingManager({"tui.editor.jumpForward": ("escape",)}),
    )

    assert router.route(InputEvent(kind="key", key="escape")) == (
        InputIntent(kind="prompt_cancel"),
    )
    assert router.route(InputEvent(kind="text", text="d")) == ()
    assert composer.value == "dabc def"


def test_input_router_prompt_jump_text_wins_before_focused_editor_fallback() -> None:
    prompt = Composer(prompt="> ")
    prompt.insert_text("abc def")
    prompt.move_to_line_start()
    router = InputRouter(composer=prompt)
    assert router.route(InputEvent(kind="key", key="ctrl+]")) == ()

    field = TextInput()
    host = SurfaceHost()
    host.open_surface(Surface(renderable=DummyRenderable(), focus_target=DecliningEditorFocus(field.editor_input_target())))
    router.surface_host = host

    assert router.route(InputEvent(kind="text", text="d")) == ()
    prompt.delete_forward()

    assert prompt.value == "abc ef"
    assert field.value == ""


def test_input_router_does_not_leak_searchable_surface_text_to_prompt() -> None:
    prompt = Composer(prompt="> ")
    host = SurfaceHost()
    surface = CommandSurface([SelectItem("/status", value="/status")])
    host.open_surface(Surface(renderable=surface, focus_target=surface))
    router = InputRouter(composer=prompt, surface_host=host)

    assert router.route(InputEvent(kind="text", text="sta")) == ()

    assert prompt.value == ""
    assert tuple(item.selected_value for item in surface._filtered_items) == ("/status",)


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
