from __future__ import annotations

import asyncio

from loushang.ai.model import ModelSelection
from loushang.coding.ui.settings_page import build_coding_settings_page
from loushang.harnesstui.settings.workflow import SettingsPageView
from loushang.harnesstui.status.line import StatusLinePreviewSnapshot
from loushang.harnesstui.status.provider import StatusProvider
from loushang.tui import InputEvent, InputIntent, RenderConstraints
from loushang.tui.cell_width import strip_control_sequences


class _Session:
    def __init__(self) -> None:
        self.current_model = ModelSelection(
            endpoint_id="test-endpoint", provider="moonshot", model_id="kimi-for-coding"
        )
        self.models = (
            ModelSelection(
                endpoint_id="test-endpoint",
                provider="moonshot",
                model_id="kimi-for-coding",
            ),
            ModelSelection(
                endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
            ),
        )
        self.set_model_calls: list[object] = []

    def get_model_selection(self) -> object:
        return self.current_model

    def get_available_models(self) -> list[object]:
        return list(self.models)

    async def set_model(self, selection: object) -> None:
        self.set_model_calls.append(selection)
        self.current_model = selection


class _SettingsManager:
    def __init__(self) -> None:
        self.terminal_progress = False
        self.show_images = True
        self.clear_on_shrink = False
        self.image_auto_resize = True
        self.block_images = False
        self.retry_enabled = True
        self.default_model_calls: list[tuple[ModelSelection | None, str]] = []

    def get_show_terminal_progress(self) -> bool:
        return self.terminal_progress

    def set_show_terminal_progress(self, enabled: bool) -> None:
        self.terminal_progress = enabled

    def get_show_images(self) -> bool:
        return self.show_images

    def set_show_images(self, enabled: bool) -> None:
        self.show_images = enabled

    def get_clear_on_shrink(self) -> bool:
        return self.clear_on_shrink

    def set_clear_on_shrink(self, enabled: bool) -> None:
        self.clear_on_shrink = enabled

    def get_image_auto_resize(self) -> bool:
        return self.image_auto_resize

    def set_image_auto_resize(self, enabled: bool) -> None:
        self.image_auto_resize = enabled

    def get_block_images(self) -> bool:
        return self.block_images

    def set_block_images(self, enabled: bool) -> None:
        self.block_images = enabled

    def get_retry_enabled(self) -> bool:
        return self.retry_enabled

    def set_retry_enabled(self, enabled: bool) -> None:
        self.retry_enabled = enabled

    def set_default_model(
        self,
        selection: ModelSelection | None,
        *,
        scope: str = "session",
    ) -> None:
        self.default_model_calls.append((selection, scope))


def test_status_provider_exposes_read_only_snapshot() -> None:
    provider = StatusProvider(
        model_label="moonshot:test-endpoint:kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label=lambda: "abcd",
        thinking_level=lambda: "medium",
        running=lambda: False,
    )

    snapshot = provider.snapshot()

    assert snapshot.model_label == "moonshot:test-endpoint:kimi-for-coding"
    assert snapshot.cwd == "/repo"
    assert snapshot.branch == "main"
    assert snapshot.session_label == "abcd"
    assert snapshot.thinking_level == "medium"
    assert snapshot.running is False
    assert snapshot.statusline_visible is True


def _status_provider() -> StatusProvider:
    return StatusProvider(
        model_label="moonshot:test-endpoint:kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label=lambda: "abcd",
        thinking_level=lambda: None,
        running=lambda: False,
    )


def _preview_snapshot(**overrides: object) -> StatusLinePreviewSnapshot:
    from dataclasses import replace

    snapshot = StatusLinePreviewSnapshot(
        model_label="moonshot:test-endpoint:kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        running=False,
    )
    return replace(snapshot, **overrides)


def _page(
    settings_manager: object | None = None,
    *,
    statusline_preview: object | None = None,
) -> SettingsPageView:
    return asyncio.run(
        build_coding_settings_page(
            session=_Session(),
            status_provider=_status_provider(),
            settings_manager=settings_manager,
            statusline_preview=statusline_preview,
        )
    )


def _plain(
    page: SettingsPageView, *, width: int = 100, height: int = 18
) -> tuple[str, ...]:
    rendered = page.render(RenderConstraints(width=width, max_height=height))
    return tuple(strip_control_sequences(line.text) for line in rendered.lines)


