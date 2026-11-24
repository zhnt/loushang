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
)
from loushang.coding.composition.capability_plugins import (
    CodingCapabilityPluginCompositionPreparation,
    CodingResumePluginParents,
)
from loushang.coding.composition.external_data import (
    CodingExternalDataProductCompilation,
    compile_coding_selected_data_resources,
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


@dataclass(slots=True, kw_only=True)
class InitialCatalogHandoff(
    SessionStartupCustody[CodingCapabilityPluginCompositionPreparation]
):
    """Keep startup Catalog projection and its Session intake in one place."""

    services: BootstrapServices
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
            session_id=self.session_id,
            details={"reasons": list(error.reasons)},
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
        builtin = None

        def prepare_capabilities(
            base: CodingBaseProductCompilation | None, enabled: list[str]
        ) -> tuple[CodingBaseProductCompilation | None, CodingCapabilityPluginCompositionPreparation]:
            nonlocal builtin
            state_root, configurations = prepare_capability_inputs(enabled)
            if base is None:
                try:
                    return None, prepare_coding_product_capability_plugin_composition(
                        runtime,
                        session_id=self.session_id,
                        configurations=configurations,
                        state_root=state_root,
                        clock=self.clock,
                        resume_parents=resume_parents,
                    )
                except BaseException:
                    self.cleanup_roots_sequentially()
                    raise
            try:
                builtin = prepare_coding_builtin_product_composition(
                    runtime,
                    base_compilation=base,
                    session_id=self.session_id,
                    configurations=configurations,
                    external_data_plugin_ids=runtime.selected_external_data_plugin_ids(),
                    state_root=state_root,
                    clock=self.clock,
                    resume_parents=resume_parents,
                )
            except BaseException as error:
                self.cleanup_roots_with_notes(
                    error,
                    state_label="Coding Product Capability state cleanup",
                    private_label="Coding Product Arch private-state cleanup",
                )
                raise
            return builtin.base_compilation, builtin.capability_preparation

        bundle, self.base, self.external = self.prepare_fenced_catalog(
            runtime, loader, cwd=cwd,
            base_plugin_id=CODING_BASE_PLUGIN_ID,
            capability_requests=requested_capabilities,
            require_capabilities=resume_parents is not None,
            max_files=max_files,
            max_total_bytes=max_total_bytes,
            clock=self.clock,
            compile_base=compile_base,
            compile_data=partial(
                compile_coding_selected_data_resources,
                composition_set=composition_set, session_id=self.session_id,
            ),
            prepare_capabilities=prepare_capabilities,
            build_adapter=partial(
                self._build_fenced_catalog_adapter,
                enabled_data_policy=CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY,
            ),
        )
        self.builtin_preparation = builtin
        return bundle

    def build_refresh_adapter(
        self,
        receipt: ResourceCatalogInputReceipt,
    ) -> InitialResourceCatalogProductAdapter:
        base, clock = self.base_assembly, self.clock
        compiled = self.base
        disabled_base = self.catalog_selection.disabled_base is not None
        evaluated_at = (
            compiled.product_composition.authority_context.evaluated_at
            if compiled is not None
            else clock()
            if base is not None
            else int(time.time())
        )
        if compiled is not None or disabled_base:
            return self._build_fenced_catalog_adapter(
                receipt, compiled, self.external, evaluated_at
            )
        return self.build_adapter(
            receipt,
            composition=self._refresh_legacy_composition(receipt, evaluated_at),
            evaluated_at=evaluated_at,
            clock=clock if base is not None else None,
        )

    def _build_fenced_catalog_adapter(
        self,
        receipt: ResourceCatalogInputReceipt,
        base: CodingBaseProductCompilation | None,
        external: CodingExternalDataProductCompilation | None,
        evaluated_at: int | None,
        *,
        enabled_data_policy: CodingResourceCatalogSourcePolicy | None = None,
    ) -> InitialResourceCatalogProductAdapter:
        disabled_composition = self._disabled_composition(external) if base is None else None
        policy = self.source_policy
        if base is None:
            policy = (
                (enabled_data_policy or self.source_policy)
                if disabled_composition is not None
                else CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
            )
        return self.build_adapter(
            receipt,
            composition=base.product_composition if base is not None else disabled_composition,
            snapshot=base if base is not None else external,
            empty_snapshot=disabled_composition is not None,
            evaluated_at=evaluated_at,
            clock=self.clock,
            source_policy=policy,
        )

    def build_adapter(
        self,
        receipt: ResourceCatalogInputReceipt,
        composition: ProductCompositionCompilation | None,
        evaluated_at: int | None,
        *,
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
            product_scope_id=self.session_id,
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
        preparation = self.preparation
        return preparation.product_composition if preparation is not None else None

    def _legacy_plan_seed(
        self,
        receipt: ResourceCatalogInputReceipt,
        evaluated_at: int,
        base_seed: ProductPluginPlanSeed | None,
    ) -> ProductPluginPlanSeed | None:
        return prepare_coding_package_plugin_plan_seed(
            receipt,
            product_scope_id=self.session_id,
            evaluated_at=evaluated_at,
            plan_seed=base_seed,
            include_configured_resource_plugins=self.include_configured,
        )

    def compile_legacy_composition(
        self,
        receipt: ResourceCatalogInputReceipt,
        evaluated_at: int,
        *,
        prepare_capabilities: Callable[
            [ProductPluginPlanSeed | None],
            CodingCapabilityPluginCompositionPreparation | None,
        ] | None,
    ) -> ProductCompositionCompilation | None:
        base = self.base_assembly
        seed = self._legacy_plan_seed(
            receipt, evaluated_at, base.plan_seed if base is not None else None
        )
        if base is not None and seed is None:
            raise CodingResourceCatalogAdmissionError(("product_selected_package_missing",))
        if self.supplied is not None:
            if prepare_capabilities is not None:
                raise CodingResourceCatalogAdmissionError(("peer_product_compilation",))
            return assemble_product_composition(self.supplied, evaluated_at=evaluated_at)
        if prepare_capabilities is not None:
            self.preparation = prepare_capabilities(seed)
            if self.preparation is not None:
                return self.preparation.product_composition
        if base is None:
            return None
        assert seed is not None
        prepared = _bind_base_catalog_plan(base, seed, evaluated_at)
        composition = prepared.product_composition
        self.legacy_preparation = prepared
        return composition

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
