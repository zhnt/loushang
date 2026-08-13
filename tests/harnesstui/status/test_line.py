from __future__ import annotations

from dataclasses import replace

from loushang.harnesstui.status.line import (
    StatusLinePreviewSnapshot,
    StatusLineSettings,
    status_line_fields,
    status_line_separator,
    status_line_style_mode,
)


def _snapshot(**overrides: object) -> StatusLinePreviewSnapshot:
    base = StatusLinePreviewSnapshot(
        model_label="moonshot/kimi-for-coding",
        cwd="/home/dev/workspace/loushang",
        branch="main",
        session_label="abcd",
        running=False,
    )
    return replace(base, **overrides)


def test_status_line_settings_defaults_match_product_defaults() -> None:
    settings = StatusLineSettings()

    assert settings.enabled is True
    assert settings.model is True
    assert settings.workspace is True
    assert settings.branch is True
    assert settings.session is True
    assert settings.permissions is True
    assert settings.runtime is True
    assert settings.queue == "auto"
    assert settings.message == "auto"
    assert settings.separator == "pipe"
    assert settings.style == "codex-like"


def test_status_line_fields_use_product_order_priority_and_tokens() -> None:
    fields = status_line_fields(
        _snapshot(
            running=True, pending_followups=2, pending_steers=1, status_message="Saved"
        ),
        StatusLineSettings(),
    )

    assert [(field.text, field.priority, field.token) for field in fields] == [
        ("moonshot/kimi-for-coding", 100, "model"),
        ("loushang", 90, "workspace"),
        ("main", 80, "branch"),
        ("abcd", 70, "session"),
        ("perm=standard", 35, "permissions"),
        ("running", 60, "runtime.running"),
        ("queued=2 steer=1", 50, "queue"),
        ("Saved", 40, "message"),
    ]


def test_status_line_fields_keep_current_missing_value_fallbacks() -> None:
    fields = status_line_fields(
        _snapshot(model_label=None, cwd="", branch=None, session_label=None),
        StatusLineSettings(),
    )

    assert [field.text for field in fields[:6]] == [
        "model",
        "cwd",
        "no-branch",
        "no-session",
        "perm=standard",
        "idle",
    ]
    assert fields[5].token == "runtime.idle"


def test_status_line_fields_can_disable_regular_fields() -> None:
    fields = status_line_fields(
        _snapshot(),
        StatusLineSettings(
            model=False,
            workspace=False,
            branch=False,
            session=False,
            permissions=False,
            runtime=False,
        ),
    )

    assert fields == ()


def test_status_line_queue_auto_true_false_behavior() -> None:
    snapshot = _snapshot()

    assert [
        field.text
        for field in status_line_fields(snapshot, StatusLineSettings(queue="auto"))
    ] == [
        "moonshot/kimi-for-coding",
        "loushang",
        "main",
        "abcd",
        "perm=standard",
        "idle",
    ]
    assert (
        status_line_fields(snapshot, StatusLineSettings(queue="true"))[-1].text
        == "queued=0 steer=0"
    )
    assert all(
        field.token != "queue"
        for field in status_line_fields(snapshot, StatusLineSettings(queue="false"))
    )


def test_status_line_queue_auto_shows_when_data_exists() -> None:
    fields = status_line_fields(
        _snapshot(pending_followups=1, pending_steers=3),
        StatusLineSettings(queue="auto"),
    )

    assert fields[-1].text == "queued=1 steer=3"
    assert fields[-1].token == "queue"


def test_status_line_message_auto_true_false_behavior() -> None:
    snapshot = _snapshot(status_message=None)

    assert all(
        field.token != "message"
        for field in status_line_fields(snapshot, StatusLineSettings(message="auto"))
    )
    assert (
        status_line_fields(snapshot, StatusLineSettings(message="true"))[-1].text
        == "no status"
    )
    assert all(
        field.token != "message"
        for field in status_line_fields(snapshot, StatusLineSettings(message="false"))
    )


def test_status_line_message_auto_shows_when_data_exists() -> None:
    fields = status_line_fields(
        _snapshot(status_message="Status line: on"), StatusLineSettings(message="auto")
    )

    assert fields[-1].text == "Status line: on"
    assert fields[-1].token == "message"


def test_status_line_separator_and_style_mapping() -> None:
    assert status_line_separator(StatusLineSettings(separator="pipe")) == " | "
    assert status_line_separator(StatusLineSettings(separator="dot")) == " · "
    assert (
        status_line_style_mode(StatusLineSettings(style="codex-like")) == "codex-like"
    )
    assert status_line_style_mode(StatusLineSettings(style="muted")) == "muted"
    assert status_line_style_mode(StatusLineSettings(style="plain")) == "plain"
