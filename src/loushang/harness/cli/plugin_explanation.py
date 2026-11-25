"""Transport-only JSON formatting for partial Plugin operation evidence."""

from __future__ import annotations

import json

from loushang.harness.cli.plugin_management import is_plugin_terminal_error_code


def format_plugin_operation_explanation(
    document: dict[str, object],
) -> str:
    return json.dumps(
        document, ensure_ascii=False, sort_keys=True
    ) + "\n"


def render_plugin_operation_explanation(
    document: dict[str, object], *, operation_id: str
) -> str:
    """Render only path-free owner codes from the partial A2/A1 read model."""

    if (
        document.get("operationId") != operation_id
        or document.get("explanationVersion") != 1
        or document.get("snapshotStatus") != "partial_evidence"
    ):
        raise ValueError("Plugin operation explanation changed request identity")
    package = document.get("package")
    if not isinstance(package, dict) or package.get("operationId") != operation_id:
        raise ValueError("Plugin Package explanation changed request identity")
    package_status = package.get("status")
    management_status = document.get("managementStatus")
    handoff = document.get("handoffEvidence")
    join = document.get("joinStatus")
    if (
        package_status not in {"observed", "unknown"}
        or management_status not in {"observed", "unknown"}
        or handoff not in {
            "not_queried", "absent", "incomplete", "settled", "identity_conflict"
        }
        or join not in {
            "same_identity", "package_only", "management_only", "unknown",
            "identity_conflict"
        }
    ):
        raise ValueError("Plugin operation owner status is invalid")
    gaps = document.get("evidenceGaps")
    if not isinstance(gaps, list) or any(
        not is_plugin_terminal_error_code(item) for item in gaps
    ):
        raise ValueError("Plugin operation evidence gaps are invalid")
    phase = package.get("phase")
    disposition = package.get("disposition")
    failure = package.get("failureCode")
    owner_action = package.get("operatorAction")
    management_disposition = document.get("managementDisposition")
    management_actor = document.get("managementActorId")
    repair_command = document.get("repairCommand")
    for value in (phase, disposition, failure, owner_action, management_disposition):
        if value is not None and not is_plugin_terminal_error_code(value):
            raise ValueError("Plugin operation owner code is invalid")
    if management_actor is not None and (
        not isinstance(management_actor, str)
        or not management_actor
        or not management_actor.isprintable()
    ):
        raise ValueError("Plugin operation actor is invalid")
    if repair_command is not None and (
        not isinstance(repair_command, str)
        or not repair_command
        or not repair_command.isprintable()
    ):
        raise ValueError("Plugin operation repair command is invalid")
    if package_status == "observed" and (phase is None or disposition is None):
        raise ValueError("Observed Package operation lacks status")
    package_text = (
        "unknown" if package_status == "unknown" else f"{phase} / {disposition}"
    )
    management_text = (
        "unknown"
        if management_status == "unknown"
        else f"observed / {management_disposition or 'pending'}"
    )
    parts = [
        f"Plugin operation {operation_id} (partial evidence)",
        f"Package: {package_text}",
        f"Management: {management_text}",
        f"Handoff: {handoff}; join: {join}",
    ]
    if management_actor is not None:
        parts.append(f"Management actor: {management_actor}")
    if repair_command is not None:
        parts.append(f"Repair: {repair_command}")
    if failure is not None:
        suffix = f"; owner action: {owner_action}" if owner_action is not None else ""
        parts.append(f"Package failure: {failure}{suffix}")
    parts.append("Evidence gaps: " + (", ".join(gaps) if gaps else "none"))
    return "\n".join(parts)


__all__ = ["format_plugin_operation_explanation", "render_plugin_operation_explanation"]
