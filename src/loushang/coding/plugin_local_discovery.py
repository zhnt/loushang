"""Bounded, read-only local Plugin and native Resource discovery for Coding."""

from __future__ import annotations

import errno
import json
import os
import re
import stat
from typing import Literal

from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources._catalog_records import NativeHostOrigin
from loushang.plugin._coding_data_wheel_validation import validate_coding_data_wheel

from ._plugin_lifecycle import resolve_coding_plugin_lifecycle_state_layout
from ._resource_catalog_shadow import (
    CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
    CodingResourceCatalogAdmissionError,
    build_coding_initial_resource_catalog_adapter,
)
from .package_product_management_cli import coding_fenced_product_exists
from .package_product_preview import CodingFencedProductReadOnlyPreviewOwner
from .plugin_management_preview import _capture_disabled_skills
from .plugin_management_read_sdk import CodingPluginManagementReadClientV1
from .resource_runtime import CodingResourceLoader

LocalKind = Literal["all", "plugin", "skill", "prompt", "theme"]
LocalSource = Literal["all", "project_local", "user_global", "local", "builtin"]
_MAX_ROWS = 500
_FALLBACK_NAME = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")


class _NativeFallbackAuthorityError(RuntimeError):
    """A declared root changed identity or crossed its path boundary."""


