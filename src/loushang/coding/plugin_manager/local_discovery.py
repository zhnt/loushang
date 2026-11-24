"""Bounded, read-only local Plugin and native Resource discovery for Coding."""

from __future__ import annotations

import re
from functools import partial
from pathlib import Path

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
    LocalDiscoveryEvidenceError,
    LocalKind,
    LocalSource,
    blocked_local_plugin_discovery,
    discover_local_plugins,
    read_inert_data_kinds,
)
from loushang.harness.plugin_management.current_preview import (
    format_local_plugin_discovery as format_coding_local_discovery,
)
from loushang.harness.plugin_management.records import (
    PluginPackageRevisionRefV1 as PluginPackageRevisionRefV1,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources._catalog_records import ResourceCatalogSnapshot
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

    def read_product_fence(workspace: Path) -> bool:
        layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
        if layout != client.layout:
            raise LocalDiscoveryEvidenceError("local_discovery_scope_changed")
        return coding_fenced_product_exists(layout)

    def project_catalog(
        workspace: Path, receipt: ResourceCatalogInputReceipt, disabled_skills: tuple[str, ...]
    ) -> ResourceCatalogSnapshot:
        adapter = build_coding_initial_resource_catalog_adapter(
            receipt,
            product_scope_id="plugin-local-discovery",
            disabled_skills=disabled_skills,
            source_policy=CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
        )
        return adapter.prepare_bootstrap_projection_with_receipt(
            product_id=_PRODUCT_ID, session_id="plugin-local-discovery", cwd=workspace
        ).catalog

    return discover_local_plugins(
        client, product_id=_PRODUCT_ID, query=query, kind=kind, source=source, limit=limit,
        max_rows=_MAX_ROWS,
        read_product_fence=read_product_fence,
        read_inert_kinds=partial(_read_inert_installed_kinds, client),
        capture_settings=_capture_disabled_skills,
        prepare_receipt=lambda workspace: CodingResourceLoader(
            workspace_root=workspace
        ).prepare_catalog_input_receipt(workspace),
        project_catalog=project_catalog,
        fallback_metadata=_fallback_native_metadata,
        catalog_admission_error=CodingResourceCatalogAdmissionError,
        fallback_authority_error=_NativeFallbackAuthorityError,
    )


def _read_inert_installed_kinds(
    client: CodingPluginManagementReadClientV1,
    revisions: dict[str, PluginPackageRevisionRefV1],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str], dict[str, str]]:
    if not revisions:
        return {}, {}, {}
    with CodingFencedProductReadOnlyPreviewOwner.open(
        client.layout, workspace_guard=client.assert_workspace_current
    ) as owner:
        result = read_inert_data_kinds(
            owner.policy.bindings, revisions,
            legacy_kinds=_LEGACY_RESOURCE_KINDS,
            artifact_kinds=frozenset({"skill", "prompt"}),
            validate_artifact=validate_coding_data_wheel,
        )
        owner.epoch_runtime.assert_current()
        return result


def blocked_coding_local_discovery(code: str) -> dict[str, object]:
    """Return the versioned fail-closed response for a boundary refusal."""

    return blocked_local_plugin_discovery(_PRODUCT_ID, code)


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
