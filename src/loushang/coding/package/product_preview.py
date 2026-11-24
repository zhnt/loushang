"""Inert Coding Product evidence for an already fenced Package namespace."""

from __future__ import annotations

import time as time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import TracebackType

from loushang.coding.composition.base_plugin import (
    CodingBasePluginAssemblyError as CodingBasePluginAssemblyError,
)
from loushang.coding.composition.base_product import (
    CodingBaseProductCompilation as CodingBaseProductCompilation,
)
from loushang.coding.composition.base_product import (
    compile_coding_base_product_selection as compile_coding_base_product_selection,
)
from loushang.coding.composition.base_product import (
    extend_coding_base_product_data_resources as extend_coding_base_product_data_resources,
)
from loushang.coding.composition.external_data import (
    CodingExternalDataProductCompilation as CodingExternalDataProductCompilation,
)
from loushang.coding.composition.external_data import (
    compile_coding_external_data_product_selection as compile_coding_external_data_product_selection,
)
from loushang.coding.composition.external_data import (
    compile_coding_selected_data_resources,
)
from loushang.coding.composition.sets import (
    resolve_coding_composition_set as resolve_coding_composition_set,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.coding.plugin_manager.lifecycle import (
    _workspace_scope_id as _workspace_scope_id,
)
from loushang.coding.resources.catalog import (
    CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY as CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY,
)
from loushang.coding.resources.catalog import (
    CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY as CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY,
)
from loushang.coding.resources.catalog import prepare_coding_catalog_projection
from loushang.coding.resources.runtime import (
    CodingResourceLoader as CodingResourceLoader,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionError as ProductCompositionError,
)
from loushang.harness.environment.probe import (
    LocalHostEnvironmentProbe as LocalHostEnvironmentProbe,
)
from loushang.harness.package_product._application_runtime import (
    open_fenced_product_manifest_reader,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs as PosixLocalWheelProductHostInputs,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    _LocalWheelSelectedManifestReader,
)
from loushang.harness.package_product.product_worker_candidate import (
    WorkerPackageCandidateV1,
    read_selected_worker_candidate,
)
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentCompositionPreviewV1,
    PluginCurrentResourceAdmissionV1,
    _InstalledResourceCompilation,
    preview_fenced_product_resources,
)
from loushang.harness.plugin_management.current_preview import (
    project_current_product_resource_facts as project_current_product_resource_facts,
)
from loushang.harness.plugin_management.current_preview import (
    project_current_product_resource_selections as project_current_product_resource_selections,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.resource_catalog.bootstrap_projection import (
    ResourceCatalogBootstrapResult,
)
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)

from .builtin_wheel import (
    coding_builtin_product_local_wheel_policy as coding_builtin_product_local_wheel_policy,
)
from .builtin_wheel import (
    inspect_posix_coding_base_product_wheel as inspect_posix_coding_base_product_wheel,
)
from .builtin_wheel import (
    inspect_posix_coding_capability_product_wheels as inspect_posix_coding_capability_product_wheels,
)
from .epoch_layout import (
    resolve_coding_package_epoch_layout as resolve_coding_package_epoch_layout,
)
from .product_runtime import _compose_coding_product_source_policy
from .product_worker_opt_in import CodingWorkerOptInDecisionV1, CodingWorkerOptInJournal

CodingDataResourceAdmissionPreviewV1 = PluginCurrentResourceAdmissionV1
CodingCurrentDataResourcePreviewV1 = PluginCurrentCompositionPreviewV1


_RESOURCE_PREVIEW_MAX_FILES = 64
_RESOURCE_PREVIEW_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerCandidateReadEvidenceV1:
    """Selected candidate identity observed without a Worker-use decision."""

    candidate: WorkerPackageCandidateV1
    artifact_digest: str
    native_platform: str


