from __future__ import annotations

from pathlib import Path

import pytest

from loushang.coding.ui.plugin_theme import (
    CodingPluginThemeError,
    select_coding_plugin_theme,
)
from loushang.harness.resources.types import (
    ResourceBundle,
    RevisionResourceRef,
    ThemeDescriptor,
)
from loushang.tui import LoushangWelcomePanel, RenderConstraints


def _bundle(tmp_path: Path, content: str, *, enabled: bool = True) -> ResourceBundle:
    return ResourceBundle(
        cwd=tmp_path,
        themes=[ThemeDescriptor(
            name="dusk",
            source_path=tmp_path / "themes" / "dusk.json",
            content=content,
            source="product_selected_snapshot",
            source_kind="external_package",
            source_scope="package",
            enabled=enabled,
            revision_ref=RevisionResourceRef(
                content_digest="a" * 64,
                relative_path="themes/dusk.json",
            ),
        )],
    )


def test_selected_package_theme_changes_visible_welcome_style(tmp_path: Path) -> None:
    selected = select_coding_plugin_theme(
        "plugin:dusk",
        _bundle(tmp_path, '{"schemaVersion":1,"tokens":{'
            '"welcome.title":{"color":"red"},'
            '"transcript.error":{"color":"bright_yellow"}}}'),
    )
    assert selected.disposition == "selected"
    assert selected.transcript_theme.resolve("transcript.error")["color"] == (
        "bright_yellow"
    )
    panel = LoushangWelcomePanel(theme=selected.welcome_theme)
    rendered = "\n".join(
        line.text for line in panel.render(
            RenderConstraints(width=42, max_height=15)
        ).lines
    )
    assert "\x1b[1;31m Loushang " in rendered


def test_disabled_package_theme_falls_back_without_loading_file(tmp_path: Path) -> None:
    selected = select_coding_plugin_theme(
        "plugin:dusk",
        _bundle(tmp_path, '{"schemaVersion":1,"tokens":{'
            '"welcome.title":{"color":"red"}}}', enabled=False),
    )
    assert selected.disposition == "unavailable"
    assert selected.welcome_theme.resolve("welcome.title")["color"] == "cyan"
    assert not (tmp_path / "themes").exists()


@pytest.mark.parametrize("content", [
    '{"schemaVersion":1,"tokens":{"welcome.title":{"color":"red",'
    '"color":"blue"}}}',
    '{"schemaVersion":1,"tokens":{"welcome.title":{"color":"\\u001b[31m"}}}',
    '{"schemaVersion":1,"tokens":{"unknown.token":{"color":"red"}}}',
])
def test_invalid_selected_theme_is_refused(
    tmp_path: Path, content: str
) -> None:
    with pytest.raises(CodingPluginThemeError):
        select_coding_plugin_theme("plugin:dusk", _bundle(tmp_path, content))
