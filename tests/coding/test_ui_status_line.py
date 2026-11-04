from __future__ import annotations

from types import SimpleNamespace

from loushang.ai.model import Capabilities, Defaults, Model
from loushang.coding.model_reasoning import (
    effective_reasoning_label,
    reasoning_choice_label,
    reasoning_description,
)
from loushang.harnesstui.status.line import (
    StatusLinePreviewSnapshot,
    StatusLineSettings,
    status_line_fields,
    status_line_separator,
    status_line_style_mode,
)
from loushang.tui import RenderConstraints, StatusBar


def test_screen_app_statusline_preview_snapshot_includes_live_queue_and_message_state() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp

    app = ScreenCodingTuiApp(
        model_label="moonshot/kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label="abcd",
    )
    app.queue_followup("next prompt")
    app.queue_steer("interrupt")
    app.set_status("Saved")

    assert app.statusline_preview_snapshot() == StatusLinePreviewSnapshot(
        model_label="moonshot/kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        running=False,
        permission_profile="standard",
        pending_followups=1,
        pending_steers=1,
        status_message="Saved",
    )


def test_screen_app_real_status_bar_uses_shared_status_line_builder() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp

    app = ScreenCodingTuiApp(
        model_label="moonshot/kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label="abcd",
    )
    settings = StatusLineSettings(queue="true", message="true", separator="dot", style="plain")
    app.set_statusline_settings(settings)

    expected = StatusBar(
        status_line_fields(app.statusline_preview_snapshot(), settings),
        separator=status_line_separator(settings),
        style_mode=status_line_style_mode(settings),
    ).render(RenderConstraints(width=100, max_height=1))
    actual = app._status_bar().render(RenderConstraints(width=100, max_height=1))

    assert actual.lines[0].text == expected.lines[0].text
    assert actual.lines[0].text == (
        "moonshot/kimi-for-coding · repo · main · abcd · idle · "
        "queued=0 steer=0 · no status · standard"
    )


def test_model_preparation_uses_runtime_field_only_while_idle() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp

    app = ScreenCodingTuiApp(
        model_label="kimi-for-coding", cwd="/repo", branch="main", session_label="abcd"
    )
    app.state.sdk_preparing = True
    idle = app._status_bar().render(RenderConstraints(width=80, max_height=1))
    assert "idle · preparing model" in idle.lines[0].text
    narrow = app._status_bar().render(RenderConstraints(width=60, max_height=1))
    assert "idle · preparing model" in narrow.lines[0].text

    app.start_prompt("hello")
    running = app._status_bar().render(RenderConstraints(width=80, max_height=1))
    assert "running" in running.lines[0].text
    assert "preparing model" not in running.lines[0].text


def test_statusline_projects_live_reasoning_level_beside_model() -> None:
    from loushang.coding.ui.screen_app import ScreenCodingTuiApp

    app = ScreenCodingTuiApp(
        model_label="openai:openai-responses:gpt-6-sol",
        cwd="/repo",
        branch="main",
        session_label="abcd",
    )
    level = "high"
    app.reasoning_label_provider = lambda: level
    app.set_statusline_settings(StatusLineSettings(style="plain"))

    assert app.statusline_preview_snapshot().reasoning_label == "high"
    assert app._status_bar().render(RenderConstraints(width=90, max_height=1)).lines[
        0
    ].text.startswith("gpt-6-sol high |")

    level = "xhigh"
    assert app._status_bar().render(RenderConstraints(width=90, max_height=1)).lines[
        0
    ].text.startswith("gpt-6-sol xhigh |")


def test_unset_agent_effort_projects_model_default() -> None:
    session = SimpleNamespace(
        model=Model(
            id="gpt-6-sol",
            provider="openai",
            endpoint="responses",
            capabilities=Capabilities(reasoning=True),
            defaults=Defaults({"reasoningEffort": "medium"}),
        ),
        thinking_level="off",
    )

    assert effective_reasoning_label(session) == "medium"
    assert reasoning_choice_label("off") == "default"
    assert reasoning_description(session, "off") == "current · model default: medium"
