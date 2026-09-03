"""Lazy public exports for resource package management."""

# ruff: noqa: F401 - TYPE_CHECKING imports preserve the typed public facade.

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from loushang.harness.resources.packages.catalog import (
        PackageCatalogBuilder,
        PackageCatalogDiagnostic,
        PackageCatalogEntry,
        PackageCatalogSources,
        PackageSummaryProvider,
        collect_package_catalog,
        empty_package_summary,
        load_package_catalog,
        mark_package_conflicts,
        package_catalog_sources,
        summarize_package_resources,
        summarize_profiled_package_resources,
    )
    from loushang.harness.resources.packages.catalog_diagnostics import (
        PackageCatalogDiagnosticsRecorder,
        record_package_lockfile_diagnostics,
        record_package_source_policy_denial,
    )
    from loushang.harness.resources.packages.inventory import (
        FilesystemPackageResourceInventory,
        PackageResourceInventoryPort,
        summarize_package_inventory,
    )
    from loushang.harness.resources.packages.manifest import (
        PackageManifestInfo,
        resolve_package_manifest,
    )
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
        PackageMaterializationLifecycle,
        PackageMaterializationRecord,
        PackageMaterializer,
        PackageMaterializerBackend,
        PackageProgressEvent,
        PackageSourcePolicy,
        PythonPackageInstallerBackend,
        package_offline_enabled,
        resolve_session_package_install_root,
    )
    from loushang.harness.resources.packages.mounts import PackageResourceMount
    from loushang.harness.resources.packages.operations import (
        PackageMaterializerPort,
        PackageMaterializerProvider,
        PackageMutationRequiresAsyncError,
        PackageOperationsRuntime,
        PackageResourceRefresh,
        PackageResourceRefreshOutcome,
        PackageResourceRefreshTransaction,
        PackageResourceRefreshTransactionRunner,
        PackageSourceRegistration,
        PackageUpdatePreparation,
    )
    from loushang.harness.resources.packages.product_activation import (
        PACKAGE_PRODUCT_ACTIVATION_VERSION,
        PackageProductActivationError,
        PackageProductEpochTransactionGuardPort,
        PackageProductIngressFactoryPort,
        PackageProductLifecycleActivation,
        PackageProductRecoveryPort,
    )
    from loushang.harness.resources.packages.product_composition import (
        PackageRetentionHandoffRecovery,
        compose_package_product_lifecycle,
    )
    from loushang.harness.resources.packages.product_contract import (
        PACKAGE_PRODUCT_EVIDENCE_VERSION,
        PACKAGE_PRODUCT_INTENT_VERSION,
        PACKAGE_PRODUCT_LIFECYCLE_FAILURE_CODES,
        PACKAGE_PRODUCT_OUTCOME_VERSION,
        PACKAGE_PRODUCT_RECORD_VERSION,
        PACKAGE_PRODUCT_UPDATE_CHECK_REQUEST_VERSION,
        PACKAGE_PRODUCT_UPDATE_MANIFEST_RECEIPT_VERSION,
        PackageProductEntrypoint,
        PackageProductLifecycleAction,
        PackageProductLifecycleEvidenceV1,
        PackageProductLifecycleIntentV1,
        PackageProductLifecycleInventoryPort,
        PackageProductLifecycleMode,
        PackageProductLifecycleOperationPort,
        PackageProductLifecycleOutcomeV1,
        PackageProductLifecycleRecordV1,
        PackageProductRoutingDisposition,
        PackageProductUpdateCheckRequestV1,
        PackageProductUpdateCheckV1,
        PackageProductUpdateManifestReceiptV1,
        PackageProductUpdateTargetV1,
    )
    from loushang.harness.resources.packages.product_inventory import (
        PACKAGE_PRODUCT_UPDATE_MANIFEST_VERSION,
        PackageProductUpdateManifestError,
        PackageProductUpdateManifestJournal,
        PackageProductUpdateManifestV1,
    )
    from loushang.harness.resources.packages.product_lifecycle import (
        PACKAGE_PRODUCT_PUBLISH_ATTEMPT_VERSION,
        PACKAGE_PRODUCT_ROUTE_VERSION,
        PackageProductLifecycleExecutionBinding,
        PackageProductLifecycleRouter,
        PackageProductLifecycleTransactionPort,
        PackageProductPublishAttemptV1,
        PackageProductRouteContractError,
        PackageProductRouteRequestV1,
    )
    from loushang.harness.resources.packages.product_runtime import (
        PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION,
        PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION,
        PackageProductRuntimeActivationError,
        PackageProductRuntimeBindingV1,
        PackageProductRuntimeFactoryPort,
        PackageProductRuntimeRequestV1,
        activate_package_product_runtime,
    )
    from loushang.harness.resources.packages.projection import (
        collect_projected_package_entries,
        project_package_entries,
        project_package_entry,
        serialize_package_materialization_record,
        serialize_package_operation_record,
    )
    from loushang.harness.resources.packages.roots import (
        ResolvedPackageResourceRoots,
        SelectedPluginPackageInput,
        configure_resource_loader_roots,
        resolve_package_resource_roots,
    )
    from loushang.harness.resources.packages.security import (
        PackageSecurityPolicy,
        PackageSourceSecurityReport,
    )
    from loushang.harness.resources.packages.settings_mutation import (
        PackageSourceMutationState,
        PackageSourceSettingsMutation,
    )
    from loushang.harness.resources.packages.source import (
        PackageSourceConfig,
        PackageSourceIdentity,
        clone_source_and_ref,
        is_python_package_source,
        is_remote_package_source,
        package_source_from_raw,
        package_source_match_key,
        python_package_name,
        python_package_requirement,
        remote_package_name,
    )
    from loushang.harness.resources.packages.source_resolver import (
        MissingSourceAction,
        MissingSourceResolver,
        PackageResolveResult,
        PackageSourceResolver,
        configured_package_sources,
        package_source_scopes,
    )

