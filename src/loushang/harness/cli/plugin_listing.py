"""Shared CLI plugin catalog discovery and projection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from loushang.harness.resources.plugins import PluginManager, project_installed_plugin


class PluginListingError(RuntimeError):
    """Raised when plugin settings cannot be resolved."""


def list_plugin_records(settings_manager: object | None) -> list[dict[str, object]]:
    get_settings = getattr(settings_manager, "get_settings", None)
    if not callable(get_settings):
        raise PluginListingError("plugin settings are not available.")
    try:
        settings = get_settings()
        plugin_sources = getattr(settings, "plugin_sources", ())
        disabled_plugins = getattr(settings, "disabled_plugins", ())
        manager = PluginManager(disabled_plugins=tuple(disabled_plugins))
        for source in plugin_sources:
            manager.add_plugin_source(source)
        return [project_installed_plugin(plugin) for plugin in manager.list_plugins()]
    except Exception as error:
        raise PluginListingError(str(error)) from error


def format_plugin_records(
    records: Sequence[Mapping[str, object]],
    output_format: str,
) -> str:
    if output_format == "json":
        return json.dumps(records, ensure_ascii=False) + "\n"
    return "".join(
        f"{plugin['name']}\t{plugin['version']}\t{plugin['path']}\t"
        f"{plugin['enabled']}\n"
        for plugin in records
    )


__all__ = ["PluginListingError", "format_plugin_records", "list_plugin_records"]
