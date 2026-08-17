from __future__ import annotations

import pytest

from loushang.harnesstui.status.line import StatusLineSettings
from loushang.harnesstui.status.provider import StatusProvider
from loushang.harnesstui.status.snapshot import StatusSnapshot


def _provider(
    *,
    settings: StatusLineSettings | None = None,
    on_changed: list[StatusLineSettings] | None = None,
) -> StatusProvider:
    return StatusProvider(
        model_label=None,
        cwd="/repo",
        branch=None,
        session_label=lambda: None,
        thinking_level=lambda: None,
        running=lambda: False,
        statusline_settings=settings,
        on_statusline_settings_changed=None
        if on_changed is None
        else on_changed.append,
    )


def test_status_provider_returns_shared_snapshot() -> None:
    provider = StatusProvider(
        model_label="moonshot/kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label=lambda: "abcd",
        thinking_level=lambda: "high",
        running=lambda: True,
        statusline_settings=StatusLineSettings(enabled=False),
    )

    snapshot = provider.snapshot()

    assert type(snapshot) is StatusSnapshot
    assert snapshot == StatusSnapshot(
        model_label="moonshot/kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        thinking_level="high",
        running=True,
        statusline_visible=False,
        statusline_settings=StatusLineSettings(enabled=False),
    )


def test_status_provider_tracks_statusline_visibility() -> None:
    saved: list[StatusLineSettings] = []
    provider = _provider(
        settings=StatusLineSettings(enabled=False, style="muted"),
        on_changed=saved,
    )

    assert provider.is_visible() is False
    assert provider.statusline_settings() == StatusLineSettings(
        enabled=False, style="muted"
    )
    assert provider.set_visible(True) == "Status line: on"
    assert provider.is_visible() is True
    assert provider.statusline_settings().enabled is True
    assert provider.set_visible(None) == "Status line: on"
    assert saved == [StatusLineSettings(enabled=True, style="muted")]


def test_status_provider_notifies_for_explicit_same_value_but_not_for_read_only_visibility() -> (
    None
):
    saved: list[StatusLineSettings] = []
    provider = _provider(on_changed=saved)

    assert provider.set_visible(True) == "Status line: on"
    assert saved == [StatusLineSettings()]

    assert provider.set_visible(None) == "Status line: on"
    assert saved == [StatusLineSettings()]


def test_status_provider_reloads_dynamic_snapshot_values() -> None:
    state: dict[str, str | bool | None] = {
        "session": "first",
        "thinking": "low",
        "running": False,
    }
    provider = StatusProvider(
        model_label="model",
        cwd="/repo",
        branch="main",
        session_label=lambda: (
            state["session"] if isinstance(state["session"], str) else None
        ),
        thinking_level=lambda: (
            state["thinking"] if isinstance(state["thinking"], str) else None
        ),
        running=lambda: state["running"] is True,
    )

    first = provider.snapshot()
    state.update(session="second", thinking="high", running=True)
    second = provider.snapshot()

    assert (first.session_label, first.thinking_level, first.running) == (
        "first",
        "low",
        False,
    )
    assert (second.session_label, second.thinking_level, second.running) == (
        "second",
        "high",
        True,
    )


def test_status_provider_updates_session_bound_context() -> None:
    provider = _provider()

    provider.update_context(
        model_label="openai/gpt-5.4",
        cwd="/next",
        branch="feature/resume",
    )

    snapshot = provider.snapshot()
    assert (
        snapshot.model_label,
        snapshot.cwd,
        snapshot.branch,
    ) == (
        "openai/gpt-5.4",
        "/next",
        "feature/resume",
    )


def test_status_provider_applies_full_statusline_settings() -> None:
    saved: list[StatusLineSettings] = []
    provider = _provider(on_changed=saved)
    settings = StatusLineSettings(
        enabled=False,
        queue="true",
        message="false",
        separator="dot",
        style="muted",
    )

    assert provider.apply_statusline_settings(settings) == "Status line: off"

    assert provider.statusline_settings() == settings
    assert provider.is_visible() is False
    assert saved == [settings]


def test_status_provider_applies_individual_statusline_settings() -> None:
    saved: list[StatusLineSettings] = []
    provider = _provider(on_changed=saved)

    assert (
        provider.apply_statusline_setting("statusline.enabled", "false")
        == "Status line: off"
    )
    assert (
        provider.apply_statusline_setting("statusline.field.queue", "true")
        == "Status line queue: true"
    )
    assert (
        provider.apply_statusline_setting("statusline.separator", "dot")
        == "Status line separator: dot"
    )
    assert (
        provider.apply_statusline_setting("statusline.style", "plain")
        == "Status line style: plain"
    )

    settings = provider.statusline_settings()
    assert settings.enabled is False
    assert settings.queue == "true"
    assert settings.separator == "dot"
    assert settings.style == "plain"
    assert saved == [
        StatusLineSettings(enabled=False),
        StatusLineSettings(enabled=False, queue="true"),
        StatusLineSettings(enabled=False, queue="true", separator="dot"),
        StatusLineSettings(enabled=False, queue="true", separator="dot", style="plain"),
    ]


@pytest.mark.parametrize(
    ("item_id", "field_name"),
    [
        ("statusline.field.model", "model"),
        ("statusline.field.workspace", "workspace"),
        ("statusline.field.branch", "branch"),
        ("statusline.field.session", "session"),
        ("statusline.field.runtime", "runtime"),
    ],
)
def test_status_provider_applies_each_boolean_field(
    item_id: str, field_name: str
) -> None:
    saved: list[StatusLineSettings] = []
    provider = _provider(on_changed=saved)

    assert provider.apply_statusline_setting(item_id, "false") == (
        f"Status line {field_name}: false"
    )
    assert getattr(provider.statusline_settings(), field_name) is False
    assert saved == [provider.statusline_settings()]


def test_status_provider_keeps_statusline_alias_and_casefold_contract() -> None:
    saved: list[StatusLineSettings] = []
    provider = _provider(on_changed=saved)

    assert (
        provider.apply_statusline_setting("statusline", "FALSE") == "Status line: off"
    )
    current = provider.statusline_settings()
    assert provider.apply_statusline_setting("statusline", " false ") == (
        "Invalid status line enabled value."
    )
    assert provider.statusline_settings() == current
    assert saved == [current]


def test_status_provider_rejects_invalid_statusline_setting_values() -> None:
    saved: list[StatusLineSettings] = []
    provider = _provider(on_changed=saved)

    assert provider.apply_statusline_setting("statusline.field.queue", "maybe") == (
        "Invalid status line queue value."
    )
    assert provider.apply_statusline_setting("statusline.separator", "slash") == (
        "Invalid status line separator value."
    )
    assert provider.apply_statusline_setting("statusline.unknown", "true") == (
        "Unknown status line setting: statusline.unknown"
    )
    assert provider.statusline_settings().queue == "auto"
    assert provider.statusline_settings().separator == "pipe"
    assert provider.statusline_settings() == StatusLineSettings()
    assert saved == []


def test_status_provider_formats_plain_settings_summary() -> None:
    provider = StatusProvider(
        model_label="moonshot/kimi",
        cwd="/repo",
        branch="main",
        session_label=lambda: "abc",
        thinking_level=lambda: "high",
        running=lambda: False,
    )

    assert provider.settings_summary_text() == "Settings\nStatus line: true"
    assert not hasattr(provider, "legacy_settings_list")
    assert not hasattr(provider, "legacy_settings_text")
    provider.set_visible(False)
    assert provider.settings_summary_text() == "Settings\nStatus line: false"