_EXPORT_MODULES = {
    "PACKAGE_PRODUCT_ACTIVATION_VERSION": "loushang.harness.resources.packages.product_activation",
    "PACKAGE_PRODUCT_EVIDENCE_VERSION": "loushang.harness.resources.packages.product_contract",
    "PACKAGE_PRODUCT_INTENT_VERSION": "loushang.harness.resources.packages.product_contract",
    "PACKAGE_PRODUCT_OUTCOME_VERSION": "loushang.harness.resources.packages.product_contract",
    "PACKAGE_PRODUCT_PUBLISH_ATTEMPT_VERSION": "loushang.harness.resources.packages.product_lifecycle",
    "PACKAGE_PRODUCT_RECORD_VERSION": "loushang.harness.resources.packages.product_contract",
    "PACKAGE_PRODUCT_UPDATE_MANIFEST_RECEIPT_VERSION": "loushang.harness.resources.packages.product_contract",
    "PACKAGE_PRODUCT_UPDATE_CHECK_REQUEST_VERSION": "loushang.harness.resources.packages.product_contract",
    "PACKAGE_PRODUCT_ROUTE_VERSION": "loushang.harness.resources.packages.product_lifecycle",
    "PACKAGE_PRODUCT_RUNTIME_BINDING_VERSION": "loushang.harness.resources.packages.product_runtime",
    "PACKAGE_PRODUCT_RUNTIME_REQUEST_VERSION": "loushang.harness.resources.packages.product_runtime",
    "PACKAGE_PRODUCT_UPDATE_MANIFEST_VERSION": "loushang.harness.resources.packages.product_inventory",
    "FilesystemPackageResourceInventory": "loushang.harness.resources.packages.inventory",
    "GitPackageMaterializerBackend": "loushang.harness.resources.packages.materializer",
    "MissingSourceAction": "loushang.harness.resources.packages.source_resolver",
    "MissingSourceResolver": "loushang.harness.resources.packages.source_resolver",
    "PackageCatalogBuilder": "loushang.harness.resources.packages.catalog",
    "PackageCatalogDiagnostic": "loushang.harness.resources.packages.catalog",
    "PackageCatalogDiagnosticsRecorder": "loushang.harness.resources.packages.catalog_diagnostics",
    "PackageCatalogEntry": "loushang.harness.resources.packages.catalog",
    "PackageCatalogSources": "loushang.harness.resources.packages.catalog",
    "PackageSummaryProvider": "loushang.harness.resources.packages.catalog",
    "PackageManifestInfo": "loushang.harness.resources.packages.manifest",
    "PackageMaterializationLifecycle": "loushang.harness.resources.packages.materializer",
    "PackageMaterializationRecord": "loushang.harness.resources.packages.materializer",
    "PackageMaterializer": "loushang.harness.resources.packages.materializer",
    "PackageMaterializerBackend": "loushang.harness.resources.packages.materializer",
    "PackageMaterializerPort": "loushang.harness.resources.packages.operations",
    "PackageResourceMount": "loushang.harness.resources.packages.mounts",
    "PackageResourceInventoryPort": "loushang.harness.resources.packages.inventory",
    "PackageMaterializerProvider": "loushang.harness.resources.packages.operations",
    "PackageMutationRequiresAsyncError": "loushang.harness.resources.packages.operations",
    "PackageOperationsRuntime": "loushang.harness.resources.packages.operations",
    "PackageProgressEvent": "loushang.harness.resources.packages.materializer",
    "PackageProductEntrypoint": "loushang.harness.resources.packages.product_contract",
    "PACKAGE_PRODUCT_LIFECYCLE_FAILURE_CODES": "loushang.harness.resources.packages.product_contract",
    "PackageProductActivationError": "loushang.harness.resources.packages.product_activation",
    "PackageProductEpochTransactionGuardPort": "loushang.harness.resources.packages.product_activation",
    "PackageProductIngressFactoryPort": "loushang.harness.resources.packages.product_activation",
    "PackageProductLifecycleActivation": "loushang.harness.resources.packages.product_activation",
    "PackageProductLifecycleAction": "loushang.harness.resources.packages.product_contract",
    "PackageProductLifecycleEvidenceV1": "loushang.harness.resources.packages.product_contract",
    "PackageProductLifecycleExecutionBinding": "loushang.harness.resources.packages.product_lifecycle",
    "PackageProductLifecycleInventoryPort": "loushang.harness.resources.packages.product_contract",
    "PackageProductLifecycleIntentV1": "loushang.harness.resources.packages.product_contract",
    "PackageProductLifecycleOperationPort": "loushang.harness.resources.packages.product_contract",
    "PackageProductLifecycleMode": "loushang.harness.resources.packages.product_contract",
    "PackageProductLifecycleOutcomeV1": "loushang.harness.resources.packages.product_contract",
    "PackageProductLifecycleRecordV1": "loushang.harness.resources.packages.product_contract",
    "PackageProductLifecycleRouter": "loushang.harness.resources.packages.product_lifecycle",
    "PackageProductLifecycleTransactionPort": "loushang.harness.resources.packages.product_lifecycle",
    "PackageProductUpdateManifestError": "loushang.harness.resources.packages.product_inventory",
    "PackageProductUpdateManifestJournal": "loushang.harness.resources.packages.product_inventory",
    "PackageProductUpdateManifestV1": "loushang.harness.resources.packages.product_inventory",
    "PackageProductPublishAttemptV1": "loushang.harness.resources.packages.product_lifecycle",
    "PackageProductRouteContractError": "loushang.harness.resources.packages.product_lifecycle",
    "PackageProductRouteRequestV1": "loushang.harness.resources.packages.product_lifecycle",
    "PackageProductRuntimeActivationError": "loushang.harness.resources.packages.product_runtime",
    "PackageProductRuntimeBindingV1": "loushang.harness.resources.packages.product_runtime",
    "PackageProductRuntimeFactoryPort": "loushang.harness.resources.packages.product_runtime",
    "PackageProductRuntimeRequestV1": "loushang.harness.resources.packages.product_runtime",
    "PackageProductRecoveryPort": "loushang.harness.resources.packages.product_activation",
    "PackageProductRoutingDisposition": "loushang.harness.resources.packages.product_contract",
    "PackageProductUpdateCheckV1": "loushang.harness.resources.packages.product_contract",
    "PackageProductUpdateCheckRequestV1": "loushang.harness.resources.packages.product_contract",
    "PackageProductUpdateManifestReceiptV1": "loushang.harness.resources.packages.product_contract",
    "PackageProductUpdateTargetV1": "loushang.harness.resources.packages.product_contract",
    "PackageResolveResult": "loushang.harness.resources.packages.source_resolver",
    "PackageRetentionHandoffRecovery": "loushang.harness.resources.packages.product_composition",
    "PackageSourceConfig": "loushang.harness.resources.packages.source",
    "PackageSourceIdentity": "loushang.harness.resources.packages.source",
    "PackageSourcePolicy": "loushang.harness.resources.packages.materializer",
    "PackageResourceRefresh": "loushang.harness.resources.packages.operations",
    "PackageResourceRefreshOutcome": "loushang.harness.resources.packages.operations",
    "PackageResourceRefreshTransaction": "loushang.harness.resources.packages.operations",
    "PackageResourceRefreshTransactionRunner": "loushang.harness.resources.packages.operations",
    "PackageSecurityPolicy": "loushang.harness.resources.packages.security",
    "PackageSourceSecurityReport": "loushang.harness.resources.packages.security",
    "PackageSourceRegistration": "loushang.harness.resources.packages.operations",
    "PackageSourceMutationState": "loushang.harness.resources.packages.settings_mutation",
    "PackageSourceSettingsMutation": "loushang.harness.resources.packages.settings_mutation",
    "PackageSourceResolver": "loushang.harness.resources.packages.source_resolver",
    "PackageUpdatePreparation": "loushang.harness.resources.packages.operations",
    "PythonPackageInstallerBackend": "loushang.harness.resources.packages.materializer",
    "ResolvedPackageResourceRoots": "loushang.harness.resources.packages.roots",
    "SelectedPluginPackageInput": "loushang.harness.resources.packages.roots",
    "activate_package_product_runtime": "loushang.harness.resources.packages.product_runtime",
    "clone_source_and_ref": "loushang.harness.resources.packages.source",
    "collect_package_catalog": "loushang.harness.resources.packages.catalog",
    "collect_projected_package_entries": "loushang.harness.resources.packages.projection",
    "compose_package_product_lifecycle": "loushang.harness.resources.packages.product_composition",
    "configure_resource_loader_roots": "loushang.harness.resources.packages.roots",
    "configured_package_sources": "loushang.harness.resources.packages.source_resolver",
    "empty_package_summary": "loushang.harness.resources.packages.catalog",
    "is_python_package_source": "loushang.harness.resources.packages.source",
    "is_remote_package_source": "loushang.harness.resources.packages.source",
    "load_package_catalog": "loushang.harness.resources.packages.catalog",
    "mark_package_conflicts": "loushang.harness.resources.packages.catalog",
    "package_catalog_sources": "loushang.harness.resources.packages.catalog",
    "package_offline_enabled": "loushang.harness.resources.packages.materializer",
    "package_source_match_key": "loushang.harness.resources.packages.source",
    "package_source_scopes": "loushang.harness.resources.packages.source_resolver",
    "package_source_from_raw": "loushang.harness.resources.packages.source",
    "project_package_entries": "loushang.harness.resources.packages.projection",
    "project_package_entry": "loushang.harness.resources.packages.projection",
    "python_package_name": "loushang.harness.resources.packages.source",
    "python_package_requirement": "loushang.harness.resources.packages.source",
    "remote_package_name": "loushang.harness.resources.packages.source",
    "record_package_lockfile_diagnostics": "loushang.harness.resources.packages.catalog_diagnostics",
    "record_package_source_policy_denial": "loushang.harness.resources.packages.catalog_diagnostics",
    "resolve_package_manifest": "loushang.harness.resources.packages.manifest",
    "resolve_package_resource_roots": "loushang.harness.resources.packages.roots",
    "resolve_session_package_install_root": "loushang.harness.resources.packages.materializer",
    "serialize_package_materialization_record": "loushang.harness.resources.packages.projection",
    "serialize_package_operation_record": "loushang.harness.resources.packages.projection",
    "summarize_profiled_package_resources": "loushang.harness.resources.packages.catalog",
    "summarize_package_resources": "loushang.harness.resources.packages.catalog",
    "summarize_package_inventory": "loushang.harness.resources.packages.inventory",
}


def __getattr__(name: str) -> Any:
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORT_MODULES})


__all__ = list(_EXPORT_MODULES)
