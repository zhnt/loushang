"""Coding screen consumer for one selected, Catalog-admitted Theme document."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from loushang.foundation.observability import get_log
from loushang.harness.resources.theme_document import (
    ThemeDocumentError,
    parse_theme_document_v1,
)
from loushang.harness.resources.types import ResourceBundle, ThemeDescriptor
from loushang.harnesstui.conversation.theme import terminal_transcript_theme
from loushang.tui import loushang_welcome_theme
from loushang.tui.theme import ThemeResolver, ThemeStyle

_THEME_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
log = get_log(__name__).bind(component="CodingPluginTheme")


class CodingPluginThemeError(ValueError):
    """An explicitly selected Theme cannot be safely applied."""


@dataclass(frozen=True, slots=True)
class CodingPluginThemeSelectionV1:
    disposition: Literal["builtin", "selected", "unavailable"]
    theme_name: str | None
    transcript_theme: ThemeResolver
    welcome_theme: ThemeResolver


def select_coding_plugin_theme(
    setting: str | None,
    bundle: ResourceBundle | None,
) -> CodingPluginThemeSelectionV1:
    """Use only captured Catalog content; never inspect a Theme's source path."""

    transcript = terminal_transcript_theme()
    welcome = loushang_welcome_theme()
    if setting is None or not setting.startswith("plugin:"):
        return CodingPluginThemeSelectionV1("builtin", None, transcript, welcome)
    name = setting.removeprefix("plugin:")
    if _THEME_NAME.fullmatch(name) is None or len(name) > 64:
        raise CodingPluginThemeError("Coding Plugin Theme selection is invalid")
    matches = tuple(
        item for item in (() if bundle is None else bundle.themes)
        if isinstance(item, ThemeDescriptor)
        and item.enabled
        and item.name == name
        and item.source == "product_selected_snapshot"
        and item.source_kind == "external_package"
        and item.revision_ref is not None
    )
    if not matches:
        return CodingPluginThemeSelectionV1("unavailable", name, transcript, welcome)
    if len(matches) != 1:
        raise CodingPluginThemeError("Coding Plugin Theme selection is ambiguous")
    tokens = parse_coding_plugin_theme_document(matches[0].content)
    transcript.update_overrides({
        key: value for key, value in tokens.items() if not key.startswith("welcome.")
    })
    welcome.update_overrides({
        key: value for key, value in tokens.items() if key.startswith("welcome.")
    })
    return CodingPluginThemeSelectionV1("selected", name, transcript, welcome)


def apply_coding_plugin_theme_to_screen(app: Any, current: Any) -> None:
    settings_manager = getattr(current, "settings_manager", None)
    theme_getter = getattr(settings_manager, "get_theme", None)
    theme_setting = theme_getter() if callable(theme_getter) else None
    if not isinstance(theme_setting, str) or not theme_setting.startswith("plugin:"):
        return
    selection = select_coding_plugin_theme(
        theme_setting, getattr(current, "resource_bundle", None)
    )
    app.transcript_theme = selection.transcript_theme
    app.welcome_theme = selection.welcome_theme
    if selection.disposition == "unavailable":
        log.problem(
            "coding_plugin_theme_unavailable",
            source="tui",
            message="Selected Plugin Theme is unavailable; using Coding defaults",
            recoverable=True,
        )


def parse_coding_plugin_theme_document(content: str | None) -> dict[str, ThemeStyle]:
    """Validate a bounded, style-only document before the screen receives it."""

    try:
        return parse_theme_document_v1(content)
    except ThemeDocumentError as exc:
        raise CodingPluginThemeError(str(exc)) from exc


__all__ = [
    "apply_coding_plugin_theme_to_screen",
    "CodingPluginThemeError",
    "CodingPluginThemeSelectionV1",
    "parse_coding_plugin_theme_document",
    "select_coding_plugin_theme",
]
