"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.plugin_manager import local_discovery as _binding


def discover_local_plugins(
    client: _binding.CodingPluginManagementReadClientV1,
    *,
    query: str,
    kind: _binding.LocalKind,
    source: _binding.LocalSource,
    limit: int,
) -> dict[str, object]:
    """Read Product-declared sources and Catalog metadata without startup or repair."""

    if kind not in {"all", "plugin", "skill", "prompt", "theme"}:
        raise ValueError("Local discovery kind is invalid")
    if source not in {"all", "project_local", "user_global", "local", "builtin"}:
        raise ValueError("Local discovery source is invalid")
    if type(limit) is not int or not 1 <= limit <= _binding._MAX_ROWS:
        raise ValueError("Local discovery limit is invalid")
    if not isinstance(query, str) or len(query) > 128 or not query.isprintable():
        raise ValueError("Local discovery query is invalid")
    client.assert_workspace_current()
    workspace = client.workspace
    rows: list[dict[str, object]] = []
    diagnostics: set[str] = set()
    completeness: dict[str, str] = {"product": "unavailable", "catalog": "unavailable"}
    evidence: dict[str, object] = {}
    initial_management_revisions: object | None = None

    # A missing fence is an ordinary partial inventory: native files remain
    # discoverable, but no installed-Plugin claim can be made from it.
    layout = _binding.resolve_coding_plugin_lifecycle_state_layout(workspace)
    if layout != client.layout:
        return _binding._blocked("local_discovery_scope_changed")
    if _binding.coding_fenced_product_exists(layout):
        try:
            management = client.management_snapshot(
                correlation_id="cli:local-discovery"
            )
            if management.get("projectionVersion") != 1:
                return _binding._blocked("local_discovery_owner_version_invalid")
            initial_management_revisions = management.get("ownerRevisions")
            installations = management.get("installations")
            if not isinstance(installations, list):
                return _binding._blocked("local_discovery_owner_invalid")
            status: dict[str, object] | None = None
            try:
                status = client.support_status(
                    correlation_id="cli:local-discovery-status"
                )
            except (OSError, RuntimeError):
                diagnostics.add("local_discovery_product_preview_unavailable")
            if status is not None:
                if status.get("scopeId") != client.scope_id:
                    return _binding._blocked("local_discovery_scope_changed")
                status_rows = status.get("installations")
                if not isinstance(status_rows, list):
                    return _binding._blocked("local_discovery_owner_invalid")
                owner_evidence = status.get("ownerEvidence")
                if not isinstance(owner_evidence, dict) or owner_evidence.get(
                    "managementRevisions"
                ) != management.get("ownerRevisions"):
                    diagnostics.add("local_discovery_product_stale")
                    status_rows = []
            else:
                status_rows = []
            status_by_plugin = {
                item["pluginId"]: item
                for item in status_rows
                if isinstance(item, dict) and isinstance(item.get("pluginId"), str)
            }
            revisions_by_plugin: dict[str, _binding.PluginPackageRevisionRefV1] = {}
            for item in installations:
                if not isinstance(item, dict):
                    return _binding._blocked("local_discovery_owner_invalid")
                try:
                    key = _binding.PluginInstallationKeyV1.from_dict(
                        item.get("installationKey")
                    )
                except (TypeError, ValueError):
                    return _binding._blocked("local_discovery_scope_changed")
                if (
                    key.product_id != _binding._PRODUCT_ID
                    or key.installation_scope != "workspace"
                    or key.scope_id != client.scope_id
                ):
                    return _binding._blocked("local_discovery_scope_changed")
                source_record = item.get("source")
                if source_record is not None and not isinstance(source_record, dict):
                    return _binding._blocked("local_discovery_owner_invalid")
                if (
                    source_record is None
                    or source_record.get("availability") != "available"
                ):
                    diagnostics.add("local_discovery_source_unavailable")
                package_ref = item.get("selectedPackageRevision")
                try:
                    revision = (
                        _binding.PluginPackageRevisionRefV1.from_dict(package_ref)
                        if package_ref is not None
                        else None
                    )
                    package_fingerprint = (
                        _binding.plugin_package_revision_fingerprint(revision)
                        if revision is not None
                        else None
                    )
                except (TypeError, ValueError):
                    return _binding._blocked("local_discovery_owner_invalid")
                if revision is not None:
                    revisions_by_plugin[key.plugin_id] = revision
                status_row = status_by_plugin.get(key.plugin_id, {})
                rows.append(
                    {
                        "identityKind": "plugin_installation",
                        "pluginId": key.plugin_id,
                        "installationKey": key.to_dict(),
                        "name": key.plugin_id,
                        "resourceKind": "plugin",
                        "resourceKinds": status_row.get("resourceKinds", []),
                        "resourceKindEvidence": (
                            "current_preview"
                            if status_row.get("resourceKinds")
                            else "not_checked"
                        ),
                        "version": (
                            source_record.get("pluginVersion")
                            if source_record
                            else None
                        ),
                        "sourceClass": (
                            source_record.get("sourceKind")
                            if source_record
                            else "unknown"
                        ),
                        "sourceScope": "workspace",
                        "sourceIdentity": (
                            source_record.get("sourceIdentity")
                            if source_record
                            else None
                        ),
                        "sourceLocation": (
                            source_record.get("sourceLocation")
                            if source_record
                            else None
                        ),
                        "sourceAvailability": (
                            source_record.get("availability")
                            if source_record
                            else "unknown"
                        ),
                        "packageRevisionFingerprint": package_fingerprint,
                        "desiredState": item.get("desiredState"),
                        "productCompatibility": (
                            "observed_in_current_projection"
                            if status_row.get("productAdmission")
                            == "observed_in_preview"
                            else "not_checked"
                        ),
                        "productAdmission": status_row.get(
                            "productAdmission", "not_checked"
                        ),
                        "productSelection": status_row.get(
                            "productSelection", "unknown"
                        ),
                        "productUse": "not_checked",
                        "diagnosticCodes": status_row.get("reasonCodes", []),
                    }
                )
            try:
                inert_kinds, inert_diagnostics, inert_evidence = (
                    read_inert_installed_kinds(client, revisions_by_plugin)
                )
            except (OSError, RuntimeError, ValueError):
                inert_kinds = {}
                inert_evidence = {}
                inert_diagnostics = {
                    plugin_id: "local_discovery_artifact_metadata_unavailable"
                    for plugin_id in revisions_by_plugin
                }
            diagnostics.update(inert_diagnostics.values())
            for row in rows:
                plugin_id = row.get("pluginId")
                kinds = (
                    inert_kinds.get(plugin_id) if isinstance(plugin_id, str) else None
                )
                error_code = (
                    inert_diagnostics.get(plugin_id)
                    if isinstance(plugin_id, str)
                    else None
                )
                if error_code:
                    previous_codes = row.get("diagnosticCodes")
                    row["diagnosticCodes"] = sorted(
                        set(previous_codes if isinstance(previous_codes, list) else [])
                        | {error_code}
                    )
                if kinds and isinstance(plugin_id, str):
                    previous = row.get("resourceKinds")
                    row["resourceKinds"] = sorted(
                        set(previous if isinstance(previous, list) else []) | set(kinds)
                    )
                    row["resourceKindEvidence"] = inert_evidence[plugin_id]
            completeness["product"] = "complete" if not diagnostics else "partial"
            evidence["managementRevisions"] = management.get("ownerRevisions")
            evidence["supportStatus"] = (
                status.get("snapshotStatus") if status is not None else "unavailable"
            )
            if status is None or status.get("snapshotStatus") != "partial_evidence":
                completeness["product"] = "partial"
                diagnostics.add("local_discovery_product_stale")
        except (OSError, RuntimeError):
            completeness["product"] = "partial"
            diagnostics.add("local_discovery_product_unavailable")
        except (TypeError, ValueError):
            return _binding._blocked("local_discovery_owner_invalid")
    else:
        diagnostics.add("local_discovery_product_not_fenced")

    receipt: _binding.ResourceCatalogInputReceipt | None = None
    try:
        disabled_skills, settings_revision = _binding._capture_disabled_skills(
            workspace
        )
        loader = _binding.CodingResourceLoader(workspace_root=workspace)
        receipt = loader.prepare_catalog_input_receipt(workspace)
        adapter = _binding.build_coding_initial_resource_catalog_adapter(
            receipt,
            product_scope_id="plugin-local-discovery",
            disabled_skills=disabled_skills,
            source_policy=_binding.CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
        )
        catalog = adapter.prepare_bootstrap_projection_with_receipt(
            product_id=_binding._PRODUCT_ID,
            session_id="plugin-local-discovery",
            cwd=workspace,
        ).catalog
        selected = {
            entry.primary_candidate_fingerprint for entry in catalog.effective_entries
        }
        merge_reason = {
            fingerprint: decision.reason
            for decision in catalog.merge_decisions
            for fingerprint in decision.candidate_fingerprints
        }
        for candidate in catalog.candidate_summaries:
            if not isinstance(candidate.content_origin, _binding.NativeHostOrigin):
                continue
            rows.append(
                {
                    "identityKind": "native_resource",
                    "pluginId": None,
                    "name": candidate.canonical_name,
                    "resourceIdentity": candidate.identity.to_payload(),
                    "resourceKind": candidate.identity.resource_kind,
                    "resourceKinds": [candidate.identity.resource_kind],
                    "version": None,
                    "sourceClass": candidate.source_class,
                    "sourceScope": candidate.content_origin.workspace_or_user_scope,
                    "candidateFingerprint": candidate.candidate_fingerprint,
                    "contentDigest": candidate.expected_content_digest,
                    "sourceEnabled": candidate.invocation_policy.enabled,
                    "enabled": candidate.candidate_fingerprint in selected,
                    "nativeCatalogSelection": (
                        "selected"
                        if candidate.candidate_fingerprint in selected
                        else "not_selected"
                    ),
                    "productCompatibility": "native_catalog_candidate",
                    "productSelection": "not_checked",
                    "mergeReason": merge_reason.get(candidate.candidate_fingerprint),
                    "diagnosticCodes": sorted(
                        {item.code for item in candidate.diagnostics}
                    ),
                }
            )
        diagnostics.update(item.code for item in catalog.diagnostics)
        completeness["catalog"] = (
            "complete" if catalog.complete and not catalog.diagnostics else "partial"
        )
        evidence["catalogGeneration"] = catalog.catalog_generation
        evidence["catalogSnapshotFingerprint"] = catalog.snapshot_fingerprint
        evidence["disabledSkillSettingsRevision"] = settings_revision
        _after_disabled, after_settings_revision = _binding._capture_disabled_skills(
            workspace
        )
        if settings_revision != after_settings_revision:
            completeness["catalog"] = "partial"
            diagnostics.add("local_discovery_settings_stale")
    except _binding.CodingResourceCatalogAdmissionError:
        return _binding._blocked("local_discovery_catalog_authority_invalid")
    except (OSError, RuntimeError):
        completeness["catalog"] = "partial"
        diagnostics.add("local_discovery_catalog_unavailable")
        if receipt is not None:
            try:
                fallback, fallback_diagnostics = _binding._fallback_native_metadata(
                    receipt
                )
            except _binding._NativeFallbackAuthorityError:
                return _binding._blocked("local_discovery_catalog_authority_invalid")
            rows.extend(fallback)
            diagnostics.update(fallback_diagnostics)
    except (TypeError, ValueError):
        return _binding._blocked("local_discovery_catalog_authority_invalid")
    if initial_management_revisions is not None:
        try:
            final_management = client.management_snapshot(
                correlation_id="cli:local-discovery:after"
            )
            final_revisions = final_management.get("ownerRevisions")
        except (OSError, RuntimeError):
            final_revisions = None
        except (TypeError, ValueError):
            return _binding._blocked("local_discovery_owner_invalid")
        if final_revisions != initial_management_revisions:
            completeness["product"] = "partial"
            diagnostics.add("local_discovery_product_stale")
            for row in rows:
                if row["identityKind"] != "plugin_installation":
                    continue
                row["productAdmission"] = "not_checked"
                row["productSelection"] = "stale_evidence"
                row["productCompatibility"] = "not_checked"
    client.assert_workspace_current()

    needle = query.casefold()
    filtered = [
        row
        for row in rows
        if _binding._matches_kind(row, kind)
        and (source == "all" or row["sourceClass"] == source)
        and (
            not needle
            or needle in str(row["name"]).casefold()
            or needle in str(row.get("pluginId") or "").casefold()
        )
    ]
    filtered.sort(
        key=lambda row: (
            str(row["identityKind"]),
            str(row["resourceKind"]),
            str(row["name"]),
            str(row.get("sourceClass")),
            str(row.get("candidateFingerprint", "")),
        )
    )
    source_truncated = bool(
        {
            "local_discovery_source_truncated",
            "resource_source_discovery_budget_exceeded",
        }
        & diagnostics
    )
    truncated = len(filtered) > limit or source_truncated
    if truncated:
        diagnostics.add("local_discovery_result_truncated")
    disposition = (
        "complete"
        if all(value == "complete" for value in completeness.values()) and not truncated
        else "partial"
    )
    return {
        "discoveryVersion": 1,
        "productId": _binding._PRODUCT_ID,
        "scopeId": client.scope_id,
        "disposition": disposition,
        "sourceCompleteness": completeness,
        "truncated": truncated,
        "sourceTruncation": (
            "observed"
            if source_truncated
            else "none"
            if completeness["catalog"] == "complete"
            else "unknown"
        ),
        "totalMatchingRows": len(filtered),
        "totalMatchingRowsKnown": (
            not source_truncated
            and completeness["catalog"] == "complete"
            and completeness["product"] == "complete"
        ),
        "rows": filtered[:limit],
        "diagnosticCodes": sorted(diagnostics),
        "ownerEvidence": evidence,
    }


