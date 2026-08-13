from __future__ import annotations

from loushang.harnesstui.settings.page import ConfigSettingsPage
from loushang.tui import InputEvent, InputIntent, RenderConstraints
from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.settings import ConfigRow, SettingsListPage


def _lines(page: ConfigSettingsPage, *, height: int = 12) -> tuple[str, ...]:
    result = page.render(RenderConstraints(width=72, max_height=height))
    return tuple(strip_control_sequences(line.text) for line in result.lines)


def test_config_settings_page_is_tui_settings_list_page_compatibility_alias() -> None:
    assert ConfigSettingsPage is SettingsListPage


def test_config_settings_page_renders_and_filters_rows() -> None:
    page = ConfigSettingsPage(
        (
            ConfigRow("terminal.progress", "Terminal progress", "false"),
            ConfigRow("terminal.show_images", "Show images", "true"),
        )
    )
    page.focus()

    assert page.handle_input(InputEvent(kind="text", text="progress")) is True

    lines = _lines(page)
    assert any("Setting" in line and "Value" in line for line in lines)
    assert any("Terminal progress" in line and "false" in line for line in lines)
    assert not any("Show images" in line for line in lines)


def test_config_settings_page_returns_boolean_setting_intent() -> None:
    page = ConfigSettingsPage(
        (ConfigRow("terminal.progress", "Terminal progress", "false"),)
    )
    page.focus()
    page.handle_input(InputEvent(kind="key", key="down"))

    result = page.handle_input(InputEvent(kind="key", key="enter"))

    assert result == InputIntent(kind="setting", text="terminal.progress", note="true")


def test_config_settings_page_ignores_disabled_row() -> None:
    page = ConfigSettingsPage((ConfigRow("locked", "Locked", "false", disabled=True),))
    page.focus()
    page.handle_input(InputEvent(kind="key", key="down"))

    assert page.handle_input(InputEvent(kind="key", key="enter")) is None


def test_config_settings_page_preserves_active_row_when_rows_change() -> None:
    page = ConfigSettingsPage(
        (
            ConfigRow("first", "First", "false"),
            ConfigRow("second", "Second", "true"),
        )
    )
    page.focus()
    page.handle_input(InputEvent(kind="key", key="down"))
    page.handle_input(InputEvent(kind="key", key="down"))

    page.set_rows(
        (
            ConfigRow("second", "Second", "false"),
            ConfigRow("third", "Third", "true"),
        ),
        preserve_active_key="second",
    )

    assert page.settings.active_item is not None
    assert page.settings.active_item.key == "second"