@dataclass(slots=True)
class CodingFencedProductReadOnlyPreviewOwner:
    """Hold the existing Product epoch while inspecting exact selected bytes."""

    epoch_runtime: PackageProductPosixFencedRuntimeOwner
    policy: PackageProductLocalWheelPolicy
    selected_manifests: _LocalWheelSelectedManifestReader
    gc_gate: PluginPackageGcReservationJournal
    worker_candidates: bool = False

    def selected_worker_candidate(self, plugin_id: str) -> WorkerPackageCandidateV1:
        """Verify inert bytes of one currently selected Worker; grant no execution."""

        return self.selected_worker_candidate_evidence(plugin_id).candidate

    def selected_worker_candidate_evidence(
        self, plugin_id: str
    ) -> CodingWorkerCandidateReadEvidenceV1:
        """Preserve the Product-selected artifact and native profile identity."""

        if not self.worker_candidates:
            raise PermissionError("Worker candidate read was not selected")
        candidate, artifact_digest, native_platform = read_selected_worker_candidate(
            self.epoch_runtime,
            self.selected_manifests,
            self.policy,
            plugin_id,
        )
        return CodingWorkerCandidateReadEvidenceV1(
            candidate=candidate,
            artifact_digest=artifact_digest,
            native_platform=native_platform,
        )

    def worker_opt_in_decision(
        self, plugin_id: str
    ) -> CodingWorkerOptInDecisionV1 | None:
        """Read one existing Worker decision without conferring selection or use."""

        self.epoch_runtime.assert_current()
        decision = CodingWorkerOptInJournal(
            self.epoch_runtime.control_root / "product-state/worker-opt-in.jsonl",
            scope_id=self.policy.project_scope_id,
            gc_gate=self.gc_gate,
            store_id=self.epoch_runtime.registry.store_id,
        ).current_read_only(plugin_id)
        self.epoch_runtime.assert_current()
        return decision

    def preview_current_data_resources(
        self,
        *,
        workspace: Path,
        composition_set_id: str = "coding-standard",
        disabled_skills: tuple[str, ...] | None = None,
    ) -> CodingCurrentDataResourcePreviewV1:
        """Compile installed data under Product policy without live activation."""

        self.epoch_runtime.assert_current()
        if (
            not isinstance(workspace, Path)
            or not workspace.is_absolute()
            or workspace != workspace.resolve(strict=True)
            or self.policy.project_scope_id != _workspace_scope_id(workspace)
        ):
            raise ValueError("Coding Product preview workspace scope changed")
        composition_set = resolve_coding_composition_set(composition_set_id)
        if disabled_skills is not None and any(
            not isinstance(item, str) or not item for item in disabled_skills
        ):
            raise ValueError("Coding Product preview disabled Skills are invalid")

        def prepare_catalog(
            compiled: _InstalledResourceCompilation | None, evaluated_at: int
        ) -> tuple[
            ResourceCatalogBootstrapResult, tuple[ProductSelectedResourceInput, ...]
        ]:
            loader = CodingResourceLoader(workspace_root=workspace)
            receipt = loader.prepare_catalog_input_receipt(workspace)
            inputs = compiled.product_resource_inputs() if compiled is not None else ()
            _, result = prepare_coding_catalog_projection(
                receipt,
                product_id=self.policy.product_id,
                session_id="plugin-preview-current",
                cwd=workspace,
                product_composition=compiled.product_composition
                if compiled is not None
                else None,
                product_snapshot_resources=inputs if compiled is not None else None,
                admission_now=evaluated_at,
                disabled_skills=disabled_skills or (),
                source_policy=(
                    CODING_PRODUCT_BASE_DISABLED_RESOURCE_CATALOG_SOURCE_POLICY
                    if compiled is None
                    else CODING_STANDARD_RESOURCE_CATALOG_SOURCE_POLICY
                ),
            )
            return result, inputs

        return preview_fenced_product_resources(
            self.epoch_runtime,
            self.policy,
            self.selected_manifests,
            base_plugin_id="coding.base",
            composition_set_id=composition_set.set_id,
            requested_plugin_ids=tuple(
                item.plugin_id for item in composition_set.plugin_requests
            ),
            disabled_skills_known=disabled_skills is not None,
            executable_trust_classes=frozenset(
                {"host-equivalent-local", "legacy-local-reacquired"}
            ),
            max_files=_RESOURCE_PREVIEW_MAX_FILES,
            max_total_bytes=_RESOURCE_PREVIEW_MAX_BYTES,
            evaluation_clock=time.time,
            observe_clock=time.time_ns,
            compile_base=lambda base, evaluated_at: (
                compile_coding_base_product_selection(
                    base,
                    composition_set,
                    installation_key=base.snapshot.installation_key,
                    session_id="plugin-preview-current",
                    host_environment=LocalHostEnvironmentProbe().detect(),
                    evaluated_at=evaluated_at,
                )
            ),
            compile_data=partial(
                compile_coding_selected_data_resources,
                composition_set=composition_set,
                session_id="plugin-preview-current",
            ),
            prepare_catalog=prepare_catalog,
            base_missing=lambda: CodingBasePluginAssemblyError(
                "Coding Product base Plugin is not installed",
                code="product_requested_base_not_installed",
            ),
            composition_errors=(CodingBasePluginAssemblyError, ProductCompositionError),
        )

    @classmethod
    def open(
        cls,
        layout: CodingPluginLifecycleStateLayout,
        *,
        workspace_guard: Callable[[], None] | None = None,
        worker_candidates: bool = False,
    ) -> CodingFencedProductReadOnlyPreviewOwner:
        if workspace_guard is not None:
            workspace_guard()
        if not isinstance(layout, CodingPluginLifecycleStateLayout):
            raise TypeError("Coding Plugin lifecycle layout is required")
        epoch = resolve_coding_package_epoch_layout(layout)
        with open_fenced_product_manifest_reader(
            epoch.fenced_runtime_open_kwargs(),
            epoch=epoch,
            scope_id=layout.scope_id,
            identity_prefix="coding-product",
            product_label="Coding",
            workspace_guard=workspace_guard,
            read_source_policy=lambda runtime, roots: _compose_coding_product_source_policy(
                layout,
                runtime,
                roots,
                include_worker_candidates=worker_candidates,
                read_only=True,
            )[0],
        ) as (runtime, policy, selected_manifests, gc_gate):
            return cls(
                epoch_runtime=runtime,
                policy=policy,
                selected_manifests=selected_manifests,
                gc_gate=gc_gate,
                worker_candidates=worker_candidates,
            )

    def close(self) -> None:
        self.epoch_runtime.close()

    def __enter__(self) -> CodingFencedProductReadOnlyPreviewOwner:
        self.epoch_runtime.assert_current()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()


__all__ = [
    "CodingCurrentDataResourcePreviewV1",
    "CodingDataResourceAdmissionPreviewV1",
    "CodingFencedProductReadOnlyPreviewOwner",
    "CodingWorkerCandidateReadEvidenceV1",
]
