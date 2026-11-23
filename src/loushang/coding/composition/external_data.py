"""Product-selected data Resources whose composition does not require coding.base."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as replace
from hashlib import sha256 as sha256

from loushang.coding.composition.base_plugin import _owner_bindings as _owner_bindings
from loushang.coding.composition.base_product import (
    CodingBaseProductResourceBody,
    _bind_coding_external_resource_owners,
    _capture_external_resource_declarations,
)
from loushang.coding.composition.base_product import (
    _candidate as _candidate,
)
from loushang.coding.composition.base_product import (
    _resource_bodies as _resource_bodies,
)
from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.composition.sets import CodingCompositionSetPlan
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
from loushang.harness.package_product._selected_plugin_revisions import (
    require_current_manifests,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
    project_selected_resource_inputs,
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
from loushang.harness.session.product_composition_assembly import (
    assemble_product_data_resources,
)


@dataclass(frozen=True, slots=True)
class CodingExternalDataProductCompilation:
    product_composition: ProductCompositionCompilation
    selected_manifests: tuple[PackageProductSelectedPluginManifestV1, ...]
    resource_bodies: tuple[CodingBaseProductResourceBody, ...]

    def product_resource_inputs(self) -> tuple[ProductSelectedResourceInput, ...]:
        return project_selected_resource_inputs(
            self.product_composition.resource_admissions,
            self.selected_manifests,
            self.resource_bodies,
        )

    def assert_current(self, runtime: PackageProductRuntimeBindingV1) -> None:
        require_current_manifests(runtime, self.selected_manifests)


def compile_coding_external_data_product_selection(
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    *,
    composition_set: CodingCompositionSetPlan,
    session_id: str,
    evaluated_at: int,
) -> CodingExternalDataProductCompilation:
    """Admit exact Product Store data roots without a base Plugin dependency."""

    if not selected or tuple(sorted(item.manifest.name for item in selected)) != tuple(
        item.manifest.name for item in selected
    ):
        raise ValueError("Product external data selections must be sorted and nonempty")
    if len({item.manifest.name for item in selected}) != len(selected):
        raise ValueError("Product external data Plugin identity is duplicated")
    if not isinstance(composition_set, CodingCompositionSetPlan):
        raise TypeError("Coding composition set is required")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Coding Product Session id is invalid")
    if type(evaluated_at) is not int or evaluated_at < 0:
        raise ValueError("Coding Product evaluation time is invalid")
    declarations = _capture_external_resource_declarations(selected, standalone=True)
    policy_digest = sha256(
        canonical_json_bytes(
            [
                {
                    "pluginId": item.manifest.name,
                    "committedSetId": item.snapshot.committed_record.committed_set.set_id,
                    "instanceRevision": item.snapshot.instance_revision_ref.to_dict(),
                }
                for item in selected
            ]
        )
    ).hexdigest()
    _, composition, _ = assemble_product_data_resources(
        selected,
        declarations,
        product_id=CODING_PRODUCT_ID,
        scope_id=f"session:{session_id.strip()}",
        policy_revision=(
            f"coding-external-data-v1:{composition_set.set_id}:{composition_set.fingerprint}:{policy_digest}"
        ),
        evaluated_at=evaluated_at,
        prepare=_candidate,
        bind_owners=_bind_coding_external_resource_owners,
        external_trust_classes=EXTERNAL_DATA_TRUST_CLASSES_ORDERED,
    )
    return CodingExternalDataProductCompilation(
        product_composition=composition,
        selected_manifests=selected,
        resource_bodies=_resource_bodies(None, composition, external_selected=selected),
    )


__all__ = [
    "CodingExternalDataProductCompilation",
    "compile_coding_external_data_product_selection",
]
