from __future__ import annotations

from types import SimpleNamespace

from loushang.tui import (
    InputEvent,
    InputIntent,
    RenderConstraints,
    SearchableListItem,
    visible_width,
)
from loushang.tui import settings as tui_settings
from loushang.tui.cell_width import strip_control_sequences


def test_config_rows_build_searchable_items_and_lookup_by_key() -> None:
    rows = (
        tui_settings.ConfigRow("enabled", "Enabled", "true"),
        tui_settings.ConfigRow("locked", "Locked", "false", "Managed", disabled=True),
    )

    assert tui_settings.config_items(rows) == (
        SearchableListItem("enabled", "Enabled", "true", "", disabled=False),
        SearchableListItem("locked", "Locked", "false", "Managed", disabled=True),
    )
    assert tui_settings.row_for_key(rows, "locked") is rows[1]
    assert tui_settings.row_for_key(rows, "missing") is None


def test_settings_input_and_boolean_helpers_preserve_existing_contract() -> None:
    assert tui_settings.as_bool("TRUE") is True
    assert tui_settings.as_bool("false") is False
    assert tui_settings.as_bool("auto") is None
    assert tui_settings.next_bool_value("true") == "false"
    assert tui_settings.next_bool_value("false") == "true"
    assert tui_settings.next_bool_value("auto") == "auto"
    assert tui_settings.is_space_event(SimpleNamespace(kind="key", key="space"))
    assert tui_settings.is_space_event(SimpleNamespace(kind="text", text=" "))
    assert tui_settings.is_tab_fallback_key(SimpleNamespace(kind="key", key="left"))
    assert not tui_settings.is_tab_fallback_key(SimpleNamespace(kind="key", key="tab"))


def test_settings_header_respects_available_width() -> None:
    assert tui_settings.settings_header(80) == f"{'Setting':<42}Value"
    assert visible_width(tui_settings.settings_header(12)) <= 12


def test_settings_list_page_preserves_compact_and_table_layout_contract() -> None:
    page = tui_settings.SettingsListPage(
        (
            tui_settings.ConfigRow("first", "First", "false"),
            tui_settings.ConfigRow("second", "Second", "true"),
        )
    )
    page.focus()

    compact = page.render(RenderConstraints(width=40, max_height=4))
    table = page.render(RenderConstraints(width=40, max_height=6))
    compact_lines = tuple(strip_control_sequences(line.text) for line in compact.lines)
    table_lines = tuple(strip_control_sequences(line.text) for line in table.lines)

    assert not any("Setting" in line and "Value" in line for line in compact_lines)
    assert table_lines[3] == ""
    assert "Setting" in table_lines[4] and "Value" in table_lines[4]
    assert compact.cursor is not None and compact.cursor.row == 1
    assert table.cursor is not None and table.cursor.row == 1


def test_settings_list_page_supports_product_neutral_selection_and_tab_fallback() -> None:
    selected: list[tui_settings.ConfigRow] = []
    row = tui_settings.ConfigRow("mode", "Mode", "auto")
    page = tui_settings.SettingsListPage(
        (row,),
        placeholder="Find an option...",
        empty_text="No options",
        on_select=lambda selected_row: selected.append(selected_row) or "selected",
    )
    page.focus()

    assert page.handle_input(InputEvent(kind="key", key="enter")) == "selected"
    assert selected == [row]
    assert page.handle_input(InputEvent(kind="key", key="down")) is True
    assert page.handle_input(InputEvent(kind="key", key="left")) is True


def test_settings_list_page_defaults_to_boolean_setting_intent() -> None:
    page = tui_settings.SettingsListPage((tui_settings.ConfigRow("enabled", "Enabled", "false"),))
    page.focus()

    assert page.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="setting",
        text="enabled",
        note="true",
    )
