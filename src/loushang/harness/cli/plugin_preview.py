"""CLI serialization of the transport-neutral current Plugin preview port."""

from __future__ import annotations

import json

from loushang.harness.cli.plugin_management import is_plugin_terminal_string_list
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentPreviewQueryPort,
    PluginCurrentPreviewRequestV1,
    project_plugin_current_preview,
)


def format_plugin_current_preview(
    query: PluginCurrentPreviewQueryPort,
    request: PluginCurrentPreviewRequestV1,
) -> str:
    return json.dumps(
        project_plugin_current_preview(query, request),
        ensure_ascii=False,
        sort_keys=True,
    ) + "\n"


def render_plugin_preview(preview: dict[str, object]) -> str:
    """Render the Product's sanitized partial read without claiming live use."""

    if preview.get("snapshotStatus") != "partial_evidence":
        raise ValueError("Plugin preview status is unsupported")

    def strings(key: str) -> list[str]:
        value = preview.get(key)
        if not is_plugin_terminal_string_list(value):
            raise ValueError("Plugin preview field is invalid")
        return value

    plugins = strings("compiledPluginIds")
    diagnostics = strings("catalogDiagnosticCodes")
    gaps = strings("evidenceGaps")
    raw_resources = preview.get("catalogResources")
    if not isinstance(raw_resources, list):
        raise ValueError("Plugin preview Catalog resources are invalid")
    resources: list[str] = []
    for item in raw_resources:
        if not isinstance(item, dict):
            raise ValueError("Plugin preview Catalog resource is invalid")
        kind, name = item.get("resourceKind"), item.get("name")
        if not all(
            isinstance(value, str) and value.isprintable() and value
            for value in (kind, name)
        ):
            raise ValueError("Plugin preview Catalog resource is invalid")
        resources.append(f"{kind}:{name}")
    disposition = preview.get("disposition")
    if disposition not in {"projected", "blocked"}:
        raise ValueError("Plugin preview disposition is invalid")
    parts = ["Plugin preview (partial)", "compiled: " + (", ".join(plugins) or "none")]
    if resources:
        parts.append("Catalog: " + ", ".join(resources))
    if disposition == "blocked":
        owner, code = preview.get("blockingOwner"), preview.get("blockingCode")
        if not all(isinstance(value, str) and value.isprintable() for value in (owner, code)):
            raise ValueError("Plugin preview blocker is invalid")
        parts.append(f"blocked: {owner}/{code}")
    if diagnostics:
        parts.append("diagnostics: " + ", ".join(diagnostics))
    if gaps:
        parts.append("evidence gaps: " + ", ".join(gaps))
    return " | ".join(parts)


def render_plugin_support_status(document: dict[str, object]) -> str:
    """Show owner-observed stages without claiming a live Session used them."""

    if document.get("supportStatusVersion") not in {1, 2} or document.get("snapshotStatus") not in {
        "partial_evidence", "stale_evidence"
    }:
        raise ValueError("Plugin support status is invalid")
    entries = document.get("installations")
    gaps = document.get("evidenceGaps")
    if not isinstance(entries, list) or not isinstance(gaps, list):
        raise ValueError("Plugin support status is invalid")
    lines = [f"Plugin support ({document['snapshotStatus']}; live use not checked)"]
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Plugin support Installation is invalid")
        plugin_id = item.get("pluginId")
        desired = item.get("desiredState")
        admission = item.get("productAdmission")
        selection = item.get("productSelection")
        use = item.get("productUse")
        reasons = item.get("reasonCodes")
        pending = item.get("pendingOperations", [])
        revision = item.get("packageRevisionFingerprint")
        instance = item.get("instanceRevisionRef")
        debt = item.get("cleanupDebtIds", [])
        retirement = item.get("retirementStates", [])
        if any(
            not isinstance(value, str) or not value.isprintable()
            for value in (plugin_id, desired, admission, selection, use)
        ) or not (
            is_plugin_terminal_string_list(reasons)
            and is_plugin_terminal_string_list(debt)
            and is_plugin_terminal_string_list(retirement)
        ) or not isinstance(pending, list) or (revision is not None and (
            not isinstance(revision, str)
            or len(revision) != 64
            or any(character not in "0123456789abcdef" for character in revision)
        )):
            raise ValueError("Plugin support Installation is invalid")
        line = (
            f"{plugin_id}: {desired}; admission={admission}; "
            f"selection={selection}; use={use}"
        )
        if reasons:
            line += "; reasons=" + ", ".join(reasons)
        if revision is not None:
            line += f"; package-revision={revision[:12]}"
        if instance is not None:
            if (
                not isinstance(instance, dict)
                or not isinstance(instance.get("instanceId"), str)
                or not instance["instanceId"].isprintable()
                or type(instance.get("revision")) is not int
            ):
                raise ValueError("Plugin support Instance revision is invalid")
            line += f"; instance={instance['instanceId']}@{instance['revision']}"
        if retirement:
            line += "; retirement=" + ", ".join(retirement)
        if debt:
            line += "; cleanup-debt=" + ", ".join(debt)
        lines.append(line)
        for operation in pending:
            if not isinstance(operation, dict):
                raise ValueError("Plugin support pending operation is invalid")
            kind = operation.get("operationKind")
            actor = operation.get("actorId")
            operation_id = operation.get("operationId")
            repair = operation.get("repairCommand")
            if (
                kind != "a1_desired"
                or any(
                    not isinstance(value, str) or not value or not value.isprintable()
                    for value in (actor, operation_id)
                )
                or (repair is not None and (not isinstance(repair, str) or not repair.isprintable()))
            ):
                raise ValueError("Plugin support pending operation is invalid")
            pending_line = f"  pending {kind} {operation_id} (actor={actor})"
            if repair is not None:
                pending_line += f"; repair: {repair}"
            lines.append(pending_line)
    if len(lines) == 1:
        lines.append("No installations")
    if gaps:
        if not is_plugin_terminal_string_list(gaps):
            raise ValueError("Plugin support evidence gap is invalid")
        lines.append("Evidence gaps: " + ", ".join(gaps))
    return "\n".join(lines)


__all__ = ["format_plugin_current_preview", "render_plugin_preview", "render_plugin_support_status"]
