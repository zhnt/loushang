from __future__ import annotations

from typing import Any

from loushang.tui import (
    ApprovalSurface,
    AutocompleteSurface,
    CommandSurface,
    DialogSurface,
    InputEvent,
    InputIntent,
    RenderConstraints,
    SelectionSurface,
    SelectItem,
    SettingItem,
    SettingsSurface,
    ThemeResolver,
    strip_control_sequences,
)


def rendered_text(surface: Any, *, width: int = 30, height: int = 5) -> tuple[str, ...]:
    result = surface.render(RenderConstraints(width=width, max_height=height))
    return tuple(line.text for line in result.lines)


def test_selection_surface_wraps_navigation_and_scrolls_selected_item_visible() -> None:
    surface = SelectionSurface(
        [
            SelectItem("one"),
            SelectItem("two"),
            SelectItem("three"),
            SelectItem("four"),
            SelectItem("five"),
        ],
        max_visible=3,
    )

    for _ in range(3):
        surface.handle_input(InputEvent(kind="key", key="down"))

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=20, height=4)) == (
        "  three",
        "> four",
        "  five",
        "  (4/5)",
    )

    surface.handle_input(InputEvent(kind="key", key="down"))
    surface.handle_input(InputEvent(kind="key", key="down"))

    assert surface.selected_index == 0


def test_selection_surface_returns_select_and_close_intents() -> None:
    surface = SelectionSurface([SelectItem("Help", value="help")])

    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="select", text="help")
    assert surface.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(kind="surface_close")


def test_selection_surface_uses_pi_style_primary_column_and_description_layout() -> None:
    surface = SelectionSurface(
        [
            SelectItem("short", value="short", description="first line\nsecond line"),
            SelectItem("a very long command name", value="long", description="Long description text"),
        ],
        max_visible=4,
    )

    raw = rendered_text(surface, width=80, height=4)

    assert tuple(strip_control_sequences(line) for line in raw) == (
        "> " + "short" + (" " * 27) + "first line second line",
        "  " + "a very long command name" + (" " * 8) + "Long description text",
    )
    assert raw[0].startswith("\x1b[1;38;5;33m> short")
    assert raw[0].endswith("\x1b[22;39m")


def test_selection_surface_selected_row_uses_theme_token_when_provided() -> None:
    surface = SelectionSurface(
        [SelectItem("Theme")],
        theme=ThemeResolver(defaults={"selection.selected": {"color": "cyan", "bold": True}}),
    )

    raw = rendered_text(surface, width=24, height=3)[0]

    assert strip_control_sequences(raw) == "> Theme"
    assert raw.startswith("\x1b[1;36m> Theme")


def test_selection_surface_can_hide_scroll_info_for_product_selectors() -> None:
    surface = SelectionSurface(
        [SelectItem(f"{index + 1}. item-{index}") for index in range(8)],
        max_visible=3,
        show_scroll_info=False,
    )

    surface.handle_input(InputEvent(kind="key", key="pageDown"))

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=20, height=4)) == (
        "  3. item-2",
        "> 4. item-3",
        "  5. item-4",
    )


def test_selection_surface_notifies_when_selection_changes() -> None:
    seen: list[SelectItem | None] = []
    surface = SelectionSurface(
        [SelectItem("Alpha", value="alpha"), SelectItem("Beta", value="beta")],
        on_selection_change=seen.append,
    )

    surface.handle_input(InputEvent(kind="key", key="down"))
    surface.handle_input(InputEvent(kind="key", key="down"))

    assert seen == [SelectItem("Beta", value="beta"), SelectItem("Alpha", value="alpha")]


