"""Pure CLI formatting over the common Plugin management query port."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence

from loushang.harness.cli.plugin_management import (
    PluginManagementCliBinding,
    is_plugin_terminal_string_list,
)
from loushang.harness.plugin_management import (
    PluginManagementInstallationViewV1,
    PluginManagementProjectionV1,
)


class PluginListingError(RuntimeError):
    """Raised when the management projection cannot be queried."""


def list_plugin_records(
    management: PluginManagementCliBinding | None,
) -> list[dict[str, object]]:
    if management is None:
        raise PluginListingError("plugin management query is not available.")
    try:
        projection = management.query(correlation_id="cli:list-plugins")
        return [
            _project_cli_record(item, projection=projection)
            for item in projection.installations
        ]
    except Exception as error:
        raise PluginListingError(str(error)) from error


def _project_cli_record(
    view: PluginManagementInstallationViewV1,
    *,
    projection: PluginManagementProjectionV1,
) -> dict[str, object]:
    key = view.installation_key
    source = view.source
    package = view.selected_package_revision
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
        if package is not None
        else None
        if source is None
        else source.plugin_version
    )
    desired_state = view.desired_state
    enabled = {
        "installed_enabled": True,
        "installed_disabled": False,
        "absent": False,
    }.get(desired_state)
    management = view.to_dict()
    management["ownerRevisions"] = projection.owner_revisions.to_dict()
    management["skew"] = [
        item.to_dict()
        for item in projection.skew
        if item.installation_key == key
    ]
    return {
        "name": key.plugin_id,
        "version": plugin_version or "",
        "path": source_location if source_kind == "local" else "",
        "source": source_location,
        "kind": source_kind,
        "enabled": enabled,
        "desiredState": desired_state,
        "convergence": view.convergence,
        "migrationStatus": view.enablement_migration_phase,
        "management": management,
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


def render_plugin_management_list(
    document: dict[str, object],
    *,
    repair_command: Callable[[str, str], str | None],
) -> str:
    """Summarize the management owner's Desired State and unknown evidence."""

    if document.get("projectionVersion") != 1:
        raise ValueError("Plugin management projection is unsupported")
    revisions = document.get("ownerRevisions")
    revision = revisions.get("desiredState") if isinstance(revisions, dict) else None
    if type(revision) is not int or revision < 0:
        raise ValueError("Plugin management Desired State revision is invalid")
    installations = document.get("installations")
    if not isinstance(installations, list):
        raise ValueError("Plugin management Installations are invalid")
    entries: list[str] = []
    for item in installations:
        if not isinstance(item, dict):
            raise ValueError("Plugin management Installation is invalid")
        key = item.get("installationKey")
        plugin_id = key.get("pluginId") if isinstance(key, dict) else None
        desired = item.get("desiredState")
        convergence = item.get("convergence")
        unknown = item.get("unknownDimensions")
        operations = item.get("operations")
        if (
            not all(
                isinstance(value, str) and value and value.isprintable()
                for value in (plugin_id, desired, convergence)
            )
            or not is_plugin_terminal_string_list(unknown)
            or not isinstance(operations, list)
        ):
            raise ValueError("Plugin management Installation is invalid")
        pending: list[str] = []
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("Plugin management operation is invalid")
            if operation.get("status") in {"accepted", "running"}:
                operation_id = operation.get("operationId")
                actor_id = operation.get("actorId")
                if (
                    not isinstance(operation_id, str)
                    or not operation_id.isprintable()
                    or not isinstance(actor_id, str)
                    or not actor_id.isprintable()
                ):
                    raise ValueError("Plugin management operation is invalid")
                hint = repair_command(actor_id, operation_id)
                detail = f"actor={actor_id}"
                if hint is not None:
                    detail += f"; repair={hint}"
                pending.append(f"{operation_id} ({detail})")
        suffix = f" ({convergence}"
        if unknown:
            suffix += "; unknown: " + ", ".join(unknown)
        backup = item.get("backupRetention")
        if backup is not None:
            if (
                not isinstance(backup, dict)
                or set(backup)
                != {"installationKey", "status", "expiryReceiptId"}
                or backup["installationKey"] != key
            ):
                raise ValueError("Plugin management backup retention is invalid")
            backup_status = backup["status"]
            expiry_receipt_id = backup["expiryReceiptId"]
            if backup_status not in {
                "retained",
                "expiry_pending",
                "expired",
                "unknown",
            } or (
                (backup_status == "expired")
                != (isinstance(expiry_receipt_id, str) and bool(expiry_receipt_id))
            ):
                raise ValueError("Plugin management backup retention is invalid")
            suffix += f"; backup: {backup_status}"
        if pending:
            suffix += "; pending: " + ", ".join(pending)
        retirement = item.get("retirementStates", [])
        debt = item.get("cleanupDebtIds", [])
        if not (
            is_plugin_terminal_string_list(retirement) and is_plugin_terminal_string_list(debt)
        ):
            raise ValueError("Plugin management cleanup evidence is invalid")
        if retirement:
            suffix += "; retirement: " + ", ".join(retirement)
        if debt:
            suffix += "; cleanup debt: " + ", ".join(debt)
        entries.append(f"{plugin_id}: {desired}{suffix})")
    skew = document.get("skew")
    if not isinstance(skew, list):
        raise ValueError("Plugin management skew is invalid")
    skew_codes: list[str] = []
    for item in skew:
        code = item.get("code") if isinstance(item, dict) else None
        if not isinstance(code, str) or not code or not code.isprintable():
            raise ValueError("Plugin management skew is invalid")
        skew_codes.append(code)
    parts = [
        f"Plugin management (Desired State revision {revision})",
        " | ".join(entries) or "none",
    ]
    if skew_codes:
        parts.append("skew: " + ", ".join(skew_codes))
    return " | ".join(parts)


__all__ = [
    "PluginListingError",
    "format_plugin_records",
    "list_plugin_records",
    "render_plugin_management_list",
]
