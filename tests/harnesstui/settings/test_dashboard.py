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


def test_dashboard_usage_view_formats_context_and_cumulative_coverage() -> None:
    lines = usage_lines(
        lambda: {
            "context": {
                "tokens": 84_000,
                "contextWindow": 128_000,
                "percent": 65.625,
                "source": "estimated_from_last_usage",
                "staleAfterCompaction": False,
            },
            "tokens": {
                "input": 100,
                "output": 20,
                "cacheRead": 30,
                "cacheWrite": 40,
                "total": 190,
                "source": "logical_outcome_derived",
                "incompleteAttempts": True,
            },
        }
    )

    assert lines[2:] == (
        "Current context    ≈84,000",
        "Context window     128,000",
        "Percent used       65.6%",
        "Context source     estimated_from_last_usage",
        "Freshness          current",
        "",
        "Cumulative input  100",
        "Cumulative output 20",
        "Cache read        30",
        "Cache write       40",
        "Cumulative total  190",
        "Coverage source   logical_outcome_derived",
        "Usage accuracy    Historical estimate",
    )


def test_dashboard_usage_view_explains_accuracy_without_hiding_source() -> None:
    def _lines(source: str, incomplete: bool) -> tuple[str, ...]:
        return usage_lines(
            lambda: {
                "context": None,
                "tokens": {
                    "input": 1,
                    "output": 2,
                    "cacheRead": 3,
                    "cacheWrite": 4,
                    "total": 10,
                    "source": source,
                    "incompleteAttempts": incomplete,
                },
            }
        )

    exact = _lines("attempt_usage_facts", False)
    partial = _lines("mixed_derived", True)
    historical = _lines("legacy_derived", True)
    unknown = _lines("unexpected", False)

    assert "Coverage source   attempt_usage_facts" in exact
    assert "Usage accuracy    Exact" in exact
    assert "Usage accuracy    Partial estimate" in partial
    assert "Usage accuracy    Historical estimate" in historical
    assert "Usage accuracy    Unavailable" in unknown
