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
from loushang.coding.composition.plan import CODING_PRODUCT_ID
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
    PreparationRootCustody,
    require_catalog_receipt,
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
    from loushang.harness.resource_catalog.product_snapshot_source import (
        ProductSelectedResourceInput,
    )
    from loushang.harness.resource_catalog.session_bootstrap import (
        InitialSessionResourceCatalogBootstrap,
    )
    from loushang.harness.resources.types import ResourceBundle
    from loushang.harness.session.bootstrap_services import BootstrapServices


def prepare_coding_catalog_projection(
    resource_loader: ResourceLoader,
    *,
    cwd: Path,
    session_id: str,
    disabled_skills: tuple[str, ...] | list[str] = (),
    product_composition: ProductCompositionCompilation | None = None,
    product_snapshot_resources: tuple[ProductSelectedResourceInput, ...] | None = None,
    admission_now: int | None = None,
    clock: Callable[[], int] | None = None,
    receipt: ResourceCatalogInputReceipt | None = None,
    source_policy: CodingResourceCatalogSourcePolicy = (
        CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
    ),
) -> tuple[InitialResourceCatalogProductAdapter, ResourceBundle]:
    """Prepare one Catalog adapter and its disposable bootstrap projection."""

    evaluated_at = int(time.time()) if admission_now is None else admission_now
    resolved_receipt = require_catalog_receipt(
        resource_loader, cwd, CodingResourceCatalogAdmissionError, receipt
    )
    adapter = build_coding_initial_resource_catalog_adapter(
        resolved_receipt,
        product_scope_id=session_id,
        disabled_skills=disabled_skills,
        product_composition=product_composition,
        product_snapshot_resources=product_snapshot_resources,
        package_admission_now=evaluated_at,
        clock=clock,
        source_policy=source_policy,
    )
    bundle = adapter.prepare_bootstrap_projection(
        product_id=CODING_PRODUCT_ID,
        session_id=session_id,
        cwd=cwd,
    )
    return adapter, bundle


