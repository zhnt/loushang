"""Inert Coding Product evidence for an already fenced Package namespace."""

from __future__ import annotations

import os as os
import stat as stat
import time as time
from collections.abc import Callable
from dataclasses import dataclass
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
from loushang.coding.composition.sets import (
    resolve_coding_composition_set as resolve_coding_composition_set,
)
from loushang.coding.harness.package_product import preview as _programs
from loushang.coding.harness.package_product import (
    resource_preview as _resource_preview_programs,
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
from loushang.coding.resources.catalog import (
    build_coding_initial_resource_catalog_adapter as build_coding_initial_resource_catalog_adapter,
)
from loushang.coding.resources.runtime import (
    CodingResourceLoader as CodingResourceLoader,
)
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionError as ProductCompositionError,
)
from loushang.harness.environment.probe import (
    LocalHostEnvironmentProbe as LocalHostEnvironmentProbe,
)
from loushang.harness.journal import JournalLoadPolicy as JournalLoadPolicy
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductHostInputs as PosixLocalWheelProductHostInputs,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    _LocalWheelSelectedManifestReader,
)
from loushang.harness.package_product.product_worker_candidate import (
    WorkerPackageCandidateV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate as verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management.assembly import (
    bind_plugin_desired_state as bind_plugin_desired_state,
)
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentCompositionPreviewV1,
    PluginCurrentResourceAdmissionV1,
)
from loushang.harness.plugin_management.current_preview import (
    project_current_product_resource_facts as project_current_product_resource_facts,
)
from loushang.harness.plugin_management.current_preview import (
    project_current_product_resource_selections as project_current_product_resource_selections,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.package_gc_binding import (
    PluginPackageGcBindingJournal as PluginPackageGcBindingJournal,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductSelectedRootReader as PackageProductSelectedRootReader,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1 as PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.committed_sets import (
    PackageCommittedSetJournal as PackageCommittedSetJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_materialization import (
    PosixPackagePluginRootReadOnlyStore as PosixPackagePluginRootReadOnlyStore,
)
from loushang.harness.resources.packages.plugin_lifecycle.store_settlements import (
    PackageStoreSettlementJournal as PackageStoreSettlementJournal,
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
from .external_data_wheel import (
    CodingExternalDataWheelCatalog as CodingExternalDataWheelCatalog,
)
from .external_dependency_wheel import (
    CodingExternalDependencyWheelCatalog as CodingExternalDependencyWheelCatalog,
)
from .external_worker_wheel import (
    CodingExternalWorkerWheelCatalog as CodingExternalWorkerWheelCatalog,
)
from .legacy_binding_catalog import (
    CodingLegacyLocalBindingCatalog as CodingLegacyLocalBindingCatalog,
)
from .legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance as reopen_coding_legacy_installed_local_acceptance,
)
from .product_worker_opt_in import CodingWorkerOptInDecisionV1, CodingWorkerOptInJournal

CodingDataResourceAdmissionPreviewV1 = PluginCurrentResourceAdmissionV1
CodingCurrentDataResourcePreviewV1 = PluginCurrentCompositionPreviewV1


_RUNTIME_PROGRAM_VALUES = {
    "value_001": "coding-product-root-store:",
    "value_002": "Coding Plugin lifecycle layout is required",
    "value_003": "Coding Package Product root is not fenced",
    "value_004": "coding-product-package-policy:1",
    "value_005": "coding-product-package-quota:1",
    "value_006": "coding-product-local-source",
    "value_007": "gc-reservations.jsonl",
    "value_008": "desired-state.jsonl",
    "value_009": "root-settlements.jsonl",
    "value_010": "legacy-local-bindings.jsonl",
    "value_011": "external-data-wheel-bindings.jsonl",
    "value_012": "external-dependency-wheel-bindings.jsonl",
    "value_013": "gc-bindings.jsonl",
    "value_014": "committed-sets.jsonl",
    "value_015": "external-worker-wheel-bindings.jsonl",
    "value_016": "Worker candidate read was not selected",
    "value_017": "Selected Worker Product binding is unavailable",
    "value_018": "Selected Worker Product owner changed",
    "private_state_unsafe": "Fenced Product state root is unsafe",
}


_RESOURCE_PREVIEW_MAX_FILES = 64
_RESOURCE_PREVIEW_MAX_BYTES = 1024 * 1024


_RESOURCE_PREVIEW_PROGRAM_VALUES = {
    "value_001": "Coding Product preview workspace scope changed",
    "value_002": "Coding Product preview disabled Skills are invalid",
    "value_003": "coding.base",
    "value_004": "plugin-preview-current",
    "value_005": "Coding Product base Plugin is not installed",
    "value_006": "product_requested_base_not_installed",
}


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

        return _programs.worker_candidate_evidence(self, plugin_id)

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

        return _resource_preview_programs.preview_current_resources(
            self,
            workspace=workspace,
            composition_set_id=composition_set_id,
            disabled_skills=disabled_skills,
        )

    @classmethod
    def open(
        cls,
        layout: CodingPluginLifecycleStateLayout,
        *,
        workspace_guard: Callable[[], None] | None = None,
        worker_candidates: bool = False,
    ) -> CodingFencedProductReadOnlyPreviewOwner:
        return _programs.open_preview(
            cls,
            layout,
            workspace_guard=workspace_guard,
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


def _selection_evidence(
    policy: PackageProductLocalWheelPolicy,
    desired_snapshot: PluginDesiredStateSnapshotV1,
    requested_plugin_ids: tuple[str, ...],
) -> tuple[set[str], set[str]]:
    if not isinstance(desired_snapshot, PluginDesiredStateSnapshotV1):
        raise TypeError("Product preview Desired State snapshot is required")
    desired_selected_ids = {
        item.installation_key.plugin_id
        for item in desired_snapshot.installations
        if item.installation_key.product_id == policy.product_id
        and item.installation_key.scope_id == policy.project_scope_id
        and item.selection.desired_state == "installed_enabled"
    }
    selected_ids = desired_selected_ids & set(requested_plugin_ids)
    binding_ids = {item.plugin_id for item in policy.bindings}
    executable = {
        item.plugin_id
        for item in policy.bindings
        if item.plugin_id in selected_ids
        and item.source_trust_class
        in {"host-equivalent-local", "legacy-local-reacquired"}
        and item.plugin_id != "coding.base"
    }
    gaps = {
        "disabled_skill_settings",
        "session_invocation_options",
        "exact_catalog_generation",
    }
    if desired_selected_ids - binding_ids:
        gaps.add("product_binding_for_selected_plugin")
    if executable:
        gaps.add("capability_authorized_preflight")
    return executable, gaps


__all__ = [
    "CodingCurrentDataResourcePreviewV1",
    "CodingDataResourceAdmissionPreviewV1",
    "CodingFencedProductReadOnlyPreviewOwner",
    "CodingWorkerCandidateReadEvidenceV1",
]
