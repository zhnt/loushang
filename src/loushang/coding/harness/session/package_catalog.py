"""Prepare and recheck the selected Package Product catalog evidence."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.coding.composition.base_plugin import (
    CodingBasePluginAssembly,
    CodingBasePluginSessionPreparation,
    prepare_coding_base_plugin_session,
    prepare_coding_base_resource_plan_seed,
)
from loushang.coding.composition.base_product import (
    CodingBaseProductCompilation,
    extend_coding_base_product_data_resources,
)
from loushang.coding.composition.capability_plugins import (
    CodingCapabilityPluginCompositionPreparation,
    CodingResumePluginParents,
)
from loushang.coding.composition.external_data import (
    CodingExternalDataProductCompilation,
    compile_coding_external_data_product_selection,
)
from loushang.coding.composition.product_capability_plugins import (
    CodingBuiltinProductCompositionPreparation,
    prepare_coding_builtin_product_composition,
    prepare_coding_product_capability_plugin_composition,
)
from loushang.coding.composition.sets import CodingCompositionSetPlan
from loushang.coding.resources.catalog import (
    finalize_coding_package_plugin_plan_seed,
    prepare_coding_package_plugin_plan_seed,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
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
from loushang.harness.session.bootstrap_construction import PreparationRootCustody
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyRequest,
    ProductPluginPlanSeed,
    assemble_product_composition,
)

from .catalog_preparation import (
    _AdmissionFailure,
    capture_selected_manifests,
    observe_requested_plugins,
    require_catalog_receipt,
    require_current_manifests,
)

if TYPE_CHECKING:
    from loushang.coding.composition.capability_specs import (
        CodingCapabilityPluginConfig,
    )
    from loushang.coding.resources.catalog import CodingResourceCatalogSourcePolicy
    from loushang.harness.resource_catalog.product_inputs import (
        InitialResourceCatalogProductAdapter,
    )
    from loushang.harness.resource_catalog.product_snapshot_source import (
        ProductSelectedResourceInput,
    )
    from loushang.harness.resource_catalog.session_bootstrap import (
        InitialSessionResourceCatalogBootstrap,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.session.bootstrap_services import BootstrapServices


@dataclass(frozen=True, slots=True)
class CatalogProductAuthority:
    runtime: PackageProductRuntimeBindingV1 | None
    capability_selections: tuple[PackageProductPluginDesiredSelectionV1, ...]
    disabled_base: PackageProductPluginDesiredSelectionV1 | None
    external: CodingExternalDataProductCompilation | None
    base: CodingBaseProductCompilation | None
    product_label: str

    def disabled_composition(
        self, preparation: CodingCapabilityPluginCompositionPreparation | None
    ) -> ProductCompositionCompilation | None:
        if self.external is not None:
            return self.external.product_composition
        return preparation.product_composition if preparation is not None else None

    def snapshot_resources(
        self, *, allow_empty_snapshot: bool
    ) -> tuple[ProductSelectedResourceInput, ...] | None:
        if self.base is not None:
            return self.base.product_resource_inputs()
        if self.external is not None:
            return self.external.product_resource_inputs()
        return () if allow_empty_snapshot else None

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


@dataclass(frozen=True, slots=True)
class FencedCatalogPreparation:
    authority: CatalogProductAuthority
    receipt: ResourceCatalogInputReceipt
    evaluated_at: int | None
    builtin: CodingBuiltinProductCompositionPreparation | None


def prepare_fenced_catalog(
    runtime: PackageProductRuntimeBindingV1,
    *,
    loader: ResourceLoader,
    cwd: Path,
    session_id: str,
    composition_set: CodingCompositionSetPlan,
    base_plugin_id: str,
    disabled_base: PackageProductPluginDesiredSelectionV1 | None,
    requested_capabilities: tuple[tuple[str, bool], ...],
    max_files: int,
    max_total_bytes: int,
    clock: Callable[[], int],
    compile_base: Callable[
        [PackageProductSelectedPluginManifestV1, int], CodingBaseProductCompilation
    ],
    prepare_capability_inputs: Callable[
        [list[str]], tuple[Path, Mapping[str, CodingCapabilityPluginConfig]]
    ],
    custody: PreparationRootCustody[CodingCapabilityPluginCompositionPreparation],
    resume_parents: CodingResumePluginParents | None,
    admission_failure: _AdmissionFailure,
    product_label: str,
    cleanup_labels: tuple[str, str],
) -> FencedCatalogPreparation:
    external = None
    base = None
    receipt = None
    evaluated_at = None
    if disabled_base is not None:
        external_ids = runtime.selected_external_data_plugin_ids()
        if external_ids:
            external = compile_coding_external_data_product_selection(
                capture_selected_manifests(
                    runtime,
                    external_ids,
                    max_files=max_files,
                    max_total_bytes=max_total_bytes,
                ),
                composition_set=composition_set,
                session_id=session_id,
                evaluated_at=clock(),
            )
    else:
        selected = runtime.capture_selected_plugin_manifest_for(
            base_plugin_id, max_files=max_files, max_total_bytes=max_total_bytes
        )
        evaluated_at = clock()
        base = compile_base(selected, evaluated_at)
        receipt = require_catalog_receipt(loader, cwd, admission_failure)

    enabled, selections = observe_requested_plugins(
        runtime, requested_capabilities, admission_failure
    )
    builtin = None
    if enabled:
        state_root, configurations = prepare_capability_inputs(enabled)
        if base is None:
            try:
                custody.preparation = (
                    prepare_coding_product_capability_plugin_composition(
                        runtime,
                        session_id=session_id,
                        configurations=configurations,
                        state_root=state_root,
                        clock=clock,
                        resume_parents=resume_parents,
                    )
                )
            except BaseException:
                custody.cleanup_roots_sequentially()
                raise
        else:
            try:
                builtin = prepare_coding_builtin_product_composition(
                    runtime,
                    base_compilation=base,
                    session_id=session_id,
                    configurations=configurations,
                    external_data_plugin_ids=runtime.selected_external_data_plugin_ids(),
                    state_root=state_root,
                    clock=clock,
                    resume_parents=resume_parents,
                )
            except BaseException as error:
                custody.cleanup_roots_with_notes(
                    error,
                    state_label=cleanup_labels[0],
                    private_label=cleanup_labels[1],
                )
                raise
            custody.preparation = builtin.capability_preparation
        custody.attach_cleanup(custody.preparation)
        if builtin is not None:
            base = builtin.base_compilation
    elif resume_parents is not None:
        raise admission_failure(("resume_plugin_participation_changed",))
    elif base is not None:
        assert evaluated_at is not None
        external_ids = runtime.selected_external_data_plugin_ids()
        if external_ids:
            base = extend_coding_base_product_data_resources(
                base,
                capture_selected_manifests(
                    runtime,
                    external_ids,
                    max_files=max_files,
                    max_total_bytes=max_total_bytes,
                ),
                evaluated_at=evaluated_at,
            )
    if receipt is None:
        receipt = require_catalog_receipt(loader, cwd, admission_failure)
    return FencedCatalogPreparation(
        CatalogProductAuthority(
            runtime, selections, disabled_base, external, base, product_label
        ),
        receipt,
        evaluated_at,
        builtin,
    )


def _bind_base_catalog_plan(
    base: CodingBasePluginAssembly, seed: ProductPluginPlanSeed, evaluated_at: int
) -> CodingBasePluginSessionPreparation:
    return prepare_coding_base_plugin_session(
        base,
        evaluated_at=evaluated_at,
        selection_seed=finalize_coding_package_plugin_plan_seed(seed),
    )


def prepare_initial_composition(
    receipt: ResourceCatalogInputReceipt,
    *,
    session_id: str,
    evaluated_at: int,
    base: CodingBasePluginAssembly | None,
    supplied: ProductCompositionAssemblyRequest | None,
    include_configured: bool,
    custody: PreparationRootCustody[CodingCapabilityPluginCompositionPreparation],
    prepare_capabilities: Callable[
        [ProductPluginPlanSeed | None],
        CodingCapabilityPluginCompositionPreparation | None,
    ]
    | None,
    admission_failure: _AdmissionFailure,
) -> tuple[
    ProductCompositionCompilation | None, CodingBasePluginSessionPreparation | None
]:
    seed = prepare_coding_package_plugin_plan_seed(
        receipt,
        product_scope_id=session_id,
        evaluated_at=evaluated_at,
        plan_seed=base.plan_seed if base is not None else None,
        include_configured_resource_plugins=include_configured,
    )
    if base is not None and seed is None:
        raise admission_failure(("product_selected_package_missing",))
    if supplied is not None:
        if prepare_capabilities is not None:
            raise admission_failure(("peer_product_compilation",))
        return assemble_product_composition(supplied, evaluated_at=evaluated_at), None
    if prepare_capabilities is not None:
        custody.preparation = prepare_capabilities(seed)
        if custody.preparation is not None:
            return custody.preparation.product_composition, None
    if base is None:
        return None, None
    assert seed is not None
    prepared = _bind_base_catalog_plan(base, seed, evaluated_at)
    return prepared.product_composition, prepared


def prepare_refresh_composition(
    receipt: ResourceCatalogInputReceipt,
    *,
    session_id: str,
    evaluated_at: int,
    authority: CatalogProductAuthority,
    base: CodingBasePluginAssembly | None,
    supplied: ProductCompositionAssemblyRequest | None,
    preparation: CodingCapabilityPluginCompositionPreparation | None,
    include_configured: bool,
    require_resource_seed: bool,
    admission_failure: _AdmissionFailure,
) -> ProductCompositionCompilation | None:
    if authority.base is not None:
        return authority.base.product_composition
    if authority.disabled_base is not None:
        return authority.disabled_composition(preparation)
    if base is None:
        return (
            assemble_product_composition(supplied, evaluated_at=evaluated_at)
            if supplied is not None
            else None
        )
    resource_seed = prepare_coding_base_resource_plan_seed(base)
    seed = (
        prepare_coding_package_plugin_plan_seed(
            receipt,
            product_scope_id=session_id,
            evaluated_at=evaluated_at,
            plan_seed=resource_seed,
            include_configured_resource_plugins=include_configured,
        )
        if resource_seed is not None
        else None
    )
    if seed is not None:
        return _bind_base_catalog_plan(base, seed, evaluated_at).product_composition
    if require_resource_seed:
        raise admission_failure(("product_selected_package_missing",))
    return None


def prepare_catalog_refresh(
    services: BootstrapServices,
    *,
    get_cwd: Callable[[], str],
    session_id: str,
    product_id: str,
    catalog_generation: int,
    authority: CatalogProductAuthority,
    base: CodingBasePluginAssembly | None,
    supplied: ProductCompositionAssemblyRequest | None,
    custody: PreparationRootCustody[CodingCapabilityPluginCompositionPreparation],
    include_configured: bool,
    source_policy: CodingResourceCatalogSourcePolicy,
    disabled_source_policy: CodingResourceCatalogSourcePolicy,
    clock: Callable[[], int],
    project_catalog: Callable[
        ..., tuple[InitialResourceCatalogProductAdapter, ResourceBundle]
    ],
    admission_failure: _AdmissionFailure,
) -> InitialSessionResourceCatalogBootstrap:
    """Refresh the Catalog over the original selected composition and receipt."""
    authority.require_current(refresh_failure=admission_failure)
    cwd = Path(get_cwd())
    receipt = require_catalog_receipt(services.resource_loader, cwd, admission_failure)
    compiled = authority.base
    disabled_base = authority.disabled_base is not None
    evaluated_at = (
        compiled.product_composition.authority_context.evaluated_at
        if compiled is not None
        else clock()
        if base is not None
        else int(time.time())
    )
    composition = prepare_refresh_composition(
        receipt,
        session_id=session_id,
        evaluated_at=evaluated_at,
        authority=authority,
        base=base,
        supplied=supplied,
        preparation=custody.preparation,
        include_configured=include_configured,
        require_resource_seed=source_policy.include_package_resources,
        admission_failure=admission_failure,
    )
    adapter, bundle = project_catalog(
        services.resource_loader,
        cwd=cwd,
        session_id=session_id,
        disabled_skills=services.settings_manager.get_settings().disabled_skills,
        product_composition=composition,
        product_snapshot_resources=authority.snapshot_resources(
            allow_empty_snapshot=disabled_base and composition is not None
        ),
        admission_now=evaluated_at,
        clock=(
            clock if base is not None or compiled is not None or disabled_base else None
        ),
        receipt=receipt,
        source_policy=(
            disabled_source_policy
            if disabled_base and composition is None
            else source_policy
        ),
    )
    return adapter.prepare_session_bootstrap(
        product_id=product_id,
        session_id=session_id,
        base_resource_bundle=bundle,
        catalog_generation=catalog_generation,
    )
