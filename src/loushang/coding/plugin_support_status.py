"""One read-only Coding presentation of Plugin owner evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path


def project_coding_plugin_support_status(
    management: dict[str, object],
    preview: dict[str, object],
    *,
    correlation_id: str,
) -> dict[str, object]:
    """Join existing owner reads without claiming a live Session consumer."""

    if management.get("projectionVersion") != 1 or preview.get("previewVersion") != 1:
        raise ValueError("Plugin support owner projection version is unsupported")
    if (
        preview.get("productId") != "coding"
        or preview.get("snapshotStatus") != "partial_evidence"
    ):
        raise ValueError("Plugin support requires Coding's partial Product preview")
    revisions = management.get("ownerRevisions")
    desired_revision = (
        revisions.get("desiredState") if isinstance(revisions, dict) else None
    )
    preview_revision = preview.get("desiredInventoryRevision")
    if type(desired_revision) is not int or type(preview_revision) is not int:
        raise ValueError("Plugin support Desired State revision is invalid")
    installations = management.get("installations")
    compiled = preview.get("compiledPluginIds")
    admissions = preview.get("admittedResources")
    gaps = preview.get("evidenceGaps")
    resources = preview.get("catalogResources")
    if (
        not isinstance(installations, list)
        or not isinstance(compiled, list)
        or any(not isinstance(item, str) for item in compiled)
        or not isinstance(admissions, list)
        or not isinstance(gaps, list)
        or any(not isinstance(item, str) for item in gaps)
        or not isinstance(resources, list)
    ):
        raise ValueError("Plugin support owner fields are invalid")
    scope_id = preview.get("scopeId")
    if not isinstance(scope_id, str) or not scope_id:
        raise ValueError("Plugin support scope is invalid")
    admission_kinds: dict[str, set[str]] = {}
    for item in admissions:
        if not isinstance(item, dict):
            raise ValueError("Plugin support admission is invalid")
        plugin_id, kind = item.get("pluginId"), item.get("resourceKind")
        if not isinstance(plugin_id, str) or not isinstance(kind, str):
            raise ValueError("Plugin support admission is invalid")
        admission_kinds.setdefault(plugin_id, set()).add(kind)
    coherent = desired_revision == preview_revision
    blocked = preview.get("disposition") == "blocked"
    blocker = preview.get("blockingCode")
    if preview.get("disposition") not in {"projected", "blocked"} or (
        blocked and not isinstance(blocker, str)
    ):
        raise ValueError("Plugin support Product disposition is invalid")
    entries: list[dict[str, object]] = []
    for item in installations:
        if not isinstance(item, dict):
            raise ValueError("Plugin support Installation is invalid")
        key = item.get("installationKey")
        plugin_id = key.get("pluginId") if isinstance(key, dict) else None
        desired = item.get("desiredState")
        unknown = item.get("unknownDimensions")
        if (
            not isinstance(key, dict)
            or key.get("productId") != "coding"
            or key.get("scopeId") != scope_id
            or not isinstance(plugin_id, str)
            or not plugin_id
            or desired
            not in {"installed_enabled", "installed_disabled", "absent", "unknown"}
            or not isinstance(unknown, list)
            or any(not isinstance(code, str) for code in unknown)
        ):
            raise ValueError("Plugin support Installation changed Product scope")
        admission = (
            "observed_in_preview"
            if coherent and not blocked and plugin_id in admission_kinds
            else "not_checked"
        )
        selection = (
            "stale_evidence"
            if not coherent
            else "not_selected"
            if desired in {"installed_disabled", "absent"}
            else "blocked"
            if blocked
            else "projected"
            if plugin_id in compiled
            else "unknown"
        )
        reason_codes = set(unknown)
        if blocked:
            assert isinstance(blocker, str)
            reason_codes.add(blocker)
        entries.append(
            {
                "pluginId": plugin_id,
                "desiredState": desired,
                "resourceKinds": sorted(admission_kinds.get(plugin_id, ())),
                "artifactBuild": "not_checked",
                "productAdmission": admission,
                "productSelection": selection,
                "productUse": "not_checked",
                "reasonCodes": sorted(reason_codes),
            }
        )
    return {
        "supportStatusVersion": 1,
        "correlationId": correlation_id,
        "productId": "coding",
        "scopeId": scope_id,
        "snapshotStatus": "partial_evidence" if coherent else "stale_evidence",
        "desiredInventoryRevision": desired_revision,
        "previewDisposition": preview["disposition"],
        "catalogResources": resources,
        "evidenceGaps": sorted(
            set(gaps) | ({"stale_snapshot"} if not coherent else set())
        ),
        "installations": sorted(entries, key=lambda entry: str(entry["pluginId"])),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="loushang-coding-plugin-status",
        description="Read partial Plugin support stages from the fenced Coding Product.",
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--composition-set", default="coding-standard")
    args = parser.parse_args(argv)
    from loushang.coding.plugin_management_read_sdk import (
        open_coding_plugin_management_read_client,
    )

    try:
        document = open_coding_plugin_management_read_client(
            Path(args.workspace)
        ).support_status(
            correlation_id="coding:cli:plugin-status",
            composition_set_id=args.composition_set,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Error: {getattr(exc, 'code', 'plugin_support_unavailable')}\n")
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = ["main", "project_coding_plugin_support_status"]
