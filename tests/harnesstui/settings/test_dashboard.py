from __future__ import annotations

from dataclasses import dataclass

from loushang.harnesstui.settings.dashboard import (
    SettingsDashboard,
    StaticLinesPage,
    model_usage_lines,
    stats_overview_lines,
    status_lines,
    usage_lines,
)
from loushang.harnesstui.settings.page import ConfigSettingsPage
from loushang.tui import InputEvent, InputIntent, RenderConstraints, TabGroup, TabPage
from loushang.tui.cell_width import strip_control_sequences
from loushang.tui.settings import ConfigRow


@dataclass(frozen=True)
class _Status:
    model_label: str | None = "provider/model"
    cwd: str = "/repo"
    branch: str | None = "main"
    session_label: str | None = "abcd"
    thinking_level: str | None = "medium"
    running: bool = False
    statusline_visible: bool = True


def _dashboard() -> SettingsDashboard:
    page = ConfigSettingsPage((ConfigRow("feature", "Feature", "false"),))
    dashboard = SettingsDashboard()
    dashboard.tabs = TabGroup(
        (TabPage("config", "Config", page),),
        value="config",
    )
    dashboard.focus()
    return dashboard


def test_dashboard_owns_shared_focus_chrome_footer_and_close_interaction() -> None:
    dashboard = _dashboard()

    assert dashboard.focus_context() == "search"
    lines = tuple(
        strip_control_sequences(line.text)
        for line in dashboard.render(RenderConstraints(width=80, max_height=12)).lines
    )
    assert lines[1] == "-" * 80
    assert lines[-1] == "Type to filter · Enter/↓ to select · ↑ to tabs · Esc to clear"

    assert dashboard.handle_input(InputEvent(kind="key", key="down")) is True
    assert dashboard.focus_context() == "settings-list"
    assert dashboard.handle_input(InputEvent(kind="text", text="q")) == InputIntent(
        kind="surface_close"
    )


def test_dashboard_escape_closes_from_any_focus_context() -> None:
    dashboard = _dashboard()

    assert dashboard.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(
        kind="surface_close"
    )


def test_static_lines_page_truncates_and_consumes_horizontal_navigation() -> None:
    page = StaticLinesPage(("123456", "second"))

    rendered = page.render(RenderConstraints(width=4, max_height=1))

    assert tuple(strip_control_sequences(line.text) for line in rendered.lines) == (
        "1234",
    )
    assert page.handle_input(InputEvent(kind="key", key="left")) is True


def test_dashboard_view_models_format_neutral_status_and_usage_snapshots() -> None:
    status = _Status()

    assert status_lines(status)[2:] == (
        "Model              provider/model",
        "Workspace          /repo",
        "Branch             main",
        "Session            abcd",
        "Thinking           medium",
        "Runtime            idle",
        "Status line        true",
    )
    assert stats_overview_lines(status)[2:] == (
        "Session            abcd",
        "Runtime            idle",
        "Historical stats   Unavailable",
    )
    assert model_usage_lines("provider/model")[2] == "Current model      provider/model"
    assert usage_lines(None) == ("Usage", "", "Usage data unavailable")


def test_dashboard_usage_view_model_contains_provider_failures() -> None:
    def _failed_provider() -> object:
        raise RuntimeError("secret product failure")

    assert usage_lines(_failed_provider) == ("Usage", "", "Usage data unavailable")