def _raw(
    page: SettingsPageView, *, width: int = 100, height: int = 18
) -> tuple[str, ...]:
    return tuple(
        line.text
        for line in page.render(RenderConstraints(width=width, max_height=height)).lines
    )


def test_settings_page_uses_canonical_page_components() -> None:
    from loushang.harnesstui.settings.dashboard import (
        SettingsDashboard,
        StaticLinesPage,
    )
    from loushang.harnesstui.settings.model import ModelPage
    from loushang.harnesstui.settings.page import (
        ConfigSettingsPage,
    )
    from loushang.harnesstui.status.settings import StatusLineSettingsPage

    page = _page()

    assert isinstance(page, SettingsDashboard)
    assert type(page.status_page) is StaticLinesPage
    assert isinstance(page.config_page, ConfigSettingsPage)
    assert isinstance(page.model_page, ModelPage)
    assert isinstance(page.statusline_page, StatusLineSettingsPage)


def test_settings_page_opens_config_tab_with_search_focus() -> None:
    page = _page()
    lines = _plain(page)

    assert any(
        "Status" in line
        and "Config" in line
        and "Model" in line
        and "Status Line" in line
        for line in lines
    )
    assert "*[Config]" in lines[0]
    assert any("Search settings" in line for line in lines)
    assert not any("Status line" in line for line in lines[2:])
    assert page.editor_input_target() is not None


def test_settings_page_config_no_longer_shows_old_statusline_row() -> None:
    page = _page(settings_manager=_SettingsManager())

    assert not any(
        "Status line" in line for line in _plain(page, width=96, height=24)[2:]
    )


def test_settings_page_config_uses_boxed_search_table_columns_footer_and_styles() -> (
    None
):
    page = _page(settings_manager=_SettingsManager())
    raw_lines = _raw(page, width=96, height=24)
    lines = tuple(strip_control_sequences(line) for line in raw_lines)

    assert "\x1b[" in raw_lines[0]
    assert "*[Config]" in lines[0]
    assert "> [Config]" not in lines[0]
    assert any(line.startswith("╭") for line in lines)
    search_index = next(
        index for index, line in enumerate(lines) if "Search settings..." in line
    )
    assert lines[search_index].startswith("│ ")
    assert "\x1b[" in raw_lines[search_index]
    assert any(line.startswith("╰") for line in lines)
    assert lines[-1] == "Type to filter · Enter/↓ to select · ↑ to tabs · Esc to clear"
    assert not any("Current model" in line for line in lines)

    header = next(line for line in lines if "Setting" in line and "Value" in line)
    value_column = header.index("Value")
    terminal_line = next(line for line in lines if "Terminal progress" in line)
    assert terminal_line.index("false") >= value_column


def test_settings_page_search_filters_config_rows() -> None:
    page = _page(settings_manager=_SettingsManager())

    assert page.handle_input(InputEvent(kind="text", text="progress")) is True
    lines = _plain(page)

    assert any("Terminal progress" in line for line in lines)
    assert not any("Show images" in line for line in lines)


def test_settings_page_statusline_tab_rows_search_cycles_and_preview() -> None:
    page = _page()
    page.tabs.focus_header()
    page.handle_input(InputEvent(kind="key", key="right"))
    page.handle_input(InputEvent(kind="key", key="right"))
    page.handle_input(InputEvent(kind="key", key="down"))

    assert page.tabs.value == "status-line"
    lines = _plain(page, width=120, height=24)
    assert any("Search status line..." in line for line in lines)
    for label in (
        "Enabled",
        "Model",
        "Workspace",
        "Branch",
        "Session",
        "Runtime",
        "Queue",
        "Message",
        "Separator",
        "Style",
    ):
        assert any(label in line for line in lines)
    assert any(
        "moonshot:test-endpoint:kimi-for-coding" in line and "repo" in line
        for line in lines
    )

    assert page.handle_input(InputEvent(kind="text", text="style")) is True
    intent = page.handle_input(InputEvent(kind="key", key="enter"))

    assert intent == InputIntent(kind="setting", text="statusline.style", note="muted")


