"""Bounded, read-only local Plugin and native Resource discovery for Coding."""

from __future__ import annotations

import json
import re

from loushang.coding.package.epoch_layout import (
    coding_fenced_product_exists as coding_fenced_product_exists,
)
from loushang.coding.package.product_preview import (
    CodingFencedProductReadOnlyPreviewOwner as CodingFencedProductReadOnlyPreviewOwner,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout as resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.plugin_manager.preview import (
    _capture_disabled_skills as _capture_disabled_skills,
)
from loushang.coding.plugin_manager.read_sdk import CodingPluginManagementReadClientV1
from loushang.coding.resources.catalog import (
    CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY as CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
)
from loushang.coding.resources.catalog import (
    CodingResourceCatalogAdmissionError as CodingResourceCatalogAdmissionError,
)
from loushang.coding.resources.catalog import (
    build_coding_initial_resource_catalog_adapter as build_coding_initial_resource_catalog_adapter,
)
from loushang.coding.resources.runtime import (
    CodingResourceLoader as CodingResourceLoader,
)
from loushang.harness.plugin_management.current_preview import (
    LocalDiscoveryEvidence,
    LocalDiscoveryEvidenceError,
    LocalKind,
    LocalSource,
)
from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint as plugin_package_revision_fingerprint,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.plugin_management.records import (
    PluginPackageRevisionRefV1 as PluginPackageRevisionRefV1,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources._catalog_records import (
    NativeHostOrigin as NativeHostOrigin,
)
from loushang.harness.resources._loader_discovery_filesystem import (
    _discover_native_fallback_metadata,
)
from loushang.plugin._coding_data_wheel_validation import (
    validate_coding_data_wheel as validate_coding_data_wheel,
)

_MAX_ROWS = 500
_FALLBACK_NAME = re.compile(r"[a-z][a-z0-9-]{0,127}\Z")


_PRODUCT_ID = "coding"
_LEGACY_RESOURCE_KINDS = {
    "legacy-local-reacquired": "skill",
    "legacy-local-reacquired-prompt": "prompt",
    "legacy-local-reacquired-theme": "theme",
}


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
    discovery = LocalDiscoveryEvidence()
    rows = discovery.rows
    diagnostics = discovery.diagnostics
    completeness = discovery.completeness
    evidence = discovery.owner_evidence

    # A missing fence is an ordinary partial inventory: native files remain
    # discoverable, but no installed-Plugin claim can be made from it.
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    if layout != client.layout:
        return _blocked("local_discovery_scope_changed")
    if coding_fenced_product_exists(layout):
        try:
            discovery.read_installations(
                client,
                product_id=_PRODUCT_ID,
                read_inert_kinds=lambda revisions: _read_inert_installed_kinds(
                    client, revisions
                ),
            )
        except LocalDiscoveryEvidenceError as error:
            return _blocked(error.code)
    else:
        diagnostics.add("local_discovery_product_not_fenced")

    receipt: ResourceCatalogInputReceipt | None = None
    try:
        disabled_skills, settings_revision = _capture_disabled_skills(
            workspace
        )
        loader = CodingResourceLoader(workspace_root=workspace)
        receipt = loader.prepare_catalog_input_receipt(workspace)
        adapter = build_coding_initial_resource_catalog_adapter(
            receipt,
            product_scope_id="plugin-local-discovery",
            disabled_skills=disabled_skills,
            source_policy=CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
        )
        catalog = adapter.prepare_bootstrap_projection_with_receipt(
            product_id=_PRODUCT_ID,
            session_id="plugin-local-discovery",
            cwd=workspace,
        ).catalog
        discovery.project_native_catalog(catalog)
        evidence["disabledSkillSettingsRevision"] = settings_revision
        _after_disabled, after_settings_revision = _capture_disabled_skills(
            workspace
        )
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
                fallback, fallback_diagnostics = _fallback_native_metadata(
                    receipt
                )
            except _NativeFallbackAuthorityError:
                return _blocked("local_discovery_catalog_authority_invalid")
            rows.extend(fallback)
            diagnostics.update(fallback_diagnostics)
    except (TypeError, ValueError):
        return _blocked("local_discovery_catalog_authority_invalid")
    try:
        discovery.recheck_installations(client)
    except LocalDiscoveryEvidenceError as error:
        return _blocked(error.code)
    client.assert_workspace_current()
    return discovery.result(
        product_id=_PRODUCT_ID, scope_id=client.scope_id,
        query=query, kind=kind, source=source, limit=limit,
    )


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
    with CodingFencedProductReadOnlyPreviewOwner.open(
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
            legacy_kind = _LEGACY_RESOURCE_KINDS.get(
                binding.source_trust_class or ""
            )
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


def _blocked(code: str) -> dict[str, object]:
    return {
        "discoveryVersion": 1,
        "productId": _PRODUCT_ID,
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
    """Recover metadata under the original native discovery owner."""

    return _discover_native_fallback_metadata(
        receipt,
        max_rows=_MAX_ROWS,
        name_pattern=_FALLBACK_NAME,
        diagnostic_prefix="local_discovery_",
        authority_error=_NativeFallbackAuthorityError,
        row_factory=_fallback_native_row,
    )


def _fallback_native_row(
    name: str,
    resource_kind: str,
    source_class: str,
    scope: str,
) -> dict[str, object]:
    return {
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


__all__ = [
    "blocked_coding_local_discovery",
    "discover_coding_local_plugins",
    "format_coding_local_discovery",
]
