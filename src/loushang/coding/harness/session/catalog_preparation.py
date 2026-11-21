"""Observe and recheck the inputs to a session resource catalog."""

from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductPluginDesiredSelectionV1,
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.plugins.selection import PluginSelectionPlanV2
from loushang.harness.resources.plugins.types import PublishedPluginPackage

_AdmissionFailure = Callable[[tuple[str, ...]], Exception]


def select_resource_plan(
    plan: PluginSelectionPlanV2,
    package: PublishedPluginPackage,
    *,
    plugin_id: str,
) -> PluginSelectionPlanV2 | None:
    resource_ids = {
        item.contribution_id
        for item in package.contribution_index.items
        if item.kind == "resource_item"
    }
    selected_resources = tuple(
        item
        for item in plan.selected_contributions
        if item.plugin_id == plugin_id and item.contribution_id in resource_ids
    )
    if not selected_resources:
        return None
    return replace(plan, selected_contributions=selected_resources)


def require_catalog_receipt(
    loader: ResourceLoader,
    cwd: Path,
    admission_failure: _AdmissionFailure,
    receipt: ResourceCatalogInputReceipt | None = None,
) -> ResourceCatalogInputReceipt:
    if receipt is None:
        try:
            receipt = loader.prepare_catalog_input_receipt(cwd)
        except (AttributeError, RuntimeError) as exc:
            raise admission_failure(("catalog_receipt_unavailable",)) from exc
    if not isinstance(receipt, ResourceCatalogInputReceipt):
        raise admission_failure(("catalog_receipt_unavailable",))
    return receipt


def observe_requested_plugins(
    runtime: PackageProductRuntimeBindingV1,
    requests: tuple[tuple[str, bool], ...],
    admission_failure: _AdmissionFailure,
) -> tuple[list[str], tuple[PackageProductPluginDesiredSelectionV1, ...]]:
    enabled: list[str] = []
    observed: list[PackageProductPluginDesiredSelectionV1] = []
    for plugin_id, requested in requests:
        if not requested:
            continue
        selection = runtime.capture_plugin_desired_selection_for(plugin_id)
        observed.append(selection)
        if selection.desired_state == "absent" and not selection.recorded:
            raise admission_failure(("product_requested_capability_not_installed",))
        if selection.desired_state == "installed_enabled":
            enabled.append(plugin_id)
    return enabled, tuple(observed)


def require_current_manifests(
    runtime: PackageProductRuntimeBindingV1,
    manifests: tuple[PackageProductSelectedPluginManifestV1, ...],
    reason: str,
    admission_failure: _AdmissionFailure,
) -> None:
    for manifest in manifests:
        try:
            runtime.assert_selected_plugin_manifest_current(manifest)
        except (
            PackageProductRuntimeActivationError,
            PackageProductRuntimeReadError,
        ) as exc:
            raise admission_failure((reason,)) from exc


def capture_selected_manifests(
    runtime: PackageProductRuntimeBindingV1,
    plugin_ids: Iterable[str],
    *,
    max_files: int,
    max_total_bytes: int,
) -> tuple[PackageProductSelectedPluginManifestV1, ...]:
    return tuple(
        runtime.capture_selected_plugin_manifest_for(
            plugin_id, max_files=max_files, max_total_bytes=max_total_bytes
        )
        for plugin_id in plugin_ids
    )
