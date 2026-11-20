"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.plugin_manager import support_status as _binding


def project_support_evidence(
    management: dict[str, object], preview: dict[str, object], *, correlation_id: str
) -> dict[str, object]:
    """Join existing owner reads without claiming a live Session consumer."""

    if management.get("projectionVersion") != 1 or preview.get("previewVersion") != 1:
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_002"])
    if (
        preview.get("productId") != _binding._RUNTIME_PROGRAM_VALUES["value_001"]
        or preview.get("snapshotStatus") != "partial_evidence"
    ):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_003"])
    revisions = management.get("ownerRevisions")
    desired_revision = (
        revisions.get("desiredState") if isinstance(revisions, dict) else None
    )
    preview_revision = preview.get("desiredInventoryRevision")
    if type(desired_revision) is not int or type(preview_revision) is not int:
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_004"])
    installations = management.get("installations")
    compiled = preview.get("compiledPluginIds")
    admissions = preview.get("admittedResources")
    gaps = preview.get("evidenceGaps")
    resources = preview.get("catalogResources")
    selected = preview.get("selectedResources", [])
    catalog_generation = preview.get("catalogGeneration")
    catalog_fingerprint = preview.get("catalogSnapshotFingerprint")
    if (
        not isinstance(installations, list)
        or not isinstance(compiled, list)
        or any(not isinstance(item, str) for item in compiled)
        or not isinstance(admissions, list)
        or not isinstance(gaps, list)
        or any(not isinstance(item, str) for item in gaps)
        or not isinstance(resources, list)
        or not isinstance(selected, list)
    ):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_005"])
    scope_id = preview.get("scopeId")
    if not isinstance(scope_id, str) or not scope_id:
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_006"])
    observed_at = preview.get("observedAtUnixNs")
    owner_complete = (
        isinstance(preview.get("productPolicyRevision"), str)
        and bool(preview["productPolicyRevision"])
        and isinstance(preview.get("productAuthorityRevision"), str)
        and bool(preview["productAuthorityRevision"])
        and isinstance(preview.get("disabledSkillSettingsRevision"), str)
        and bool(preview["disabledSkillSettingsRevision"])
        and type(observed_at) is int
        and observed_at >= 0
    )

    def valid_digest(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    if selected and (
        type(catalog_generation) is not int
        or catalog_generation < 1
        or not valid_digest(catalog_fingerprint)
    ):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_007"])
    selections_by_key: dict[
        _binding.PluginInstallationKeyV1, list[dict[str, object]]
    ] = {}
    for selection_receipt in selected:
        if not isinstance(selection_receipt, dict):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_009"])
        try:
            selected_key = _binding.PluginInstallationKeyV1.from_dict(
                selection_receipt.get("installationKey")
            )
            selected_instance = _binding.PluginInstanceRevisionRef.from_dict(
                selection_receipt.get("instanceRevisionRef")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_009"]) from exc
        if (
            selected_key.product_id != _binding._RUNTIME_PROGRAM_VALUES["value_001"]
            or selected_key.installation_scope != "workspace"
            or selected_key.scope_id != scope_id
            or selected_key.plugin_id != selected_instance.plugin_id
            or type(selection_receipt.get("catalogGeneration")) is not int
            or selection_receipt.get("catalogGeneration") != catalog_generation
            or selection_receipt.get("catalogSnapshotFingerprint")
            != catalog_fingerprint
            or not isinstance(selection_receipt.get("contributionId"), str)
            or not selection_receipt["contributionId"]
            or not valid_digest(selection_receipt.get("admissionFingerprint"))
            or not valid_digest(selection_receipt.get("candidateFingerprint"))
            or not valid_digest(selection_receipt.get("packageRevisionFingerprint"))
            or selection_receipt.get("resourceKind") not in {"skill", "prompt", "theme"}
        ):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_010"])
        selections_by_key.setdefault(selected_key, []).append(selection_receipt)
    admission_kinds: dict[str, set[str]] = {}
    for item in admissions:
        if not isinstance(item, dict):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_011"])
        plugin_id, kind = item.get("pluginId"), item.get("resourceKind")
        if not isinstance(plugin_id, str) or not isinstance(kind, str):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_011"])
        admission_kinds.setdefault(plugin_id, set()).add(kind)
    coherent = desired_revision == preview_revision and "stale_snapshot" not in gaps
    blocked = preview.get("disposition") == "blocked"
    blocker = preview.get("blockingCode")
    if preview.get("disposition") not in {"projected", "blocked"} or (
        blocked and not isinstance(blocker, str)
    ):
        raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_008"])
    entries: list[dict[str, object]] = []
    for item in installations:
        if not isinstance(item, dict):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_012"])
        key = item.get("installationKey")
        try:
            installation_key = _binding.PluginInstallationKeyV1.from_dict(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_012"]) from exc
        plugin_id = installation_key.plugin_id
        desired = item.get("desiredState")
        unknown = item.get("unknownDimensions")
        cleanup_debt = item.get("cleanupDebtIds", [])
        retirement_states = item.get("retirementStates", [])
        if (
            installation_key.product_id != _binding._RUNTIME_PROGRAM_VALUES["value_001"]
            or installation_key.installation_scope != "workspace"
            or installation_key.scope_id != scope_id
            or not isinstance(plugin_id, str)
            or not plugin_id
            or desired
            not in {"installed_enabled", "installed_disabled", "absent", "unknown"}
            or not isinstance(unknown, list)
            or any(not isinstance(code, str) for code in unknown)
            or not isinstance(cleanup_debt, list)
            or any(
                not isinstance(code, str) or not code.isprintable()
                for code in cleanup_debt
            )
            or not isinstance(retirement_states, list)
            or any(
                not isinstance(code, str) or not code.isprintable()
                for code in retirement_states
            )
        ):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_013"])
        owner_package = item.get("selectedPackageRevision")
        owner_instance = item.get("selectedInstanceRevisionRef")
        if owner_instance is not None:
            try:
                owner_instance = _binding.PluginInstanceRevisionRef.from_dict(
                    owner_instance
                ).to_dict()
            except (TypeError, ValueError) as exc:
                raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_016"]) from exc
        if owner_package is not None:
            try:
                revision_fingerprint = _binding.plugin_package_revision_fingerprint(
                    _binding.PluginPackageRevisionRefV1.from_dict(owner_package)
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_017"]) from exc
        else:
            revision_fingerprint = None
        exact_selection: list[dict[str, object]] = []
        identity_mismatch = False
        for receipt in selections_by_key.get(installation_key, []):
            if (
                receipt["packageRevisionFingerprint"] == revision_fingerprint
                and receipt["instanceRevisionRef"] == owner_instance
            ):
                exact_selection.append(receipt)
            else:
                identity_mismatch = True
        if identity_mismatch:
            exact_selection.clear()
        admission = (
            "observed_in_preview"
            if coherent and owner_complete and not blocked and exact_selection
            else "not_checked"
        )
        selection = (
            "stale_evidence"
            if not coherent
            else "unknown"
            if not owner_complete
            else "not_selected"
            if desired in {"installed_disabled", "absent"}
            else "blocked"
            if blocked
            else "selected"
            if exact_selection
            else "unknown"
            if identity_mismatch
            else "projected"
            if plugin_id in compiled
            else "unknown"
        )
        reason_codes = set(unknown)
        if identity_mismatch:
            reason_codes.add("selection_identity_mismatch")
        if blocked:
            assert isinstance(blocker, str)
            reason_codes.add(blocker)
        operations = item.get("operations", [])
        if not isinstance(operations, list):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_014"])
        pending: list[dict[str, object]] = []
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_015"])
            if operation.get("status") not in {"accepted", "running"}:
                continue
            operation_id = operation.get("operationId")
            actor_id = operation.get("actorId")
            if (
                not isinstance(operation_id, str)
                or not operation_id
                or not operation_id.isprintable()
                or not isinstance(actor_id, str)
                or not actor_id
                or not actor_id.isprintable()
            ):
                raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_015"])
            pending.append(
                {
                    "operationKind": "a1_desired",
                    "actorId": actor_id,
                    "operationId": operation_id,
                    "repairCommand": _binding.coding_desired_repair_command(
                        actor_id, operation_id
                    ),
                }
            )
        entries.append(
            {
                "pluginId": plugin_id,
                "installationKey": key,
                "packageRevisionFingerprint": revision_fingerprint,
                "instanceRevisionRef": owner_instance,
                "desiredState": desired,
                "cleanupDebtIds": cleanup_debt,
                "retirementStates": retirement_states,
                "resourceKinds": sorted(admission_kinds.get(plugin_id, ())),
                "artifactBuild": "not_checked",
                "productAdmission": admission,
                "productSelection": selection,
                "productUse": "not_checked",
                "selectedContributions": sorted(
                    (receipt["contributionId"] for receipt in exact_selection),
                    key=str,
                ),
                "pendingOperations": sorted(
                    pending, key=lambda operation: str(operation["operationId"])
                ),
                "reasonCodes": sorted(reason_codes),
            }
        )
    return {
        "supportStatusVersion": 2,
        "correlationId": correlation_id,
        "productId": _binding._RUNTIME_PROGRAM_VALUES["value_001"],
        "scopeId": scope_id,
        "snapshotStatus": "partial_evidence" if coherent else "stale_evidence",
        "desiredInventoryRevision": desired_revision,
        "ownerEvidence": {
            "managementRevisions": revisions,
            "previewObservedAtUnixNs": preview.get("observedAtUnixNs"),
            "productPolicyRevision": preview.get("productPolicyRevision"),
            "productAuthorityRevision": preview.get("productAuthorityRevision"),
            "disabledSkillSettingsRevision": preview.get(
                "disabledSkillSettingsRevision"
            ),
            "catalogGeneration": catalog_generation,
            "catalogSnapshotFingerprint": catalog_fingerprint,
        },
        "previewDisposition": preview["disposition"],
        "catalogResources": resources,
        "evidenceGaps": sorted(
            set(gaps)
            | ({"stale_snapshot"} if not coherent else set())
            | ({"owner_revision_missing"} if not owner_complete else set())
        ),
        "installations": sorted(entries, key=lambda entry: str(entry["pluginId"])),
    }