def test_settings_page_statusline_apply_updates_rows_and_preview() -> None:
    page = _page(
        statusline_preview=lambda: _preview_snapshot(
            pending_followups=1, pending_steers=2
        )
    )
    page.tabs.focus_header()
    page.handle_input(InputEvent(kind="key", key="right"))
    page.handle_input(InputEvent(kind="key", key="right"))
    page.handle_input(InputEvent(kind="key", key="down"))

    result = asyncio.run(page.apply_setting("statusline.separator", "dot"))

    assert result.statusline_settings is not None
    assert result.statusline_settings.separator == "dot"
    assert result.message == "Status line separator: dot"
    lines = _plain(page, width=120, height=24)
    assert any("Separator" in line and "dot" in line for line in lines)
    assert any(
        "moonshot:test-endpoint:kimi-for-coding · repo · main · abcd · idle · queued=1 steer=2"
        in line
        for line in lines
    )


def test_settings_page_statusline_enabled_toggle_returns_visibility_result() -> None:
    page = _page()

    result = asyncio.run(page.apply_setting("statusline.enabled", "false"))

    assert result.statusline_visible is False
    assert result.statusline_settings is not None
    assert result.statusline_settings.enabled is False
    assert result.message == "Status line: off"


def test_settings_page_terminal_progress_apply_updates_settings_manager_and_rows() -> (
    None
):
    settings_manager = _SettingsManager()
    page = _page(settings_manager=settings_manager)

    result = asyncio.run(page.apply_setting("terminal.progress", "true"))

    assert settings_manager.terminal_progress is True
    assert result.message == "Terminal progress: on"
    assert any("Terminal progress" in line and "true" in line for line in _plain(page))


def test_settings_page_down_moves_past_terminal_progress_when_more_config_rows_are_available() -> (
    None
):
    page = _page(settings_manager=_SettingsManager())

    assert page.handle_input(InputEvent(kind="key", key="down")) is True
    assert page.config_page.settings.active_key == "terminal.progress"

    assert page.handle_input(InputEvent(kind="key", key="down")) is True

    assert page.config_page.settings.active_key == "terminal.show_images"
    assert any(
        line.startswith("> Show images") for line in _plain(page, width=96, height=24)
    )


def test_settings_page_q_is_search_text_but_closes_from_list_focus() -> None:
    search_page = _page()

    assert search_page.handle_input(InputEvent(kind="text", text="q")) is True
    assert any("q" in line for line in _plain(search_page))

    list_page = _page(settings_manager=_SettingsManager())
    list_page.handle_input(InputEvent(kind="key", key="down"))

    assert list_page.handle_input(InputEvent(kind="text", text="q")) == InputIntent(
        kind="surface_close"
    )


def test_settings_page_search_editing_keys_do_not_switch_tabs() -> None:
    page = _page()

    before = page.tabs.value
    assert page.handle_input(InputEvent(kind="key", key="right")) is True

    assert page.tabs.value == before


def test_settings_page_up_from_search_declares_cursor_on_selected_tab() -> None:
    page = _page()

    assert page.handle_input(InputEvent(kind="key", key="up")) is True
    rendered = page.render(RenderConstraints(width=96, max_height=24))
    lines = tuple(strip_control_sequences(line.text) for line in rendered.lines)

    assert page.editor_input_target() is None
    assert rendered.cursor is not None
    assert rendered.cursor.row == 0
    assert rendered.cursor.column == lines[0].index(">[Config]")


def test_settings_page_model_tab_filters_and_selects_model() -> None:
    page = _page()
    page.tabs.focus_header()
    page.handle_input(InputEvent(kind="key", key="right"))
    page.handle_input(InputEvent(kind="key", key="down"))

    assert page.tabs.value == "model"
    assert page.handle_input(InputEvent(kind="text", text="gpt")) is True
    intent = page.handle_input(InputEvent(kind="key", key="enter"))

    assert intent == InputIntent(
        kind="setting", text="model.current", note="openai:test-endpoint:gpt-5.4"
    )


def test_settings_page_model_apply_persists_with_page_settings_manager() -> None:
    settings_manager = _SettingsManager()
    page = _page(settings_manager=settings_manager)

    result = asyncio.run(
        page.apply_setting("model.current", "openai:test-endpoint:gpt-5.4")
    )

    selection = ModelSelection(
        endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
    )
    assert result.message == "Model set: openai:test-endpoint:gpt-5.4"
    assert result.refresh_model_label is True
    assert settings_manager.default_model_calls == [(selection, "global")]
