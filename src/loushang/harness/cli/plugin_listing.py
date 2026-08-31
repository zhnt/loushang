"""Pure CLI formatting over the common Plugin management query port."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from loushang.harness.cli.plugin_management import PluginManagementCliBinding


class PluginListingError(RuntimeError):
    """Raised when the management projection cannot be queried."""


def list_plugin_records(
    management: PluginManagementCliBinding | None,
) -> list[dict[str, object]]:
    if management is None:
        raise PluginListingError("plugin management query is not available.")
    try:
        projection = management.query(correlation_id="cli:list-plugins")
        return [_project_cli_record(item) for item in projection.installations]
    except Exception as error:
        raise PluginListingError(str(error)) from error


def _project_cli_record(view: object) -> dict[str, object]:
    key = getattr(view, "installation_key")
    source = getattr(view, "source")
    package = getattr(view, "selected_package_revision")
    source_kind = "unknown" if source is None else source.source_kind
    source_location = (
        package.package_source_identity
        if source is None and package is not None
        else ""
        if source is None or source.source_location is None
        else source.source_location
    )
    plugin_version = (
        package.plugin_version
        if source is None and package is not None
        else (
            None
            if source is None
            else source.plugin_version
            or (None if package is None else package.plugin_version)
        )
    )
    desired_state = getattr(view, "desired_state")
    enabled = {
        "installed_enabled": True,
        "installed_disabled": False,
        "absent": False,
    }.get(desired_state)
    return {
        "name": key.plugin_id,
        "version": plugin_version or "",
        "path": source_location if source_kind == "local" else "",
        "source": source_location,
        "kind": source_kind,
        "enabled": enabled,
        "desiredState": desired_state,
        "convergence": getattr(view, "convergence"),
        "migrationStatus": getattr(view, "enablement_migration_phase"),
    }


def format_plugin_records(
    records: Sequence[Mapping[str, object]],
    output_format: str,
) -> str:
    if output_format == "json":
        return json.dumps(records, ensure_ascii=False) + "\n"
    return "".join(
        f"{plugin['name']}\t{plugin['version']}\t{plugin['path']}\t"
        f"{'unknown' if plugin['enabled'] is None else plugin['enabled']}\n"
        for plugin in records
    )


__all__ = ["PluginListingError", "format_plugin_records", "list_plugin_records"]