def discover_coding_local_plugins(
    client: CodingPluginManagementReadClientV1,
    *,
    query: str = "",
    kind: LocalKind = "all",
    source: LocalSource = "all",
    limit: int = 200,
) -> dict[str, object]:
    """Read Product-declared sources and Catalog metadata without startup or repair."""

    if kind not in {"all", "plugin", "skill", "prompt", "theme"}:
        raise ValueError("Local discovery kind is invalid")
    if source not in {"all", "project_local", "user_global", "local", "builtin"}:
        raise ValueError("Local discovery source is invalid")
    if type(limit) is not int or not 1 <= limit <= _MAX_ROWS:
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
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    if layout != client.layout:
        return _blocked("local_discovery_scope_changed")
    if coding_fenced_product_exists(layout):
        try:
            management = client.management_snapshot(correlation_id="cli:local-discovery")
            if management.get("projectionVersion") != 1:
                return _blocked("local_discovery_owner_version_invalid")
            initial_management_revisions = management.get("ownerRevisions")
            installations = management.get("installations")
            if not isinstance(installations, list):
                return _blocked("local_discovery_owner_invalid")
            status: dict[str, object] | None = None
            try:
                status = client.support_status(correlation_id="cli:local-discovery-status")
            except (OSError, RuntimeError):
                diagnostics.add("local_discovery_product_preview_unavailable")
            if status is not None:
                if status.get("scopeId") != client.scope_id:
                    return _blocked("local_discovery_scope_changed")
                status_rows = status.get("installations")
                if not isinstance(status_rows, list):
                    return _blocked("local_discovery_owner_invalid")
                owner_evidence = status.get("ownerEvidence")
                if (
                    not isinstance(owner_evidence, dict)
                    or owner_evidence.get("managementRevisions")
                    != management.get("ownerRevisions")
                ):
                    diagnostics.add("local_discovery_product_stale")
                    status_rows = []
            else:
                status_rows = []
            status_by_plugin = {
                item["pluginId"]: item
                for item in status_rows
                if isinstance(item, dict) and isinstance(item.get("pluginId"), str)
            }
            revisions_by_plugin: dict[str, PluginPackageRevisionRefV1] = {}
            for item in installations:
                if not isinstance(item, dict):
                    return _blocked("local_discovery_owner_invalid")
                try:
                    key = PluginInstallationKeyV1.from_dict(item.get("installationKey"))
                except (TypeError, ValueError):
                    return _blocked("local_discovery_scope_changed")
                if (
                    key.product_id != "coding"
                    or key.installation_scope != "workspace"
                    or key.scope_id != client.scope_id
                ):
                    return _blocked("local_discovery_scope_changed")
                source_record = item.get("source")
                if source_record is not None and not isinstance(source_record, dict):
                    return _blocked("local_discovery_owner_invalid")
                if source_record is None or source_record.get("availability") != "available":
                    diagnostics.add("local_discovery_source_unavailable")
                package_ref = item.get("selectedPackageRevision")
                try:
                    revision = (
                        PluginPackageRevisionRefV1.from_dict(package_ref)
                        if package_ref is not None else None
                    )
                    package_fingerprint = (
                        plugin_package_revision_fingerprint(revision)
                        if revision is not None else None
                    )
                except (TypeError, ValueError):
                    return _blocked("local_discovery_owner_invalid")
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
                            "current_preview" if status_row.get("resourceKinds") else "not_checked"
                        ),
                        "version": (
                            source_record.get("pluginVersion") if source_record else None
                        ),
                        "sourceClass": (
                            source_record.get("sourceKind") if source_record else "unknown"
                        ),
                        "sourceScope": "workspace",
                        "sourceIdentity": (
                            source_record.get("sourceIdentity") if source_record else None
                        ),
                        "sourceLocation": (
                            source_record.get("sourceLocation") if source_record else None
                        ),
                        "sourceAvailability": (
                            source_record.get("availability") if source_record else "unknown"
                        ),
                        "packageRevisionFingerprint": package_fingerprint,
                        "desiredState": item.get("desiredState"),
                        "productCompatibility": (
                            "observed_in_current_projection"
                            if status_row.get("productAdmission") == "observed_in_preview"
                            else "not_checked"
                        ),
                        "productAdmission": status_row.get("productAdmission", "not_checked"),
                        "productSelection": status_row.get("productSelection", "unknown"),
                        "productUse": "not_checked",
                        "diagnosticCodes": status_row.get("reasonCodes", []),
                    }
                )
            try:
                inert_kinds, inert_diagnostics, inert_evidence = _read_inert_installed_kinds(
                    client, revisions_by_plugin
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
                kinds = inert_kinds.get(plugin_id) if isinstance(plugin_id, str) else None
                error_code = (
                    inert_diagnostics.get(plugin_id)
                    if isinstance(plugin_id, str) else None
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
            return _blocked("local_discovery_owner_invalid")
    else:
        diagnostics.add("local_discovery_product_not_fenced")

    receipt: ResourceCatalogInputReceipt | None = None
    try:
        disabled_skills, settings_revision = _capture_disabled_skills(workspace)
        loader = CodingResourceLoader(workspace_root=workspace)
        receipt = loader.prepare_catalog_input_receipt(workspace)
        adapter = build_coding_initial_resource_catalog_adapter(
            receipt,
            product_scope_id="plugin-local-discovery",
            disabled_skills=disabled_skills,
            source_policy=CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
        )
        catalog = adapter.prepare_bootstrap_projection_with_receipt(
            product_id="coding", session_id="plugin-local-discovery", cwd=workspace
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
            if not isinstance(candidate.content_origin, NativeHostOrigin):
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
                        "selected" if candidate.candidate_fingerprint in selected else "not_selected"
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
        _after_disabled, after_settings_revision = _capture_disabled_skills(workspace)
        if settings_revision != after_settings_revision:
            completeness["catalog"] = "partial"
            diagnostics.add("local_discovery_settings_stale")
    except CodingResourceCatalogAdmissionError:
        return _blocked("local_discovery_catalog_authority_invalid")
    except (OSError, RuntimeError):
        completeness["catalog"] = "partial"
        diagnostics.add("local_discovery_catalog_unavailable")
        if receipt is not None:
            try:
                fallback, fallback_diagnostics = _fallback_native_metadata(receipt)
            except _NativeFallbackAuthorityError:
                return _blocked("local_discovery_catalog_authority_invalid")
            rows.extend(fallback)
            diagnostics.update(fallback_diagnostics)
    except (TypeError, ValueError):
        return _blocked("local_discovery_catalog_authority_invalid")
    if initial_management_revisions is not None:
        try:
            final_management = client.management_snapshot(
                correlation_id="cli:local-discovery:after"
            )
            final_revisions = final_management.get("ownerRevisions")
        except (OSError, RuntimeError):
            final_revisions = None
        except (TypeError, ValueError):
            return _blocked("local_discovery_owner_invalid")
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
        if _matches_kind(row, kind)
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
        {"local_discovery_source_truncated", "resource_source_discovery_budget_exceeded"}
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
        "productId": "coding",
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


def format_coding_local_discovery(document: dict[str, object], output: str) -> str:
    if output == "json":
        return json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n"
    if output != "text":
        raise ValueError("Local discovery format is invalid")
    lines = [
        f"Local discovery: {document['disposition']} "
        f"({document['totalMatchingRows']} matching; truncated={str(document['truncated']).lower()})"
    ]
    rows = document.get("rows")
    codes = document.get("diagnosticCodes")
    if not isinstance(rows, list) or not isinstance(codes, list):
        raise ValueError("Local discovery document is invalid")
    for row in rows:
        assert isinstance(row, dict)
        if row["identityKind"] == "plugin_installation":
            lines.append(
                f"plugin {row['name']} version={row.get('version') or 'unknown'} "
                f"scope={row['sourceScope']} source={row['sourceClass']} "
                f"availability={row['sourceAvailability']} "
                f"desired={row['desiredState']} "
                f"compatibility={row['productCompatibility']} "
                f"selection={row['productSelection']} "
                f"kinds={','.join(row.get('resourceKinds', [])) or 'unknown'}"
            )
        else:
            lines.append(
                f"native {row['resourceKind']} {row['name']} "
                f"scope={row['sourceScope']} source={row['sourceClass']} "
                f"enabled={row.get('enabled')} "
                f"catalog={row['nativeCatalogSelection']} "
                f"product={row['productSelection']}"
            )
        for code in row.get("diagnosticCodes", []):
            lines.append(f"  diagnostic: {code}")
    for code in codes:
        lines.append(f"diagnostic: {code}")
    return "\n".join(lines) + "\n"


def _matches_kind(row: dict[str, object], kind: LocalKind) -> bool:
    if kind == "all" or row.get("resourceKind") == kind:
        return True
    kinds = row.get("resourceKinds")
    return isinstance(kinds, list) and kind in kinds


def _read_inert_installed_kinds(
    client: CodingPluginManagementReadClientV1,
    revisions: dict[str, PluginPackageRevisionRefV1],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str], dict[str, str]]:
    """Classify exact Product-bound data bytes regardless of Desired enablement."""

    if not revisions:
        return {}, {}, {}
    kinds: dict[str, tuple[str, ...]] = {}
    diagnostics: dict[str, str] = {}
    evidence: dict[str, str] = {}
    legacy = {
        "legacy-local-reacquired": "skill",
        "legacy-local-reacquired-prompt": "prompt",
        "legacy-local-reacquired-theme": "theme",
    }
    with CodingFencedProductReadOnlyPreviewOwner.open(
        client.layout, workspace_guard=client.assert_workspace_current
    ) as owner:
        for plugin_id, revision in revisions.items():
            matches = tuple(
                binding for binding in owner.policy.bindings
                if binding.plugin_id == plugin_id
                and binding.source_identity == revision.package_source_identity
                and binding.artifact_digest == revision.package_content_digest
            )
            if len(matches) != 1:
                diagnostics[plugin_id] = "local_discovery_binding_unavailable"
                continue
            binding = matches[0]
            legacy_kind = legacy.get(binding.source_trust_class or "")
            if legacy_kind is not None:
                kinds[plugin_id] = (legacy_kind,)
                evidence[plugin_id] = "product_binding"
                continue
            if binding.source_trust_class != "local-data-only":
                continue
            report = validate_coding_data_wheel(binding.source_identity)
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


def _blocked(code: str) -> dict[str, object]:
    return {
        "discoveryVersion": 1,
        "productId": "coding",
        "scopeId": None,
        "disposition": "blocked",
        "sourceCompleteness": {"product": "blocked", "catalog": "blocked"},
        "truncated": False,
        "sourceTruncation": "unknown",
        "totalMatchingRows": 0,
        "totalMatchingRowsKnown": False,
        "rows": [],
        "diagnosticCodes": [code],
        "ownerEvidence": {},
    }


def blocked_coding_local_discovery(code: str) -> dict[str, object]:
    """Return the versioned fail-closed response for a boundary refusal."""

    return _blocked(code)


def _fallback_native_metadata(
    receipt: ResourceCatalogInputReceipt,
) -> tuple[list[dict[str, object]], set[str]]:
    """Recover fixed-depth names from declared roots after Catalog failure.

    These rows have no Catalog identity or selection proof.  The fallback does
    not read author bytes, descend unrelated directories, or follow symlinks.
    """

    rows: list[dict[str, object]] = []
    diagnostics: set[str] = {"local_discovery_native_metadata_fallback"}
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        diagnostics.add("local_discovery_native_fallback_unsupported")
        return rows, diagnostics
    roots = [(receipt.project_resource_root, "project_local", "workspace")]
    roots.extend((root, "user_global", "user") for root in receipt.user_resource_roots)
    if len(roots) > 16:
        roots = roots[:16]
        diagnostics.add("local_discovery_source_truncated")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    for root, source_class, scope in roots:
        if len(rows) >= _MAX_ROWS:
            diagnostics.add("local_discovery_source_truncated")
            break
        try:
            before = root.lstat()
            if not stat.S_ISDIR(before.st_mode) or root.resolve(strict=True) != root:
                raise _NativeFallbackAuthorityError("declared root is unsafe")
            root_fd = os.open(root, flags)
        except FileNotFoundError:
            diagnostics.add("local_discovery_native_root_unavailable")
            continue
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise _NativeFallbackAuthorityError("declared root became a link") from exc
            diagnostics.add("local_discovery_native_root_unavailable")
            continue
        opened = before
        try:
            opened = os.fstat(root_fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise _NativeFallbackAuthorityError("declared root changed on open")
            for dirname, resource_kind, suffix in (
                ("skills", "skill", None),
                ("prompts", "prompt", ".md"),
                ("themes", "theme", ".json"),
            ):
                if len(rows) >= _MAX_ROWS:
                    diagnostics.add("local_discovery_source_truncated")
                    break
                try:
                    directory_fd = os.open(dirname, flags, dir_fd=root_fd)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        try:
                            current = os.stat(
                                dirname, dir_fd=root_fd, follow_symlinks=False
                            )
                        except OSError:
                            raise _NativeFallbackAuthorityError(
                                "native directory changed during open"
                            ) from exc
                        if stat.S_ISLNK(current.st_mode):
                            raise _NativeFallbackAuthorityError(
                                "native directory became a link"
                            ) from exc
                    diagnostics.add("local_discovery_native_root_unavailable")
                    continue
                try:
                    with os.scandir(directory_fd) as entries:
                        for index, entry in enumerate(entries):
                            if index >= _MAX_ROWS or len(rows) >= _MAX_ROWS:
                                diagnostics.add("local_discovery_source_truncated")
                                break
                            try:
                                if suffix is None:
                                    if not entry.is_dir(follow_symlinks=False):
                                        diagnostics.add("local_discovery_native_entry_skipped")
                                        continue
                                    if _FALLBACK_NAME.fullmatch(entry.name) is None:
                                        diagnostics.add("local_discovery_native_entry_skipped")
                                        continue
                                    child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                                    try:
                                        metadata = os.stat(
                                            "SKILL.md", dir_fd=child_fd, follow_symlinks=False
                                        )
                                    finally:
                                        os.close(child_fd)
                                    name = f"{entry.name}/SKILL.md"
                                else:
                                    if not entry.name.endswith(suffix):
                                        continue
                                    if _FALLBACK_NAME.fullmatch(
                                        entry.name[: -len(suffix)]
                                    ) is None:
                                        diagnostics.add("local_discovery_native_entry_skipped")
                                        continue
                                    metadata = os.stat(
                                        entry.name, dir_fd=directory_fd, follow_symlinks=False
                                    )
                                    name = entry.name
                                if not stat.S_ISREG(metadata.st_mode):
                                    diagnostics.add("local_discovery_native_entry_skipped")
                                    continue
                            except OSError as exc:
                                if exc.errno == errno.ELOOP:
                                    raise _NativeFallbackAuthorityError("native child became a link") from exc
                                diagnostics.add("local_discovery_native_entry_skipped")
                                continue
                            rows.append(
                                {
                                    "identityKind": "native_resource",
                                    "pluginId": None,
                                    "name": name,
                                    "resourceKind": resource_kind,
                                    "resourceKinds": [resource_kind],
                                    "version": None,
                                    "sourceClass": source_class,
                                    "sourceScope": scope,
                                    "candidateFingerprint": None,
                                    "contentDigest": None,
                                    "enabled": None,
                                    "nativeCatalogSelection": "not_checked",
                                    "productCompatibility": "not_checked",
                                    "productSelection": "not_checked",
                                    "discoveryEvidence": "fallback_metadata",
                                    "diagnosticCodes": ["local_discovery_catalog_unavailable"],
                                }
                            )
                finally:
                    os.close(directory_fd)
        finally:
            os.close(root_fd)
            try:
                after = root.lstat()
                if (
                    not stat.S_ISDIR(after.st_mode)
                    or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
                    or root.resolve(strict=True) != root
                ):
                    raise _NativeFallbackAuthorityError("declared root changed during read")
            except OSError as exc:
                raise _NativeFallbackAuthorityError("declared root disappeared") from exc
    return rows, diagnostics


__all__ = [
    "blocked_coding_local_discovery",
    "discover_coding_local_plugins",
    "format_coding_local_discovery",
]
