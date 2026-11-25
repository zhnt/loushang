"""Product-selected data Resources whose composition does not require coding.base."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding.composition.base_product import (
    _EXTERNAL_DATA_RESOURCES,
    CodingBaseProductCompilation,
    CodingBaseProductResourceBody,
    extend_coding_base_product_data_resources,
)
from loushang.coding.composition.base_product import (
    _resource_bodies as _resource_bodies,
)
from loushang.coding.composition.plan import CODING_PRODUCT_ID
from loushang.coding.composition.sets import CodingCompositionSetPlan
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
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
from loushang.harness.session.product_composition_assembly import (
    StandaloneProductDataSelection,
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
    _, composition, _ = _EXTERNAL_DATA_RESOURCES.compile(
        selected,
        lambda: StandaloneProductDataSelection(
            product_id=CODING_PRODUCT_ID,
            scope_id=f"session:{session_id.strip()}",
            policy_revision_prefix=(
                f"coding-external-data-v1:{composition_set.set_id}:{composition_set.fingerprint}"
            ),
        ),
        standalone=True,
        evaluated_at=evaluated_at,
    )
    return CodingExternalDataProductCompilation(
        product_composition=composition,
        selected_manifests=selected,
        resource_bodies=_resource_bodies(None, composition, external_selected=selected),
    )


def compile_coding_selected_data_resources(
    base: CodingBaseProductCompilation | None,
    selected: tuple[PackageProductSelectedPluginManifestV1, ...],
    evaluated_at: int,
    *,
    composition_set: CodingCompositionSetPlan,
    session_id: str,
) -> tuple[CodingBaseProductCompilation | None, CodingExternalDataProductCompilation | None]:
    if base is not None:
        return extend_coding_base_product_data_resources(
            base, selected, evaluated_at=evaluated_at
        ), None
    return None, compile_coding_external_data_product_selection(
        selected,
        composition_set=composition_set,
        session_id=session_id,
        evaluated_at=evaluated_at,
    )


__all__ = [
    "CodingExternalDataProductCompilation",
    "compile_coding_external_data_product_selection",
]