def test_selection_surface_accepts_custom_layout_and_truncation_hooks() -> None:
    calls: list[tuple[str, int, str]] = []

    def truncate(text: str, max_width: int, ellipsis: str) -> str:
        calls.append((text, max_width, ellipsis))
        return text[:max_width]

    surface = SelectionSurface(
        [SelectItem("long-command-name", value="long", description="Long description text")],
        primary_column_width=8,
        min_description_width=3,
        truncate_text=truncate,
    )

    assert strip_control_sequences(rendered_text(surface, width=24, height=2)[0]) == "> long-c  Long descri"
    assert calls == [
        ("long-command-name", 6, ""),
        ("Long description text", 11, ""),
    ]


def test_selection_surface_search_input_filters_items_and_tracks_cursor() -> None:
    surface = SelectionSurface(
        [
            SelectItem("Alpha", value="alpha"),
            SelectItem("Model", value="model", description="Current model"),
            SelectItem("Memory", value="memory"),
        ],
        max_visible=4,
        enable_search=True,
        filter_mode="contains",
    )

    surface.handle_input(InputEvent(kind="text", text="mo"))
    result = surface.render(RenderConstraints(width=60, max_height=6))

    lines = tuple(strip_control_sequences(line.text) for line in result.lines)
    assert lines[:2] == ("Search: mo", "")
    assert lines[2].startswith("> Model")
    assert lines[2].endswith("Current model")
    assert lines[3] == "  Memory"
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, len("Search: mo"))

    surface.handle_input(InputEvent(kind="key", key="backspace"))

    lines = tuple(strip_control_sequences(line) for line in rendered_text(surface, width=60, height=6))
    assert lines[:2] == ("Search: m", "")
    assert lines[2].startswith("> Model")
    assert lines[2].endswith("Current model")
    assert lines[3] == "  Memory"


def test_selection_surface_search_can_use_fuzzy_filtering() -> None:
    surface = SelectionSurface(
        [
            SelectItem("Theme", value="theme"),
            SelectItem("Model Selection", value="model"),
        ],
        enable_search=True,
        filter_mode="fuzzy",
    )

    surface.handle_input(InputEvent(kind="text", text="ms"))

    lines = tuple(strip_control_sequences(line) for line in rendered_text(surface, width=40, height=5))
    assert lines[:3] == ("Search: ms", "", "> Model Selection")


def test_selection_surface_page_navigation_keeps_selected_item_visible() -> None:
    surface = SelectionSurface([SelectItem(f"item-{index}") for index in range(8)], max_visible=3)

    surface.handle_input(InputEvent(kind="key", key="pageDown"))

    assert surface.selected_index == 3
    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=20, height=4)) == (
        "  item-2",
        "> item-3",
        "  item-4",
        "  (4/8)",
    )


def test_selection_surface_home_end_navigation_jumps_to_edges() -> None:
    surface = SelectionSurface([SelectItem(f"item-{index}") for index in range(6)], max_visible=3)

    surface.handle_input(InputEvent(kind="key", key="end"))

    assert surface.selected_index == 5
    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=20, height=4)) == (
        "  item-3",
        "  item-4",
        "> item-5",
        "  (6/6)",
    )

    surface.handle_input(InputEvent(kind="key", key="home"))

    assert surface.selected_index == 0
    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=20, height=4)) == (
        "> item-0",
        "  item-1",
        "  item-2",
        "  (1/6)",
    )


def test_selection_surface_home_end_navigation_works_when_search_is_hidden() -> None:
    surface = SelectionSurface(
        [SelectItem(f"item-{index}") for index in range(6)],
        max_visible=3,
        enable_search=True,
        show_search_when_empty=False,
    )

    surface.handle_input(InputEvent(kind="key", key="end"))

    assert surface.selected_index == 5
    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=20, height=4)) == (
        "  item-3",
        "  item-4",
        "> item-5",
        "  (6/6)",
    )

    surface.handle_input(InputEvent(kind="key", key="home"))

    assert surface.selected_index == 0


