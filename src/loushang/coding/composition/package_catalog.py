"""Prepare Coding’s initial Catalog and recheck its admission evidence on refresh."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from loushang.coding.composition.base_plugin import (
    CodingBasePluginAssembly,
    CodingBasePluginSessionPreparation,
    prepare_coding_base_plugin_session,
    prepare_coding_base_resource_plan_seed,
)
from loushang.coding.composition.base_product import (
    CODING_BASE_PLUGIN_ID,
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
    CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
    CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY,
    CodingResourceCatalogAdmissionError,
    CodingResourceCatalogSourcePolicy,
    build_coding_initial_resource_catalog_adapter,
    finalize_coding_package_plugin_plan_seed,
    prepare_coding_package_plugin_plan_seed,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionCompilation,
)
from loushang.harness.package_product._selected_plugin_revisions import (
    ProductCatalogSelection,
    capture_catalog_base_selection,
    capture_selected_manifests,
    observe_requested_plugins,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.session.bootstrap_construction import (
    SessionStartupCustody,
)
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyRequest,
    ProductPluginPlanSeed,
    assemble_product_composition,
)

if TYPE_CHECKING:
    from loushang.coding.composition.capability_specs import (
        CodingCapabilityPluginConfig,
    )
    from loushang.harness.resource_catalog.product_inputs import (
        InitialResourceCatalogProductAdapter,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.session.bootstrap_services import BootstrapServices


@dataclass(slots=True)
class InitialCatalogHandoff:
    """Keep startup Catalog projection and its Session intake in one place."""

    services: BootstrapServices
    custody: SessionStartupCustody[CodingCapabilityPluginCompositionPreparation]
    source_policy: CodingResourceCatalogSourcePolicy
    base_assembly: CodingBasePluginAssembly | None
    supplied: ProductCompositionAssemblyRequest | None
    include_configured: bool
    clock: Callable[[], int]
    base: CodingBaseProductCompilation | None = field(default=None, init=False)
    external: CodingExternalDataProductCompilation | None = field(
        default=None, init=False
    )
    legacy_preparation: CodingBasePluginSessionPreparation | None = field(
        default=None, init=False
    )
    builtin_preparation: CodingBuiltinProductCompositionPreparation | None = field(
        default=None, init=False
    )

    def record_admission_failure(
        self, error: CodingResourceCatalogAdmissionError
    ) -> None:
        self.services.diagnostics_service.capture_failure(
            code=error.code,
            error=str(error),
            phase="startup",
            source="bootstrap",
            session_id=self.custody.session_id,
            details={"reasons": list(error.reasons)},
        )

    def prepare_legacy_projection(
        self,
        loader: ResourceLoader,
        *,
        cwd: Path,
        prepare_capabilities: Callable[
            [ProductPluginPlanSeed | None],
            CodingCapabilityPluginCompositionPreparation | None,
        ]
        | None,
        reconcile_compatibility: Callable[[], None],
        use_plugin_clock: bool,
    ) -> ResourceBundle:
        receipt = self.custody.require_catalog_input(loader, cwd)
        clock = self.clock if use_plugin_clock else None
        evaluated_at = clock() if clock is not None else int(time.time())
        composition, self.legacy_preparation = self._prepare_legacy_composition(
            receipt, evaluated_at, prepare_capabilities
        )
        reconcile_compatibility()
        return self.custody.prepare_initial_catalog(
            self._build_catalog_adapter(
                receipt,
                composition=composition,
                evaluated_at=(
                    evaluated_at
                    if composition is None
                    else composition.authority_context.evaluated_at
                ),
                clock=clock,
            ),
            cwd=cwd,
        )

    def prepare_fenced_projection(
        self,
        runtime: PackageProductRuntimeBindingV1,
        loader: ResourceLoader,
        *,
        cwd: Path,
        composition_set: CodingCompositionSetPlan,
        requested_capabilities: tuple[tuple[str, bool], ...],
        max_files: int,
        max_total_bytes: int,
        compile_base: Callable[
            [PackageProductSelectedPluginManifestV1, int], CodingBaseProductCompilation
        ],
        prepare_capability_inputs: Callable[
            [list[str]], tuple[Path, Mapping[str, CodingCapabilityPluginConfig]]
        ],
        resume_parents: CodingResumePluginParents | None,
    ) -> ResourceBundle:
        clock = self.clock
        disabled_base = capture_catalog_base_selection(
            runtime, CODING_BASE_PLUGIN_ID, CodingResourceCatalogAdmissionError
        )
        capture_manifests = partial(
            capture_selected_manifests,
            runtime.capture_selected_plugin_manifest_for,
            max_files=max_files,
            max_total_bytes=max_total_bytes,
        )
        external = None
        base = None
        receipt = None
        evaluated_at = None
        if disabled_base is not None:
            external_ids = runtime.selected_external_data_plugin_ids()
            if external_ids:
                external = compile_coding_external_data_product_selection(
                    capture_manifests(external_ids),
                    composition_set=composition_set,
                    session_id=self.custody.session_id,
                    evaluated_at=clock(),
                )
        else:
            (selected,) = capture_manifests((CODING_BASE_PLUGIN_ID,))
            evaluated_at = clock()
            base = compile_base(selected, evaluated_at)
            receipt = self.custody.require_catalog_input(loader, cwd)

        enabled, selections = observe_requested_plugins(
            runtime, requested_capabilities, CodingResourceCatalogAdmissionError
        )
        builtin = None
        if enabled:
            state_root, configurations = prepare_capability_inputs(enabled)
            if base is None:
                try:
                    self.custody.preparation = (
                        prepare_coding_product_capability_plugin_composition(
                            runtime,
                            session_id=self.custody.session_id,
                            configurations=configurations,
                            state_root=state_root,
                            clock=clock,
                            resume_parents=resume_parents,
                        )
                    )
                except BaseException:
                    self.custody.cleanup_roots_sequentially()
                    raise
            else:
                try:
                    builtin = prepare_coding_builtin_product_composition(
                        runtime,
                        base_compilation=base,
                        session_id=self.custody.session_id,
                        configurations=configurations,
                        external_data_plugin_ids=runtime.selected_external_data_plugin_ids(),
                        state_root=state_root,
                        clock=clock,
                        resume_parents=resume_parents,
                    )
                except BaseException as error:
                    self.custody.cleanup_roots_with_notes(
                        error,
                        state_label="Coding Product Capability state cleanup",
                        private_label="Coding Product Arch private-state cleanup",
                    )
                    raise
                self.custody.preparation = builtin.capability_preparation
            self.custody.attach_cleanup(self.custody.preparation)
            if builtin is not None:
                base = builtin.base_compilation
        elif resume_parents is not None:
            raise CodingResourceCatalogAdmissionError(
                ("resume_plugin_participation_changed",)
            )
        elif base is not None:
            assert evaluated_at is not None
            external_ids = runtime.selected_external_data_plugin_ids()
            if external_ids:
                base = extend_coding_base_product_data_resources(
                    base,
                    capture_manifests(external_ids),
                    evaluated_at=evaluated_at,
                )
        if receipt is None:
            receipt = self.custody.require_catalog_input(loader, cwd)
        disabled_composition = (
            self._disabled_composition(external) if base is None else None
        )
        bundle = self.custody.prepare_initial_catalog(
            self._build_catalog_adapter(
                receipt,
                composition=base.product_composition if base is not None else disabled_composition,
                snapshot=base if base is not None else external,
                empty_snapshot=disabled_composition is not None,
                evaluated_at=evaluated_at if base is not None else None,
                clock=clock,
                source_policy=(
                    self.source_policy
                    if base is not None
                    else CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
                    if disabled_composition is not None
                    else CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
                ),
            ),
            cwd=cwd,
        )
        self.custody.catalog_selection = ProductCatalogSelection(
            runtime=runtime,
            capability_selections=selections,
            disabled_base=disabled_base,
            base=base.selected_manifest if base is not None else None,
            capabilities=base.selected_capability_manifests if base is not None else (),
            external=(
                base.selected_external_data_manifests
                if base is not None
                else external.selected_manifests if external is not None else ()
            ),
        )
        self.base = base
        self.external = external
        self.builtin_preparation = builtin
        return bundle

    def build_refresh_adapter(
        self,
        receipt: ResourceCatalogInputReceipt,
    ) -> InitialResourceCatalogProductAdapter:
        base, clock = self.base_assembly, self.clock
        compiled = self.base
        disabled_base = self.custody.catalog_selection.disabled_base is not None
        evaluated_at = (
            compiled.product_composition.authority_context.evaluated_at
            if compiled is not None
            else clock()
            if base is not None
            else int(time.time())
        )
        composition: ProductCompositionCompilation | None
        if compiled is not None:
            composition = compiled.product_composition
        elif disabled_base:
            composition = self._disabled_composition(self.external)
        else:
            composition = self._refresh_legacy_composition(receipt, evaluated_at)
        return self._build_catalog_adapter(
            receipt,
            composition=composition,
            snapshot=compiled if compiled is not None else self.external,
            empty_snapshot=disabled_base and composition is not None,
            evaluated_at=evaluated_at,
            clock=clock if base is not None or compiled is not None or disabled_base else None,
            source_policy=(
                CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
                if disabled_base and composition is None
                else self.source_policy
            ),
        )

    def _build_catalog_adapter(
        self,
        receipt: ResourceCatalogInputReceipt,
        *,
        composition: ProductCompositionCompilation | None,
        evaluated_at: int | None,
        clock: Callable[[], int] | None,
        snapshot: CodingBaseProductCompilation | CodingExternalDataProductCompilation | None = None,
        empty_snapshot: bool = False,
        source_policy: CodingResourceCatalogSourcePolicy | None = None,
    ) -> InitialResourceCatalogProductAdapter:
        disabled_skills = self.services.settings_manager.get_settings().disabled_skills
        resources = snapshot.product_resource_inputs() if snapshot is not None else (
            () if empty_snapshot else None
        )
        if evaluated_at is None:
            evaluated_at = clock() if clock is not None else int(time.time())
        return build_coding_initial_resource_catalog_adapter(
            receipt,
            product_scope_id=self.custody.session_id,
            disabled_skills=disabled_skills,
            product_composition=composition,
            product_snapshot_resources=resources,
            package_admission_now=evaluated_at,
            clock=clock,
            source_policy=self.source_policy if source_policy is None else source_policy,
        )

    def _disabled_composition(
        self, external: CodingExternalDataProductCompilation | None
    ) -> ProductCompositionCompilation | None:
        if external is not None:
            return external.product_composition
        preparation = self.custody.preparation
        return preparation.product_composition if preparation is not None else None

    def _legacy_plan_seed(
        self,
        receipt: ResourceCatalogInputReceipt,
        evaluated_at: int,
        base_seed: ProductPluginPlanSeed | None,
    ) -> ProductPluginPlanSeed | None:
        return prepare_coding_package_plugin_plan_seed(
            receipt,
            product_scope_id=self.custody.session_id,
            evaluated_at=evaluated_at,
            plan_seed=base_seed,
            include_configured_resource_plugins=self.include_configured,
        )

    def _prepare_legacy_composition(
        self,
        receipt: ResourceCatalogInputReceipt,
        evaluated_at: int,
        prepare_capabilities: Callable[
            [ProductPluginPlanSeed | None],
            CodingCapabilityPluginCompositionPreparation | None,
        ] | None,
    ) -> tuple[ProductCompositionCompilation | None, CodingBasePluginSessionPreparation | None]:
        base = self.base_assembly
        seed = self._legacy_plan_seed(
            receipt, evaluated_at, base.plan_seed if base is not None else None
        )
        if base is not None and seed is None:
            raise CodingResourceCatalogAdmissionError(("product_selected_package_missing",))
        if self.supplied is not None:
            if prepare_capabilities is not None:
                raise CodingResourceCatalogAdmissionError(("peer_product_compilation",))
            return assemble_product_composition(self.supplied, evaluated_at=evaluated_at), None
        if prepare_capabilities is not None:
            self.custody.preparation = prepare_capabilities(seed)
            if self.custody.preparation is not None:
                return self.custody.preparation.product_composition, None
        if base is None:
            return None, None
        assert seed is not None
        prepared = _bind_base_catalog_plan(base, seed, evaluated_at)
        return prepared.product_composition, prepared

    def _refresh_legacy_composition(
        self, receipt: ResourceCatalogInputReceipt, evaluated_at: int
    ) -> ProductCompositionCompilation | None:
        base = self.base_assembly
        if base is None:
            return (
                assemble_product_composition(self.supplied, evaluated_at=evaluated_at)
                if self.supplied is not None
                else None
            )
        base_seed = prepare_coding_base_resource_plan_seed(base)
        if base_seed is not None:
            seed = self._legacy_plan_seed(receipt, evaluated_at, base_seed)
            if seed is not None:
                return _bind_base_catalog_plan(base, seed, evaluated_at).product_composition
        if self.source_policy.include_package_resources:
            raise CodingResourceCatalogAdmissionError(("product_selected_package_missing",))
        return None


def _bind_base_catalog_plan(
    base: CodingBasePluginAssembly, seed: ProductPluginPlanSeed, evaluated_at: int
) -> CodingBasePluginSessionPreparation:
    return prepare_coding_base_plugin_session(
        base,
        evaluated_at=evaluated_at,
        selection_seed=finalize_coding_package_plugin_plan_seed(seed),
    )
