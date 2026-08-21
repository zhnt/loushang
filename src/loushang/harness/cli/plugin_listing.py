"""Shared CLI plugin catalog discovery and projection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from loushang.harness.resources.plugins import (
    PluginResolutionAuthority,
    PluginSource,
    is_remote_plugin_source,
    project_installed_plugin,
)


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
        authority = PluginResolutionAuthority(disabled_plugins=tuple(disabled_plugins))
        plugins_by_name = {}
        for source in plugin_sources:
            plugin_source = (
                PluginSource(url=source, kind="remote")
                if is_remote_plugin_source(source)
                else PluginSource(path=Path(source).expanduser())
            )
            inspection = authority.inspect(plugin_source)
            inspection.raise_for_error()
            if inspection.plugin is None:
                raise ValueError(f"Plugin source could not be inspected: {source}")
            plugins_by_name[inspection.plugin.manifest.name] = inspection.plugin
        return [
            project_installed_plugin(plugins_by_name[name])
            for name in sorted(plugins_by_name)
        ]
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