@dataclass(slots=True)
class InitialCatalogHandoff:
    """Keep startup Catalog projection and its Session intake in one place."""

    services: BootstrapServices
    session_id: str
    custody: PreparationRootCustody[CodingCapabilityPluginCompositionPreparation]
    source_policy: CodingResourceCatalogSourcePolicy
    selection: ProductCatalogSelection = field(
        default_factory=ProductCatalogSelection, init=False
    )
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
    _adapter: InitialResourceCatalogProductAdapter | None = field(
        default=None, init=False
    )

    def require_unprepared(self, error: str) -> None:
        if self._adapter is not None:
            raise RuntimeError(error)

    def take_adapter(self) -> InitialResourceCatalogProductAdapter:
        adapter = self._adapter
        if adapter is None:
            raise RuntimeError(
                "Initial Resource Catalog projection adapter is unavailable"
            )
        self._adapter = None
        return adapter

    def record_admission_failure(
        self, error: CodingResourceCatalogAdmissionError
    ) -> None:
        self.services.diagnostics_service.capture_failure(
            code=error.code,
            error=str(error),
            phase="startup",
            source="bootstrap",
            session_id=self.session_id,
            details={"reasons": list(error.reasons)},
        )

    def prepare_legacy_projection(
        self,
        loader: ResourceLoader,
        *,
        cwd: Path,
        base: CodingBasePluginAssembly | None,
        supplied: ProductCompositionAssemblyRequest | None,
        include_configured: bool,
        prepare_capabilities: Callable[
            [ProductPluginPlanSeed | None],
            CodingCapabilityPluginCompositionPreparation | None,
        ]
        | None,
        reconcile_compatibility: Callable[[], None],
        clock: Callable[[], int] | None,
    ) -> ResourceBundle:
        receipt = require_catalog_receipt(
            loader, cwd, CodingResourceCatalogAdmissionError
        )
        evaluated_at = clock() if clock is not None else int(time.time())
        composition, self.legacy_preparation = prepare_initial_composition(
            receipt,
            session_id=self.session_id,
            evaluated_at=evaluated_at,
            base=base,
            supplied=supplied,
            include_configured=include_configured,
            custody=self.custody,
            prepare_capabilities=prepare_capabilities,
        )
        reconcile_compatibility()
        adapter, projection = prepare_coding_catalog_projection(
            loader,
            cwd=cwd,
            session_id=self.session_id,
            disabled_skills=self.services.settings_manager.get_settings().disabled_skills,
            product_composition=composition,
            admission_now=(
                evaluated_at
                if composition is None
                else composition.authority_context.evaluated_at
            ),
            clock=clock,
            receipt=receipt,
            source_policy=self.source_policy,
        )
        self._adapter = adapter
        return projection

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
        clock: Callable[[], int],
        compile_base: Callable[
            [PackageProductSelectedPluginManifestV1, int], CodingBaseProductCompilation
        ],
        prepare_capability_inputs: Callable[
            [list[str]], tuple[Path, Mapping[str, CodingCapabilityPluginConfig]]
        ],
        resume_parents: CodingResumePluginParents | None,
    ) -> ResourceBundle:
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
                    session_id=self.session_id,
                    evaluated_at=clock(),
                )
        else:
            (selected,) = capture_manifests((CODING_BASE_PLUGIN_ID,))
            evaluated_at = clock()
            base = compile_base(selected, evaluated_at)
            receipt = require_catalog_receipt(
                loader, cwd, CodingResourceCatalogAdmissionError
            )

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
                            session_id=self.session_id,
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
                        session_id=self.session_id,
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
            receipt = require_catalog_receipt(
                loader, cwd, CodingResourceCatalogAdmissionError
            )
        disabled_composition = (
            self._disabled_composition(external) if base is None else None
        )
        adapter, projection = prepare_coding_catalog_projection(
            loader,
            cwd=cwd,
            session_id=self.session_id,
            disabled_skills=self.services.settings_manager.get_settings().disabled_skills,
            product_composition=(
                base.product_composition if base is not None else disabled_composition
            ),
            product_snapshot_resources=self._snapshot_resources(
                base, external, allow_empty_snapshot=disabled_composition is not None
            ),
            admission_now=evaluated_at if base is not None else clock(),
            clock=clock,
            receipt=receipt,
            source_policy=(
                self.source_policy
                if base is not None
                else CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
                if disabled_composition is not None
                else CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
            ),
        )
        self.selection = ProductCatalogSelection(
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
        self._adapter = adapter
        return projection

    def prepare_refresh(
        self,
        catalog_generation: int,
        *,
        get_cwd: Callable[[], str],
        base: CodingBasePluginAssembly | None,
        supplied: ProductCompositionAssemblyRequest | None,
        include_configured: bool,
        clock: Callable[[], int],
    ) -> InitialSessionResourceCatalogBootstrap:
        """Refresh the Catalog over the original selected composition and receipt."""
        self.selection.require_current(
            product_label="Coding", refresh_failure=CodingResourceCatalogAdmissionError
        )
        cwd = Path(get_cwd())
        receipt = require_catalog_receipt(
            self.services.resource_loader, cwd, CodingResourceCatalogAdmissionError
        )
        compiled = self.base
        disabled_base = self.selection.disabled_base is not None
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
            composition = _prepare_legacy_refresh_composition(
                receipt,
                session_id=self.session_id,
                evaluated_at=evaluated_at,
                base=base,
                supplied=supplied,
                include_configured=include_configured,
                require_resource_seed=self.source_policy.include_package_resources,
            )
        adapter, bundle = prepare_coding_catalog_projection(
            self.services.resource_loader,
            cwd=cwd,
            session_id=self.session_id,
            disabled_skills=self.services.settings_manager.get_settings().disabled_skills,
            product_composition=composition,
            product_snapshot_resources=self._snapshot_resources(
                compiled,
                self.external,
                allow_empty_snapshot=disabled_base and composition is not None,
            ),
            admission_now=evaluated_at,
            clock=(
                clock
                if base is not None or compiled is not None or disabled_base
                else None
            ),
            receipt=receipt,
            source_policy=(
                CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
                if disabled_base and composition is None
                else self.source_policy
            ),
        )
        return adapter.prepare_session_bootstrap(
            product_id=CODING_PRODUCT_ID,
            session_id=self.session_id,
            base_resource_bundle=bundle,
            catalog_generation=catalog_generation,
        )

    def _disabled_composition(
        self, external: CodingExternalDataProductCompilation | None
    ) -> ProductCompositionCompilation | None:
        if external is not None:
            return external.product_composition
        preparation = self.custody.preparation
        return preparation.product_composition if preparation is not None else None

    @staticmethod
    def _snapshot_resources(
        base: CodingBaseProductCompilation | None,
        external: CodingExternalDataProductCompilation | None,
        *,
        allow_empty_snapshot: bool,
    ) -> tuple[ProductSelectedResourceInput, ...] | None:
        if base is not None:
            return base.product_resource_inputs()
        if external is not None:
            return external.product_resource_inputs()
        return () if allow_empty_snapshot else None


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
        raise CodingResourceCatalogAdmissionError(("product_selected_package_missing",))
    if supplied is not None:
        if prepare_capabilities is not None:
            raise CodingResourceCatalogAdmissionError(("peer_product_compilation",))
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


def _prepare_legacy_refresh_composition(
    receipt: ResourceCatalogInputReceipt,
    *,
    session_id: str,
    evaluated_at: int,
    base: CodingBasePluginAssembly | None,
    supplied: ProductCompositionAssemblyRequest | None,
    include_configured: bool,
    require_resource_seed: bool,
) -> ProductCompositionCompilation | None:
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
        raise CodingResourceCatalogAdmissionError(("product_selected_package_missing",))
    return None
