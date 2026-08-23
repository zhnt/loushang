from __future__ import annotations

import runpy
from typing import Any

from loushang.tui import (
    CommandPalette,
    CommandPaletteItem,
    CompletionItem,
    CompletionProvider,
    InputEvent,
    RenderConstraints,
    strip_control_sequences,
    visible_width,
)
from loushang.tui.ui_parts.widgets.command_palette import CommandPaletteView
from tests.tui.widget_example_playback import play_example


def intent_tuple(intent: object) -> tuple[str, str, str]:
    return (
        str(getattr(intent, "kind", "")),
        str(getattr(intent, "text", "")),
        str(getattr(intent, "note", "")),
    )


def intent_tuples(intents: object) -> tuple[tuple[str, str, str], ...]:
    if isinstance(intents, tuple):
        return tuple(intent_tuple(intent) for intent in intents)
    return (intent_tuple(intents),)


def test_command_palette_item_disabled_defaults_to_false() -> None:
    assert CommandPaletteItem("deploy").disabled is False
    assert CommandPaletteItem("archive", disabled=True).disabled is True


def test_harnesstui_palette_projection_keeps_disabled_out_of_scope() -> None:
    from loushang.harnesstui.commands.presentation import command_palette_select_items

    items = command_palette_select_items(
        CommandPalette(
            (
                CommandPaletteItem(
                    value="archive",
                    label="Archive release",
                    description="unavailable",
                    disabled=True,
                ),
            )
        )
    )

    assert len(items) == 1
    assert items[0].selected_value == "archive"
    assert not hasattr(items[0], "disabled")


def _items() -> tuple[CommandPaletteItem, ...]:
    return (
        CommandPaletteItem("deploy", "Deploy service", "Run deployment pipeline"),
        CommandPaletteItem("logs", "Open logs", "Show latest logs"),
        CommandPaletteItem("tests", "Run tests", "Execute test suite"),
        CommandPaletteItem("cache", "Clear cache", "Invalidate local cache"),
        CommandPaletteItem("worker", "Restart worker", "Restart background worker"),
        CommandPaletteItem("archive", "Archive release", "unavailable", disabled=True),
    )


def render_result(part: Any, *, width: int = 60, height: int = 10):
    return part.render(RenderConstraints(width=width, max_height=height))


def render_lines(part: Any, *, width: int = 60, height: int = 10) -> tuple[str, ...]:
    return tuple(line.text for line in render_result(part, width=width, height=height).lines)


def plain_lines(part: Any, *, width: int = 60, height: int = 10) -> tuple[str, ...]:
    return tuple(strip_control_sequences(line) for line in render_lines(part, width=width, height=height))


def test_command_palette_view_title_sources_and_private_snapshot() -> None:
    palette = CommandPalette(_items(), title="Actions")

    assert CommandPaletteView(palette).title == "Actions"
    assert CommandPaletteView(palette, title="").title == ""
    assert CommandPaletteView(_items()).title == "Command Palette"
    assert CommandPaletteView(_items(), title="Run").title == "Run"


def test_command_palette_view_query_is_internal_editor_backed() -> None:
    view = CommandPaletteView(_items(), query="dep")

    assert view.query == "dep"
    assert [item.value for item in view.filtered_items] == ["deploy"]

    view.set_query("log")
    assert view.query == "log"
    assert [item.value for item in view.filtered_items] == ["logs"]

    assert view.handle_input(InputEvent(kind="text", text="s")) is True
    assert view.query == "logs"
    assert [item.value for item in view.filtered_items] == ["logs"]


def test_command_palette_view_filters_value_label_and_description_case_insensitive_in_order() -> None:
    view = CommandPaletteView(_items())

    assert [item.value for item in view.filtered_items] == [
        "deploy",
        "logs",
        "tests",
        "cache",
        "worker",
        "archive",
    ]

    view.set_query("RUN")
    assert [item.value for item in view.filtered_items] == ["deploy", "tests"]

    view.set_query("restart")
    assert [item.value for item in view.filtered_items] == ["worker"]


def test_command_palette_from_completion_provider_preserves_existing_shape() -> None:
    palette = CommandPalette.from_completion_provider(
        CompletionProvider(
            (
                CompletionItem("/deploy", label="/deploy", description="Deploy app"),
            )
        ),
        title="Commands",
    )

    assert palette == CommandPalette(
        (CommandPaletteItem("/deploy", "/deploy", "Deploy app"),),
        title="Commands",
    )


def test_command_palette_view_disabled_items_render_but_navigation_skips_them() -> None:
    view = CommandPaletteView(_items())
    view.focus()

    view.set_query("archive")
    assert view.active_value == ""
    assert view.handle_input(InputEvent(kind="key", key="enter")) is None
    lines = plain_lines(view, width=60, height=10)
    assert not any(line.startswith("> Archive release") for line in lines)
    assert any("Archive release" in line for line in lines)


def test_command_palette_view_navigation_repairs_active_and_visible_window() -> None:
    view = CommandPaletteView(_items(), max_visible=2)
    view.focus()

    assert view.active_value == "deploy"
    assert view.handle_input(InputEvent(kind="key", key="down")) is True
    assert view.handle_input(InputEvent(kind="key", key="down")) is True
    assert view.active_value == "tests"

    lines = plain_lines(view, width=60, height=8)
    assert any(line.startswith("> Run tests") for line in lines)
    assert sum(line.startswith("> ") for line in lines) == 1

    assert view.handle_input(InputEvent(kind="key", key="ctrl+end")) is True
    assert view.active_value == "worker"
    assert view.handle_input(InputEvent(kind="key", key="ctrl+home")) is True
    assert view.active_value == "deploy"