def test_selection_surface_mouse_press_selects_visible_row_after_render() -> None:
    surface = SelectionSurface([SelectItem(f"item-{index}") for index in range(6)], max_visible=3)
    surface.handle_input(InputEvent(kind="key", key="pageDown"))
    rendered_text(surface, width=20, height=4)

    intent = surface.handle_input(
        InputEvent(
            kind="mouse",
            mouse_button=0,
            mouse_column=2,
            mouse_row=2,
            mouse_action="press",
        )
    )

    assert intent is None
    assert surface.selected_index == 4
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="select", text="item-4")


def test_selection_surface_empty_state_ignores_enter_and_mouse() -> None:
    surface = SelectionSurface([], empty_text="No items")

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=20, height=4)) == ("No items",)
    assert surface.handle_input(InputEvent(kind="key", key="enter")) is None
    assert surface.handle_input(InputEvent(kind="mouse", mouse_button=0, mouse_row=0, mouse_action="press")) is None
    assert surface.selected_item() is None


def test_autocomplete_surface_returns_completion_intent() -> None:
    surface = AutocompleteSurface([SelectItem("README.md", value="README.md")])

    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="complete", text="README.md")


def test_command_surface_filters_and_returns_command_intent() -> None:
    surface = CommandSurface(
        [SelectItem("/help", value="help"), SelectItem("/model", value="model")],
        query="/h",
    )

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=20, height=4)) == (
        "Search: /h",
        "",
        "> /help",
    )
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="command", text="help")


def test_command_surface_searches_from_typed_text() -> None:
    surface = CommandSurface(
        [
            SelectItem("/model", value="/model"),
            SelectItem("/status", value="/status"),
        ],
    )

    surface.handle_input(InputEvent(kind="text", text="sta"))

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=30, height=4)) == (
        "Search: sta",
        "",
        "> /status",
    )
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="command", text="/status")


def test_settings_surface_renders_description_and_returns_setting_intent() -> None:
    surface = SettingsSurface([SelectItem("Theme", value="theme", description="Change color theme")])

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=50, height=3)) == ("> Theme  Change color theme",)
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="setting", text="theme")


def test_settings_surface_cycles_values_and_reports_new_value() -> None:
    surface = SettingsSurface(
        [
            SettingItem(
                id="theme",
                label="Theme",
                current_value="dark",
                values=("dark", "light"),
                description="Terminal color theme",
            )
        ],
        max_visible=5,
    )

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=44, height=6)) == (
        "> Theme  dark",
        "",
        "  Terminal color theme",
        "",
        "  Enter/Space to change - Esc to cancel",
    )

    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="setting",
        text="theme",
        note="light",
    )
    assert strip_control_sequences(rendered_text(surface, width=44, height=3)[0]) == "> Theme  light"
    assert surface.handle_input(InputEvent(kind="text", text=" ")) == InputIntent(
        kind="setting",
        text="theme",
        note="dark",
    )


def test_settings_surface_wraps_selected_description() -> None:
    surface = SettingsSurface(
        [
            SettingItem(
                id="theme",
                label="Theme",
                current_value="dark",
                description="Controls how terminal color themes are rendered in compact layouts",
            )
        ],
        max_visible=5,
    )

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=28, height=5)) == (
        "> Theme  dark",
        "",
        "  Controls how terminal",
        "  color themes are rendered",
        "  in compact layouts",
    )


def test_settings_surface_can_delegate_value_selection_to_submenu() -> None:
    def submenu(_current: str, _done: Any) -> SelectionSurface:
        return SelectionSurface([SelectItem("GPT", value="gpt")])

    surface = SettingsSurface(
        [
            SettingItem(
                id="model",
                label="Model",
                current_value="kimi",
                submenu=submenu,
            )
        ],
    )

    assert surface.handle_input(InputEvent(kind="key", key="enter")) is None
    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=20, height=3)) == ("> GPT",)
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="setting",
        text="model",
        note="gpt",
    )
    assert surface.selected_setting() == SettingItem(
        id="model",
        label="Model",
        current_value="gpt",
        submenu=submenu,
    )