def read_inert_installed_kinds(
    client: _binding.CodingPluginManagementReadClientV1,
    revisions: dict[str, _binding.PluginPackageRevisionRefV1],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str], dict[str, str]]:
    """Classify exact Product-bound data bytes regardless of Desired enablement."""

    if not revisions:
        return {}, {}, {}
    kinds: dict[str, tuple[str, ...]] = {}
    diagnostics: dict[str, str] = {}
    evidence: dict[str, str] = {}
    with _binding.CodingFencedProductReadOnlyPreviewOwner.open(
        client.layout, workspace_guard=client.assert_workspace_current
    ) as owner:
        for plugin_id, revision in revisions.items():
            matches = tuple(
                binding
                for binding in owner.policy.bindings
                if binding.plugin_id == plugin_id
                and binding.source_identity == revision.package_source_identity
                and binding.artifact_digest == revision.package_content_digest
            )
            if len(matches) != 1:
                diagnostics[plugin_id] = "local_discovery_binding_unavailable"
                continue
            binding = matches[0]
            legacy_kind = _binding._LEGACY_RESOURCE_KINDS.get(
                binding.source_trust_class or ""
            )
            if legacy_kind is not None:
                kinds[plugin_id] = (legacy_kind,)
                evidence[plugin_id] = "product_binding"
                continue
            if binding.source_trust_class != "local-data-only":
                continue
            report = _binding.validate_coding_data_wheel(binding.source_identity)
            if (
                report.get("valid") is not True
                or report.get("pluginId") != plugin_id
                or report.get("version") != revision.plugin_version
                or report.get("sha256") != revision.package_content_digest
                or report.get("resourceKind") not in {"skill", "prompt"}
            ):
                diagnostics[plugin_id] = "local_discovery_artifact_metadata_unavailable"
                continue
            resource_kind = report["resourceKind"]
            assert isinstance(resource_kind, str)
            kinds[plugin_id] = (resource_kind,)
            evidence[plugin_id] = "inert_artifact"
        owner.epoch_runtime.assert_current()
    return kinds, diagnostics, evidence
