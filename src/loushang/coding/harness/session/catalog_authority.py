"""Recheck the Package Product evidence retained by a resource catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loushang.harness.package_product.product_runtime import (
    PackageProductPluginDesiredSelectionV1,
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)

from .catalog_preparation import _AdmissionFailure, require_current_manifests

if TYPE_CHECKING:
    from loushang.coding.composition.base_product import CodingBaseProductCompilation
    from loushang.coding.composition.external_data import (
        CodingExternalDataProductCompilation,
    )


@dataclass(frozen=True, slots=True)
class CatalogProductAuthority:
    runtime: PackageProductRuntimeBindingV1 | None
    capability_selections: tuple[PackageProductPluginDesiredSelectionV1, ...]
    disabled_base: PackageProductPluginDesiredSelectionV1 | None
    external: CodingExternalDataProductCompilation | None
    base: CodingBaseProductCompilation | None
    product_label: str

    def _require_runtime(self, role: str) -> PackageProductRuntimeBindingV1:
        if self.runtime is None:
            raise RuntimeError(f"{self.product_label} {role} runtime is unavailable")
        return self.runtime

    def require_current(
        self, *, refresh_failure: _AdmissionFailure | None = None
    ) -> None:
        """Check admission evidence, with additional membership checks on refresh."""
        if self.capability_selections:
            runtime = self._require_runtime("Capability")
            try:
                for selection in self.capability_selections:
                    runtime.assert_plugin_desired_selection_current(selection)
            except (
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
            ) as exc:
                if refresh_failure is None:
                    raise
                raise refresh_failure(
                    ("product_capability_selection_refresh_requires_restart",)
                ) from exc
        if self.disabled_base is not None:
            runtime = self._require_runtime("disabled-base")
            try:
                runtime.assert_plugin_desired_selection_current(self.disabled_base)
                if refresh_failure is not None:
                    current_ids = runtime.selected_external_data_plugin_ids()
                    if current_ids != (
                        tuple(
                            item.manifest.name
                            for item in self.external.selected_manifests
                        )
                        if self.external is not None
                        else ()
                    ):
                        raise RuntimeError("Product external data selection changed")
                if self.external is not None:
                    self.external.assert_current(runtime)
            except RuntimeError as exc:
                if refresh_failure is None:
                    raise
                raise refresh_failure(
                    ("product_disabled_base_refresh_requires_restart",)
                ) from exc
        if self.base is not None and refresh_failure is not None:
            runtime = self._require_runtime("base")
            require_current_manifests(
                runtime,
                (self.base.selected_manifest,),
                "product_selected_base_refresh_requires_restart",
                refresh_failure,
            )
            require_current_manifests(
                runtime,
                self.base.selected_capability_manifests,
                "product_selected_capability_refresh_requires_restart",
                refresh_failure,
            )
            require_current_manifests(
                runtime,
                self.base.selected_external_data_manifests,
                "product_selected_resource_refresh_requires_restart",
                refresh_failure,
            )
