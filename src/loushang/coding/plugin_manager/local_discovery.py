"""Bounded, read-only local Plugin and native Resource discovery for Coding."""

from __future__ import annotations

import json
import re
from typing import Literal

from loushang.coding.harness.plugin_management import local_discovery as _programs
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

LocalKind = Literal["all", "plugin", "skill", "prompt", "theme"]
LocalSource = Literal["all", "project_local", "user_global", "local", "builtin"]
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

    return _programs.discover_local_plugins(
        client, query=query, kind=kind, source=source, limit=limit
    )


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