def test_command_palette_view_select_and_cancel_intents_with_close_flags() -> None:
    view = CommandPaletteView(_items())

    assert intent_tuples(view.handle_input(InputEvent(kind="key", key="enter"))) == (
        ("command_select", "deploy", "Deploy service"),
        ("surface_close", "", ""),
    )

    stay_open = CommandPaletteView(_items(), close_on_select=False, close_on_cancel=False)
    assert intent_tuples(stay_open.handle_input(InputEvent(kind="key", key="enter"))) == (
        ("command_select", "deploy", "Deploy service"),
    )
    assert intent_tuples(stay_open.handle_input(InputEvent(kind="key", key="escape"))) == (
        ("command_cancel", "", ""),
    )
    assert intent_tuples(stay_open.handle_input(InputEvent(kind="key", key="esc"))) == (
        ("command_cancel", "", ""),
    )
    assert intent_tuples(view.handle_input(InputEvent(kind="key", key="ctrl+c"))) == (
        ("command_cancel", "", ""),
        ("surface_close", "", ""),
    )


def test_command_palette_view_home_end_edit_query_ctrl_edges_move_results() -> None:
    view = CommandPaletteView(_items(), query="dep")

    assert view.handle_input(InputEvent(kind="key", key="home")) is True
    assert view.handle_input(InputEvent(kind="text", text="x")) is True
    assert view.query == "xdep"
    assert view.active_value == ""

    view.set_query("")
    assert view.handle_input(InputEvent(kind="key", key="ctrl+end")) is True
    assert view.active_value == "worker"


def test_command_palette_view_preserves_active_value_across_query_changes() -> None:
    view = CommandPaletteView(_items())

    assert view.handle_input(InputEvent(kind="key", key="down")) is True
    assert view.active_value == "logs"

    view.set_query("log")
    assert view.active_value == "logs"

    view.set_query("run")
    assert view.active_value == "deploy"


def test_command_palette_view_paste_updates_query_and_repairs_active() -> None:
    view = CommandPaletteView(_items())

    assert view.handle_input(InputEvent(kind="paste", text="cache")) is True
    assert view.query == "cache"
    assert view.active_value == "cache"


def test_command_palette_view_respects_width_height_cursor_and_empty_state() -> None:
    view = CommandPaletteView(_items(), query="missing")
    view.focus()

    result = render_result(view, width=18, height=5)
    lines = tuple(strip_control_sequences(line.text) for line in result.lines)

    assert len(lines) <= 5
    assert all(visible_width(line) <= 18 for line in lines)
    assert any("No commands" in line for line in lines)
    assert result.cursor is not None


def test_command_palette_view_is_reexported_from_public_modules() -> None:
    from loushang.tui import CommandPaletteView
    from loushang.tui.ui_parts import CommandPaletteView as UiCommandPaletteView
    from loushang.tui.ui_parts.widgets import (
        CommandPaletteView as WidgetCommandPaletteView,
    )

    assert CommandPaletteView is UiCommandPaletteView
    assert CommandPaletteView is WidgetCommandPaletteView


def test_command_palette_view_theme_tokens_apply_without_width_changes() -> None:
    from loushang.tui import ThemeResolver

    theme = ThemeResolver(
        defaults={
            "widget.commandPalette.title": {"bold": True},
            "widget.commandPalette.queryLabel": {"color": "cyan"},
            "widget.commandPalette.queryText": {"color": "white"},
            "widget.commandPalette.placeholder": {"color": "bright_black"},
            "widget.commandPalette.section": {"bold": True},
            "widget.commandPalette.item": {"color": "white"},
            "widget.commandPalette.focus": {"bold": True, "color": "cyan"},
            "widget.commandPalette.disabled": {"dim": True},
            "widget.commandPalette.description": {"color": "bright_black"},
            "widget.commandPalette.empty": {"color": "bright_black"},
            "widget.commandPalette.footer": {"color": "bright_black"},
        }
    )
    view = CommandPaletteView(_items(), theme=theme)
    view.focus()

    raw = render_lines(view, width=60, height=10)
    plain = tuple(strip_control_sequences(line) for line in raw)

    assert raw[0].startswith("\x1b[1m")
    assert "\x1b[1;36m> Deploy service" in "\n".join(raw)
    assert all(visible_width(line) <= 60 for line in raw)
    assert all(visible_width(line) <= 60 for line in plain)


def test_widgets_command_palette_example_imports() -> None:
    namespace = runpy.run_path("examples/tui/51_widgets_command_palette.py", run_name="__test__")

    build_app = namespace["build_app"]
    app = build_app()
    result = app.render(RenderConstraints(width=80, max_height=20))

    assert callable(build_app)
    assert result.lines


def test_widgets_command_palette_example_playback_snapshots() -> None:
    frames = play_example(
        "examples/tui/51_widgets_command_palette.py",
        events=(
            ("down", InputEvent(kind="key", key="down")),
            ("type log", InputEvent(kind="text", text="log")),
            ("enter", InputEvent(kind="key", key="enter")),
            ("escape", InputEvent(kind="key", key="escape")),
        ),
        width=80,
        height=20,
    )

    assert frames[0].lines[:10] == (
        "Operations Console",
        "",
        "Status        Ready",
        "",
        "Commands",
        "Command Palette",
        "",
        "Search        Search commands",
        "",
        "Results",
    )
    assert any(line == "> Open logs  Show latest logs" for line in frames[1].lines)
    assert any(line == "> Open logs  Show latest logs" for line in frames[2].lines)
    assert any("Selected: Open logs" in line for line in frames[3].lines)
    assert any("Cancelled" in line for line in frames[4].lines)