def test_settings_surface_search_filters_with_text_and_backspace() -> None:
    surface = SettingsSurface(
        [
            SettingItem(id="theme", label="Theme", current_value="dark"),
            SettingItem(id="model", label="Model", current_value="kimi"),
        ],
        enable_search=True,
    )

    surface.handle_input(InputEvent(kind="text", text="mo"))

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=36, height=5)[:3]) == (
        "Search: mo",
        "",
        "> Model  kimi",
    )

    surface.handle_input(InputEvent(kind="key", key="backspace"))

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=36, height=5)[:3]) == (
        "Search: m",
        "",
        "> Theme  dark",
    )


def test_settings_surface_search_uses_fuzzy_matching() -> None:
    surface = SettingsSurface(
        [
            SettingItem(id="model", label="Model Selection", current_value="gpt-5"),
            SettingItem(id="theme", label="Theme", current_value="dark"),
        ],
        enable_search=True,
    )

    surface.handle_input(InputEvent(kind="text", text="ms"))

    assert tuple(strip_control_sequences(line) for line in rendered_text(surface, width=40, height=5)[:3]) == (
        "Search: ms",
        "",
        "> Model Selection  gpt-5",
    )


def test_settings_surface_search_uses_text_input_cursor_editing() -> None:
    surface = SettingsSurface(
        [
            SettingItem(id="memory", label="Memory", current_value="on"),
            SettingItem(id="model", label="Model", current_value="kimi"),
        ],
        enable_search=True,
    )

    surface.handle_input(InputEvent(kind="text", text="mo"))
    surface.handle_input(InputEvent(kind="key", key="left"))
    surface.handle_input(InputEvent(kind="text", text="x"))
    result = surface.render(RenderConstraints(width=36, max_height=5))

    assert tuple(line.text for line in result.lines)[:3] == (
        "Search: mxo",
        "",
        "  No matching settings",
    )
    assert result.cursor is not None
    assert (result.cursor.row, result.cursor.column) == (0, len("Search: mx"))


def test_approval_surface_returns_explicit_approval_or_rejection() -> None:
    surface = ApprovalSurface(action="Run command", risk="writes files")

    assert rendered_text(surface, width=40, height=4) == (
        "Run command",
        "writes files",
        "[y] approve  [n] reject",
    )
    assert surface.handle_input(InputEvent(kind="key", key="y")) == InputIntent(kind="approve")
    assert surface.handle_input(InputEvent(kind="key", key="n")) == InputIntent(kind="reject")
    assert surface.handle_input(InputEvent(kind="text", text="y")) == InputIntent(kind="approve")
    assert surface.handle_input(InputEvent(kind="text", text="n")) == InputIntent(kind="reject")


def test_approval_surface_handle_input_carries_action_id() -> None:
    surface = ApprovalSurface(action="Delete cache", action_id="cache:delete")

    assert surface.handle_input(InputEvent(kind="key", key="y")) == InputIntent(
        kind="approve", note="cache:delete"
    )
    assert surface.handle_input(InputEvent(kind="key", key="n")) == InputIntent(
        kind="reject", note="cache:delete"
    )


def test_approval_surface_no_action_id_keeps_empty_note() -> None:
    surface = ApprovalSurface(action="Delete cache")

    assert surface.handle_input(InputEvent(kind="key", key="y")) == InputIntent(kind="approve", note="")
    assert surface.handle_input(InputEvent(kind="key", key="n")) == InputIntent(kind="reject", note="")


def test_dialog_surface_returns_confirm_cancel_and_escape_close_reasons() -> None:
    surface = DialogSurface(title="Switch model?", message="Unsaved draft remains")

    assert rendered_text(surface, width=40, height=4) == (
        "Switch model?",
        "Unsaved draft remains",
        "[enter] confirm  [esc] cancel",
    )
    assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(kind="dialog_confirm")
    assert surface.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(kind="dialog_cancel")
