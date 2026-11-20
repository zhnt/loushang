"""Product-selected data Resources whose composition does not require coding.base."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as replace
from hashlib import sha256 as sha256

from loushang.coding.composition.base_plugin import _owner_bindings as _owner_bindings
from loushang.coding.composition.base_product import (
    CodingBaseProductResourceBody,
)
from loushang.coding.composition.base_product import (
    _candidate as _candidate,
)
from loushang.coding.composition.base_product import (
    _resource_bodies as _resource_bodies,
)
from loushang.coding.composition.sets import CodingCompositionSetPlan
from loushang.coding.harness.session import (
    external_resource_composition as _resource_programs,
)
from loushang.coding.package.legacy_data_trust import (
    EXTERNAL_DATA_TRUST_CLASSES as EXTERNAL_DATA_TRUST_CLASSES,
)
from loushang.coding.package.legacy_data_trust import (
    EXTERNAL_DATA_TRUST_CLASSES_ORDERED as EXTERNAL_DATA_TRUST_CLASSES_ORDERED,
)
from loushang.coding.package.legacy_data_trust import (
    permits_external_data_owner as permits_external_data_owner,
)
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION as MODEL_INPUT_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities import (
    WORKSPACE_CAPABILITY_DEFINITION as WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority as OwnerContributionAuthority,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes as canonical_json_bytes,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation as PluginContributionReservation,
)
from loushang.harness.resources.plugins.declarations import (
    PluginDeclaration as PluginDeclaration,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef as PluginContributionRef,
)
from loushang.harness.resources.plugins.selection import (
    PluginEffectiveConfigurationEntry as PluginEffectiveConfigurationEntry,
)
from loushang.harness.resources.plugins.selection import (
    PluginEffectiveConfigurationSetV1 as PluginEffectiveConfigurationSetV1,
)
from loushang.harness.resources.plugins.selection import (
    PluginPreflightContextV1 as PluginPreflightContextV1,
)
from loushang.harness.resources.plugins.selection import (
    PluginSelectionPlanV2 as PluginSelectionPlanV2,
)
from loushang.harness.resources.plugins.selection import (
    PluginSourceTrustSnapshotV1 as PluginSourceTrustSnapshotV1,
)
from loushang.harness.session.product_composition_assembly import (
    ProductContributionOwnerBinding as ProductContributionOwnerBinding,
)
from loushang.harness.session.product_composition_assembly import (
    _assemble_product_contribution_candidates as _assemble_product_contribution_candidates,
)

_RESOURCE_COMPOSITION_PROGRAM_VALUES = {
    "value_001": "coding-external-data-v1:",
    "value_002": "Product external data selections must be sorted and nonempty",
    "value_003": "Product external data Plugin identity is duplicated",
    "value_004": "Coding composition set is required",
    "value_005": "Coding Product Session id is invalid",
    "value_006": "Coding Product evaluation time is invalid",
    "value_007": "Product external data Resource selection changed",
    "value_008": "coding",
    "value_009": "Product data Resource body identity is duplicated",
}


@dataclass(frozen=True, slots=True)
class CodingExternalDataProductCompilation:
    product_composition: ProductCompositionCompilation
    selected_manifests: tuple[PackageProductSelectedPluginManifestV1, ...]
    resource_bodies: tuple[CodingBaseProductResourceBody, ...]

    def product_resource_inputs(self) -> tuple[ProductSelectedResourceInput, ...]:
        return _resource_programs.external_resource_inputs(self)

    def assert_current(self, runtime: PackageProductRuntimeBindingV1) -> None:
        for selected in self.selected_manifests:
            runtime.assert_selected_plugin_manifest_current(selected)


def compile_coding_external_data_product_selection(
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    *,
    composition_set: CodingCompositionSetPlan,
    session_id: str,
    evaluated_at: int,
) -> CodingExternalDataProductCompilation:
    """Admit exact Product Store data roots without a base Plugin dependency."""

    return _resource_programs.compile_data_selection(
        selected,
        composition_set=composition_set,
        session_id=session_id,
        evaluated_at=evaluated_at,
    )


__all__ = [
    "CodingExternalDataProductCompilation",
    "compile_coding_external_data_product_selection",
]
