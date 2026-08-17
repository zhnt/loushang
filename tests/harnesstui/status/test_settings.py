from __future__ import annotations

from loushang.harnesstui.status import settings as shared_settings
from loushang.harnesstui.status.line import (
    StatusLinePreviewSnapshot,
    StatusLineSettings,
)
from loushang.tui import RenderConstraints


def test_statusline_rows_are_product_neutral_view_data() -> None:
    rows = shared_settings.statusline_rows(
        StatusLineSettings(enabled=False, queue="true", separator="dot", style="plain")
    )

    assert [(row.id, row.value) for row in rows] == [
        ("statusline.enabled", "false"),
        ("statusline.field.model", "true"),
        ("statusline.field.workspace", "true"),
        ("statusline.field.branch", "true"),
        ("statusline.field.session", "true"),
        ("statusline.field.permissions", "true"),
        ("statusline.field.runtime", "true"),
        ("statusline.field.queue", "true"),
        ("statusline.field.message", "auto"),
        ("statusline.separator", "dot"),
        ("statusline.style", "plain"),
    ]


def test_next_statusline_value_preserves_existing_cycles() -> None:
    assert (
        shared_settings.next_statusline_value("statusline.enabled", "true") == "false"
    )
    assert (
        shared_settings.next_statusline_value("statusline.field.queue", "auto")
        == "true"
    )
    assert (
        shared_settings.next_statusline_value("statusline.field.queue", "true")
        == "false"
    )
    assert (
        shared_settings.next_statusline_value("statusline.field.queue", "false")
        == "auto"
    )
    assert (
        shared_settings.next_statusline_value("statusline.separator", "pipe") == "dot"
    )
    assert (
        shared_settings.next_statusline_value("statusline.style", "plain")
        == "codex-like"
    )


def test_statusline_page_keeps_preview_layout() -> None:
    page = shared_settings.StatusLineSettingsPage(
        statusline_settings=StatusLineSettings(),
        statusline_preview=lambda: StatusLinePreviewSnapshot(
            model_label="model",
            cwd="/workspace/repo",
            branch="main",
            session_label="session",
            running=False,
        ),
    )

    result = page.render(RenderConstraints(width=80, max_height=20))

    assert "Preview" in [line.text for line in result.lines]
    assert any("model" in line.text and "repo" in line.text for line in result.lines)


def test_statusline_page_keeps_compact_height_and_cursor_contract() -> None:
    page = shared_settings.StatusLineSettingsPage(
        statusline_settings=StatusLineSettings(),
        statusline_preview=lambda: StatusLinePreviewSnapshot(
            model_label=None,
            cwd="/workspace",
            branch=None,
            session_label=None,
            running=False,
        ),
    )
    page.focus()

    compact = page.render(RenderConstraints(width=60, max_height=6))
    expanded = page.render(RenderConstraints(width=60, max_height=7))
    compact_lines = tuple(line.text for line in compact.lines)
    expanded_lines = tuple(line.text for line in expanded.lines)

    assert not any("Setting" in line and "Value" in line for line in compact_lines)
    assert "Preview" not in compact_lines
    assert any("Setting" in line and "Value" in line for line in expanded_lines)
    assert "Preview" in expanded_lines
    assert compact.cursor is not None and compact.cursor.row == 1
    assert expanded.cursor is not None and expanded.cursor.row == 1


def test_statusline_page_updates_composed_rows_without_replacing_public_list() -> None:
    page = shared_settings.StatusLineSettingsPage(
        statusline_settings=StatusLineSettings(),
        statusline_preview=lambda: StatusLinePreviewSnapshot(
            model_label=None,
            cwd="/workspace",
            branch=None,
            session_label=None,
            running=False,
        ),
    )
    public_list = page.settings
    page.focus()
    page.settings.focus_list()

    page.set_statusline_settings(
        StatusLineSettings(enabled=False),
        preserve_active_key="statusline.enabled",
    )

    assert page.settings is public_list
    assert page.settings.active_item is not None
    assert page.settings.active_item.key == "statusline.enabled"
    assert page.settings.active_item.value == "false"
